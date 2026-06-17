# Roborock Q10 (B01) cloud protocol — reverse-engineering reference

> **As of:** 2026-06-16 · **Hardware:** Roborock Q10 S5+ (`roborock.vacuum.ss07`, B01 protocol), firmware
> **03.11.24** · **Stack:** `python-roborock` 5.14.2, Python 3.11 · **Method:** on-device HTTPS proxy +
> single-connection MQTT tap, with a timestamped operator log (see [Method & provenance](#method--provenance)).
>
> This is an **unofficial, reverse-engineered** reference — not a vendor spec. Findings are **best-effort and
> due-diligence as of the date above**; behaviour may differ on other models or firmware. Every claim carries a
> confidence tier (below). Corrections and contradictions are welcome — see [Open questions](#open-questions).

This page is the **readable hub**. The detailed tables live in their own files and are linked as drill-downs:
- **[DP_DICTIONARY.md](DP_DICTIONARY.md)** — every data-point: meaning + decoded wire format + confidence.
- **[CAPABILITIES.md](CAPABILITIES.md)** — every interaction, scoped can / can't / unknown.
- **[DESIGN_NOTES.md](DESIGN_NOTES.md)** — why it works this way; the deeper RE narrative.
- **[frames.ksy](frames.ksy)** — machine-readable Kaitai schema for the map-frame headers (drop your own
  capture into the [Kaitai Web IDE](https://ide.kaitai.io/) to verify/extend against your device).

## Confidence key

Every entry in this reference and the linked tables is tagged:

| Tier | Meaning |
|---|---|
| ✅ **Confirmed** | Round-trip or behavioural proof on our hardware/firmware (cited session). |
| 🟡 **Plausible** | Inferred from protocol structure or analogy; no counter-evidence, not independently triggered. |
| ❓ **Reported** | From a third-party project/source (cited); **not** independently verified here. |
| ⬜ **Unknown** | Observed but semantics undetermined. |

Confirmed entries also carry a **firmware + session anchor** (e.g. `fw 03.11.24, s22`) — that's both the proof
and the staleness signal: if your firmware is newer, treat it as advisory.

## Overview

The Q10 S5+ is a **"B01" device: cloud-only.** There is no local-network control path (confirmed — see
[local control](DESIGN_NOTES.md#why-cloud-only)); every command is relayed through Roborock's cloud over **MQTT**, with a
**REST** API for onboarding, schedules, and one-time room cleans. The live map/path arrives as a spontaneous
binary **MQTT protocol-301** stream while cleaning. ✅ `fw 03.11.24, s5–s26`

## Transport

| Channel | Use | Confidence |
|---|---|---|
| **REST** (`api-us.roborock.com` / `usiot.roborock.com`) | onboarding, home/device data, `/jobs` (schedules + one-time room cleans) | ✅ `s16,s26` |
| **MQTT** (cloud broker, TLS) | all live control + status; the device's output topic broadcasts to any subscribed client | ✅ `s21–s26` |
| **MQTT protocol-301** (binary, spontaneous while cleaning) | map grid + cleaning path frames | ✅ `s5–s26` |

<details><summary>The account-level <code>135</code> rate-limit (and why the daemon exists)</summary>

Many MQTT connections in a short window trip an account-level error **`135`** ("Not Authorized" on reconnect[^135]) that
locks out the CLI *and* the app. Holding **one** persistent connection sidesteps it — that's the single-connection
daemon. ✅ `s20–s24`. No other surveyed project treats 135 as a deliberate-avoidance design (see [CREDITS.md](CREDITS.md) for the landscape).
</details>

## Authentication — Hawk, and the write-path body-signing

REST requests are **Hawk**-signed. The pre-string is seven colon-joined fields; the last is the **payload-hash
slot**. GET signs it empty (works); **body-bearing writes (POST/PUT) to `/jobs` must put `md5(compact-JSON
body)` there, and must SEND those exact compact bytes** — re-serialization with spaces breaks the MAC → `401`.
This is why writes (schedules, room cleans) failed until we cracked it. ✅ `s16` — reproduced the app's captured
`PUT` MAC exactly; filed upstream as [python-roborock#849](https://github.com/Python-roborock/python-roborock/issues/849).
GET and `DELETE /jobs/{id}` (no body) are unaffected.

```
prestr = u : s : nonce : ts : md5(path) : md5(sorted-params) : md5(compact-json body)   # last slot empty for GET
```
*(Captured-evidence excerpt is in DESIGN_NOTES, with auth/identity redacted per the privacy floor.)*

## Data points (DP model)

State and control ride **`device.b01_q10_properties`** → `.command` / `.vacuum` / `.status` / `.remote`. DP
names + numeric codes are in `roborock/data/b01_q10/b01_q10_code_mappings.py` (`B01_Q10_DP`, plus the `YX*` value
enums). **The full decoded DP reference — meanings, payload formats, confidence — is [DP_DICTIONARY.md](DP_DICTIONARY.md)**
(~114 DPs; the most complete public B01-Q10 reference we're aware of). Highlights:
- Settings split: `fan`/`water`/`mode` **persist**; `volume`/`child-lock`/`boost`/`DND` are **cloud-authoritative**
  (CLI sends, cloud reverts). ✅ `s20,s24`
- `FAULT` is **overloaded** — it also carries lifecycle codes (`8`=trapped, `400`=benign "starting clean"); a
  non-zero FAULT is not necessarily an error. ✅ `s22`
- `CLEAN_RECORD` history is a 12-field underscore string (`op:list`); the live *pull* trigger is app-only
  (MQTT, not our `op:list`). ✅ format `s20–s24`; ⬜ live-pull trigger.
- Multi-map: `MULTI_MAP` ops `list`/`update`(rename)/`select`; `MULTI_MAP_SWITCH=4` = multi-level on; map id ≈
  creation epoch. ✅ `s26`

## Map frames (protocol-301)

**Full walkthrough — a map building itself, the decode pipeline, and typed per-byte field tables:
[FRAME_ANATOMY.md](FRAME_ANATOMY.md).** Header layout (machine-checked): [frames.ksy](frames.ksy).
Two sub-types, by the first 2 header bytes.
- **`0101` — room/occupancy grid.** LZ4-compressed. Grid **W/H read from the header** (`raw[7:9]`,`raw[9:11]`
  BE u16 — verified == empirical on 424/424 frames); `pixel//4=room_id`, `243`=outside, `249`=wall; trailing
  room-name records. ✅ `s5,s25`. Header byte `[6]` is a **map-segmented/finalized flag** (`0` while
  building, `1` once rooms exist — verified 89/89 on a from-scratch build, `s26`). 🟡
- **`0201` — cleaning path.** BE int16 `(x,y)` mm pairs after a 16-byte header; last point = robot position. ✅ `s6`
- **Georeference** (path mm → grid pixel): the origin is **not transmitted**; we **auto-fit** it per capture
  (it's stable per home, anchored top-right, grows left/down). ✅ `s25,s26`. Others use manual-tune
  calibration. ❓ python-roborock PR #848 draft attempts an auto-fit too.

## Capabilities

Full scoped matrix (can / can't / unknown, per interaction) → **[CAPABILITIES.md](CAPABILITIES.md)**. In short:
reads + room-targeted cleaning + map/history decode + a single-connection daemon all work live; structured map
mutations (walls/zones) decode but can't be set from here; some settings are cloud-authoritative.

## Open questions

Where we're uncertain or others disagree — **the high-value targets for anyone extending this** (data to test
against in the seed corpus, when published):
- **No-mop zone type code:** we observe **`0x02`** (ground-truthed, drew one, `s26`); python-roborock PR #850
  reports **`0x03`**. Unresolved — possibly per-firmware or sub-types. ⬜ ❓ *Context (Reported):* the RRMapFile
  **file** format (marcelrv/XiaomiRobotVacuumProtocol) numbers these as separate *blocks* — no-go=9, virtual
  walls=10, no-mop=12 — a different encoding from the B01 **MQTT DP** `RESTRICTED_ZONE_UP` types, which is one
  reason type numbers don't cross-map cleanly between projects. Reconcile by comparing raw captures across homes.
- **Map origin in the cloud channel:** not in the 301 stream; may live in the on-demand map RPC / 102-JSON. ⬜
- **`CLEAN_RECORD` live-pull trigger:** app-only MQTT publish; our `op:list` gets no reply. Needs a transparent
  MQTT MITM to capture the app's exact payload. ⬜
- **Unexplained DPs** seen on the `novel` tap but never decoded. ⬜
- The anomalous path `pts[0]` sentinel `(0,−1907)` (0x11+ firmware) — band-aided, intent unknown. ⬜

## Method & provenance

Every datapoint here is **"we used hardware H + method M → result R"**, then interpreted over the totality of
available information. Method: an on-device HTTPS proxy (REST capture) + a single-connection MQTT tap (the live
DP + 301 stream) run together, with a **timestamped operator log** so app-action → REST → MQTT → robot-state can
be aligned. Sessions are labelled `s5`…`s26` (2026-06-12 … 2026-06-16); the per-finding anchors above cite them. The
hands-on window was four days: protocol/map RE from captures (`s2`–`s19`, 06-12/13), then **live robot
validation** (`s20`–`s26`, 06-14/15 — `s22`–`s26` each retain a capture; `s25` is a desk re-analysis). So a
✅ on live behaviour traces to a specific supervised run, not a one-off guess.
Captured evidence is retained internally; published excerpts are scrubbed per the **privacy floor** (settings/
rooms/cron/timestamps clear; tokens/Hawk-creds/MAC/SSID/IP/email redacted; duid/serial/map-id placeholdered).

## Credits

Built on others' work — the full landscape + attribution is in **[CREDITS.md](CREDITS.md)**.
Notably: [python-roborock](https://github.com/Python-roborock/python-roborock) (the library); the
[HA Roborock integration](https://www.home-assistant.io/integrations/roborock/) (the single-connection coordinator
pattern); [v1b3c0d3x3r/roborock-qseries-map-bridge](https://github.com/v1b3c0d3x3r/roborock-qseries-map-bridge)
(B01 map decode); the [openHAB Roborock binding](https://github.com/openhab/openhab-addons) (clean-record + status
tables); [marcelrv/XiaomiRobotVacuumProtocol](https://github.com/marcelrv/XiaomiRobotVacuumProtocol) and Dennis
Giese / [dustcloud](https://github.com/dgiese/dustcloud) (the RE lineage).

[^135]: `135` is MQTT5 return code `0x87` "Not Authorized" on reconnect-storm, not purely a rate-limit — but holding one connection still avoids it.
