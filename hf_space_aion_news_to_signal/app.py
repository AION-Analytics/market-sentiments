#!/usr/bin/env python3
from __future__ import annotations

from collections import defaultdict
from datetime import datetime, timezone
import hashlib
import json
import os
import sqlite3
import time
from threading import Lock
from typing import Any

import gradio as gr
import requests


API_BASE_URL = os.getenv("AION_API_BASE_URL", "https://api.aiondashboard.site").rstrip("/")
SPACE_API_KEY = os.getenv("AION_SPACE_API_KEY", "").strip()
NULL_EVENT_LOG_URL = os.getenv("AION_NULL_EVENT_LOG_URL", "").strip()
NULL_EVENT_LOG_KEY = os.getenv("AION_NULL_EVENT_LOG_KEY", "").strip()
ACCESS_PAGE_URL = "https://dashboard.aiondashboard.site/access/register"
RATE_LIMIT = int(os.getenv("AION_SPACE_DEMO_RATE_LIMIT", "3"))
RATE_WINDOW = int(os.getenv("AION_SPACE_DEMO_RATE_WINDOW_SECS", "86400"))
DEMO_USAGE_DB = os.getenv("AION_SPACE_USAGE_DB", "hf_demo_usage.db").strip()
SESSION_COUNTS: defaultdict[str, int] = defaultdict(int)
SESSION_LAST_RESET: defaultdict[str, float] = defaultdict(float)
DEMO_COUNTS_LOCK = Lock()
USAGE_LOCK = Lock()

DEMO_BANNER = (
    f"This is a rate-limited demo ({RATE_LIMIT} requests per visitor per day). "
    "Production access requires an API key.  \n"
    f"→ {ACCESS_PAGE_URL}"
)
PRODUCTION_FOOTER = f"---\n🔑 Production usage: {ACCESS_PAGE_URL}"
PRODUCTION_FOOTER_UI = f"🔑 Production usage: {ACCESS_PAGE_URL}"


def _session_key(request: gr.Request | None) -> str:
    if request is not None:
        session_hash = getattr(request, "session_hash", None)
        if session_hash:
            return str(session_hash)
        headers = getattr(request, "headers", None) or {}
        forwarded = headers.get("x-forwarded-for") or headers.get("cf-connecting-ip") or ""
        user_agent = headers.get("user-agent") or ""
        if forwarded or user_agent:
            raw = f"{forwarded}|{user_agent}".encode("utf-8", "ignore")
            return hashlib.sha256(raw).hexdigest()[:32]
        client = getattr(request, "client", None)
        if client is not None and getattr(client, "host", None):
            return f"client:{client.host}"
    return "anonymous-demo-session"


def _request_fingerprint(request: gr.Request | None) -> dict[str, str]:
    headers = getattr(request, "headers", None) or {}
    forwarded = headers.get("x-forwarded-for") or headers.get("cf-connecting-ip") or ""
    user_agent = headers.get("user-agent") or ""
    client = getattr(request, "client", None)
    client_host = getattr(client, "host", "") if client is not None else ""
    raw = f"{forwarded}|{client_host}|{user_agent}".encode("utf-8", "ignore")
    return {
        "session_key": _session_key(request),
        "visitor_hash": hashlib.sha256(raw).hexdigest()[:32],
        "ip_hash": hashlib.sha256((forwarded or client_host).encode("utf-8", "ignore")).hexdigest()[:32]
        if forwarded or client_host
        else "",
        "user_agent_hash": hashlib.sha256(user_agent.encode("utf-8", "ignore")).hexdigest()[:32]
        if user_agent
        else "",
    }


