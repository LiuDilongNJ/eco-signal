from contextlib import contextmanager
from types import SimpleNamespace

import pytest

from app.core import observability
from app.core.config import settings


def test_init_sentry_skips_when_disabled(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(settings, "SENTRY_ENABLED", False)
    monkeypatch.setattr(settings, "SENTRY_DSN", "https://examplePublicKey@o0.ingest.sentry.io/0")

    assert observability.init_sentry("api") is False


def test_init_sentry_skips_when_dsn_missing(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(settings, "SENTRY_ENABLED", True)
    monkeypatch.setattr(settings, "SENTRY_DSN", None)

    assert observability.init_sentry("api") is False


def test_init_sentry_passes_configurable_options(monkeypatch: pytest.MonkeyPatch) -> None:
    init_calls: list[dict] = []
    captured_tags: list[tuple[str, str]] = []

    monkeypatch.setattr(settings, "SENTRY_ENABLED", True)
    monkeypatch.setattr(settings, "SENTRY_DSN", "https://examplePublicKey@o0.ingest.sentry.io/0")
    monkeypatch.setattr(settings, "SENTRY_ENABLE_IN_LOCAL", True)
    monkeypatch.setattr(settings, "ENVIRONMENT", "local")
    monkeypatch.setattr(settings, "APP_VERSION", "1.2.3")
    monkeypatch.setattr(settings, "SENTRY_TRACES_SAMPLE_RATE", 1.0)
    monkeypatch.setattr(settings, "SENTRY_SEND_DEFAULT_PII", True)
    monkeypatch.setattr(settings, "SENTRY_ENABLE_LOGS", True)
    monkeypatch.setattr(settings, "SENTRY_PROFILE_SESSION_SAMPLE_RATE", 1.0)
    monkeypatch.setattr(settings, "SENTRY_PROFILE_LIFECYCLE", "trace")
    monkeypatch.setattr(
        observability.sentry_sdk,
        "Hub",
        SimpleNamespace(current=SimpleNamespace(client=None)),
    )
    monkeypatch.setattr(observability.sentry_sdk, "init", lambda **kwargs: init_calls.append(kwargs))
    monkeypatch.setattr(
        observability.sentry_sdk,
        "set_tag",
        lambda key, value: captured_tags.append((key, value)),
    )

    assert observability.init_sentry("worker") is True

    assert len(init_calls) == 1
    init_kwargs = init_calls[0]
    assert init_kwargs["dsn"] == "https://examplePublicKey@o0.ingest.sentry.io/0"
    assert init_kwargs["environment"] == "local"
    assert init_kwargs["release"] == "1.2.3"
    assert init_kwargs["enable_tracing"] is True
    assert init_kwargs["traces_sample_rate"] == 1.0
    assert init_kwargs["send_default_pii"] is True
    assert init_kwargs["enable_logs"] is True
    assert init_kwargs["profile_session_sample_rate"] == 1.0
    assert init_kwargs["profile_lifecycle"] == "trace"
    assert init_kwargs["before_send"] is observability._sentry_before_send
    assert captured_tags == [("service", "worker")]


def test_sentry_before_send_masks_sensitive_fields() -> None:
    event = {
        "request": {
            "headers": {
                "authorization": "Bearer token",
                "cookie": "session=secret",
            }
        },
        "extra": {
            "password": "secret",
            "nested": [{"refresh_token": "token"}, {"safe": "value"}],
        },
    }

    sanitized = observability._sentry_before_send(event, {})

    assert sanitized["request"]["headers"]["authorization"] == "***"
    assert sanitized["request"]["headers"]["cookie"] == "***"
    assert sanitized["extra"]["password"] == "***"
    assert sanitized["extra"]["nested"][0]["refresh_token"] == "***"
    assert sanitized["extra"]["nested"][1]["safe"] == "value"


def test_sentry_request_scope_binds_request_id(monkeypatch: pytest.MonkeyPatch) -> None:
    recorded: list[tuple[str, str, str]] = []

    class _Scope:
        def set_tag(self, key: str, value: str) -> None:
            recorded.append(("tag", key, value))

        def set_extra(self, key: str, value: str) -> None:
            recorded.append(("extra", key, value))

    @contextmanager
    def _new_scope():
        yield _Scope()

    monkeypatch.setattr(observability.sentry_sdk, "new_scope", _new_scope)

    with observability.sentry_request_scope("req_test_123"):
        pass

    assert ("tag", "request_id", "req_test_123") in recorded
    assert ("extra", "request_id", "req_test_123") in recorded
