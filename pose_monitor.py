#!/usr/bin/env python3
"""Live-pose cockpit for the Roborock Q10 (B01).

Sustains the DP-110 `HEARTBEAT` so the robot streams its protocol-301 live map, and prints the robot's
live (x,y) from the `0201` path as it moves — **pose without a clean and without a camera rig** (the
2026-06-20 finding; see PROTOCOL). Drive with `./vac.py drive <dir>` in another shell and watch it move.

Requires a running daemon (it routes the heartbeat through the daemon's connection and reads the 301
replies from a fresh daemon `--bytes` tap it writes to the current directory).

Usage: ./pose_monitor.py [seconds]      (default 90)

Coords are the robot's global-map frame; ×2.5 mm/path-unit (±5%). `0201` points are at byte offset 14
(see pose_extract.py / parse_path notes). Prints only when the pose changes (stationary = silent)."""
import subprocess, time, json, base64, struct, sys, os, math

HERE = os.path.dirname(os.path.abspath(__file__))
TAP = os.path.join(os.getcwd(), "a capture")
DUR = int(sys.argv[1]) if len(sys.argv) > 1 else 90


def vac(*args):
    return subprocess.run(["./vac.py", *args], cwd=HERE, capture_output=True, text=True)


def parse_0201(raw):
    if raw[:2] != b"\x02\x01":
        return None
    count = struct.unpack(">H", raw[8:10])[0]
    body = raw[14:]
    pts = [struct.unpack(">hh", body[i * 4:i * 4 + 4]) for i in range(len(body) // 4)]
    return count, pts


def latest_pose():
    """Scan the tap for the most recent 0201 frame carrying at least one point."""
    if not os.path.exists(TAP):
        return None
    best = None
    for line in open(TAP):
        try:
            r = json.loads(line)
        except ValueError:
            continue
        if r.get("protocol_num") != 301 or not isinstance(r.get("payload"), str):
            continue
        p = parse_0201(base64.b64decode(r["payload"]))
        if p and p[1]:
            best = (r.get("time"), p[1][-1], p[0])     # (time, last point = robot, declared count)
    return best


def main():
    print(f"[*] rotating bytes tap -> {os.path.relpath(TAP, HERE)}")
    vac("daemon", "record", "--bytes", TAP)
    print(f"[*] LIVE-POSE COCKPIT — heartbeating DP-110, reading 0201 for {DUR}s.")
    print(f"[*] Drive in another shell:  ./vac.py drive forward   (then watch the robot move below)\n")
    print(f"    {'time':>8}   {'robot (x,y) mm':>20}   {'pts':>4}   {'step mm':>8}")
    t0 = time.time()
    last = None
    while time.time() - t0 < DUR:
        vac("raw", "--common", "HEARTBEAT", "1")
        lp = latest_pose()
        if lp:
            t, (x, y), c = lp
            if last is None or (x, y) != last:
                step = f"{math.hypot(x - last[0], y - last[1]) * 2.5:.0f}" if last else "—"
                print(f"    {t[-8:]:>8}   ({x * 2.5:8.0f},{y * 2.5:8.0f})   {c:>4}   {step:>8}", flush=True)
                last = (x, y)
        time.sleep(4)
    print("\n[*] done. (Heartbeats stopped; the robot's live stream lapses ~seconds later.)")


if __name__ == "__main__":
    main()