def _init_usage_db() -> None:
    if not DEMO_USAGE_DB:
        return
    with USAGE_LOCK:
        with sqlite3.connect(DEMO_USAGE_DB) as conn:
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS demo_usage (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    timestamp TEXT NOT NULL,
                    session_key TEXT,
                    visitor_hash TEXT,
                    ip_hash TEXT,
                    user_agent_hash TEXT,
                    headline_sha256 TEXT NOT NULL,
                    headline TEXT NOT NULL,
                    published_at TEXT,
                    event TEXT,
                    sector_vector_zero INTEGER NOT NULL,
                    is_null_event INTEGER NOT NULL,
                    status TEXT NOT NULL
                )
                """
            )
            conn.execute("CREATE INDEX IF NOT EXISTS idx_demo_usage_timestamp ON demo_usage(timestamp)")
            conn.execute("CREATE INDEX IF NOT EXISTS idx_demo_usage_visitor ON demo_usage(visitor_hash)")
            conn.commit()


def _record_demo_usage(
    *,
    headline: str,
    published_at: str | None,
    result: dict[str, Any],
    request: gr.Request | None,
    status: str,
) -> None:
    if not DEMO_USAGE_DB:
        return
    try:
        _init_usage_db()
        fp = _request_fingerprint(request)
        with USAGE_LOCK:
            with sqlite3.connect(DEMO_USAGE_DB) as conn:
                conn.execute(
                    """
                    INSERT INTO demo_usage (
                        timestamp, session_key, visitor_hash, ip_hash, user_agent_hash,
                        headline_sha256, headline, published_at, event,
                        sector_vector_zero, is_null_event, status
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        datetime.now(timezone.utc).isoformat(),
                        fp["session_key"],
                        fp["visitor_hash"],
                        fp["ip_hash"],
                        fp["user_agent_hash"],
                        hashlib.sha256(headline.encode("utf-8")).hexdigest(),
                        headline,
                        published_at,
                        result.get("event"),
                        int(_sector_vector_is_zero(result)),
                        int(_is_null_event_result(result)),
                        status,
                    ),
                )
                conn.commit()
    except Exception:
        return


def check_rate_limit(session_id: str) -> bool:
    now = time.time()
    with DEMO_COUNTS_LOCK:
        if now - SESSION_LAST_RESET[session_id] > RATE_WINDOW:
            SESSION_COUNTS[session_id] = 0
            SESSION_LAST_RESET[session_id] = now
        if SESSION_COUNTS[session_id] >= RATE_LIMIT:
            return False
        SESSION_COUNTS[session_id] += 1
        return True


def _limit_payload() -> dict[str, str]:
    return {
        "error": "demo_limit_reached",
        "message": (
            f"Demo limit of {RATE_LIMIT} requests per day reached. Get production access at "
            f"{ACCESS_PAGE_URL}"
        ),
        "next_step": ACCESS_PAGE_URL,
    }


def _error_payload(error: str, message: str) -> dict[str, str]:
    return {
        "error": error,
        "message": message,
        "next_step": ACCESS_PAGE_URL,
    }


def _sector_vector_is_zero(result: dict[str, Any]) -> bool:
    vector = result.get("sector_vector")
    if not isinstance(vector, dict) or not vector:
        return True
    for value in vector.values():
        try:
            if abs(float(value)) > 1e-12:
                return False
        except (TypeError, ValueError):
            continue
    return True


def _rate_limit_key(request: gr.Request | None) -> str:
    fp = _request_fingerprint(request)
    return fp.get("visitor_hash") or fp.get("session_key") or _session_key(request)


def _is_null_event_result(result: dict[str, Any]) -> bool:
    return result.get("event") is None or _sector_vector_is_zero(result)


def _send_null_event_log(headline: str, published_at: str | None, result: dict[str, Any]) -> None:
    if not NULL_EVENT_LOG_URL or not NULL_EVENT_LOG_KEY or not _is_null_event_result(result):
        return
    try:
        requests.post(
            NULL_EVENT_LOG_URL,
            headers={"X-Internal-Log-Key": NULL_EVENT_LOG_KEY},
            json={
                "headline": headline,
                "published_at": published_at,
                "source": "hf_demo",
                "predicted_confidence": result.get("confidence"),
                "vix_regime": result.get("vix_regime"),
                "result": result,
            },
            timeout=5,
        )
    except requests.RequestException:
        # Demo response should not fail because learning telemetry is unavailable.
        return


