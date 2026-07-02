# Credits & prior art

This project stands on a lot of other people's work. It is an unofficial CLI + daemon
for Roborock **B01 / Q10** devices; the novel part is the *packaging* (a safe-by-default
single-connection daemon + CLI for this device family, plus the B01 reverse-engineering
below). Everything else we reuse, learn from, or build on — credited here.

## Depends on
- **[python-roborock](https://github.com/Python-roborock/python-roborock)** (Lash-L,
  allenporter, contributors) — the library we build on. We hold its `DeviceManager` +
  `FileCache` open in our daemon and reuse its MQTT session, reconnect/backoff, and the
  B01/Q10 decoders. `vac.py` uses some of its internals directly (see the adapter block
  in `vac.py` and `check_roborock_api.py`).

## Patterns learned from (not code-copied)
- **[Home Assistant Roborock integration](https://www.home-assistant.io/integrations/roborock/)**
  — the coordinator pattern our daemon follows: one shared long-lived connection per
  device, verify/login once (not per command), cache HomeData to avoid the cloud's
  ~15/hr `home_data` rate-limit, adaptive poll intervals.
- **[local_roborock_server](https://github.com/Python-roborock/local_roborock_server)**
  — a self-hosted Roborock cloud *replacement* (your robot connects to it). A different
  goal than ours (we keep the official cloud and just hold one connection to it), but it
  informed our understanding of the stack. If you want full local control, use it.
- **[Valetudo](https://github.com/Hypfer/Valetudo)** (Hypfer) — cloud-free vacuum control
  via firmware replacement. The other major "take back your vacuum" approach; complementary
  to this tool.
- **[CocoIndex "invisible daemon"](https://cocoindex.io/blogs/building-an-invisible-daemon/)**
  — the Unix-socket + version-handshake IPC pattern our CLI↔daemon link uses.

## Protocol / reverse-engineering lineage
- **[XiaomiRobotVacuumProtocol](https://github.com/marcelrv/XiaomiRobotVacuumProtocol)**
  (marcelrv) — the protocol-documentation style (per-DP tables with uncertainty markers)
  our `DP_DICTIONARY.md` follows.
- **`v1b3c0d3x3r/roborock-qseries-map-bridge`** — confirmed the Q-series map is
  LZ4-compressed, which unblocked our `decode_map.py` grid decode (see `FRAME_ANATOMY.md`).
- **[dustcloud](https://github.com/dgiese/dustcloud)** (Dennis Giese) — foundational
  Roborock/Xiaomi RE that this whole ecosystem builds on.

## What's original here (and worth contributing upstream)
- A **single-connection daemon + thin CLI for B01/Q10** that makes cloud control
  safe-by-default against the connection rate-limit. python-roborock has the reusable
  `DeviceManager` but no documented long-running/daemon mode — an `examples/daemon.py`
  upstream is a gap we'd like to fill.
- **B01 reverse-engineering**, contributed back to `python-roborock`:
  - **Merged:** the Hawk REST **body-signing** fix (path-only signing can't do B01 `/jobs` writes) —
    [PR #852](https://github.com/Python-roborock/python-roborock/pull/852), shipped in **5.15.2** (our first
    contribution); the **`remote_trait`** inner-key fix (`{"101":{"12":N}}`) —
    [PR #854](https://github.com/Python-roborock/python-roborock/pull/854); and the **Q10 zone type-2/3**
    correction contributed to [PR #850](https://github.com/Python-roborock/python-roborock/pull/850), shipped
    in **5.18.0**.
  - **Proposed / open:** the **`CLEAN_RECORD` clean-history** decode —
    [PR #857](https://github.com/Python-roborock/python-roborock/pull/857) (open, under review); a **`B01Fault`
    table** for the Q10 path — [issue #855](https://github.com/Python-roborock/python-roborock/issues/855); and
    the map-package **obstacle / erase / carpet layers**, offered as a follow-up comment on the community map PR
    [#848](https://github.com/Python-roborock/python-roborock/pull/848).
  - **Still on the bench (not yet proposed):** the **`0201` firmware SLAM heading** + closed-loop nav.

## Built with AI assistance

Much of this project — the CLI code, the B01 reverse-engineering, and the documentation — was
developed with the help of AI coding assistants: Anthropic's **Claude Opus 4.8** (architecture and
review) and **Claude Sonnet 4.6** (implementation), working under **human direction and supervision**.
A human set the goals, reviewed the changes, ran every live test against the real device, and made the
final calls (especially anything that touches the account or moves the robot). It's noted here in the
same spirit as the rest of these credits — so the provenance of the work is clear.

If we've used your work and missed crediting it here, please open an issue — that's a bug.
