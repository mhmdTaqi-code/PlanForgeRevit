# Models & Data — what to download and where it lives

Everything the pipeline needs, with exact locations. Only **one** item is a manual download (the RAG database) — the models fetch themselves on first use.

## Required today (Phases 0–1)

| # | Component | Used by | Size | Min hardware | Source | Where it lives locally |
|---|---|---|---|---|---|---|
| 1 | **Revit 2025 API RAG database** (ChromaDB) | `revit-rag` server | ~700 MB | CPU only, ~2 GB free RAM | [RevitGeminiRAG release v1.0.0-database](https://github.com/ismail-seleit/RevitGeminiRAG/releases/tag/v1.0.0-database) | `data/revit_db/` — **manual download**, layout below |
| 2 | **Snowflake Arctic Embed L v2.0** (embeddings, 1024-dim, 568M params) | `revit-rag` server | ~1.2 GB | **No GPU needed** — CPU + ~3 GB free RAM. With GPU: ~2 GB VRAM | [huggingface.co/Snowflake/snowflake-arctic-embed-l-v2.0](https://huggingface.co/Snowflake/snowflake-arctic-embed-l-v2.0) | HuggingFace cache — **auto-downloaded** on first search |
| 3 | **Architext gptj-162M** (plan generation, 162M params) | `plan-generator` server | ~650 MB | **No GPU needed** — CPU + ~2 GB free RAM. With GPU: ~1 GB VRAM | [huggingface.co/architext/gptj-162M](https://huggingface.co/architext/gptj-162M) | HuggingFace cache — **auto-downloaded** on first `generate_plan` |

### Minimum machine for Phases 0–1

| | Minimum | Comfortable |
|---|---|---|
| RAM | 8 GB (servers load models lazily, one at a time) | 16 GB (both servers warm + Revit open) |
| GPU / VRAM | **none required** — everything runs on CPU | any 2 GB+ VRAM GPU speeds up search and generation (`device: cuda` is picked automatically) |
| Disk | ~5 GB free | 10 GB (room for HF cache growth) |
| CPU-only latency to expect | first query/generation: a few seconds | — |

### 1. RAG database — manual download, exact layout

Download the six release assets and arrange them **exactly** like this (the five index files go inside a folder named after the vector segment UUID — see [getting-started.md](getting-started.md#2-download-the-rag-database)):

```
data/revit_db/
├── chroma.sqlite3
└── 1ccb803a-3d67-4028-a8e8-35b549456170/
    ├── data_level0.bin
    ├── header.bin
    ├── index_metadata.pickle
    ├── length.bin
    └── link_lists.bin
```

Different location? Set `db_path` in `mcp-servers/revit-rag/config.json` or the `REVIT_RAG_DB_PATH` env var.

### 2–3. HuggingFace models — automatic

Both models download to the standard HuggingFace cache on first use and never re-download:

- Windows: `C:\Users\<you>\.cache\huggingface\hub`
- Linux/macOS: `~/.cache/huggingface/hub`

To relocate the cache (e.g. small system drive), set the `HF_HOME` environment variable before starting the servers. To use a model you already have on disk, point the config at its folder path instead of the hub id:

| Config key | File | Default |
|---|---|---|
| `embedding_model` | `mcp-servers/revit-rag/config.json` | `Snowflake/snowflake-arctic-embed-l-v2.0` |
| `model` | `mcp-servers/plan-generator/config.json` | `architext/gptj-162M` |

> ⚠️ `embedding_model` must always match the model the database was built with — the prebuilt database above was built with Arctic Embed L v2.0. Swapping it breaks search silently.

## The executor (separate install, not part of this repo)

| Component | Purpose | Source |
|---|---|---|
| **pyRevit** | Revit scripting runtime | [github.com/pyrevitlabs/pyRevit](https://github.com/pyrevitlabs/pyRevit) |
| **revit-mcp-server** (pyRevit extension) | MCP tools inside Revit (`create_wall`, `create_level`, ... — takes millimeters) | [github.com/Demolinator/revit-mcp-server](https://github.com/Demolinator/revit-mcp-server) → `%APPDATA%\pyRevit\Extensions\` |

## Coming in later phases (not needed yet)

| Phase | Component | Purpose | Min hardware | Source |
|---|---|---|---|---|
| 2 | **HouseDiffusion** + checkpoints | vector plan generation from bubble diagrams | GPU required for sane speed: ~6–8 GB VRAM (free Colab/Kaggle **T4 16 GB** is plenty) | [github.com/aminshabani/house_diffusion](https://github.com/aminshabani/house_diffusion) |
| 2 (optional) | **GSDiff** (AAAI 2025) | generation within plot boundary constraints | same class as HouseDiffusion — run on Colab/Kaggle T4 | [github.com/SizheHu/GSDiff](https://github.com/SizheHu/GSDiff) |
| 3 | **ResPlan dataset** | 17k vector plans to mix with the Iraqi dataset | n/a (data, ~ a few GB disk) | [github.com/m-agour/ResPlan](https://github.com/m-agour/ResPlan) / Kaggle |
| 3 | **Qwen2.5-3B-Instruct** (or Llama-3.2-3B) | base model for the Iraqi/Gulf fine-tune | **training**: LoRA 4-bit needs ~12 GB VRAM → fits the free **T4 16 GB** (that's why a 3B model was chosen). **inference**: 4-bit ~3 GB VRAM, or CPU with 8 GB RAM | [huggingface.co/Qwen/Qwen2.5-3B-Instruct](https://huggingface.co/Qwen/Qwen2.5-3B-Instruct) |

## Disk budget

| | |
|---|---|
| RAG database | ~0.7 GB |
| Arctic embeddings model | ~1.2 GB |
| Architext model | ~0.65 GB |
| torch + transformers (pip) | ~2.5 GB |
| **Total (Phases 0–1)** | **~5 GB** |
