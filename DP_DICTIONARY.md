# Data-point dictionary (B01 / Q10 S5+)

What each data-point (DP) the robot emits **actually means**, built by observing a
live "mop entire apartment" run on 2026-06-12 (captured to a JSONL feed) and
cross-referencing `B01_Q10_DP` in the library.

- **Observed** = value(s) actually seen in the feed (a range, or the constant value).
- **Meaning** = inferred; ✅ confirmed by behavior, ❓ hypothesis, ⬆/⬇ direction.
- The catalog has **114** DPs; the robot spontaneously emits **~66** (counted across all
  sessions). The rest are request/set-only (e.g. `MULTI_MAP`, `GET_CARPET`) or never
  triggered in our captures. See "Never-seen notable DPs" section at the bottom.

## Live cleaning state (changes during a run)

| DP | code | observed | meaning |
|---|---|---|---|
| `STATUS` | dpStatus | 3,6,7,8,10,12,22,101,103,104,105 | device state enum (`YXDeviceState`). **Full table** (all 11 values observed across all sessions ✅): `3`=idle, `6`=returning_home, `7`=remote_control_active, `8`=charging, `10`=paused, `12`=error, `22`=emptying_the_bin, `101`=relocating, `103`=mopping, `104`=sweep_and_mop (also used for leaving-dock transition, ~2 s), `105`=transitioning. Sequence for a start+stop+return: 8→104→101→104→10→3→6→8. |
| `BATTERY` | dpBattery | 58–66 | battery %. ✅ drained ~0.4%/min while mopping. |
| `CLEAN_PROGRESS` | dpCleanProgress | 26–37 | **% of current job complete (0–100)**. ✅ monotonic. Now surfaced in `status`/`watch`. |
| `CLEAN_AREA` | dpCleanArea | 38–50 | **swept** area this run, m² — distance-swept × lane-width, NOT floor footprint. ✅ Cross-checked: latest path polyline 256m × ~0.2m lane ≈ 51 m² ≈ CLEAN_AREA 50, inside an ~18 m² room (path bbox). Counts overlap + the 2 passes (CLEAN_COUNT=2). |
| `CLEAN_TIME` | dpCleanTime | 3762–5070 | **task clock, seconds**, ticks ~1/sec. ✅ pauses when docked; flatline while mopping = stall signal. |
| `FAULT` | dpFault | 0 | active fault code; 0 = none. **Decode table = `B01Fault` enum, which ships in the library's *Q7* module (`roborock.data.b01_q7.b01_q7_code_mappings`) — the Q10 module defines `FAULT=("dpFault",90)` but does NOT import `B01Fault`, so vac.py currently shows raw ints.** Codes seen against a live device: **501=`F_501 robot_suspended`** ("move robot away & restart; wipe cliff sensors" — HIGH conf, matches a cliff-trip halt mid-clean); **570** = table says `F_570 main_brush_entangled` but that CONTRADICTS our observation (570 fired on an *unreachable* room @ 0 m²; the table's `F_2007/F_2012 cannot_reach_target` fits far better) → **this firmware may map 570 differently; do NOT trust the label** until validated; **400** = absent from table (≈`F_407 cleaning_in_progress`, likely benign/transient); **8** w/ STATUS=12 = ambiguous, not a 3-digit B01 fault. Useful neighbours: 500=lidar_blocked, 509=cliff_sensor_error, 510=bumper_stuck, 513/514=robot_trapped, 560=side_brush_entangled, 2007/2012=cannot_reach_target, 2102=cleaning_complete. **Future vac.py win:** import `B01Fault` from the q7 module to decode `status` faults (validate a few codes first per the 570 mismatch). |

## Consumables = HOURS OF USE ✅ (confirmed vs app, 2026-06-12)

