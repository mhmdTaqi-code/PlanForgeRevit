"""
HouseDiffusion sampled coordinates  ->  TarkeebAI plan_schema.json.

The model emits corner coordinates in normalized [-1, 1] space, grouped per
room by the `room_indices` conditioning. This module un-normalizes them to a
real plot in meters, rebuilds one polygon per room, and derives wall
centerlines from the polygon edges — producing exactly the same plan_schema
dict that the Architext generator produces, so the rest of the pipeline
(validate_plan, the Revit executor) does not change.

Pure numpy. The un-normalization mirrors `save_samples` in
AIProjects/house_diffusion/scripts/image_sample.py (point/2 + 0.5), with two
TarkeebAI-specific steps added: scale to the plot size in meters, and flip Y so
the result is Y-up (plan_schema convention) instead of image Y-down.
"""

import numpy as np

from . import room_types as rt

DEFAULT_PLOT = {"width_m": 10.0, "depth_m": 20.0}
DOOR_CLASS_IDS = {11, 12, 13}


def _dedupe(points):
    """Drop consecutive duplicate points (after rounding)."""
    out = []
    for p in points:
        if not out or (abs(p[0] - out[-1][0]) > 1e-6 or abs(p[1] - out[-1][1]) > 1e-6):
            out.append(p)
    if len(out) > 1 and out[0] == out[-1]:
        out.pop()
    return out


def _split_rooms(coords, room_types_oh, room_indices_oh, padding_mask):
    """Group corner points into rooms, mirroring save_samples' grouping logic."""
    rooms = []
    poly, cur_type = [], None
    prev_index = None
    for j in range(len(coords)):
        if padding_mask[j] == 1:        # padding point -> stop
            break
        index = np.argmax(room_indices_oh[j])
        if prev_index is not None and index != prev_index and poly:
            rooms.append((cur_type, poly))
            poly = []
        poly.append((float(coords[j][0]), float(coords[j][1])))
        cur_type = int(np.argmax(room_types_oh[j]))
        prev_index = index
    if poly:
        rooms.append((cur_type, poly))
    return rooms


def derive_walls(rooms, level="L0"):
    """Room polygon edges -> wall centerlines (shared edge = interior wall).

    Same rule as the Architext generator: an edge belonging to two rooms is one
    interior wall; an edge belonging to one room is exterior.
    """
    edge_count = {}
    for room in rooms:
        poly = room["polygon"]
        for i in range(len(poly)):
            p1, p2 = tuple(poly[i]), tuple(poly[(i + 1) % len(poly)])
            if p1 == p2:
                continue
            edge_count.setdefault(tuple(sorted([p1, p2])), 0)
            edge_count[tuple(sorted([p1, p2]))] += 1

    walls = []
    for i, ((p1, p2), count) in enumerate(sorted(edge_count.items()), start=1):
        kind = "interior" if count > 1 else "exterior"
        walls.append({
            "id": f"W{i}", "level": level,
            "start": list(p1), "end": list(p2),
            "thickness_m": 0.12 if kind == "interior" else 0.24,
            "height_m": 3.0, "kind": kind,
        })
    return walls


def polys_to_plan(sample_coords, model_kwargs, batch_index=0, plot=None,
                  description="", name="HouseDiffusion generated plan"):
    """Convert one generated sample to a plan_schema dict.

    sample_coords : array [N, 2] of the final-timestep coordinates in [-1, 1]
                    (i.e. sample[-1][batch_index] after permuting to [...,N,2]).
    model_kwargs  : the numpy conditioning dict from build_model_kwargs
                    (or torch tensors moved to cpu/numpy).
    """
    plot = plot or DEFAULT_PLOT
    w, d = float(plot["width_m"]), float(plot["depth_m"])

    def as_np(x):
        return x.detach().cpu().numpy() if hasattr(x, "detach") else np.asarray(x)

    coords = as_np(sample_coords)
    room_types_oh = as_np(model_kwargs["room_types"])[batch_index]
    room_indices_oh = as_np(model_kwargs["room_indices"])[batch_index]
    padding = as_np(model_kwargs["src_key_padding_mask"])[batch_index]
    # src_key_padding_mask is 0 for real points, 1 for padding.

    rooms = []
    type_counts = {}
    for rclass, raw_poly in _split_rooms(coords, room_types_oh, room_indices_oh, padding):
        if rclass == 0 or rclass in DOOR_CLASS_IDS:
            continue
        # un-normalize: [-1,1] -> [0,1] -> meters; flip Y to Y-up.
        poly_m = []
        for x, y in raw_poly:
            ux, uy = x / 2 + 0.5, y / 2 + 0.5
            poly_m.append([round(ux * w, 2), round((1 - uy) * d, 2)])
        poly_m = _dedupe(poly_m)
        if len(poly_m) < 3:
            continue
        schema_type = rt.RPLAN_TO_SCHEMA.get(rclass, "other")
        type_counts[schema_type] = type_counts.get(schema_type, 0) + 1
        rooms.append({
            "id": f"R{len(rooms) + 1}",
            "type": schema_type,
            "name": f"{schema_type.replace('_', ' ').title()} {type_counts[schema_type]}",
            "level": "L0",
            "polygon": poly_m,
        })

    if not rooms:
        raise ValueError("no usable rooms in the generated sample")

    return {
        "meta": {
            "name": name,
            "units": "meters",
            "plot": {"width_m": w, "depth_m": d},
            "description": description,
        },
        "levels": [
            {"id": "L0", "name": "Ground Floor", "elevation_m": 0.0, "height_m": 3.0}
        ],
        "rooms": rooms,
        "walls": derive_walls(rooms),
        "doors": [],
        "windows": [],
    }
