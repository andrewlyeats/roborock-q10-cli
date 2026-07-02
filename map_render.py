#!/usr/bin/env python3
"""Reusable, canonical map renderer for the Roborock Q10 (B01) live map.

Stop hand-rolling one-off annotation scripts. This is the single place that turns a
`vac.py watch --bytes` capture (+ an optional `watch --raw` DP capture) into annotated
PNGs. It does NOT re-derive the decode — it reuses the SETTLED functions in
`decode_map.py` (grid LZ4 codec, header dims, header georef origin, path parse, DP
overlay) and `pose_extract.py` (true byte-14 pose + SLAM heading). See FRAME_ANATOMY.md
for the byte layout and PROTOCOL.md for why these constants are not to be re-fit.

Two render styles (pick with --style; default = both):

  • decode  — exactly what decode_map already produces:
      <prefix>_rooms.png    colour-coded room/occupancy grid with room labels
      <prefix>_overlay.png  path + dock/robot markers + DP walls/zones/carpets on the grid
    (uses decode_map's existing render path — parse_path's byte-16 coords on the LARGEST frame —
    so this output matches map_overlay.png pixel-for-pixel.)

  • xy      — a NEW true-scale XY plot in PATH-UNITS (~2.5 mm/unit):
      <prefix>_xy.png
    Standard math orientation: path-X horizontal (→ +x), path-Y vertical (↑ +y), so the
    firmware heading convention (0=+x, +90=+y, ±180=−x, −90=−y) renders directly as the
    arrow angle. (decode_map's overlay renders in the app's display orientation instead; this
    XY view uses world axes so they read in real path-units.) It draws:
      - labelled X/Y axes + ticks in path-units, equal scale on both axes (true-scale)
      - occupancy WALLS (grid cell 249); --rooms also tints floor cells by room
      - the cleaning PATH polyline (byte-14 TRUE pose from pose_extract, LATEST frame)
      - the map ORIGIN (ox = 2·y_min, oy = −2·x_min from the 0101 header) marked + labelled
      - a HEADING arrow at the robot's CURRENT position (heading from the 0201 header bytes 10–11)
      - dock (≈ first path point) + robot markers
      - optional --samples N labelled (x,y) points spaced along the path

Registration (deliberate, CORPUS-VALIDATED — see PROTOCOL 2026-06-23):
  - Frame: the PATH polyline uses the LARGEST path frame (like decode_map), NOT the latest. The
    latest frame is often a different path-EPOCH (0201 bytes 2-3) than the grid → it won't land on
    the grid in any orientation. The live robot pose + heading come from the latest frame ONLY when
    it shares the grid's epoch (≥80% of its points register); otherwise the marker falls back to the
    path end and the renderer SAYS the latest frame was off-grid. Self-check (% of path on floor) is
    printed every run, so misregistration on a build/multi-epoch capture is flagged, never silent.
  - Offset: byte-14 TRUE pose (pose_extract) for the XY plot — real coords + real heading — placed on
    the grid with decode_map.path_to_pixel (col←x, row←y inverted), the registration verified 97-100%
    on-floor on 49/51 corpus maps. The decode-style overlay keeps parse_path (byte 16) so it stays
    identical to decode_map.
  - Orientation: the path↔grid orientation is a VALIDATED CONVENTION (corpus-invariant, but not read
    from any header field). The `Registration` defaults to the read header-standard; when that lands
    few path points on floor (an unseen home / firmware / re-oriented map) it FITS orientation+origin
    by on-floor (decode_map.fit_registration, ≈ upstream solve_calibration) — conservatively, so a
    short/degenerate path never gets a spurious "recovery". So a deviating map auto-recovers or is
    flagged, never silently mis-rendered.

PIL only (no matplotlib/scipy/cv2 — project convention, see the project docs).

Usage:
  ./map_render.py <capture.jsonl> [--dps <raw-watch.jsonl>] [--style decode|xy|both]
                  [--out <prefix>] [--rooms] [--no-walls] [--samples N]
  ./map_render.py capture.jsonl --style xy --samples 6

Output PNGs reveal the home floorplan → they are gitignored (cap_render_*.png / *_xy.png).
"""
import math
import sys

