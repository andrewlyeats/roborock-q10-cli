#!/usr/bin/env python3
"""
Decode the Roborock Q10 (B01) live map from a `vac.py watch --bytes` capture.

The robot streams protocol-301 `map_response` frames over MQTT while cleaning
(spontaneously), and also on demand to any client that sends DP-110 (HEARTBEAT)
polls — the live-map keepalive the app sends ~every 5s. So the live map + path is
available outside a clean too (not "only while cleaning"). python-roborock's B01
path drops these frames (its dps decoder only accepts protocol-102 JSON), so
`watch --bytes` (or a daemon bytes tap) is how we capture them. This tool decodes them.

Two 301 sub-types, distinguished by their 2-byte sub-type prefix (`0101`/`0201`);
the 8-byte example headers below show the surrounding constant/per-map bytes:
  • 0201000800020000  — the CLEANING PATH. Big-endian int16 (x,y) pairs after a
    14-byte header (bytes 8-9 = point count; raw pose starts at byte 14; the
    clean-render georef reads byte 16 as a tuned offset — see parse_path).
    Units = path-units (~2.5 mm/unit, not true mm); LAST point = robot's
    current position; first ≈ dock. Rendered to an SVG polyline.
  • 0101…  — the ROOM/OCCUPANCY GRID (match the 2-byte prefix; bytes 2-5 are a
    device-specific map id). **LZ4-compressed** (not RLE).
    Header: declared size = bytes[25:27] BE, comp len = bytes[27:29] BE, LZ4 block
    from byte 29. Decompresses to a width×height grid (`pixel//4 = room_id`,
    243=outside, 249=wall) followed by room records (`[0x01,count]` then count×47B;
    name length at record byte 26, name from byte 27). Grid width/height are read
    from the header (`raw[7:9]`/`raw[9:11]` BE u16; the empirical row-stride that
    makes vertically-adjacent rows most similar is now only a fallback).
    Rendered to a colour-coded PNG with room-name labels.
    Format credit: v1b3c0d3x3r/roborock-qseries-map-bridge (prior art).

Optional DP overlay (--dps <raw-watch-jsonl>):
  Pass a `watch --raw` JSONL (or your_capture.jsonl) to overlay walls, no-go
  zones, cleaning zones, and carpets on the map_overlay.png.
  DP formats (decoded sessions 9-26; no-mop type corrected to 0x02 in s26):
    VIRTUAL_WALL_UP  = [count:u8] + count×(x1,y1,x2,y2) BE int16, ~5 mm/unit.
                       NOTE: wall coords are (y,x) vs path's (x,y) — first value
                       is path_y, second is path_x (swap on coord_to_pixel call).
    RESTRICTED_ZONE_UP = [0x01][count:u8] + count×([type:u8][nverts:u8=4] + 4×(x,y) BE int16)
                       type=0x00 for no-go, 0x02 for no-mop zone (0x02 ground-truthed s26;
                       0x01 was an early wrong inference — see parse_restricted_zones).
    ZONED_UP         = identical format, type=0x01 for cleaning zone.
    CARPET_UP        = JSON {"data":[{id,rug_clean_mode,vertexs:[[x,y]×4]},...]}

Usage:
  ./vac.py watch --bytes --out cap.jsonl     # capture while the robot cleans
  ./vac.py watch --raw --out raw.jsonl       # capture DPs (walls, zones) simultaneously
  ./decode_map.py cap.jsonl                  # -> map_path.svg, map_rooms.png, map_overlay.png
  ./decode_map.py cap.jsonl --dps raw.jsonl  # -> overlay includes walls + zones
  ./decode_map.py cap.jsonl --json           # -> structured data on stdout (no images; pipe to jq)

The `--json` output is the "give others the data" surface (CAPABILITIES #21): grid dims +
georeference transform, rooms with pixel geometry, the robot's current position + room,
the cleaning path, and any wall/zone overlay — so a status panel / web UI / HA shell
command can consume the decode without parsing a PNG. Schema: `roborock-b01-map/1`.
"""
import base64
import json
import struct
import sys

# Path frames: match only the 2-byte sub-type PREFIX (0201). Byte 3 of the full header
# varies by session / firmware / clean-mode (0x08 AND 0x11 both observed — s23 mop-mode
# emitted 0201_0011_...); parse_path reads the point count from bytes 8-9 and is agnostic
# to it. Matching the full 8-byte sig "0201000800020000" found ZERO path frames whenever
# byte 3 differed (it silently dropped the entire s23 cleaning path). See PROTOCOL s23.
PATH_SIG = "0201"
# Grid frames: match only the 2-byte sub-type PREFIX. Bytes 2-5 of the full 8-byte
# header are a device-specific map id (e.g. <device-map-id> on the dev's robot) and differ per
# device/home — matching the full signature would find zero frames on anyone else's robot.
GRID_PREFIX = "0101"

# Grid ↔ path registration. PRIMARY source is now origin_from_header() — the origin IS transmitted
# in every 0101 header (ox=2*y_min, oy=-2*x_min; validated at parity with auto-fit). fit_origin is a
# FALLBACK/cross-check for null-origin frames; these constants are the last-ditch default. Stable
# while dock position / map unchanged.
# col = (path_y - GRID_ORIGIN_OY) // GRID_MM_PER_PIXEL   ← grid column  (x-axis)
# row = (GRID_ORIGIN_OX - path_x) // GRID_MM_PER_PIXEL   ← grid row     (y-axis, inverted)
# (Legacy default below = an old auto-fit value, 99.87% on its capture; superseded by the header read.)
GRID_ORIGIN_OX = 1001   # path-units (~2.5 mm/unit) — path_x that maps to grid row 0 (top edge)
GRID_ORIGIN_OY = -3307  # path-units (~2.5 mm/unit) — path_y that maps to grid col 0 (left edge)
GRID_MM_PER_PIXEL = 20  # PATH-UNITS per grid pixel, NOT mm. path≈2.5 mm/unit → ≈50 mm/px (the standard Roborock resolution). The registration path//20=pixel is correct; only the "mm" label was wrong — see DP_DICTIONARY coord-frame note.

# Room palette (room_id -> RGB). Stable, distinct, readable on white.
ROOM_COLORS = [
    (78, 161, 255), (57, 211, 83), (226, 75, 74), (240, 159, 39),
    (157, 123, 221), (29, 158, 117), (212, 83, 126), (120, 144, 156),
]
OUTSIDE = (255, 255, 255)
WALL = (55, 55, 55)


