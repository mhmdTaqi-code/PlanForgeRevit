#!/usr/bin/env python3
"""
plan_generator_server.py
MCP server exposing two tools:

  generate_plan  — natural-language description -> floor plan JSON
                   (TarkeebAI plan_schema.json format), powered by the
                   Architext gptj-162M model (fully local, no API keys).
  validate_plan  — check any plan JSON against schema/plan_schema.json.

Configuration is resolved in this order (highest priority first):
  1. Environment variables:  PLAN_GEN_MODEL, PLAN_GEN_DEVICE
  2. config.json next to this script (copy config.example.json)
  3. Built-in defaults (model auto-downloads from HuggingFace)

Manual testing without any MCP client:
  python plan_generator_server.py --test "a house with three bedrooms and two bathrooms"

See docs/phase-1-pipeline.md for the full walkthrough.
"""

import asyncio
import json
import os
import re
import sys
from pathlib import Path

SCRIPT_DIR = Path(__file__).resolve().parent
REPO_ROOT = SCRIPT_DIR.parent.parent
SCHEMA_PATH = REPO_ROOT / "schema" / "plan_schema.json"

DEFAULTS = {
    "model": "architext/gptj-162M",
    # "auto" picks cuda if available, otherwise cpu. The model is only 162M
    # parameters, so cpu is perfectly fine.
    "device": "auto",
}

# Architext was trained with coordinates on a fixed grid; dividing by this
# factor yields meters (taken from the official demo app).
ARCHITEXT_UNITS_PER_METER = 14.2

# Architext room labels -> plan_schema.json room types
ARCHITEXT_TO_SCHEMA = {
    "living_room": "living",
    "kitchen": "kitchen",
    "bedroom": "bedroom",
    "bathroom": "bathroom",
    "closet": "store",
    "balcony": "balcony",
    "corridor": "corridor",
    "dining_room": "dining",
    "laundry_room": "laundry",
    "missing": "other",
}

CREATIVITY = {
    "low": {"top_p": 0.95, "top_k": 10},
    "medium": {"top_p": 0.9, "top_k": 50},
    "high": {"top_p": 0.85, "top_k": 100},
}

# Architext understands spelled-out numbers better than digits.
NUM_WORDS = {
    "0": "zero", "1": "one", "2": "two", "3": "three", "4": "four",
    "5": "five", "6": "six", "7": "seven", "8": "eight", "9": "nine",
    "10": "ten", "11": "eleven", "12": "twelve",
}

ROOM_RE = re.compile(r"([a-z_]+)\s*:\s*((?:\([^)]*\))+)")
POINT_RE = re.compile(r"\(([^)]*)\)")


def load_config() -> dict:
    config = dict(DEFAULTS)

    config_path = Path(os.environ.get("PLAN_GEN_CONFIG", SCRIPT_DIR / "config.json"))
    if config_path.is_file():
        with open(config_path, encoding="utf-8") as f:
            config.update({k: v for k, v in json.load(f).items() if v})

    for key, env in [("model", "PLAN_GEN_MODEL"), ("device", "PLAN_GEN_DEVICE")]:
        if os.environ.get(env):
            config[key] = os.environ[env]

    return config


# ─────────────────────────────────────────────────────────
# Parsing: raw Architext output -> plan_schema.json
# ─────────────────────────────────────────────────────────

def parse_layout(layout_text: str) -> list[dict]:
    """Parse 'living_room: (x,y)(x,y)..., bedroom: ...' into raw room dicts."""
    rooms = []
    for label, points_blob in ROOM_RE.findall(layout_text):
        if label not in ARCHITEXT_TO_SCHEMA:
            continue
        polygon = []
        for blob in POINT_RE.findall(points_blob):
            parts = blob.split(",")
            if len(parts) != 2:
                continue
            try:
                polygon.append((float(parts[0]), float(parts[1])))
            except ValueError:
                continue
        if len(polygon) >= 3:
            rooms.append({"label": label, "polygon": polygon})
    return rooms


