"""실제 환경 파일 없이 운영 설정 검증과 오류의 비밀값 비노출을 확인한다."""

import pytest
from pydantic import ValidationError

from app.config import Settings


VALID_SECRET = "fake-session-secret-" + "x" * 12
DATABASE_PASSWORD = "fake-database-password"
DATABASE_URL = f"postgresql+psycopg2://fake-user:{DATABASE_PASSWORD}@db/fake-db"
OPENAI_KEY = "fake-openai-api-key"


@pytest.fixture
def production_environment(monkeypatch):
    """Compose가 전달하는 환경변수를 가짜 값으로 구성한다."""
    values = {
        "FMH_ENVIRONMENT": "production",
        "FMH_DATABASE_URL": DATABASE_URL,
        "FMH_SESSION_SECRET": VALID_SECRET,
        "FMH_COOKIE_SECURE": "true",
        "FMH_OPENAI_API_KEY": OPENAI_KEY,
    }
    for key, value in values.items():
        monkeypatch.setenv(key, value)


def assert_sanitized(error, *extra_secrets):
    message = str(error)
    for value in (DATABASE_URL, DATABASE_PASSWORD, OPENAI_KEY, VALID_SECRET, *extra_secrets):
        if value:
            assert value not in message
    assert "input_value" not in message


@pytest.mark.parametrize("secret, expected_message", [
    (
        "replace_with_an_independent_random_secret_at_least_32_chars",
        "운영 FMH_SESSION_SECRET의 예시값을 실제 무작위 비밀값으로 변경하세요.",
    ),
    (
        "development-only-change-this-secret",
        "운영 FMH_SESSION_SECRET의 예시값을 실제 무작위 비밀값으로 변경하세요.",
    ),
    ("fake-short-secret", "운영 FMH_SESSION_SECRET은 32자 이상이어야 합니다."),
    ("x" * 31, "운영 FMH_SESSION_SECRET은 32자 이상이어야 합니다."),
    ("", "운영 FMH_SESSION_SECRET은 32자 이상이어야 합니다."),
])
def test_production_secret_errors_are_actionable_and_hide_environment_values(
    production_environment, monkeypatch, secret, expected_message,
):
    monkeypatch.setenv("FMH_SESSION_SECRET", secret)

    with pytest.raises(ValidationError) as error:
        Settings()

    assert expected_message in str(error.value)
    assert_sanitized(error.value, secret)


def test_production_accepts_a_non_placeholder_secret_of_exactly_32_characters(
    production_environment,
):
    assert len(VALID_SECRET) == 32

    settings = Settings()

    assert settings.environment == "production"
    assert settings.session_secret.get_secret_value() == VALID_SECRET
    assert settings.database_url.get_secret_value() == DATABASE_URL
    assert settings.cookie_secure is True


@pytest.mark.parametrize("key, value, expected_message", [
    ("FMH_COOKIE_SECURE", "false", "운영 세션 쿠키에는 Secure가 필요합니다."),
    ("FMH_DATABASE_URL", "sqlite:///fake-config-test.db", "운영 환경은 PostgreSQL을 사용해야 합니다."),
])
def test_other_production_validation_errors_hide_environment_values(
    production_environment, monkeypatch, key, value, expected_message,
):
    monkeypatch.setenv(key, value)

    with pytest.raises(ValidationError) as error:
        Settings()

    assert expected_message in str(error.value)
    assert_sanitized(error.value)


def test_field_validation_errors_hide_invalid_input(production_environment, monkeypatch):
    invalid_value = "fake-private-invalid-session-hours"
    monkeypatch.setenv("FMH_SESSION_HOURS", invalid_value)

    with pytest.raises(ValidationError) as error:
        Settings()

    assert "session_hours" in str(error.value)
    assert_sanitized(error.value, invalid_value)


def test_development_still_accepts_the_default_secret(production_environment, monkeypatch):
    monkeypatch.setenv("FMH_ENVIRONMENT", "development")
    monkeypatch.delenv("FMH_SESSION_SECRET")
    monkeypatch.setenv("FMH_COOKIE_SECURE", "false")
    monkeypatch.setenv("FMH_DATABASE_URL", "sqlite:///fake-config-test.db")

    settings = Settings()

    assert settings.session_secret.get_secret_value() == "development-only-change-this-secret"
    assert settings.cookie_secure is False
