# Contributing

Thanks for your interest. This is a reverse-engineered, unofficial controller for
Roborock **B01** vacuums (developed against the **Q10 S5+**). Contributions that
extend device coverage, sharpen the protocol docs, or harden the CLI are all welcome.

## Before you start

- Use a Python **≥ 3.11** environment with `python-roborock` 5.x installed
  (`pip install -r requirements.txt`; `requirements.lock.txt` pins known-good versions), then run
  the CLI as `./vac.py …`. On Python 3.9/3.10 pip silently installs an old 0.x release with no B01
  modules — see `README.md` / `DESIGN_NOTES.md`.
- After any `pip install -U python-roborock`, run `./check_roborock_api.py` — it tells you
  exactly which internal symbol moved before you hit a runtime crash.
- **Never commit captures or credentials.** `~/.roborock_vac.json` and all `*_capture.jsonl`
  / `watch` output contain login tokens + device PII (MAC/IP/SSID) and are gitignored. Don't
  `git add -f` them. See `credentials.example.json` for the creds-file schema.

## How to add (or report) another device

Even another Roborock model helps. The two most useful artifacts:

1. **A `watch --raw` capture of normal use.** `./vac.py watch --raw --out mydevice.jsonl`,
   then drive the robot through start / pause / dock / a room clean / settings changes in the
   app. This records every decoded data-point (DP) the device emits.
2. **A note of what differs** from the documented behavior: which DP codes/enums your device
   uses, any new DP keys, and which commands work vs. error out.

**Scrub before sharing.** Remove NET_INFO (IP/MAC/SSID), the device serial, and any tokens
from a capture before attaching it. Prefer pasting the relevant *decoded DP rows* over a raw dump.

Open an issue (or PR) with: model string (e.g. `roborock.vacuum.ss07`), firmware version, and
the scrubbed observations. New enum values / DP meanings go in `DP_DICTIONARY.md`; capability
results go in `CAPABILITIES.md`.

## Code / docs conventions

- **Protocol uncertainty is marked, not hidden.** In `DP_DICTIONARY.md`, fields whose meaning
  is confirmed get ✅; inferred-but-untested get 🟡 / ❓. Don't upgrade a marker without evidence.
- **Library internals are centralized.** All imports of `python-roborock` private modules live
  in one adapter block at the top of `vac.py`. Add new ones there, and to `check_roborock_api.py`.
- **Validate writes inertly.** Anything that triggers robot motion (e.g. `clean-rooms`) must be
  testable via `--dry-run` (posts a *disabled* job, then deletes it) before a live run. See
  `DESIGN_NOTES.md` (dry-run fail-safe).
- **Be gentle with the cloud.** The robot is on a real account; avoid rapid repeated commands
  (each opens a new MQTT session and can trip an account-level connection rate-limit). For
  monitoring, run one `watch` and read its output file rather than polling `status`. See
  `DESIGN_NOTES.md` (single-connection daemon).
- Propose changes via an issue or PR; record significant protocol findings in `DP_DICTIONARY.md` /
  `DESIGN_NOTES.md` and capability results in `CAPABILITIES.md`.

## Scope

`vac.py` controls the device over Roborock's **cloud MQTT** (B01 has no local control channel).
Map/state *reads* and schedule/room-clean *writes* work; persistent settings
(volume/child-lock/boost/DND) are cloud-authoritative and don't stick from the CLI. See
`CAPABILITIES.md` for the current matrix.
