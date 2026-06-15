#!/usr/bin/env python3
"""
Decode the Roborock Q10 (B01) live map from a `vac.py watch --bytes` capture.

The robot streams protocol-301 `map_response` frames over MQTT *while cleaning*
(spontaneously — no request needed). python-roborock's B01 path drops them (its
dps decoder only accepts protocol-102 JSON), so `watch --bytes` is how we capture
them. This tool decodes them.

Two 301 sub-types, distinguished by their first 8 header bytes:
  • 0201000800020000  — the CLEANING PATH. Big-endian int16 (x,y) pairs after a
    16-byte header (bytes 8-9 = point count). Units = mm; LAST point = robot's
    current position; first ≈ dock. Rendered to an SVG polyline.
  • 0101…  — the ROOM/OCCUPANCY GRID (match the 2-byte prefix; bytes 2-5 are a
    device-specific map id). **LZ4-compressed** (not RLE).
    Header: declared size = bytes[25:27] BE, comp len = bytes[27:29] BE, LZ4 block
    from byte 29. Decompresses to a width×height grid (`pixel//4 = room_id`,
    243=outside, 249=wall) followed by room records (`[0x01,count]` then count×47B;
    name length at record byte 26, name from byte 27). Grid width is found
    empirically (the row stride that makes vertically-adjacent rows most similar).
    Rendered to a colour-coded PNG with room-name labels.
    Format credit: v1b3c0d3x3r/roborock-qseries-map-bridge (prior art).

Optional DP overlay (--dps <raw-watch-jsonl>):
  Pass a `watch --raw` JSONL (or your_capture.jsonl) to overlay walls, no-go
  zones, cleaning zones, and carpets on the map_overlay.png.
  DP formats (all confirmed, DECISIONS sessions 9-10):
    VIRTUAL_WALL_UP  = [count:u8] + count×(x1,y1,x2,y2) BE int16, mm.
                       NOTE: wall coords are (y,x) vs path's (x,y) — first value
                       is path_y, second is path_x (swap on coord_to_pixel call).
    RESTRICTED_ZONE_UP = [0x01][count:u8] + count×([type:u8][nverts:u8=4] + 4×(x,y) BE int16)
                       type=0x00 for no-go, 0x01 for no-mop zone.
    ZONED_UP         = identical format, type=0x01 for cleaning zone.
    CARPET_UP        = JSON {"data":[{id,rug_clean_mode,vertexs:[[x,y]×4]},...]}

Usage:
  ./vac.py watch --bytes --out cap.jsonl     # capture while the robot cleans
  ./vac.py watch --raw --out raw.jsonl       # capture DPs (walls, zones) simultaneously
  ./decode_map.py cap.jsonl                  # -> map_path.svg, map_rooms.png, map_overlay.png
  ./decode_map.py cap.jsonl --dps raw.jsonl  # -> overlay includes walls + zones
"""
import base64
import json
import struct
import sys

# Path frames: match only the 2-byte sub-type PREFIX (0201). Byte 3 of the full header
# varies by session / firmware / clean-mode (0x08 AND 0x11 both observed — s23 mop-mode
# emitted 0201_0011_...); parse_path reads the point count from bytes 8-9 and is agnostic
# to it. Matching the full 8-byte sig "0201000800020000" found ZERO path frames whenever
# byte 3 differed (it silently dropped the entire s23 cleaning path). See DECISIONS s23.
PATH_SIG = "0201"
# Grid frames: match only the 2-byte sub-type PREFIX. Bytes 2-5 of the full 8-byte
# header are a device-specific map id (e.g. <device-map-id> on the dev's robot) and differ per
# device/home — matching the full signature would find zero frames on anyone else's robot.
GRID_PREFIX = "0101"

