"""Router tests. No network: the upstream client is a mocked httpx transport."""
import httpx
import pytest

from redfox_router import classifier, engine
from redfox_router.config import BACKENDS, LOGICAL_MODELS
from redfox_router.store import RouterStore


@pytest.fixture
def store(tmp_path):
    return RouterStore(tmp_path / "router.db")


@pytest.fixture(autouse=True)
def fake_keys(monkeypatch):
    for b in BACKENDS.values():
        monkeypatch.setattr(b, "api_key", lambda: "test-key")


def test_classifier_status():
    assert classifier.classify_status(200) == classifier.OK
    assert classifier.classify_status(401) == classifier.AUTH
    assert classifier.classify_status(403) == classifier.AUTH
    assert classifier.classify_status(429) == classifier.RATE_LIMIT
    assert classifier.classify_status(402) == classifier.QUOTA_EXHAUSTED
    assert classifier.classify_status(404) == classifier.MODEL_UNAVAILABLE
    assert classifier.classify_status(503) == classifier.UPSTREAM_5XX
    assert classifier.classify_status(400) == classifier.INVALID_REQUEST
    assert classifier.should_failover(classifier.RATE_LIMIT)
    assert not classifier.should_failover(classifier.INVALID_REQUEST)


def test_unknown_logical_model(store):
    status, body, _ = engine.chat("nope", {"messages": []}, store)
    assert status == 404
    assert body["error"]["code"] == "model_not_found"


def test_failover_to_second_backend(store, monkeypatch):
    calls = []

    def handler(request):
        calls.append(str(request.url))
        if "tokenharbor" in str(request.url):
            return httpx.Response(429, json={"error": {"message": "slow down"}})
        return httpx.Response(200, json={"choices": [{"message": {"content": "from beat"}}]})

    monkeypatch.setattr(engine, "_client", lambda timeout: httpx.Client(transport=httpx.MockTransport(handler)))

    status, body, headers = engine.chat("deepseek-flash-v41-free", {"messages": [{"role": "user", "content": "hi"}]}, store)
    assert status == 200
    assert body["choices"][0]["message"]["content"] == "from beat"
    assert headers["x-redfox-backend"] == "beatapi"
    # tokenharbor should now be in cooldown
    assert store.in_cooldown("tokenharbor") > 0
    assert store.health("tokenharbor")["last_failure_class"] == classifier.RATE_LIMIT


def test_cooldown_skips_backend(store, monkeypatch):
    # put tokenharbor in cooldown, then a request should go straight to beatapi
    store.record_failure("tokenharbor", classifier.RATE_LIMIT, 600)
    seen = []

    def handler(request):
        seen.append(str(request.url))
        return httpx.Response(200, json={"choices": [{"message": {"content": "ok"}}]})

    monkeypatch.setattr(engine, "_client", lambda timeout: httpx.Client(transport=httpx.MockTransport(handler)))
    status, _, headers = engine.chat("deepseek-flash-v41-free", {"messages": []}, store)
    assert status == 200
    assert headers["x-redfox-backend"] == "beatapi"
    assert all("tokenharbor" not in u for u in seen)


def test_all_backends_fail(store, monkeypatch):
    monkeypatch.setattr(engine, "_client",
                        lambda timeout: httpx.Client(transport=httpx.MockTransport(
                            lambda req: httpx.Response(503))))
    status, body, _ = engine.chat("deepseek-flash-v41-free", {"messages": []}, store)
    assert status == 502
    assert body["error"]["code"] == "no_healthy_backend"
    assert len(body["attempts"]) >= 2


def test_success_resets_health(store, monkeypatch):
    # failure with no cooldown window, so the next request still tries this backend
    store.record_failure("tokenharbor", classifier.UPSTREAM_5XX, 0)
    monkeypatch.setattr(engine, "_client",
                        lambda timeout: httpx.Client(transport=httpx.MockTransport(
                            lambda req: httpx.Response(200, json={"choices": []}))))
    engine.chat("deepseek-flash-v41-free", {"messages": []}, store)
    h = store.health("tokenharbor")
    assert h["state"] == "healthy"
    assert h["consecutive_failures"] == 0