def to_meters(rooms: list[dict]) -> list[dict]:
    """Scale to meters, flip Y (image space is y-down), move origin to (0,0)."""
    all_points = [p for r in rooms for p in r["polygon"]]
    max_y = max(p[1] for p in all_points)
    min_x = min(p[0] for p in all_points)
    min_y = min(max_y - p[1] for p in all_points)

    result = []
    for room in rooms:
        polygon = [
            [
                round((x - min_x) / ARCHITEXT_UNITS_PER_METER, 2),
                round((max_y - y - min_y) / ARCHITEXT_UNITS_PER_METER, 2),
            ]
            for x, y in room["polygon"]
        ]
        result.append({"label": room["label"], "polygon": polygon})
    return result


def derive_walls(rooms: list[dict], level: str = "L0") -> list[dict]:
    """Turn room polygon edges into wall centerlines.

    An edge shared by exactly two rooms becomes one interior wall; an edge
    that belongs to a single room becomes an exterior wall. Partially
    overlapping (non-identical) edges are kept as-is — good enough for the
    v0.1 proof of concept.
    """
    edge_count: dict[tuple, int] = {}
    for room in rooms:
        poly = room["polygon"]
        for i in range(len(poly)):
            p1, p2 = tuple(poly[i]), tuple(poly[(i + 1) % len(poly)])
            if p1 == p2:
                continue
            key = tuple(sorted([p1, p2]))
            edge_count[key] = edge_count.get(key, 0) + 1

    walls = []
    for i, ((p1, p2), count) in enumerate(sorted(edge_count.items()), start=1):
        kind = "interior" if count > 1 else "exterior"
        walls.append({
            "id": f"W{i}",
            "level": level,
            "start": list(p1),
            "end": list(p2),
            "thickness_m": 0.12 if kind == "interior" else 0.24,
            "height_m": 3.0,
            "kind": kind,
        })
    return walls


def layout_to_plan(layout_text: str, description: str) -> dict:
    """Full conversion: raw Architext layout text -> plan_schema.json dict."""
    raw_rooms = parse_layout(layout_text)
    if not raw_rooms:
        raise ValueError("no rooms could be parsed from the model output")

    rooms_m = to_meters(raw_rooms)

    type_counts: dict[str, int] = {}
    rooms = []
    for i, room in enumerate(rooms_m, start=1):
        room_type = ARCHITEXT_TO_SCHEMA[room["label"]]
        type_counts[room_type] = type_counts.get(room_type, 0) + 1
        rooms.append({
            "id": f"R{i}",
            "type": room_type,
            "name": f"{room['label'].replace('_', ' ').title()} {type_counts[room_type]}",
            "level": "L0",
            "polygon": room["polygon"],
        })

    return {
        "meta": {
            "name": "Architext generated plan",
            "units": "meters",
            "description": description,
        },
        "levels": [
            {"id": "L0", "name": "Ground Floor", "elevation_m": 0.0, "height_m": 3.0}
        ],
        "rooms": rooms,
        "walls": derive_walls([{"polygon": r["polygon"]} for r in rooms]),
        "doors": [],
        "windows": [],
    }


def validate_plan(plan: dict) -> list[str]:
    """Validate a plan dict against plan_schema.json. Returns error list."""
    import jsonschema

    with open(SCHEMA_PATH, encoding="utf-8") as f:
        schema = json.load(f)
    validator = jsonschema.Draft202012Validator(schema)
    return [
        f"{'/'.join(str(p) for p in e.absolute_path) or '<root>'}: {e.message}"
        for e in validator.iter_errors(plan)
    ]


# ─────────────────────────────────────────────────────────
# Model loading / generation
# ─────────────────────────────────────────────────────────

CONFIG = load_config()

_model = None
_tokenizer = None


def _digits_to_words(text: str) -> str:
    return " ".join(NUM_WORDS.get(word, word) for word in text.split(" "))


def _blocking_load():
    """Load Architext (runs in a worker thread)."""
    global _model, _tokenizer
    if _model is not None:
        return _model, _tokenizer
    import torch
    from transformers import AutoConfig, AutoTokenizer, AutoModelForCausalLM

    device = CONFIG["device"]
    if device == "auto":
        device = "cuda" if torch.cuda.is_available() else "cpu"

    print(f"PlanGen: loading model '{CONFIG['model']}' on {device}...",
          file=sys.stderr, flush=True)
    _tokenizer = AutoTokenizer.from_pretrained(CONFIG["model"])

    model_config = AutoConfig.from_pretrained(CONFIG["model"])
    # The Architext checkpoint declares rotary_dim=64 (copied from GPT-J-6B)
    # but its head dim is only 48. Old transformers sized the rotary table
    # from the tensor, modern versions from the config — clamp to match.
    head_dim = getattr(model_config, "n_embd", 0) // max(getattr(model_config, "n_head", 1), 1)
    if getattr(model_config, "rotary_dim", None) and head_dim and model_config.rotary_dim > head_dim:
        model_config.rotary_dim = head_dim

    _model = AutoModelForCausalLM.from_pretrained(
        CONFIG["model"], config=model_config
    ).to(device)
    print("PlanGen: ready!", file=sys.stderr, flush=True)
    return _model, _tokenizer


