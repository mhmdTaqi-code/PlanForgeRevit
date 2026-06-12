---
name: bim-best-practices
description: >-
  Set up and enforce Iraqi residential BIM standards inside an active Autodesk Revit
  document via the pyRevit MCP bridge. Use this skill WHENEVER the user wants to create,
  standardize, audit, or fix the building-element standards of a Revit model of an Iraqi
  house or villa — defining proper multi-layer wall types (cement plaster → thermostone/brick
  → gypsum plaster), setting heights and level naming, enforcing column-to-wall joins, or
  validating standard wall thicknesses and naming. Trigger on phrases like "set up the wall
  types", "make proper Iraqi walls", "my walls have no materials/layers", "standardize this
  Revit model", "audit the walls", "check wall thicknesses", "fix the BIM standards", or
  "enforce column joins" — even if the user never says "skill" or "validator". This is the
  STANDARDS/QUALITY counterpart to the design skills: it does not invent floor plans, it makes
  the building elements of an EXISTING model correct and buildable.
compatibility: Requires the revit-pyrevit MCP server connected to a live Revit session with a document open.
---

# Iraqi Residential BIM Best-Practices

This skill turns a loosely-built Revit residential model into one that obeys real Iraqi
construction standards. It was built by inspecting verified Iraqi reference models
(`Vilaa.0001.rvt`, `mohammad.rvt`) and the IRAQI_AI_MASTER_SYSTEM rule files. Those models
work geometrically but take shortcuts the construction industry would not accept: walls are
single "Structure" layers with **no material** and **no plaster skins**, type names are cryptic
(`"25"`, `"0.1"`, `"b"`), and the reinforced-concrete skeleton is often not modeled. This
skill fixes exactly those gaps.

## When and why to use this

A Revit model can be *geometrically* fine and still be *constructionally* wrong. An Iraqi
contractor builds a wall as **plaster → block/brick → plaster**, not as an undifferentiated
slab of "Structure" with no material. When the layers and materials are missing, the section
poché is blank, quantity take-offs are meaningless, and thermal/finish schedules are empty. So
the moment a model is going toward documentation or hand-off, the building elements must be
made real. Use this skill at that point, or whenever the user complains that walls "have no
material", "look empty in section", or "the wall types are a mess".

## The three operations

Work in this order. Each operation has a copy-pasteable script under `scripts/`. All scripts
run inside the pyRevit MCP `execute_revit_code` tool (IronPython 2.7 — see the IronPython
notes below) and assume `doc`, `DB`, `revit` are in scope.

### 1. Create the standard Iraqi wall catalog — `scripts/create_iraqi_wall_types.py`

Builds named, multi-layer wall types with real materials and correct total thicknesses:

| Type name | Total | Layers (exterior → interior) |
|---|---|---|
| `Iraqi Exterior Wall - 25cm` | 250 mm | 25 cement plaster (Labej) · 200 thermostone (core) · 25 gypsum plaster (Bofya) |
| `Iraqi Exterior Wall - 36cm` | 360 mm | 25 cement plaster · 310 thermostone (core) · 25 gypsum plaster |
| `Iraqi Interior Partition - 12cm` | 120 mm | 15 gypsum plaster · 90 block (core) · 15 gypsum plaster |
| `Iraqi Wet-Zone Wall - 20cm` | 200 mm | 15 cement plaster · 170 block (core) · 15 cement plaster |

The script is **idempotent** (re-running updates rather than duplicates) and **parametric**
(edit the `CATALOG` list to add a type or change a thickness). It creates the materials too,
with sensible section colors so poché reads correctly.

> Why these numbers: the IRAQI_AI_MASTER_SYSTEM standard wall is 25 cm exterior / 12 cm
> partition; the active reference model confirmed 250 mm and 100 mm walls in use. 25 cm = a
> ~20 cm thermostone/brick core wrapped in ~2.5 cm cement plaster outside and ~2.5 cm gypsum
> plaster inside, which is how the wall is actually built and costed.

