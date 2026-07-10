#!/usr/bin/env python3
"""
resplan_to_tarkeeb.py
Convert the ResPlan dataset (github.com/m-agour/ResPlan, MIT) into TarkeebAI
training data:

  1. each ResPlan plan (shapely geometries on a 256px canvas)  ->  plan_schema.json
  2. each converted plan  ->  one SFT sample {"prompt": ..., "target": ...}
     where the prompt is the room program + plot size + adjacencies (derived
     from the geometry) and the target is the canonical compact plan JSON.

Designed to run inside the Colab training notebook:

    python tools/resplan_to_tarkeeb.py \
        --pickle ResPlan/ResPlan.pkl \
        --schema schema/plan_schema.json \
        --out data/tarkeeblm \
        --max-plans 20000

Only needs: shapely, jsonschema (networkx optional, for the Kaggle graphs).
"""

import argparse
import json
import pickle
import random
import sys
from pathlib import Path

from shapely.geometry import Polygon, MultiPolygon
from shapely.ops import unary_union

# ResPlan room label -> plan_schema room type
TYPE_MAP = {
    "living": "living",
    "kitchen": "kitchen",
    "bedroom": "bedroom",
    "bathroom": "bathroom",
    "balcony": "balcony",
    "storage": "store",
    "stair": "stair",
}
ROOM_KEYS = list(TYPE_MAP.keys())

# plausible real-world sizes used to sanity-clamp the px->m scale
MIN_DIM_M, MAX_DIM_M = 5.0, 30.0
WALL_DEPTH_M = 0.12          # a ResPlan wall (~4 px) is a light partition


def iter_polys(geom):
    """Yield individual Polygons from Polygon/MultiPolygon/collections."""
    if geom is None or geom.is_empty:
        return
    if isinstance(geom, Polygon):
        yield geom
    elif isinstance(geom, MultiPolygon):
        for g in geom.geoms:
            yield g
    elif hasattr(geom, "geoms"):
        for g in geom.geoms:
            for p in iter_polys(g):
                yield p


def plan_scale(plan) -> float:
    """px -> meters. Prefer wall thickness as the yardstick, clamp by extent."""
    wd = float(plan.get("wall_depth") or 4.0)
    scale = WALL_DEPTH_M / max(wd, 1e-6)
    inner = plan.get("inner")
    if inner is not None and not inner.is_empty:
        minx, miny, maxx, maxy = inner.bounds
        ext = max(maxx - minx, maxy - miny) * scale
        if ext < MIN_DIM_M:
            scale *= MIN_DIM_M / ext
        elif ext > MAX_DIM_M:
            scale *= MAX_DIM_M / ext
    return scale


def poly_to_coords(poly: Polygon, scale: float, ox: float, oy: float, tol_px=2.0):
    """Simplified, origin-shifted, rounded exterior ring (no closing dup)."""
    p = poly.simplify(tol_px, preserve_topology=True)
    coords = list(p.exterior.coords[:-1])
    out = [[round((x - ox) * scale, 2), round((y - oy) * scale, 2)] for x, y in coords]
    # drop consecutive duplicates after rounding
    dedup = [c for i, c in enumerate(out) if c != out[i - 1] or i == 0]
    return dedup


def shared_len(a: Polygon, b: Polygon, buf=2.0) -> float:
    """Length of the boundary the two rooms (nearly) share, in px."""
    try:
        inter = a.buffer(buf).intersection(b.buffer(buf))
        return inter.area / (2 * buf) if not inter.is_empty else 0.0
    except Exception:
        return 0.0