def _blocking_generate(description: str, creativity: str, max_attempts: int = 3) -> dict:
    """Generate a plan, retrying on unparseable samples (runs in a worker thread)."""
    model, tokenizer = _blocking_load()
    params = CREATIVITY.get(creativity, CREATIVITY["medium"])

    prompt = f"[User prompt] {_digits_to_words(description.strip())} [Layout]"
    inputs = tokenizer(prompt, return_tensors="pt").to(model.device)

    last_error = None
    for _ in range(max_attempts):
        output = model.generate(
            **inputs,
            do_sample=True,
            top_p=params["top_p"],
            top_k=params["top_k"],
            eos_token_id=50256,
            max_length=400,
            pad_token_id=50256,
        )
        text = tokenizer.batch_decode(output, skip_special_tokens=True)[0]
        layout_text = text.split("[Layout]")[-1]
        try:
            return layout_to_plan(layout_text, description)
        except ValueError as exc:
            last_error = exc
    raise ValueError(f"failed after {max_attempts} attempts: {last_error}")


# ─────────────────────────────────────────────────────────
# MCP server
# ─────────────────────────────────────────────────────────

from mcp.server import Server
from mcp.server.stdio import stdio_server
from mcp.types import Tool, TextContent

server = Server("plan-generator")


@server.list_tools()
async def list_tools():
    return [
        Tool(
            name="generate_plan",
            description=(
                "Generate a residential floor plan from a natural-language "
                "description. Returns plan JSON (TarkeebAI plan_schema.json "
                "format): levels, rooms with polygons in meters, and walls. "
                "After generating, validate with validate_plan, then build it "
                "in Revit using the revit-rag and pyRevit tools. "
                "Example descriptions: 'a house with three bedrooms and two "
                "bathrooms', 'the kitchen is adjacent to the dining room'."
            ),
            inputSchema={
                "type": "object",
                "properties": {
                    "description": {
                        "type": "string",
                        "description": "The house description in natural language (English)"
                    },
                    "creativity": {
                        "type": "string",
                        "enum": ["low", "medium", "high"],
                        "description": "Sampling diversity (default medium)",
                        "default": "medium"
                    }
                },
                "required": ["description"]
            }
        ),
        Tool(
            name="plan_from_bubble_diagram",
            description=(
                "Generate a floor plan with HouseDiffusion (Phase 2, higher "
                "quality than generate_plan) from a BUBBLE DIAGRAM, not from "
                "text. HouseDiffusion does not read language — so YOU (the "
                "agent) first translate the user's brief into a graph: a list "
                "of rooms (each with an 'id' and a 'type' from the plan schema "
                "vocabulary, optionally 'corners') and a list of 'adjacencies' "
                "(pairs of room ids that share a wall / a door). See "
                "schema/bubble_diagram_schema.json. Returns the same plan JSON "
                "as generate_plan. If the HouseDiffusion model is not installed "
                "locally (it needs a GPU + checkpoint), this returns the "
                "validated diagram plus instructions to run it on Colab. "
                "Example diagram: {\"meta\":{\"plot\":{\"width_m\":10,"
                "\"depth_m\":20}},\"rooms\":[{\"id\":\"maj\",\"type\":"
                "\"majlis\"},{\"id\":\"liv\",\"type\":\"living\"}],"
                "\"adjacencies\":[[\"maj\",\"liv\"]]}."
            ),
            inputSchema={
                "type": "object",
                "properties": {
                    "diagram": {
                        "type": "string",
                        "description": "The bubble diagram as a JSON string (bubble_diagram_schema.json)"
                    },
                    "num_samples": {
                        "type": "integer",
                        "description": "How many variations to sample; the first is returned (default 1)",
                        "default": 1
                    }
                },
                "required": ["diagram"]
            }
        ),
        Tool(
            name="validate_plan",
            description=(
                "Validate floor-plan JSON against the TarkeebAI plan schema. "
                "Call this on any plan before building it in Revit, including "
                "plans you edited yourself. Returns OK or a list of errors."
            ),
            inputSchema={
                "type": "object",
                "properties": {
                    "plan": {
                        "type": "string",
                        "description": "The plan as a JSON string"
                    }
                },
                "required": ["plan"]
            }
        ),
    ]


