"""
Room-type mappings between TarkeebAI's plan_schema vocabulary and the RPLAN /
House-GAN++ class ids that HouseDiffusion was trained on.

RPLAN class ids (from sepidsh/Housegan-data-reader `ROOM_CLASS`):
    1 living_room   2 kitchen      3 bedroom     4 bathroom    5 balcony
    6 entrance      7 dining_room  8 study_room  10 storage
    15 front_door   16 unknown     17 interior_door
HouseDiffusion internally remaps the door classes (15->11, 17->12, 16->13);
real rooms keep ids 1..10. We only ever emit real-room nodes — door placement is
handled downstream from the adjacency graph, not as polygon nodes.

If you retrain on a different dataset, this is the ONLY file you need to touch.
"""

# TarkeebAI plan_schema room type  ->  nearest RPLAN class id the model knows.
SCHEMA_TO_RPLAN = {
    "living": 1,
    "family_living": 1,
    "majlis": 1,          # formal guest living — closest trained class is living
    "kitchen": 2,
    "bedroom": 3,
    "master_bedroom": 3,
    "bathroom": 4,
    "wc": 4,
    "balcony": 5,
    "tarma": 5,           # covered porch — outdoor, maps to balcony
    "roof_terrace": 5,
    "garden": 5,
    "hosh": 5,            # courtyard — open outdoor space, closest is balcony
    "corridor": 6,        # circulation — closest is entrance
    "stair": 6,
    "dining": 7,
    "store": 10,
    "laundry": 10,
    "garage": 10,         # no garage class in RPLAN — treat as a large store
    "other": 10,
}

# RPLAN class id  ->  the plan_schema type we label generated rooms with.
RPLAN_TO_SCHEMA = {
    1: "living",
    2: "kitchen",
    3: "bedroom",
    4: "bathroom",
    5: "balcony",
    6: "corridor",
    7: "dining",
    8: "other",
    10: "store",
}

# Default polygon corner count per RPLAN class when the bubble diagram does not
# specify one. 4 = rectangle, which is what almost every Iraqi residential room
# is; living rooms get 6 so the model can produce an L-shape if it wants to.
DEFAULT_CORNERS = {1: 6}
DEFAULT_CORNERS_FALLBACK = 4

# The model's room_types one-hot width (must match the trained checkpoint).
NUM_ROOM_CLASSES = 25
# Max rooms / max corners-per-room one-hot widths used by HouseDiffusion.
MAX_ROOMS_ONEHOT = 32
MAX_CORNERS_ONEHOT = 32
# Padding budget: HouseDiffusion pads every house to this many corner points.
MAX_NUM_POINTS = 100
# Per-corner feature width before the coordinate columns are prepended.
FEATURE_WIDTH = 94


def corners_for(rplan_id: int, requested) -> int:
    """Resolve the corner count for a room: explicit request wins, else default."""
    if requested:
        return int(requested)
    return DEFAULT_CORNERS.get(rplan_id, DEFAULT_CORNERS_FALLBACK)
