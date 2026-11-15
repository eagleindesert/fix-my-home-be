"""실제 SDK의 요청 주소를 외부 통신 없이 확인한다."""

import json

import httpx
import pytest
from openai import OpenAI

from app import ai_provider
from app.config import Settings


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
    requests = []
    output = {"summary": None}

    def respond(request):
        requests.append(request)
        return httpx.Response(200, json={
            "id": "resp_test",
            "object": "response",
            "created_at": 0,
            "status": "completed",
            "output": [{
                "id": "msg_test",
                "type": "message",
                "role": "assistant",
                "status": "completed",
                "content": [{
                    "type": "output_text",
                    "text": json.dumps(output),
                    "annotations": [],
                }],
            }],
        })

    def client_with_mock_transport(**kwargs):
        return OpenAI(
            **kwargs,
            http_client=httpx.Client(transport=httpx.MockTransport(respond)),
        )

    monkeypatch.setattr(ai_provider, "OpenAI", client_with_mock_transport)

    assert ai_provider.generate(settings, {"type": "DIAGNOSIS"}, [], timeout=10) == output
    assert len(requests) == 1
    assert requests[0].method == "POST"
    assert str(requests[0].url) == expected_url
    assert requests[0].headers["authorization"] == "Bearer fake-test-key"
