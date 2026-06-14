"""
TarkeebAI ⇄ HouseDiffusion bridge (Phase 2).

HouseDiffusion (Shabani et al., 2022) generates *vector* floor plans, but its
input is NOT text and NOT an image — it is a room-adjacency graph (a "bubble
diagram"). This package is the reusable glue that lets any MCP agent drive it:

    bubble diagram (rooms + adjacencies)        <- the LLM writes this from text
        │  graph_to_model_input.build_model_kwargs
        ▼
    HouseDiffusion model_kwargs tensors
        │  engine.sample  (needs torch + a checkpoint; runs on Colab/Kaggle GPU)
        ▼
    normalized room polygons
        │  model_output_to_plan.polys_to_plan
        ▼
    plan_schema.json   (the same format Architext produces, so the rest of the
                        TarkeebAI pipeline — validate_plan, the Revit executor —
                        is unchanged)

`graph_to_model_input` and `model_output_to_plan` are pure-numpy and have no
torch dependency, so they are unit-tested offline (see test_bridge.py). Only
`engine` needs torch + the HouseDiffusion source on the path.
"""

from .room_types import SCHEMA_TO_RPLAN, RPLAN_TO_SCHEMA, DEFAULT_CORNERS

__all__ = ["SCHEMA_TO_RPLAN", "RPLAN_TO_SCHEMA", "DEFAULT_CORNERS"]