@server.call_tool()
async def call_tool(name: str, arguments: dict):
    try:
        if name == "generate_plan":
            description = arguments.get("description", "").strip()
            if not description:
                return [TextContent(type="text", text="Error: description is empty.")]
            creativity = arguments.get("creativity", "medium")

            loop = asyncio.get_event_loop()
            plan = await loop.run_in_executor(
                None, _blocking_generate, description, creativity
            )
            return [TextContent(type="text", text=json.dumps(plan, indent=2))]

        if name == "plan_from_bubble_diagram":
            try:
                diagram = json.loads(arguments.get("diagram", ""))
            except json.JSONDecodeError as exc:
                return [TextContent(type="text", text=f"Invalid diagram JSON: {exc}")]
            num_samples = int(arguments.get("num_samples", 1) or 1)

            from housediffusion import graph_to_model_input as g2m
            from housediffusion import engine as hd_engine

            # Validate the graph first — clear errors are better than a model crash.
            try:
                g2m.normalize_diagram(diagram)
            except ValueError as exc:
                return [TextContent(type="text", text=f"Invalid bubble diagram: {exc}")]

            status = hd_engine.availability()
            if not status["ready"]:
                msg = (
                    "The bubble diagram is valid, but the HouseDiffusion model "
                    "is not runnable here:\n- "
                    + "\n- ".join(status["missing"])
                    + "\n\nRun it on a GPU with notebooks/HouseDiffusion_TarkeebAI.ipynb "
                    "(Colab/Kaggle), or set HOUSE_DIFFUSION_CKPT to a local "
                    "checkpoint. Meanwhile you can use generate_plan (Architext) "
                    "for a CPU-only plan.\n\nValidated diagram:\n"
                    + json.dumps(diagram, ensure_ascii=False, indent=2)
                )
                return [TextContent(type="text", text=msg)]

            loop = asyncio.get_event_loop()
            plan = await loop.run_in_executor(
                None, hd_engine.generate_from_diagram, diagram, num_samples
            )
            errors = validate_plan(plan)
            footer = "" if not errors else "\n\n(WARNING: schema issues: " + "; ".join(errors) + ")"
            return [TextContent(type="text", text=json.dumps(plan, indent=2) + footer)]

        if name == "validate_plan":
            try:
                plan = json.loads(arguments.get("plan", ""))
            except json.JSONDecodeError as exc:
                return [TextContent(type="text", text=f"Invalid JSON: {exc}")]
            errors = validate_plan(plan)
            if errors:
                return [TextContent(type="text", text="Validation FAILED:\n- " + "\n- ".join(errors))]
            return [TextContent(type="text", text="Validation OK: plan conforms to plan_schema.json")]

        return [TextContent(type="text", text=f"Unknown tool: {name}")]

    except Exception as exc:
        return [TextContent(type="text", text=f"PlanGen error: {exc}")]


async def main():
    # Pre-warm the model in the background while the server starts.
    loop = asyncio.get_event_loop()
    loop.run_in_executor(None, _blocking_load)

    async with stdio_server() as (read_stream, write_stream):
        await server.run(
            read_stream,
            write_stream,
            server.create_initialization_options()
        )


if __name__ == "__main__":
    if len(sys.argv) > 2 and sys.argv[1] == "--test":
        # Manual test mode, no MCP client needed:
        #   python plan_generator_server.py --test "a house with three bedrooms"
        creativity = sys.argv[3] if len(sys.argv) > 3 else "medium"
        result = _blocking_generate(sys.argv[2], creativity)
        errors = validate_plan(result)
        print(json.dumps(result, indent=2))
        print("\nschema validation:", "FAILED: " + "; ".join(errors) if errors else "OK",
              file=sys.stderr)
    else:
        asyncio.run(main())
