# -*- coding: utf-8 -*-
# validate_wall_standards.py
# The acceptance gate for Iraqi residential wall standards. Run before sign-off; re-run after
# every fix until it prints PASS. Read-only — it changes nothing.
#
# HOW TO RUN: paste into mcp__revit-pyrevit__execute_revit_code (doc/DB/revit in scope).
#
# Checks (only on wall TYPES actually used by >=1 wall; curtain/storefront skipped):
#   [FAIL] single-layer wall with no material assigned   (the reference-model defect)
#   [FAIL] total thickness not within +-TOL of the standard set {120,200,250,360} mm
#   [WARN] used type whose name does not follow the "Iraqi ..." convention
# A validator must be trustworthy, so it never flags legitimate curtain systems and only
# judges types that are in use.

MM = 304.8
TOL_MM = 5.0                                   # thickness tolerance
STD_THICK = [120, 200, 250, 360]               # extend only for a genuine project need
NAME_PREFIX = "iraqi"


def type_name(el):
    # WallType.Name is not reliably reachable via getattr in this IronPython build;
    # the SYMBOL_NAME_PARAM built-in parameter is. Fall back to the static Name getter.
    p = el.get_Parameter(DB.BuiltInParameter.SYMBOL_NAME_PARAM)
    if p and p.AsString():
        return p.AsString()
    try:
        return DB.Element.Name.GetValue(el)
    except:
        return "?"

# ---- gather used wall types ----------------------------------------------------
used = {}
for w in DB.FilteredElementCollector(doc).OfClass(DB.Wall).WhereElementIsNotElementType().ToElements():
    tid = w.GetTypeId().IntegerValue
    used[tid] = used.get(tid, 0) + 1

fails = 0
warns = 0
checked = 0
print("=== wall-standard validation on '{0}' ===".format(doc.Title))

for wt in DB.FilteredElementCollector(doc).OfClass(DB.WallType).ToElements():
    cnt = used.get(wt.Id.IntegerValue, 0)
    if cnt == 0:
        continue                                # judge only used types
    name = type_name(wt)

    # curtain / storefront systems legitimately have no compound structure -> skip
    kind = getattr(wt, "Kind", None)
    is_basic = (str(kind) == "Basic")
    if not is_basic:
        print("  [skip] '{0}' (curtain/stacked system, x{1})".format(name, cnt))
        continue

    checked += 1
    try:
        total_mm = wt.Width * MM
    except:
        total_mm = -1

    cs = wt.GetCompoundStructure()
    nlayers = cs.LayerCount if cs else 0
    materialed = 0
    if cs:
        for i in range(nlayers):
            mid = cs.GetMaterialId(i)
            if mid and mid.IntegerValue > 0:
                materialed += 1

    # (1) bare wall: one layer and/or no materials at all
    if nlayers <= 1 or materialed == 0:
        print("  [FAIL] '{0}' (x{1}) is a bare wall: {2} layer(s), {3} with material — "
              "needs plaster/core/plaster stack-up with real materials".format(
                  name, cnt, nlayers, materialed))
        fails += 1

    # (2) non-standard total thickness
    near = [s for s in STD_THICK if abs(s - total_mm) <= TOL_MM]
    if not near:
        print("  [FAIL] '{0}' (x{1}) total {2:.0f}mm is non-standard (expected one of {3} mm)".format(
            name, cnt, total_mm, STD_THICK))
        fails += 1

    # (3) naming convention
    if NAME_PREFIX not in name.lower():
        print("  [WARN] '{0}' (x{1}) does not follow the 'Iraqi ...' naming convention".format(name, cnt))
        warns += 1

print("\n--- summary ---")
print("  used basic wall types checked : {0}".format(checked))
print("  FAILs : {0}    WARNs : {1}".format(fails, warns))
if fails == 0:
    print("  RESULT: PASS  (warnings are advisory, not blocking)")
else:
    print("  RESULT: FAIL  — fix the items above, then re-run.")