def test_routeway_snapshot_recorded(store, monkeypatch):
    headers = {
        "x-ratelimit-limit-minute": "5", "x-ratelimit-remaining-minute": "4",
        "x-ratelimit-reset-minute": "60",
        "x-ratelimit-limit-day": "200", "x-ratelimit-remaining-day": "199",
        "x-ratelimit-reset-day": "600",
    }
    monkeypatch.setattr(engine, "_client",
                        lambda timeout: httpx.Client(transport=httpx.MockTransport(
                            lambda req: httpx.Response(200, json={"choices": []}, headers=headers))))
    status, _, headers_out = engine.chat("gemma-4-26b-free", {"messages": []}, store)
    assert status == 200
    assert headers_out["x-redfox-backend"] == "routeway"
    snap = store.latest_snapshot("routeway")
    assert snap["rpd_remaining"] == 199
    assert snap["rpm_limit"] == 5


def test_model_list_matches_config():
    from redfox_router import server
    data = server.models()["data"]
    ids = {m["id"] for m in data}
    assert ids == set(LOGICAL_MODELS.keys())


# ── Auth tests ──
def test_auth_disabled_by_default(monkeypatch):
    """When REDFOX_ROUTER_API_KEY is not set, /v1/* routes work without auth."""
    monkeypatch.delenv("REDFOX_ROUTER_API_KEY", raising=False)
    from redfox_router import server
    from fastapi.testclient import TestClient
    client = TestClient(server.app)
    # Health should work without auth
    r = client.get("/health")
    assert r.status_code == 200
    # Models should work without auth when disabled
    r = client.get("/v1/models")
    assert r.status_code == 200


def test_auth_required_when_key_set(monkeypatch):
    """When REDFOX_ROUTER_API_KEY is set, /v1/* routes require valid Bearer token."""
    monkeypatch.setenv("REDFOX_ROUTER_API_KEY", "test-secret-123")
    # Need to reimport to pick up the new env var
    import importlib
    import redfox_router.server as server_module
    importlib.reload(server_module)
    from fastapi.testclient import TestClient
    client = TestClient(server_module.app)
    # No auth -> 401
    r = client.get("/v1/models")
    assert r.status_code == 401
    # Wrong key -> 403
    r = client.get("/v1/models", headers={"Authorization": "Bearer wrong"})
    assert r.status_code == 403
    # Correct key -> 200
    r = client.get("/v1/models", headers={"Authorization": "Bearer test-secret-123"})
    assert r.status_code == 200
    # Also works without "Bearer " prefix
    r = client.get("/v1/models", headers={"Authorization": "test-secret-123"})
    assert r.status_code == 200


# ── Streaming test ──
def test_stream_chat_basic(store, monkeypatch):
    """Test streaming path returns SSE chunks and records first-byte event."""
    chunks = [
        b'data: {"choices":[{"delta":{"content":"Hello"}}]}\n\n',
        b'data: {"choices":[{"delta":{"content":" world"}}]}\n\n',
        b'data: [DONE]\n\n',
    ]

    class MockResponse:
        def __init__(self):
            self.status_code = 200
            self.headers = {}
            self._chunks = iter(chunks)

        def iter_bytes(self):
            return self._chunks

        def __enter__(self):
            return self

        def __exit__(self, exc_type, exc_val, exc_tb):
            pass

    class MockClient:
        def __init__(self):
            self._response = MockResponse()

        def stream(self, method, url, headers, json):
            return self._response

        def __enter__(self):
            return self

        def __exit__(self, exc_type, exc_val, exc_tb):
            pass

        def close(self):
            pass

    # Mock the client.stream call
    import redfox_router.engine as engine_module

    def mock_client(timeout):
        return MockClient()

    monkeypatch.setattr(engine_module, "_client", mock_client)

    # Call stream_chat (it's a sync generator)
    results = list(engine_module.stream_chat(
        "deepseek-flash-v41-free",
        {"messages": [{"role": "user", "content": "hi"}], "stream": True},
        store
    ))

    assert len(results) == 3
    assert b"Hello" in results[0]
    assert b"world" in results[1]
    assert b"[DONE]" in results[2]

    # Verify event was recorded
    events = store.recent_events(5)
    assert len(events) >= 1
    assert events[0]["http_status"] == 200
    assert events[0]["failure_class"] == "ok"
