#!/usr/bin/env python3
"""
revit_rag_server.py
MCP server exposing semantic search over a local Revit 2025 API
documentation database (ChromaDB + sentence-transformers).

Configuration is resolved in this order (highest priority first):
  1. Environment variables:  REVIT_RAG_DB_PATH, REVIT_RAG_COLLECTION,
                             REVIT_RAG_EMBEDDING_MODEL
  2. config.json next to this script (copy config.example.json)
  3. Built-in defaults (database at <repo>/data/revit_db)

See docs/getting-started.md for setup instructions.
"""

import asyncio
import json
import os
import sqlite3
import sys
from pathlib import Path

from mcp.server import Server
from mcp.server.stdio import stdio_server
from mcp.types import Tool, TextContent

SCRIPT_DIR = Path(__file__).resolve().parent
REPO_ROOT = SCRIPT_DIR.parent.parent

DEFAULTS = {
    "db_path": str(REPO_ROOT / "data" / "revit_db"),
    "collection": "revit_api_2025_chunked",
    # Must be the same model the database was built with.
    "embedding_model": "Snowflake/snowflake-arctic-embed-l-v2.0",
}


def load_config() -> dict:
    config = dict(DEFAULTS)

    config_path = Path(os.environ.get("REVIT_RAG_CONFIG", SCRIPT_DIR / "config.json"))
    if config_path.is_file():
        with open(config_path, encoding="utf-8") as f:
            config.update({k: v for k, v in json.load(f).items() if v})

    for key, env in [
        ("db_path", "REVIT_RAG_DB_PATH"),
        ("collection", "REVIT_RAG_COLLECTION"),
        ("embedding_model", "REVIT_RAG_EMBEDDING_MODEL"),
    ]:
        if os.environ.get(env):
            config[key] = os.environ[env]

    return config


def validate_db_layout(db_path: Path) -> None:
    """Fail early with actionable messages instead of cryptic Chroma errors."""
    sqlite_file = db_path / "chroma.sqlite3"
    if not sqlite_file.is_file():
        sys.exit(
            f"RAG error: no database found at {db_path}\n"
            "Download the prebuilt database (see docs/getting-started.md) "
            "or point db_path/REVIT_RAG_DB_PATH to your own ChromaDB folder."
        )

    # The HNSW index files must live in a subfolder named after the vector
    # segment UUID. Release assets download as flat files, so check and guide.
    con = sqlite3.connect(sqlite_file)
    try:
        rows = con.execute("SELECT id FROM segments WHERE scope = 'VECTOR'").fetchall()
    finally:
        con.close()

    for (segment_id,) in rows:
        segment_dir = db_path / segment_id
        if not segment_dir.is_dir() and (db_path / "data_level0.bin").is_file():
            sys.exit(
                f"RAG error: index files are in the wrong place.\n"
                f"Create the folder {segment_dir}\n"
                f"and move data_level0.bin, header.bin, length.bin, "
                f"link_lists.bin and index_metadata.pickle into it."
            )


CONFIG = load_config()

server = Server("revit-rag")
_collection = None
_model = None


def _blocking_load():
    """Load the embedding model and database (runs in a worker thread)."""
    global _collection, _model
    if _collection is not None:
        return _collection, _model
    import chromadb
    from sentence_transformers import SentenceTransformer

    print(f"RAG: loading embedding model '{CONFIG['embedding_model']}'...",
          file=sys.stderr, flush=True)
    _model = SentenceTransformer(CONFIG["embedding_model"], trust_remote_code=True)
    print(f"RAG: connecting to DB at {CONFIG['db_path']}...",
          file=sys.stderr, flush=True)
    client = chromadb.PersistentClient(path=CONFIG["db_path"])
    _collection = client.get_collection(name=CONFIG["collection"])
    print("RAG: ready!", file=sys.stderr, flush=True)
    return _collection, _model


def _blocking_query(query: str, n: int):
    """Embed the query and search the database (runs in a worker thread)."""
    col, model = _blocking_load()
    embedding = model.encode([query]).tolist()
    return col.query(
        query_embeddings=embedding,
        n_results=n,
        include=["documents", "metadatas", "distances"],
    )


@server.list_tools()
async def list_tools():
    return [
        Tool(
            name="search_revit_api",
            description=(
                "Search Revit 2025 API documentation database. "
                "ALWAYS call this FIRST before using revit-pyrevit tools. "
                "Returns exact API classes, methods, and code examples. "
                "Example queries: 'create wall', 'place door', "
                "'get room area', 'color override element in view', "
                "'create floor from lines', 'set wall height parameter'."
            ),
            inputSchema={
                "type": "object",
                "properties": {
                    "query": {
                        "type": "string",
                        "description": "What you want to do in Revit — natural language"
                    },
                    "n": {
                        "type": "integer",
                        "description": "Number of results (default 5, max 10)",
                        "default": 5
                    }
                },
                "required": ["query"]
            }
        )
    ]


@server.call_tool()
async def call_tool(name: str, arguments: dict):
    if name != "search_revit_api":
        return [TextContent(type="text", text=f"Unknown tool: {name}")]

    query = arguments.get("query", "").strip()
    n = min(int(arguments.get("n", 5)), 10)

    if not query:
        return [TextContent(type="text", text="Error: query is empty.")]

    try:
        # Run in a worker thread so the event loop is never blocked.
        loop = asyncio.get_event_loop()
        results = await loop.run_in_executor(None, _blocking_query, query, n)

        docs = results["documents"][0]
        metas = results["metadatas"][0]
        dists = results["distances"][0]

        if not docs:
            return [TextContent(type="text", text="No relevant API docs found.")]

        parts = []
        for i, (doc, meta, dist) in enumerate(zip(docs, metas, dists)):
            # Metadata keys differ between database builds: custom builds have
            # api_element_name/element_type, the public release has filename/chunk_num.
            api = meta.get("api_element_name") or meta.get("filename") or "—"
            kind = meta.get("element_type") or f"chunk {meta.get('chunk_num', '—')}"
            rel = round((1 - dist) * 100, 1)
            parts.append(
                f"{'━'*50}\n"
                f"Result {i+1} | {api} | {kind} | relevance: {rel}%\n"
                f"{'━'*50}\n{doc}"
            )

        return [TextContent(type="text", text="\n\n".join(parts))]

    except Exception as exc:
        return [TextContent(type="text", text=f"RAG error: {exc}")]


async def main():
    validate_db_layout(Path(CONFIG["db_path"]))

    # Pre-warm model and DB in the background while the server starts.
    loop = asyncio.get_event_loop()
    loop.run_in_executor(None, _blocking_load)

    async with stdio_server() as (read_stream, write_stream):
        await server.run(
            read_stream,
            write_stream,
            server.create_initialization_options()
        )


if __name__ == "__main__":
    asyncio.run(main())
