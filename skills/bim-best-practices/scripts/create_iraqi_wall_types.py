# -*- coding: utf-8 -*-
# create_iraqi_wall_types.py
# Build the standard Iraqi residential wall catalog as proper MULTI-LAYER wall types
# with real materials, inside the ACTIVE Revit document.
#
# HOW TO RUN: paste the whole file into the pyRevit MCP tool
#   mcp__revit-pyrevit__execute_revit_code   (doc / DB / revit are already in scope).
# It is IDEMPOTENT: re-running updates the existing types/materials instead of duplicating.
# It is PARAMETRIC: edit CATALOG below to add a type or change a thickness/layer.
#
# SAFETY: never run against a read-only reference (mohammad.rvt / Vilaa.0001.rvt).

import clr
from System.Collections.Generic import List

MM = 304.8  # 1 ft = 304.8 mm  ->  ft = mm / MM

# ----------------------------------------------------------------------------------
# CATALOG: (type_name, [ (function, width_mm, material_key), ... exterior -> interior ])
# function is one of: "Finish1", "Finish2", "Substrate", "Insulation", "Structure"
# The "Structure" layer(s) become the structural core automatically.
# ----------------------------------------------------------------------------------
CATALOG = [
    ("Iraqi Exterior Wall - 25cm", [
        ("Finish1",   25, "cement_plaster"),   # Labej (exterior cement render)
        ("Structure", 200, "thermostone"),     # thermostone / clay block core
        ("Finish2",   25, "gypsum_plaster"),   # Bofya (interior gypsum plaster)
    ]),
    ("Iraqi Exterior Wall - 36cm", [
        ("Finish1",   25, "cement_plaster"),
        ("Structure", 310, "thermostone"),
        ("Finish2",   25, "gypsum_plaster"),
    ]),
    ("Iraqi Interior Partition - 12cm", [
        ("Finish1",   15, "gypsum_plaster"),
        ("Structure", 90,  "block"),
        ("Finish2",   15, "gypsum_plaster"),
    ]),
    ("Iraqi Wet-Zone Wall - 20cm", [
        ("Finish1",   15, "cement_plaster"),
        ("Structure", 170, "block"),
        ("Finish2",   15, "cement_plaster"),
    ]),
]

# material_key -> (display name, RGB color for section poché)
MATERIALS = {
    "cement_plaster": ("Iraqi Cement Plaster (Labej)", (210, 210, 205)),
    "gypsum_plaster": ("Iraqi Gypsum Plaster (Bofya)", (235, 235, 230)),
    "thermostone":    ("Iraqi Thermostone Block",      (225, 200, 165)),
    "block":          ("Iraqi Concrete Block",         (200, 200, 200)),
}

FUNC = {
    "Finish1":   DB.MaterialFunctionAssignment.Finish1,
    "Finish2":   DB.MaterialFunctionAssignment.Finish2,
    "Substrate": DB.MaterialFunctionAssignment.Substrate,
    "Insulation": DB.MaterialFunctionAssignment.Insulation,
    "Structure": DB.MaterialFunctionAssignment.Structure,
}


def type_name(el):
    # WallType.Name is not reliably reachable via getattr in this IronPython build.
    p = el.get_Parameter(DB.BuiltInParameter.SYMBOL_NAME_PARAM)
    if p and p.AsString():
        return p.AsString()
    try:
        return DB.Element.Name.GetValue(el)
    except:
        return "?"


def get_or_create_material(name, rgb):
    for m in DB.FilteredElementCollector(doc).OfClass(DB.Material).ToElements():
        if m.Name == name:
            return m.Id
    mid = DB.Material.Create(doc, name)
    m = doc.GetElement(mid)
    try:
        m.Color = DB.Color(rgb[0], rgb[1], rgb[2])
        m.SurfaceForegroundPatternColor = DB.Color(rgb[0], rgb[1], rgb[2])
    except:
        pass
    return mid


def find_basic_walltype():
    # A Basic (compound) wall type to duplicate from — never a curtain/stacked type.
    # WallType.Kind stringifies to "Basic" / "Curtain" / "Stack"; the string compare is the
    # build-independent way to detect it (verified live against the pyRevit MCP).
    for wt in DB.FilteredElementCollector(doc).OfClass(DB.WallType).ToElements():
        if str(getattr(wt, "Kind", None)) == "Basic":
            return wt
    return None


def get_or_duplicate_walltype(name, template):
    for wt in DB.FilteredElementCollector(doc).OfClass(DB.WallType).ToElements():
        p = wt.get_Parameter(DB.BuiltInParameter.SYMBOL_NAME_PARAM)
        if p and p.AsString() == name:
            return wt          # exists -> we will overwrite its compound structure
    return template.Duplicate(name)


def build_compound(layers_spec):
    layers = List[DB.CompoundStructureLayer]()
    for func, wmm, matkey in layers_spec:
        matname, rgb = MATERIALS[matkey]
        mid = get_or_create_material(matname, rgb)
        layers.Add(DB.CompoundStructureLayer(wmm / MM, FUNC[func], mid))
    cs = DB.CompoundStructure.CreateSimpleCompoundStructure(layers)
    return cs


# ---- execute -------------------------------------------------------------------
template = find_basic_walltype()
if template is None:
    print("[ABORT] No Basic wall type found to use as a template.")
else:
    t = DB.Transaction(doc, "Create Iraqi standard wall catalog")
    t.Start()
    made = []
    for name, spec in CATALOG:
        wt = get_or_duplicate_walltype(name, template)
        wt.SetCompoundStructure(build_compound(spec))
        total = sum(w for _, w, _ in spec)
        made.append((name, total, "{0}mm".format(int(round(wt.Width * MM)))))
    t.Commit()
    print("=== Iraqi wall catalog ready in '{0}' ===".format(doc.Title))
    for name, want, got in made:
        flag = "ok" if abs(want - int(got[:-2])) <= 1 else "CHECK"
        print("  [{0}] '{1}'  target={2}mm  actual={3}".format(flag, name, want, got))

    # Suggest a remap of existing walls (by current thickness) -> new standard type.
    print("\n--- remap suggestion (existing used types -> standard) ---")
    used = {}
    for w in DB.FilteredElementCollector(doc).OfClass(DB.Wall).WhereElementIsNotElementType().ToElements():
        wt = doc.GetElement(w.GetTypeId())
        try:    th = int(round(wt.Width * MM))
        except: th = -1
        nm = type_name(wt)
        used.setdefault((nm, th), 0)
        used[(nm, th)] += 1
    STD = {120: "Iraqi Interior Partition - 12cm", 200: "Iraqi Wet-Zone Wall - 20cm",
           250: "Iraqi Exterior Wall - 25cm", 360: "Iraqi Exterior Wall - 36cm"}
    for (nm, th), cnt in sorted(used.items(), key=lambda x: -x[1]):
        target = STD.get(th, "(no standard at {0}mm — review)".format(th))
        print("  '{0}' ({1}mm) x{2}  ->  {3}".format(nm, th, cnt, target))
    print("\nReassignment is a separate, explicit step — tell me which walls to convert.")