import decode_map as dm
import pose_extract as pe


# ── path↔grid registration (orientation + origin) ───────────────────────────

class Registration:
    """Maps a TRUE (byte-14) pose ↔ grid cell, in ONE orientation so the path and walls stay in the same
    frame. The DEFAULT is the header-read Q10 standard (`col←x, row←y-inverted` = decode_map.path_to_pixel;
    same form as upstream GridCalibration). A FITTED instance (from decode_map.fit_registration)
    covers an unseen orientation (different home/firmware/re-oriented map). General form:
        col = (sign_c·cval − oc)//res ,  row = (sign_r·rval − orow)//res ,  (cval,rval) = (x,y) or (y,x) per swap.
    cell_bounds() is the exact inverse (cell → world-coord extent) the renderer draws walls with."""

    def __init__(self, swap, sign_c, sign_r, oc, orow, res, W, H, source):
        self.swap, self.sign_c, self.sign_r = swap, sign_c, sign_r
        self.oc, self.orow, self.res = oc, orow, res
        self.W, self.H, self.source = W, H, source

    @classmethod
    def header_standard(cls, ox, oy, res, W, H):
        """The validated Q10 default: col=(x−oy)//res, row=(ox−y)//res (== decode_map.path_to_pixel)."""
        return cls(False, 1, -1, oy, -ox, res, W, H, "header-standard")

    @classmethod
    def from_fit(cls, params, W, H, score):
        swap, sign_c, sign_r, oc, orow, res = params
        std = (not swap) and sign_c == 1 and sign_r == -1
        return cls(swap, sign_c, sign_r, oc, orow, res, W, H,
                   f"fitted({'standard-orient' if std else f'swap={swap},sc={sign_c},sr={sign_r}'}, {score*100:.0f}% on-floor)")

    def to_cell(self, x, y):
        cval = y if self.swap else x
        rval = x if self.swap else y
        col = (self.sign_c * cval - self.oc) // self.res
        row = (self.sign_r * rval - self.orow) // self.res
        return (col, row) if (0 <= col < self.W and 0 <= row < self.H) else None

    def cell_bounds(self, col, row):
        """Grid cell (col,row) → true-pose extent (x0,x1,y0,y1). Exact inverse of to_cell()."""
        cval0, cval1 = sorted(((col * self.res + self.oc) / self.sign_c,
                               ((col + 1) * self.res + self.oc) / self.sign_c))
        rval0, rval1 = sorted(((row * self.res + self.orow) / self.sign_r,
                               ((row + 1) * self.res + self.orow) / self.sign_r))
        if self.swap:                       # cval=y, rval=x
            return rval0, rval1, cval0, cval1
        return cval0, cval1, rval0, rval1    # cval=x, rval=y


# ── scene assembly (decode once, render many) ────────────────────────────────

