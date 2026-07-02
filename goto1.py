#!/usr/bin/env python3
"""Closed-loop GO-TO for the Roborock Q10 (B01) using live DP-110 heartbeat-pose feedback — the
"go-to capstone" enabled by the 2026-06-20 live-pose finding.

run_goto(target) drives the robot (started docked, facing -x) to a target (x,y) in its map frame via
"Manhattan + per-axis feedback":
  Phase 1 — close the X gap: forward nudges (heading -x → x decreases), read pose, repeat until x≈Tx.
  Phase 2 — turn ~90° toward the target's y side: LEFT (→ -y) if Ty<y, else RIGHT (→ +y). (open-loop)
  Phase 3 — close the Y gap: forward nudges, read pose, repeat until y≈Ty.
Per-axis feedback ⇒ no fragile continuous heading estimate. Bounded (maxit/phase) + logged.
Reach is the -x, ±y region from the dock (targets must be -x of the dock; pick a real y offset).

Importable: `from goto1 import run_goto, vac`. Standalone: runs one default target."""
import subprocess, time, json, base64, struct, os, math

HERE = os.path.dirname(os.path.abspath(__file__))
TAP = os.path.join(os.getcwd(), "a capture")


def vac(*a):
    return subprocess.run(["./vac.py", *a], cwd=HERE, capture_output=True, text=True)


def hb():
    vac("raw", "--common", "HEARTBEAT", "1")


def latest_pose(tap=TAP):
    if not os.path.exists(tap):
        return None, None
    best = bt = None
    for line in open(tap):
        try:
            r = json.loads(line)
        except ValueError:
            continue
        if r.get("protocol_num") != 301 or not isinstance(r.get("payload"), str):
            continue
        raw = base64.b64decode(r["payload"])
        if raw[:2] != b"\x02\x01":
            continue
        body = raw[14:]
        n = len(body) // 4
        if n:
            best = struct.unpack(">hh", body[(n - 1) * 4:n * 4])
            bt = r.get("time")
    return best, bt


def fresh_pose(prev_t, tap=TAP, tries=6):
    for _ in range(tries):
        hb()
        time.sleep(3)
        p, t = latest_pose(tap)
        if p and t != prev_t:
            return p, t
    return latest_pose(tap)


def run_goto(target, tag="goto", log=print, tap=TAP, margin=30, maxit=8):
    """Drive to target=(x,y). Returns {target, final, error_mm, post_p1, turn}. Robot ends with drive exit."""
    tx, ty = target
    log(f"[{tag}] GO-TO target={target} margin={margin}u(~{margin*2.5:.0f}mm)")
    vac("drive", "stop"); time.sleep(2)
    p, t = fresh_pose(None, tap)
    log(f"[{tag}] start={p}" + ("" if p else " (none yet — Phase 1 establishes it by moving off the dock)"))

    for it in range(maxit):                                   # Phase 1: close X (forward, heading -x)
        p, t = fresh_pose(t, tap)
        if not p:
            vac("drive", "forward"); continue
        if p[0] <= tx + margin:
            break
        vac("drive", "forward")
    log(f"[{tag}] post-P1={p}")

    turn = "left" if ty < (p[1] if p else ty) else "right"    # Phase 2: turn toward target's y side
    log(f"[{tag}] turn {turn} x4 (left→-y, right→+y)")
    for _ in range(4):
        vac("drive", turn); hb(); time.sleep(1.2)
    vac("drive", "forward")                                    # probe into the new heading
    p, t = fresh_pose(t, tap)
    log(f"[{tag}] post-turn={p}")
    facing_neg_y = (turn == "left")

    for it in range(maxit):                                   # Phase 3: close Y
        p, t = fresh_pose(t, tap)
        if not p:
            vac("drive", "forward"); continue
        if facing_neg_y and p[1] <= ty + margin:
            break
        if (not facing_neg_y) and p[1] >= ty - margin:
            break
        vac("drive", "forward")

    vac("drive", "exit")
    p, t = fresh_pose(t, tap)
    err = math.hypot(p[0] - tx, p[1] - ty) * 2.5 if p else None
    log(f"[{tag}] FINAL={p} target={target} error={err:.0f}mm" if err else f"[{tag}] FINAL: no pose")
    return {"target": target, "final": p, "error_mm": round(err) if err is not None else None, "turn": turn}


if __name__ == "__main__":
    import sys
    if len(sys.argv) < 3:
        sys.exit("usage: ./goto1.py <x> <y> [margin_units]\n"
                 "  Drives the robot to (x,y) in its map frame (path-units, ~2.5 mm/unit) via live-pose feedback.\n"
                 "  e.g. ./goto1.py -280 350    (reachable region: -x of the dock, ±y; default margin 30u≈75mm)\n"
                 "  ⚠ MOVES the robot from its dock (Manhattan + per-axis feedback); watch it. Re-docks when done.")
    tx, ty = int(sys.argv[1]), int(sys.argv[2])
    margin = int(sys.argv[3]) if len(sys.argv) > 3 else 30
    open(os.path.join(os.getcwd(), "goto1_log.txt"), "w").close()
    def _log(m):
        print(m, flush=True)
        open(os.path.join(os.getcwd(), "goto1_log.txt"), "a").write(m + "\n")
    vac("daemon", "record", "--bytes", TAP); time.sleep(2)
    r = run_goto((tx, ty), f"goto({tx},{ty})", _log, margin=margin)
    _log(f"RESULT: {r}")
    vac("dock")
