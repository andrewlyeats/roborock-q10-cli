# Capability matrix — Roborock Q10 S5+ (B01)

Every interaction the robot exposes (all 114 `B01_Q10_DP` data-points + library traits),
scoped by what we can and can't do. Built 2026-06-12 from live testing + source/web research.

**Legend**
- ✅ **Confirmed** — tested live, works.
- 🟢 **Available** — exposed + mechanism proven (same path as a ✅), untested but should work.
- 🟡 **Unknown** — needs reverse-engineering or testing (payload/format unclear).
- 🔴 **Not possible** — architectural limit, not exposed, or cloud-only.

How to drive anything: `./vac.py <verb>` for built-ins, or `./vac.py raw <DP_NAME> '<json>'`
for anything else (fire-and-forget). Reads come back on the MQTT stream, not as a return.

---

## 🔴 Architectural limits (can't be done this way, ever)
| Want | Why not |
|---|---|
| Local / LAN control | B01 is **cloud-MQTT only** — no local TCP port. Every command is a cloud round-trip. |
| Obstacle objects + photos | **This model has no camera** (lidar + structured-light only, user-confirmed) — so AI-classified obstacles (cable/shoe/pet) and obstacle photos **don't exist at all**, not just "cloud-only." Confirmed: zero map/photo URLs in the app's REST traffic. Structured-light avoidance reports presence/height, no imagery. |
| Map georeference for free | The on-demand `MULTI_MAP` returns the same `0101` grid, NOT the Q7 SCMap with `MapHeadInfo` (resolution/origin). Must derive the transform ourselves. |
| Live obstacle/dirt events | Same cloud-side boundary. |

---

## Cleaning control (actions)
| Interaction | DP / method | Status | Notes |
|---|---|---|---|
| Start full clean | `START_CLEAN {cmd:1}` / `vacuum.start_clean()` | ✅ | "smart" auto clean; robot undocks. **Confirmed against a live device:** STATUS 8→104→101, CLEAN_TASK_TYPE=1. |
| Pause | `PAUSE` / `pause_clean()` | ✅ | reflects in status immediately. **Confirmed against a live device:** →STATUS 10. |
| Resume | `RESUME` / `resume_clean()` | ✅ | **Confirmed against a live device:** 10→101 (resumed cleaning). |
| Stop | `STOP` / `stop_clean()` | 🟢 | library method (dock used to end runs in testing). |
| Return to dock | `START_DOCK_TASK {}` / `return_to_dock()` | ✅ | → returning_home → charging. **Confirmed against a live device:** →STATUS 6→22→8. |
| Empty dustbin (dock) | `START_DOCK_TASK 2` / `empty_dustbin()` | ✅ | dock auto-empty; loud, no robot motion. **Confirmed against a live device:** auto-empty fired on dock return (STATUS 22, BACK_TYPE=4). |
| Locate beep | `SEEK {}` / `vac.py find` | ✅ | **`vac.py find` sent OK against a live device** ("Locate signal sent"); audible beep not machine-verifiable. |
| Manual drive | `REMOTE` via `remote.{forward,left,right,stop}` | 🟢 | exposed; **moves the robot** — untested. |
| Room / segment clean | one-time `POST /jobs` `rooms:[…]` (REST) | ✅ **validated live (targeting)** | `./vac.py clean-rooms <name\|id>…`. **Targeting confirmed live on 3 rooms** — robot accepted EXACTLY the requested room (`CLEAN_EXPAND.room_id_list`=[5]/[6]/[1], `CLEAN_TASK_TYPE`=2). `--fan max_plus` posts `fanLevel=5` (B01 fix) ✅; numeric-id grid-skip ✅. NB: physical cleans **faulted** (570/501) due to the **environment** (a virtual-wall enclosure made some rooms unreachable; cramped baths) — not a vac.py bug; targeting was always correct. A fault-free complete physical run still wanted. `--dry-run` posts a disabled job (safe). |
| Zone / spot clean | `CUSTOMER_CLEAN` / `CUSTOMER_CLEAN_REQUEST` | 🟡 | payload unknown. |
| Add-area clean | `ADD_CLEAN_AREA` / `ADD_CLEAN_STATE` | 🟡 | unknown. |
| Cancel in motion | `TASK_CANCEL_IN_MOTION` | 🟡 | unknown. |
| Start "back" task | `START_BACK` | 🟡 | unclear vs dock. |
| Misc | `BEAK_CLEAN`, `JUMP_SCAN`, `GROUND_CLEAN` | 🟡 | purpose unknown. |

