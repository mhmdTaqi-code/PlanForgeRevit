# Phase 2 — Quality upgrade with HouseDiffusion

**Goal: replace the simple Architext generator with a research-grade model that
outputs *vector* plans (precise polygons per room) — the ideal format to build
in Revit.**

Phase 1 (Architext) proved the chain works. Phase 2 raises plan quality with
[HouseDiffusion](https://arxiv.org/abs/2211.13287) while keeping the rest of the
pipeline — `plan_schema.json`, `validate_plan`, the Revit executor — unchanged.

## The key idea: HouseDiffusion speaks *graphs*, not text

HouseDiffusion does not read natural language or images. It is conditioned on a
**bubble diagram**: rooms as nodes, "this room is next to that room" as edges.
So the layers split cleanly:

```
"guest majlis near the entrance, 3 bedrooms, family living"
        │
        ▼  Layer 2 — the orchestrating LLM writes a bubble diagram
{ rooms: [...], adjacencies: [...] }          (schema/bubble_diagram_schema.json)
        │
        ▼  plan_from_bubble_diagram (MCP tool) → housediffusion bridge → model
plan JSON  (rooms with vector polygons in meters + derived walls)
        │
        ▼  validate_plan → your MCP agent + search_revit_api + pyRevit
walls / levels inside Revit
```

> **Why not CLIP?** A natural question is "if the model doesn't understand text,
> add CLIP." CLIP aligns **images** with **text** — but HouseDiffusion's input
> is a **graph**, not an image, so CLIP has nothing to plug into. The correct
> translator from text to graph is the LLM you're already orchestrating with.
> See [`mcp-servers/plan-generator/housediffusion/README.md`](../mcp-servers/plan-generator/housediffusion/README.md).

## What ships in this repo

- **The bridge** — [`mcp-servers/plan-generator/housediffusion/`](../mcp-servers/plan-generator/housediffusion/):
  `graph_to_model_input` (graph → model tensors), `model_output_to_plan`
  (polygons → `plan_schema.json`), and `engine` (loads + runs the model).
- **The bubble-diagram contract** — [`schema/bubble_diagram_schema.json`](../schema/bubble_diagram_schema.json).
- **A new MCP tool** — `plan_from_bubble_diagram` on the `plan-generator` server.
- **A Colab notebook** — [`notebooks/HouseDiffusion_TarkeebAI.ipynb`](../notebooks/HouseDiffusion_TarkeebAI.ipynb).
- **The HouseDiffusion source** — vendored in [`AIProjects/house_diffusion/`](../AIProjects/house_diffusion).

## Run it (Colab/Kaggle — recommended)

HouseDiffusion needs a GPU. Open the notebook in Colab, set the runtime to GPU,
and run top to bottom: it clones this repo, downloads a checkpoint, and turns a
bubble diagram into a validated `plan_schema.json`. Only `torch` + `numpy` are
needed for sampling — the notebook deliberately **skips** HouseDiffusion's old
pinned `requirements.txt` (TensorFlow / mpi4py / nightly torch), which the
generation path never touches.

## Run it through the MCP tool

The `plan_from_bubble_diagram` tool runs the model when a checkpoint is
available locally:

```bash
# Windows
set HOUSE_DIFFUSION_CKPT=C:\path\to\model.pt
```

Then the orchestrator calls it with a bubble diagram. **Without** a local
checkpoint/GPU, the tool still validates the diagram and returns clear
instructions to use the notebook — it never errors out, so the agent can fall
back to `generate_plan` (Architext, CPU) automatically.

## Verify the bridge offline (no GPU)

The numpy halves — graph→tensors and polygons→schema — are unit-tested without
the model:

```bash
python mcp-servers/plan-generator/housediffusion/test_bridge.py
```

## Getting a checkpoint

| Source | Notes |
|---|---|
| HouseDiffusion temporary RPLAN model | Google Drive link in the [HouseDiffusion README](https://github.com/aminshabani/house_diffusion#readme) (the notebook downloads it with `gdown`). RPLAN typology — foreign, but proves the pipeline. |
| Your own fine-tune (Phase 3) | The Iraqi/Gulf model is the project's headline deliverable. Point `HOUSE_DIFFUSION_CKPT` at it; nothing else changes. |

## Limitations (by design, this phase)

- **Foreign typology** — RPLAN is Chinese apartments; Iraqi features are
  approximated by the nearest class (`majlis`→living, `hosh`→balcony, …). Fixed
  in Phase 3 by fine-tuning, see [the roadmap](../README.md#roadmap).
- **Doors/windows** — derived later (from adjacencies + the executor), like
  Phase 1; the polygons and walls are the model's contribution.
- **GPU for sane speed** — CPU sampling is possible but slow; use Colab/Kaggle.
