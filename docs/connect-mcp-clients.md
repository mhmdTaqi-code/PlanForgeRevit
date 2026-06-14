# Connecting TarkeebAI to MCP Clients

Both servers (`revit-rag` and `plan-generator`) speak standard MCP over stdio, so **any MCP-capable agent** can use them. The only machine-specific values you ever provide are two paths: your Python executable and the server script.

## Claude Code — zero config

The repo ships a [`.mcp.json`](../.mcp.json) at its root. Open the repo folder with Claude Code and both servers are detected automatically (you'll be asked to approve them once). It uses `python` from your PATH — activate your venv first, or edit `.mcp.json` to point at `.venv/Scripts/python.exe`.

Alternatively, register them globally:

```bash
claude mcp add revit-rag -- /path/to/TarkeebAI/.venv/bin/python /path/to/TarkeebAI/mcp-servers/revit-rag/revit_rag_server.py
claude mcp add plan-generator -- /path/to/TarkeebAI/.venv/bin/python /path/to/TarkeebAI/mcp-servers/plan-generator/plan_generator_server.py
```

## Claude Desktop

Merge the contents of [`mcp-config.example.json`](../mcp-config.example.json) into your config file, replacing `<REPO>` with the absolute repo path:

- Windows: `%APPDATA%\Claude\claude_desktop_config.json`
- macOS: `~/Library/Application Support/Claude/claude_desktop_config.json`

```json
{
  "mcpServers": {
    "revit-rag": {
      "command": "C:\\path\\to\\TarkeebAI\\.venv\\Scripts\\python.exe",
      "args": ["C:\\path\\to\\TarkeebAI\\mcp-servers\\revit-rag\\revit_rag_server.py"]
    },
    "plan-generator": {
      "command": "C:\\path\\to\\TarkeebAI\\.venv\\Scripts\\python.exe",
      "args": ["C:\\path\\to\\TarkeebAI\\mcp-servers\\plan-generator\\plan_generator_server.py"]
    }
  }
}
```

Restart the app after editing.

## Antigravity / Cursor / other MCP clients

Same shape as the Claude Desktop snippet above — every stdio MCP client takes a `command` + `args` pair. Find your client's MCP settings file (Antigravity: MCP config in agent settings; Cursor: `~/.cursor/mcp.json`) and paste the same two entries.

## What the agent gets

| Tool | Server | Purpose |
|---|---|---|
| `generate_plan` | plan-generator | description → floor plan JSON (rooms, walls, meters) — Architext, CPU |
| `plan_from_bubble_diagram` | plan-generator | bubble diagram (rooms + adjacencies) → floor plan JSON — HouseDiffusion, higher quality, GPU ([Phase 2](phase-2-housediffusion.md)) |
| `validate_plan` | plan-generator | check any plan JSON against `schema/plan_schema.json` |
| `search_revit_api` | revit-rag | semantic search over Revit 2025 API docs |

## The executor: pyRevit MCP extension

The third layer (building inside Revit) is provided by a pyRevit-based MCP server installed as a pyRevit extension — for example [revit-mcp-server](https://github.com/Demolinator/revit-mcp-server) (Revit 2024–2027, 48 tools incl. `create_level`, `create_wall`, `create_room`). It talks to Revit through pyRevit's Routes API (`localhost:48884`) and registers in your MCP client like any other server. Any equivalent pyRevit MCP bridge works — TarkeebAI is executor-agnostic by design.

**Installing the extension (the right way).** pyRevit does *not* watch a fixed `%APPDATA%\pyRevit\Extensions\` folder — that path is a common mistake. Instead, pyRevit loads extensions from directories you explicitly register, and an extension folder **must end in `.extension`**:

```powershell
# 1. clone/copy it as a *.extension folder anywhere convenient
git clone https://github.com/Demolinator/revit-mcp-server.git "D:\pyrevit-ext\revit-mcp-server.extension"

# 2. register the PARENT directory (the one that contains the .extension folder)
pyrevit extensions paths add "D:\pyrevit-ext"

# 3. reload pyRevit (CLI or the pyRevit tab → Reload button in Revit)
pyrevit reload
```

Alternatively, do step 2 from Revit: **pyRevit tab → Settings → Custom Extension Directories → add `D:\pyrevit-ext` → Save Settings and Reload**. Confirm with `pyrevit extensions paths` — your directory should be listed. Then start Revit with a document open; the Routes API serves on `localhost:48884`.

> ⚠️ **Units:** TarkeebAI plans are in **meters**; revit-mcp-server tools take **millimeters**. The orchestration prompt below handles the ×1000 conversion.

## Recommended orchestration prompt

Paste this as the task prompt for your agent when you want the full text → Revit chain (requires Revit running with the pyRevit MCP extension):

```text
Build the following house in Revit: <your description>.

Follow this exact workflow:
1. Call generate_plan with the description.
2. Call validate_plan on the result. If validation fails, regenerate (max 3 tries).
3. Review the plan briefly: rooms should not overlap and areas should be plausible.
   If a regeneration is clearly better, prefer it.
4. Build the plan with the Revit MCP tools. If a tool's usage or the underlying
   API behavior is unclear, call search_revit_api first to check the exact
   Revit API semantics:
   a. Create the level(s) from plan.levels.
   b. Create each wall from plan.walls — start/end are centerline coordinates
      in METERS; the Revit MCP tools expect MILLIMETERS, so multiply by 1000.
   c. Place doors and windows on their host walls using offset_m along the wall.
5. Report what was built and any items you skipped.
```

## Notes

- First `generate_plan` call downloads the Architext model (~650 MB) from HuggingFace — subsequent runs use the cache.
- First `search_revit_api` call downloads the embedding model (~1.2 GB).
- Both servers are independent: you can register only one of them if you need just that tool.
