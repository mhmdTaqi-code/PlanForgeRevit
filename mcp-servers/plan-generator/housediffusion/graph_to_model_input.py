"""
bubble diagram (rooms + adjacencies)  ->  HouseDiffusion model_kwargs tensors.

This reproduces, faithfully, the conditioning that HouseDiffusion's own dataset
builds in its *synthesis* path (RPlanhgDataset, set_name='eval', the branch that
feeds the model zero coordinates and lets it generate them). The only difference
is the source: instead of reading an RPLAN file, we read a bubble diagram graph
the orchestrating LLM produced from the user's brief.

Pure numpy — no torch, no torch checkpoint. That keeps it unit-testable offline
(test_bridge.py) and importable by the lightweight MCP server without pulling in
the whole deep-learning stack.

Reference: AIProjects/house_diffusion/house_diffusion/rplanhg_datasets.py
(RPlanhgDataset.__getitem__ and the eval branch of __init__).
"""

import numpy as np

from . import room_types as rt


def _one_hot(index: int, size: int) -> np.ndarray:
    return np.eye(size)[index]


def normalize_diagram(diagram: dict) -> dict:
    """Validate a bubble diagram and resolve room types + corner counts.

    Returns a dict with:
      rooms: list of {id, schema_type, rplan_id, corners}
      adj:   set of frozenset({i, j}) over 0-based room indices
    Raises ValueError on malformed input.
    """
    rooms_in = diagram.get("rooms") or []
    if not rooms_in:
        raise ValueError("bubble diagram has no rooms")

    rooms = []
    id_to_index = {}
    for i, r in enumerate(rooms_in):
        rid = r.get("id")
        schema_type = r.get("type")
        if not rid:
            raise ValueError(f"room #{i} is missing an 'id'")
        if rid in id_to_index:
            raise ValueError(f"duplicate room id: {rid!r}")
        if schema_type not in rt.SCHEMA_TO_RPLAN:
            raise ValueError(
                f"room {rid!r} has unknown type {schema_type!r}; "
                f"allowed: {sorted(rt.SCHEMA_TO_RPLAN)}"
            )
        rplan_id = rt.SCHEMA_TO_RPLAN[schema_type]
        rooms.append({
            "id": rid,
            "schema_type": schema_type,
            "rplan_id": rplan_id,
            "corners": rt.corners_for(rplan_id, r.get("corners")),
        })
        id_to_index[rid] = i

    adj = set()
    for edge in diagram.get("adjacencies") or []:
        if len(edge) != 2:
            raise ValueError(f"adjacency {edge!r} must have exactly two room ids")
        a, b = edge
        if a not in id_to_index or b not in id_to_index:
            raise ValueError(f"adjacency {edge!r} references an unknown room id")
        if a == b:
            continue
        adj.add(frozenset((id_to_index[a], id_to_index[b])))

    total_corners = sum(r["corners"] for r in rooms)
    if total_corners > rt.MAX_NUM_POINTS:
        raise ValueError(
            f"too many corners ({total_corners} > {rt.MAX_NUM_POINTS}); "
            "use fewer rooms or fewer corners per room"
        )
    return {"rooms": rooms, "adj": adj}


def build_model_kwargs(diagram: dict, batch_size: int = 1):
    """Build (data_shape, model_kwargs) for HouseDiffusion's sample loop.

    data_shape is what `p_sample_loop` needs (it generates coordinates from
    noise of this shape). model_kwargs holds the conditioning as numpy arrays
    with a leading batch dimension; the engine converts them to torch tensors.
    """
    norm = normalize_diagram(diagram)
    rooms, adj = norm["rooms"], norm["adj"]
    n_rooms = len(rooms)
    max_pts = rt.MAX_NUM_POINTS

    # ---- per-corner feature blocks (coords are zeros for synthesis) ----
    blocks = []
    corner_bounds = []
    num_points = 0
    for room_pos, room in enumerate(rooms):
        nc = room["corners"]
        coords = np.zeros((nc, 2))
        rtype = np.repeat([_one_hot(room["rplan_id"], rt.NUM_ROOM_CLASSES)], nc, 0)
        corner_index = np.array([_one_hot(c, rt.MAX_CORNERS_ONEHOT) for c in range(nc)])
        room_index = np.repeat([_one_hot(room_pos + 1, rt.MAX_ROOMS_ONEHOT)], nc, 0)
        padding_mask = np.ones((nc, 1))
        connections = np.array([[c, (c + 1) % nc] for c in range(nc)]) + num_points
        blocks.append(np.concatenate(
            (coords, rtype, corner_index, room_index, padding_mask, connections), 1
        ))
        corner_bounds.append([num_points, num_points + nc])
        num_points += nc

    house = np.concatenate(blocks, 0)
    real_len = len(house)
    house = np.concatenate((house, np.zeros((max_pts - real_len, rt.FEATURE_WIDTH))), 0)

    # ---- attention masks (max_pts x max_pts), 0 = "attend", 1 = "block" ----
    gen_mask = np.ones((max_pts, max_pts))
    gen_mask[:real_len, :real_len] = 0

    self_mask = np.ones((max_pts, max_pts))
    door_mask = np.ones((max_pts, max_pts))
    living_index = next((i for i, r in enumerate(rooms) if r["rplan_id"] == 1), 0)

    for i in range(n_rooms):
        bi0, bi1 = corner_bounds[i]
        self_mask[bi0:bi1, bi0:bi1] = 0
        connected = False
        for j in range(n_rooms):
            if i == j:
                continue
            if frozenset((i, j)) in adj:
                bj0, bj1 = corner_bounds[j]
                door_mask[bi0:bi1, bj0:bj1] = 0
                connected = True
        # HouseDiffusion's fallback: an unconnected room attaches to the living room
        if not connected and i != living_index:
            lj0, lj1 = corner_bounds[living_index]
            door_mask[bi0:bi1, lj0:lj1] = 0

    # ---- room adjacency triples [a, +1/-1, b], padded to 200 ----
    triples = []
    for k in range(n_rooms):
        for l in range(n_rooms):
            if l > k:
                triples.append([k, 1 if frozenset((k, l)) in adj else -1, l])
    graph = np.array(triples) if triples else np.zeros((0, 3))
    graph = np.concatenate((graph, np.zeros((200 - len(graph), 3))), 0)

    nc2 = 2  # num_coords
    single = {
        "door_mask": door_mask,
        "self_mask": self_mask,
        "gen_mask": gen_mask,
        "room_types": house[:, nc2:nc2 + 25],
        "corner_indices": house[:, nc2 + 25:nc2 + 57],
        "room_indices": house[:, nc2 + 57:nc2 + 89],
        "src_key_padding_mask": 1 - house[:, nc2 + 89],
        "connections": house[:, nc2 + 90:nc2 + 92],
        "graph": graph,
    }
    model_kwargs = {k: np.repeat(v[None], batch_size, 0) for k, v in single.items()}
    data_shape = (batch_size, nc2, max_pts)
    return data_shape, model_kwargs, norm
