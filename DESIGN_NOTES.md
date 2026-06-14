# Design notes & protocol findings

This document explains *why* the tool is built the way it is, and what we learned reverse-engineering a Roborock Q10 (B01-series) robot vacuum. It is meant to be read by anyone curious about how these robots actually talk to the cloud — whether you want to use this CLI, extend it, or build your own client. Throughout, we try to be honest about what is **confirmed** (observed in live traffic or round-trip tested) versus **inferred**.

## Why cloud-only

Older Roborock S-series robots (the "V1" protocol family) accept a direct TCP connection on the local network — you can talk to them on your LAN without going through Roborock's servers. The Q10 and its B01-series siblings **do not**. They report `pv=B01` during discovery and are reachable only through Roborock's cloud MQTT broker. There is no local control API, no documented local port, and (at time of writing) no Valetudo/custom-firmware path for this model.

The practical consequence: **every command this tool sends is a cloud round-trip.** The phone app and this CLI are both just clients of the same Roborock cloud account, issuing the same kinds of messages over the same broker. We are not bypassing Roborock's cloud — we are speaking its protocol as a peer of the official app. This also shaped the early architecture of the tool: the B01 device is driven through a B01-specific properties API (command / status / vacuum / remote traits), not the much richer V1 trait set, so several V1-only conveniences (segment cleaning by room id, wash-towel modes, pre-rendered map images) simply aren't exposed by the library's B01 path and had to be rebuilt from scratch here. (Home Assistant's official Roborock integration has since been adding native Q10 support, including segment cleaning — if you use Home Assistant, prefer it; this project targets terminal/cron/scripting use without HA, and documents the protocol.)

## The two channels: MQTT vs REST

A B01 robot is controlled over **two completely disjoint channels**, and understanding the split is the single most useful thing to know about the protocol:

- **MQTT** carries the real-time relationship with the robot: live status/telemetry, runtime settings (fan/water/mode), stored preferences, the map stream, and direct clean control (start / pause / resume / dock / find / auto-empty). The robot subscribes to an *input* topic and publishes to an *output* topic; we can subscribe to the output topic and watch everything the robot emits.
- **REST** (an HTTPS API authenticated with Hawk signatures) carries **scheduling** — the `/jobs` endpoint — and, as it turns out, **one-time room-targeted cleans**.

We confirmed the channels are disjoint by running an MQTT capture and an HTTPS proxy on the same clock and merging the timelines: every map mutation, wall/zone draw, and room clean fired on MQTT with **zero** REST writes within seconds of it, while every schedule edit fired on REST and produced **no** MQTT echo. So clean/wall/zone/settings commands ride MQTT; only schedules (and, by extension, scheduled room cleans) ride REST. They never overlap.

## Room cleaning over REST `/jobs`

The most useful finding in the whole project: **you don't need to solve the MQTT room-clean command at all.** The scheduling API can do it.

The app's scheduling system posts cron jobs to `POST /user/devices/{duid}/jobs`. Most are *repeated* weekly schedules (`repeated: true`). But the app also posts **one-time jobs** — `repeated: false` with a fully dated cron expression a minute or two in the future. A one-time job whose body specifies particular rooms is, in effect, **"clean these rooms, once, very soon."** That is exactly what a room-targeted clean is. So "clean room N now" becomes: post a one-time job with a cron a couple of minutes out and `rooms: [N]`.

The job body schema (captured from real app traffic) is roughly:

```
{ cron, repeated, enabled,
  param: { mapId, rooms:[...], roomCount,
           cleanMode, cleanRoute, fanLevel, waterLevel, cleanCount } }
```

A few details worth calling out:

