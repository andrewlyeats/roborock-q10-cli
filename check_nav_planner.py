#!/usr/bin/env python3
"""Pure offline unit tests for nav's pure functions — plan_dead_reckon + parse_waypoints
(NO robot — safe to run anytime). Validates the dead-reckon planner's turn-direction sign + nudge
math against the verified kinematics (LEFT=+Δheading/CCW, RIGHT=-Δheading/CW; ~21.8°/nudge;
~120mm/nudge; 2.5mm/unit), plus the --patrol waypoint parser's malformed-input rejection."""
import sys, os
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from nav import plan_dead_reckon, angle_norm, parse_waypoints

ok = True


def approx(a, b, tol=1.0):
    return abs(a - b) <= tol


def check(name, cond):
    global ok
    ok = ok and bool(cond)
    print(("PASS" if cond else "FAIL"), name)


# 1. facing -x (180°), target straight -x → no turn, forward only
p = plan_dead_reckon((0, 0), 180, (-100, 0))
check("straight -x: ~0° turn", abs(p["turn_deg"]) <= 1)
check("straight -x: fwd nudges>0", p["fwd_nudges"] > 0)
check("straight -x: dist 250mm (100u*2.5)", approx(p["dist_mm"], 250, 2))

# 2. facing -x (180°), target -y (0,-100) → LEFT ~90° (CCW: 180→-90)
p = plan_dead_reckon((0, 0), 180, (0, -100))
check("to -y: bearing -90°", approx(p["bearing"], -90))
check("to -y: turn LEFT", p["turn_dir"] == "left")
check("to -y: ~90°", approx(abs(p["turn_deg"]), 90))
check("to -y: ~4 nudges", p["turn_nudges"] == 4)

# 3. facing -x (180°), target +y (0,100) → RIGHT ~90° (CW: 180→90)
p = plan_dead_reckon((0, 0), 180, (0, 100))
check("to +y: bearing 90°", approx(p["bearing"], 90))
check("to +y: turn RIGHT", p["turn_dir"] == "right")
check("to +y: ~4 nudges", p["turn_nudges"] == 4)

# 4. facing +x (0°), target +x → no turn
p = plan_dead_reckon((0, 0), 0, (100, 0))
check("facing+x to +x: ~0° turn", abs(p["turn_deg"]) <= 1)

# 5. angle_norm wrap-around
check("angle_norm(270)=-90", angle_norm(270) == -90)
check("angle_norm(-270)=90", angle_norm(-270) == 90)
check("angle_norm(181)=-179", angle_norm(181) == -179)

# 6. real apartment frame: dock (-1020,-1437) facing -76°, target +y → bearing 90°, big left turn
p = plan_dead_reckon((-1020, -1437), -76, (-1020, -1000))
check("apt frame +y: bearing 90°", approx(p["bearing"], 90))
check("apt frame +y: turn left (CCW from -76 to 90)", p["turn_dir"] == "left")
check("apt frame +y: ~166° turn", approx(abs(p["turn_deg"]), 166))

# 7. parse_waypoints — valid parses + malformed-input rejection (review P2: the parser was unvalidated)
check("parse 2 legs", parse_waypoints("100,0 -100,0") == [(100, 0), (-100, 0)])
check("parse negatives", parse_waypoints("-140,-140") == [(-140, -140)])
def _raises(s):
    try:
        parse_waypoints(s); return False
    except ValueError:
        return True
check("space-typo '100 0' raises (not a silent 1-tuple)", _raises("100 0"))
check("3-coord '1,2,3' raises", _raises("1,2,3"))
check("non-int 'a,b' raises", _raises("a,b"))
check("empty string raises", _raises(""))

print("\n" + ("ALL PASS ✅" if ok else "SOME FAILED ❌"))
sys.exit(0 if ok else 1)
