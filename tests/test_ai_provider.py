"""실제 SDK의 요청·함수 결과 처리를 외부 통신 없이 확인한다."""

import base64
import json

import httpx
import pytest
from openai import OpenAI

from app import ai_provider
from app.config import Settings
from app.errors import DomainError


def tool_call(arguments='{"summary": null}', **overrides):
    return {
        "id": "fc_test", "call_id": "call_test", "type": "function_call",
        "name": "submit_repair_assistance", "status": "completed",
        "arguments": arguments,
    } | overrides


def mock_completion(monkeypatch, output, status="completed"):
    requests = []

    def respond(request):
        requests.append(request)
        return httpx.Response(200, json={
            "id": "resp_test", "object": "response", "created_at": 0,
            "status": status, "output": output,
        })

    def client_with_mock_transport(**kwargs):
        return OpenAI(**kwargs, http_client=httpx.Client(transport=httpx.MockTransport(respond)))

    monkeypatch.setattr(ai_provider, "OpenAI", client_with_mock_transport)
    return requests


@pytest.fixture
def ai_settings():
    return Settings(
        environment="test", openai_api_key="fake-test-key", openai_model="fake-test-model",
        openai_base_url="https://ai.example.test/v1",
    )


@pytest.mark.parametrize("base_url, expected_url", [
    (None, "https://api.openai.com/v1/responses"),
    ("", "https://api.openai.com/v1/responses"),
    ("   ", "https://api.openai.com/v1/responses"),
    ("https://ai.example.test/v1", "https://ai.example.test/v1/responses"),
    (" https://ai.example.test/tenant/v1/ ", "https://ai.example.test/tenant/v1/responses"),
])
def test_generate_uses_configured_base_url(monkeypatch, base_url, expected_url):
    monkeypatch.delenv("OPENAI_BASE_URL", raising=False)
    if base_url is None:
        monkeypatch.delenv("FMH_OPENAI_BASE_URL", raising=False)
    else:
        monkeypatch.setenv("FMH_OPENAI_BASE_URL", base_url)

    settings = Settings(
        environment="development",
        openai_api_key="fake-test-key",
        openai_model="fake-test-model",
    )
    output = {"summary": None}
    requests = mock_completion(monkeypatch, [tool_call(json.dumps(output))])

    assert ai_provider.generate(settings, {"type": "DIAGNOSIS"}, [], timeout=10) == output
    assert len(requests) == 1
    assert requests[0].method == "POST"
    assert str(requests[0].url) == expected_url
    assert requests[0].headers["authorization"] == "Bearer fake-test-key"


@pytest.mark.parametrize("job_type", ["DIAGNOSIS", "CASE_MATCHING"])
def test_schema_and_photos_reach_the_function_request(monkeypatch, ai_settings, job_type):
    """SDK가 함수 스키마와 기존 사진 입력을 함께 전송하는지 확인한다."""
    requests = mock_completion(monkeypatch, [
        {"id": "rs_test", "type": "reasoning", "summary": []},
        tool_call(),
    ])
    photo = {"photoId": "test-photo", "bytes": b"synthetic-photo-bytes"}
    result = ai_provider.generate(ai_settings, {"type": job_type}, [photo], timeout=10)
    assert result == {"summary": None}
    assert len(requests) == 1
    body = json.loads(requests[0].content)
    assert "text" not in body
    assert body["reasoning"] == {"effort": "low"}
    assert body["store"] is False
    assert body["parallel_tool_calls"] is False
    assert body["tool_choice"] == {"type": "function", "name": "submit_repair_assistance"}
    assert len(body["tools"]) == 1
    tool = body["tools"][0]
    assert tool["name"] == body["tool_choice"]["name"]
    assert tool["type"] == "function" and tool["strict"] is True
    assert tool["parameters"]["type"] == "object"
    assert tool["parameters"]["additionalProperties"] is False
    assert "summary" in tool["parameters"]["required"]
    content = body["input"][0]["content"]
    assert json.loads(content[0]["text"]) == {"type": job_type}
    assert content[1]["text"] == "photoId=test-photo"
    assert content[2] == {
        "type": "input_image",
        "image_url": "data:image/jpeg;base64," + base64.b64encode(photo["bytes"]).decode(),
    }


