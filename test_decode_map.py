#!/usr/bin/env python3
"""Offline unit tests for decode_map.py's structured-output path (CAPABILITIES #21).

SAFE / OFFLINE — builds SYNTHETIC protocol-301 frames in memory (no real capture, no
device, no PII) and exercises the decode → `--json` pipeline end to end. Run:

    /path/to/python test_decode_map.py        # prints PASS/FAIL per check

Covers: coord_to_pixel transform, room_geometry, room_at_pixel/robot_room (exact-room),
and build_map_json on a fully synthetic capture (schema, grid dims, rooms, georeference,
robot current-room). It does NOT touch the robot or any committed capture file.
"""
import base64
import json
import struct
import tempfile

import lz4.block

import decode_map as dm


# ── synthetic frame builders (mirror the real on-wire layout) ────────────────

def _grid_frame(W, H, grid_bytes, rooms, map_id=b"\x00\x00\x00\x01"):
    """Build a 0101 grid frame: 29-byte header + LZ4 block of (grid + room records).
    rooms = [(room_id, name), ...]."""
    assert len(grid_bytes) == W * H
    recs = bytes([0x01, len(rooms)])
    for rid, name in rooms:
        nb = name.encode()
        rec = bytearray(47)
        struct.pack_into(">H", rec, 0, rid)
        rec[26] = len(nb)
        rec[27:27 + len(nb)] = nb
        recs += bytes(rec)
    out = bytes(grid_bytes) + recs
    block = lz4.block.compress(out, store_size=False)  # raw block; decode passes uncompressed_size
    hdr = (b"\x01\x01" + map_id + b"\x01"               # sub_type, map_id, segmented flag
           + struct.pack(">H", W) + struct.pack(">H", H)  # bytes 7-8 W, 9-10 H
           + b"\x00" * 14                                 # bytes 11-24
           + struct.pack(">H", len(out))                  # declared_size 25-26
           + struct.pack(">H", len(block)))               # compressed_size 27-28
    assert len(hdr) == 29
    return hdr + block


def _path_frame(points, counter=0x08):
    """Build a 0201 path frame: 16-byte header + BE int16 (x,y) pairs."""
    hdr = (b"\x02\x01" + bytes([0x00, counter]) + b"\x00\x02\x00\x00"
           + struct.pack(">H", len(points)) + b"\x00" * 6)
    assert len(hdr) == 16
    body = b"".join(struct.pack(">hh", x, y) for x, y in points)
    return hdr + body


def _write_capture(frames):
    """Write frames as a watch --bytes JSONL capture; return the temp path."""
    fh = tempfile.NamedTemporaryFile("w", suffix=".jsonl", delete=False)
    for fr in frames:
        fh.write(json.dumps({"protocol_num": 301, "kind": "binary_b64",
                             "time": "2026-01-01T00:00:00",
                             "payload": base64.b64encode(fr).decode()}) + "\n")
    fh.close()
    return fh.name


def _solid_grid(W, H, room_value, wall_border=True):
    """W×H grid: interior = room_value, optional 249 wall border, 243 elsewhere."""
    g = bytearray(243 for _ in range(W * H))
    for r in range(H):
        for c in range(W):
            if wall_border and (r in (0, H - 1) or c in (0, W - 1)):
                g[r * W + c] = 249
            else:
                g[r * W + c] = room_value
    return g


# ── tests ────────────────────────────────────────────────────────────────────

def test_coord_to_pixel():
    # Default origin: col=(y-(-3307))//20, row=(1001-x)//20
    assert dm.coord_to_pixel(801, -3107, 64, 64) == (10, 10)
    assert dm.coord_to_pixel(10**6, 0, 64, 64) is None  # out of bounds → None


def test_room_geometry():
    W = H = 10
    g = bytearray(243 for _ in range(W * H))
    # a 3x2 block of room 3 (value 12) at cols 2-4, rows 5-6
    for r in (5, 6):
        for c in (2, 3, 4):
            g[r * W + c] = 12
    geo = dm.room_geometry(g, W, H)
    assert set(geo) == {3}, geo
    assert geo[3]["bbox_px"] == [2, 5, 4, 6], geo[3]
    assert geo[3]["cells"] == 6
    assert geo[3]["centroid_px"] == [3, 5] or geo[3]["centroid_px"] == [3, 6], geo[3]


