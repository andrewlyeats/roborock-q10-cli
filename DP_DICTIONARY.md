# Data-point dictionary (B01 / Q10 S5+)

> **As of:** 2026-06-16 · Q10 S5+ (`roborock.vacuum.ss07`), firmware 03.11.24 · `python-roborock` 5.14.2.
> Best-effort/due-diligence as of this date. The readable overview + method live in **[PROTOCOL.md](PROTOCOL.md)**;
> this is the detailed drill-down.

What each data-point (DP) the robot emits **actually means**, built by observing
live runs (first captured 2026-06-12) and cross-referencing `B01_Q10_DP` in the library.

**Confidence key** (standardised across rows):
**✅ Confirmed** (behavioural/round-trip proof, our HW; cite session) · **🟡 Plausible** (inferred from
structure/naming, no counter-evidence, not independently triggered) · **❓ Reported** (third-party source,
cited, unverified here) · **⬜ Unknown** (seen, opaque). Confirmed rows should carry a firmware+session
anchor (e.g. `fw 03.11.24, s22`).

> **Migration note (2026-06-16):** earlier rows used a *legacy* `❓` to mean "our own untested
> hypothesis." Under the key above `❓` now means **Reported (third-party)** only, so those legacy
> markers have been reclassified per-row to **🟡** (named/structural inference) or **⬜** (opaque). If you
> see a stray bare `❓` that isn't paired with a cited external source, treat it as 🟡/⬜ pending review.

