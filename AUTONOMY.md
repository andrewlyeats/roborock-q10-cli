# Autonomy layer — Roborock Q10 (B01)

> ⚠️ **EXPERIMENTAL** — the autonomy layer (nav/scan/recover) is newer and less battle-tested than the core CLI; interfaces may change.

*Standalone tooling built **on top of** the cloud-MQTT comms in `vac.py` — go-to, on-demand
lidar/mapping, and lost→remap→recover. Deliberately kept **out of** `vac.py` (which stays a thin
controller for the robot's native features); a candidate for extraction into its own sister project.*

> **⚠ Moves the robot — no AI/laser obstacle avoidance.** `nav.py` / `recover.py` drive via `REMOTE`,
> steering by live pose + dead-reckoning with no path-planning — they bypass the app's laser/AI
> avoidance and only abort *after* they get stuck. We have **not** verified which hardware failsafes
> (bumper / cliff sensors) stay active under `REMOTE`, so **supervise every run, clear the area first,
> and never run it near stairs or drop-offs.**

## Why this is possible (the two enabling findings)

- **DP-110 `HEARTBEAT` → live stream, no rig.** Any client that sends `COMMON(101){"110":1}` gets the
  robot's live protocol-301 stream — the `0101` occupancy grid **and** the `0201` path frame (which
  carries **live pose + SLAM heading**, decoded by `pose_extract.py`) — even while docked/idle, outside
  a clean. This is what makes real-time goto and on-demand lidar possible without the app.
- **String-key COMMON write surface** `{str(dp.code): value}` — drives the robot (`REMOTE`/12) and every
  other B01 write. See PROTOCOL, *"write surface CONFIRMED GENERAL"*.

## Components

| Tool | Role | Status / validated metric |
|---|---|---|
| `pose_extract.py` | decode `0201`: live (x,y) + heading° + path-epoch; `reloc_loss` = FAULT-556 detector | live-confirmed (heading ±3° vs path tangent) |
| `nav.py` | heading-aware, **frame-agnostic** go-to. Modes `closed` (steer-to-bearing) / `dead` (open-loop). `--rel` offsets; `--patrol "x,y x,y …"` multi-waypoint. Aborts on reloc-loss **or** "stuck" (no-progress). | closed ~51 mm / dead ~95 mm single-leg (live A/B, small n); **patrol mean 38 mm** over one 3-leg tour |
| `scan.py` · on-demand lidar | **`./scan.py`** = one-command live snapshot: heartbeat → capture → render the raw real-time `0101` grid (no cloud fetch, no clean, **no motion**). Also: `vac.py map` = saved/segmented map · `START_CLEAN {"cmd":4}` = build a NEW map (free slot via `MULTI_MAP` delete) · `decode_map.py` renders any capture | **live grid proven decodable on demand** (2026-06-21): `scan.py` rendered the study at 76×58; a moving-capture decode hit 100% georef |
| `recover.py` | lost→remap→recover orchestrator (detect 556 → `cmd:4` rebuild → `nav.closed_loop`) | actions mechanically validated; **end-to-end needs a staged kidnap** |

## Motion model (characterized 2026-06-23, with error bars)

Measured against the robot's own SLAM (no external rig), one Q10/study, over a 400-trial detached batch:
- **Forward nudge ≈ 150 mm** (unobstructed; median 152, mean 146 ± 41) — each `drive forward` is one discrete move.
- **Turn ≈ 21.3°/nudge, SYMMETRIC L/R** (left 21.5 ± 2.3°, right 20.8 ± 2.0°; an apparent asymmetry was a measurement artifact).
- **Command→motion latency ≈ 3.0 s** (median; floor ~1.2 s) — the hard floor on closed-loop precision.
- **`stop` does NOT truncate a nudge**, and CLI sends are subprocess-paced (~1/s) → the robot is never in *continuous*
  motion, so there is no clean "stopping distance." Practical consequence: the closed-loop landing floor is ~1 nudge
  (≈38 mm with feedback); finer is not achievable on the discrete-nudge `REMOTE` interface.
- **Heading** (`0201` offset-10): drive-mode **1–2°**, teleop **8.7°**; clean-mode per-frame is noisy (not a validation regime).

## Gated / pending (need the user, or a decision)

- **Kidnap recovery demo** — a physical pick-up-and-set-down to induce a real "lost", then `recover.py`
  end-to-end. (The only missing piece of the recover flow.)
- **Multi-room goto** — goto is single-room-validated; the study is confined. Multi-room over the full
  apartment map is the "publishable" bar (blind-review note). Needs the study un-confined.
- **Sister-project extraction** — whether this layer stays here or graduates to its own repo is still
  open; for now it ships **in this repo, experimental**.

---
*Run via `./nav.py` / `./recover.py` (shebang → the conda `roborock` env, Python 3.11); never bare
`python3`. Planner is pure + unit-tested (`check_nav_planner.py`).*