## Settings (writes)

> **Settled:** `volume`/`auto_boost`/`child_lock` are **☁ cloud-authoritative**
> — the server stores user preferences and re-asserts them after any MQTT write. App-force-closed
> test confirmed: `vac.py volume 70` accepted, MQTT echo returns 55. Earlier "CLI write didn't land"
> observations were real, not a confound. `fan`/`water`/`mode` work normally because they are runtime
> session parameters (not stored user preferences). See DESIGN_NOTES.md.
>
> **CLI honesty:** `vac.py volume`/`child-lock`/`boost` now print a
> "cloud may revert this — change it in the app to persist" caveat after the success line,
> so the CLI no longer implies the write stuck. (Code: `CLOUD_REVERT_NOTE` in vac.py.)

| Setting | DP / verb | Status | Notes |
|---|---|---|---|
| Fan / suction | `FAN_LEVEL` / `vac.py fan` | ✅ | quiet…max_plus. **Persists — confirmed against a live device** (FAN_LEVEL echoed the set value and stuck; session/runtime param, not cloud-overridden). |
| Water level | `WATER_LEVEL` / `vac.py water` | ✅ | off…high. **Persists — confirmed against a live device.** |
| Clean mode | `CLEAN_MODE` / `vac.py mode` | ✅ | vac/mop/vac+mop. **Persists — confirmed against a live device.** |
| Voice volume | `VOLUME` / `vac.py volume` | ☁ cloud-authoritative | CLI send accepted; server re-asserts stored value (55). Set via app only. ✅ confirmed, **re-confirmed against a live device** (echo stayed 55). |
| Child lock | `CHILD_LOCK` / `vac.py child-lock` | ☁ cloud-authoritative | App toggle confirmed ✅ (echo 0→1→0). **Confirmed against a live device:** `child-lock on` accepted but echo stayed 0 (server re-asserts). |
| Carpet auto-boost | `AUTO_BOOST` / `vac.py boost` | ☁ cloud-authoritative | CLI write didn't land — confirmed real behaviour (not confound). App toggle confirmed ✅. ✅ settled, **re-confirmed against a live device** (echo stayed 0). |
| Do-not-disturb | `NOT_DISTURB` / `NOT_DISTURB_DATA` / `vac.py dnd` | ☁ cloud-authoritative | **Confirmed against a live device:** `dnd off` accepted but NOT_DISTURB stayed 1 (never dropped); `dnd on` sends only `NOT_DISTURB_DATA` which never echoed. **Both CLI paths are ineffective** — the server owns this stored preference (same bucket as volume/child-lock/boost). Set via app. |
| Auto-empty on/off | `DUST_SWITCH` | 🟢 | settable. |
| Auto-empty frequency | `DUST_SETTING` | 🟢 | daily / interval_15…60. |
| Route pattern | `CLEAN_LINE` | 🟢 | fast / daily / fine. |
| Passes per area | `CLEAN_COUNT` | 🟢 | 1 or 2 (clean-twice). |
| Carpet handling | `CARPET_CLEAN_TYPE` / `CARPET_CLEAN_PREFER` / `SELF_IDENTIFYING_CARPET` | 🟢 | |
| Obstacle avoidance | `LINE_LASER_OBSTACLE_AVOIDANCE` / `IGNORE_OBSTACLE` | 🟢 | on/off. |
| Resume-after-charge | `BREAKPOINT_CLEAN` | 🟢 | |
| Off-peak charging | `VALLEY_POINT_CHARGING` / `VALLEY_POINT_CHARGING_DATA` | 🟢 | |
| Map persistence | `MAP_SAVE_SWITCH` / `MULTI_MAP_SWITCH` | 🟢 | |
| Voice pack / language | `VOICE_PACKAGE` / `VOICE_LANGUAGE` | 🟢 | |
| Units | `UNIT` / `AREA_UNIT` | 🟢 | m²/ft². |
| Dock button light | `BUTTON_LIGHT_SWITCH` | 🟢 | |
| Logging | `LOG_SWITCH` | 🟢 | |
| Misc / unclear | `CUSTOM_MODE`, `CLEAN_ORDER`, `CLEAN_EXPAND`, `FLOOR_MATERIAL`, `FLEEING_GOODS`, `SUSPECTED_THRESHOLD` | 🟡 | semantics/format unknown. |