# Grid ↔ path registration (empirically derived; stable while dock position / map unchanged).
# col = (path_y - GRID_ORIGIN_OY) // GRID_MM_PER_PIXEL   ← grid column  (x-axis)
# row = (GRID_ORIGIN_OX - path_x) // GRID_MM_PER_PIXEL   ← grid row     (y-axis, inverted)
# Score: 99.87 % of path points land on floor pixels at these values (6117/6125).
GRID_ORIGIN_OX = 1001   # mm — path_x that maps to grid row 0 (top edge)
GRID_ORIGIN_OY = -3307  # mm — path_y that maps to grid col 0 (left edge)
GRID_MM_PER_PIXEL = 20  # mm per grid pixel (standard Roborock resolution)

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
    """Return (points, declared_count). Big-endian int16 (x,y) after 16-byte header.

    WORKED AROUND, NOT understood (s24): the 0201_0x11+ frames carry a SPURIOUS first point —
    a constant ~(0,-1900) (x≈map-origin, y≈dock-y), outside the map; the 0008 era had a normal
    point here. The header is 16 bytes for BOTH eras (byte 3 is just a per-clean counter), so
    pts[0] is structurally a real point whose VALUE is anomalous — we don't know why the newer
    firmware emits it (dock/origin reference? delta base?). Callers strip it via
    `_drop_path_outlier(pts)` (a band-aid, NOT a resolution). Do NOT "fix" by shifting the offset
    (16→18 re-pairs every int16 and transposes the path — tried+reverted s23). OPEN: DECISIONS/TASKS.
    """
    count = struct.unpack(">H", raw[8:10])[0]
    body = raw[16:]
    n = len(body) // 4
    pts = [struct.unpack(">hh", body[i * 4:i * 4 + 4]) for i in range(n)]
    return pts, count


def _drop_path_outlier(pts):
    """BAND-AID (not a resolution) for the unexplained spurious first point in 0201_0x11+ path
    frames (a constant ~(0,-1900), outside the map — meaning UNKNOWN; see parse_path + DECISIONS
    s24 OPEN QUESTION). Drop pts[0] ONLY if its step to pts[1] is a gross outlier (>20x the median
    step), so a real pts[0] (e.g. the 0008 dock point) is never dropped. Surfaced as the green
    START dot landing outside the apartment walls (user-caught, s24).
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
    """The row stride that makes vertically-adjacent rows most similar (real image)."""
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
    return best[1], best[2]  # (W, H)


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
        "no_mop":      parse_restricted_zones(latest.get("RESTRICTED_ZONE_UP"), want_type=0x01),
        "clean_zones": parse_restricted_zones(latest.get("ZONED_UP"), want_type=0x01),
        "carpets":     parse_carpets(latest.get("CARPET_UP")),
    }


def parse_virtual_walls(value):
    """VIRTUAL_WALL_UP base64 → list of ((y1,x1),(y2,x2)) in mm path space.

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


def parse_restricted_zones(value, want_type):
    """RESTRICTED_ZONE_UP / ZONED_UP base64 → list of 4-corner polygons in mm.

    Format: [0x01][count:u8] + count × ([type:u8][nverts:u8=4] + 4×(x,y) BE int16)
    want_type=0x00 → no-go zones; 0x01 → no-mop / cleaning zones.
    """
    if not value:
        return []
    raw = base64.b64decode(value)
    if len(raw) < 2 or raw[0] != 0x01:
        return []
    count = raw[1]
    zones = []
    pos = 2
    for _ in range(count):
        if pos + 2 > len(raw):
            break
        zone_type = raw[pos]
        nverts = raw[pos + 1]
        pos += 2
        pts = []
        for _ in range(nverts):
            if pos + 4 > len(raw):
                break
            x, y = struct.unpack(">hh", raw[pos:pos + 4])
            pts.append((x, y))
            pos += 4
        if zone_type == want_type:
            zones.append(pts)
    return zones