def test_portfolio_analysis_uses_the_image_and_returns_observation_text(monkeypatch, ai_settings):
    response = {"observations": [{"photoId": "portfolio-photo", "text": "  문 하단 금속 레일  "}]}
    requests = mock_completion(monkeypatch, [
        tool_call(json.dumps(response), name="submit_portfolio_observations"),
    ])
    photo = {"photoId": "portfolio-photo", "bytes": b"portfolio-image"}

    assert ai_provider.describe_portfolio(ai_settings, [photo], timeout=10) == {
        "portfolio-photo": "문 하단 금속 레일",
    }

    body = json.loads(requests[0].content)
    assert body["reasoning"] == {"effort": "low"}
    assert body["tool_choice"]["name"] == "submit_portfolio_observations"
    content = body["input"][0]["content"]
    assert content[1]["text"] == "photoId=portfolio-photo"
    assert content[2]["image_url"].endswith(base64.b64encode(photo["bytes"]).decode())


def test_portfolio_analysis_rejects_observations_for_another_photo(monkeypatch, ai_settings):
    response = {"observations": [{"photoId": "another-photo", "text": "금속 레일"}]}
    mock_completion(monkeypatch, [tool_call(json.dumps(response), name="submit_portfolio_observations")])
    photo = {"photoId": "portfolio-photo", "bytes": b"portfolio-image"}

    with pytest.raises(DomainError) as failure:
        ai_provider.describe_portfolio(ai_settings, [photo], timeout=10)
    assert failure.value.code == "AI_INVALID_OUTPUT"


@pytest.mark.parametrize("arguments", [
    '```json\n{"summary": null}\n```',
    '{"summary": null, "summary": null}',
    '{"summary":',
    '{"confidence": NaN}',
    'private-provider-response',
])
def test_invalid_provider_json_is_an_ai_output_error(monkeypatch, ai_settings, arguments):
    """모델의 잘못된 출력을 사용자 HTTP 요청 오류로 보고하지 않는다."""
    requests = mock_completion(monkeypatch, [tool_call(arguments)])
    with pytest.raises(DomainError) as failure:
        ai_provider.generate(ai_settings, {"type": "DIAGNOSIS"}, [], timeout=10)
    assert failure.value.code == "AI_INVALID_OUTPUT"
    assert not failure.value.retryable
    assert arguments not in json.dumps(failure.value.body(), ensure_ascii=False)
    assert len(requests) == 1


@pytest.mark.parametrize("output,status", [
    ([], "completed"),
    (None, "completed"),
    ([tool_call()], "incomplete"),
    ([tool_call(status="incomplete")], "completed"),
    ([tool_call(name="unexpected_tool")], "completed"),
    ([tool_call(), tool_call(call_id="second_call")], "completed"),
    ([tool_call(arguments=None)], "completed"),
    ([tool_call(arguments=" ")], "completed"),
    ([{
        "id": "msg_test", "type": "message", "role": "assistant", "status": "completed",
        "content": [{"type": "output_text", "text": '{"summary":null}', "annotations": []}],
    }], "completed"),
])
def test_missing_or_ambiguous_function_result_is_rejected(monkeypatch, ai_settings, output, status):
    """함수 결과가 없으면 일반 텍스트나 여러 호출 중 하나로 대신 성공시키지 않는다."""
    requests = mock_completion(monkeypatch, output, status)
    with pytest.raises(DomainError) as failure:
        ai_provider.generate(ai_settings, {"type": "DIAGNOSIS"}, [], timeout=10)
    assert failure.value.code == "AI_INVALID_OUTPUT"
    assert not failure.value.retryable
    assert len(requests) == 1


def test_optional_function_status_can_be_absent(monkeypatch, ai_settings):
    call = tool_call()
    del call["status"]
    mock_completion(monkeypatch, [call])
    assert ai_provider.generate(ai_settings, {"type": "DIAGNOSIS"}, [], timeout=10) == {"summary": None}