def analyze_payload(
    headline: str,
    published_at: str | None = None,
    request: gr.Request | None = None,
) -> tuple[dict[str, Any], str]:
    headline = (headline or "").strip()
    if not headline:
        result = _error_payload("headline_required", "Headline is required.")
        _record_demo_usage(
            headline="",
            published_at=published_at,
            result=result,
            request=request,
            status="headline_required",
        )
        return result, PRODUCTION_FOOTER_UI

    session_id = _rate_limit_key(request)
    if not check_rate_limit(session_id):
        result = _limit_payload()
        _record_demo_usage(
            headline=headline,
            published_at=published_at,
            result=result,
            request=request,
            status="rate_limited",
        )
        return result, PRODUCTION_FOOTER_UI

    if not SPACE_API_KEY:
        result = _error_payload(
            "demo_backend_not_configured",
            "This demo surface is not configured with its internal API key.",
        )
        _record_demo_usage(
            headline=headline,
            published_at=published_at,
            result=result,
            request=request,
            status="backend_not_configured",
        )
        return (
            result,
            PRODUCTION_FOOTER_UI,
        )

    payload: dict[str, Any] = {"headline": headline, "source": "hf_demo"}
    if published_at:
        payload["published_at"] = published_at

    try:
        fp = _request_fingerprint(request)
        response = requests.post(
            f"{API_BASE_URL}/v1/analyze",
            headers={
                "X-API-Key": SPACE_API_KEY,
                "X-AION-Source": "hf_demo",
                "X-AION-Demo-Visitor": fp.get("visitor_hash", ""),
                "X-AION-Demo-Session": fp.get("session_key", ""),
            },
            json=payload,
            timeout=45,
        )
        if response.status_code >= 400:
            try:
                detail: Any = response.json()
            except Exception:
                detail = response.text[:400]
            result = {
                "error": "api_request_failed",
                "message": f"API request failed ({response.status_code}).",
                "detail": detail,
                "next_step": ACCESS_PAGE_URL,
            }
            _record_demo_usage(
                headline=headline,
                published_at=published_at,
                result=result,
                request=request,
                status="api_request_failed",
            )
            return result, PRODUCTION_FOOTER_UI
        result = response.json()
        if isinstance(result, dict):
            result = dict(result)
            _send_null_event_log(headline, published_at, result)
            result["production_usage"] = ACCESS_PAGE_URL
            _record_demo_usage(
                headline=headline,
                published_at=published_at,
                result=result,
                request=request,
                status="ok",
            )
        return result, PRODUCTION_FOOTER_UI
    except requests.RequestException as exc:
        result = _error_payload("demo_unavailable", str(exc))
        _record_demo_usage(
            headline=headline,
            published_at=published_at,
            result=result,
            request=request,
            status="demo_unavailable",
        )
        return result, PRODUCTION_FOOTER_UI


with gr.Blocks(title="AION India Event Intelligence") as demo:
    gr.Markdown(
        f"""
        # AION India Event Intelligence

        Formerly `aion-news-to-signal`.

        > {DEMO_BANNER}

        This Space is a demo UI backed by the managed AION API.

        Production API contract:
        - `POST {API_BASE_URL}/v1/analyze`
        - header: `X-API-Key: <key>`

        This Space is not the supported production runtime.
        """
    )
    with gr.Row():
        headline = gr.Textbox(
            label="Headline",
            lines=2,
            placeholder="RBI hikes repo rate by 25 bps",
        )
    with gr.Row():
        published_at = gr.Textbox(
            label="Published At (optional)",
            placeholder="2026-04-26",
        )
    run = gr.Button("Analyze", variant="primary")
    output = gr.JSON(label="Analysis")
    footer = gr.Markdown(value=PRODUCTION_FOOTER_UI)

    examples = [
        ["RBI hikes repo rate by 25 bps", ""],
        ["Heatwave in Punjab during March damages wheat crop and threatens food inflation", ""],
        ["Unseasonal rainfall and hailstorm hit apple orchards in Himachal Pradesh in April", ""],
        ["Crude oil prices fall sharply", ""],
    ]
    gr.Examples(examples=examples, inputs=[headline, published_at])

    run.click(
        fn=analyze_payload,
        inputs=[headline, published_at],
        outputs=[output, footer],
        api_name="analyze",
    )


if __name__ == "__main__":
    demo.launch(
        server_name="0.0.0.0",
        server_port=int(os.getenv("PORT", "7860")),
        show_error=True,
    )
