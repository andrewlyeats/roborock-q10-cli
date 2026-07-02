#!/usr/bin/env python3
"""Heading-aware navigation for the Roborock Q10 (B01) — both nav modes as options (CAPABILITIES #15).

Enabled by the 2026-06-20 finding that the 0201 frame carries a live SLAM heading (b[10:12], i16°).
Unlike goto1.py (which assumed the dock at origin facing -x — INVALID on the whole-apartment map),
nav.py is FRAME-AGNOSTIC: it reads the actual live pose AND heading and steers by
bearing-to-target. Two user-selectable modes:

  --mode closed  (default): closed-loop. Each step: read live pose+heading → if not aimed at the
                  target, spin toward the bearing (using the live heading to know when aligned) →
                  else drive forward. Repeat until within margin. Aborts on a FAULT-556 reloc-loss.
  --mode dead   : dead-reckoning (open-loop). Read ONE start pose+heading, compute the whole nudge
                  plan from the motion model (turn to bearing, then forward), fire it BLIND (no
                  mid-course feedback), then read the final pose only to REPORT error. Works even if
                  live pose is unavailable; shows the open-loop model error (~14% per the motion model).

Heading/turn sign convention (verified offline, pose_turn1/dr1): LEFT nudge = +Δheading (CCW),
RIGHT = -Δheading (CW); fwd ~120 mm (~48 path-units) / nudge; turn ~21.8°/nudge; ~2.5 mm/unit.

CLI:  ./nav.py <x> <y> [--mode closed|dead] [--margin UNITS] [--no-dock]
Importable:  from nav import plan_dead_reckon, closed_loop, dead_reckon
The planner plan_dead_reckon() is pure (no robot) and unit-tested in check_nav_planner.py."""
import subprocess, time, os, sys, math, random

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import pose_extract

TAP = os.path.join(os.getcwd(), "a capture")
MM_PER_UNIT = 2.5
FWD_MM_PER_NUDGE = 120.0
DEG_PER_NUDGE = 21.8
STUCK_EPS = 15        # path-units (~38 mm): a real fwd nudge advances ~48u, so < this = no progress
STUCK_N = 4           # this many consecutive no-progress reads despite nudging ⇒ physically blocked


def vac(*a):
    return subprocess.run(["./vac.py", *a], cwd=HERE, capture_output=True, text=True)


def hb():
    vac("raw", "--common", "HEARTBEAT", "1")


def angle_norm(d):
    """Normalize degrees to (-180, 180]."""
    return (d + 180) % 360 - 180


def latest(tap=TAP):
    """-> ((x,y), heading, epoch, time) of the most recent 0201 frame with points, or (None,..)."""
    frames = pose_extract.pose_frames(tap)
    for t, count, pts, heading, epoch in reversed(frames):
        if pts:
            return pts[-1], heading, epoch, t
    return None, None, None, None


def fresh(prev_t, tap=TAP, tries=6):
    """Heartbeat until a NEW 0201 frame (time != prev_t) appears."""
    for _ in range(tries):
        hb()
        time.sleep(3)
        p, h, ep, t = latest(tap)
        if p and t != prev_t:
            return p, h, ep, t
    return latest(tap)


# ── pure planner (unit-tested offline) ───────────────────────────────────────────

def plan_dead_reckon(start, start_heading, target):
    """Pure: from start pose (x,y) + heading° + target (x,y), return the open-loop nudge plan.
    Turn to the target bearing (LEFT if we must increase heading / CCW, else RIGHT), then drive
    forward the straight-line distance. No robot I/O."""
    sx, sy = start
    tx, ty = target
    dx, dy = tx - sx, ty - sy
    bearing = math.degrees(math.atan2(dy, dx))
    turn = angle_norm(bearing - start_heading)        # +ve => left/CCW, -ve => right/CW
    dist_units = math.hypot(dx, dy)
    dist_mm = dist_units * MM_PER_UNIT
    return {
        "bearing": round(bearing, 1),
        "turn_deg": round(turn, 1),
        "turn_dir": "left" if turn > 0 else "right",
        "turn_nudges": int(round(abs(turn) / DEG_PER_NUDGE)),
        "fwd_nudges": int(round(dist_mm / FWD_MM_PER_NUDGE)),
        "dist_mm": round(dist_mm),
    }


# ── live controllers ─────────────────────────────────────────────────────────────

def _err_mm(p, target):
    return math.hypot(p[0] - target[0], p[1] - target[1]) * MM_PER_UNIT


