#!/usr/bin/env python3
"""
Offline self-check for the HouseDiffusion bridge — no torch, no checkpoint, no
GPU. It verifies the two pure-numpy halves that the integration depends on:

  1. build_model_kwargs produces conditioning tensors with exactly the shapes
     and semantics HouseDiffusion expects.
  2. polys_to_plan turns generated coordinates back into a plan_schema.json that
     passes the real schema validator.

We can't run the diffusion model here (that needs a GPU + checkpoint, see the
Colab notebook), so we fabricate plausible normalized coordinates and check the
plumbing around the model. Run:  python test_bridge.py
"""

import json
import sys
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))  # plan-generator/
from housediffusion import graph_to_model_input as g2m  # noqa: E402
from housediffusion import model_output_to_plan as o2p  # noqa: E402
from housediffusion import room_types as rt  # noqa: E402

REPO_ROOT = Path(__file__).resolve().parents[3]
PLAN_SCHEMA = REPO_ROOT / "schema" / "plan_schema.json"
BUBBLE_SCHEMA = REPO_ROOT / "schema" / "bubble_diagram_schema.json"

# A realistic Iraqi-style brief expressed as a bubble diagram.
DIAGRAM = {
    "meta": {"name": "test house", "plot": {"width_m": 10.0, "depth_m": 20.0},
             "description": "guest majlis near entrance, 3 bedrooms, family living"},
    "rooms": [
        {"id": "majlis", "type": "majlis", "corners": 4},
        {"id": "living", "type": "family_living"},          # default corners (6)
        {"id": "kitchen", "type": "kitchen", "corners": 4},
        {"id": "corr", "type": "corridor", "corners": 4},
        {"id": "bed1", "type": "master_bedroom", "corners": 4},
        {"id": "bed2", "type": "bedroom", "corners": 4},
        {"id": "bed3", "type": "bedroom", "corners": 4},
        {"id": "bath1", "type": "bathroom", "corners": 4},
        {"id": "bath2", "type": "wc", "corners": 4},
    ],
    "adjacencies": [
        ["majlis", "corr"], ["living", "corr"], ["kitchen", "living"],
        ["corr", "bed1"], ["corr", "bed2"], ["corr", "bed3"],
        ["bed1", "bath1"], ["corr", "bath2"],
    ],
}


def _check(cond, msg):
    if not cond:
        raise AssertionError(msg)
    print(f"  ok: {msg}")


def test_normalize():
    print("normalize_diagram:")
    norm = g2m.normalize_diagram(DIAGRAM)
    _check(len(norm["rooms"]) == 9, "all 9 rooms kept")
    _check(norm["rooms"][0]["rplan_id"] == 1, "majlis maps to RPLAN living (1)")
    _check(norm["rooms"][1]["corners"] == 6, "family_living gets the default 6 corners")
    _check(norm["rooms"][2]["corners"] == 4, "explicit corner count respected")
    _check(frozenset((0, 3)) in norm["adj"], "majlis-corridor adjacency recorded")
    return norm


def test_build_kwargs():
    print("build_model_kwargs:")
    B = 3
    data_shape, mk, norm = g2m.build_model_kwargs(DIAGRAM, batch_size=B)
    total_corners = sum(r["corners"] for r in norm["rooms"])
    _check(data_shape == (B, 2, rt.MAX_NUM_POINTS), f"data_shape is {data_shape}")
    _check(mk["room_types"].shape == (B, 100, 25), "room_types shape [B,100,25]")
    _check(mk["room_indices"].shape == (B, 100, 32), "room_indices shape [B,100,32]")
    _check(mk["corner_indices"].shape == (B, 100, 32), "corner_indices shape [B,100,32]")
    _check(mk["door_mask"].shape == (B, 100, 100), "door_mask shape [B,100,100]")
    _check(mk["graph"].shape == (B, 200, 3), "graph padded to [B,200,3]")
    # src_key_padding_mask is 0 for real points, 1 for padding -> #zeros == corners
    real = int((mk["src_key_padding_mask"][0] == 0).sum())
    _check(real == total_corners, f"real points ({real}) == total corners ({total_corners})")
    # every real corner belongs to exactly one room type
    rt_rows = mk["room_types"][0][:total_corners]
    _check(np.all(rt_rows.sum(axis=1) == 1), "each real corner has exactly one room type")
    return mk, norm


