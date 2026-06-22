#!/usr/bin/env python3
"""Round-trip regression tests for encode_restricted_zones / encode_virtual_walls in decode_map.py.

SAFE / OFFLINE — no robot, no network, no PII. Fixtures are either:
  [REAL] — byte-for-byte derived from live s30 captured hex samples documented in
            the s30 wall-codec capture §1 (wall hex `01 f96e f9c5 fcec fa0e`,
            `01 fdae fe01 fdbb 0075`; zone hex `01 01 03 04 0083 ffdb …`).
  [SYNTH] — constructed to cover a code path not captured live (empty lists, 2-zone blobs).

Round-trip contract: encode(parse(blob)) == blob  AND  parse(encode(x)) == x
"""
import base64
import struct

import decode_map as dm


# ── FIXTURES ───────────────────────────────────────────────────────────────────

# [REAL] s30 captured walls (hex from the s30 wall-codec capture §1)
# hex: 01 f96e f9c5 fcec fa0e  → count=1, (y1=-1682, x1=-1595, y2=-788, x2=-1522)
WALL_BLOB_1 = "Aflu+cX87PoO"

# [REAL] s30 captured wall sample 2
# hex: 01 fdae fe01 fdbb 0075  → count=1, (y1=-594, x1=-511, y2=-581, x2=117)
WALL_BLOB_2 = "Af2u/gH9uwB1"

# [SYNTH] empty wall list → count byte 0
WALL_BLOB_EMPTY = "AA=="

# [REAL] s30 captured zone, threshold type (0x03), 4 verts
# hex: 01 01 03 04 0083 ffdb 00b4 00ab 00ca 00a6 0099 ffd6 <20-byte zero pad>
ZONE_BLOB_THRESHOLD = "AQEDBACD/9sAtACrAMoApgCZ/9YAAAAAAAAAAAAAAAAAAAAAAAAAAA=="

# [SYNTH] two-zone blob: no-go (type 0x00) + no-mop (type 0x02), each 4 verts, 38-byte slots
def _make_two_zone_blob() -> str:
    pts_a = [(100, 200), (300, 200), (300, 400), (100, 400)]  # no-go
    pts_b = [(-50, -100), (-50, 50), (50, 50), (50, -100)]    # no-mop
    def slot(ztype, pts):
        s = bytes([ztype, 4]) + b"".join(struct.pack(">hh", x, y) for x, y in pts)
        return s.ljust(38, b"\x00")
    raw = bytes([0x01, 2]) + slot(0x00, pts_a) + slot(0x02, pts_b)
    return base64.b64encode(raw).decode()

ZONE_BLOB_TWO = _make_two_zone_blob()

# [SYNTH] empty zone blob: format=0x01, count=0
ZONE_BLOB_EMPTY = base64.b64encode(bytes([0x01, 0x00])).decode()


# ── Virtual wall round-trip tests ─────────────────────────────────────────────

def test_wall_roundtrip_blob1():
    """[REAL s30] encode(parse(blob)) == blob — wall blob 1."""
    walls = dm.parse_virtual_walls(WALL_BLOB_1)
    assert len(walls) == 1
    assert walls[0] == ((-1682, -1595), (-788, -1522))
    assert dm.encode_virtual_walls(walls) == WALL_BLOB_1


def test_wall_roundtrip_blob2():
    """[REAL s30] encode(parse(blob)) == blob — wall blob 2."""
    walls = dm.parse_virtual_walls(WALL_BLOB_2)
    assert len(walls) == 1
    assert walls[0] == ((-594, -511), (-581, 117))
    assert dm.encode_virtual_walls(walls) == WALL_BLOB_2


def test_wall_roundtrip_empty():
    """[SYNTH] Empty wall list encodes to AA== and round-trips cleanly."""
    assert dm.encode_virtual_walls([]) == WALL_BLOB_EMPTY
    assert dm.parse_virtual_walls(WALL_BLOB_EMPTY) == []
    assert dm.parse_virtual_walls(None) == []


def test_wall_encode_decode_roundtrip():
    """[SYNTH] parse(encode(x)) == x for a constructed wall list."""
    original = [((-800, -900), (-810, -1100)), ((0, 0), (100, 100))]
    blob = dm.encode_virtual_walls(original)
    assert dm.parse_virtual_walls(blob) == original


# ── Restricted zone round-trip tests ─────────────────────────────────────────

def test_zone_roundtrip_threshold():
    """[REAL s30] encode(parse(blob)) == blob — threshold zone (type 0x03)."""
    zones = dm.parse_all_restricted_zones(ZONE_BLOB_THRESHOLD)
    assert len(zones) == 1
    ztype, pts = zones[0]
    assert ztype == 0x03
    assert len(pts) == 4
    assert pts[0] == (131, -37)
    assert dm.encode_restricted_zones(zones) == ZONE_BLOB_THRESHOLD


def test_zone_roundtrip_two_zones():
    """[SYNTH] Two-zone blob (no-go + no-mop) round-trips byte-identically."""
    zones = dm.parse_all_restricted_zones(ZONE_BLOB_TWO)
    assert len(zones) == 2
    assert zones[0][0] == 0x00   # no-go
    assert zones[1][0] == 0x02   # no-mop
    assert len(zones[0][1]) == 4
    assert len(zones[1][1]) == 4
    assert dm.encode_restricted_zones(zones) == ZONE_BLOB_TWO


def test_zone_roundtrip_empty():
    """[SYNTH] Empty zone blob: count=0 round-trips cleanly."""
    zones = dm.parse_all_restricted_zones(ZONE_BLOB_EMPTY)
    assert zones == []
    assert dm.encode_restricted_zones([]) == ZONE_BLOB_EMPTY
    assert dm.parse_all_restricted_zones(None) == []


def test_zone_encode_decode_roundtrip():
    """[SYNTH] parse(encode(x)) == x for a constructed zone list."""
    original = [(0x00, [(10, 20), (30, 20), (30, 40), (10, 40)]),    # no-go
                (0x02, [(-5, -10), (-5, 5), (5, 5), (5, -10)])]      # no-mop
    blob = dm.encode_restricted_zones(original)
    zones = dm.parse_all_restricted_zones(blob)
    assert zones == original


def test_zone_stride_consistency():
    """[SYNTH] Slot size is always _RZONE_STRIDE (38 B) regardless of coord values."""
    pts = [(0, 0), (100, 0), (100, 100), (0, 100)]
    blob = dm.encode_restricted_zones([(0x00, pts)])
    raw = base64.b64decode(blob)
    # format byte + count byte + 1 × 38-byte slot = 40 bytes
    assert len(raw) == 2 + dm._RZONE_STRIDE


# ── runner ────────────────────────────────────────────────────────────────────

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
