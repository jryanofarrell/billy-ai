from types import SimpleNamespace

import pytest

from parts_parser.web.session import BrowserSession, WebError


class _FakeResponse:
    def __init__(self, status: int, payload: dict | None = None) -> None:
        self.status = status
        self._payload = payload

    def json(self) -> dict:
        if self._payload is None:
            raise ValueError("not json")
        return self._payload


class _FakeRequest:
    """Yields one scripted outcome per get(); an Exception instance is raised."""

    def __init__(self, outcomes: list) -> None:
        self._outcomes = list(outcomes)
        self.calls = 0

    def get(self, url: str):
        self.calls += 1
        outcome = self._outcomes.pop(0)
        if isinstance(outcome, Exception):
            raise outcome
        return outcome


def _session_with(outcomes: list, monkeypatch) -> tuple[BrowserSession, _FakeRequest]:
    monkeypatch.setattr("parts_parser.web.session.time.sleep", lambda s: None)
    session = BrowserSession(min_request_interval=0)
    fake = _FakeRequest(outcomes)
    session._context = SimpleNamespace(request=fake)
    return session, fake


def test_get_json_retries_transport_failures_then_succeeds(monkeypatch):
    session, fake = _session_with(
        [TimeoutError("hang"), OSError("dropped"), _FakeResponse(200, {"ok": 1})],
        monkeypatch,
    )
    assert session.get_json("https://x.com/api") == {"ok": 1}
    assert fake.calls == 3


def test_get_json_retries_server_errors_then_raises(monkeypatch):
    session, fake = _session_with(
        [_FakeResponse(503), _FakeResponse(503), _FakeResponse(503)], monkeypatch
    )
    with pytest.raises(WebError, match="HTTP 503"):
        session.get_json("https://x.com/api")
    assert fake.calls == 3


def test_get_json_does_not_retry_deterministic_errors(monkeypatch):
    session, fake = _session_with([_FakeResponse(404)], monkeypatch)
    with pytest.raises(WebError, match="HTTP 404"):
        session.get_json("https://x.com/api")
    assert fake.calls == 1


def test_get_json_bad_json_raises_without_retry(monkeypatch):
    session, fake = _session_with([_FakeResponse(200, payload=None)], monkeypatch)
    with pytest.raises(WebError, match="unexpected response"):
        session.get_json("https://x.com/api")
    assert fake.calls == 1