## Maintenance (consumable counter resets)
| Interaction | DP | Status | Notes |
|---|---|---|---|
| Reset main brush | `RESET_MAIN_BRUSH` | 🟢 | resets the used-counter; do after physical replacement. |
| Reset side brush / filter / sensor / rag | `RESET_SIDE_BRUSH` / `RESET_FILTER` / `RESET_SENSOR` / `RESET_RAG_LIFE` | 🟢 | same. |
| Reset / set room name | `RESET_ROOM_NAME` | 🔒 read-only | it's the room-rename DP (see Map & spatial) — decoded, but SET blocked like other map edits. |
| ⚠️ Reset map | `MAP_RESET` | 🟡 untested | **destructive** — wipes the saved map; never tested (may be blocked like other map writes). Avoid. |

## Map & spatial
| Interaction | DP | Status | Notes |
|---|---|---|---|
| Get room/wall map | `MULTI_MAP` (+ 301 stream) | ✅ | LZ4 grid, 7 rooms decoded → `vac.py map`. |
| Robot position + path | 301 `0201` stream | ✅ | live during cleaning only. |
| Carpet / no-mop zone | `GET_CARPET` / `CARPET_UP` | 🔒 read-only | JSON `{id,rug_clean_mode,vertexs:[[x,y]×4]}` — decoded (you drew a 200 mm carpet); SET blocked. |
| Virtual wall | `VIRTUAL_WALL` / `_UP` | 🔒 read-only | **READ format cracked** (`[count][x1,y1,x2,y2]` BE int16); **SET blocked** — 4 send variants didn't engage (write rides the blocked input topic). |
| No-go / no-mop / restricted zone | `RESTRICTED_ZONE` / `_UP` | 🔒 read-only | decoded (rectangles, mm); also holds no-mop + thresholds. SET blocked (same as walls). |
| Floor material | `FLOOR_MATERIAL` | 🔒 read-only | `[01][n](room_id,material)`; `YXRoomMaterial` (2=tile, 255=other), confirmed by toggling room 6; SET blocked. |
| **Room split** | `ROOM_SPLIT` | 🔒 read-only | **observed** — you split room 2 → "Test"; ack `=1`, the geometry change is in the regenerated grid. SET blocked. |
| Room rename | `RESET_ROOM_NAME` | 🔒 read-only | `[01][id][namelen][name]` — decoded (renamed room 2 → "Test"); SET blocked. |
| **Room merge / combine** | `ROOM_MERGE` | 🟡 not yet done | not captured (we never ran merge); inferred read-only like split. |
| Restricted area / cliff area | `RESTRICTED_AREA` / `CLIFF_RESTRICTED_AREA` (+`_UP`) | 🟡 unused | stayed empty `[]` — not drawn. |
| Door thresholds | `SUSPECTED_THRESHOLD` / `_UP` | 🟡 unused | stayed empty — thresholds you drew went into `RESTRICTED_ZONE` instead. |
| Map-build event | `CREATE_MAP_FINISHED` | 🟡 | read/event. |

## Map management (inferred from the iOS app UI — not yet captured/tested)
Recorded from what the app *offers*; the robot must support these. Most are structured
map-mutations → expected **read-only** over MQTT (write command unobservable, like walls).
The scalar toggles are the likely exceptions (controllable). `MULTI_MAP` is the one
structured DP we *can* send (`{op:list}` works), so its other `op`s may be reachable.