| DP | code | observed | meaning |
|---|---|---|---|
| `MAIN_BRUSH_LIFE` | dpMainBrushLife | 6 | **hours of use** ⬆. App % remaining = (300−h)/300 (lifetime 300 h). 6 h → 98%. |
| `SIDE_BRUSH_LIFE` | dpSideBrushLife | 6 | hours used; lifetime **200 h**. 6 h → 97%. |
| `FILTER_LIFE` | dpFilterLife | 6 | hours used; lifetime **150 h**. 6 h → 96%. |
| `SENSOR_LIFE` | dpSensorLife | 6 | hours used; app shows sensor/mop/dust "as needed" (no fixed lifetime → no %). |

> **Confirmed:** the DP value = hours used, matching the app's Settings→Maintenance
> "N h" exactly; % remaining = `(lifetime − hours)/lifetime` with lifetimes
> main 300 h / side 200 h / filter 150 h. `vac.py consumables` now shows "N h · M% left".

## Lifetime totals (constant within a run)

| DP | code | observed | meaning |
|---|---|---|---|
| `TOTAL_CLEAN_AREA` | dpTotalCleanArea | 114→198 | lifetime m² cleaned. ✅ **updates at job end, not mid-run** — jumped 114→198 (+84) after today's mop docked. |
| `TOTAL_CLEAN_COUNT` | dpTotalCleanCount | 10→11 | lifetime number of cleans. ✅ +1 after today's run. |
| `TOTAL_CLEAN_TIME` | dpTotalCleanTime | 204→351 | lifetime minutes cleaned. ✅ +147min (≈2.45h) = today's run length. |
| `CLEAN_COUNT` | dpCleanCount | 2 | passes per area for *this* job (2 = clean-twice), not a room count. ❓ |

## Settings (mirror app toggles; stable unless changed)

