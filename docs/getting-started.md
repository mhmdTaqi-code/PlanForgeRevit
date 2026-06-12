# Getting Started

This guide takes you from a fresh clone to a working `search_revit_api` tool inside your MCP client (Claude Desktop, Claude Code, Antigravity, or any other MCP-capable agent).

**Requirements:** Python 3.10+, ~3 GB of free disk space (database + embedding model), no GPU and no API keys needed.

## 1. Clone and install

```bash
git clone https://github.com/<your-username>/TarkeebAI.git
cd TarkeebAI
python -m venv .venv
# Windows:
.venv\Scripts\activate
# Linux/macOS:
source .venv/bin/activate

pip install -r mcp-servers/revit-rag/requirements.txt
```

## 2. Download the RAG database

Download all six assets from the
[RevitGeminiRAG v1.0.0-database release](https://github.com/ismail-seleit/RevitGeminiRAG/releases/tag/v1.0.0-database)
(~700 MB total) and place them like this:

```
data/revit_db/
├── chroma.sqlite3
└── 1ccb803a-3d67-4028-a8e8-35b549456170/   ← create this folder, exact name
    ├── data_level0.bin
    ├── header.bin
    ├── index_metadata.pickle
    ├── length.bin
    └── link_lists.bin
```

> ⚠️ **Common pitfall:** the assets download as flat files. ChromaDB will only find the
> index if the five `.bin`/`.pickle` files are inside the UUID-named subfolder shown above.
> The server checks this at startup and prints the exact fix if it's wrong.

## 3. Configure (only if your paths differ)

Out of the box **no configuration is needed** — the server looks for the database at
`<repo>/data/revit_db` and downloads the embedding model automatically from HuggingFace
on first run (~1.2 GB, cached afterwards in `~/.cache/huggingface`).

If your setup differs, copy the template and edit it:

```bash
cp mcp-servers/revit-rag/config.example.json mcp-servers/revit-rag/config.json
```

| Key | Default | When to change it |
|---|---|---|
| `db_path` | `<repo>/data/revit_db` | your database lives somewhere else |
| `collection` | `revit_api_2025_chunked` | you built your own database with a different collection name |
| `embedding_model` | `Snowflake/snowflake-arctic-embed-l-v2.0` | **only** if your database was embedded with a different model — it must always match the model used to build the database, or search results will be garbage |

Environment variables override everything: `REVIT_RAG_DB_PATH`, `REVIT_RAG_COLLECTION`,
`REVIT_RAG_EMBEDDING_MODEL` (and `REVIT_RAG_CONFIG` to point to a config file elsewhere).

`config.json` is git-ignored, so your local paths never leak into the repo.

## 4. Smoke-test the server

```bash
python mcp-servers/revit-rag/revit_rag_server.py
```

You should see on stderr:

```
RAG: loading embedding model 'Snowflake/snowflake-arctic-embed-l-v2.0'...
RAG: connecting to DB at .../data/revit_db...
RAG: ready!
```

The first run is slow (model download). The process then waits silently for an MCP client
on stdin — that's normal; press `Ctrl+C` to stop.

## 5. Register the server in your MCP client

Use the **absolute paths** of your machine (these are the only machine-specific values in the whole setup):

### Claude Desktop / Antigravity (`claude_desktop_config.json` or equivalent)

```json
{
  "mcpServers": {
    "revit-rag": {
      "command": "C:\\path\\to\\TarkeebAI\\.venv\\Scripts\\python.exe",
      "args": ["C:\\path\\to\\TarkeebAI\\mcp-servers\\revit-rag\\revit_rag_server.py"]
    }
  }
}
```

### Claude Code

```bash
claude mcp add revit-rag -- /path/to/TarkeebAI/.venv/bin/python /path/to/TarkeebAI/mcp-servers/revit-rag/revit_rag_server.py
```

Restart the client. You should now see the `search_revit_api` tool. Try:

> *"Search the Revit API for how to create a wall from a line."*

## 6. Troubleshooting

| Symptom | Cause / fix |
|---|---|
| `RAG error: no database found at ...` | step 2 not done, or `db_path` points to the wrong folder |
| `RAG error: index files are in the wrong place` | the `.bin` files are flat — move them into the UUID subfolder (the message tells you the exact path) |
| Search returns nonsense results | `embedding_model` doesn't match the model the database was built with |
| Very long first startup | normal: the embedding model (~1.2 GB) is being downloaded and cached |
| `trust_remote_code` warnings | expected for the Arctic embedding model; the code is loaded from the official Snowflake HuggingFace repo |