| App feature | likely DP | inferred status |
|---|---|---|
| Combine / merge rooms | `ROOM_MERGE` | 🔒 read-only (structured, like `ROOM_SPLIT`) |
| Cleaning sequence (room order) | `CLEAN_ORDER` | 🟡 unknown (structured; maybe a settable order list) |
| Map rename | `MULTI_MAP {op:rename?}` | 🟡 unknown — `MULTI_MAP` op-sends DO reach the robot, so this may be settable |
| Map delete | `MAP_RESET` / `MULTI_MAP {op:delete?}` | 🟡 unknown — ⚠️ destructive, don't test casually |
| Set map as home / select | `MULTI_MAP {op:select?}` | 🟡 unknown |
| Toggle map saving | `MAP_SAVE_SWITCH` | ✅ likely controllable (scalar bool, like other settings) |
| Single- vs multi-level home | `MULTI_MAP_SWITCH` | ✅ likely controllable (scalar) |
| Map list | `MULTI_MAP {op:list}` | ✅ read — confirmed works |
| 90° CW map rotation (map screen) | (no clear DP) | 🟡 likely an app *display* transform; if it persists server-side it may relate to the path/grid orientation twist we hit in georeferencing |

## Scheduling
| Interaction | DP / method | Status | Notes |
|---|---|---|---|
| List cloud schedules | REST GET `/user/devices/{duid}/jobs` | ✅ | `./vac.py schedule list` works. Hawk auth via `rriot`. |
| Enable / disable / delete / add | REST PUT/DELETE/POST same endpoint | ✅ | Write path confirmed (Hawk body-signing fix, committed f8aa403). `vac.py schedule enable/disable/delete/add` all live. |
| On-device schedule | `TIMER` / `REQUEST_TIMER` / `TIMER_TYPE` | 🟡 | format unknown; fallback if REST writes stay blocked. |
| Host cron | `./vac.py start` via system cron | ✅ alt | simplest path for "clean daily at 10 AM" — no REST write needed. |

## Reads / telemetry (all ✅ — see DP_DICTIONARY.md)
State `STATUS`, `BATTERY`, `CLEAN_PROGRESS`, `CLEAN_TIME`, `CLEAN_AREA`, `FAULT`,
`CLEAN_TASK_TYPE`, `BACK_TYPE`, `MOP_STATE` · totals `TOTAL_CLEAN_*`, `CLEAN_COUNT` ·
consumables `*_LIFE` (read) · env `NET_INFO`, `TIME_ZONE`, `ROBOT_COUNTRY_CODE`,
`ROBOT_TYPE`, `USER_PLAN`, `VOICE_VERSION/LANGUAGE`, `AREA_UNIT` · plumbing `REQUEST_DPS`,
`HEARTBEAT`, `OFFLINE`, `COMMON` (response wrapper).
- ✅ `CLEAN_RECORD` — clean **history** decoded: `{"data":[<underscore-string per clean>]}`
  (`<id>_<unixtime>_…_<flags>`). Emitted on `op:notify` (e.g. when the app opens history).
- 🟡 `DEVICE_INFO`, `RECENT_CLEAN_RECORD` — returned nothing to a bare request.

---

## Next experiments to resolve the 🟡s (priority order)

**Major items resolved:** write token (was Hawk body-signing, not scope) ✅;
`clean-rooms` dry-validated ✅ and **validated against a live device** (correct room targeting on 3 rooms,
B01 fan=5) ✅; settings cloud-authoritative behaviour fully mapped live ✅;
the volume/boost/child-lock settings are cloud-authoritative ✅.

1. **Live room clean** — **validated live** for targeting/params (robot accepted the exact requested room
   each time). Still wanted: one **fault-free complete physical run** — the cleans faulted on
   environment (virtual-wall enclosure / cramped baths), not software. Best next attempt: an open,
   reachable room with the area clear.
2. **Settings** — **validated live:** volume/child-lock/boost/dnd are cloud-authoritative (CLI sends
   accepted but reverted); fan/water/mode persist (session params) ✅. CLI now prints a revert caveat.
3. **Walls/zones SET** — MQTT-only (write command rides the blocked input topic). Read formats
   fully decoded. Only path forward: WireGuard MITM or a self-sent `{"op":"save"}` retry.
4. **`CLEAN_RECORD` field decode** — trailing field t1 unclear (12/154/192/230 pattern). Needs
   samples with known fan levels at clean completion.
5. **Manual drive** — test `remote.forward/left/right/stop` (moves robot; do in clear space).
6. **Shadow endpoint as `status --quick`** — `GET /devices/{duid}/shadow` returns 11 DPs via
   pure REST (no MQTT session). Could speed up `vac.py status`. ❓ untested.