def test_robot_room_exact():
    # left half = room 1 (v=4), right half = room 2 (v=8); explicit origin ox=63,oy=0,res=1
    W = H = 64
    g = bytearray(243 for _ in range(W * H))
    for r in range(1, H - 1):
        for c in range(1, W - 1):
            g[r * W + c] = 4 if c < 32 else 8
    # ox=63, oy=0, res=1 → col=path_y, row=63-path_x
    rc, rid = dm.robot_room((33, 10), g, W, H, ox=63, oy=0, res=1)   # col=10 (left)→room1
    assert rid == 1, (rc, rid)
    rc, rid = dm.robot_room((10, 50), g, W, H, ox=63, oy=0, res=1)   # col=50 (right)→room2
    assert rid == 2, (rc, rid)
    # boundary/wall pixel falls back to a nearby room rather than None
    rc, rid = dm.robot_room((63, 0), g, W, H, ox=63, oy=0, res=1)    # col=0 (wall) → neighbour
    assert rid in (1, 2), (rc, rid)


def test_build_map_json_end_to_end():
    W = H = 64
    grid = _solid_grid(W, H, room_value=4)        # whole interior = room 1
    gframe = _grid_frame(W, H, grid, [(1, "Office")])
    # a short in-bounds path; exact mm don't matter (origin is auto-fit onto the floor)
    path = [(800 + i * 20, -3100 - i * 20) for i in range(12)]
    pframe = _path_frame(path)
    cap = _write_capture([gframe, pframe])

    d = dm.build_map_json(cap)
    assert d["schema"] == "roborock-b01-map/1"
    assert d["grid"]["width"] == W and d["grid"]["height"] == H
    assert d["grid"]["dims_source"] == "header"
    names = {r["name"] for r in d["rooms"]}
    assert names == {"Office"}, d["rooms"]
    assert d["rooms"][0]["cells"] > 0 and d["rooms"][0]["bbox_px"] is not None
    assert d["path"]["point_count"] == 12
    assert d["path"]["declared_count"] == 12
    assert d["georeference"] is not None
    assert d["robot"] is not None and d["robot"]["in_grid"] is True
    assert d["robot"]["current_room"] == {"id": 1, "name": "Office"}, d["robot"]


def test_robot_uses_latest_path_frame():
    """Regression (s27): robot position = the LATEST path frame, not the LARGEST.
    The bug was `max(paths, key=len)` — on a multi-clean capture the biggest frame is an
    earlier/larger room, so the robot got reported in the wrong place."""
    W = H = 64
    gframe = _grid_frame(W, H, _solid_grid(W, H, room_value=4), [(1, "Office")])
    big = _path_frame([(800 + i * 5, -3100 - i * 5) for i in range(8)])   # 8 pts, ends (835, -3135)
    small = _path_frame([(820, -3120), (824, -3124)])                     # ends (824, -3124)
    cap = _write_capture([gframe, big, small])                           # small written LAST -> latest
    paths = dm.load_frames(cap, dm.PATH_SIG)
    assert dm.largest_path(paths)[1] == big                              # big is the largest frame
    d = dm.build_map_json(cap)
    assert d["path"]["robot_mm"] == [824, -3124], d["path"]             # latest's last pt, NOT (835, -3135)
    assert "latest" in d["source"]["path_frame_selection"]


def test_json_pipeline_via_build():
    """The dict round-trips through json (no non-serializable types leak in)."""
    grid = _solid_grid(40, 40, room_value=4)
    cap = _write_capture([_grid_frame(40, 40, grid, [(1, "Room")]),
                          _path_frame([(800, -3100), (820, -3120)])])
    s = json.dumps(dm.build_map_json(cap))
    assert json.loads(s)["schema"] == "roborock-b01-map/1"


def _run():
    tests = [v for k, v in sorted(globals().items()) if k.startswith("test_")]
    failed = 0
    for t in tests:
        try:
            t()
            print(f"PASS {t.__name__}")
        except AssertionError as e:
            failed += 1
            print(f"FAIL {t.__name__}: {e}")
    print(f"\n{len(tests) - failed}/{len(tests)} passed")
    return failed


if __name__ == "__main__":
    import sys
    sys.exit(1 if _run() else 0)
