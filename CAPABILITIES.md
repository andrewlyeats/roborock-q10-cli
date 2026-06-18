# Capability matrix — Roborock Q10 S5+ (B01)

> **As of:** 2026-06-16 · firmware 03.11.24 · `python-roborock` 5.14.2. Best-effort/due-diligence as of this
> date. Readable overview + confidence key: **[PROTOCOL.md](PROTOCOL.md)**.

Every interaction the robot exposes (all 114 `B01_Q10_DP` data-points + library traits),
scoped by what we can and can't do — built from live testing + source/web research.

**Legend.** This table tracks a **capability axis** (can / can't / untested) — *distinct* from the
4-tier **confidence** key in [PROTOCOL.md](PROTOCOL.md) (Confirmed / Plausible / Reported / Unknown).
The glyphs are not the same scheme: here 🟡 means "needs RE/testing," **not** the confidence key's
🟡 "Plausible." (`🔒` set-blocked and `☁` cloud-authoritative, used below and in DP_DICTIONARY, are
orthogonal status markers on top of either axis.)
- ✅ **Confirmed** — tested live, works.
- 🟢 **Available** — exposed + mechanism proven (same path as a ✅), untested but should work.
- 🟡 **Unknown/untested** — needs reverse-engineering or testing (payload/format unclear).
- 🔴 **Not possible** — architectural limit, not exposed, or cloud-only.

How to drive anything: `./vac.py <verb>` for built-ins, or `./vac.py raw <DP_NAME> '<json>'`
for anything else (fire-and-forget). Reads come back on the MQTT stream, not as a return.

---

## 🔴 Architectural limits (can't be done this way, ever)
| Want | Why not |
|---|---|
| Local / LAN control | B01 is **cloud-MQTT only** — no local TCP port. Every command is a cloud round-trip. |
| Obstacle objects + photos | **This model has no camera** (lidar + structured-light only) — so AI-classified obstacles (cable/shoe/pet) and obstacle photos **don't exist at all**, not just "cloud-only." Structured-light avoidance reports presence/height, no imagery. |
| Map georeference for free | The on-demand `MULTI_MAP` returns the same `0101` grid, NOT the Q7 SCMap with `MapHeadInfo` (resolution/origin). Must derive the transform ourselves. |
| Live obstacle/dirt events | Same cloud-side boundary. |

---

## Cleaning control (actions)
| Interaction | DP / method | Status | Notes |
|---|---|---|---|
| Start full clean | `START_CLEAN {cmd:1}` / `vacuum.start_clean()` | ✅ | "smart" auto clean; robot undocks. |
| Pause | `PAUSE` / `pause_clean()` | ✅ | reflects in status immediately. |
| Resume | `RESUME` / `resume_clean()` | ✅ | resumes the paused clean. |
| Stop | `STOP` / `stop_clean()` | ✅ | halts an active clean — catch it before it commits to docking (once it's returning, it may finish). |
| Return to dock | `START_DOCK_TASK {}` / `return_to_dock()` | ✅ | → returning_home → charging. |
| Empty dustbin (dock) | `START_DOCK_TASK 2` / `empty_dustbin()` | ✅ | dock auto-empty; loud, no robot motion. |
| Locate beep | `SEEK {}` / `vac.py find` | ✅ | plays a locate beep (audible only — not machine-verifiable). |
| Manual drive | `REMOTE` via `remote.{forward,left,right,stop}` | 🔴 app-only | CLI `drive` sends are **inert** (no STATUS change, never STATUS=7, no motion); the **app** drives fine. `REMOTE` rides the **blocked input topic** (same wall as settings / walls-SET) — not honored over our channel. Path forward = MITM the app's drive frames. |
| Room / segment clean | one-time `POST /jobs` `rooms:[…]` (REST) | ✅ validated live | `./vac.py clean-rooms <name\|id>…` — correct room targeting confirmed live; `--fan`/`--water`/`--route`/`--count` take effect on the wire; `--dry-run` posts a *disabled* job (safe). A COMPLETE cycle (undock→clean→bin-empty→dock+charging) is validated. |
| Zone / spot clean | `CUSTOMER_CLEAN` / `CUSTOMER_CLEAN_REQUEST` | 🟡 / observed as PART | App spot-clean runs a **PART** clean (`CLEAN_TASK_TYPE=5`) that needs a successful relocalize. `CUSTOMER_CLEAN` isn't echoed (app input topic, like `REMOTE`); CLI payload unknown — a coord-bearing zone clean would leave the kitchen, untested. |
| Add-area clean | `ADD_CLEAN_AREA` / `ADD_CLEAN_STATE` | 🟡 state readable | State reads back: `ADD_CLEAN_AREA` = base64 `[01 00 00]` (no area set), `ADD_CLEAN_STATE` = 0. SET needs an area-coord payload — not tested (coord-less is uninformative; a coord-bearing one leaves the kitchen). |
| Cancel in motion | `TASK_CANCEL_IN_MOTION` | 🟡 (no-op) | Sent mid-clean — **did NOT cancel** (clean continued); no effect via bare `command.send`. App-only or unknown payload. |
| Start "back" task | `START_BACK` | 🟡 (no-op) | **No observable effect** — `raw START_BACK` bare or `--common`; robot stayed idle. Likely app-only / unknown payload. |
| Misc | `BEAK_CLEAN`, `JUMP_SCAN`, `GROUND_CLEAN` | 🟡 (no-op) | Each sent during an active clean — **no observable effect**; bare send doesn't engage them (app-only / unknown payload). `GROUND_CLEAN` is also a readable state DP (`0`). |

## Settings (writes)

> **Settled:** `volume`/`auto_boost`/`child_lock` are **☁ cloud-authoritative**
> — the server stores user preferences and re-asserts them after any MQTT write.
> `fan`/`water`/`mode` work normally because they are runtime
> session parameters (not stored user preferences). See DESIGN_NOTES.md.
>
>
> **CLI honesty:** `vac.py volume`/`child-lock`/`boost` now print a
> "cloud may revert this — change it in the app to persist" caveat after the success line,
> so the CLI no longer implies the write stuck. (Code: `CLOUD_REVERT_NOTE` in vac.py.)

| Setting | DP / verb | Status | Notes |
|---|---|---|---|
| Fan / suction | `FAN_LEVEL` / `vac.py fan` | ✅ | quiet…max_plus. **Persists** — session/runtime param, not cloud-overridden. |
| Water level | `WATER_LEVEL` / `vac.py water` | ✅ | off…high. **Persists.** |
| Clean mode | `CLEAN_MODE` / `vac.py mode` | ✅ | vac/mop/vac+mop. **Persists.** |
| Voice volume | `VOLUME` / `vac.py volume` | ☁ cloud-authoritative | CLI send accepted; server re-asserts stored value. Set via app only. |
| Child lock | `CHILD_LOCK` / `vac.py child-lock` | ☁ cloud-authoritative | App toggle works; `child-lock on` accepted but server re-asserts. Set via app. |
| Carpet auto-boost | `AUTO_BOOST` / `vac.py boost` | ☁ cloud-authoritative | CLI write doesn't land; app toggle works. Set via app. |
| Do-not-disturb | `NOT_DISTURB` / `NOT_DISTURB_DATA` / `vac.py dnd` | ☁ cloud-authoritative | **Both CLI paths are ineffective** — the server owns this stored preference (same bucket as volume/child-lock/boost). Set via app. |
| Auto-empty on/off | `DUST_SWITCH` | ☁ | MQTT write didn't change it — **cloud-authoritative, app-only**. |
| Auto-empty frequency | `DUST_SETTING` | ☁ | daily / interval_15…60; MQTT write didn't stick — set in app. |
| Route pattern | `CLEAN_LINE` | ☁ / ✅ per-clean | global MQTT write didn't stick (cloud-auth) — **but the route IS settable per clean** via `clean-rooms --route fast\|daily\|fine`. |
| Passes per area | `CLEAN_COUNT` | ✅ | **settable live** — a runtime cleaning param (same bucket as fan/water/mode), **not** a cloud-stored pref. Also settable per-clean via `clean-rooms --count`. |
| Carpet handling | `CARPET_CLEAN_TYPE` / `CARPET_CLEAN_PREFER` / `SELF_IDENTIFYING_CARPET` | ☁ | `CARPET_CLEAN_TYPE` write didn't stick; the other two aren't reported even in a full `REQUEST_DPS` dump. Cloud-authoritative — set in app. |
| Obstacle avoidance | `LINE_LASER_OBSTACLE_AVOIDANCE` / `IGNORE_OBSTACLE` | ☁ | `LINE_LASER…` write didn't stick; `IGNORE_OBSTACLE` not reported. Cloud-authoritative — set in app. |
| Resume-after-charge | `BREAKPOINT_CLEAN` | ☁ | MQTT write didn't stick — cloud-authoritative, set in app. |
| Off-peak charging | `VALLEY_POINT_CHARGING` / `VALLEY_POINT_CHARGING_DATA` | ☁ | write didn't stick. `…_DATA_UP` readable (base64 window blob `[FC 19 00 19 00 00]`). Set in app. |
| Map persistence | `MAP_SAVE_SWITCH` / `MULTI_MAP_SWITCH` | ☁ | `MAP_SAVE_SWITCH` write didn't stick; set in app. `MULTI_MAP_SWITCH` reads `4` (multi-map enabled). |
| Voice pack / language | `VOICE_PACKAGE` / `VOICE_LANGUAGE` | ☁ (read ✅) | `VOICE_LANGUAGE`/`VOICE_VERSION` readable. SET **not tested** — changing voice pack/language can trigger a firmware voice-pack download; deliberately not exercised. App-only assumed. |
| Units | `UNIT` / `AREA_UNIT` | ☁ | `AREA_UNIT` write didn't stick; `UNIT` not reported. Cloud-authoritative — set in app. |
| Dock button light | `BUTTON_LIGHT_SWITCH` | ☁ | MQTT write didn't stick; dock-LED ground-truth not yet eyeballed. |
| Logging | `LOG_SWITCH` | ☁ (unverifiable) | Not reported even in a full `REQUEST_DPS` dump — no read-back channel; app-only assumed (same cluster as the other stored prefs). |
| Room targeting | `CLEAN_EXPAND` | ✅ read | JSON `{"room_id_list":[…]}` — echoes the active clean's target rooms. |
| Misc / unclear | `CUSTOM_MODE`, `CLEAN_ORDER`, `FLEEING_GOODS`, `SUSPECTED_THRESHOLD` | 🟡 | not reported / unused — semantics unknown. (`FLOOR_MATERIAL` is decoded read-only — see Map & spatial.) |

## Maintenance (consumable counter resets)
| Interaction | DP | Status | Notes |
|---|---|---|---|
| Reset main brush | `RESET_MAIN_BRUSH` | 🟢 (untested by choice) | resets the used-counter; do after physical replacement. **Not exercised** — firing it would falsely zero a real consumable's life counter. |
| Reset side brush / filter / sensor / rag | `RESET_SIDE_BRUSH` / `RESET_FILTER` / `RESET_SENSOR` / `RESET_RAG_LIFE` | 🟢 (untested by choice) | same — would corrupt maintenance tracking; deliberately not fired. |
| Reset / set room name | `RESET_ROOM_NAME` | 🔒 read-only | it's the room-rename DP (see Map & spatial) — decoded, but SET blocked like other map edits. |
| ⚠️ Reset map | `MAP_RESET` | 🟡 untested | **destructive** — wipes the saved map; never tested (may be blocked like other map writes). Avoid. |

## Map & spatial
| Interaction | DP | Status | Notes |
|---|---|---|---|
| Get room/wall map | `MULTI_MAP` (+ 301 stream) | ✅ | LZ4 grid, 7 rooms decoded → `vac.py map`. |
| Robot position + path | 301 `0201` stream | ✅ | live during cleaning only. |
| Carpet / no-mop zone | `GET_CARPET` / `CARPET_UP` | 🔒 read-only | JSON `{id,rug_clean_mode,vertexs:[[x,y]×4]}` — decoded; SET blocked. |
| Virtual wall | `VIRTUAL_WALL` / `_UP` | 🔒 read-only | **READ format cracked** (`[count][x1,y1,x2,y2]` BE int16); **SET blocked** — write rides the blocked input topic. |
| No-go / no-mop / restricted zone | `RESTRICTED_ZONE` / `_UP` | 🔒 read-only | decoded (rectangles, mm); also holds no-mop + thresholds. SET blocked (same as walls). |
| Floor material | `FLOOR_MATERIAL` | 🔒 read-only | `[01][n](room_id,material)`; `YXRoomMaterial` (2=tile, 255=other); SET blocked. |
| **Room split** | `ROOM_SPLIT` | 🔒 read-only | **observed**; SET blocked. |
| Room rename | `RESET_ROOM_NAME` | 🔒 read-only | `[01][id][namelen][name]` — decoded; SET blocked. |
| **Room merge / combine** | `ROOM_MERGE` | 🟡 not yet done | inferred read-only like split. |
| Restricted area / cliff area | `RESTRICTED_AREA` / `CLIFF_RESTRICTED_AREA` (+`_UP`) | 🟡 unused | not drawn. |
| Door thresholds | `SUSPECTED_THRESHOLD` / `_UP` | 🟡 unused | thresholds drawn in-app went into `RESTRICTED_ZONE` instead. |
| Map-build event | `CREATE_MAP_FINISHED` | 🟡 event-only | fires on a map-build completion. |

## Map management (inferred from the iOS app UI — not yet captured/tested)
Recorded from what the app *offers*; the robot must support these. Most are structured
map-mutations → expected **read-only** over MQTT (write command unobservable, like walls).
`MAP_SAVE_SWITCH` **tested as cloud-authoritative** (write didn't stick); `MULTI_MAP_SWITCH` write
untested (same stored-pref bucket, presumed ☁). Our own `MULTI_MAP` op-sends get **no reply** (only the
*app's* `op:list` is observed, captured passively; see the Map list row), so even `op:list` isn't a working
PULL for us, and the other `op`s (rename/select/delete) are unproven — likely the same blocked input topic.


| App feature | likely DP | inferred status |
|---|---|---|
| Combine / merge rooms | `ROOM_MERGE` | 🔒 read-only (structured, like `ROOM_SPLIT`) |
| Cleaning sequence (room order) | `CLEAN_ORDER` | 🟡 unknown (structured; maybe a settable order list) |
| Map rename | `MULTI_MAP {op:rename?}` | 🟡 unknown — settability unproven |
| Map delete | `MAP_RESET` / `MULTI_MAP {op:delete?}` | 🟡 unknown — ⚠️ destructive, don't test casually |
| Set map as home / select | `MULTI_MAP {op:select?}` | 🟡 unknown |
| Toggle map saving | `MAP_SAVE_SWITCH` | ☁ cloud-auth — MQTT write didn't stick |
| Single- vs multi-level home | `MULTI_MAP_SWITCH` | ☁ likely — reads `4`; write untested (same stored-pref bucket) |
| Map list | `MULTI_MAP {op:list}` | ✅ read (passive) | **Broadcast-only:** the robot answers the *app's* `op:list`, not ours. **Watching while the app opens the map screen captures the full list** (each map's `id`+`name`+`timestamp`). Our own `op:list` PULL still gets no reply. So map *enumeration* is readable passively even though CLI map-switch isn't. |
| 90° CW map rotation (map screen) | (no clear DP) | 🟡 likely an app *display* transform; if it persists server-side it may relate to the path/grid orientation twist seen in georeferencing |

## Scheduling
| Interaction | DP / method | Status | Notes |
|---|---|---|---|
| List cloud schedules | REST GET `/user/devices/{duid}/jobs` | ✅ | `./vac.py schedule list` works. Hawk auth via `rriot`. |
| Enable / disable / delete / add | REST PUT/DELETE/POST same endpoint | ✅ | Write path confirmed (Hawk body-signing fix). `vac.py schedule enable/disable/delete/add` all live. |
| On-device schedule | `TIMER` / `REQUEST_TIMER` / `TIMER_TYPE` | 🟡 readable | `TIMER` reads as a base64 4-byte blob `[01 FC 00 00]`, `TIMER_TYPE`=`1` — encoding identified (base64-binary, like walls); full field decode still open. Fallback if REST writes stay blocked. |
| Host cron | `./vac.py start` via system cron | ✅ alt | simplest path for "clean daily at 10 AM" — no REST write needed. |

## Connection / daemon
The cloud broker rate-limits new MQTT CONNECTs (account-level `code 135`), which knocks out the CLI
*and* the phone app. Fixed architecturally — a long-running **daemon holds ONE MQTT connection** and
serves the CLI over a Unix socket. See [DESIGN_NOTES.md](DESIGN_NOTES.md).

| Interaction | How | Status | Notes |
|---|---|---|---|
| Single-connection daemon | `./vac.py daemon start [--careful]` / `stop` / `restart` / `status` | ✅ | Holds one `DeviceManager`; the CLI uses it by default (`--force` runs standalone). `--careful` halts on the first 135/auth complaint and is **preserved across `restart`**. |
| Telemetry taps | `./vac.py daemon record --events/--novel/--bytes F` | ✅ | In-process fan-out over the one held connection → **zero extra cloud connections/subscriptions**. `--bytes` captures raw 301 map/path frames. |
| Live stream | `./vac.py watch [--raw\|--bytes] [--out F]` | ✅ | Streams the daemon event bus to stdout/file; watchers reaped promptly on client disconnect. |
| 135 recovery | escalating backoff → `needs_login` | 🟢 | offline-tested; not yet exercised by a *natural* live 135. Don't provoke. |

## Reads / telemetry (all ✅ — see DP_DICTIONARY.md)
Every data-point in [DP_DICTIONARY.md](DP_DICTIONARY.md) reads back on the MQTT stream — state, totals,
consumables, environment, and plumbing (`REQUEST_DPS` / `HEARTBEAT` / `COMMON`). Notables:
- ✅ **Clean history** — `CLEAN_RECORD` is a per-clean underscore string (`<id>_<unixtime>_…_<flags>`;
  12 fields: dur_min / area / mode / pass / ok solid, 7 = water, 6 = a monotonic accumulator).
  **`./vac.py history --from-capture <watch.jsonl>`** decodes the back-catalog **offline**. (The live
  `op:list` PULL gets no reply — the robot push/broadcasts the list to the app, not to us.)
- ✅ **STATUS is mode-specific while cleaning** — `102`=vacuuming, `103`=mopping, `104`=sweep_and_mop
  (= CLEAN_MODE 2 / 3 / 1); `22`=dock auto-empty, `8`=charging. See DP_DICTIONARY STATUS row.
- ✅ `RECENT_CLEAN_RECORD` — a boolean "a recent clean exists" flag (distinct from the `CLEAN_RECORD` list).
- 🔴 `DEVICE_INFO` — never sent over MQTT (REST/app-only).
- The robot reports ~60 of the 114 catalog DPs on request; the rest are set-only or never triggered. A few
  structured blobs are decoded (`CLEAN_EXPAND` / `NOT_DISTURB_EXPAND` JSON; `TIMER`, `NOT_DISTURB_DATA`,
  `ADD_CLEAN_AREA`, `VALLEY_POINT_CHARGING_DATA_UP` are base64-binary, same family as walls/zones).

---

## Open frontier — and the one thing that would unblock it

Everything above is ✅ working or 🔒/☁ scoped. What's genuinely **open** is a single class, all behind the
same wall:

- **Set walls / no-go & no-mop zones / room split-merge-rename** — read formats fully decoded, but the SET
  command rides the app's **MQTT input topic** we can't see (4 self-send variants didn't engage).
- **Manual drive** (`REMOTE`) — built (`vac.py drive`) but **inert from the CLI**; the app drives fine. Same
  input topic.
- **Live `history` pull** — the back-catalog decodes offline today (`history --from-capture`); a *live* trigger
  is app/push-only.

All three are gated on the same thing: the app's **MQTT input (write) topic**, which an HTTPS proxy can't see.
The technique that would crack them is a **transparent `:8883` MQTT MITM** (WireGuard/iptables TLS interception)
— see [PROTOCOL.md](PROTOCOL.md) (Method & provenance). Everything reachable *without* it — the full read
surface, the per-DP write-path behaviour, the map/history decode — is done.