> **Writing** these very likely works: action commands proved the write path
> is fine; the earlier "settings didn't reflect" was a read-back artifact (these settings
> aren't in the live-modeled status, so they were read from a stale `COMMON` snapshot).
> To *prove* a specific setting, use `volume` (audible) or check the app.

| DP | code | observed | meaning |
|---|---|---|---|
| `FAN_LEVEL` | dpFanLevel | 8 | suction. 8 = max_plus (`YXFanLevel`). ✅ |
| `WATER_LEVEL` | dpWaterLevel | 3 | mop water. 3 = high (`YXWaterLevel`). ✅ |
| `CLEAN_MODE` | dpCleanMode | 1–4, 6 | clean mode enum. The REST /jobs `cleanMode` param uses `YXCleanType` (1=vac_and_mop, 2=vacuum, 3=mop, 4=customized); the MQTT DP uses `YXDeviceWorkMode` (same codes 1–4, plus 5=save_worry, **6=sweep_mop** — sweep entire flat first, then mop). Codes 1–4 are numerically identical between both enums. **Code 6 observed** (user cycling modes in app, STATUS=8/charging). ✅ |
| `VOLUME` | dpVolume | 55 (current) | voice volume 0–100. **☁ CLOUD-AUTHORITATIVE** (settled): `vac.py volume 70` accepted, MQTT echo returns 55. The server stores the preference and re-asserts it; MQTT write is overridden. Settable via app only. ✅ |
| `CHILD_LOCK` | dpChildLock | 0 | 0/1. App toggle ON/OFF confirmed ✅ (echo 0→1→0). **☁ CLOUD-AUTHORITATIVE — confirmed against a live device:** `child-lock on` accepted but CHILD_LOCK echo stayed 0 (server re-asserts stored value), same as VOLUME/AUTO_BOOST. |
| `AUTO_BOOST` | dpAutoBoost | 0 | carpet auto-boost 0/1. **☁ CLOUD-AUTHORITATIVE** (same as VOLUME — settled; re-confirmed against a live device: `boost on` echo stayed 0): earlier "CLI write didn't land" was real behaviour, not a confound. Server re-asserts stored value. App toggle confirmed ✅. ✅ |
| `NOT_DISTURB` | dpNotDisturb | 1 | DND enabled 0/1. **☁ CLOUD-AUTHORITATIVE — confirmed against a live device:** `dnd off` accepted but NOT_DISTURB stayed 1 (never dropped to 0); `NOT_DISTURB_DATA` (the `dnd on` payload) never echoed. So BOTH CLI dnd paths are ineffective — the server owns this stored preference. Set via app. |
| `NOT_DISTURB_EXPAND` | dpNotDisturbExpand | dict | DND sub-flags (dust/light/resume/voice). |
| `DUST_SWITCH` | dpDustSwitch | 1 | auto-empty enabled 0/1. ❓ |
| `DUST_SETTING` | dpDustSetting | 0 | auto-empty frequency. `YXDeviceDustCollectionFrequency`: **DAILY=0**, INTERVAL_15/30/45/60. Value 0 = daily ✅ |
| `MOP_STATE` | dpMopState | 1 | mop pad attached/engaged 0/1. ❓ |
| `MAP_SAVE_SWITCH` | dpMapSaveSwitch | true | persist map between runs. |
| `MULTI_MAP_SWITCH` | dpMultiMapSwitch | 1 | multi-floor maps enabled. |
| `CLEAN_LINE` | dpCleanLine | 2 | route pattern. `YXCleanLine`: FAST=0, DAILY=1, **FINE=2** ✅ |
| `BREAKPOINT_CLEAN` | dpBreakpointClean | 0 | resume-after-charge armed 0/1. ❓ |
| `VALLEY_POINT_CHARGING` | dpValleyPointCharging | false/true | off-peak charging enabled (bool). ❓ toggled by user |
| `VALLEY_POINT_CHARGING_DATA_UP` | dpValleyPointChargingDataUp | base64 | off-peak charging window — **same 6-byte format as `NOT_DISTURB_DATA`**: `[flag:u8, startH:u8, startM:u8, endH:u8, endM:u8, 0]`. Observed: 22:00–08:00, 22:00–01:00, 01:00–01:00. Flag byte 0xFC in all observed samples (0x00 may mean disabled, matching NOT_DISTURB_DATA pattern). ❓ flag semantics |
| `LINE_LASER_OBSTACLE_AVOIDANCE` | — | 1 | obstacle avoidance on 0/1. |
| `CARPET_CLEAN_TYPE` | dpCarpetCleanType | 0 | carpet handling mode. ❓ |
| `GROUND_CLEAN` | dpGroundClean | 0 | ❓ |
| `BACK_TYPE` | dpBackType | 5 | return-to-dock reason. `YXBackType`: IDLE=0, **BACK_DUSTING=4** (✅ now observed against a live device, during auto-empty on dock return), **BACK_CHARGING=5** ✅ |
| `CLEAN_TASK_TYPE` | dpCleanTaskType | 1 | `YXDeviceCleanTask`: IDLE=0, **SMART=1** (full auto), ELECTORAL=2 (room select), DIVIDE_AREAS=3, CREATING_MAP=4, PART=5 ✅ |
| `ADD_CLEAN_STATE` | dpAddCleanState | 0 | second-pass / add-clean active. ❓ |
| `TIMER_TYPE` | dpTimerType | 1 | schedule kind. ❓ |
| `AREA_UNIT` | dpAreaUnit | 1 | 1 = m² (vs ft²). ✅ explains m² area. |

## Spatial & map-config formats (decoded, read-only over MQTT)

**Provenance:** decoded from a monitored app session (2026-06-12) where the user
drew/edited each feature and the robot echoed it on its OUTPUT topic. **`_UP` DPs are device→app *reports*** — reading them is ✅ confirmed.
**SETTING any of these is 🔒 blocked** (round-trip test 2026-06-12: 4 send variants for
`VIRTUAL_WALL` never changed the wall count — the real write command rides the MQTT INPUT
topic the broker won't let us subscribe to; same root cause as room-select cleaning).
**Coordinate frame:** **stored values are in 0.5 mm units — multiply by 2 to get path mm.**
Wall binary order is `(y,x)` (confirmed: gives vertical lines matching app display). Zone/carpet
coords are `(x,y)`. Use `_mm_to_pixel(..., coord_scale=2)` — baked into `decode_map.py`.
Calibrated via two known walls (master/living boundary + kitchen/living diagonal); k≈1.98 from
both axes (DESIGN_NOTES.md). ✅ = decode confirmed, 🟡 = inferred/partial.

| DP | format (decoded) | provenance / confidence |
|---|---|---|
| `VIRTUAL_WALL_UP` | base64 `[count:u8]` + per wall `(y1,x1,y2,x2)` BE int16 (mm). ⚠ byte order is **(y,x)** not (x,y) — confirmed empirically vs app display. e.g. wall (y=-809,x=-834)→(y=-814,x=-1152). `decode_map.py:parse_virtual_walls` parses this correctly. | Drew 2 walls → count 1→2. ✅ decode confirmed · 🔒 set blocked |
| `RESTRICTED_ZONE_UP` | base64 `[0x01][count:u8]` + per zone: `[type:u8][nverts:u8=4]` + 4×`(x,y)` BE int16 + 20B zero-pad = 38 B/zone. **type values observed:** `0x00`=no-go rect; `0x02`=🟡 unknown rect; `0x03`=🟡 door-threshold (thin rotated quad ~70×220mm). **`0x01` (no-mop, inferred) not yet observed in RESTRICTED_ZONE_UP** — may live in ZONED_UP or a separate DP. `load_dp_overlay` currently filters want_type=0x00 for no-go and 0x01 for no-mop (may need revision once 0x01 is captured). | Captured 3 zones: one 0x00, one 0x02, one 0x03 (2026-06-13 raw dump). ✅ decode · 🔒 set blocked |
| `ZONED_UP` | base64 **same scheme as `RESTRICTED_ZONE_UP`**: `[0x01][count:u8]` + per zone: `[type:u8][nverts:u8=4]` + 4×`(x,y)` BE int16 (mm). type=0x01 → cleaning zone. `AQAA`=empty (count=0). | ✅ format confirmed (multi-record verify: 17B→2 walls, 25B→3 walls cross-validated). `decode_map.py:parse_restricted_zones` handles both. 🔒 set blocked |
| `CARPET_UP` | JSON `{data:[{id, rug_clean_mode, vertexs:[[x,y]×4]}], op:"list"}`; write echoes `{op:"save",result:1}`. coords (x,y) in mm. | Drew a 200×200 mm carpet (id 101). ✅ decode · 🔒 set |
| `FLOOR_MATERIAL` | base64 `[01][n_rooms:u8]` + per room `(room_id:u8, material:u8)`. Material = `YXRoomMaterial`: 0=horiz-floorboard, 1=vert-floorboard, **2=ceramic tile**, **255=other**. | User toggled room 6 tile↔other; confirmed 2=tile / 255=other. ✅ confirmed |
| `RESET_ROOM_NAME` | base64 `[01][room_id:u8][00][namelen:u8][name…]`. | Renamed room 2 → "Test". ✅ decode · 🔒 set |
| `ROOM_SPLIT` / `ROOM_MERGE` | scalar ack (`=1`); the geometry change is in the regenerated grid, not a coord DP. | Split room 2. ✅ observed · 🔒 set |
| `REMOVE_ZONED_UP` | `{op:"save",result:1}` (ack). | Removed a zone. ✅ |
| `RESTRICTED_AREA_UP` / `CLIFF_RESTRICTED_AREA_UP` / `SUSPECTED_THRESHOLD_UP` | base64 list (presumed same scheme). | All stayed `[]` (unused — thresholds went to RESTRICTED_ZONE). 🟡 |
| `CLEAN_RECORD` | `{data:[<underscore-string per clean>], op:...}`. **Format FULLY CRACKED (22-record corpus):** 12 underscore fields, 0-indexed: `0:id`(16-char opaque) · `1:epoch`(clean START, unix sec UTC; +TZ=local) · **`2:duration_MINUTES`** · `3:f3`(~0.55×dur; likely effective/mop minutes, med conf) · `4:f4`(slow device accumulator — **NOT duration**, low conf) · **`5:area_m²×1000`** (12053→12.05 m²) · **`6:t1`**(monotonic accumulator/sequence counter — **NOT fan level**; the old "4=fan MAX" was coincidence; ignore for display) · `7:water`(YXWaterLevel) · `8:mode`(YXCleanType) · `9:route`(YXCleanLine) · **`10:pass_count`**(1 or 2 — NOT a constant) · `11:ok`(1 done / 0 aborted). Example `…_1781226271_27_19_6692_12053_4_00_02_01_1_1` = started 2026-06-11 21:04, **27 min, 12.05 m²**, water off, vacuum-only, daily route, 1 pass, completed. **Fetch mechanism (for a future `vac.py history`):** send `CLEAN_RECORD` with **`op:"list"`** → robot replies with the full `data[]` history array (12–18 records); **`op:"notify"`** = single live "clean finished" event (coincides with `TOTAL_CLEAN_COUNT`+1); `op:"select"`/`op:"delete"` = per-record detail/delete acks. | ✅ format + fetch cracked (corrects prior duration_sec/t1/pass-count guesses) |
| `CLEAN_EXPAND` | dpCleanExpand | `{room_id_list:[ids]}` or `{}` | Robot's **echo of the room selection for the current job** (a report, not a command). Appears at clean start for ELECTORAL task type. e.g. `{"room_id_list":[1]}` = robot is cleaning room 1. `{}` = full-home clean (no selection). ✅ seen in live captures |
| `CUSTOMER_CLEAN` | dpCustomerClean | base64 blob (440–504 B) | **Room directory** — same per-room record format as the map's trailing block: `[count:u8]` + N×47B records (id + name). Appears once per session on request. Already read more reliably from the LZ4 map via `vac.py rooms`. ✅ |
| `ADD_CLEAN_AREA` | dpAddCleanArea | `AQAA` (base64) | "Add clean area" request or ack. `AQAA` = `[0x01, 0x00, 0x00]`. Appears once after a partial/interrupted clean. Function unclear — possibly signals "resumable clean area available". ❓ |
| `NOT_DISTURB_DATA` | base64 packed bytes `[flag, startH, startM, endH, endM, ?]` (read). `[0,22,0,8,0,0]` = 22:00–08:00. (`cmd_dnd` *writes* a JSON dict — write path unconfirmed.) | ✅ read decode |
| `TIMER` | base64; observed minimal `[1,252,0,0]` (no schedule set). | 🟡 format unknown |
| `MULTI_MAP` | `{op:"list"}` → map list `[{id,name,timestamp}]`; `{op:"notify"}` on edits. The `0101` grid arrives as protocol-301, NOT here (see below). | ✅ read; **op-sends DO reach the robot** (unlike walls) → rename/select ops may be settable (untested) |
| `RECENT_CLEAN_RECORD` | bool; per-run history flag (false unless requested). | ✅ |

## Map & position — MQTT protocol 301 (NOT a dps DP)

The robot **spontaneously publishes `map_response` (protocol 301) binary frames** — no
request needed. These are NOT `dps` frames, so `watch`/`watch --raw` never see them (the
dps decoder drops them). Use **`vac.py map`** (one-shot capture + render), or `watch
--bytes` + `decode_map.py` for the raw stream. Two sub-types, keyed by the first 8 header
bytes — note they have **different availability**: the room grid streams **even while
docked**, but the path/position only streams **during an active clean** (confirmed
2026-06-12):

| sub-type (hdr[:8]) | size | meaning | status |
|---|---|---|---|
| `0201000800020000` | ~23KB | **cleaning path** — 16B header (bytes 8-9 = point count), then big-endian int16 (x,y) pairs. Last point = **robot's current position**; first ≈ dock. **Units = mm** (confirmed: polyline 256m × 0.2m lane ≈ CLEAN_AREA). Path is decimated (≈20mm median vertex spacing) so it's reliable for route + position, but cumulative length underestimates true travel → don't derive cruise speed from it. | ✅ decoded |
| `0101<map-id><ver>` | ~7.7KB | **room/occupancy grid — LZ4-compressed** (not RLE). declared size=bytes[25:27] BE; comp len=bytes[27:29] BE; LZ4 block from byte 29. Decompresses to a **222×261** grid (`pixel//4 = room_id`; 243=outside, 249=wall) + trailing room records (`[0x01,count]` then count×47B; name = byte26 len + bytes27..). **Decoded + rendered** by `decode_map.py` → `map_rooms.png` + `map_overlay.png` (colour-coded, labeled, path overlaid). Our capture: 7 named rooms. NB: header bytes[8:10]=478 is a LE u16 but NOT the grid width — real width is byte[8]=222 alone; bytes 10–24 are constant metadata that does NOT encode bounding-box coordinates. **Georeference (solved 2026-06-12):** `col=(path_y+3307)//20`, `row=(1001−path_x)//20`; row-axis is y-inverted. Score 99.87 % (constants stable while dock position unchanged). | ✅ decoded + rendered + georeferenced |

### Obstacles are NOT in the map data (checked 2026-06-12)
AI-recognized obstacles (cable/shoe/pet icons + photos in the app) are **cloud-side**,
fetched by the app over HTTPS — they never touch the MQTT stream. Verified: no obstacle
301 sub-type; grid pixels are only room/wall(249)/outside(243); the trailing block is the
coverage mask; and the SCMap protobuf (`RobotMap`) has no obstacle/object field at all.
Permanent obstacle *geometry* is baked into the grid as wall cells, but the semantic
layer (type + photo) is cloud-only. Aside: the SCMap `MapHeadInfo` (on-demand RPC only)
carries `resolution` + `minX/maxX/minY/maxY` = clean grid↔mm georeference.

## Identity / environment (constant)

| DP | observed | meaning |
|---|---|---|
| `NET_INFO` | `{ip:192.0.2.x, mac:AA:BB:CC:DD:EE:FF, signal:-48, ssid:<your-ssid>}` (placeholders; real values scrubbed) | wifi info. Control is cloud-only, but the local IP is reachable for presence/ping. |
| `TIME_ZONE` | `America/New_York, -14400s` | device TZ. |
| `OFFLINE` | dpOffline | 0 | online/offline flag; 0 = online. One of the 11 DPs in the REST Shadow endpoint (`GET /devices/{duid}/shadow`) — appears there alongside STATUS/BATTERY/etc. ✅ |
| `ROBOT_COUNTRY_CODE` | `us` | region. |
| `ROBOT_TYPE` | 1 | model class. |
| `VOICE_VERSION` / `VOICE_LANGUAGE` | 4 / 104 | voice pack version / language id. Language codes from `/app/talc/voice-pkg/info`: 1=zh-CN, 2=zh-TW, 3=en, 101=ko, 102=ru, 103=de, **104=es**, 105=fr, 106=it, 108=ja, 109=uk, 110=he, 111=pl, 112=ro, 113=id, 114=th, 115=vi, 116=pt, 117=ms, 118=es-LA. This device has Spanish voice (104). ✅ |
| `USER_PLAN` | 0 | cloud subscription tier. |

## REST Shadow endpoint — compact status without MQTT

`GET /devices/{duid}/shadow` (Hawk-authenticated, same as /jobs) returns 11 DPs in a
single REST call, no MQTT session needed. Fields (numeric code → name):

| code | DP name | example |
|---|---|---|
| 135 | OFFLINE | 0 |
| 121 | STATUS | 8 |
| 122 | BATTERY | 97 |
| 123 | FAN_LEVEL | 8 |
| 125 | MAIN_BRUSH_LIFE | 6 |
| 126 | SIDE_BRUSH_LIFE | 6 |
| 127 | FILTER_LIFE | 6 |
| 136 | CLEAN_COUNT | 1 |
| 137 | CLEAN_MODE | 1 |
| 138 | CLEAN_TASK_TYPE | 0 |
| 139 | BACK_TYPE | 5 |

Could back a `vac.py status --quick` that skips device_session setup (no MQTT connect,
no waiting for status frames). Subset of what `status` shows but much faster. ❓ untested.

## Never-seen notable DPs (48 total; most are command/write-only)

DPs in the enum that never appeared in any of our 7 capture files. Grouped by likely reason:

**Command-only** (we send them, robot never echoes them — expected): `START_CLEAN`, `START_BACK`, `START_DOCK_TASK`, `PAUSE`, `RESUME`, `STOP`, `SEEK`, `REMOTE`, `RESET_*`, `REQUEST*`, `MAP_RESET`, `REMOVE_ZONED`, `VIRTUAL_WALL`, `RESTRICTED_ZONE`, `ZONED`, `GET_CARPET`, `SELF_IDENTIFYING_CARPET`, `ROOM_MERGE`, `ROOM_SPLIT`, `JUMP_SCAN`, `COMMON`, `REQUEST_DPS`.

**Interesting — may appear under specific conditions:**

| DP | code | When it might appear |
|---|---|---|
| `RAG_LIFE` | 23 | Mop rag hours used — may only emit if the optional mop rag accessory is registered with the dock |
| `CLEANING_PROGRESS` | 141 | **Different DP from `CLEAN_PROGRESS`** (code 87). Never emitted — possibly a newer firmware field or triggered only on demand |
| `FLEEING_GOODS` | 142 | Obstacle-avoidance status — may only emit when the robot is actively avoiding an object |
| `TASK_CANCEL_IN_MOTION` | 132 | Fires when a job is cancelled while the robot is mid-move |
| `CREATE_MAP_FINISHED` | 94 | Fires once when a mapping run completes |
| `DEVICE_INFO` | 34 | Full device info blob — request-only |
| `VOICE_PACKAGE` | 35 | Current voice pack info — request-only |
| `HEARTBEAT` | 110 | Keepalive — never echoed on output topic |
| `CARPET_CLEAN_PREFER` | 44 | Carpet mode preference — may not emit until carpet mode is configured |
| `BUTTON_LIGHT_SWITCH` | 77 | Physical button LED toggle |
| `CUSTOM_MODE` | 39 | Per-room custom settings — may require custom mode active |
| `LOG_SWITCH` | 84 | Debug logging toggle |
| `UNIT` | 42 | Unit system (possibly same as AREA_UNIT, or a legacy alias) |
| `VALLEY_POINT_CHARGING_DATA` | 107 | Write-side of VALLEY_POINT_CHARGING_DATA_UP (set the window) |

## Open questions

- **Map units/origin:** ✅ RESOLVED (2026-06-12). Path is mm; grid↔path georeference confirmed
  at 99.87 % (see DESIGN_NOTES.md). `map_overlay.png` produced by `decode_map.py`.
- **`CLEAN_RECORD` t1 field — RESOLVED:** NOT fan level. Across 22 chronologically-sorted records it is strictly non-decreasing (4→12→154→192→230) and identical for cleans with different fan/water/mode/area → a **monotonic accumulator / sequence counter**, not a per-clean parameter. The "4=fan MAX" reading was coincidence. Exact unit still open (record-sequence or runtime tick) but it is definitively not a clean attribute. See the corrected `CLEAN_RECORD` row above.
- **`CLEAN_RECORD` f2/f3:** unknown fields at positions 2-3. Not duration, not area. Possibly room_count and segment_count or obstacle encounter count.
- **`CLEANING_PROGRESS` (code 141):** never seen — what triggers it vs `CLEAN_PROGRESS` (87)?
- **`VALLEY_POINT_CHARGING_DATA_UP` flag byte:** 0xFC in all observed samples. Meaning unknown.
- **`AREA_UNIT=0`:** seen once (2026-06-12T22:13:40, STATUS=8). Presumably ft² but single sample only.
- **`CLEAN_LINE`, `BACK_TYPE`, `CLEAN_TASK_TYPE`, `BREAKPOINT_CLEAN`:** ✅ meanings confirmed from enum; `BACK_TYPE`=5 (BACK_CHARGING) in normal docking, and **=4 (BACK_DUSTING) confirmed against a live device** during the auto-empty cycle on dock return. `CLEAN_TASK_TYPE`=2 confirmed live = room/segment clean (vs 1=full).