def load_frames(path, sig):
    """Load proto-301 frames whose header starts with `sig` (a hex prefix of any length)."""
    nbytes = len(sig) // 2
    frames = []
    with open(path) as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            r = json.loads(line)
            if r.get("protocol_num") == 301 and r.get("kind") == "binary_b64":
                raw = base64.b64decode(r["payload"])
                if raw[:nbytes].hex() == sig:
                    frames.append((r.get("time"), raw))
    return frames


# ── path (0201) ────────────────────────────────────────────────────────────────

def parse_path(raw):
    """Return (points, declared_count). BE int16 (x,y) path-unit pairs.

    Points truly start at **byte 14** (`pose_extract.py`; verified exact, 850/850 teleop frames). This
    renderer reads from **byte 16** — a render-path legacy (the count then reads one high), kept because
    the overlay's `coord_to_pixel`/`render_path_svg` are matched to it. FLAGGED FOR REFACTOR to byte 14 +
    `path_to_pixel`.

    Stray leading point: SOME autonomous dock-rooted cleans prepend one extra point ≈ the map origin
    (counted in `count`); `_drop_path_outlier` strips it. Absent on teleop/heartbeat (pose_hb1/hb4) and
    map-builds; present in the s23/s24/s26 cleans. OPEN QUESTION (do NOT call resolved): what TRIGGERS it
    — clean mode? resume? A targeted short-vs-long/resumed-clean capture would settle it. See PROTOCOL s28.
    """
    count = struct.unpack(">H", raw[8:10])[0]
    body = raw[16:]
    n = len(body) // 4
    pts = [struct.unpack(">hh", body[i * 4:i * 4 + 4]) for i in range(n)]
    return pts, count


