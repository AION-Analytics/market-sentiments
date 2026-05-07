# AION India Event Intelligence MCP Server

Convert Indian financial headlines into structured sector-level intelligence using causal propagation — not sentiment, not trading signals.

Formerly `aion-news-to-signal`.

Connect AI agents and coding IDEs like ChatGPT, Claude, Gemini, Cursor, VS Code, Windsurf, Antigravity, Cline, and other MCP clients directly to Indian financial event intelligence.

Use it as an India-focused event intelligence API inside MCP-compatible workflows.

# What it does

- Exposes a single tool: `analyze_news`
- Given a headline like `"RBI hikes repo rate by 25 bps"`
- Returns only the `sector_vector`
- Helps answer which sectors are directly affected, indirectly pressured, or relatively supported
- Requires API key configuration through `AION_API_KEY`
- Enforces quota through the managed API
- Does not execute trades or generate executable orders

# Installation

```bash
pip install aion-news-to-signal mcp
```

# Usage

```bash
python aion_mcp_server.py
```

Environment:

```bash
export AION_API_KEY="<your_api_key>"
```

Then connect your LLM client or IDE to the MCP server and ask:

```text
Analyze this Indian financial headline using AION India Event Intelligence and return the sector_vector only: <headline>
```

# Compatible clients

- ChatGPT
- Claude
- Gemini
- Cursor
- VS Code
- Windsurf
- Antigravity
- Cline
- Other MCP-compatible IDEs and agent runtimes

# Links

- Base model surface: [AION India Event Intelligence](https://huggingface.co/AION-Analytics/aion-news-to-signal)
- PyPI: [aion-news-to-signal](https://pypi.org/project/aion-news-to-signal/)
- Live demo: [HuggingFace Space](https://huggingface.co/spaces/AION-Analytics/aion-news-to-signal)
- API access page: [dashboard.aiondashboard.site/access/register](https://dashboard.aiondashboard.site/access/register)
- Documentation and MCP integration: [dashboard.aiondashboard.site/models/news-to-signal](https://dashboard.aiondashboard.site/models/news-to-signal)