- **The REST fan scale differs from the MQTT enum at the top tier.** The maximum fan level over REST is encoded differently than the equivalent MQTT setting — an early bug sent the wrong top-tier value. If you reuse this schema, treat the REST `fanLevel` enum as its own thing, not as the MQTT fan enum.
- **The Hawk body-signing fix.** This is the bug that blocked writes for a long time and is worth understanding if you build your own client. Reads (GET) and writes (POST/PUT/DELETE) to the same endpoint sign the Hawk request **differently**: a GET signs the *path only*, leaving the request-body hash slot empty, while a **write must sign `md5(compact_json(body))`** in that slot. We spent a long time convinced the problem was *token scope* — that the library's login issued a read-only token and only the app got write permission — because every GET returned 200 and every write returned 401 `auth.err.invalid.token`. It was never the token. Any valid credential writes fine **once the body is signed correctly.** The fix has two halves that must agree: sign `md5` of the compact, separator-tight JSON, *and* send those exact same bytes on the wire (don't let your HTTP library re-serialize the body with different spacing, or the server's hash of what it received won't match your signature). The upstream library signs path-only even for writes, which is why it cannot perform these `/jobs` writes out of the box.
- **Dry-running a job safely.** A one-time clean job moves a physical robot, so you want to validate the write without triggering it. The naive approach — post the job, then quickly delete it before it fires — has a race: the server's cron scheduler *queues* a firing at the minute boundary, and a DELETE removes the job from the list but does **not** abort an already-queued firing. So a job posted with a near-future cron can still fire even though the delete returned 200. The robust fix is to post the dry-run job with `enabled: false` — the scheduler skips disabled jobs entirely, so it cannot fire regardless of delete timing. The general rule we banked: **to validate a write that triggers a physical action, post it inert (disabled or far-future), never post-it-live-and-race-to-undo.**

## The map protocol

The robot streams its map over MQTT **spontaneously while cleaning** — roughly a 23 KB frame every few seconds, no request needed — on **protocol 301**. (It can also be pulled on demand via a map RPC, but the passively-streamed format is identical and needs no command.) Naive decoders silently drop these frames because they only yield the JSON status frames; you have to tap the MQTT stream one level lower to capture the raw binary.

Within a 301 frame there are two sub-types, keyed by the first header bytes:

- **The cleaning path.** After a fixed-size header (which includes a point count), the body is a sequence of **big-endian int16 (x, y) pairs** (little-endian decodes to garbage). The polyline grows over the run, and **the last point is the robot's current position.** Coordinates are in millimetres. Note the path is decimated (~20 mm between vertices), so it's accurate for route and position but its cumulative length underestimates true travel — don't compute speed from it.
- **The room/occupancy grid.** This one is **LZ4-compressed** (after a fixed header), and decompresses to an occupancy grid where **`pixel // 4 = room id`**, followed by trailing fixed-size records carrying room names. It is *not* AES-encrypted and *not* the older S-series SCMap format — two proofs settled this: the frames have variable lengths with inconsistent residues mod 16 (AES-ECB ciphertext is always a multiple of the 16-byte block), and the byte entropy (~5.1 bits/byte) is far below the ~8.0 of real ciphertext. The recurring byte motifs that initially looked like run-length markers are LZ4 back-reference tokens.

**Georeferencing** the path onto the grid (so a path coordinate in mm maps to a grid pixel) is solved empirically: there is a fixed origin offset and a resolution of **20 mm per pixel**, with the grid's row axis inverted relative to the path's x axis. The registration fits over 99.8% of path points onto floor pixels. The header does *not* contain the bounding box — that metadata lives only in the on-demand map RPC's protobuf — so empirical registration is the right approach for the spontaneous stream. The anchor is the dock position; coordinates stay stable as long as the dock doesn't move and the map isn't reset. Virtual-wall and zone coordinates use a different convention again — they are stored in **half-millimetre units** (multiply by two before applying the path georeference) and use a `(y, x)` axis order rather than the path's `(x, y)`.

A large amount of from-scratch reverse engineering on the grid format was **avoided** by searching for prior art first: a community Q-series B01 map-bridge project had already worked out the LZ4 layout and room-id encoding. The format matched our captured frames exactly. The lesson, which generalizes well beyond this project: **before reverse-engineering a binary format, search for someone who has already done it — it's the cheap first move.** That work is credited in the project's credits file.

## Why a single-connection daemon

Opening a fresh MQTT connection for every command seems harmless, but it isn't. Roborock enforces an **account-level connection rate limit.** Poll status a few times, start a clean, restart a watch — each a new MQTT session — and the broker starts refusing connections with **`code 135 Not authorized`**. This is account-scoped, not client-scoped: when we tripped it, the *phone app* also lost the robot until it cleared. (The REST channel is separate and stays up through an MQTT throttle.)

The fix is architectural: a **long-lived daemon that holds exactly one MQTT connection open** and serves commands to the thin CLI over a local Unix-domain socket. The CLI becomes a client of the daemon; the daemon owns the single cloud connection for its entire lifetime. Command logic is shared verbatim between the two modes — the daemon injects its held session into the same command functions the standalone CLI uses — so behavior is identical whether you go through the daemon or run a one-off standalone command.

