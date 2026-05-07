#!/usr/bin/env python3
from __future__ import annotations

import json
import os
from threading import Lock
from typing import Any

import gradio as gr
import requests


API_BASE_URL = os.getenv("AION_API_BASE_URL", "https://api.aiondashboard.site").rstrip("/")
SPACE_API_KEY = os.getenv("AION_SPACE_API_KEY", "").strip()
ACCESS_PAGE_URL = os.getenv(
    "AION_ACCESS_PAGE_URL",
    "https://dashboard.aiondashboard.site/access/register",
)
DEMO_REQUEST_LIMIT = 10
DEMO_COUNTS: dict[str, int] = {}
DEMO_COUNTS_LOCK = Lock()

DEMO_BANNER = (
    "This is a rate-limited demo (10 requests per session). "
    "Production access requires an API key.  \n"
    f"→ {ACCESS_PAGE_URL}"
)
DEMO_LIMIT_MESSAGE = (
    "Demo limit reached. Get production access at "
    f"{ACCESS_PAGE_URL}"
)
PRODUCTION_FOOTER = (
    "---\n"
    f"🔑 Production usage: {ACCESS_PAGE_URL}"
)


def _session_key(request: gr.Request | None) -> str:
    if request is not None:
        session_hash = getattr(request, "session_hash", None)
        if session_hash:
            return str(session_hash)
    return "anonymous-demo-session"


def _consume_demo_request(request: gr.Request | None) -> bool:
    key = _session_key(request)
    with DEMO_COUNTS_LOCK:
        used = DEMO_COUNTS.get(key, 0)
        if used >= DEMO_REQUEST_LIMIT:
            return False
        DEMO_COUNTS[key] = used + 1
        return True


def _format_success_output(payload: dict[str, Any]) -> str:
    return f"```json\n{json.dumps(payload, indent=2, ensure_ascii=False)}\n```\n\n{PRODUCTION_FOOTER}"


def _format_error_output(title: str, detail: Any | None = None) -> str:
    lines = [f"**{title}**"]
    if detail not in (None, ""):
        if isinstance(detail, (dict, list)):
            lines.append(f"```json\n{json.dumps(detail, indent=2, ensure_ascii=False)}\n```")
        else:
            lines.append(str(detail))
    lines.append("")
    lines.append(PRODUCTION_FOOTER)
    return "\n\n".join(lines)


def analyze_payload(
    headline: str,
    published_at: str | None = None,
    request: gr.Request | None = None,
) -> str:
    headline = (headline or "").strip()
    if not headline:
        return _format_error_output("Headline is required.")

    if not _consume_demo_request(request):
        return DEMO_LIMIT_MESSAGE

    if not SPACE_API_KEY:
        return _format_error_output(
            "Demo backend not configured.",
            "This demo surface is not configured with its internal API key.",
        )

    payload: dict[str, Any] = {"headline": headline}
    if published_at:
        payload["published_at"] = published_at

    try:
        response = requests.post(
            f"{API_BASE_URL}/v1/analyze",
            headers={"X-API-Key": SPACE_API_KEY},
            json=payload,
            timeout=45,
        )
        if response.status_code >= 400:
            try:
                detail: Any = response.json()
            except Exception:
                detail = response.text[:400]
            return _format_error_output(
                f"API request failed ({response.status_code}).",
                detail,
            )
        return _format_success_output(response.json())
    except requests.RequestException as exc:
        return _format_error_output("Demo unavailable.", str(exc))


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
    output = gr.Markdown(label="Analysis")

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
        outputs=output,
        api_name="analyze",
    )


if __name__ == "__main__":
    demo.launch(
        server_name="0.0.0.0",
        server_port=int(os.getenv("PORT", "7860")),
        show_error=True,
    )