def convert_plan(plan, plan_id):
    """ResPlan dict -> (plan_schema dict, adjacency list) or None."""
    scale = plan_scale(plan)

    rooms_raw = []          # (schema_type, Polygon)
    for key in ROOM_KEYS:
        for poly in iter_polys(plan.get(key)):
            if poly.area * scale * scale < 1.0:      # skip < 1 m2 slivers
                continue
            rooms_raw.append((TYPE_MAP[key], poly))
    if not (3 <= len(rooms_raw) <= 12):
        return None

    # origin = plan bbox min
    allb = unary_union([p for _, p in rooms_raw]).bounds
    ox, oy = allb[0], allb[1]
    width = round((allb[2] - allb[0]) * scale, 2)
    depth = round((allb[3] - allb[1]) * scale, 2)
    if not (MIN_DIM_M <= max(width, depth) <= MAX_DIM_M):
        return None

    type_counts, rooms = {}, []
    for i, (rtype, poly) in enumerate(rooms_raw, start=1):
        coords = poly_to_coords(poly, scale, ox, oy)
        if len(coords) < 3 or len(coords) > 14:
            return None
        type_counts[rtype] = type_counts.get(rtype, 0) + 1
        rooms.append({
            "id": "R{0}".format(i),
            "type": rtype,
            "name": "{0} {1}".format(rtype.title(), type_counts[rtype]),
            "level": "L0",
            "polygon": coords,
        })

    # adjacency from geometry (shared boundary >= ~0.8 m)
    adjacency = []
    for i in range(len(rooms_raw)):
        for j in range(i + 1, len(rooms_raw)):
            if shared_len(rooms_raw[i][1], rooms_raw[j][1]) * scale >= 0.8:
                adjacency.append([rooms[i]["id"], rooms[j]["id"]])

    plan_json = {
        "meta": {
            "name": "ResPlan {0}".format(plan_id),
            "units": "meters",
            "plot": {"width_m": width, "depth_m": depth},
        },
        "levels": [{"id": "L0", "name": "Ground Floor",
                    "elevation_m": 0.0, "height_m": 3.0}],
        "rooms": rooms,
        "walls": [],           # walls derivable from room polygons downstream
        "doors": [],
        "windows": [],
    }
    return plan_json, adjacency


def build_prompt(plan_json, adjacency):
    """The instruction the model will see. Compact, deterministic, English."""
    counts = {}
    id2name = {}
    for r in plan_json["rooms"]:
        counts[r["type"]] = counts.get(r["type"], 0) + 1
        id2name[r["id"]] = r["id"]
    program = ", ".join("{0} {1}".format(n, t if n == 1 else t + "s")
                        for t, n in sorted(counts.items()))
    plot = plan_json["meta"]["plot"]
    adj = "; ".join("{0}-{1}".format(a, b) for a, b in adjacency)
    return ("Design a residential floor plan as JSON (TarkeebAI plan_schema). "
            "Plot: {0} x {1} m. Program: {2}. Required adjacencies: {3}."
            .format(plot["width_m"], plot["depth_m"], program, adj or "none"))


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--pickle", required=True)
    ap.add_argument("--schema", required=True)
    ap.add_argument("--out", required=True)
    ap.add_argument("--max-plans", type=int, default=20000)
    ap.add_argument("--val-frac", type=float, default=0.02)
    ap.add_argument("--seed", type=int, default=17)
    args = ap.parse_args()

    import jsonschema
    schema = json.load(open(args.schema, encoding="utf-8"))
    validator = jsonschema.Draft202012Validator(schema)

    with open(args.pickle, "rb") as f:
        plans = pickle.load(f)
    print("loaded {0} ResPlan plans".format(len(plans)))

    random.seed(args.seed)
    if len(plans) > args.max_plans:
        plans = random.sample(plans, args.max_plans)

    samples, dropped = [], 0
    for i, plan in enumerate(plans):
        try:
            res = convert_plan(plan, i)
        except Exception:
            res = None
        if res is None:
            dropped += 1
            continue
        plan_json, adjacency = res
        if next(validator.iter_errors(plan_json), None) is not None:
            dropped += 1
            continue
        target = json.dumps(plan_json, separators=(",", ":"))
        if len(target) > 6000:            # keep sequences trainable
            dropped += 1
            continue
        samples.append({"prompt": build_prompt(plan_json, adjacency),
                        "target": target})

    random.shuffle(samples)
    n_val = max(50, int(len(samples) * args.val_frac))
    val, train = samples[:n_val], samples[n_val:]

    out = Path(args.out)
    out.mkdir(parents=True, exist_ok=True)
    for name, rows in (("train", train), ("val", val)):
        with open(out / "{0}.jsonl".format(name), "w", encoding="utf-8") as f:
            for r in rows:
                f.write(json.dumps(r, ensure_ascii=False) + "\n")
    print("kept {0} samples ({1} train / {2} val), dropped {3}"
          .format(len(samples), len(train), len(val), dropped))
    print("wrote {0}".format(out))


if __name__ == "__main__":
    sys.exit(main())
