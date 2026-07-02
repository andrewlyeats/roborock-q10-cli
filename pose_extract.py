#!/usr/bin/env python3
"""Extract live teleop pose + heading from a daemon `--bytes` capture's protocol-301 `0201` frames.

0201 header — fully decoded + verified vs 4 captures (2026-06-20; see PROTOCOL):
  b[0:2]=0201 · b[2:4]=path-epoch counter (u16 BE; resets on power-cycle, ++ per new traversal) ·
  b[4:8]=const 00020000 · b[8:10]=point count (u16 BE) · b[10:12]=HEADING in degrees (i16 BE;
  0=+x, +90=+y, ±180=-x, -90=-y) · b[12:14]=const 0000 · b[14:]=(x,y) i16-BE pairs.
Pose points start at OFFSET 14 (decode_map.parse_path reads 16 — a render-only shear the clean x↔y
swap cancels; raw pose needs 14). Heading is the SLAM yaw — the "missing heading DP" we thought had
to be inferred from path bends; it's a header field. A localization loss (FAULT 556) shows as
epoch++ with the first pose ≈(0,0) AND heading reset to 0° (verified vs s27's two live 556 events).

Usage: ./pose_extract.py <a capture>
Prints each 0201 frame's epoch, count, heading, last point (= robot's live position), and the step
from the previous frame's last point (displacement between samples)."""
import json, base64, sys, struct, math


def pose_frames(path):
    """-> list of (time, count, pts, heading_deg, epoch). pts = [(x,y), ...] in path-units."""
    out = []
    for line in open(path):
        try:
            r = json.loads(line)
            if r.get("protocol_num") != 301:
                continue
            pay = r.get("payload")
            if not isinstance(pay, str):
                continue
            raw = base64.b64decode(pay)
            if raw[:2].hex() != "0201" or len(raw) < 14:   # need the full 14-byte header before the points
                continue
            epoch = struct.unpack(">H", raw[2:4])[0]
            count = struct.unpack(">H", raw[8:10])[0]
            heading = struct.unpack(">h", raw[10:12])[0]
            body = raw[14:]
            n = len(body) // 4
            pts = [struct.unpack(">hh", body[i * 4:i * 4 + 4]) for i in range(n)]
            out.append((r.get("time"), count, pts, heading, epoch))
        except (struct.error, ValueError):     # partial/truncated/garbled line (incl. JSON + base64 errors) → skip, don't crash the nav loop
            continue
    return out


def reloc_loss(heading, last):
    """The FAULT-556 signature in a frame: heading reset to 0° AND pose snapped near origin.
    Validated SPECIFIC (2026-06-20): a normal relocalization/epoch-change keeps a real heading+pose
    (e.g. the in-situ build's relocating phase: −173°, (84,−1)), so it does NOT trigger this — only a
    true localization loss falls back to the local origin frame. Epoch++ alone is therefore NOT a loss.

    ⚠ LIMITATION (review P2-E, 2026-06-21): this checks heading→0 + pose≈origin on ANY frame, so it would
    FALSE-TRIGGER if the robot genuinely navigated to ≈the map origin (0,0) facing +x — a real risk only on
    MULTI-ROOM nav (in the confined study the robot is far from origin). Epoch can't gate it: epoch ++s per
    traversal during a NORMAL nav (verified 117→120 across one patrol), not just on a 556. A robust fix needs
    the discontinuity signature — the FIRST frame of a NEW epoch snapping to origin (a 556 jumps to origin; a
    normal new traversal starts at the real pose) — best validated against a real 556 capture (gated kidnap)."""
    return heading == 0 and last is not None and abs(last[0]) < 60 and abs(last[1]) < 60


if __name__ == "__main__":
    if len(sys.argv) < 2:
        sys.exit("usage: ./pose_extract.py <a capture>")
    frames = pose_frames(sys.argv[1])
    print(f"# {len(frames)} x 0201 path frames")
    prev = None
    for t, count, pts, heading, epoch in frames:
        last = pts[-1] if pts else None
        d = ""
        if last and prev:
            dx, dy = last[0] - prev[0], last[1] - prev[1]
            d = f"  Δ=({dx:+d},{dy:+d}) dist={math.hypot(dx, dy):.0f}"
        lost = "  ⚠RELOC-LOSS(556)" if reloc_loss(heading, last) else ""
        print(f"{t}  ep={epoch} count={count} npts={len(pts)} head={heading:>4}°  last(robot)={last}{d}{lost}")
        if last:
            prev = last
    if frames:
        # densest frame = the fullest trajectory snapshot
        dense = max(frames, key=lambda f: len(f[2]))
        print(f"\n# densest frame {dense[0]} ({len(dense[2])} pts, head={dense[3]}°):")
        print("  " + " ".join(f"({x},{y})" for x, y in dense[2]))