def _drop_path_outlier(pts):
    """Drop the bogus leading point that SOME cleans prepend to 0201 path frames (a sentinel
    ~(0,-1900), counted in the frame's `count`; see parse_path). Drop pts[0] ONLY if its step to
    pts[1] is a gross outlier (>20x the median step), so a genuine first point (e.g. a dock point)
    is never dropped — robust and trigger-agnostic. NOT a firmware-version thing (byte[3] is a
    per-clean counter). What TRIGGERS the sentinel is an OPEN QUESTION (see parse_path / PROTOCOL
    s28). Surfaced as the green START dot landing outside the walls (user-caught, s24).
    """
    if len(pts) < 4:
        return pts
    steps = [abs(pts[i + 1][0] - pts[i][0]) + abs(pts[i + 1][1] - pts[i][1]) for i in range(len(pts) - 1)]
    rest = sorted(steps[1:])
    med = rest[len(rest) // 2] or 1
    return pts[1:] if steps[0] > 20 * med else pts


def render_path_svg(pts, scale=10.0, pad=12):
    # The robot's raw (x,y) is transposed vs the real-world / app orientation.
    # Swapping x<->y puts the map in the same orientation the Roborock app shows
    # (confirmed 2026-06-12 against an app screenshot + a drawn virtual wall).
    pts = [(y, x) for x, y in pts]
    xs = [p[0] for p in pts]
    ys = [p[1] for p in pts]
    minx, maxx, miny, maxy = min(xs), max(xs), min(ys), max(ys)
    sx = lambda x: (x - minx) / scale + pad
    sy = lambda y: (maxy - y) / scale + pad  # flip y for screen coords
    vw = (maxx - minx) / scale + 2 * pad
    vh = (maxy - miny) / scale + 2 * pad
    poly = " ".join(f"{sx(x):.0f},{sy(y):.0f}" for x, y in pts)
    return (
        f'<svg viewBox="0 0 {vw:.0f} {vh:.0f}" xmlns="http://www.w3.org/2000/svg" role="img" width="100%">\n'
        f'<title>Roborock cleaning path</title>\n'
        f'<polyline points="{poly}" fill="none" stroke="#378ADD" stroke-width="1.6" '
        f'stroke-opacity="0.85" stroke-linejoin="round" stroke-linecap="round"/>\n'
        f'<circle cx="{sx(pts[0][0]):.1f}" cy="{sy(pts[0][1]):.1f}" r="5" fill="#1D9E75"/>\n'
        f'<circle cx="{sx(pts[-1][0]):.1f}" cy="{sy(pts[-1][1]):.1f}" r="6" fill="#E24B4A"/>\n'
        f'</svg>\n'
    )


# ── room grid (0101) ─────────────────────────────────────────────────────────────

def decompress_grid(raw):
    import lz4.block
    declared = struct.unpack(">H", raw[25:27])[0]
    clen = struct.unpack(">H", raw[27:29])[0]
    return lz4.block.decompress(raw[29:29 + clen], uncompressed_size=declared)


def parse_rooms(out):
    """Find the trailing room block `[0x01, count]` + count×47B records → {id: name}.

    Returns (room_names, grid_region_len). Falls back to ({}, len(out)) if not found.
    """
    for rc in range(1, 16):
        off = len(out) - (2 + rc * 47)
        if off < 0:
            continue
        if out[off] == 0x01 and out[off + 1] == rc:
            rooms = {}
            recs = out[off + 2:]
            for i in range(rc):
                rec = recs[i * 47:(i + 1) * 47]
                rid = struct.unpack(">H", rec[0:2])[0]
                nlen = rec[26]
                name = rec[27:27 + nlen].decode("utf-8", "replace") if nlen else f"room{rid}"
                rooms[rid] = name
            return rooms, off
    return {}, len(out)


def find_width(grid):
    """The row stride that makes vertically-adjacent rows most similar (real image).

    Empirical fallback for `grid_dims_from_header` — kept as a cross-check and for any
    frame whose header is absent/implausible.
    """
    best = None
    for W in range(60, 800):
        if len(grid) % W:
            continue
        H = len(grid) // W
        if H < 8:
            continue
        diff = sum(1 for i in range(0, (H - 1) * W) if grid[i] != grid[i + W])
        score = diff / ((H - 1) * W)
        if best is None or score < best[0]:
            best = (score, W, H)
    return (best[1], best[2]) if best else None  # (W, H); None if no plausible width found


def grid_dims_from_header(raw):
    """Grid (W, H) read straight from the 0101 frame header: raw[7:9]=W, raw[9:11]=H,
    both BE u16. Verified 100% against find_width across 424 frames / 2 widths (PROTOCOL
    s25). Returns None if the bytes are missing or implausible, so callers fall back to
    find_width. This is what makes the decode size-agnostic on any home (the dimensions
    are read off the wire, not guessed from a row-stride heuristic)."""
    if len(raw) < 11:
        return None
    W = struct.unpack(">H", raw[7:9])[0]
    H = struct.unpack(">H", raw[9:11])[0]
    if 60 <= W <= 800 and 8 <= H <= 800:
        return W, H
    return None


def resolve_dims(raw, out):
    """(W, H, grid, source) from the full decompressed `out`. Prefer the header dims
    (raw[7:9],[9:11]) and slice `grid = out[:W*H]`; fall back to find_width over the
    parse_rooms-trimmed region only if the header is absent/implausible.

    Slicing by the HEADER dims (not by parse_rooms' boundary) is what keeps decode robust:
    some frames decompress to exactly W*H+2 bytes (a 2-byte room footer), which made the old
    find_width path mis-detect the stride (e.g. 418×41) on in-progress/edge frames. See
    PROTOCOL s26. `(0,0)` reset frames → grid_dims_from_header returns None → fallback."""
    hdr = grid_dims_from_header(raw)
    if hdr and hdr[0] * hdr[1] <= len(out):
        W, H = hdr
        return W, H, out[:W * H], "header"
    _, grid_len = parse_rooms(out)
    grid = out[:grid_len]
    fw = find_width(grid)
    if fw is None:
        raise ValueError(
            f"resolve_dims: ungridable frame — no plausible header dims (raw[7:11]) and no "
            f"factorable row width (decompressed len={len(out)}, grid_len={grid_len}). Likely a "
            f"partial/in-progress or reset frame, not a finalized map. build_map_json picks the "
            f"largest grid frame, so a finalized capture won't hit this.")
    W, H = fw
    return W, H, grid, "find_width"


def origin_from_header(raw):
    """Map georef origin (ox, oy), read DIRECTLY from the 0101 grid-frame header — retires auto-fit.

    The header carries the map origin (the block long thought "unknown"): x_min @ bytes 11-12,
    y_min @ bytes 13-14 (s16 BE), in 5-mm units (= 2 path-units each, since 1 path-unit ≈ 2.5 mm).
    So the path→grid registration is EXACT, not searched:
        ox = 2 * y_min   (path_x at grid row 0)      oy = -2 * x_min   (path_y at grid col 0)
    (Cross-checked vs the app's own JS map parser `parserPublicRealTimeMap`, and validated at on-floor
    PARITY with the old auto-fit on 29/31 captures — gap_research/validate_origin.py. The header also
    carries resolution @ 15-16 [/100 m/px = 0.05 = 50 mm/px = 20 path-units/px] and the dock pose @
    17-22.) Returns (ox, oy) or None for a null/keepalive frame (x_min==y_min==0) so the caller can
    fall back to fit_origin.
    """
    if not raw or len(raw) < 15 or raw[:2] != b"\x01\x01":
        return None
    x_min = struct.unpack(">h", raw[11:13])[0]
    y_min = struct.unpack(">h", raw[13:15])[0]
    if x_min == 0 and y_min == 0:
        return None
    return 2 * y_min, -2 * x_min


def fit_origin(grid, W, H, pts, res=GRID_MM_PER_PIXEL):
    """Auto-fit the path→grid registration origin (ox, oy) by grid-search: pick the (ox,
    oy) that lands the most path points on FLOOR cells (b%4==0, b!=0). The path must lie
    inside the W×H grid, which bounds the search tightly. Returns (ox, oy, res, score) with
    score = on-floor fraction, or None if it can't fit.

    FALLBACK ONLY: the origin IS transmitted in the 0101 header (x_min@11-12, y_min@13-14) —
    `origin_from_header()` reads it directly and is the primary source. This auto-fit is kept as a
    fallback/cross-check for null-origin frames; it lands at on-floor parity with the header origin
    (29/31 captures). (The old "origin is NOT transmitted, exhaustive search" belief — PROTOCOL s25 —
    was overturned by the gap-research byte-coverage sweep; see origin_from_header.)
    """
    if len(pts) < 4:
        return None
    floor = {(i % W, i // W) for i, b in enumerate(grid) if b and b % 4 == 0}
    if not floor:
        return None
    xs = [p[0] for p in pts]; ys = [p[1] for p in pts]
    minx, maxx, miny, maxy = min(xs), max(xs), min(ys), max(ys)
    # The whole path must map into [0,W)×[0,H) → principled, tight bounds on the origin.
    ox_lo, ox_hi = maxx, minx + H * res
    oy_lo, oy_hi = maxy - W * res, miny
    if ox_lo > ox_hi or oy_lo > oy_hi:
        return None  # path larger than the grid — can't be a clean fit

    def score(ox, oy, sample):
        # floor is keyed (col, row); coord_to_pixel uses col=(y-oy)//res, row=(ox-x)//res.
        hit = 0
        for x, y in sample:
            if ((y - oy) // res, (ox - x) // res) in floor:
                hit += 1
        return hit

    sample = pts if len(pts) <= 1500 else pts[::max(1, len(pts) // 1500)]

    # coarse pass (subsampled), then fine pass (full points) around the winner
    best = None
    cstep = res * 4
    ox = ox_lo
    while ox <= ox_hi:
        oy = oy_lo
        while oy <= oy_hi:
            s = score(ox, oy, sample)
            if best is None or s > best[0]:
                best = (s, ox, oy)
            oy += cstep
        ox += cstep
    if best is None:
        return None
    _, cox, coy = best
    best = None
    for ox in range(cox - res * 4, cox + res * 4 + 1, res):
        for oy in range(coy - res * 4, coy + res * 4 + 1, res):
            s = score(ox, oy, pts)
            if best is None or s > best[0]:
                best = (s, ox, oy)
    sc, ox, oy = best
    return ox, oy, res, sc / len(pts)


# Orientation candidates for the TRUE (byte-14) pose → grid (swap, sign_c, sign_r): swap=False → col
# from x / row from y, True → col from y / row from x; signs flip each axis. The Q10 header-standard is
# (False, 1, -1). fit_registration searches all 8 only as a FALLBACK for an unseen orientation.
_ORIENTATIONS = [(s, sc, sr) for s in (False, True) for sc in (1, -1) for sr in (1, -1)]


def fit_registration(grid, W, H, pts, res=GRID_MM_PER_PIXEL):
    """FALLBACK orientation+origin fit for the TRUE (byte-14) pose, for a map where the header-standard
    orientation lands few path points on floor (a different home / firmware / a re-oriented map).

    Searches the 8 axis-aligned orientations (swap × col-sign × row-sign) × translation (each via
    `fit_origin`'s bbox slide). Mirrors upstream python-roborock `solve_calibration` — resolution is FIXED
    at the read 50 mm/px (=20 path-units/px); we search orientation + offset. Returns a list of
    `((swap, sign_c, sign_r, oc, orow, res), score)` SORTED by score desc (best first), for
    `col=(sign_c·cval − oc)//res, row=(sign_r·rval − orow)//res` (cval,rval = x,y or y,x per swap); `[]` if
    it can't fit. The header-standard default is `(False, 1, -1, oy, -ox, res)`. The caller must adopt a
    fit CONSERVATIVELY (enough points + a clear margin over the runner-up — a short path slides onto a
    floor blob in many orientations), so the common path stays the deterministic header read. See
    FRAME_ANATOMY step 9 / PROTOCOL 2026-06-23."""
    if len(pts) < 4:
        return []
    out = []
    for swap, sc, sr in _ORIENTATIONS:
        # Transform each true (x,y) so fit_origin's (col=(b−oy)//res, row=(ox−a)//res) realises this
        # orientation: b = sc·cval, a = −sr·rval.  Then oc = oy_fit, orow = −ox_fit (derivation in docs).
        tp = [((-sr * (x if swap else y)), (sc * (y if swap else x))) for x, y in pts]
        fit = fit_origin(grid, W, H, tp, res)
        if fit is None:
            continue
        ox_f, oy_f, _, score = fit
        out.append(((swap, sc, sr, oy_f, -ox_f, res), score))
    out.sort(key=lambda ps: ps[1], reverse=True)
    return out


def render_grid_png(grid, W, H, rooms, scale=3):
    from PIL import Image, ImageDraw
    img = Image.new("RGB", (W, H), OUTSIDE)
    px = img.load()
    centroids = {}  # room_id -> [sumx, sumy, count]
    for i, b in enumerate(grid):
        x, y = i % W, i // W
        if b == 243:
            continue  # outside (already white)
        if b == 249:
            px[x, y] = WALL
            continue
        if b and b % 4 == 0:
            rid = b // 4
            px[x, y] = ROOM_COLORS[(rid - 1) % len(ROOM_COLORS)]
            c = centroids.setdefault(rid, [0, 0, 0])
            c[0] += x; c[1] += y; c[2] += 1
        else:
            px[x, y] = (210, 210, 210)
    img = img.resize((W * scale, H * scale), Image.NEAREST)
    draw = ImageDraw.Draw(img)
    for rid, (sx, sy, n) in centroids.items():
        if n < 30:
            continue
        label = rooms.get(rid, f"room{rid}").replace("rr_", "")
        draw.text((sx / n * scale, sy / n * scale), label, fill=(0, 0, 0), anchor="mm")
    return img


# ── DP overlay data (walls / zones / carpets) ────────────────────────────────

def load_dp_overlay(dps_path):
    """Read a watch --raw JSONL and return the latest value of each relevant DP.

    Returns dict with keys: 'walls', 'no_go', 'no_mop', 'clean_zones', 'carpets'.
    Each value is a list of decoded shapes (see parse_* functions below).
    """
    latest = {}
    with open(dps_path) as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            try:
                r = json.loads(line)
            except json.JSONDecodeError:
                continue
            dps = r.get("dps") or {}
            for key in ("VIRTUAL_WALL_UP", "RESTRICTED_ZONE_UP", "ZONED_UP", "CARPET_UP"):
                if key in dps:
                    latest[key] = dps[key]
    return {
        "walls":       parse_virtual_walls(latest.get("VIRTUAL_WALL_UP")),
        "no_go":       parse_restricted_zones(latest.get("RESTRICTED_ZONE_UP"), want_type=0x00),
        "no_mop":      parse_restricted_zones(latest.get("RESTRICTED_ZONE_UP"), want_type=0x02),
        "clean_zones": parse_restricted_zones(latest.get("ZONED_UP"), want_type=0x01),
        "carpets":     parse_carpets(latest.get("CARPET_UP")),
    }


def parse_virtual_walls(value):
    """VIRTUAL_WALL_UP base64 → list of ((y1,x1),(y2,x2)) in wall units (~5 mm/unit).

    Wall coords are stored as (y,x) not (x,y) — swap relative to the path frame.
    Confirmed against drawn wall (-811,-836)→(-815,-1153) matching app display.
    """
    if not value:
        return []
    raw = base64.b64decode(value)
    if not raw:
        return []
    count = raw[0]
    walls = []
    for i in range(count):
        off = 1 + i * 8
        if off + 8 > len(raw):
            break
        y1, x1, y2, x2 = struct.unpack(">hhhh", raw[off:off + 8])
        walls.append(((y1, x1), (y2, x2)))
    return walls


def encode_virtual_walls(walls):
    """Inverse of parse_virtual_walls → base64 blob for VIRTUAL_WALL (DP 56).
    `[count:u8]` + per wall `(y1,x1,y2,x2)` BE-int16 (8 B/wall) — the SAME stored (y,x) order
    parse_virtual_walls reads, so `walls` is a list of ((y1,x1),(y2,x2)) tuples in that stored order
    (the caller does any path-frame (x,y)↔(y,x) swap). Empty list → `AA==` (count 0).
    Round-trips the s30 captured DP-56/57 blobs byte-identically (validated). Coords = robot units (~5 mm)."""
    out = bytes([len(walls)])
    for (y1, x1), (y2, x2) in walls:
        out += struct.pack(">hhhh", int(y1), int(x1), int(y2), int(x2))
    return base64.b64encode(out).decode()


def parse_restricted_zones(value, want_type):
    """RESTRICTED_ZONE_UP / ZONED_UP base64 → list of 4-corner polygons in ~5 mm/unit.

    Format: [0x01][count:u8] + count × FIXED-SIZE slots. Each slot:
      [type:u8][nverts:u8] + nverts×(x,y) BE int16, then ZERO-PADDED to the slot stride
      (stride reserves up to 9 verts → 2 + 9*4 = 38 bytes; derived from len/count for safety).
    Zones are NOT tightly packed — walking them packed makes a no-go's (type 0x00) trailing
    zero-pad look like a second empty zone and skips the real next zone (s26 ground-truth bug).
    Types for RESTRICTED_ZONE_UP, confirmed by drawing each (s26): **0x00 = no-go, 0x02 = no-mop**.
    (ZONED_UP cleaning-zone type is unverified — never captured populated.)
    """
    if not value:
        return []
    raw = base64.b64decode(value)
    if len(raw) < 2 or raw[0] != 0x01:
        return []
    count = raw[1]
    if count == 0:
        return []
    body = len(raw) - 2
    stride = body // count if body % count == 0 and body // count >= 6 else 2 + 9 * 4
    zones = []
    for i in range(count):
        off = 2 + i * stride
        if off + 2 > len(raw):
            break
        zone_type = raw[off]
        nverts = raw[off + 1]
        pts = []
        for j in range(nverts):
            p = off + 2 + j * 4
            if p + 4 > len(raw):
                break
            x, y = struct.unpack(">hh", raw[p:p + 4])
            pts.append((x, y))
        if zone_type == want_type and pts:
            zones.append(pts)
    return zones


# RESTRICTED_ZONE type codes — s26 ground-truth, re-confirmed by the s30 capture decode
# (no-go/no-mop/threshold; there is NO "type 1" here — virtual walls are the separate DP 56).
RZONE_TYPES = {0: "no-go", 2: "no-mop", 3: "threshold"}
RZONE_NAMES = {v: k for k, v in RZONE_TYPES.items()}
_RZONE_STRIDE = 2 + 9 * 4  # 38: [type][nverts] + up to 9 (x,y) BE-int16, zero-padded


def parse_all_restricted_zones(value):
    """Full decode of RESTRICTED_ZONE(_UP) → [(type:int, [(x,y),...]), ...] (every zone, with its type).
    Inverse of encode_restricted_zones; coords are robot units (~5 mm/unit). cf. parse_restricted_zones."""
    if not value:
        return []
    raw = base64.b64decode(value)
    if len(raw) < 2 or raw[0] != 0x01:
        return []
    count = raw[1]
    if count == 0:
        return []
    body = len(raw) - 2
    stride = body // count if body % count == 0 and body // count >= 6 else _RZONE_STRIDE
    zones = []
    for i in range(count):
        off = 2 + i * stride
        if off + 2 > len(raw):
            break
        ztype, nverts = raw[off], raw[off + 1]
        pts = []
        for j in range(nverts):
            p = off + 2 + j * 4
            if p + 4 > len(raw):
                break
            pts.append(struct.unpack(">hh", raw[p:p + 4]))
        zones.append((ztype, pts))
    return zones


def encode_restricted_zones(zones):
    """Inverse of parse_all_restricted_zones → base64 blob for RESTRICTED_ZONE (DP 54).
    `[0x01][count]` + count × 38-byte slots `[type][nverts]` + nverts×(x,y) BE-int16, zero-padded.
    Round-trips the s30 captured SET/echo blobs byte-identically (validated). Coords = robot units (~5 mm)."""
    out = bytes([0x01, len(zones)])
    for ztype, pts in zones:
        slot = bytes([ztype, len(pts)]) + b"".join(struct.pack(">hh", int(x), int(y)) for x, y in pts)
        out += slot.ljust(_RZONE_STRIDE, b"\x00")
    return base64.b64encode(out).decode()


def parse_carpets(value):
    """CARPET_UP JSON → list of 4-corner polygons in ~5 mm/unit."""
    if not value:
        return []
    data = value if isinstance(value, dict) else json.loads(value)
    carpets = []
    for item in (data.get("data") or []):
        verts = item.get("vertexs") or []
        if verts:
            carpets.append([(v[0], v[1]) for v in verts])
    return carpets


def _mm_to_pixel(mm_y, mm_x, W, H, scale,
                 ox=GRID_ORIGIN_OX, oy=GRID_ORIGIN_OY, res=GRID_MM_PER_PIXEL,
                 coord_scale=1):
    """Convert coords → scaled image pixel. Returns None if OOB.

    coord_scale=2 is CORRECT for wall/zone/carpet DPs: their stored values are
    zone/wall units of ~5 mm = 2× the ~2.5 mm path-unit (k≈1.98 from both axes).
    (Earlier "half-mm" wording was the s13/s26 half-mm/half-cm slip — corrected s30.)
    """
    col = (mm_y * coord_scale - oy) // res
    row = (ox - mm_x * coord_scale) // res
    if 0 <= col < W and 0 <= row < H:
        return (col * scale + scale // 2, row * scale + scale // 2)
    return None


# ── overlay ──────────────────────────────────────────────────────────────────

def coord_to_pixel(path_x, path_y, W, H,
                   ox=GRID_ORIGIN_OX, oy=GRID_ORIGIN_OY, res=GRID_MM_PER_PIXEL):
    """Convert RENDER-frame path coords (parse_path's byte-16 output) → grid (col, row), or None if OOB.

    Convention: col←path_y, row←path_x (the app's display orientation), paired with parse_path's byte-16
    render coords. ⚠ Do NOT feed the TRUE (byte-14 / pose_extract) pose here — use path_to_pixel()."""
    col = (path_y - oy) // res
    row = (ox - path_x) // res
    if 0 <= col < W and 0 <= row < H:
        return col, row
    return None


def path_to_pixel(x, y, W, H, ox=GRID_ORIGIN_OX, oy=GRID_ORIGIN_OY, res=GRID_MM_PER_PIXEL):
    """Convert a TRUE (byte-14 / pose_extract) path point (x, y) → grid (col, row), or None if OOB.

    World→pixel registration: col←x, row←y inverted — `col=(x−oy)//res, row=(ox−y)//res` (a per-axis
    scale + Y-flip). Use for the real pose frame (heading 0=+x/+90=+y): pose_extract output, nav, the XY
    plot. Same form as upstream `GridCalibration.world_to_pixel`. (Implemented as coord_to_pixel with x,y
    swapped, since coord_to_pixel uses the app's col←y orientation.) See FRAME_ANATOMY §9."""
    return coord_to_pixel(y, x, W, H, ox, oy, res)


def render_overlay_png(grid, W, H, rooms, path_pts, dp_overlay=None, scale=3,
                       ox=GRID_ORIGIN_OX, oy=GRID_ORIGIN_OY, res=GRID_MM_PER_PIXEL):
    """Room grid PNG with the cleaning path and optional DP shapes overlaid.

    dp_overlay: dict from load_dp_overlay() — walls, no-go zones, carpets, etc.
    Dock = green circle, robot end = red circle.
    Virtual walls = dark red lines. No-go zones = red hatched rectangles.
    Cleaning zones = green rectangles. Carpets = blue outlines.
    """
    from PIL import Image, ImageDraw
    img = Image.new("RGB", (W * scale, H * scale), OUTSIDE)
    px = img.load()
    centroids = {}
    for i, b in enumerate(grid):
        gx, gy = i % W, i // W
        if b == 243:
            continue
        if b == 249:
            c = WALL
        elif b and b % 4 == 0:
            c = ROOM_COLORS[(b // 4 - 1) % len(ROOM_COLORS)]
            cc = centroids.setdefault(b // 4, [0, 0, 0])
            cc[0] += gx; cc[1] += gy; cc[2] += 1
        else:
            c = (210, 210, 210)
        for dy in range(scale):
            for dx in range(scale):
                px[gx * scale + dx, gy * scale + dy] = c

    draw = ImageDraw.Draw(img)
    for rid, (sx, sy, n) in centroids.items():
        if n < 30:
            continue
        label = rooms.get(rid, f"room{rid}").replace("rr_", "")
        draw.text((sx / n * scale, sy / n * scale), label, fill=(0, 0, 0), anchor="mm")

    # Path polyline
    pts_px = []
    for (path_x, path_y) in path_pts:
        p = coord_to_pixel(path_x, path_y, W, H, ox, oy, res)
        if p:
            pts_px.append((p[0] * scale + scale // 2, p[1] * scale + scale // 2))
    if pts_px:
        draw.line(pts_px, fill=(0, 100, 220), width=1)

    # Dock and end markers
    for (path_x, path_y), color in [(path_pts[0], (0, 200, 0)), (path_pts[-1], (220, 30, 30))]:
        p = coord_to_pixel(path_x, path_y, W, H, ox, oy, res)
        if p:
            r = scale + 3
            cx, cy = p[0] * scale + scale // 2, p[1] * scale + scale // 2
            draw.ellipse([cx - r, cy - r, cx + r, cy + r], fill=color, outline=(0, 0, 0))

    # DP overlay shapes
    if dp_overlay:
        def to_px(mm_y, mm_x):
            return _mm_to_pixel(mm_y, mm_x, W, H, scale, ox, oy, res, coord_scale=2)

        # Virtual walls — dark red thick lines
        # Wall format is (y,x) in path space (see PROTOCOL session 9 + docstring)
        for (y1, x1), (y2, x2) in dp_overlay.get("walls", []):
            p1 = to_px(y1, x1)
            p2 = to_px(y2, x2)
            if p1 and p2:
                draw.line([p1, p2], fill=(180, 0, 0), width=scale + 1)

        # No-go zones — red semi-transparent rectangles
        # Zone/carpet points are stored as (x, y) where x=col-direction (path_y), y=row-direction (path_x).
        # to_px(mm_y, mm_x) maps col=f(mm_y) and row=f(mm_x), so pass (p[0], p[1]) = (zone_x, zone_y).
        # (Walls are different: parse_virtual_walls stores (path_y, path_x) directly, so to_px(y1,x1) is correct.)
        for pts in dp_overlay.get("no_go", []):
            pxpts = [to_px(p[0], p[1]) for p in pts]
            pxpts = [p for p in pxpts if p]
            if len(pxpts) >= 2:
                draw.polygon(pxpts, outline=(220, 30, 30), fill=None)

        # No-mop zones — orange rectangles
        for pts in dp_overlay.get("no_mop", []):
            pxpts = [to_px(p[0], p[1]) for p in pts]
            pxpts = [p for p in pxpts if p]
            if len(pxpts) >= 2:
                draw.polygon(pxpts, outline=(240, 140, 0), fill=None)

        # Cleaning zones — green rectangles
        for pts in dp_overlay.get("clean_zones", []):
            pxpts = [to_px(p[0], p[1]) for p in pts]
            pxpts = [p for p in pxpts if p]
            if len(pxpts) >= 2:
                draw.polygon(pxpts, outline=(0, 180, 60), fill=None)

        # Carpets — blue outlines
        for pts in dp_overlay.get("carpets", []):
            pxpts = [to_px(p[0], p[1]) for p in pts]
            pxpts = [p for p in pxpts if p]
            if len(pxpts) >= 2:
                draw.polygon(pxpts, outline=(30, 80, 220), fill=None)

    return img


# ── structured (machine-consumable) output ──────────────────────────────────

def room_geometry(grid, W, H):
    """Per-room pixel geometry from the occupancy grid.

    Returns {room_id: {"bbox_px": [min_col,min_row,max_col,max_row],
                       "centroid_px": [col,row], "cells": n}}. Pixels are grid cells;
    use the georeference block to convert to mm. Lets a consumer place room labels /
    hit-test which room a coordinate is in without re-walking the grid.
    """
    geo = {}
    for i, b in enumerate(grid):
        if b and b % 4 == 0:
            rid = b // 4
            col, row = i % W, i // W
            g = geo.get(rid)
            if g is None:
                geo[rid] = [col, row, col, row, col, row, 1]  # min_c,min_r,max_c,max_r,sum_c,sum_r,n
            else:
                g[0] = min(g[0], col); g[1] = min(g[1], row)
                g[2] = max(g[2], col); g[3] = max(g[3], row)
                g[4] += col; g[5] += row; g[6] += 1
    out = {}
    for rid, g in geo.items():
        n = g[6]
        out[rid] = {"bbox_px": [g[0], g[1], g[2], g[3]],
                    "centroid_px": [round(g[4] / n), round(g[5] / n)], "cells": n}
    return out


def room_at_pixel(grid, W, H, col, row):
    """room_id at grid (col,row), or None for outside/wall/out-of-bounds."""
    if not (0 <= col < W and 0 <= row < H):
        return None
    b = grid[row * W + col]
    return b // 4 if (b and b % 4 == 0) else None


def robot_room(last_pt, grid, W, H, ox=GRID_ORIGIN_OX, oy=GRID_ORIGIN_OY,
               res=GRID_MM_PER_PIXEL, search_radius=2):
    """Map the robot's last path point (mm) → ((col,row), room_id).

    Exact cell first; if the robot sits on a wall/boundary pixel, take the majority
    room within a few px. Returns ((col,row) or None, room_id or None).
    """
    cp = coord_to_pixel(last_pt[0], last_pt[1], W, H, ox, oy, res)
    if cp is None:
        return None, None
    col, row = cp
    rid = room_at_pixel(grid, W, H, col, row)
    if rid is None:
        from collections import Counter
        votes = Counter()
        for rad in range(1, search_radius + 1):
            for dc in range(-rad, rad + 1):
                for dr in range(-rad, rad + 1):
                    r = room_at_pixel(grid, W, H, col + dc, row + dr)
                    if r is not None:
                        votes[r] += 1
            if votes:
                break
        rid = votes.most_common(1)[0][0] if votes else None
    return (col, row), rid


def latest_path(paths):
    """Most-RECENT path frame = the robot's CURRENT position. On a multi-clean capture, take
    the latest in time, NOT the largest (`max(...,key=len)`): the biggest frame may be an
    earlier/larger room, which would report the robot in the wrong place. Ties → file order."""
    return max(enumerate(paths), key=lambda iv: (iv[1][0] or "", iv[0]))[1]


def largest_path(paths):
    """Most-COMPLETE single path frame = best for the georef fit (most points to land on floor)."""
    return max(paths, key=lambda x: len(x[1]))


def build_map_json(cap, dps_path=None):
    """Decode a `watch --bytes` capture into a structured, machine-consumable dict.

    The "give others the data" surface (CAPABILITIES #21): a status panel / web UI / HA shell
    command can consume this instead of parsing a PNG. Coordinate frames — path,
    robot.position_mm, path.points_mm, and overlay shapes are robot **mm** (path frame);
    room bbox/centroid and robot.position_px are grid **pixels**; the `georeference`
    block carries the mm↔pixel transform. Schema id: `roborock-b01-map/1`.
    """
    result = {
        "schema": "roborock-b01-map/1",
        "source": {"capture": cap},
        "grid": None, "georeference": None, "rooms": [], "robot": None,
        "path": None, "overlay": None,
    }
    paths = load_frames(cap, PATH_SIG)
    grids = load_frames(cap, GRID_PREFIX)
    result["source"]["path_frames"] = len(paths)
    result["source"]["grid_frames"] = len(grids)

    pts = None          # LATEST frame → robot position + current path
    fit_pts = None      # LARGEST frame → georef fit (most points = best registration)
    if paths:
        tm, raw = latest_path(paths)
        pts, declared = parse_path(raw)
        pts = _drop_path_outlier(pts)
        fit_pts = _drop_path_outlier(parse_path(largest_path(paths)[1])[0])
        result["source"]["path_frame_time"] = tm
        result["source"]["path_frame_selection"] = "latest for robot/path; largest for georef fit"
        result["path"] = {
            "point_count": len(pts),
            "declared_count": declared,
            "start_mm": list(pts[0]) if pts else None,
            "robot_mm": list(pts[-1]) if pts else None,
            "points_mm": [[x, y] for x, y in pts],
        }

    if grids:
        tm, raw = max(grids, key=lambda x: len(x[1]))
        out = decompress_grid(raw)
        W, H, grid, dsrc = resolve_dims(raw, out)
        rooms, _ = parse_rooms(out)
        result["source"]["grid_frame_time"] = tm
        result["grid"] = {
            "width": W, "height": H, "dims_source": dsrc, "map_id": raw[2:6].hex(),
            "cell_legend": {"243": "outside", "249": "wall",
                            "floor": "v where v%4==0; room_id = v//4"},
        }
        geo = room_geometry(grid, W, H)
        result["rooms"] = [
            {"id": rid, "name": rooms.get(rid, f"room{rid}"),
             "bbox_px": geo[rid]["bbox_px"] if rid in geo else None,
             "centroid_px": geo[rid]["centroid_px"] if rid in geo else None,
             "cells": geo[rid]["cells"] if rid in geo else 0}
            for rid in sorted(set(rooms) | set(geo))
        ]

        ox, oy, res = GRID_ORIGIN_OX, GRID_ORIGIN_OY, GRID_MM_PER_PIXEL
        fit_method, fit_score = "default", None
        hdr = origin_from_header(raw)          # the origin IS in the frame header — prefer it; retires auto-fit
        if hdr:
            ox, oy = hdr
            fit_method = "header"
        if pts:
            fit = fit_origin(grid, W, H, fit_pts or pts)
            if fit:
                fit_score = fit[3]             # auto-fit score retained as a cross-check on the header origin
                if fit_method != "header":
                    if fit[3] >= 0.90:
                        ox, oy, res, fit_method = fit[0], fit[1], fit[2], "auto"
                    else:
                        fit_method = "default(weak-fit)"
        result["georeference"] = {
            "origin_mm": {"ox": ox, "oy": oy},
            "resolution_mm_per_px": res,
            "grid_mm_per_px": round(res * 2.5),   # ≈50: the TRUE physical cell size (1 path-unit ≈ 2.5 mm)
            "fit_method": fit_method,
            "fit_score": round(fit_score, 4) if fit_score is not None else None,
            "transform": "col = (path_y - oy) // res ; row = (ox - path_x) // res",
            "unit_note": ("⚠ origin_mm / resolution_mm_per_px are MISLABELED for back-compat: ox/oy/res and the 0201 "
                          "path coords are PATH-UNITS (≈2.5 mm/unit, anchored to the app's 3.3 ft default zone), NOT mm. "
                          "resolution_mm_per_px=20 means 20 path-units/px; the true physical cell is grid_mm_per_px≈50. "
                          "Use res (path-units) in `transform`; use grid_mm_per_px for physical distances. "
                          "(A clean rename to *_pathunits is pending — kept under the old keys for back-compat.)"),
            "axis_note": "grid col from path y, grid row from path x; row axis inverted; oy is typically negative.",
            "origin_note": "origin IS in the 0101 header (x_min@11-12, y_min@13-14, s16 BE, 5-mm units): ox=2*y_min, oy=-2*x_min (fit_method='header'). auto-fit is now a fallback/cross-check for null-origin frames; per-install, stable until the dock moves or the map resets.",
        }

        if pts:
            rc, rid = robot_room(pts[-1], grid, W, H, ox, oy, res)
            result["robot"] = {
                "position_mm": list(pts[-1]),
                "position_px": list(rc) if rc else None,
                "in_grid": rc is not None,
                "current_room": ({"id": rid, "name": rooms.get(rid, f"room{rid}")}
                                 if rid is not None else None),
                "note": "position/room are live during a clean OR while DP-110 HEARTBEAT polls are active (teleop pose); docked-idle with no heartbeat → no path frame is emitted.",
            }

    if dps_path:
        ov = load_dp_overlay(dps_path)
        result["overlay"] = {
            "walls": [[list(a), list(b)] for a, b in ov["walls"]],
            "no_go": [[list(p) for p in z] for z in ov["no_go"]],
            "no_mop": [[list(p) for p in z] for z in ov["no_mop"]],
            "clean_zones": [[list(p) for p in z] for z in ov["clean_zones"]],
            "carpets": [[list(p) for p in z] for z in ov["carpets"]],
        }
    return result


# ── main ─────────────────────────────────────────────────────────────────────

def main():
    argv = sys.argv[1:]
    if not argv or argv[0] in ("-h", "--help"):
        print(__doc__)
        sys.exit(0)

    # Parse: decode_map.py <capture.jsonl> [--dps <raw-watch.jsonl>] [--json]
    dps_path = None
    positional = []
    json_mode = False
    i = 0
    while i < len(argv):
        if argv[i] == "--dps" and i + 1 < len(argv):
            dps_path = argv[i + 1]
            i += 2
        elif argv[i] == "--json":
            json_mode = True
            i += 1
        else:
            positional.append(argv[i])
            i += 1
    if not positional:
        print("usage: decode_map.py <capture.jsonl> [--dps <raw-watch.jsonl>] [--json]")
        sys.exit(1)
    cap = positional[0]

    for f in (cap, dps_path):
        if f is not None:
            try:
                open(f).close()
            except FileNotFoundError:
                sys.exit(f"File not found: {f}")
            except OSError as e:
                sys.exit(f"Cannot read {f}: {e}")

    # Machine-consumable output: structured data on stdout, no images, no chatter
    # (so `decode_map.py cap.jsonl --json | jq` is clean). See build_map_json / CAPABILITIES #21.
    if json_mode:
        print(json.dumps(build_map_json(cap, dps_path), indent=2))
        return

    dp_overlay = load_dp_overlay(dps_path) if dps_path else None
    if dp_overlay:
        print(f"DP overlay: {len(dp_overlay.get('walls', []))} wall(s), "
              f"{len(dp_overlay.get('no_go', []))} no-go zone(s), "
              f"{len(dp_overlay.get('clean_zones', []))} clean zone(s), "
              f"{len(dp_overlay.get('carpets', []))} carpet(s)")

    paths = load_frames(cap, PATH_SIG)
    grids = load_frames(cap, GRID_PREFIX)
    print(f"path frames: {len(paths)}   grid frames: {len(grids)}")

    if paths:
        tm, raw = latest_path(paths)           # robot's CURRENT position = latest frame (NOT largest)
        pts, declared = parse_path(raw)
        pts = _drop_path_outlier(pts)          # s24: strip the spurious leading sentinel (green-dot bug)
        xs = [p[0] for p in pts]; ys = [p[1] for p in pts]
        print(f"\nPATH @ {tm} (latest): {len(pts)} points (header {declared})")
        print(f"  extent x {min(xs)}..{max(xs)}  y {min(ys)}..{max(ys)} "
              f"(~{(max(xs)-min(xs))/1000:.1f}m x {(max(ys)-min(ys))/1000:.1f}m)")
        print(f"  start (dock?): {pts[0]}   robot now: {pts[-1]}")
        with open("map_path.svg", "w") as f:
            f.write(render_path_svg(pts))
        print("  wrote map_path.svg")

    if grids:
        tm, raw = max(grids, key=lambda x: len(x[1]))
        out = decompress_grid(raw)
        W, H, grid, dsrc = resolve_dims(raw, out)
        rooms, _ = parse_rooms(out)
        print(f"\nROOM GRID @ {tm}: {len(grid)} cells, {W}x{H} (via {dsrc}), {len(rooms)} rooms")
        for rid in sorted(rooms):
            print(f"  room {rid}: {rooms[rid]}")
        img = render_grid_png(grid, W, H, rooms)
        img.save("map_rooms.png")
        print(f"  wrote map_rooms.png ({img.size[0]}x{img.size[1]})")

        if paths:
            pts, _ = parse_path(largest_path(paths)[1])   # fit on the most-complete frame (best registration)
            pts = _drop_path_outlier(pts)      # s24: same sentinel strip as the SVG path
            hdr = origin_from_header(raw)       # the origin is in the frame header — prefer it
            fit = fit_origin(grid, W, H, pts)  # auto-fit kept as a cross-check / fallback
            sc = fit[3] if fit else None
            if hdr:
                ox, oy, res = hdr[0], hdr[1], GRID_MM_PER_PIXEL
                xc = f"{sc*100:.1f}% on floor" if sc is not None else "no path to cross-check"
                print(f"  georef from header: OX={ox} OY={oy} res={res} (auto-fit cross-check: {xc})")
            elif fit and fit[3] >= 0.90:
                ox, oy, res = fit[0], fit[1], fit[2]
                print(f"  georef auto-fit (no header origin): OX={ox} OY={oy} res={res} ({sc*100:.1f}% of path on floor)")
            else:
                ox, oy, res = GRID_ORIGIN_OX, GRID_ORIGIN_OY, GRID_MM_PER_PIXEL
                why = f"weak ({fit[3] * 100:.0f}%)" if fit else "no fit"
                print(f"  georef auto-fit {why} → committed OX={ox} OY={oy} res={res}")
            overlay = render_overlay_png(grid, W, H, rooms, pts, dp_overlay=dp_overlay,
                                         ox=ox, oy=oy, res=res)
            overlay.save("map_overlay.png")
            suffix = " + DP shapes" if dp_overlay else ""
            print(f"  wrote map_overlay.png (path on grid{suffix})")


if __name__ == "__main__":
    main()
