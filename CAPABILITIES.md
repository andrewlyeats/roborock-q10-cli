# Capability matrix — Roborock Q10 S5+ (B01)

> **As of:** 2026-06-27 · firmware 03.11.24 · `python-roborock` 5.14.2 (locked; upstream now 5.22.0).
> Best-effort/due-diligence as of this date. Readable overview + confidence key: **[PROTOCOL.md](PROTOCOL.md)**.

Every interaction the robot exposes (all 114 `B01_Q10_DP` data-points + library traits),
scoped by what we can and can't do — built from live testing + source/web research.

**Legend.** This table tracks a **capability axis** (can / can't / untested) — *distinct* from the
4-tier **confidence** key in [PROTOCOL.md](PROTOCOL.md) (Confirmed / Plausible / Reported / Unknown).
The glyphs are not the same scheme: here 🟡 means "needs RE/testing," **not** the confidence key's
🟡 "Plausible."
- ✅ **Confirmed** — tested live, works.
- 🟢 **Available** — exposed + mechanism proven (same path as a ✅), untested but should work.
- 🟡 **Unknown/untested** — needs reverse-engineering or testing, or deliberately not exercised.
- 🔴 **Not possible** — architectural limit, not exposed, or cloud-only.

For settings/data points that are both readable and writable, the Status shows **read · write** — e.g. ✅ ✅
(readable and writable), ✅ 🟡 (readable, write untested), ✅ ❌ (readable, write doesn't take).

How to drive anything: `./vac.py <verb>` for built-ins, or `./vac.py raw <DP_NAME> '<json>'`
for anything else (fire-and-forget). Reads come back on the MQTT stream, not as a return.

---

## 🔴 Architectural limits (can't be done this way, ever)
| Want | Why not |
|---|---|
| Local / LAN control | B01 is cloud-MQTT only — no local TCP port. Every command is a cloud round-trip. |
| AI obstacle **photos** and dirt events | This model has no camera (lidar + structured-light only), so obstacle *imagery* (cable/shoe/pet snapshots) and live dirt events aren't generated. **Obstacle *marker positions* (the "cones") ARE decoded** — they ride in the map frame's post-grid vector layers, along with erase/no-go areas and carpet (see DP_DICTIONARY + FRAME_ANATOMY). |

---

## Cleaning control (actions)
| Interaction | DP / method | Status | Notes |
|---|---|---|---|
| Start full clean | `START_CLEAN {cmd:1}` / `vacuum.start_clean` | ✅ | "smart" auto clean; robot undocks. |
| Pause | `PAUSE` / `pause_clean` | ✅ | reflects in status immediately. |
| Resume | `RESUME` / `resume_clean` | ✅ | resumes the paused clean. |
| Stop | `STOP` / `stop_clean` | ✅ | halts an active clean — catch it before it commits to docking (once it's returning, it may finish). |
| Return to dock | `START_DOCK_TASK {}` / `return_to_dock` | ✅ | → returning_home → charging. |
| Empty dustbin (dock) | `START_DOCK_TASK 2` / `empty_dustbin` | ✅ | dock auto-empty; loud, no robot motion. |
| Locate beep | `SEEK {}` / `vac.py find` | ✅ | plays a locate beep (audible only — not machine-verifiable). |
| Manual drive | `REMOTE` (101.12) via `vac.py drive` | ✅ works (string-key COMMON; live 2026-06-19) | Validated live 2026-06-19: the fixed `vac.py drive` (and `raw --common REMOTE <code>`) flips State to **`remote_control_active`** and the robot drives (0=fwd/2=left/3=right/4=stop=enter/5=exit). The old "deferred/inert" read was the **wrong-envelope** artifact — `vac.py drive` went via the library `RemoteTrait`, which sends `COMMON{` *enum-member* `REMOTE`: v}`, the same wrong inner-key bug as the settings overturn; **now fixed** to string-key `COMMON{"12": v}`. Drive moves the robot — use a clear space. |
| Room / segment clean | **instant:** MQTT `START_CLEAN {cmd:2}` · **scheduled / per-param:** one-time `POST /jobs` (REST) | ✅ validated live | `./vac.py clean-rooms <name\|id>…`. **`--mqtt`** = instant MQTT segment-clean (no Hawk; each room uses its *saved* fan/water/mode). Default = REST `/jobs`, fires **~2 min out** but carries per-job `--fan`/`--water`/`--route`/`--count`; `--dry-run` posts a *disabled* job (safe). A COMPLETE cycle (undock→clean→bin-empty→dock+charging) validated. |
| Spot / part clean | `START_CLEAN {201:5}` (scalar) → `Task=part` | ✅ live-verified 2026-06-21 | A **part/spot clean** around the robot's current position — **`cmd:5`**, the value missing from our 1/2/3/4 catalogue. Found via upstream PR #846 (its author live-verified) + **replicated live here**: `raw START_CLEAN 5` → STATUS `sweep_and_mop`, **`Task=part`**, **`CLEAN_TASK_TYPE`(138)=5**, then stopped+docked. The **scalar `{201:N}`** form works for parameter-less cleans (whole-home=1, spot=5) alongside our dict `{201:{cmd:N}}` form. |
| Zone / spot clean | `CUSTOMER_CLEAN` / `CUSTOMER_CLEAN_REQUEST` | 🟡 / observed as PART | App spot-clean runs a **PART** clean (`CLEAN_TASK_TYPE=5`) that needs a successful relocalize. `CUSTOMER_CLEAN`'s SET payload is unknown and not in the app-wire capture (the old "app input topic" framing is stale — the topic is open; the payload form is what's missing); a coord-bearing zone clean would leave the kitchen, untested. |
| Add-area clean | `ADD_CLEAN_AREA` / `ADD_CLEAN_STATE` | 🟡 state readable | State reads back: `ADD_CLEAN_AREA` = base64 `[01 00 00]` (no area set), `ADD_CLEAN_STATE` = 0. SET needs an area-coord payload — not tested (coord-less is uninformative; a coord-bearing one leaves the kitchen). |
| Cancel in motion | `TASK_CANCEL_IN_MOTION` | 🟡 (no-op) | Sent mid-clean (bare) — **did NOT cancel**. Not in the app-wire command surface, so the correct payload/trigger is unknown (the old "app-only / blocked topic" framing is stale). |
| Start dock / "back" task | `START_BACK` (202) | ✅ (`202:5` = dock) | The app **docks via top-level `{"202":5}`** (capture + openHAB confirm). The "no-op" tests used payloads `{}`/`1` during an *active clean* — wrong forms, not a dead DP. (202 vs 203=`START_DOCK_TASK` is a minor unprobed nuance.) |
| Floor-direction clean | `GROUND_CLEAN` (88) | ✅ SET captured | **"Clean along floor direction"** — Floor Cleaning Settings → Floor Cleaning Mode toggle (in full/room clean the robot cleans ALONG the floorboard direction to minimize scraping seams). Boolean; app SET via COMMON `{"88":1}`/`{"88":0}`, round-trip captured 2026-06-25 (on→off). Earlier "bare no-op" reads were the wrong-form/wrong-context era. |
| Misc | `BEAK_CLEAN`, `JUMP_SCAN` | 🟡 (no-op) | Each sent bare during an active clean — **no observable effect**. Neither appears in the app-wire command surface → correct payload/trigger unknown (the "app-only" framing is stale). |

## Settings (writes)

> **Stored preferences (`volume`/`child_lock`/`boost`/`dust`/`route`/…) are settable** through the **string-key
> COMMON(101)** envelope — `command.send(COMMON, {str(code): value})`, the exact form the app uses — and stick. An
> earlier interpretation found only a *subset of values* stuck (the runtime params) and read the rest as
> server-controlled; that was a wire-format inner-key bug, not server authority. The SET surface is **real but
> not universal** — a few prefs still don't take even via the correct envelope (the ❌ rows below).
>

| Setting | DP / verb | Read · Write | Notes |
|---|---|---|---|
| Fan / suction | `FAN_LEVEL` / `vac.py fan` | ✅ ✅ | quiet…max_plus. **Persists** — session/runtime param. |
| Water level | `WATER_LEVEL` / `vac.py water` | ✅ ✅ | off…high. **Persists.** |
| Clean mode | `CLEAN_MODE` / `vac.py mode` | ✅ ✅ | **1=vac+mop / 2=vac / 3=mop / 4=customized** (REST `/jobs` `YXCleanType`, codes 1–4 only). The MQTT DP uses `YXDeviceWorkMode`: same codes 1–4 plus **5=save_worry** and **6=sweep_mop** (sweep entire flat then mop; **code 6 live-observed**). Decoding code 6 via `YXCleanType` (which lacks value 6) crashes — use `YXDeviceWorkMode`. **Persists.** |
| Voice volume | `VOLUME` / `vac.py volume` | ✅ ✅ | 0–100. **Settable via string-key COMMON** — sticks across re-reads (validated live). |
| Child lock | `CHILD_LOCK` / `vac.py child-lock` | ✅ ✅ | **Settable via string-key COMMON** (same path as VOLUME). |
| Carpet auto-boost | `AUTO_BOOST` / `vac.py boost` | ✅ ✅ | **Settable via string-key COMMON** (same path as VOLUME). |
| Do-not-disturb | `NOT_DISTURB` 25 (enable) · `NOT_DISTURB_DATA` 33 (window) · `NOT_DISTURB_EXPAND` 92 (sub-flags) / `vac.py dnd` | ✅ ✅ | DND is **three** DPs under string-key COMMON, not one; `vac.py dnd` writes the captured app wire form. **Enable + window + sub-flags all SET live-validated** (2026-06-19: `dnd off`→`25=0` stuck, `dnd on`→`25=1` restored; `dnd on --start 22:00 --end 09:00` → DP 33 read-back `/BYACQAA` 2×; DP 92 `disturb_voice` toggled + restored). DP 33 is change-notification-only (periodic reads `null`); 6-byte base64 `[flag,sh,sm,eh,em,0]` window. |
| Auto-empty on/off | `DUST_SWITCH` (37) | ✅ ✅ | **Settable via string-key COMMON** (stuck). |
| Auto-empty frequency | `DUST_SETTING` (50) | ✅ ✅ | daily / interval_15…60. SET live-validated (0→15 stuck + restored). |
| Route pattern | `CLEAN_LINE` (78) | ✅ ✅ | **Settable via string-key COMMON**; also per-clean via `clean-rooms --route fast\|daily\|fine`. |
| Passes per area | `CLEAN_COUNT` | ✅ ✅ | a runtime cleaning param (same bucket as fan/water/mode). Also settable per-clean via `clean-rooms --count`. |
| Carpet handling | `CARPET_CLEAN_TYPE` / `CARPET_CLEAN_PREFER` / `SELF_IDENTIFYING_CARPET` | ✅ ✅ | **`CARPET_CLEAN_TYPE` SET live-validated** (0→1 stuck + restored). The other two aren't reported in a REQUEST_DPS dump. |
| Obstacle avoidance | `LINE_LASER_OBSTACLE_AVOIDANCE` (86) / `IGNORE_OBSTACLE` | 🟡 read · ✅ SET | **SET works via string-key COMMON — live round-trip validated** (2026-06-21: `1→0→1`, the device echoed each change on the daemon DP capture). The old "wrong envelope" verdict is closed. (Value isn't in the status dump; read via the daemon's DP echo.) |
| Resume-after-charge | `BREAKPOINT_CLEAN` | ✅ ❌ | reads `0`; **write to 1 did NOT stick** even via string-key COMMON — genuinely cloud-side or needs another form (unlike volume/dust/carpet). |
| Off-peak charging | `VALLEY_POINT_CHARGING` (105) / `VALLEY_POINT_CHARGING_DATA` (107) | ✅ read · ✅ SET (enable) | switch + `…_DATA_UP` window readable (6-byte, same format as DND). **Enable SET works via string-key COMMON — live round-trip validated** (2026-06-21: `false→true→false`, device-echoed). The window-blob SET (107) is the same class (very likely settable), individually untested. The old "wrong envelope" verdict is closed. |
| Map persistence | `MAP_SAVE_SWITCH` / `MULTI_MAP_SWITCH` | ✅ ❌ | `MAP_SAVE_SWITCH` reads `True`; **write to 0 didn't stick** even via string-key COMMON — genuinely cloud-side or another form. `MULTI_MAP_SWITCH` reads `4`, SET untested. |
| Voice pack / language | `VOICE_LANGUAGE` / `VOICE_VERSION` (read) · `VOICE_PACKAGE` | ✅ 🟡 | `VOICE_LANGUAGE` (104=es) / `VOICE_VERSION` readable; `VOICE_PACKAGE` (35) request-only, never seen. SET **deliberately not exercised** — changing voice pack/language can trigger a firmware voice-pack download. |
| Units | `UNIT` / `AREA_UNIT` | ✅ read (`AREA_UNIT`) · ✅ SET validated | **`AREA_UNIT` IS reported** — reads `1` (✅ **RESOLVED 2026-06-21: `0`=m², `1`=ft²**; live-confirmed `=1` in a post-clean sync while the app showed ft²; see DP_DICTIONARY). **Display-preference only** — the `clean_area`/`total_clean_area` status *values* stay natively **m²** (map-cross-checked), so the tool's `m²` labels hold regardless of this flag. `UNIT` (42) still never seen. **SET round-trip validated via string-key COMMON (dual-tap, 2026-06-24).** |
| Dock button light | `BUTTON_LIGHT_SWITCH` | 🟡 🟡 | reported only on change (reads `null` otherwise); SET not retested via string-key COMMON. |
| Logging | `LOG_SWITCH` | 🟡 🟡 | not reported in a dump — no read-back channel to confirm a SET either way. |
| Room targeting | `CLEAN_EXPAND` | ✅ — | read-only: JSON `{"room_id_list":[…]}` echoes the active clean's target rooms. |
| Misc / unclear | `CUSTOM_MODE`, `FLEEING_GOODS`, `SUSPECTED_THRESHOLD` | 🟡 | not reported / unused — semantics unknown. (`CLEAN_ORDER` is now decoded + ✅live SET — see Map management; `FLOOR_MATERIAL` SET validated — see Map & spatial.) |

## Maintenance (consumable counter resets)
| Interaction | DP | Status | Notes |
|---|---|---|---|
| Reset main brush | `RESET_MAIN_BRUSH` | 🟡 (untested by choice) | resets the used-counter; do after physical replacement. **Not exercised** — firing it would falsely zero a real consumable's life counter. |
| Reset side brush / filter / sensor / rag | `RESET_SIDE_BRUSH` / `RESET_FILTER` / `RESET_SENSOR` / `RESET_RAG_LIFE` | 🟡 (untested by choice) | same — would corrupt maintenance tracking; deliberately not fired. |
| Reset / set room name | `RESET_ROOM_NAME` | ✅ read · ✅ SET validated | the room-rename DP (see Map & spatial) — decoded; **SET round-trip validated via string-key COMMON (dual-tap, 2026-06-24).** |
| ⚠️ Reset map | `MAP_RESET` | 🟡 untested | **destructive** — wipes the saved map; never fired (no reversal path, no known-correct payload). Avoid. |

## Map & spatial
| Interaction | DP | Status | Notes |
|---|---|---|---|
| Get room/wall map | `MULTI_MAP` (+ 301 stream) | ✅ | LZ4 grid, 7 rooms decoded (home-specific count) → `vac.py map`. |
| **Build / manage maps on demand** | `START_CLEAN {"cmd":4}` · `MULTI_MAP` delete/select | ✅ validated 2026-06-20 | **`vac.py map-build`** quick-maps a NEW map (STATUS 29, ~30–60 s; needs a free slot); **`vac.py multimap delete <id> --yes` / `select <id>`** (delete frees a slot, cap ≈ 4; **`op:apply <id>` switches the active map** — `op:select` is list-preview only — and a switch does NOT re-localize; only a clean / dock-return does. 2026-06-25). The SAVED map (`vac.py map`) is onboard-finalized → it ≠ the raw build stream. |
| **Live pose+heading readout / autonomous go-to(experimental)** | DP-110 `HEARTBEAT` + 301 `0201` (x,y **+ heading** at `b[10:12]`) | ✅ validated live 2026-06-20 | **`pose_monitor.py`** = live (x,y) cockpit; **`nav.py <x> <y> [--mode closed\|dead] [--rel]`** = heading-aware autonomous go-to, **frame-agnostic** (steers by bearing using live heading, no dock-origin assumption), modes closed-loop (pose+heading feedback) / dead-reckon (open-loop motion-model) + **`--patrol "x,y x,y …"`** multi-waypoint, with **reloc-loss + stuck aborts**. Live in-study (small n): closed-loop ~51 mm, dead-reckon ~84–95 mm single-leg, patrol mean 38 mm/leg. **★ Closed-loop goto execution validated end-to-end live 2026-06-25 (the long-noted "publishable bar"): converged precision ≈18 mm at a tight 8u≈20 mm margin; the earlier 37 mm was the margin-STOP, not the precision floor (the run overshot at it=3, corrected back to 18 mm by it=7 — undock-shift is corrected away during iteration, so it only confounds open-loop dead-reckon step-size measured from the dock). on-map goto is enabled (the earlier pause-guard is lifted); full whole-apartment multi-room nav stays gated (robot study-confined). Re-localization dependency: a CLEAN actively re-localizes (~mid-clean); a plain dock-return / `op:select` / `op:apply` does NOT — after any manual drive-off (mis-dock fix, teleop) the robot is de-localized, so re-localize via a confined `clean-rooms Test` before relying on goto. nav.py's `reloc-loss` / `stuck` / `no-signal` aborts all fired correctly — validated safety features; it never blind-drives a lost robot.`recover.py`** chains lost→remap→recover (see `AUTONOMY.md`). `goto1.py` is the earlier −x/dock-origin-specific version (37 mm/10 on the study map). Motion model (error-barred 2026-06-23, see `AUTONOMY.md`): fwd nudge **≈150 mm**, turn **≈21.3°/nudge (symmetric L/R)**, command→motion latency **≈3.0 s** (floor 1.2 s); `stop` does not truncate the atomic nudge (discrete-nudge interface — no continuous-brake regime). **Heading accuracy by regime: drive-mode 1–2°** (deliberate long straight runs, 2026-06-22); **teleop 8.7° mae** (48 motion / 17 turn frames); **clean-mode per-frame heading diverges from the accumulated-path tangent (~18–52°)** — an instantaneous sample during active maneuvering vs an accumulated path, not bad data; **not a tight-validation regime.** ⚠ MOVES the robot. |
| Room directory / category | `CUSTOMER_CLEAN` (62) | ✅ read | `[count:u8]` + N×47B records; **byte[2] = room category** (`ROOM_CATEGORY`: 1 master / 4 living / 6 kitchen / 8 toilet / 10 study / 0 unset — survives renames; the library has no room-type enum, so it's ours; ⚠ the enum is THIS home's, inferred), **byte[10] = floor material**. `vac.py rooms` surfaces **id + name** only — category/material are analysis-confirmed byte positions **not surfaced by the tool**. |
| Robot position + path | 301 `0201` stream | ✅ | live during a clean **OR on demand** — any client sending DP-110 (`HEARTBEAT`) polls (~5 s) gets the live `0201` path/pose stream, **including during manual teleop, no camera rig** (`raw --common HEARTBEAT 1` + a daemon bytes tap → `pose_extract.py`, offset-14). Cross-validated vs the app's Remote-Control screen. |
| Live occupancy grid (lidar map) **(experimental)** | 301 `0101` stream | ✅ on demand | **`scan.py`** — heartbeat (DP-110) → capture → decode the RAW live `0101` grid to a PNG (no cloud `get_map`, no clean, **no motion**). The map counterpart of the on-demand `0201` pose above — distinct from `vac.py map` (the onboard-finalized SAVED map). Proven 2026-06-21: `decode_map` renders a heartbeat-stream capture (study 77×58) at 100% path-on-floor georef; `scan.py` live-rendered the study (76×58). |
| Carpet / no-mop zone | `GET_CARPET` / `CARPET_UP` | ✅ read · ✅ SET | JSON `{id,rug_clean_mode,vertexs:[[x,y]×4]}` — decoded. **SET CONFIRMED 2026-06-25** via `GET_CARPET`(64) `op:save` (CLI-replicated clear/list round-trip; `rug_clean_mode` confirms `YXCarpetCleanType`). See the `CARPET_UP` row in `DP_DICTIONARY.md`. |
| Virtual wall | `VIRTUAL_WALL` (56) / `_UP` (57) | ✅ SET validated | READ format cracked; **SET works via string-key COMMON — live round-trip validated** (`wall add`→read→`wall clear`→restored). The old "blocked" used the wrong envelope. `vac.py wall`. |
| No-go / no-mop / restricted zone | `RESTRICTED_ZONE` (54) / `_UP` (55) | ✅ SET validated | decoded (types 0=no-go / 2=no-mop / 3=threshold). **SET works via string-key COMMON — live-validated** (added a zone, read back, restored). `vac.py zone`. |
| Floor material | `FLOOR_MATERIAL` | ✅ read · ✅ SET validated | `[01][n](room_id,material)`; `YXRoomMaterial` (2=tile, 255=other). **SET round-trip validated via string-key COMMON (dual-tap, 2026-06-24).** |
| **Room split** | `ROOM_SPLIT` (73) | ✅ read · ✅ SET captured | **SET format captured 2026-06-25** (app-driven on disposable Map2): base64 `[room_id:u8]` + **2×(x,y) int16-BE split-line endpoints in robot ~5 mm units** (e.g. `A/wj/wYAWv8G`=`[3]`+(988,-250)→(90,-250), a horizontal split of room 3). The app auto-places a default split line on room-select; Complete commits; the robot then regenerates the grid (no separate coord echo). |
| Room rename | `RESET_ROOM_NAME` | ✅ read · ✅ SET validated | `[01][id][namelen][name]` — decoded. **SET round-trip validated via string-key COMMON (dual-tap, 2026-06-24).** |
| **Room merge / combine** | `ROOM_MERGE` (72) | ✅ SET captured | **SET format captured 2026-06-25** (app-driven on disposable Map2): base64 `[count:u8][room_id:u8 ×count]` — same shape as `CLEAN_ORDER` (e.g. `AgMB`=`[2,3,1]` merges rooms 3+1). |
| Restricted area / cliff area | `RESTRICTED_AREA` / `CLIFF_RESTRICTED_AREA` (+`_UP`) | 🟡 unused | not drawn. |
| Door thresholds | `SUSPECTED_THRESHOLD` / `_UP` | ✅ read (decoded) | **NON-EMPTY observed** — `SUSPECTED_THRESHOLD_UP` showed `[[-172,157]]` : robot-DETECTED threshold/cliff coords in the path frame (≠ user-DRAWN thresholds, which go to `RESTRICTED_ZONE` type `0x03`). Format decoded. |
| Map-build event | `CREATE_MAP_FINISHED` | 🟡 event-only | fires on a map-build completion. |

## Map management (inferred from the iOS app UI)
Recorded from what the app *offers*. **REVISED:** the "our op-sends get no reply / likely blocked input
topic" verdict was the **wrong-envelope** artifact — via **string-key COMMON** our own `MULTI_MAP {op:list}`
now REPLIES (`vac.py multimap list`; see the Map list row). **`op:apply <id>` switches the active map**
(CLI-validated 2026-06-25, no motion); `op:select` is list-preview only and does **NOT** switch or re-localize —
re-localization is an active process (a clean / dock-return), not a passive select (2026-06-24/25). `MAP_SAVE_SWITCH`
is **live-tested NOT settable** even via the correct envelope.

| App feature | likely DP | inferred status |
|---|---|---|
| Combine / merge rooms | `ROOM_MERGE` (72) | ✅ SET captured 2026-06-25 — `[count][room_id ×count]` (see Map & spatial) |
| Cleaning sequence (room order) | `CLEAN_ORDER` (82) | ✅ decode + ✅live SET-via-CLI — `[count:u8][ordered room_id ×count]` (e.g. `AwcJBQ==`=[3,7,9,5]); restored via `vac.py raw --common CLEAN_ORDER`, 2026-06-25 |
| Map rename | `MULTI_MAP {op:rename?}` | 🟡 unknown — settability unproven |
| Map delete | `MAP_RESET` / `MULTI_MAP {op:delete?}` | 🟡 unknown — ⚠️ destructive, don't test casually |
| Set map as home / select | `MULTI_MAP {op:apply,id}` | ✅ `op:apply {id}` switches the active map (CLI-validated 2026-06-25); `op:select` = list-preview only |
| Toggle map saving | `MAP_SAVE_SWITCH` | ❌ live-tested NOT settable even via string-key COMMON |
| Single- vs multi-level home | `MULTI_MAP_SWITCH` | 🟡 untested — reads `4`; SET via string-key COMMON untested (the "stored-pref bucket = cloud-auth" premise is overturned) |
| Map list | `MULTI_MAP {op:list}` | ✅ live pull | **Our own `op:list` now REPLIES** via string-key COMMON — `vac.py multimap list` returns each map's id+name+timestamp live (Testmap3/Testmap4). The old "broadcast-only / no reply to us" was the enum-key envelope. |
| 90° CW map rotation (map screen) | (no clear DP) | 🟡 likely an app *display* transform; if it persists server-side it may relate to the path/grid orientation twist seen in georeferencing. **Capturing a rotated map + diffing the `0101` header is the open test for whether orientation is a latent header field** (see FRAME_ANATOMY's georeference section) — today it's a validated convention the renderer fits (`map_render` `Registration`), not a read field |

## Scheduling
| Interaction | DP / method | Status | Notes |
|---|---|---|---|
| List cloud schedules | REST GET `/user/devices/{duid}/jobs` | ✅ | `./vac.py schedule list` works. Hawk auth via `rriot`. |
| Enable / disable / delete / add | REST PUT/DELETE/POST same endpoint | ✅ | Write path confirmed (Hawk body-signing fix). `vac.py schedule enable/disable/delete/add` all live. (Upstreamed as [PR #852](https://github.com/Python-roborock/python-roborock/pull/852) — **merged**, released in 5.15.2.) |
| On-device schedule | `TIMER` / `REQUEST_TIMER` / `TIMER_TYPE` | ✅ VESTIGIAL | `TIMER` reads `[01 FC 00 00]` and **stays unchanged even with an active app schedule** (verified live 2026-06-21: a "Scheduled cleaning" for 18:45 left `TIMER` untouched; `REQUEST_TIMER` returns nothing new). **Q10 scheduling lives entirely in cloud REST `/jobs`** — this DP is vestigial/unused on the Q10. The old "format unknown / needs a timer-set capture" question is closed: setting a timer doesn't touch it. |
| Host cron | `./vac.py start` via system cron | ✅ alt | simplest path for "clean daily at 10 AM" — no REST write needed. |

## Connection / daemon
The cloud broker rate-limits new MQTT CONNECTs (account-level `code 135`), which knocks out the CLI
*and* the phone app. Fixed architecturally — a long-running **daemon holds ONE MQTT connection** and
serves the CLI over a Unix socket. See [PROTOCOL.md](PROTOCOL.md#transport).

| Interaction | How | Status | Notes |
|---|---|---|---|
| Single-connection daemon | `./vac.py daemon start [--careful]` / `stop` / `restart` / `status` | ✅ | Holds one `DeviceManager`; the CLI uses it by default (`--force` runs standalone). `--careful` halts on the first 135/auth complaint and is **preserved across `restart`**. ⚠ A running daemon serves **stale code** after a `vac.py` edit — `daemon restart` is required for new/changed verbs to take effect (a new verb silently does nothing against a running daemon until it is restarted). Daemon-served `status` now **warns when the held shadow is stale** (no live frame in >90 s ⇒ `⚠ data is N min old — the robot may be offline or sleeping`), so an offline robot no longer reads as a live cached state. |
| Fast status (no MQTT/daemon) | `./vac.py status --quick` | ✅ | REST device-shadow read (`GET /devices/{duid}/shadow`, Hawk) — no MQTT, no daemon; returns the legacy v1 DP space (battery/state/totals). A quick one-shot check. |
| Telemetry taps | `./vac.py daemon record --events/--novel/--bytes F` | ✅ | In-process fan-out over the one held connection → **zero extra cloud connections/subscriptions**. `--bytes` captures raw 301 map/path frames. |
| Live stream | `./vac.py watch [--raw\|--bytes] [--out F]` | ✅ | Streams the daemon event bus to stdout/file; watchers reaped promptly on client disconnect. |
| 135 recovery | escalating backoff → `needs_login` | 🟢 | offline-tested; not yet exercised by a *natural* live 135. Don't provoke. |

## Reads / telemetry
Every data-point in [DP_DICTIONARY.md](DP_DICTIONARY.md) reads back on the MQTT stream — state, totals,
consumables, environment, and plumbing (`REQUEST_DPS` / `HEARTBEAT` / `COMMON`). Notables:
- ✅ **Clean history** — `CLEAN_RECORD` 12-field per-clean string; decode now mirrors the library's
  `b01_q7.CleanRecordDetail` names (field 2 = active use-time [`duration_min` ↔ `record_use_time`], area ÷1000, mode/route/task_status). **The live
  `op:list` pull WORKS** via string-key COMMON — `vac.py history` returns the full back-catalog (25 records,
  live-validated -). `history --from-capture` still decodes offline from a capture. (The old
  "no reply / push-to-app-only" was the enum-key envelope.)
- ✅ **STATUS is mode-specific while cleaning** — `102`=sweeping, `103`=mopping, `104`=sweep_and_mop
  (= CLEAN_MODE 2 / 3 / 1); `22`=dock auto-empty, `8`=charging. See DP_DICTIONARY STATUS row.
- ✅ `RECENT_CLEAN_RECORD` — a boolean "a recent clean exists" flag (distinct from the `CLEAN_RECORD` list).
- 🟡 `DEVICE_INFO` — never seen over MQTT (request-only per the catalog; REST path not independently confirmed).
- The robot reports **~66** of the 114 catalog DPs across all sessions (61 in a single `REQUEST_DPS` harvest); the rest are set-only or never triggered. A few
  structured blobs are decoded (`CLEAN_EXPAND` / `NOT_DISTURB_EXPAND` JSON; `TIMER`, `NOT_DISTURB_DATA`,
  `ADD_CLEAN_AREA`, `VALLEY_POINT_CHARGING_DATA_UP` are base64-binary, same family as walls/zones).

---

## Limitations

- **One tested device.** Everything here is validated on a single Roborock Q10 (S5+); behaviour on other firmware or sibling B01 models may differ.
- **Depends on `python-roborock` internals.** The CLI rides private, undocumented internals of the library, which can break on upgrade — mitigated by a pinned dependency set (`requirements.lock.txt`) and `check_roborock_api.py`, a canary that flags an internal that moved.

