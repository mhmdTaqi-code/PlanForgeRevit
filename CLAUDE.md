# TarkeebAI (PlanForgeRevit) — Agent Instructions

Text → Plan → Revit pipeline. Three MCP servers work together:

| Server | Tools | Role |
|---|---|---|
| `plan-generator` | `generate_plan`, `plan_from_bubble_diagram`, `validate_plan` | invent the floor plan (JSON, meters) |
| `revit-rag` | `search_revit_api` | look up exact Revit 2025 API semantics |
| a Revit executor (e.g. `revit-mcp` / pyRevit MCP) | `create_level`, wall/door/window tools… | build real geometry inside Revit |

The shared contract is `schema/plan_schema.json`. Example plan: `examples/iraqi_house_10x20.json`.

## When the user asks to design/build a house ("ابنيلي بيت…", "صمم دار…", "build a house…")

Run the full chain without asking for permission between steps:

1. **Generate** — call `generate_plan` with an English description (translate the user's Arabic brief yourself; spell out digit counts as words happens server-side).
   - For higher quality, or when the user gives explicit room adjacencies, build a bubble diagram (`schema/bubble_diagram_schema.json`) and call `plan_from_bubble_diagram` instead. If the HouseDiffusion checkpoint isn't available it tells you and you fall back to `generate_plan`.
2. **Validate** — call `validate_plan` on the result. On failure, regenerate (max 3 tries).
3. **Sanity-check** — rooms shouldn't overlap; areas should be plausible for the brief. Prefer a clearly better regeneration.
4. **Build in Revit** — requires Revit running with a Revit MCP executor connected (check its status tool first, e.g. `get_revit_status`).
   - ⚠️ **Units: the plan is in METERS; Revit MCP tools take MILLIMETERS — multiply every coordinate by 1000.**
   - Create level(s) from `plan.levels` (elevation_m, height_m).
   - Create each wall from `plan.walls`: `start`/`end` are centerline coords, use `thickness_m`/`height_m`/`kind` (interior/exterior).
   - Place doors/windows from `plan.doors`/`plan.windows` on their host walls via `offset_m` (these arrays may be empty — that's fine, say so).
   - When a tool's Revit API behavior is unclear, call `search_revit_api` BEFORE guessing.
5. **Report** — what was built, what was skipped, in the user's language.

For Iraqi construction standards (multi-layer wall types, column joins, naming), apply the agent skill in `skills/bim-best-practices/SKILL.md`.

## Conventions

- User communicates in Iraqi Arabic; all public/repo content stays in **English**.
- Never let the LLM invent coordinates — geometry always comes from the plan JSON.
- `generate_plan` descriptions must be in English; Architext understands room counts best ("three bedrooms and two bathrooms").

## Verification commands (offline, fast)

```bash
python mcp-servers/plan-generator/test_parser.py                      # Architext parser self-check
python mcp-servers/plan-generator/housediffusion/test_bridge.py      # HouseDiffusion bridge self-check
python mcp-servers/plan-generator/plan_generator_server.py --test "a house with three bedrooms"   # full generation (downloads model on first run)
```

## Gotchas

- First `generate_plan` call downloads Architext (~650 MB); first `search_revit_api` downloads Arctic embeddings (~1.2 GB). Both servers answer the MCP handshake immediately and warm the model in the background — the first tool call may still take ~30 s.
- The Revit RAG DB (~700 MB) lives git-ignored at `data/revit_db/` — layout rules in `docs/getting-started.md`.
- HouseDiffusion checkpoint path comes from the `HOUSE_DIFFUSION_CKPT` env var (set in `.mcp.json`); without it `plan_from_bubble_diagram` degrades gracefully to Colab instructions.
