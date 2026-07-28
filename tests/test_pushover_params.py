"""Tests for optional Pushover parameters (priority/title/sound)."""
import http.client


class _FakeResponse:
    status = 200

    def read(self):
        return b'{"status":1}'


class _FakeConn:
    last_body = None

    def __init__(self, *args, **kwargs):
        pass

    def request(self, method, path, body, headers):
        _FakeConn.last_body = body

    def getresponse(self):
        return _FakeResponse()

    def close(self):
        pass


def _patch(monkeypatch):
    _FakeConn.last_body = None
    monkeypatch.setenv("PUSHOVER_TAPO_API_TOKEN", "tok")
    monkeypatch.setattr(http.client, "HTTPSConnection", _FakeConn)


def test_priority_and_sound_included_when_set(monkeypatch):
    _patch(monkeypatch)
    from utils import send_pushover_notification_new

    ok = send_pushover_notification_new("user1", "hi", priority=1, sound="siren")

    assert ok is True
    assert "priority=1" in _FakeConn.last_body
    assert "sound=siren" in _FakeConn.last_body


def test_optional_params_omitted_by_default(monkeypatch):
    _patch(monkeypatch)
    from utils import send_pushover_notification_new

    send_pushover_notification_new("user1", "hi")

    assert "priority=" not in _FakeConn.last_body
    assert "sound=" not in _FakeConn.last_body
    assert "title=" not in _FakeConn.last_body
