#!/usr/bin/env python3
"""scan.py — on-demand lidar snapshot for the Roborock Q10 (B01).

Heartbeats the robot (DP-110) to trigger its live protocol-301 stream, captures a few seconds, and
decodes the raw 0101 occupancy grid to a PNG via decode_map — the robot's CURRENT sensed surroundings,
with NO cloud get_map and NO clean. This is the LIVE stream, distinct from `vac.py map` (which returns
the saved/processed map). MOVES NOTHING — only heartbeats + reads, so it is safe to run anytime.

Proven 2026-06-21: decode_map renders the raw heartbeat-stream grid (study, 77x58) at 100% georef —
i.e. the live grid is fully decodable on demand, the cloud fetch is not required for a snapshot.

Usage:      ./scan.py [--secs 10] [--name study]
              -> ./<name>_rooms.png (+ _overlay.png if a path frame is present)
Importable: from scan import scan; scan(secs=10, name="study")
"""
import subprocess, time, os, sys, argparse, shutil

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
from nav import vac, hb                 # reuse the proven capture helpers (vac() shells ./vac.py; hb() = DP-110)
PY = sys.executable


def scan(secs=10, name="scan", tap=None):
    """Capture a live grid snapshot and render it. Returns {png_name: path, ...} or None."""
    od = os.getcwd()
    tap = tap or os.path.join(od, "a capture")
    open(tap, "w").close()                                  # fresh tap (no stale frames)
    vac("daemon", "record", "--bytes", tap); time.sleep(2)  # start the background 301 capture
    for _ in range(max(3, secs // 2)):                      # heartbeat to trigger + sustain the stream
        hb(); time.sleep(2)
    vac("daemon", "record", "--off")                        # stop the byte tap — capture done, don't leave it streaming (P4-A)
    # Decode via the proven decode_map CLI (handles largest-frame pick, header dims, georef, render).
    r = subprocess.run([PY, os.path.join(HERE, "decode_map.py"), tap], cwd=od, capture_output=True, text=True)
    sys.stdout.write(r.stdout)
    if r.returncode != 0:
        sys.stderr.write(r.stderr or "scan: decode failed\n")
        return None
    out = {}
    for src, dst in (("map_rooms.png", f"{name}_rooms.png"), ("map_overlay.png", f"{name}_overlay.png")):
        s = os.path.join(od, src)
        if os.path.exists(s):
            d = os.path.join(od, dst); shutil.move(s, d); out[dst] = d
    print(f"scan: wrote {', '.join(out) if out else '(no png — no grid frame captured?)'}")
    return out or None


if __name__ == "__main__":
    ap = argparse.ArgumentParser(description="On-demand lidar snapshot (live 0101 grid -> PNG). Heartbeats the robot; moves nothing.")
    ap.add_argument("--secs", type=int, default=10, help="seconds of stream to capture (default 10)")
    ap.add_argument("--name", default="scan", help="output basename written to the current directory (default 'scan')")
    a = ap.parse_args()
    sys.exit(0 if scan(a.secs, a.name) else 1)
