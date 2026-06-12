#!/usr/bin/env python3
"""
Offline tests for the Architext output parser — no model download needed.
Run:  python test_parser.py
"""

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from plan_generator_server import (
    parse_layout, to_meters, layout_to_plan, validate_plan,
    ARCHITEXT_UNITS_PER_METER,
)

# A realistic raw output in the exact format the official Architext demo parses:
# rooms separated by ", ", each "label: (x,y)(x,y)..."
SAMPLE = (
    "living_room: (44,38)(44,81)(87,81)(87,38), "
    "kitchen: (87,38)(87,60)(109,60)(109,38), "
    "bedroom: (109,38)(109,81)(152,81)(152,38), "
    "bedroom: (44,81)(44,124)(87,124)(87,81), "
    "bathroom: (87,60)(87,81)(109,81)(109,60), "
    "corridor: (87,81)(87,124)(152,124)(152,81)"
)

failures = 0

def check(name, condition, detail=""):
    global failures
    status = "PASS" if condition else "FAIL"
    if not condition:
        failures += 1
    print(f"  [{status}] {name}" + (f" — {detail}" if detail and not condition else ""))


print("1. parse_layout")
rooms = parse_layout(SAMPLE)
check("parses all 6 rooms", len(rooms) == 6, f"got {len(rooms)}")
check("two bedrooms found", sum(1 for r in rooms if r["label"] == "bedroom") == 2)
check("4 points per polygon", all(len(r["polygon"]) == 4 for r in rooms))

print("2. to_meters")
rooms_m = to_meters(rooms)
all_pts = [p for r in rooms_m for p in r["polygon"]]
check("origin starts at (0,0)", min(x for x, y in all_pts) == 0 and min(y for x, y in all_pts) == 0)
width = max(x for x, y in all_pts)
check("plausible house width (5-12m)", 5 <= width <= 12, f"width={width}m")
expected_w = round((152 - 44) / ARCHITEXT_UNITS_PER_METER, 2)
check("scale factor applied", abs(width - expected_w) < 0.01, f"{width} vs {expected_w}")

print("3. layout_to_plan")
plan = layout_to_plan(SAMPLE, "a house with two bedrooms and one bathroom")
check("6 rooms in plan", len(plan["rooms"]) == 6)
check("room types mapped", {r["type"] for r in plan["rooms"]} ==
      {"living", "kitchen", "bedroom", "bathroom", "corridor"})
check("walls derived", len(plan["walls"]) > 0, "no walls")
interior = [w for w in plan["walls"] if w["kind"] == "interior"]
check("shared edges became interior walls", len(interior) >= 2, f"got {len(interior)}")
check("description preserved", plan["meta"]["description"].startswith("a house"))

print("4. schema validation")
errors = validate_plan(plan)
check("plan conforms to plan_schema.json", not errors, "; ".join(errors[:3]))

print("5. garbage input")
try:
    layout_to_plan("complete nonsense without any rooms", "x")
    check("raises on garbage", False)
except ValueError:
    check("raises on garbage", True)

print()
if failures:
    print(f"{failures} test(s) FAILED")
    sys.exit(1)
print("All parser tests passed.")
