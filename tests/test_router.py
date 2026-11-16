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