### 2. Enforce structural alignment & joins — `scripts/enforce_column_wall_joins.py`

Iraqi houses are an RC skeleton (columns + beams + cast-in-place slabs) with masonry infill.
For the model to read correctly in plan and section, the masonry must *join* to the concrete,
not float against it. This script:

- `JoinGeometryUtils.JoinGeometry` between every structural column and each wall it touches.
- Joins wall-to-wall at shared corners so the section poché stays continuous.
- Reports columns with no joined wall and walls whose ends don't meet anything (open corners).

If the model has **no** structural columns (common in these reference models), the script says
so clearly and only does the wall-to-wall corner joins — it never fabricates a skeleton silently.

### 3. Validate against the standard — `scripts/validate_wall_standards.py`

The acceptance gate. Run it before sign-off; re-run after every fix until it returns `PASS`.
It flags, per wall type in use:

- **`[FAIL]` single-layer / no-material walls** — a wall with one "Structure" layer and no
  material assigned (the exact defect in the reference models).
- **`[FAIL]` non-standard total thickness** — total not within ±5 mm of the standard set
  {120, 200, 250, 360} mm (extend the set in the script if a project genuinely needs another).
- **`[WARN]` non-conforming type name** — a used wall type not following the `Iraqi …`
  naming convention (cryptic names like `"25"`, `"0.1"`).

A validator is only useful if it is trustworthy, so it never cries wolf: it ignores curtain/
storefront systems (they legitimately have no compound structure) and only judges *used* types.

## Workflow

1. Confirm the right document is active (`get_revit_status`). **Never run write operations
   against `mohammad.rvt` or `Vilaa.0001.rvt`** — they are read-only pattern references.
2. Run `scripts/validate_wall_standards.py` first to get a baseline of what's wrong.
3. Run `scripts/create_iraqi_wall_types.py` to create the standard catalog.
4. Reassign existing walls to the new types if asked (the create script prints a mapping of
   old → suggested new type by thickness; reassignment is a separate, explicit step so the
   user stays in control of which wall becomes which). **Never silently snap a near-miss
   thickness** — e.g. a 100 mm wall is *not* a 120 mm partition. Changing it to the nearest
   standard alters the geometry by 20 mm, which moves wall faces and can break dimensions and
   joins. Surface every non-exact match as its own line and let the user decide: keep it,
   widen it deliberately, or add a new standard thickness. Auto-snapping is a silent geometry
   edit, and silent geometry edits are exactly what this skill exists to prevent.
5. Run `scripts/enforce_column_wall_joins.py`.
6. Re-run `scripts/validate_wall_standards.py` until it returns `PASS`. That green result is
   the definition of "done".

## Domain reference

For the full Iraqi construction stack-ups (walls, roofing system, levels/heights, structural
sizing) read `references/iraqi_construction_standards.md`. Load it when you need a layer
breakdown the four catalog types above don't cover (e.g. roof build-up, foundation walls,
parapet heights).

## IronPython 2.7 notes (the MCP runs IronPython, not CPython)

These bite every time, so internalize them:

- **No f-strings.** Use `"{0} {1}".format(a, b)` with explicit positional indices.
- Revit internal units are **feet**, always. Convert mm → ft with `mm / 304.8`. Areas are
  ft²; multiply by 0.092903 for m². The document's *display* units being meters does not
  change the API units.
- Wrap every model change in a transaction you open yourself:
  `t = DB.Transaction(doc, "..."); t.Start(); ...; t.Commit()`. The MCP opens none for you.
- Build .NET lists with `from System.Collections.Generic import List` then `List[T]()`.
- `getattr(el, "Name", "?")` — some type names aren't directly accessible in IronPython.
- Read a wall type's layers with `wt.GetCompoundStructure()`, then per layer index `i`:
  `cs.GetLayerFunction(i)`, `cs.GetLayerWidth(i)`, `cs.GetMaterialId(i)`, `cs.IsCoreLayer(i)`.
  (`GetLayerMaterialId` does **not** exist in this API version — it is `GetMaterialId`.)
