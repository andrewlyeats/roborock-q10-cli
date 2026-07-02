#!/usr/bin/env python3
"""Lost → remap → recover (thread e) — chains tonight's validated pieces into the recovery ACTIONS.

★ This is only the BOTTOM rung of the recovery ladder. When moved, the robot FIRST tries to
re-localize against the map it's still on (firmware global re-localization — scan + feature-match).
Three outcomes:
  (a) it re-localizes on the saved map → snaps back, carries on, NO 556, recover.py NOT needed (the
      common case for a modest move — "intervention: none");
  (b) it CAN'T re-localize → FAULT-556 → this script's rebuild→nav path takes over;
  (c) 556 but the rebuild can't re-find the (unmoved) dock → the DOCK WATCHDOG below aborts before nav
      → fall back to the manual app-relocalize.
recover.py only acts in (b); the watchdog catches (c).

When the robot is lost (FAULT-556 — `pose_extract.reloc_loss`: heading→0° + pose≈(0,0) at an epoch
boundary; watch it live with `pose_monitor.py`), the saved map no longer localizes the robot. The
user's "lidar-on-demand" recovery idea, now executable:
  1. build a FRESH map on the spot — `vac.py map-build` (cmd:4) re-localizes the robot in a new frame;
  2. navigate to the goal in that frame — `nav.py closed_loop` (heading-aware, frame-agnostic).
This script does steps 1–2 (needs a free map slot — cap 4).

KIDNAP TEST (the user, at the robot — the only part that can't be automated unattended):
  1. `./pose_monitor.py` (or watch `nav_log`) to see the live heading/pose;
  2. pick the robot up + set it down on OPEN FLOOR at the "sweet spot" — different/unrecognizable enough
     to DEFEAT re-localization (→ 556), but NOT so far/isolated the rebuild can't re-find the dock
     (e.g. an adjacent room that still opens onto the dock's area, big orientation change);
  3. `./recover.py <goal_x> <goal_y> --rel` ONLY if it lands in outcome (b) (556 / fresh map); if it
     re-localizes on its own (a), there's nothing to run.

Usage:  ./recover.py <goal_x> <goal_y> [--rel] [--margin U]    ⚠ MOVES the robot (map-build + nav)."""
import subprocess, os, time, sys, re
HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import nav


def vac(*a):
    return subprocess.run(["./vac.py", *a], cwd=HERE, capture_output=True, text=True)


def state():
    for ln in vac("status").stdout.splitlines():
        if "State" in ln:
            return ln.split(":", 1)[1].strip()
    return "?"


def map_slots_full():
    # Count map entries (each lists as "  [<id>] <name>"); match line-start brackets so a '[' in a map
    # name or the "Fetching maps…" header line can't inflate the count.
    lines = vac("multimap", "list").stdout.splitlines()
    return sum(1 for ln in lines if re.match(r"\s*\[", ln)) >= 4


def remap():
    """cmd:4 build → robot maps + re-localizes in a new frame; wait until it returns to the dock."""
    # map-build prints a FIXED success string even when slots are full (it silently won't save), so
    # guard on the actual slot count — NOT on map-build's stdout (the old "max"/"reached" check was dead).
    if map_slots_full():
        print("  ⚠ no free map slot (cap 4) — `vac.py multimap delete <id> --yes` first, then re-run.", flush=True)
        return None
    out = vac("map-build").stdout.strip()
    print("  " + out, flush=True)
    t0, saw_active, homed = time.time(), False, False
    while time.time() - t0 < 240:
        vac("raw", "--common", "HEARTBEAT", "1")
        time.sleep(8)
        st = state()
        if st not in ("charging", "idle", "?"):
            saw_active = True
        if saw_active and st in ("charging", "idle"):
            homed = True
            break
    if not homed:
        # DOCK WATCHDOG: the rebuild never returned to the dock => the robot likely couldn't
        # re-find its (unmoved) dock from the kidnap spot (outcome (c)). Do NOT proceed to nav
        # on a still-lost robot — bail to the manual fallback instead.
        print("  ⚠ rebuild did not return to the dock within the window — the robot may be too far from "
              "it to re-home. ABORTING before nav (won't drive a lost robot).\n"
              "    Fallback: load the saved map in the app + run a confined `./vac.py clean-rooms <room>` "
              "to re-localize, then dock.", flush=True)
        return None
    return state()


if __name__ == "__main__":
    import argparse
    ap = argparse.ArgumentParser(description="Lost→remap→recover. MOVES the robot (map-build + nav).")
    ap.add_argument("goal_x", type=int)
    ap.add_argument("goal_y", type=int)
    ap.add_argument("--rel", action="store_true", help="goal is an offset from the post-rebuild pose (safer)")
    ap.add_argument("--margin", type=int, default=30)
    a = ap.parse_args()

    print("RECOVERY 1/2: building a fresh map (cmd:4) to re-localize… (remap aborts if no free slot)", flush=True)
    end = remap()
    if end is None:
        sys.exit("recovery aborted (rebuild could not start).")
    print(f"  rebuild done; robot {end}.", flush=True)
    print(f"RECOVERY 2/2: navigating to goal ({a.goal_x},{a.goal_y}) rel={a.rel}…", flush=True)
    r = nav.closed_loop((a.goal_x, a.goal_y), log=print, rel=a.rel, margin=a.margin, dock=True)
    print("RECOVERY result:", r, flush=True)