Because the library does not auto-recover from a 135, the daemon catches it, **cools down with escalating backoff, and reconnects** with the existing credentials; a genuine token revocation (which needs an interactive re-login) is surfaced clearly rather than retried blindly. There is also a **careful mode** that stops on the first auth/rate-limit complaint rather than risk hammering the account. The broader discipline this enforces: **budget total MQTT connects, not just per-command reversibility** — use one persistent session, monitor by reading its output rather than re-polling, and let the reconnect loop recover a quiet-but-alive session instead of killing and reopening it.

## Cloud-authoritative vs runtime settings

Not every setting behaves the same way when you write it over MQTT, and this surprised us until we understood the split:

- **Runtime session parameters — fan, water, mode — persist.** These are properties of the cleaning session, the robot adopts them immediately, and they stick. Writing them over MQTT works.
- **Stored preferences — volume, child-lock, auto-boost, do-not-disturb — are cloud-authoritative and revert.** You can send the MQTT write, the command is accepted, and a few seconds later a status dump shows the *old* value. The reason is that these are saved server-side, and the Roborock cloud **re-asserts the stored value** after any override attempt. This was confirmed cleanly with the phone app fully force-closed (ruling out the app re-writing the value): the write simply doesn't stick. So for this class of setting, **change it in the app, not via MQTT** — the cloud will win otherwise. This is not a bug in the MQTT send path; it's the server reasserting authority over its stored preferences.

A related honest caveat: the library ships **no B01 fault-code table**, so when the robot reports a fault, the tool surfaces the raw code rather than a friendly description.

## Dependency fragility

This tool stands on `python-roborock` (the public PyPI package, version 5.x — there is no fork involved), but it reaches into the library's **internals** to do B01 work the library doesn't yet expose publicly: a private Hawk-auth helper, a private channel's stream-subscribe attribute, deep B01-specific RPC and data modules. None of these have a stability contract, so a minor version bump can rename or move any of them and break the tool mid-run.

Three mitigations keep this manageable:

1. **A version pin** that blocks the next major release (where a large restructure would land).
2. **A lockfile** capturing the exact known-good versions of the library and its full dependency tree, so a rebuild is reproducible.
3. **An API canary** — a small script that imports every internal symbol the tool relies on, checks the auth helper's signature and the required data-point members, and reports exactly what moved. **Run it after any upgrade**; it turns a cryptic mid-session crash into a clear, actionable diff up front. Where practical, the riskiest internals (notably the Hawk helper) have been vendored as small stdlib-only copies so the tool no longer depends on the private originals.

One environment trap is worth flagging because it masquerades as "the library is broken." The 5.x line requires **Python ≥ 3.11**. On 3.9/3.10, `pip install python-roborock` cannot satisfy that requirement and **silently installs an ancient 0.x release** that has no B01 device modules — producing a `ModuleNotFoundError: No module named 'roborock.devices'` that looks like a missing dependency but is really a wrong-interpreter problem. Run the tool with an interpreter that is actually 3.11+; don't "fix" the import error by pip-installing into a stray Python.

## Reverse-engineering methodology

For anyone wanting to extend this or do the same work on another model, here's how the findings above were actually obtained:

- **Watching the robot's MQTT output.** The robot echoes a great deal on its output topic — far more than the modeled status fields. A raw watch mode taps the decoded stream (and a bytes mode taps below that, for binary frames like the map) and logs everything, which is how the unmodeled payloads (zones, walls, the map stream) were decoded. This works because the MQTT session fans one topic subscription out to multiple callbacks, so our tap coexists with the library's own subscribe loop without disturbing it.
- **An HTTPS proxy for the REST and login flows.** Proxying the phone app's HTTPS traffic captured the `/jobs` schema, the login token format, and the exact Hawk signatures we needed to compare against. **Crucially, an HTTP proxy cannot see MQTT** — MQTT connects directly to the broker on its own port and never passes through an HTTP proxy. So the proxy is the right tool for REST/login and useless for clean/wall/zone commands; those are only visible via the MQTT output echo.
- **Cross-correlating timelines.** Running the MQTT capture and the HTTPS proxy simultaneously on the same machine clock — then merging both into one timeline — is what proved the MQTT/REST channel split, by showing which mutations produced which traffic (and which produced none on the other channel).

Throughout, every account write was treated as a real, observable action against a live account: prefer passive capture, make at most one reversible write at a time, and avoid blind probing that risks rate-limits, token revocation, or account review.