- **Observed** = value(s) actually seen in the feed (a range, or the constant value).
- **Meaning** = inferred per the confidence key above (some rows also use ⬆/⬇ to note a value's direction).
- The catalog has **114** DPs; the robot spontaneously emits **~66** (counted across all
  sessions). The rest are request/set-only (e.g. `MULTI_MAP`, `GET_CARPET`) or never
  triggered in our captures. See "Never-seen notable DPs" section at the bottom.

## Live cleaning state (changes during a run)

| DP | code | observed | meaning |
|---|---|---|---|
| `STATUS` | dpStatus | 3,6,7,8,10,12,22,29,101,102,103,104,105 | device state enum (`YXDeviceState`); all 13 values observed ✅. `8`=charging, `3`=idle, `6`=returning, `12`=error, `22`=emptying-bin, `29`=mapping; the `102/103/104` active-clean states are mode-specific. **Full table, the state sequences, and the openHAB cross-ref → [STATUS detail](#status-detail) below.** |
| `BATTERY` | dpBattery | 58–66 | battery %. ✅ drained ~0.4%/min while mopping. |
| `CLEAN_PROGRESS` | dpCleanProgress | 26–37 | **% of current job complete (0–100)**. ✅ monotonic. Now surfaced in `status`/`watch`. |
| `CLEAN_AREA` | dpCleanArea | 38–50 | **swept** area this run, m² — distance-swept × lane-width, NOT floor footprint. ✅ Cross-checked: latest path polyline 256m × ~0.2m lane ≈ 51 m² ≈ CLEAN_AREA 50, inside an ~18 m² room (path bbox). Counts overlap + the 2 passes (CLEAN_COUNT=2). |
| `CLEAN_TIME` | dpCleanTime | 3762–5070 | **task clock, seconds**, ticks ~1/sec. ✅ pauses when docked; flatline while mopping = stall signal. |
| `FAULT` | dpFault | 0 | active fault code; 0 = none. **⚠️ OVERLOADED — also carries lifecycle/state codes, so a non-zero FAULT is NOT necessarily an error** ✅ `s22` (e.g. `400`=benign "starting clean", `8`=trapped, `501`=cliff-suspended). Decoded best-effort via the library's `B01Fault`, always with raw-code passthrough. **Full code table, the `B01Fault` caveat, and the openHAB cross-ref → [FAULT detail](#fault-detail) below.** |
| `SUSPECTED_THRESHOLD_UP` | — | `[]` | **s23 (new).** Appeared at clean start; value an empty list when no threshold flagged. Threshold-detection related — surfaced in the same run as a `501 robot_suspended` (cliff/threshold) trip. Likely a list of suspected threshold locations/edges; needs samples with a non-empty value to decode. |
| `CLIFF_RESTRICTED_AREA_UP` | — | `[]` | **s23 (new).** Appeared at clean start alongside `SUSPECTED_THRESHOLD_UP`; empty list when none. Cliff-sensor "restricted area" reporting (no-go edges the robot detected). Needs a non-empty sample. |
| `ADD_CLEAN_AREA` | — | `"AQAA"` | **s23/s24.** Appears at the **fault-RECOVERY moment** (right around each transient 501). Base64 → bytes `01 00 00`, and it is **CONSTANT across s23+s24** (never any other value) → a **flag/marker** (robot re-adding clean area after an interruption), NOT a varying counter. |
| `FLOOR_MATERIAL` | — | `[]` | Per-room floor material. **Format already cracked** (CAPABILITIES: `[01][n](room_id, material)`, `YXRoomMaterial` 2=tile/255=other, confirmed by toggling room 6; SET blocked). Seen `[]` in the s23/s24 captures (none set then). |

### STATUS detail

**Full table** (`YXDeviceState`; all 13 values observed across all sessions ✅): `3`=idle, `6`=returning_home,
`7`=remote_control_active, `8`=charging, `10`=paused, `12`=error, `22`=emptying_the_bin, `101`=relocating,
`102`=vacuuming, `103`=mopping, `104`=sweep_and_mop (also the ~2 s leaving-dock transition), `105`=transitioning,
`29`=active mapping.

- **Sequences.** Start+stop+return: `8→104→101→104→10→3→6→8`. s22 scheduled-clean→abort→dock:
  `8→104`(undock)`→6`(cleaning)`→[dock]→22`(bin auto-empty)`→104/105/101`(returning)`→12→8`(charging) — re-confirms
  `22`=emptying_the_bin (matched the app's "dock vacuum clean") and `8`=charging.
- **s24 — STATUS↔CLEAN_MODE mapping nailed** (ran each mode deliberately): the active-clean status is
  **mode-specific** → CLEAN_MODE `1` (vac_and_mop)=`104`, `2` (vacuum)=`102`, `3` (mop)=`103`. The `6`/`101`/`105`
  values are the surrounding returning/relocating/transition states.
- **s26 — `29` = active MAPPING** (quick-map): seen throughout a live "build a new map" run (robot off dock, growing
  the `0101` grid) — a distinct mapping state, not a clean state.
- ⚠️ `6` also appeared during the ACTIVE-clean phase (between undock and dock), which sits oddly with the
  `6=returning_home` label — `6` may be a generic working state. Flagged for review.
- ❓ **Reported cross-ref** (openHAB `roborock` binding, `api/enums/StatusType.java`, 2026-06-16): their status enum
  (a *classic Roborock-protocol* table, **not** confirmed to be the B01 `YXDeviceState`) lists
  `3=IDLE, 6=RETURNING, 8=CHARGING, 10=PAUSED, 12=ERROR, 22=EMPTYING_BIN, 29=MAPPING` — **independently corroborating**
  our labels for those codes. It diverges where B01 is its own thing: openHAB `101=OFFLINE` (we observe relocating),
  no `102/104/105` (our mode-specific states; openHAB *does* define `103=LOCKED`, which we never see) — so the 100-range
  is B01-specific. The alignment is the evidence, the divergence is the open edge. (openHAB — see [CREDITS.md](CREDITS.md).)

### FAULT detail

**Decode table = the library's `B01Fault` enum**, which ships in the **Q7** module
(`roborock.data.b01_q7.b01_q7_code_mappings`) — the Q10 module defines `FAULT=("dpFault",90)` but does **not** import
it. `vac.py cmd_status` decodes via `B01Fault[f"F_{code}"]` (imported from `roborock`) and prints the **raw code in
parens when non-zero**; because the table lacks `8`/`400` and remaps others, decoding is best-effort — **keep the raw
passthrough.**

**⚠️ The FAULT DP is OVERLOADED** — it carries normal lifecycle/state codes as well as genuine faults, so a non-zero
FAULT is **not** necessarily an error. Codes seen against a live device:

- **`8` = robot trapped** ✅ s22 — app push *"Robot trapped. Clear away any obstacles…"* at the same timestamp,
  co-occurring with STATUS=12. This firmware reports trapped as `8`, **not** the library's `513/514 robot_trapped`
  (a firmware remap).
- **`400` = benign "Starting scheduled cleanup"** ✅ s22 — a lifecycle/START code, **not** a fault (≈`F_407
  cleaning_in_progress`). Do not present it as an error.
- **`501` = `F_501 robot_suspended`** — cliff-trip/threshold halt mid-clean; s23 reconfirmed it self-cleared in ~16 s
  and the robot still finished the clean (a 501 does not necessarily abort).
- **`570`** — the table says `F_570 main_brush_entangled`, but that **contradicts** our observation (570 fired on an
  *unreachable* room @ 0 m²; `F_2007/F_2012 cannot_reach_target` fits far better) → **do not trust the 570 label**
  until validated.

Both `8` and `400` are absent from `B01Fault`; they were decoded by lining iOS pushes (phone-clock − "Nm ago") up
against timestamped tap frames. Library neighbours for reference: `500`=lidar_blocked, `509`=cliff_sensor_error,
`510`=bumper_stuck, `513/514`=robot_trapped, `560`=side_brush_entangled, `2007/2012`=cannot_reach_target,
`2102`=cleaning_complete. **Remaining win:** build an empirical code→meaning table (decode live codes via app pushes),
since the q7 table is incomplete and this firmware remaps some codes.

- ❓ **Reported cross-ref** (openHAB `roborock` binding, `api/enums/VacuumErrorType.java`, 2026-06-16): their error
  table (a *classic-protocol* enum, ≠ B01 `B01Fault`) reads **`8 = "Device stuck"`** — **corroborating our s22
  `FAULT=8 = trapped`** from an independent source (and matching it better than `513/514`). It tops out near
  `56/254/255` and has **none** of our `400`/`501`/`570`, reinforcing those as B01-specific. Neighbours: `4`=Cliff
  sensor fault, `5`=Main brush blocked, `24`=No-go/invisible wall, `28`=Robot on carpet, `254`=Bin full. Treat as a
  labelling cross-check, not B01 ground truth. (openHAB — see [CREDITS.md](CREDITS.md).)

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
| `CLEAN_COUNT` | dpCleanCount | 2 | passes per area for *this* job (2 = clean-twice), not a room count. ✅ `s24` — `--count 2` ran ~2× the duration of a single pass (behavioural confirmation that the count = pass repetitions). |

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
| `DUST_SWITCH` | dpDustSwitch | 1 | auto-empty enabled 0/1. 🟡 (name + 0/1 value; not toggled to verify) |
| `DUST_SETTING` | dpDustSetting | 0 | auto-empty frequency. `YXDeviceDustCollectionFrequency`: **DAILY=0**, INTERVAL_15/30/45/60. Value 0 = daily ✅ |
| `MOP_STATE` | dpMopState | 1 | mop pad attached/engaged 0/1. 🟡 (name inference; no detach test) |
| `MAP_SAVE_SWITCH` | dpMapSaveSwitch | true | persist map between runs. |
| `MULTI_MAP_SWITCH` | dpMultiMapSwitch | 1, 4 | multi-floor maps. **s26 (live): observed = `4` right after toggling multi-level ON in-app — so NOT a simple bool; the earlier `1` was a guess. `4`=multi-level enabled; off-value/other semantics uncaptured. Settable via this DP.** |
| `CLEAN_LINE` | dpCleanLine | 2 | route pattern. `YXCleanLine`: FAST=0, DAILY=1, **FINE=2** ✅ |
| `BREAKPOINT_CLEAN` | dpBreakpointClean | 0 | resume-after-charge armed 0/1. 🟡 (name inference) |
| `VALLEY_POINT_CHARGING` | dpValleyPointCharging | false/true | off-peak charging enabled (bool). 🟡 (observed flip false↔true when the user toggled it in-app; semantics inferred from name + the decoded `_DATA_UP` window) |
| `VALLEY_POINT_CHARGING_DATA_UP` | dpValleyPointChargingDataUp | base64 | off-peak charging window — **same 6-byte format as `NOT_DISTURB_DATA`**: `[flag:u8, startH:u8, startM:u8, endH:u8, endM:u8, 0]`. Observed: 22:00–08:00, 22:00–01:00, 01:00–01:00. Flag byte 0xFC in all observed samples (0x00 may mean disabled, matching NOT_DISTURB_DATA pattern). ✅ window format · ⬜ flag-byte semantics |
| `LINE_LASER_OBSTACLE_AVOIDANCE` | — | 1 | obstacle avoidance on 0/1. |
| `CARPET_CLEAN_TYPE` | dpCarpetCleanType | 0 | carpet handling mode. 🟡 (name inference; only the constant `0` seen, never varied) |
| `GROUND_CLEAN` | dpGroundClean | 0 | ⬜ opaque — only the constant `0` seen; no inferable meaning beyond the name. |
| `BACK_TYPE` | dpBackType | 5 | return-to-dock reason. `YXBackType`: IDLE=0, **BACK_DUSTING=4** (✅ now observed against a live device, during auto-empty on dock return), **BACK_CHARGING=5** ✅ |
| `CLEAN_TASK_TYPE` | dpCleanTaskType | 1 | `YXDeviceCleanTask`: IDLE=0, **SMART=1** (full auto), ELECTORAL=2 (room select), DIVIDE_AREAS=3, CREATING_MAP=4, PART=5 ✅ |
| `ADD_CLEAN_STATE` | dpAddCleanState | 0 | second-pass / add-clean active. 🟡 (name inference; pairs with `ADD_CLEAN_AREA`) |
| `TIMER_TYPE` | dpTimerType | 1 | schedule kind. 🟡 (name inference; not cross-referenced to a set timer) |
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
| `RESTRICTED_ZONE_UP` | base64 `[0x01][count:u8]` + per zone: `[type:u8][nverts:u8=4]` + 4×`(x,y)` BE int16 + 20B zero-pad = 38 B/zone. **type values (s26 GROUND-TRUTH — drew each, watched the echo):** `0x00`=no-go rect; **`0x02`=no-mop rect (CONFIRMED — drew a no-mop, it returned type `0x02`, NOT the `0x01` we'd inferred)**; `0x03`=door-threshold (thin rotated quad ~70×220mm). **`parse_restricted_zones` FIXED s26:** zones are in FIXED 38-B slots (the old tight-packed parse mis-read a no-go's zero-pad as a 2nd empty zone when count>1, and missed the real next zone); `load_dp_overlay` now uses want_type=`0x02` for no-mop. | Captured 0x00+0x02 live (s26) + 0x03 (2026-06-13). ✅ decode (count>1 fixed s26) · 🔒 set blocked |
| `ZONED_UP` | base64 **same scheme as `RESTRICTED_ZONE_UP`**: `[0x01][count:u8]` + per zone: `[type:u8][nverts:u8=4]` + 4×`(x,y)` BE int16 (mm). type=0x01 → cleaning zone. `AQAA`=empty (count=0). | ✅ format confirmed (multi-record verify: 17B→2 walls, 25B→3 walls cross-validated). `decode_map.py:parse_restricted_zones` handles both. 🔒 set blocked |
| `CARPET_UP` | JSON `{data:[{id, rug_clean_mode, vertexs:[[x,y]×4]}], op:"list"}`; write echoes `{op:"save",result:1}`. coords (x,y) in mm. | Drew a 200×200 mm carpet (id 101). ✅ decode · 🔒 set |
| `FLOOR_MATERIAL` | base64 `[01][n_rooms:u8]` + per room `(room_id:u8, material:u8)`. Material = `YXRoomMaterial`: 0=horiz-floorboard, 1=vert-floorboard, **2=ceramic tile**, **255=other**. | User toggled room 6 tile↔other; confirmed 2=tile / 255=other. ✅ confirmed |
| `RESET_ROOM_NAME` | base64 `[01][room_id:u8][00][namelen:u8][name…]`. | Renamed room 2 → "Test". ✅ decode · 🔒 set |
| `ROOM_SPLIT` / `ROOM_MERGE` | scalar ack (`=1`); the geometry change is in the regenerated grid, not a coord DP. | Split room 2. ✅ observed · 🔒 set |
| `REMOVE_ZONED_UP` | `{op:"save",result:1}` (ack). | Removed a zone. ✅ |
| `RESTRICTED_AREA_UP` / `CLIFF_RESTRICTED_AREA_UP` / `SUSPECTED_THRESHOLD_UP` | base64 list (presumed same scheme). | All stayed `[]` (unused — thresholds went to RESTRICTED_ZONE). 🟡 |
| `CLEAN_RECORD` | `{data:[<underscore-string per clean>], op:...}` — 12 underscore fields per clean (`id·epoch·`**`duration_min`**`·f3·f4·`**`area×1000`**`·t1·water·mode·route·`**`pass`**`·ok`); **format cracked over a 22-record corpus.** The remaining open part is the live **fetch** (`op:list` is app/push-only). **Full field map, worked example, and the fetch RE → [CLEAN_RECORD detail](#clean_record-detail) below.** | ⚠️ format cracked; **live fetch still UNSHIPPED** |
| `CLEAN_EXPAND` | dpCleanExpand | `{room_id_list:[ids]}` or `{}` | Robot's **echo of the room selection for the current job** (a report, not a command). Appears at clean start for ELECTORAL task type. e.g. `{"room_id_list":[1]}` = robot is cleaning room 1. `{}` = full-home clean (no selection). ✅ seen in live captures |
| `CUSTOMER_CLEAN` | dpCustomerClean | base64 blob (440–504 B) | **Room directory** — same per-room record format as the map's trailing block: `[count:u8]` + N×47B records (id + name). Appears once per session on request. Already read more reliably from the LZ4 map via `vac.py rooms`. ✅ |
| `ADD_CLEAN_AREA` | dpAddCleanArea | `AQAA` (base64) | "Add clean area" marker. `AQAA` = `[0x01, 0x00, 0x00]`, **constant across s23+s24** — appears at the fault-RECOVERY moment (around each transient 501), so it reads as a flag, not a varying counter. Exact function ⬜ (see the fuller entry in *Live cleaning state* above). |
| `NOT_DISTURB_DATA` | base64 packed bytes `[flag, startH, startM, endH, endM, ?]` (read). `[0,22,0,8,0,0]` = 22:00–08:00. (`cmd_dnd` *writes* a JSON dict — write path unconfirmed.) | ✅ read decode |
| `TIMER` | base64; observed minimal `[1,252,0,0]` (no schedule set). | 🟡 format unknown |
| `MULTI_MAP` | `{op:"list"}` → map list `[{id,name,timestamp}]`; `{op:"update"}`/`{op:"notify"}` on edits. The `0101` grid arrives as protocol-301, NOT here. **s26 op surface CONFIRMED (captured the app doing each, live): `list` / `update`(rename: id+timestamp stable, only name changes) / `select`({id,name}); `delete` inferred (not captured). Map `id` ≈ creation unix-epoch. Multi-level (`MULTI_MAP_SWITCH=4`) PRESERVES existing maps — built a new map alongside the old.** | ✅ read + ops observed live → a `map rename/select/delete` CLI is buildable (ROADMAP) |
| `RECENT_CLEAN_RECORD` | bool; per-run history flag (false unless requested). | ✅ |

### CLEAN_RECORD detail

**Field map** (12 underscore fields, 0-indexed; cracked over a 22-record corpus):
`0:id` (16-char opaque) · `1:epoch` (clean START, unix sec UTC; +TZ=local) · **`2:duration_MINUTES`** ·
`3:f3` (~0.55×dur; likely effective/mop minutes, med conf) · `4:f4` (slow device accumulator — **not** duration,
low conf) · **`5:area_m²×1000`** (12053 → 12.05 m²) · **`6:t1`** (monotonic accumulator/sequence counter —
**not** fan level; the old "4=fan MAX" reading was coincidence) · `7:water` (YXWaterLevel — 🟡 *mode-correlated*
across 22 records, not write-verified: vacuum→0, vac_mop→{0,1,3,4}, mop→{0,1}; value **`4` exceeds the YXWaterLevel
max (3)** — an unconfirmed possible 4th/custom level) · `8:mode` (YXCleanType) · `9:route` (YXCleanLine — 🟡
corpus-inferred) · **`10:pass_count`** (1 or 2) · `11:ok` (1 done / 0 aborted).

**Worked example.** `…_1781226271_27_19_6692_12053_4_00_02_01_1_1` = started 2026-06-11 21:04, **27 min, 12.05 m²**,
water off, vacuum-only, daily route, 1 pass, completed.

**Fetch RE (the open part — blocks a live `vac.py history`).** `op:"list"` → the robot replies with the full
`data[]` history (12–18 records); `op:"notify"` = a single live "clean finished" event (coincides with
`TOTAL_CLEAN_COUNT`+1); `op:"select"`/`op:"delete"` = per-record detail/delete acks.
- **s23 — `op:list` is not pull-able by us:** `command.send(CLEAN_RECORD,{op:list})` got no reply across 2 sessions,
  while the identical `command.send(MULTI_MAP,{op:list})` works (the `map` command uses it). The captured `op:list`
  `data[]` replies were almost certainly **app-triggered pushes** → CLEAN_RECORD `op:list` looks **push-only**
  (robot→app, post-clean / history-screen), not pull-able like MULTI_MAP.
- **s26 — mitm'd the history screen:** the trigger is **MQTT, not REST** (the proxy saw no history endpoint);
  opening an entry = `op:"select"` (ack only, no data). A CLI `op:"list"` fired with the app **closed** got no reply
  in 45 s → bare `op:list` is **definitively insufficient.** Only path left = a transparent MQTT MITM (:8883) to
  capture the app's exact publish.

## Map & position — MQTT protocol 301 (NOT a dps DP)

The robot **spontaneously publishes `map_response` (protocol 301) binary frames** — no
request needed. These are NOT `dps` frames, so `watch`/`watch --raw` never see them (the
dps decoder drops them). Use **`vac.py map`** (one-shot capture + render), or `watch
--bytes` + `decode_map.py` for the raw stream. Two sub-types, keyed by the **first 2 header
bytes** (`0x0101` grid / `0x0201` path) — note they have **different availability**: the
room grid streams **even while docked**, but the path/position only streams **during an
active clean** (confirmed 2026-06-12):

| sub-type | size | summary (full byte spec → [FRAME_ANATOMY.md](FRAME_ANATOMY.md)) | status |
|---|---|---|---|
| `0x0201` path | ~23KB | 16B header (bytes 8-9 = point count), then BE int16 (x,y) **mm** pairs; last point = **robot position**, first ≈ dock; decimated (~20mm vertices) so it's reliable for route/position but cumulative length underestimates true travel → don't derive speed. *(example header `0201000800020000`; bytes 2-7 vary per clean.)* | ✅ decoded |
| `0x0101` grid | ~7.7KB | LZ4-compressed occupancy grid (`pixel//4=room_id`, 243=outside, 249=wall) + trailing room-name records; W/H read from the header; byte `[6]` = map-finalized flag. **Rendered** by `decode_map.py` → `map_rooms.png` + `map_overlay.png` (colour-coded, labeled, path overlaid). *(our main single-floor map: 222×261 px, 7 named rooms — varies per home; example header `0101<map-id><ver>`, bytes 2-5 = per-map id.)* | ✅ decoded + rendered + georeferenced |

**→ Full byte-level decode is single-sourced in [FRAME_ANATOMY.md](FRAME_ANATOMY.md)** — every offset, the
declared/compressed-size fields, the 47-byte room-record layout, the W/H `424/424` and byte-`[6]` `89/89`
verifications, the `raw[11:25]` sub-structure, the historical `bytes[8:10]`-as-LE→`478` correction, and the
georeference algorithm + per-install origin (≈99.87 % on-floor fit). Machine-checkable header
schema: [frames.ksy](frames.ksy). *(This dictionary catalogs DPs; the frame format lives there so it has one
home.)*

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
no waiting for status frames). Subset of what `status` shows but much faster. 🟡 (the 11 Shadow fields are ✅ from a live Shadow `GET`; the proposed `status --quick` path itself is untested).

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
  - ❓ **Reported cross-reference (openHAB roborock binding, `api/dto/GetCleanRecord.java`, source-verified 2026-06-16):** their `Result` DTO declares, **in order**: `begin, end, duration, area, error, complete, start_type, clean_type, finish_reason, dust_collection_status, avoid_count, wash_count, map_flag, cleaned_area, manual_replenish, dirty_replenish, clean_times`. **Caveat — this is the *classic-protocol JSON* DTO, a different SERIALIZATION from our B01 underscore string, so the order will NOT line up positionally.** Use it only as a vocabulary of *candidate meanings* for our still-unknown positions: our `f3` (~0.55×dur) and `f4` (slow accumulator) are plausibly a second time/`finish_reason`/`avoid_count`; our `f6` monotonic accumulator could be `map_flag` or a sequence id. **Verify against our positional decode before promoting any to ✅.** Note their DTO has no explicit `water`/`route`/`pass` ints (which our B01 string carries at f7/f9/f10), confirming the two formats are not a relabel of each other. (openHAB binding — see [CREDITS.md](CREDITS.md).)
- **`CLEANING_PROGRESS` (code 141):** never seen — what triggers it vs `CLEAN_PROGRESS` (87)?
- **`VALLEY_POINT_CHARGING_DATA_UP` flag byte:** 0xFC in all observed samples. Meaning unknown.
- **`AREA_UNIT=0`:** seen once (2026-06-12T22:13:40, STATUS=8). Presumably ft² but single sample only.
- **`CLEAN_LINE`, `BACK_TYPE`, `CLEAN_TASK_TYPE`, `BREAKPOINT_CLEAN`:** ✅ meanings confirmed from enum; `BACK_TYPE`=5 (BACK_CHARGING) in normal docking, and **=4 (BACK_DUSTING) confirmed against a live device** during the auto-empty cycle on dock return. `CLEAN_TASK_TYPE`=2 confirmed live = room/segment clean (vs 1=full).
