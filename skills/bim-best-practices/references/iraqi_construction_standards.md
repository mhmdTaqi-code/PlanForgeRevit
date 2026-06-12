# Iraqi Residential Construction Standards (BIM reference)

Load this when you need a layer breakdown, height, or member size that the four catalog
wall types in `SKILL.md` don't cover. Values are derived from the IRAQI_AI_MASTER_SYSTEM
rule files (02_REVIT_BIM.md) and confirmed against the verified reference models
`Vilaa.0001.rvt` and `mohammad.rvt`. Revit internal units are FEET — convert mm → ft with
`mm / 304.8`.

## Table of contents
1. Structural system
2. Wall stack-ups (full set)
3. Floor / roof build-ups
4. Levels & heights
5. Member sizing rules
6. Naming conventions

---

## 1. Structural system

Iraqi residential construction is a **reinforced-concrete skeleton with masonry infill**:
cast-in-place RC columns + beams (including drop beams) + solid or Hordi (ribbed) slabs,
with thermostone/clay-block walls filling between the frame. The masonry is not load-bearing
in modern villas — it is infill — so in BIM every masonry wall must JOIN the concrete it abuts
(see `scripts/enforce_column_wall_joins.py`) rather than floating against it.

## 2. Wall stack-ups (full set)

Exterior → interior order. Plaster: *Labej* = exterior cement render, *Bofya* = interior
gypsum plaster.

| Type | Total | Layers |
|---|---|---|
| Exterior 25 cm | 250 mm | 25 cement plaster · 200 thermostone (core) · 25 gypsum plaster |
| Exterior 36 cm | 360 mm | 25 cement plaster · 310 thermostone (core) · 25 gypsum plaster |
| Interior partition 12 cm | 120 mm | 15 gypsum · 90 block (core) · 15 gypsum |
| Wet-zone wall 20 cm | 200 mm | 15 cement · 170 block (core) · 15 cement (waterproof) |
| Foundation wall 30 cm | 300 mm | single layer RC concrete (core), material = concrete |
| Retaining wall 30 cm | 300 mm | single layer RC concrete (core) |

Parapet heights (unconnected top): outer *Sitara* 1.50 m · courtyard parapet 1.20 m ·
penthouse 3.00 m · first-floor stair partition to penthouse 3.30 m.

## 3. Floor / roof build-ups

- **Suspended floor slab**: RC slab 15 cm (default), 20 cm for large spans, 25 cm Hordi for
  spans > 5.5 m. Topping/screed + finish above.
- **Flat roof (top down)**: concrete roof tiles (*Shtayger*) → screed to falls → thermal
  insulation (styrofoam or earth/sand layer) → moisture proofing (bitumen / Flintkote) →
  RC roof slab. Model as a layered floor type so the section reads correctly.

## 4. Levels & heights

Confirmed in `Vilaa.0001.rvt`: **floor-to-floor = 4.0 m**, levels named `GroundFloor`,
`FirstFloor`, `SecondFloor` with elevations 0 / 4000 / 8000 mm; a foundation level sits at
−3000 mm. Clear floor-to-ceiling after slab + finishes is typically ~3.0–3.2 m. Use 4.0 m
floor-to-floor as the residential default unless the brief says otherwise.

## 5. Member sizing rules (from 02_REVIT_BIM.md)

| Member | Standard | Note |
|---|---|---|
| Column | 25×25 cm standard; 25×40 / 25×50 moment frame; 30×60 transfer | name `Iraqi Column - 25x25cm` etc. |
| Slab | 15 cm default; 20 cm large span; 25 cm Hordi > 5.5 m | `Iraqi Concrete Slab - 15cm` |
| Cantilever > 1.2 m carrying 25 cm masonry | needs RC support column ≥ 25×25 + 30×60 transfer beam below | unsupported masonry cantilever is a defect |
| Span > 4.5 m | RC moment-frame columns | spans > 5.5 m → ≥ 20 cm slab or 25 cm Hordi |

## 6. Naming conventions

Keep the clean Mohammad-style naming even when a reference model uses cryptic names
(`"25"`, `"0.1"`, `"b"` were all seen in `Vilaa.0001.rvt`):

- Walls: `Iraqi Exterior Wall - 25cm`, `Iraqi Interior Partition - 12cm`, `Iraqi Wet-Zone Wall - 20cm`
- Columns: `Iraqi Column - 25x25cm`
- Slabs: `Iraqi Concrete Slab - 15cm`
- Units: **metres** for display; thicknesses quoted in **cm** (integer) in schedules/tags.