def dead_reckon(target, log=print, tap=TAP, dock=True, rel=False):
    """Open-loop: plan from one start read, fire blind, report final error.
    rel=True: `target` is a (dx,dy) OFFSET from the start pose (safe for the confined study)."""
    open(tap, "w").close()                # fresh tap — never anchor on a stale prior-run frame (P2-A)
    vac("daemon", "record", "--bytes", tap); time.sleep(2)
    vac("drive", "stop"); time.sleep(2)
    p, h, ep, t = fresh(None, tap)
    if not p:
        # establish a pose by nudging once off the dock, then read
        vac("drive", "forward"); p, h, ep, t = fresh(t, tap)
    if not p:
        log("[dead] no pose — cannot plan"); return {"mode": "dead", "error_mm": None}
    if rel:
        target = (p[0] + target[0], p[1] + target[1])
        log(f"[dead] rel target resolved to {target} from start {p}")
    plan = plan_dead_reckon(p, h, target)
    log(f"[dead] start={p} head={h}° target={target} plan={plan}")
    for _ in range(plan["turn_nudges"]):
        vac("drive", plan["turn_dir"]); hb(); time.sleep(1.0 + random.random())
    for _ in range(plan["fwd_nudges"]):
        vac("drive", "forward"); hb(); time.sleep(0.6 + random.random())
    vac("drive", "exit")
    if plan["fwd_nudges"] == 0:
        p2, h2 = p, h        # no forward leg → no new 0201 frame would arrive; a read would just wait ~18s then return stale
        log("[dead] no forward leg (target≈start) — start pose is the result")
    else:
        p2, h2, ep2, t2 = fresh(t, tap)
    err = _err_mm(p2, target) if p2 else None
    log(f"[dead] final={p2} head={h2}° error={err:.0f}mm" if err is not None else "[dead] final: no pose")
    if dock:
        vac("dock")
    return {"mode": "dead", "final": p2, "error_mm": round(err) if err is not None else None, "plan": plan}


def closed_loop(target, log=print, tap=TAP, margin=30, maxit=24, dock=True, rel=False):
    """Closed-loop: read pose+heading each step; spin toward the bearing, then drive; repeat.
    rel=True: `target` is a (dx,dy) OFFSET from the start pose (safe for the confined study)."""
    open(tap, "w").close()                # fresh tap — never anchor on a stale prior-run frame (P2-A)
    vac("daemon", "record", "--bytes", tap); time.sleep(2)
    vac("drive", "stop"); time.sleep(2)
    p, h, ep, t = fresh(None, tap)
    if rel:
        if not p:
            vac("drive", "forward"); p, h, ep, t = fresh(t, tap)
        if p:
            target = (p[0] + target[0], p[1] + target[1])
            log(f"[closed] rel target resolved to {target} from start {p}")
    tx, ty = target
    log(f"[closed] start={p} head={h}° target={target} margin={margin}u(~{margin*MM_PER_UNIT:.0f}mm)")
    abort_reason = None; prev_p = None; stuck = 0; no_pose = 0
    for it in range(maxit):
        p, h, ep, t = fresh(t, tap)
        if p is None:
            no_pose += 1                       # P2-B: a sustained no-pose run = lost / offline / blocked-without-telemetry
            if no_pose >= 6:
                log(f"[closed] ⚠ no pose for {no_pose} reads — ABORT (no telemetry; offline/lost/blocked)")
                abort_reason = "no-signal"; break
            vac("drive", "forward"); continue
        no_pose = 0
        if pose_extract.reloc_loss(h, p):
            log(f"[closed] ⚠ RELOC-LOSS (heading→0 @ origin) at {p} — ABORT"); abort_reason = "reloc-loss"; break
        if prev_p is not None and math.hypot(p[0] - prev_p[0], p[1] - prev_p[1]) < STUCK_EPS:
            stuck += 1
            if stuck >= STUCK_N:
                log(f"[closed] ⚠ STUCK — pose ~unchanged at {p} over {stuck} reads despite nudging (wall/blocked?) — ABORT"); abort_reason = "stuck"; break
        else:
            stuck = 0
        prev_p = p
        dx, dy = tx - p[0], ty - p[1]
        dist = math.hypot(dx, dy)
        if dist <= margin:
            log(f"[closed] within margin at it={it}: {p} ({dist*MM_PER_UNIT:.0f}mm)"); break
        bearing = math.degrees(math.atan2(dy, dx))
        err = angle_norm(bearing - h) if h is not None else 0
        turned = 0
        if abs(err) > 22:                                   # steer toward the bearing (open turns)
            turn = "left" if err > 0 else "right"
            turned = min(3, max(1, int(round(abs(err) / DEG_PER_NUDGE))))
            for _ in range(turned):
                vac("drive", turn); time.sleep(0.8)
        # ALWAYS advance one forward nudge afterwards. CRITICAL: in-place turns emit NO new 0201
        # frame (frames are ~50mm-distance-triggered), so without a translation the pose+heading
        # never refresh and the loop spins forever. The forward step is what produces feedback.
        vac("drive", "forward"); hb()
        steer = (f"{turned}x{'left' if err > 0 else 'right'}+" if turned else "")
        log(f"[closed] it={it} {p} head={h}° bearing={bearing:.0f}° err={err:.0f}° -> {steer}fwd")
    vac("drive", "exit")
    p2, h2, ep2, t2 = fresh(t, tap)
    err = _err_mm(p2, target) if p2 else None
    log(f"[closed] FINAL={p2} head={h2}° error={err:.0f}mm" if err is not None else "[closed] FINAL: no pose")
    if dock:
        vac("dock")
    return {"mode": "closed", "final": p2, "error_mm": round(err) if err is not None else None,
            "aborted": abort_reason is not None, "reason": abort_reason}


