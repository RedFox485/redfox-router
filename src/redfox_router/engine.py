"""Routing engine: pick a backend for a logical model, fail over, record telemetry."""
from __future__ import annotations

import json
import os
import time

import httpx

from . import classifier
from .config import backend_for
from .store import RouterStore

DEFAULT_TIMEOUT = float(os.environ.get("REDFOX_ROUTER_TIMEOUT", "120"))
BASE_COOLDOWN_S = float(os.environ.get("REDFOX_ROUTER_COOLDOWN", "60"))


def _client(timeout: float) -> httpx.Client:
    return httpx.Client(timeout=timeout)


def _cooldown_for(failure_class: str, retry_after: float | None) -> float:
    if retry_after and retry_after > 0:
        return max(1.0, min(float(retry_after), 3600.0))
    return {
        classifier.RATE_LIMIT: 60.0,
        classifier.QUOTA_EXHAUSTED: 900.0,
        classifier.TIMEOUT: 120.0,
        classifier.CONNECTION_DROPPED: 120.0,
    }.get(failure_class, BASE_COOLDOWN_S)


def _error_body(message: str, code: str, **extra) -> dict:
    body = {"error": {"message": message, "type": code, "code": code}}
    body.update(extra)
    return body


def _parse_retry_after(headers: dict) -> float | None:
    ra = headers.get("retry-after")
    if not ra:
        return None
    try:
        return float(ra)
    except (TypeError, ValueError):
        return None


def _upstream_body(payload: dict, upstream_model: str, stream: bool | None = None) -> dict:
    body = dict(payload)
    body["model"] = upstream_model
    if stream is not None:
        body["stream"] = stream
    return body


def chat(logical_id: str, payload: dict, store: RouterStore,
         timeout: float | None = None) -> tuple[int, dict, dict]:
    """Non-streaming completion. Returns (status, body, response_headers)."""
    chain = backend_for(logical_id)
    if not chain:
        return 404, _error_body(f"unknown logical model: {logical_id}", "model_not_found"), {}

    timeout = timeout or DEFAULT_TIMEOUT
    attempts: list[dict] = []

    for i, (backend, upstream_model) in enumerate(chain):
        left = store.in_cooldown(backend.id)
        if left > 0:
            attempts.append({"backend": backend.id, "skipped": f"cooldown {int(left)}s"})
            continue
        key = backend.api_key()
        if not key:
            attempts.append({"backend": backend.id, "class": classifier.AUTH, "error": "no key configured"})
            continue

        url = backend.base_url.rstrip("/") + "/chat/completions"
        headers = {"Authorization": f"Bearer {key}", "Content-Type": "application/json"}
        body = _upstream_body(payload, upstream_model)
        t0 = time.time()
        try:
            client = _client(timeout)
            try:
                r = client.post(url, headers=headers, json=body)
            finally:
                client.close()
        except Exception as exc:  # network/timeout
            latency = int((time.time() - t0) * 1000)
            fc = classifier.classify_exception(exc)
            store.record_event(logical_id, backend.id, upstream_model, None, fc, latency,
                               error_excerpt=str(exc), attempt=i)
            if classifier.should_failover(fc):
                store.record_failure(backend.id, fc, _cooldown_for(fc, None), summary=f"{fc}: {exc}")
                attempts.append({"backend": backend.id, "class": fc})
                continue
            return 502, _error_body(f"upstream error: {exc}", fc), {}

        latency = int((time.time() - t0) * 1000)
        if r.status_code == 200:
            store.record_event(logical_id, backend.id, upstream_model, 200, classifier.OK, latency, attempt=i)
            store.record_success(backend.id)
            if backend.exposes_headers:
                store.record_snapshot(backend.id, dict(r.headers))
            try:
                payload_out = r.json()
            except Exception:
                payload_out = {"error": {"message": "upstream returned non-JSON", "code": "bad_upstream"}}
            return 200, payload_out, {"x-redfox-backend": backend.id}

        text = r.text[:300]
        fc = classifier.classify_status(r.status_code, text)
        retry_after = _parse_retry_after(dict(r.headers))
        store.record_event(logical_id, backend.id, upstream_model, r.status_code, fc, latency,
                           retry_after, text, i)
        if classifier.should_failover(fc):
            store.record_failure(backend.id, fc, _cooldown_for(fc, retry_after),
                                 summary=f"{fc}: {text[:150]}")
            attempts.append({"backend": backend.id, "status": r.status_code, "class": fc})
            continue
        # e.g. invalid_request: not a routing problem, return it to the client
        try:
            return r.status_code, r.json(), {"x-redfox-backend": backend.id}
        except Exception:
            return r.status_code, {"error": {"message": text, "code": fc}}, {"x-redfox-backend": backend.id}

    return 502, _error_body("no healthy backend available", "no_healthy_backend", attempts=attempts), {}


def _sse_error(message: str) -> bytes:
    data = json.dumps({"error": {"message": message, "code": "no_healthy_backend"}})
    return f"data: {data}\n\n".encode()


def stream_chat(logical_id: str, payload: dict, store: RouterStore,
                timeout: float | None = None):
    """Streaming (SSE) completion. Fails over only before the first upstream byte."""
    chain = backend_for(logical_id)
    if not chain:
        yield _sse_error(f"unknown logical model: {logical_id}")
        return

    timeout = timeout or DEFAULT_TIMEOUT
    for i, (backend, upstream_model) in enumerate(chain):
        if store.in_cooldown(backend.id) > 0:
            continue
        key = backend.api_key()
        if not key:
            continue
        url = backend.base_url.rstrip("/") + "/chat/completions"
        headers = {"Authorization": f"Bearer {key}", "Content-Type": "application/json"}
        body = _upstream_body(payload, upstream_model, stream=True)
        t0 = time.time()
        try:
            with _client(timeout) as client:
                with client.stream("POST", url, headers=headers, json=body) as r:
                    if r.status_code != 200:
                        text = b"".join(r.iter_bytes()).decode("utf-8", "replace")[:300]
                        fc = classifier.classify_status(r.status_code, text)
                        store.record_event(logical_id, backend.id, upstream_model,
                                           r.status_code, fc, int((time.time() - t0) * 1000),
                                           error_excerpt=text, attempt=i)
                        if classifier.should_failover(fc):
                            store.record_failure(backend.id, fc, _cooldown_for(fc, None),
                                                 summary=f"{fc}: {text[:150]}")
                            continue
                        yield _sse_error(text)
                        return
                    store.record_success(backend.id)
                    if backend.exposes_headers:
                        store.record_snapshot(backend.id, dict(r.headers))
                    first = True
                    for chunk in r.iter_bytes():
                        if first:
                            store.record_event(logical_id, backend.id, upstream_model, 200,
                                               classifier.OK, int((time.time() - t0) * 1000), attempt=i)
                            first = False
                        yield chunk
                    if first:  # upstream returned 200 but no bytes
                        store.record_event(logical_id, backend.id, upstream_model, 200,
                                           classifier.OK, int((time.time() - t0) * 1000), attempt=i)
                    return
        except Exception as exc:
            fc = classifier.classify_exception(exc)
            store.record_event(logical_id, backend.id, upstream_model, None, fc,
                               int((time.time() - t0) * 1000), error_excerpt=str(exc), attempt=i)
            if classifier.should_failover(fc):
                store.record_failure(backend.id, fc, _cooldown_for(fc, None), summary=f"{fc}: {exc}")
                continue
            yield _sse_error(str(exc))
            return

    yield _sse_error("no healthy backend available")
