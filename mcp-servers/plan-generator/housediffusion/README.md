# `housediffusion` — the TarkeebAI ⇄ HouseDiffusion bridge

This package is the reusable glue between TarkeebAI and
[HouseDiffusion](https://github.com/aminshabani/house_diffusion) (the source
lives in [`AIProjects/house_diffusion/`](../../../AIProjects/house_diffusion)).

## Why a bridge is needed

HouseDiffusion is a strong *vector* floor-plan generator, but its input is **not
text and not an image** — it is conditioned on a **room-adjacency graph** (a
"bubble diagram"). So the integration is:

```
user brief (text)
   │   ← the orchestrating LLM (Claude / Antigravity) writes the graph
   ▼
bubble diagram  ──► graph_to_model_input ──► HouseDiffusion ──► model_output_to_plan ──► plan_schema.json
   (rooms + adjacencies)        (engine: torch + checkpoint + GPU)
```

**This is why we do not add CLIP.** CLIP aligns *images* with *text*;
HouseDiffusion consumes neither — it consumes a graph. The text→graph step is a
language task the LLM already does well, so the right "translator" is the
orchestrator, not a CLIP encoder.

## Modules

| File | Depends on | Role |
|---|---|---|
| `room_types.py` | — | TarkeebAI ⇄ RPLAN room-class maps + corner-count defaults. **The only file to edit if you retrain on a new dataset.** |
| `graph_to_model_input.py` | numpy | bubble diagram → HouseDiffusion conditioning tensors (faithful to its `eval`/synthesis path) |
| `model_output_to_plan.py` | numpy | generated coordinates → `plan_schema.json` (un-normalize, scale to meters, derive walls) |
| `engine.py` | torch + checkpoint + HouseDiffusion source | loads the model and runs the diffusion sampler |
| `test_bridge.py` | numpy + jsonschema | offline self-check of the two numpy halves (no GPU) |

`graph_to_model_input` and `model_output_to_plan` are pure numpy, so the bridge
is verified without a GPU:

```bash
python mcp-servers/plan-generator/housediffusion/test_bridge.py
```

## Running the model

HouseDiffusion needs a GPU + a checkpoint, so the intended runner is
[`notebooks/HouseDiffusion_TarkeebAI.ipynb`](../../../notebooks/HouseDiffusion_TarkeebAI.ipynb)
(Colab/Kaggle T4). To run locally, set two env vars and the engine picks it up:

```bash
set HOUSE_DIFFUSION_CKPT=C:\path\to\model.pt      # required
set HOUSE_DIFFUSION_SRC=...\AIProjects\house_diffusion   # optional (auto-detected)
```

Then the `plan_from_bubble_diagram` MCP tool runs it. If the checkpoint/torch is
missing, that tool reports exactly what's missing and falls back to advising
Colab — it never crashes the server.

## Limitations (Phase 2 scaffold)

- The model is **RPLAN-trained** (Chinese apartment typology). Iraqi/Gulf
  features (majlis, hosh, single-façade 10×20) are approximated by the nearest
  RPLAN class — Phase 3 fine-tunes a model on real Iraqi plans.
- Corner counts default to 4 (rectangle), 6 for living rooms; override per room
  via the bubble diagram's `corners` field.
- Generated polygons are raw model output (axis-aligned cleanup / wall snapping
  is left to the executor and the `bim-best-practices` skill).