def _fabricate_coords(norm, mk):
    """Make plausible normalized [-1,1] coords: a small convex polygon per room,
    in the SAME point order build_model_kwargs used (room by room, corner by
    corner). This lets polys_to_plan reconstruct one polygon per room."""
    coords = np.zeros((rt.MAX_NUM_POINTS, 2))
    j = 0
    n = len(norm["rooms"])
    for k, room in enumerate(norm["rooms"]):
        nc = room["corners"]
        cx = -0.8 + 1.6 * (k + 0.5) / n          # spread rooms across the plot
        cy = 0.0
        for c in range(nc):
            ang = 2 * np.pi * c / nc
            coords[j] = [cx + 0.06 * np.cos(ang), cy + 0.06 * np.sin(ang)]
            j += 1
    return coords


def test_output_to_plan(norm, mk):
    print("polys_to_plan + schema validation:")
    import jsonschema
    coords = _fabricate_coords(norm, mk)
    plan = o2p.polys_to_plan(coords, mk, batch_index=0,
                             plot=DIAGRAM["meta"]["plot"],
                             description=DIAGRAM["meta"]["description"])
    _check(len(plan["rooms"]) == len(norm["rooms"]),
           f"{len(plan['rooms'])} rooms out == {len(norm['rooms'])} rooms in")
    _check(len(plan["walls"]) > 0, "walls were derived from room edges")
    for r in plan["rooms"]:
        _check(len(r["polygon"]) >= 3, f"room {r['id']} polygon has >= 3 points")
        for x, y in r["polygon"]:
            _check(0 <= x <= 10 and 0 <= y <= 20, f"room {r['id']} point within 10x20 plot")

    schema = json.loads(PLAN_SCHEMA.read_text(encoding="utf-8"))
    errors = list(jsonschema.Draft202012Validator(schema).iter_errors(plan))
    _check(not errors, "generated plan validates against plan_schema.json"
           + ("" if not errors else ":\n    " + "\n    ".join(e.message for e in errors)))


def test_bubble_schema():
    print("bubble diagram validates against its own schema:")
    import jsonschema
    schema = json.loads(BUBBLE_SCHEMA.read_text(encoding="utf-8"))
    errors = list(jsonschema.Draft202012Validator(schema).iter_errors(DIAGRAM))
    _check(not errors, "DIAGRAM conforms to bubble_diagram_schema.json"
           + ("" if not errors else ":\n    " + "\n    ".join(e.message for e in errors)))


def test_errors():
    print("input validation:")
    for bad, why in [
        ({"rooms": [], "adjacencies": []}, "empty rooms"),
        ({"rooms": [{"id": "a", "type": "spaceship"}], "adjacencies": []}, "unknown type"),
        ({"rooms": [{"id": "a", "type": "living"}, {"id": "a", "type": "kitchen"}],
          "adjacencies": []}, "duplicate id"),
        ({"rooms": [{"id": "a", "type": "living"}], "adjacencies": [["a", "ghost"]]},
         "edge to unknown room"),
    ]:
        try:
            g2m.normalize_diagram(bad)
            raise AssertionError(f"should have rejected: {why}")
        except ValueError:
            print(f"  ok: rejected {why}")


def main():
    norm = test_normalize()
    mk, norm = test_build_kwargs()
    test_output_to_plan(norm, mk)
    test_bubble_schema()
    test_errors()
    print("\nAll bridge self-checks passed.")
    print("(The diffusion model itself runs on a GPU - see "
          "notebooks/HouseDiffusion_TarkeebAI.ipynb.)")


if __name__ == "__main__":
    main()