class MapScene:
    """One capture decoded into everything both renderers need. Reuses decode_map /
    pose_extract — no decode logic is re-implemented here."""

    def __init__(self, cap, dps=None):
        self.cap = cap
        self.dps = dps
        self.paths = dm.load_frames(cap, dm.PATH_SIG)
        self.grids = dm.load_frames(cap, dm.GRID_PREFIX)

        # Grid (largest frame = most-complete map). resolve_dims prefers header dims.
        self.grid = self.W = self.H = self.rooms = None
        self.dims_source = None
        self.grid_raw = None
        if self.grids:
            tm, raw = max(self.grids, key=lambda x: len(x[1]))
            out = dm.decompress_grid(raw)
            self.W, self.H, self.grid, self.dims_source = dm.resolve_dims(raw, out)
            self.rooms, _ = dm.parse_rooms(out)
            self.grid_raw = raw
            self.grid_time = tm

        # Render-style path: byte-16 parse_path on the LARGEST frame (matches decode_map).
        self.render_pts = None
        if self.paths:
            self.render_pts = dm._drop_path_outlier(dm.parse_path(dm.largest_path(self.paths)[1])[0])

        # XY-style path = byte-14 TRUE pose (pose_extract) on the LARGEST (most-complete) frame.
        #
        # ★ Frame choice matters MORE than the offset. decode_map registers its overlay on the LARGEST
        # path frame, not the latest, because the LATEST frame is often a different path-EPOCH than the
        # grid (bytes 2-3; a relocalize/new-traversal shifts the coordinate frame) → it won't land on
        # the grid in ANY orientation. Verified across the corpus: the byte-14 pose lands 97-100% on
        # floor on the LARGEST frame for 49/51 maps, but the LATEST frame misregisters on map-builds
        # (mapbuild_study, s26). So the PATH polyline uses the largest frame; the live robot pose +
        # heading come from the latest frame ONLY when it shares the grid's epoch (checked below).
        self.path_pts = None          # LARGEST frame → the cleaning-path polyline (registers universally)
        self.path_heading = None
        self.path_epoch = None
        self.late_pts = self.late_heading = self.late_epoch = self.pose_time = None
        pframes = [f for f in pe.pose_frames(cap) if f[2]]
        if pframes:
            _, _, lpts, lh, lep = max(pframes, key=lambda f: len(f[2]))         # largest = most points
            self.path_pts = dm._drop_path_outlier(lpts)
            self.path_heading, self.path_epoch = lh, lep
            tm, _, npts, nh, nep = max(pframes, key=lambda f: (f[0] or "", len(f[2])))  # latest in time
            self.late_pts = dm._drop_path_outlier(npts)
            self.late_heading, self.late_epoch, self.pose_time = nh, nep, tm

        # Georef origin: header first (origin_from_header), then auto-fit, then defaults —
        # the same selection decode_map.main() uses, so both styles share one transform.
        self.ox, self.oy, self.res = dm.GRID_ORIGIN_OX, dm.GRID_ORIGIN_OY, dm.GRID_MM_PER_PIXEL
        self.fit_method = "default"
        self.fit_score = None
        if self.grid_raw is not None:
            hdr = dm.origin_from_header(self.grid_raw)
            if hdr:
                self.ox, self.oy = hdr
                self.fit_method = "header"
            if self.render_pts:
                fit = dm.fit_origin(self.grid, self.W, self.H, self.render_pts)
                if fit:
                    self.fit_score = fit[3]
                    if self.fit_method != "header" and fit[3] >= 0.90:
                        self.ox, self.oy, self.res, self.fit_method = fit[0], fit[1], fit[2], "auto"

        # DP overlay (walls / zones / carpets)
        self.dp_overlay = dm.load_dp_overlay(dps) if dps else None

        # ── Registration (orientation + origin) ──────────────────────────────────────────────
        # DEFAULT = the validated header-standard (col←x, row←y-inverted). It is invariant across the
        # whole corpus (3,726/3,726 single-map frames), so this is the deterministic fast path. ONLY if it
        # lands few path points on floor — a different home/firmware/re-oriented map we've never seen — do
        # we FIT orientation+origin by on-floor (decode_map.fit_registration, = upstream solve_calibration's
        # posture). So a deviating map auto-RECOVERS rather than rendering wrong; never silent.
        self.reg = None
        self.floor_frac = self.wall_frac = None
        self.floor_cells = 0
        self._floor = self._wall = None
        if self.grid is not None:
            self._floor = {(i % self.W, i // self.W) for i, b in enumerate(self.grid) if b and b % 4 == 0}
            self._wall = {(i % self.W, i // self.W) for i, b in enumerate(self.grid) if b == 249}
            self.floor_cells = len(self._floor)
            self.reg = Registration.header_standard(self.ox, self.oy, self.res, self.W, self.H)
            if self.path_pts:
                self.floor_frac, self.wall_frac = self._score(self.reg)
                # Adopt a fitted orientation ONLY on strong, DISCRIMINATING evidence — a short path slides
                # onto a floor blob in several orientations, so we require: standard clearly failing, a long
                # enough path, the winner ≥90%, beating the header-standard by ≥15 pts AND the runner-up
                # orientation by ≥10 pts. Else keep the standard and stay flagged (build/degenerate maps
                # don't get a spurious "recovery"). This is the unseen-home/firmware/re-oriented-map path.
                if self.floor_frac < 0.85 and len(self.path_pts) >= 40:
                    cands = dm.fit_registration(self.grid, self.W, self.H, self.path_pts)
                    if cands:
                        (bp, bs) = cands[0]
                        runner = cands[1][1] if len(cands) > 1 else 0.0
                        if bs >= 0.90 and bs > self.floor_frac + 0.15 and bs > runner + 0.10:
                            self.reg = Registration.from_fit(bp, self.W, self.H, bs)
                            self.floor_frac, self.wall_frac = self._score(self.reg)

        # Live robot pose + heading: use the LATEST frame only if its last point shares the grid's
        # epoch (lands in-bounds, not on the unmapped void). Otherwise fall back to the largest-frame
        # path end + its heading, and say so — never draw a current-pose arrow from a stale epoch.
        self.robot_xy = self.robot_heading = None
        self.robot_src = None
        if self.path_pts:
            self.robot_xy = self.path_pts[-1]
            self.robot_heading = self.path_heading
            self.robot_src = "path end (largest frame)"
            if self.late_pts:
                # Same epoch ⇔ the latest frame as a WHOLE registers on the grid. A single end-point
                # landing on floor is not enough (it can coincide; s26's stale epoch did exactly that).
                if self._floor:
                    hit = sum(1 for x, y in self.late_pts if self.true_pose_to_cell(x, y) in self._floor)
                    late_frac = hit / len(self.late_pts)
                else:
                    late_frac = 0
                if late_frac >= 0.80:
                    self.robot_xy = self.late_pts[-1]
                    self.robot_heading = self.late_heading
                    self.robot_src = "latest frame (live)"
                else:
                    self.robot_src = (f"path end — latest frame (epoch {self.late_epoch}) only "
                                      f"{late_frac*100:.0f}% on-grid, different map session")

    def _score(self, reg):
        """(floor_frac, wall_frac) of the largest-frame path under `reg`."""
        f = w = 0
        for x, y in self.path_pts:
            c = reg.to_cell(x, y)
            if c in self._floor:
                f += 1
            elif c in self._wall:
                w += 1
        n = len(self.path_pts)
        return f / n, w / n

    def true_pose_to_cell(self, x, y):
        """A TRUE (byte-14) pose point (x,y) → grid (col,row), via the chosen Registration (default =
        the canonical header-standard col←x/row←y-inverted = decode_map.path_to_pixel)."""
        return self.reg.to_cell(x, y) if self.reg else None

    def cell_path_bounds(self, col, row):
        """Grid cell (col,row) → its extent in TRUE path coords (x0,x1,y0,y1) — the exact inverse of
        true_pose_to_cell, so walls and the byte-14 path stay in ONE frame."""
        return self.reg.cell_bounds(col, row)


# ── style (a): exactly what decode_map produces ──────────────────────────────

def render_decode_style(scene, prefix):
    """Write <prefix>_rooms.png and <prefix>_overlay.png — identical to decode_map's output."""
    written = []
    if scene.grid is None:
        return written
    img = dm.render_grid_png(scene.grid, scene.W, scene.H, scene.rooms)
    rooms_path = f"{prefix}_rooms.png"
    img.save(rooms_path)
    written.append(rooms_path)
    if scene.render_pts:
        overlay = dm.render_overlay_png(
            scene.grid, scene.W, scene.H, scene.rooms, scene.render_pts,
            dp_overlay=scene.dp_overlay, ox=scene.ox, oy=scene.oy, res=scene.res)
        overlay_path = f"{prefix}_overlay.png"
        overlay.save(overlay_path)
        written.append(overlay_path)
    return written


# ── style (b): true-scale XY (path-unit) plot ────────────────────────────────

def _nice_step(span, target_ticks=8):
    """A readable axis tick step (1/2/5 × 10ⁿ) for `span` path-units over ~target ticks."""
    if span <= 0:
        return 1
    raw = span / target_ticks
    mag = 10 ** math.floor(math.log10(raw))
    for m in (1, 2, 5, 10):
        if raw <= m * mag:
            return int(m * mag) if m * mag >= 1 else m * mag
    return 10 * mag


def render_xy(scene, out_path, show_walls=True, show_rooms=False, samples=0,
              target_px=1200, margin=78):
    """True-scale XY plot in path-units. See module docstring for the full annotation list."""
    from PIL import Image, ImageDraw, ImageFont

    if scene.path_pts is None:
        raise ValueError("render_xy: no path/pose frames in capture — nothing to plot.")
    pts = scene.path_pts        # largest-frame byte-14 pose; registers universally (see MapScene)
    ox, oy, res = scene.ox, scene.oy, scene.res

    # Collect wall / floor cells in grid space (converted to path-units on draw).
    wall_cells, floor_cells = [], []
    if scene.grid is not None:
        for i, b in enumerate(scene.grid):
            if b == 249 and show_walls:
                wall_cells.append((i % scene.W, i // scene.W))
            elif show_rooms and b and b % 4 == 0:
                floor_cells.append((i % scene.W, i // scene.W, b // 4))

    # Bounds in path-units: path points + full grid extent + origin marker, all via the Registration
    # (so a fitted non-standard orientation places walls/origin consistently with the path).
    xs = [p[0] for p in pts]
    ys = [p[1] for p in pts]
    origin_xy = (oy, ox)
    if scene.reg is not None:
        ox0, ox1, oy0, oy1 = scene.reg.cell_bounds(0, 0)          # grid cell (0,0) world extent
        origin_xy = (ox0, oy1)                                    # its (col0,row0) corner
        gx0, gx1, gy0, gy1 = scene.reg.cell_bounds(scene.W - 1, scene.H - 1)
        xs += [ox0, ox1, gx0, gx1]                                # full grid extent (both far corners)
        ys += [oy0, oy1, gy0, gy1]
    xs.append(origin_xy[0]); ys.append(origin_xy[1])
    xmin, xmax, ymin, ymax = min(xs), max(xs), min(ys), max(ys)
    xr, yr = max(xmax - xmin, 1), max(ymax - ymin, 1)

    # Equal scale on both axes → true-scale. Fit the larger range to target_px.
    scale = (target_px - 2 * margin) / max(xr, yr)
    img_w = int(xr * scale + 2 * margin)
    img_h = int(yr * scale + 2 * margin)

    def T(x, y):
        return (margin + (x - xmin) * scale, margin + (ymax - y) * scale)  # flip y → up

    img = Image.new("RGB", (img_w, img_h), (255, 255, 255))
    draw = ImageDraw.Draw(img, "RGBA")
    # Try common regular/bold TrueType fonts across macOS / Linux / Windows; fall back to
    # Pillow's built-in bitmap font if none are present (labels still render, just lower quality).
    _FONTS = [
        ("/System/Library/Fonts/Supplemental/Arial.ttf", "/System/Library/Fonts/Supplemental/Arial Bold.ttf"),  # macOS
        ("/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf", "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf"),  # Linux
        ("DejaVuSans.ttf", "DejaVuSans-Bold.ttf"),  # Pillow-bundled / on PATH
        ("arial.ttf", "arialbd.ttf"),  # Windows
    ]
    font = fontb = None
    for _reg, _bold in _FONTS:
        try:
            font = ImageFont.truetype(_reg, 13)
            fontb = ImageFont.truetype(_bold, 14)
            break
        except OSError:
            continue
    if font is None:
        font = fontb = ImageFont.load_default()

    # Floor tint (optional) then walls — drawn as true-scale cell rects.
    for col, row, rid in floor_cells:
        x0, x1, y0, y1 = scene.cell_path_bounds(col, row)
        c = dm.ROOM_COLORS[(rid - 1) % len(dm.ROOM_COLORS)]
        draw.rectangle([T(x0, y1), T(x1, y0)], fill=(c[0], c[1], c[2], 70))
    for col, row in wall_cells:
        x0, x1, y0, y1 = scene.cell_path_bounds(col, row)
        draw.rectangle([T(x0, y1), T(x1, y0)], fill=(55, 55, 55, 255))

    # Axes box + ticks (labelled in path-units).
    box = [T(xmin, ymax), T(xmax, ymin)]
    draw.rectangle([box[0], box[1]], outline=(120, 120, 120), width=1)
    xstep = _nice_step(xr)
    ystep = _nice_step(yr)
    tx = math.ceil(xmin / xstep) * xstep
    while tx <= xmax:
        sx, sy = T(tx, ymin)
        draw.line([(sx, sy), (sx, sy + 6)], fill=(120, 120, 120), width=1)
        draw.text((sx, sy + 8), f"{int(tx)}", fill=(70, 70, 70), font=font, anchor="ma")
        tx += xstep
    ty = math.ceil(ymin / ystep) * ystep
    while ty <= ymax:
        sx, sy = T(xmin, ty)
        draw.line([(sx - 6, sy), (sx, sy)], fill=(120, 120, 120), width=1)
        draw.text((sx - 9, sy), f"{int(ty)}", fill=(70, 70, 70), font=font, anchor="rm")
        ty += ystep
    draw.text((img_w / 2, img_h - 18), "X  (path-units, ~2.5 mm)  →  +x",
              fill=(40, 40, 40), font=fontb, anchor="ma")
    draw.text((16, margin - 24), "Y ↑ (path-units)", fill=(40, 40, 40), font=fontb, anchor="lm")

    # Cleaning path polyline.
    poly = [T(x, y) for x, y in pts]
    if len(poly) >= 2:
        draw.line(poly, fill=(0, 100, 220, 220), width=2)

    # Map origin marker — grid cell (0,0) in true path coords.
    oxp, oyp = T(*origin_xy)
    draw.line([(oxp - 9, oyp), (oxp + 9, oyp)], fill=(150, 0, 150), width=2)
    draw.line([(oxp, oyp - 9), (oxp, oyp + 9)], fill=(150, 0, 150), width=2)
    # flip the label inward when the origin sits near a canvas edge so it never clips off
    o_side = "rm" if oxp > img_w * 0.7 else "lm"
    o_lx = oxp - 11 if o_side == "rm" else oxp + 11
    o_ly = min(max(oyp - 4, margin), img_h - margin)
    draw.text((o_lx, o_ly), f"origin ({int(origin_xy[0])},{int(origin_xy[1])})  [{scene.fit_method}]",
              fill=(150, 0, 150), font=font, anchor=o_side)

    # Optional labelled sample points along the path.
    if samples and len(pts) > 2:
        step = max(1, len(pts) // (samples + 1))
        for k in range(step, len(pts) - 1, step):
            x, y = pts[k]
            sx, sy = T(x, y)
            draw.ellipse([sx - 3, sy - 3, sx + 3, sy + 3], fill=(0, 100, 220))
            draw.text((sx + 5, sy - 5), f"({x},{y})", fill=(0, 70, 160), font=font, anchor="lm")

    # Dock (≈ path start) + robot (current pose — latest frame if same epoch, else path end).
    dx, dy = T(*pts[0])
    draw.ellipse([dx - 7, dy - 7, dx + 7, dy + 7], fill=(0, 190, 0), outline=(0, 0, 0))
    draw.text((dx + 10, dy), "dock≈start", fill=(0, 120, 0), font=font, anchor="lm")
    rxy = scene.robot_xy
    rx, ry = T(*rxy)
    draw.ellipse([rx - 7, ry - 7, rx + 7, ry + 7], fill=(220, 30, 30), outline=(0, 0, 0))

    # Heading arrow at the robot's current position (header heading; 0=+x, +90=+y).
    if scene.robot_heading is not None:
        th = math.radians(scene.robot_heading)
        arrow_pu = 0.10 * max(xr, yr)
        ex, ey = rxy[0] + arrow_pu * math.cos(th), rxy[1] + arrow_pu * math.sin(th)
        tipx, tipy = T(ex, ey)
        draw.line([(rx, ry), (tipx, tipy)], fill=(220, 30, 30), width=3)
        for da in (math.radians(150), math.radians(-150)):       # arrowhead
            hx = ex + 0.28 * arrow_pu * math.cos(th + da)
            hy = ey + 0.28 * arrow_pu * math.sin(th + da)
            draw.line([(tipx, tipy), T(hx, hy)], fill=(220, 30, 30), width=3)
        # flip the label inward near the right edge so it never clips off-canvas
        r_label = f"robot ({rxy[0]},{rxy[1]})  hdg {scene.robot_heading}°  [{scene.robot_src}]"
        r_side = "rm" if rx > img_w * 0.6 else "lm"
        draw.text((rx - 11 if r_side == "rm" else rx + 11, ry + 12), r_label,
                  fill=(170, 0, 0), font=fontb, anchor=r_side)

    # Title / provenance strip (incl. the on-floor self-check).
    chk = f"   path-on-floor:{scene.floor_frac*100:.1f}%" if scene.floor_frac is not None else ""
    reg_src = f"   reg:{scene.reg.source}" if scene.reg else ""
    title = (f"{scene.cap.split('/')[-1]}   path:{len(pts)}pts (byte-14 pose, largest frame)   "
             f"grid:{scene.W}×{scene.H}   res:{res} pu/px (~{round(res * 2.5)} mm/px)   "
             f"georef:{scene.fit_method}{reg_src}{chk}")
    draw.text((margin, 18), title, fill=(20, 20, 20), font=font, anchor="lm")

    img.save(out_path)
    return out_path


# ── CLI ──────────────────────────────────────────────────────────────────────

def main():
    argv = sys.argv[1:]
    if not argv or argv[0] in ("-h", "--help"):
        print(__doc__)
        return

    cap = None
    dps = None
    style = "both"
    prefix = "cap_render"
    show_rooms = False
    show_walls = True
    samples = 0
    i = 0
    while i < len(argv):
        a = argv[i]
        if a == "--dps" and i + 1 < len(argv):
            dps = argv[i + 1]; i += 2
        elif a == "--style" and i + 1 < len(argv):
            style = argv[i + 1]; i += 2
        elif a == "--out" and i + 1 < len(argv):
            prefix = argv[i + 1]; i += 2
        elif a == "--samples" and i + 1 < len(argv):
            samples = int(argv[i + 1]); i += 2
        elif a == "--rooms":
            show_rooms = True; i += 1
        elif a == "--no-walls":
            show_walls = False; i += 1
        elif cap is None:
            cap = a; i += 1
        else:
            i += 1
    if cap is None:
        sys.exit("usage: map_render.py <capture.jsonl> [--dps <raw.jsonl>] "
                 "[--style decode|xy|both] [--out <prefix>] [--rooms] [--no-walls] [--samples N]")
    if style not in ("decode", "xy", "both"):
        sys.exit(f"--style must be decode|xy|both, got {style!r}")
    for f in (cap, dps):
        if f is not None:
            try:
                open(f).close()
            except OSError as e:
                sys.exit(f"Cannot read {f}: {e}")

    scene = MapScene(cap, dps)
    print(f"path frames: {len(scene.paths)}   grid frames: {len(scene.grids)}   "
          f"georef: {scene.fit_method}"
          + (f" (auto-fit cross-check {scene.fit_score*100:.1f}% on floor)"
             if scene.fit_score is not None else ""))
    if scene.grid is not None:
        print(f"grid {scene.W}×{scene.H} (via {scene.dims_source}), {len(scene.rooms)} rooms, "
              f"origin ({scene.ox},{scene.oy}) res {scene.res}")
    if scene.reg is not None:
        print(f"registration: {scene.reg.source}")
    if scene.floor_frac is not None:
        warn = "  ⚠ LOW — build/multi-epoch capture, or an orientation the fit couldn't recover" if scene.floor_frac < 0.90 else ""
        print(f"path-on-floor self-check: {scene.floor_frac*100:.1f}% floor / "
              f"{scene.wall_frac*100:.1f}% wall ({scene.floor_cells} floor cells){warn}")
    if scene.robot_src is not None:
        print(f"robot pose: {scene.robot_src}")

    written = []
    if style in ("decode", "both"):
        written += render_decode_style(scene, prefix)
    if style in ("xy", "both"):
        if scene.path_pts is None:
            print("  (skipping xy: no path frames)")
        else:
            written.append(render_xy(scene, f"{prefix}_xy.png",
                                     show_walls=show_walls, show_rooms=show_rooms, samples=samples))
    for w in written:
        print(f"  wrote {w}")


if __name__ == "__main__":
    main()