def parse_carpets(value):
    """CARPET_UP JSON → list of 4-corner polygons in mm."""
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

    coord_scale=2 for wall/zone/carpet DPs whose stored values are in half-mm
    units (empirically: stored_val × 2 = path mm, k≈1.98 from both axes).
    """
    col = (mm_y * coord_scale - oy) // res
    row = (ox - mm_x * coord_scale) // res
    if 0 <= col < W and 0 <= row < H:
        return (col * scale + scale // 2, row * scale + scale // 2)
    return None


# ── overlay ──────────────────────────────────────────────────────────────────

def coord_to_pixel(path_x, path_y, W, H,
                   ox=GRID_ORIGIN_OX, oy=GRID_ORIGIN_OY, res=GRID_MM_PER_PIXEL):
    """Convert robot mm coords (path frame) → grid (col, row). Returns None if out of bounds."""
    col = (path_y - oy) // res
    row = (ox - path_x) // res
    if 0 <= col < W and 0 <= row < H:
        return col, row
    return None


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
        # Wall format is (y,x) in path space (see DECISIONS session 9 + docstring)
        for (y1, x1), (y2, x2) in dp_overlay.get("walls", []):
            p1 = to_px(y1, x1)
            p2 = to_px(y2, x2)
            if p1 and p2:
                draw.line([p1, p2], fill=(180, 0, 0), width=scale + 1)

        # No-go zones — red semi-transparent rectangles
        for pts in dp_overlay.get("no_go", []):
            pxpts = [to_px(p[1], p[0]) for p in pts]
            pxpts = [p for p in pxpts if p]
            if len(pxpts) >= 2:
                draw.polygon(pxpts, outline=(220, 30, 30), fill=None)

        # No-mop zones — orange rectangles
        for pts in dp_overlay.get("no_mop", []):
            pxpts = [to_px(p[1], p[0]) for p in pts]
            pxpts = [p for p in pxpts if p]
            if len(pxpts) >= 2:
                draw.polygon(pxpts, outline=(240, 140, 0), fill=None)

        # Cleaning zones — green rectangles
        for pts in dp_overlay.get("clean_zones", []):
            pxpts = [to_px(p[1], p[0]) for p in pts]
            pxpts = [p for p in pxpts if p]
            if len(pxpts) >= 2:
                draw.polygon(pxpts, outline=(0, 180, 60), fill=None)

        # Carpets — blue outlines
        for pts in dp_overlay.get("carpets", []):
            pxpts = [to_px(p[1], p[0]) for p in pts]
            pxpts = [p for p in pxpts if p]
            if len(pxpts) >= 2:
                draw.polygon(pxpts, outline=(30, 80, 220), fill=None)

    return img


# ── main ─────────────────────────────────────────────────────────────────────

def main():
    argv = sys.argv[1:]
    if not argv or argv[0] in ("-h", "--help"):
        print(__doc__)
        sys.exit(0)

    # Parse: decode_map.py <capture.jsonl> [--dps <raw-watch.jsonl>]
    dps_path = None
    positional = []
    i = 0
    while i < len(argv):
        if argv[i] == "--dps" and i + 1 < len(argv):
            dps_path = argv[i + 1]
            i += 2
        else:
            positional.append(argv[i])
            i += 1
    if not positional:
        print("usage: decode_map.py <capture.jsonl> [--dps <raw-watch.jsonl>]")
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
        tm, raw = max(paths, key=lambda x: len(x[1]))
        pts, declared = parse_path(raw)
        pts = _drop_path_outlier(pts)          # s24: strip the spurious leading sentinel (green-dot bug)
        xs = [p[0] for p in pts]; ys = [p[1] for p in pts]
        print(f"\nPATH @ {tm}: {len(pts)} points (header {declared})")
        print(f"  extent x {min(xs)}..{max(xs)}  y {min(ys)}..{max(ys)} "
              f"(~{(max(xs)-min(xs))/1000:.1f}m x {(max(ys)-min(ys))/1000:.1f}m)")
        print(f"  start (dock?): {pts[0]}   robot now: {pts[-1]}")
        with open("map_path.svg", "w") as f:
            f.write(render_path_svg(pts))
        print("  wrote map_path.svg")

    if grids:
        tm, raw = max(grids, key=lambda x: len(x[1]))
        out = decompress_grid(raw)
        rooms, grid_len = parse_rooms(out)
        grid = out[:grid_len]
        W, H = find_width(grid)
        print(f"\nROOM GRID @ {tm}: {len(grid)} cells, {W}x{H}, {len(rooms)} rooms")
        for rid in sorted(rooms):
            print(f"  room {rid}: {rooms[rid]}")
        img = render_grid_png(grid, W, H, rooms)
        img.save("map_rooms.png")
        print(f"  wrote map_rooms.png ({img.size[0]}x{img.size[1]})")

        if paths:
            pts, _ = parse_path(max(paths, key=lambda x: len(x[1]))[1])
            pts = _drop_path_outlier(pts)      # s24: same sentinel strip as the SVG path
            overlay = render_overlay_png(grid, W, H, rooms, pts, dp_overlay=dp_overlay)
            overlay.save("map_overlay.png")
            suffix = " + DP shapes" if dp_overlay else ""
            print(f"  wrote map_overlay.png (path on grid{suffix})")


if __name__ == "__main__":
    main()
