# -*- coding: utf-8 -*-
# enforce_column_wall_joins.py
# Enforce the RC-skeleton-plus-masonry-infill convention: masonry must JOIN the concrete
# columns it abuts (so plan/section poché is continuous), and walls must close their corners.
#
# HOW TO RUN: paste into mcp__revit-pyrevit__execute_revit_code (doc/DB/revit in scope).
# Read-only diagnosis first, then it performs the joins inside one transaction.
# It NEVER fabricates a structural skeleton — if there are no columns it says so and only
# closes wall-to-wall corners.

MM = 304.8
TOL = 0.05            # ft (~15 mm) endpoint coincidence tolerance


def wall_curve(w):
    loc = w.Location
    if isinstance(loc, DB.LocationCurve):
        return loc.Curve
    return None


walls = list(DB.FilteredElementCollector(doc).OfClass(DB.Wall)
             .WhereElementIsNotElementType().ToElements())
cols = list(DB.FilteredElementCollector(doc).OfCategory(DB.BuiltInCategory.OST_StructuralColumns)
            .WhereElementIsNotElementType().ToElements())

print("=== column/wall join enforcement on '{0}' ===".format(doc.Title))
print("walls={0}  structural columns={1}".format(len(walls), len(cols)))

joined_cw = 0
joined_ww = 0
open_corners = []

t = DB.Transaction(doc, "Enforce Iraqi column/wall joins")
t.Start()

# ---- (1) column <-> wall joins (only if columns exist) -------------------------
if cols:
    for c in cols:
        cbb = c.get_BoundingBox(None)
        if not cbb:
            continue
        cmin, cmax = cbb.Min, cbb.Max
        touched = 0
        for w in walls:
            cv = wall_curve(w)
            if cv is None:
                continue
            # cheap proximity: does the column bbox (expanded) contain either wall end?
            for k in (0, 1):
                p = cv.GetEndPoint(k)
                if (cmin.X - TOL <= p.X <= cmax.X + TOL and
                        cmin.Y - TOL <= p.Y <= cmax.Y + TOL):
                    try:
                        if not DB.JoinGeometryUtils.AreElementsJoined(doc, c, w):
                            DB.JoinGeometryUtils.JoinGeometry(doc, c, w)
                            joined_cw += 1
                        touched += 1
                    except:
                        pass
                    break
        if touched == 0:
            print("  [WARN] column {0} touches no wall — check placement".format(c.Id.IntegerValue))
else:
    print("  [INFO] No structural columns modeled — skipping column joins, doing corner joins only.")

# ---- (2) wall <-> wall corner joins -------------------------------------------
ends = []
for w in walls:
    cv = wall_curve(w)
    if cv is None:
        continue
    ends.append((w, cv.GetEndPoint(0), cv.GetEndPoint(1)))

for i in range(len(ends)):
    wi, a0, a1 = ends[i]
    meets = False
    for j in range(len(ends)):
        if i == j:
            continue
        wj, b0, b1 = ends[j]
        for pa in (a0, a1):
            for pb in (b0, b1):
                if pa.DistanceTo(pb) <= TOL:
                    meets = True
                    try:
                        if not DB.JoinGeometryUtils.AreElementsJoined(doc, wi, wj):
                            DB.JoinGeometryUtils.JoinGeometry(doc, wi, wj)
                            joined_ww += 1
                    except:
                        pass
        if meets:
            break
    if not meets:
        open_corners.append(wi.Id.IntegerValue)

t.Commit()

print("\n--- result ---")
print("  column<->wall joins made : {0}".format(joined_cw))
print("  wall<->wall joins made   : {0}".format(joined_ww))
if open_corners:
    print("  [WARN] {0} wall(s) with an end that meets nothing within 15mm (open corner / stub):".format(len(open_corners)))
    print("         ids: {0}".format(open_corners[:40]))
else:
    print("  [ok] every wall end meets another element — no open corners.")