def parse_waypoints(s):
    """Parse a --patrol string "x1,y1 x2,y2 ..." into [(x,y), ...]. Raises ValueError on a malformed
    leg (each must be exactly two integers) so a typo like "100 0" (space, not comma) fails clearly
    instead of producing a 1-tuple that crashes the controller on unpack. Pure — unit-tested."""
    wps = []
    for leg in s.split():
        parts = leg.split(",")
        if len(parts) != 2:
            raise ValueError(f"bad waypoint {leg!r}: expected 'x,y' (two ints, comma-separated)")
        try:
            wps.append((int(parts[0]), int(parts[1])))
        except ValueError:
            raise ValueError(f"bad waypoint {leg!r}: x and y must be integers")
    if not wps:
        raise ValueError("no waypoints given")
    return wps


def patrol(waypoints, log=print, tap=TAP, margin=30, rel=False, dock=True):
    """Multi-waypoint go-to: closed-loop nav through `waypoints` in order, then dock once at the end.
    rel=True chains them — each leg's (dx,dy) is an offset from the pose reached at the END of the
    previous leg (a safe, bounded tour for the confined study; e.g. a square is
    "120,0 0,120 -120,0 0,-120"). Stops early if a leg loses localisation (FAULT-556) rather than
    driving on blind. Returns per-leg results + the mean landing error."""
    legs = []
    for i, wp in enumerate(waypoints):
        log(f"[patrol] === leg {i+1}/{len(waypoints)} -> {wp} (rel={rel}, no dock between) ===")
        r = closed_loop(wp, log=log, tap=tap, margin=margin, dock=False, rel=rel)
        legs.append(r)
        if r and r.get("aborted"):
            log(f"[patrol] ⚠ leg aborted ({r.get('reason')}) — stopping the tour (recover/redock before continuing)"); break
        time.sleep(random.uniform(0, 3))                 # jitter between legs (rate-limit hygiene)
    if dock:
        vac("dock")
    errs = [l["error_mm"] for l in legs if l and l.get("error_mm") is not None]
    out = {"mode": "patrol", "legs": legs, "n": len(legs), "errors_mm": errs,
           "mean_err_mm": round(sum(errs) / len(errs)) if errs else None}
    log(f"[patrol] DONE — {len(legs)} legs, errors={errs}mm mean={out['mean_err_mm']}mm")
    return out


if __name__ == "__main__":
    import argparse
    ap = argparse.ArgumentParser(description="Heading-aware go-to for the Q10 (B01). MOVES the robot.")
    ap.add_argument("x", type=int, nargs="?"); ap.add_argument("y", type=int, nargs="?")
    ap.add_argument("--mode", choices=["closed", "dead"], default="closed")
    ap.add_argument("--margin", type=int, default=30)
    ap.add_argument("--no-dock", action="store_true")
    ap.add_argument("--rel", action="store_true", help="x y (or each --patrol leg) is an OFFSET from the current pose (safer for the confined study)")
    ap.add_argument("--patrol", default=None, help='multi-waypoint tour: "x1,y1 x2,y2 ..." — closed-loop each leg, dock at end. With --rel each leg chains off the previous pose.')
    ap.add_argument("--tap", default=None, help="capture filename written to the current directory — use a fresh one per run to avoid stale-frame anchors")
    a = ap.parse_args()
    logf = os.path.join(os.getcwd(), "nav_log.txt")
    def _log(m):
        print(m, flush=True)
        open(logf, "a").write(m + "\n")
    tp = None
    if a.tap:
        tp = os.path.join(os.getcwd(), a.tap)
        open(tp, "w").close()          # fresh/empty → the start read can't be a stale prior-run frame
    if a.patrol:
        try:
            wps = parse_waypoints(a.patrol)
        except ValueError as e:
            ap.error(str(e))
        _log(f"=== nav patrol ({len(wps)} legs, rel={a.rel}) -> {wps} ===")
        kw = {"margin": a.margin, "rel": a.rel, "dock": not a.no_dock}
        if tp: kw["tap"] = tp
        r = patrol(wps, _log, **kw)
    elif a.x is not None and a.y is not None:
        _log(f"=== nav {a.mode} -> ({a.x},{a.y}) ===")
        fn = closed_loop if a.mode == "closed" else dead_reckon
        kw = {"margin": a.margin} if a.mode == "closed" else {}
        if tp: kw["tap"] = tp
        r = fn((a.x, a.y), _log, dock=not a.no_dock, rel=a.rel, **kw)
    else:
        ap.error('give either  x y  or  --patrol "x1,y1 x2,y2 ..."')
    _log(f"RESULT: {r}")
