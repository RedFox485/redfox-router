"""FastAPI app: OpenAI-compatible router surface + a small status/dashboard API."""
from __future__ import annotations

import hmac
import os
import time
from pathlib import Path

from fastapi import Depends, FastAPI, HTTPException, Request, Security
from fastapi.responses import HTMLResponse, JSONResponse, StreamingResponse
from fastapi.security import APIKeyHeader
from starlette.concurrency import run_in_threadpool

from . import engine
from .config import BACKENDS, LOGICAL_MODELS
from .store import RouterStore

# Simple local auth via API key (env var REDFOX_ROUTER_API_KEY)
# If not set, auth is disabled (localhost-only dev mode)
ROUTER_API_KEY = os.environ.get("REDFOX_ROUTER_API_KEY")
api_key_header = APIKeyHeader(name="Authorization", auto_error=False)


async def verify_api_key(authorization: str = Security(api_key_header)):
    if not ROUTER_API_KEY:
        return  # Auth disabled
    if not authorization:
        raise HTTPException(status_code=401, detail="Missing Authorization header")
    # Support "Bearer <key>" or just "<key>"
    provided = authorization.removeprefix("Bearer ").strip()
    if not hmac.compare_digest(provided, ROUTER_API_KEY):
        raise HTTPException(status_code=403, detail="Invalid API key")


app = FastAPI(title="RedFox Router", version="0.1.0")
store = RouterStore()
_DASHBOARD = Path(__file__).resolve().parent / "dashboard.html"

# Apply auth to all /v1/* routes; /health, /api/status, / remain open
from fastapi import Depends
_v1_routes_dep = Depends(verify_api_key)


@app.get("/health")
def health() -> dict:
    return {
        "status": "ok",
        "logical_models": list(LOGICAL_MODELS.keys()),
        "backends": {b.id: BACKENDS[b.id].name for b in BACKENDS.values()},
    }


@app.get("/v1/models", dependencies=[Depends(verify_api_key)])
def models() -> dict:
    return {
        "object": "list",
        "data": [
            {"id": m.id, "object": "model", "owned_by": "redfox-router",
             "name": m.display_name,
             "context": m.context, "output": m.output}
            for m in LOGICAL_MODELS.values()
        ],
    }


@app.post("/v1/chat/completions", dependencies=[Depends(verify_api_key)])
async def chat_completions(req: Request):
    try:
        payload = await req.json()
    except Exception:
        return JSONResponse({"error": {"message": "invalid JSON body", "code": "invalid_request"}},
                            status_code=400)
    logical_id = str(payload.get("model") or "")
    if payload.get("stream"):
        gen = engine.stream_chat(logical_id, payload, store)
        return StreamingResponse(gen, media_type="text/event-stream")
    status, body, headers = await run_in_threadpool(engine.chat, logical_id, payload, store)
    return JSONResponse(body, status_code=status, headers=headers)


@app.get("/api/status")
def api_status() -> dict:
    now = time.time()
    backends = []
    for bid, b in BACKENDS.items():
        h = store.health(bid)
        snap = store.latest_snapshot(bid)
        backends.append({
            "id": bid,
            "name": b.name,
            "base_url": b.base_url,
            "has_key": bool(b.api_key()),
            "state": h.get("state"),
            "consecutive_failures": h.get("consecutive_failures", 0),
            "last_ok_at": h.get("last_ok_at"),
            "last_error_at": h.get("last_error_at"),
            "last_failure_class": h.get("last_failure_class"),
            "cooldown_s_left": round(store.in_cooldown(bid), 1),
            "exposes_headers": b.exposes_headers,
            "assumed_rpm": b.assumed_rpm,
            "assumed_rpd": b.assumed_rpd,
            "notes": b.notes,
            "quota": snap,
        })
    return {
        "now": now,
        "backends": backends,
        "incidents": store.recent_incidents(5),
        "recent_events": store.recent_events(10),
        "counts": store.counts(),
    }


@app.get("/", response_class=HTMLResponse)
def dashboard() -> str:
    try:
        return _DASHBOARD.read_text()
    except OSError:
        return "<h1>RedFox Router</h1><p>dashboard.html missing.</p>"
