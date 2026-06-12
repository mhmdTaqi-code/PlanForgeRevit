# Revit 2025 API RAG Database

The ChromaDB database files are **not stored in git** (~700 MB). Download them from the
[RevitGeminiRAG v1.0.0-database release](https://github.com/ismail-seleit/RevitGeminiRAG/releases/tag/v1.0.0-database)
and arrange them **exactly** like this:

```
data/revit_db/
├── chroma.sqlite3
└── 1ccb803a-3d67-4028-a8e8-35b549456170/   ← create this folder yourself
    ├── data_level0.bin
    ├── header.bin
    ├── index_metadata.pickle
    ├── length.bin
    └── link_lists.bin
```

> ⚠️ The release assets download as flat files, but ChromaDB requires the five
> index files to be inside a subfolder named after the vector segment UUID
> (`1ccb803a-3d67-4028-a8e8-35b549456170` for this prebuilt database).
> If they are left flat, the server will refuse to start and tell you how to fix it.

Database contents: the full Revit 2025 API documentation, chunked and embedded with
[Snowflake/snowflake-arctic-embed-l-v2.0](https://huggingface.co/Snowflake/snowflake-arctic-embed-l-v2.0)
(1024 dimensions), collection name `revit_api_2025_chunked`.

Credit: [Ismail Seleit — RevitGeminiRAG](https://github.com/ismail-seleit/RevitGeminiRAG) (MIT).
