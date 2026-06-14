# Phase 1 — Text → Plan → Revit (Architext pipeline)

**Goal: prove the concept end-to-end with the simplest possible model. Quality is not the metric here — a complete chain is the metric.**

This walkthrough assumes you just cloned the repo and want to do everything by hand, step by step.

## How it works

```
"a house with three bedrooms"
        │
        ▼  generate_plan (MCP tool — Architext gptj-162M, 100% local)
plan JSON  (rooms with polygons in meters + derived walls)
        │
        ▼  validate_plan (MCP tool — checks against schema/plan_schema.json)
validated plan
        │
        ▼  your MCP agent + search_revit_api + pyRevit
walls / levels inside Revit
```

Architext ([paper](https://arxiv.org/abs/2303.07519)) is a 162M-parameter language model trained to output residential layouts as room polygons. It runs on any machine — no GPU needed.

## Step 1 — Install

```bash
cd TarkeebAI
# same venv as revit-rag, or a fresh one
pip install -r mcp-servers/plan-generator/requirements.txt
```

This pulls `transformers` + `torch` (CPU build is fine). Python 3.10–3.12 recommended (torch wheels may lag behind the newest Python).

## Step 2 — Verify the parser (offline, instant)

```bash
python mcp-servers/plan-generator/test_parser.py
```

All tests should pass. This checks the Architext-output → plan-schema conversion logic without downloading anything.

## Step 3 — First generation (manual, no MCP client)

```bash
python mcp-servers/plan-generator/plan_generator_server.py --test "a house with three bedrooms and two bathrooms"
```

First run downloads the model (~650 MB). You get the full plan JSON on stdout and a schema-validation verdict on stderr. Try a few descriptions Architext understands well:

- typology: `"a house with two bedrooms and three bathrooms"`
- adjacency: `"the bedroom is adjacent to the living room"`
- location: `"the kitchen is in the north side of the house"`

Optional third argument controls sampling: `--test "..." low|medium|high`.

> 📝 Week-2 exercise from the project plan: run 10 different descriptions and
> note which work well and which don't — those notes become your first
> LinkedIn technical post.

## Step 4 — Connect to your agent

See [connect-mcp-clients.md](connect-mcp-clients.md). Short version: Claude Code picks up `.mcp.json` automatically; everything else needs two absolute paths in its MCP settings.

## Step 5 — The full chain into Revit

1. Install a pyRevit MCP extension as the executor — e.g. [revit-mcp-server](https://github.com/Demolinator/revit-mcp-server). pyRevit does **not** auto-load a fixed `%APPDATA%` folder; instead you register the extension's directory with pyRevit:
   - Clone/copy the extension anywhere you like — the folder name **must end in `.extension`** (e.g. `D:\pyrevit-ext\revit-mcp-server.extension`).
   - Register the directory that *contains* it: `pyrevit extensions paths add "D:\pyrevit-ext"` (or pyRevit tab → Settings → *Custom Extension Directories* → add the folder), then **Reload** pyRevit.
   - Start Revit with a document open (pyRevit Routes API serves on `localhost:48884`), and register its MCP server in your client alongside the two TarkeebAI servers.
2. Give your agent the orchestration prompt from [connect-mcp-clients.md](connect-mcp-clients.md#recommended-orchestration-prompt) — note it converts the plan's meters to the millimeters the Revit tools expect.
3. The agent: generates → validates → builds the levels and walls, consulting `search_revit_api` whenever the Revit API behavior is unclear.

Record the screen the first time it works end-to-end — that's the v0.1 demo video. 🎬

## Configuration reference

Same three-layer system as revit-rag (env > config.json > defaults):

| Key | Default | Env override | Notes |
|---|---|---|---|
| `model` | `architext/gptj-162M` | `PLAN_GEN_MODEL` | any causal LM fine-tuned on the same format |
| `device` | `auto` | `PLAN_GEN_DEVICE` | `auto` = cuda if available, else cpu |

Copy `mcp-servers/plan-generator/config.example.json` to `config.json` (git-ignored) to persist changes.

## Known v0.1 limitations (by design)

- **No doors/windows yet** — Architext outputs room polygons only; `doors`/`windows` arrays are empty. The agent (or you) can add them to the JSON; `validate_plan` accepts plans with them.
- **Walls are derived from room edges** — edges shared by two rooms become one interior wall; partially-overlapping edges may produce duplicate walls. Good enough to prove the chain; Phase 2 (HouseDiffusion) replaces this generator entirely.
- **English descriptions only** — that's what Architext was trained on. Your orchestrating agent can translate Arabic input before calling the tool.
- **Single level** — everything lands on `L0`.
