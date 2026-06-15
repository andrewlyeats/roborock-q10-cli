#!/usr/bin/env python3
"""
Roborock Q10 S5+ controller  (B01 / cloud-MQTT protocol)

The Q10 S5+ speaks Roborock's "B01" protocol, which is MQTT-only — there is no
local TCP control channel (unlike older S-series "V1" devices). Every command is
relayed through Roborock's cloud broker. See DESIGN_NOTES.md for the why.

Setup (first time only):
  ./vac.py login --email your@email.com
  ./vac.py discover

Control:
  ./vac.py status                          # battery, state, fan, water, mode
  ./vac.py start | stop | pause | resume
  ./vac.py dock                            # return to dock
  ./vac.py dock-empty                      # trigger dock auto-empty
  ./vac.py find                            # play locate beep
  ./vac.py fan <quiet|balanced|turbo|max|max_plus>
  ./vac.py water <off|low|medium|high>
  ./vac.py mode <vac_and_mop|vacuum|mop>
  ./vac.py volume <0-100>                  # voice volume
  ./vac.py child-lock <on|off>
  ./vac.py boost <on|off>                  # auto carpet-boost
  ./vac.py watch [--out log.csv] [--interval N]   # stream live status telemetry
  ./vac.py watch --raw [--out log.jsonl]   # capture EVERY decoded data-point
  ./vac.py watch --bytes [--out log.jsonl] # capture EVERY raw MQTT frame (incl. binary/map)
  ./vac.py map [--timeout N] [--out PREFIX] # render the map → PREFIX_rooms.png / PREFIX_path.svg (default "map")
  ./vac.py rooms                           # list rooms on the current map (id + name)
  ./vac.py clean-rooms <name|id>...        # clean only the named/numbered rooms via REST /jobs
      [--fan <level>]  [--water <level>]  [--mode <mode>]
      [--route fast|daily|fine]  [--count 1|2]
      [--dry-run]                          # post job, verify in list, delete before it fires
  ./vac.py consumables                     # brush/filter/sensor life %
  ./vac.py history [--json]               # clean history (live op:list pull is app/push-only — WIP)
  ./vac.py history --from-capture F.jsonl [--json]  # decode clean history from a watch/echo capture (offline)
  ./vac.py dnd <on|off> [--start HH:MM] [--end HH:MM]
  ./vac.py raw <DP_NAME> [json_value]      # send any raw data-point command

  ./vac.py schedule list                   # show cloud schedules (id · time · rooms)
  ./vac.py schedule enable <id>
  ./vac.py schedule disable <id>
  ./vac.py schedule delete <id>
  ./vac.py schedule add --time HH:MM       # daily full-house clean at HH:MM
      [--days mon,wed,fri]                 # specific weekdays instead of daily
      [--once]                             # one-shot (auto-picks today or tomorrow)
      [--rooms <name|id>...]               # room-selective (resolves from map)
      [--fan <level>]  [--water <level>]  [--mode <mode>]
      [--route fast|daily|fine]  [--passes 1|2]

  ./vac.py daemon start [--careful] | stop | restart | status   # the connection holder
  ./vac.py daemon record [--events F] [--novel F] [--bytes F] | --off   # telemetry taps

Daemon model:
  By DEFAULT every command runs through a background daemon that holds ONE cloud
  connection (so commands don't each open a new MQTT session and trip the cloud
  rate-limit). Start it once with `./vac.py daemon start`. If it isn't running,
  commands error with instructions. Add --force (or --no-daemon) to run a single
  command standalone with its own session (avoid repeating — it can hit the limit).
  --careful: stop the daemon COMPLETELY on the first auth/rate-limit complaint (135)
  instead of backing off — maximally conservative; recommended for first live runs.

Add --json to status/consumables/discover for machine-readable output.
Add --device <duid> to target a specific robot when more than one is registered.

Files:
  ~/.roborock_vac.json        credentials (login token)
  ~/.roborock_vac_cache.pkl   device cache (avoids cloud rate-limits on discover)
  ~/.roborock_vacd.sock/.pid/.log   daemon socket / pid / log
"""
from __future__ import annotations

import asyncio
import base64
import contextlib
import hashlib
import hmac
import io
import json
import logging
import math
import os
import pathlib
import re
import secrets
import signal
import subprocess
import sys
import time
import traceback
from contextlib import asynccontextmanager
from dataclasses import asdict, dataclass
from datetime import datetime

# The library logs harmless WARNINGs for data-point codes it doesn't model
# (e.g. "112 is not a valid code for B01_Q10_DP"). Keep our output clean.
logging.basicConfig(level=logging.WARNING)
logging.getLogger("roborock").setLevel(logging.ERROR)

# ── python-roborock internal-API adapter ───────────────────────────────────────
# vac.py relies on python-roborock INTERNALS (private functions/attributes, deep
# module paths) that carry no API-stability guarantee. ALL such imports are
# centralized HERE so a breaking library upgrade is a one-line fix in ONE place
# rather than a hunt through the file. After any `pip install -U python-roborock`,
# run ./check_roborock_api.py to confirm these still exist. See DECISIONS
# 'dependency fragility' / TASKS #12 / CLAUDE.md.
try:
    from roborock import B01Fault
    from roborock.data import UserData
    from roborock.data.b01_q10.b01_q10_code_mappings import (
        B01_Q10_DP,
        YXCleanLine,
        YXCleanType,
        YXFanLevel,
        YXWaterLevel,
    )
    from roborock.devices.device_manager import UserParams, create_device_manager
    from roborock.devices.file_cache import FileCache
    from roborock.devices.rpc.b01_q10_channel import stream_decoded_responses
    from roborock.mqtt.session import MqttSessionUnauthorized
    from roborock.web_api import RoborockApiClient
except ImportError as _exc:  # environment / upgrade guard
    sys.exit(
        f"python-roborock internal import failed: {_exc}\n"
        "Likely the wrong interpreter (run ./vac.py, or use the conda env / Python "
        ">=3.11), or a breaking library upgrade. Run ./check_roborock_api.py to see "
        "exactly what moved (see CLAUDE.md / DECISIONS 'dependency fragility')."
    )


def _hawk_extra(values: dict | None) -> str:
    """md5 of sorted ``k=v`` pairs, or ``""`` when None. Vendored from
    python-roborock's ``_process_extra_hawk_values`` (v5.14.2)."""
    if values is None:
        return ""
    pairs = [f"{k}={values[k]}" for k in sorted(values)]
    return hashlib.md5("&".join(pairs).encode()).hexdigest()


def _hawk_auth(rriot, url: str, formdata: dict | None = None,
               params: dict | None = None,
               json_body: dict | None = None) -> str:
    """Build a Hawk ``Authorization`` header for the Roborock REST API.

    Vendored from python-roborock ``web_api._get_hawk_authentication`` (v5.14.2) so
    vac.py does not depend on a private library function (TASKS #12). GET requests
    sign the path only. PUT/POST JSON bodies are signed via ``json_body``: the
    server validates ``md5(compact_json(body))`` in the formdata slot (confirmed
    by cross-checking app-captured MACs against all signing variants, session 17).
    """
    timestamp = math.floor(time.time())
    nonce = secrets.token_urlsafe(6)
    if json_body is not None:
        fd_field = hashlib.md5(
            json.dumps(json_body, separators=(',', ':')).encode()
        ).hexdigest()
    else:
        fd_field = _hawk_extra(formdata)
    prestr = ":".join([
        rriot.u,
        rriot.s,
        nonce,
        str(timestamp),
        hashlib.md5(url.encode()).hexdigest(),
        _hawk_extra(params),
        fd_field,
    ])
    mac = base64.b64encode(
        hmac.new(rriot.h.encode(), prestr.encode(), hashlib.sha256).digest()
    ).decode()
    return f'Hawk id="{rriot.u}",s="{rriot.s}",ts="{timestamp}",nonce="{nonce}",mac="{mac}"'

CREDS_FILE = pathlib.Path("~/.roborock_vac.json").expanduser()
CACHE_FILE = pathlib.Path("~/.roborock_vac_cache.pkl").expanduser()

# B01 commands are fire-and-forget MQTT publishes; this only guards against a
# wedged broker connection, not slow device responses.
ACTION_TIMEOUT = 10
# Status arrives asynchronously across several MQTT frames after REQUEST_DPS.
STATUS_TIMEOUT = 10


# ── cloud connection rate-limit handling ───────────────────────────────────────
# vac.py opens a fresh MQTT session per invocation. Firing many commands quickly
# (e.g. polling `status` in a loop) can trip an ACCOUNT-LEVEL connection rate-limit:
# the broker then refuses new sessions with `code 135 Not authorized`, which also
# knocks out the phone app until it cools off (minutes–~1h). See DECISIONS s20 +
# DESIGN_NOTES.md. We turn that cryptic crash into a clear message, and for read-only
# commands retry a couple of times with backoff in case it's a brief throttle.
_THROTTLE_MSG = (
    "\nCloud MQTT connection refused — rate-limited / not authorized (code 135).\n"
    "Too many connections in a short window. Wait a few minutes, then retry.\n"
    "Tip: for monitoring run ONE `./vac.py watch --raw --out log.jsonl` and read the file;\n"
    "don't poll `status` in a loop (each call opens a new MQTT session). See DESIGN_NOTES.md."
)


def _is_throttle(exc: BaseException) -> bool:
    """True if exc is the cloud broker refusing the connection (rate-limit / not authorized)."""
    if isinstance(exc, MqttSessionUnauthorized):
        return True
    s = str(exc).lower()
    return "not authorized" in s or "code:135" in s or "code: 135" in s


# Broader "the server complained about auth or rate-limit" check — used only to TRIP
# careful mode (where a false positive merely stops the daemon, the safe outcome). Covers
# REST/Hawk complaints (e.g. clean-rooms/schedule 401) on top of the MQTT 135 throttle.
_AUTH_RATE_SIGNS = ("401", "403", "forbidden", "unauthoriz", "invalid.token",
                    "invalid token", "auth.err", "rate limit", "ratelimit",
                    "too many request", "quota")


def _is_auth_or_rate(exc: BaseException) -> bool:
    if _is_throttle(exc):
        return True
    s = str(exc).lower()
    return any(sign in s for sign in _AUTH_RATE_SIGNS)


def _reason_code(exc: BaseException):
    """Best-effort numeric reason code from an exception message (135, 401, 429, …)."""
    s = str(exc)
    m = re.search(r"code:?\s*(\d{2,3})", s, re.I)        # MQTT 'code:135'
    if m:
        return m.group(1)
    m = re.search(r"\b(401|403|404|409|429|500|502|503|504)\b", s)  # HTTP-ish
    return m.group(1) if m else None


def _classify_error(exc: BaseException) -> str:
    if _is_throttle(exc):
        return "mqtt-throttle(135)"
    s = str(exc).lower()
    if "429" in s or "rate limit" in s or "ratelimit" in s or "quota" in s or "too many" in s:
        return "rest-rate-limit"
    if any(x in s for x in ("401", "403", "forbidden", "unauthoriz", "invalid.token",
                            "invalid token", "auth.err")):
        return "auth"
    if isinstance(exc, (ConnectionError, OSError, asyncio.TimeoutError)):
        return "network"
    return "other"


_ERROR_HINTS = {
    "mqtt-throttle(135)": "Account-level MQTT connect throttle — the app shares this limit. Wait "
                          "several minutes; do NOT reconnect hard (that extends it). See DESIGN_NOTES.md.",
    "rest-rate-limit":    "REST rate-limit (e.g. the ~15/hr home_data bucket). Slow down and avoid "
                          "daemon restart churn.",
    "auth":               "Credentials may be expired/revoked. Run ./vac.py login, then "
                          "./vac.py daemon restart.",
    "network":            "Network/transport issue reaching the cloud. Usually transient; the daemon "
                          "will retry. Check connectivity if it persists.",
    "other":              "Unexpected — see the traceback in ~/.roborock_vacd.log. Could be a transient "
                          "glitch or a python-roborock change (run ./check_roborock_api.py).",
}


# ── daemon: paths + session injection ──────────────────────────────────────────
# A long-running daemon holds ONE python-roborock DeviceManager open and serves the
# CLI over a Unix socket, so every command rides a single cloud connection instead
# of a new MQTT session per invocation (which trips the account-level connect
# throttle — see _THROTTLE_MSG / DECISIONS s20). When the daemon is running it sets
# _INJECTED_SESSION; device_session then hands every existing cmd_* that one held
# session transparently, so command logic is shared verbatim between the daemon and
# the standalone `--force` path. Architecture credits in CREDITS.md.
DAEMON_PROTO = 1                       # bump when the socket protocol changes
# Escalating cool-down (seconds) between reconnect attempts after a 135 throttle, so
# we don't hammer the broker during an active ban (which only extends it). After this
# many consecutive failures the daemon gives up and requires a manual login — retrying
# revoked credentials forever is just noise to the server. (DECISIONS s21; server-view.)
_RECONNECT_BACKOFF = [120, 300, 900, 900, 900]
_MAX_RECONNECTS = len(_RECONNECT_BACKOFF)
SOCK_PATH = pathlib.Path("~/.roborock_vacd.sock").expanduser()
PID_PATH  = pathlib.Path("~/.roborock_vacd.pid").expanduser()
LOG_PATH  = pathlib.Path("~/.roborock_vacd.log").expanduser()
HALT_PATH = pathlib.Path("~/.roborock_vacd.halt").expanduser()   # why a careful-mode daemon stopped

# Set by the running daemon to (device, props); makes device_session reuse the held
# session instead of opening a new one. None in the standalone/--force path.
_INJECTED_SESSION = None


# ── credentials ───────────────────────────────────────────────────────────────

@dataclass
class Creds:
    email: str
    user_data: dict
    base_url: str | None = None


def load_creds() -> Creds | None:
    if not CREDS_FILE.exists():
        return None
    with open(CREDS_FILE) as f:
        return Creds(**json.load(f))


def save_creds(creds: Creds) -> None:
    with open(CREDS_FILE, "w") as f:
        json.dump(asdict(creds), f, indent=2)


def require_creds() -> Creds:
    creds = load_creds()
    if not creds:
        sys.exit("Not logged in. Run:  ./vac.py login --email your@email.com")
    return creds


# ── device session ────────────────────────────────────────────────────────────

def _select_device(devices: list, duid: str | None):
    if not devices:
        sys.exit("No devices found.")
    if duid:
        dev = next((d for d in devices if d.duid == duid), None)
        if not dev:
            known = ", ".join(d.duid for d in devices)
            sys.exit(f"Device {duid} not found. Known: {known}")
        return dev
    if len(devices) == 1:
        return devices[0]
    listing = ", ".join(f"{d.name} ({d.duid})" for d in devices)
    sys.exit(f"Multiple devices — use --device <duid>. Found: {listing}")


@asynccontextmanager
async def device_session(duid: str | None = None, *, map_parser_config=None):
    """Open a connected device, yield its Q10 properties API, and clean up.

    Handles the full lifecycle once so command functions don't have to:
    load creds → build manager (with file cache) → discover → select device →
    flush cache + close manager on exit.

    When a daemon is running it injects its held session, so every cmd_* reuses the
    one persistent connection instead of opening (and rate-limiting) a new one.
    """
    if _INJECTED_SESSION is not None:
        yield _INJECTED_SESSION          # daemon-held session; do NOT create/close
        return

    creds = require_creds()
    user_data = UserData.from_dict(creds.user_data)
    params = UserParams(username=creds.email, user_data=user_data, base_url=creds.base_url)
    cache = FileCache(CACHE_FILE)
    manager = await create_device_manager(
        params, cache=cache, prefer_cache=True, map_parser_config=map_parser_config,
    )
    try:
        devices = await manager.discover_devices(prefer_cache=True)
        device = _select_device(devices, duid)
        props = getattr(device, "b01_q10_properties", None)
        if props is None:
            sys.exit(
                f"Device '{device.name}' is not a B01/Q10 device (pv={device.device_info.pv}). "
                "This tool targets the Roborock Q10 family."
            )
        yield device, props
    finally:
        await cache.flush()
        await manager.close()


async def fetch_status(props, timeout: int = STATUS_TIMEOUT):
    """Request a fresh status and wait for it to actually arrive.

    refresh() only *publishes* a REQUEST_DPS; the device answers asynchronously
    across several MQTT frames over ~1s. We register an update listener and wait
    until the core fields (battery + state) are populated, returning whatever we
    have if the device is slow or offline.
    """
    populated = asyncio.Event()

    def check():
        s = props.status
        if s.battery is not None and s.status is not None:
            populated.set()

    remove = props.status.add_update_listener(check)
    try:
        await props.refresh()
        check()  # maybe a prior frame already populated it
        await asyncio.wait_for(populated.wait(), timeout=timeout)
    except asyncio.TimeoutError:
        pass  # fall through with partial/empty status
    finally:
        remove()
    return props.status


# Stored user-preference settings (volume/child-lock/auto-boost) are cloud-authoritative:
# the MQTT write is accepted by the broker but the server re-asserts the saved value on the
# next sync, so the change does not stick from the CLI. There is no usable write channel for
# these (the app persists them over the MQTT *input* topic we cannot publish to — confirmed
# DECISIONS s18 / coord O22). We send anyway (harmless) but must not claim it persisted.
CLOUD_REVERT_NOTE = (
    "  note: this is a cloud-stored preference — the server may revert it on the next sync. "
    "Change it in the Roborock app to make it stick. (See CAPABILITIES.md.)"
)


async def run_action(action, success_msg: str, duid: str | None, caveat: str | None = None):
    """Run a single fire-and-forget device action with a timeout + message."""
    async with device_session(duid) as (_device, props):
        try:
            await asyncio.wait_for(action(props), timeout=ACTION_TIMEOUT)
            print(success_msg)
            if caveat:
                print(caveat)
        except asyncio.TimeoutError:
            print("Command timed out — the robot may be offline.")


# ── status / info commands ────────────────────────────────────────────────────

STATE_EMOJI = {
    "cleaning": "🧹", "charging": "🔋", "charging_complete": "✅",
    "idle": "💤", "returning_home": "🏠", "paused": "⏸",
    "error": "❌", "emptying_the_bin": "🗑", "mapping": "🗺",
    "sweeping": "🧹", "mopping": "🫧", "sweep_and_mop": "🧹🫧",
    "sleeping": "😴", "relocating": "🧭", "waiting_to_charge": "🔌",
}


def _enum_name(value) -> str:
    return value.name.lower() if value is not None else "?"


async def cmd_discover(duid: str | None, as_json: bool = False):
    async with device_session(duid) as (device, props):
        s = await fetch_status(props)
        if as_json:
            print(json.dumps({
                "name": device.name, "duid": device.duid, "model": device.product.model,
                "battery": s.battery, "state": _enum_name(s.status),
            }))
        else:
            print(f"  Name    : {device.name}")
            print(f"  DUID    : {device.duid}")
            print(f"  Model   : {device.product.model}")
            print(f"  Battery : {s.battery if s.battery is not None else '—'}%")
            print(f"  State   : {_enum_name(s.status)}")


# Empirically-decoded FAULT codes the library's B01Fault table lacks — decoded live from
# the iOS app's human-readable pushes (see DP_DICTIONARY / DECISIONS s22). The FAULT DP is
# OVERLOADED: it also carries benign lifecycle/status codes, so "non-zero" ≠ fault.
_FAULT_OVERRIDES = {8: "robot trapped — clear obstacles"}   # firmware reports trapped as 8 (lib: 513/514)
_FAULT_BENIGN = {400}   # 400 = "starting scheduled cleanup" — a START code, not a fault


async def cmd_status(duid: str | None, as_json: bool = False):
    async with device_session(duid) as (_device, props):
        s = await fetch_status(props)
        if s.status is None and s.battery is None:
            if as_json:
                print(json.dumps({"error": "offline"}))
            else:
                print("Could not reach the robot (offline or sleeping).")
            return
        fault_label = None
        if s.fault and s.fault not in _FAULT_BENIGN:
            if s.fault in _FAULT_OVERRIDES:
                fault_label = _FAULT_OVERRIDES[s.fault]
            else:
                try:
                    fault_label = B01Fault[f"F_{s.fault}"].value.replace("_", " ")
                except Exception:
                    fault_label = str(s.fault)
        # clean_task_type / back_type are already-decoded enums on the status object
        # (YXDeviceCleanTask / YXBackType). Surface them: task = what kind of clean
        # (smart/electoral/part…), back_type = return reason (e.g. backcharging).
        task = getattr(s, "clean_task_type", None)
        back = getattr(s, "back_type", None)
        if as_json:
            print(json.dumps({
                "state": _enum_name(s.status), "battery": s.battery,
                "fan": _enum_name(s.fan_level), "water": _enum_name(s.water_level),
                "mode": _enum_name(s.clean_mode), "task": _enum_name(task),
                "back_type": _enum_name(back), "clean_time_s": s.clean_time,
                "clean_area_m2": s.clean_area, "progress_pct": s.cleaning_progress,
                "fault": fault_label, "fault_code": s.fault,
            }))
        else:
            emoji = STATE_EMOJI.get(s.status.name if s.status else "", "")
            print(f"{emoji} State      : {_enum_name(s.status)}")
            print(f"   Battery   : {s.battery if s.battery is not None else '—'}%")
            print(f"   Fan       : {_enum_name(s.fan_level)}")
            print(f"   Water     : {_enum_name(s.water_level)}")
            print(f"   Mode      : {_enum_name(s.clean_mode)}")
            if task is not None and task.name not in ("UNKNOWN", "IDLE"):
                print(f"   Task      : {_enum_name(task)}")
            if s.cleaning_progress is not None:
                print(f"   Progress  : {s.cleaning_progress}%")
            if s.clean_time:
                print(f"   Clean time: {s.clean_time // 60}m {s.clean_time % 60}s")
            if s.clean_area:
                # clean_area is *swept* area in m² (distance-swept × lane-width, incl.
                # overlap + passes), not floor footprint — confirmed by cross-checking
                # the decoded map path. See DP_DICTIONARY.md / DESIGN_NOTES.md.
                print(f"   Area swept: {s.clean_area} m²")
            if fault_label:
                print(f"   Fault     : {fault_label} ({s.fault})")


async def cmd_consumables(duid: str | None, as_json: bool = False):
    # *_LIFE = HOURS OF USE (confirmed 2026-06-12 against the app: DP value matched the
    # app's "N h"). The app derives % remaining from standard lifetimes; sensor/mop/dust
    # are "as needed" in the app (no fixed lifetime), so no % is shown for the sensor.
    LIFETIME_H = {"main_brush": 300, "side_brush": 200, "filter": 150}
    async with device_session(duid) as (_device, props):
        s = await fetch_status(props)
        used = {"main_brush": s.main_brush_life, "side_brush": s.side_brush_life,
                "filter": s.filter_life, "sensor": s.sensor_life}

        def pct_left(key):
            h = used[key]
            if h is None or key not in LIFETIME_H:
                return None
            return max(0, round(100 * (LIFETIME_H[key] - h) / LIFETIME_H[key]))

        if as_json:
            print(json.dumps({
                k: {"hours_used": used[k], "pct_remaining": pct_left(k)} for k in used
            }))
        else:
            print("Consumables (hours used · % remaining):")
            for key, label in (("main_brush", "Main brush"), ("side_brush", "Side brush"),
                               ("filter", "Filter"), ("sensor", "Sensor")):
                h = used[key]
                p = pct_left(key)
                hs = f"{h} h" if h is not None else "—"
                ps = f"· {p}% left" if p is not None else "· (as needed)"
                print(f"  {label:<11}: {hs:<6} {ps}")


# ── CLEAN_RECORD decode (shared: live history + --from-capture) ─────────────────
# 12 underscore fields, field map cross-validated against an 18-record corpus
# (DECISIONS s24): 2=dur_min, 5=area×1000, 8=mode, 10=pass, 11=ok are solid; 7=water
# (vacuum→0; 4=possible "custom" level); 3≈0.55×dur; 6=monotonic accumulator (not a
# clean attribute, so not surfaced).
_CR_WATER = {0: "off", 1: "low", 2: "medium", 3: "high", 4: "custom"}
_CR_MODE  = {1: "vac_and_mop", 2: "vacuum", 3: "mop", 4: "customized"}
_CR_ROUTE = {0: "fast", 1: "daily", 2: "fine"}


def _decode_clean_record(raw: str) -> dict | None:
    parts = raw.split("_")
    if len(parts) != 12:
        return None
    try:
        return {
            "id": parts[0],
            "started": datetime.fromtimestamp(int(parts[1])).strftime("%Y-%m-%d %H:%M"),
            "duration_min": int(parts[2]),
            "area_m2": round(int(parts[5]) / 1000, 3),
            "water": _CR_WATER.get(int(parts[7]), parts[7]),
            "mode": _CR_MODE.get(int(parts[8]), parts[8]),
            "route": _CR_ROUTE.get(int(parts[9]), parts[9]),
            "passes": int(parts[10]),
            "ok": int(parts[11]) == 1,
        }
    except (ValueError, IndexError):
        return None


def _print_clean_history(records, as_json):
    records.sort(key=lambda r: r["started"], reverse=True)
    if as_json:
        print(json.dumps(records, indent=2))
        return
    hdr = f"{'Started':<16}  {'Dur':>5}  {'Area':>8}  {'Water':<7}  {'Mode':<12}  {'Route':<5}  {'Pass':>4}  OK"
    print(hdr)
    print("-" * len(hdr))
    for r in records:
        print(f"{r['started']:<16}  {r['duration_min']:>4}m  {r['area_m2']:>7.3f}m²  "
              f"{r['water']:<7}  {r['mode']:<12}  {r['route']:<5}  {r['passes']:>4}  {'✓' if r['ok'] else '✗'}")


def cmd_history_from_capture(path: str, as_json: bool = False):
    """Decode the clean history from a capture file — NO live session.

    Reads CLEAN_RECORD `op:list` `data[]` + `op:notify`/status `id` strings. The robot
    broadcasts its op:list reply on the device topic, so a `watch`/`daemon record` capture
    taken WHILE the phone app opens its History screen contains the full back-catalog.
    """
    seen: dict[str, dict] = {}
    records: list[dict] = []

    def _harvest(cr):
        if not isinstance(cr, dict):
            return
        ids = [s for s in cr.get("data", []) if isinstance(s, str)] if isinstance(cr.get("data"), list) else []
        if isinstance(cr.get("id"), str):
            ids.append(cr["id"])
        for s in ids:
            key = "_".join(s.split("_")[:2])    # dedupe by id+epoch
            if key not in seen:
                rec = _decode_clean_record(s)
                if rec:
                    seen[key] = rec
                    records.append(rec)

    try:
        fh = open(path)
    except OSError as e:
        sys.exit(f"Cannot read capture: {e}")
    with fh:
        for line in fh:
            if "CLEAN_RECORD" not in line:
                continue
            try:
                j = json.loads(line)
            except Exception:
                continue
            stack = [j]                          # CLEAN_RECORD may be nested under dps/etc.
            while stack:
                o = stack.pop()
                if isinstance(o, dict):
                    if "CLEAN_RECORD" in o:
                        _harvest(o["CLEAN_RECORD"])
                    stack.extend(o.values())
                elif isinstance(o, list):
                    stack.extend(o)
    if not records:
        print(f"No CLEAN_RECORD entries found in {path}.")
        return
    print(f"Recovered {len(records)} clean record(s) from {path}:")
    _print_clean_history(records, as_json)


async def cmd_history(duid: str | None, as_json: bool = False, timeout: int = 15):
    # The op:list REQUEST is app/push-only — a vac.py op:list send gets no reply (DECISIONS
    # s22–s24). The 12-field parser IS validated (18-record corpus). For the back-catalog
    # offline, use `--from-capture` on a watch/echo capture taken while the app shows History.
    print("NOTE: live `history` (op:list pull) is not working yet — the robot pushes the list to the"
          " app, not to a vac.py request. Use `./vac.py history --from-capture <watch.jsonl>`. (TASKS #13)")

    records: list[dict] = []
    seen: set[str] = set()
    got = asyncio.Event()

    async with device_session(duid) as (device, props):
        print(f"Fetching history from {device.name}…")

        async def collect():
            async for dps in stream_decoded_responses(props._channel):
                cr = dps.get(B01_Q10_DP.CLEAN_RECORD)
                if not (isinstance(cr, dict) and cr.get("op") == "list"
                        and isinstance(cr.get("data"), list)):
                    continue
                for raw in cr["data"]:
                    if isinstance(raw, str) and raw not in seen:
                        seen.add(raw)
                        rec = _decode_clean_record(raw)
                        if rec:
                            records.append(rec)
                got.set()

        async def trigger():
            try:
                for _ in range(3):
                    if got.is_set():
                        return
                    try:
                        await props.command.send(B01_Q10_DP.CLEAN_RECORD, {"op": "list"})
                    except Exception:
                        pass
                    await asyncio.sleep(4)
            except asyncio.CancelledError:
                pass

        ct = asyncio.create_task(collect())
        tt = asyncio.create_task(trigger())
        try:
            await asyncio.wait_for(got.wait(), timeout=timeout)
        except (asyncio.TimeoutError, KeyboardInterrupt):
            pass
        finally:
            ct.cancel()
            tt.cancel()

    if not records:
        print("No history received — the op:list pull is app/push-only; use --from-capture.")
        return
    _print_clean_history(records, as_json)


async def cmd_watch(duid: str | None, out_path: str | None, interval: int):
    """Hold one MQTT session open and stream telemetry until interrupted.

    While cleaning, the robot pushes status frames on its own; we log every push
    as it arrives. A periodic refresh() acts as a keepalive/poll so the log keeps
    flowing even if the device goes quiet (e.g. when it pauses or docks).
    """
    # Raw values are logged (clean_area undivided) so the capture is faithful for
    # later analysis — see ROADMAP.md re: unit verification.
    cols = ["time", "elapsed_s", "state", "battery", "fan", "water", "mode",
            "clean_time_s", "clean_area_raw", "progress_pct", "eta_min",
            "batt_to_finish", "fault"]
    write_header = out_path and not pathlib.Path(out_path).exists()
    csv_file = open(out_path, "a") if out_path else None
    if csv_file and write_header:
        csv_file.write(",".join(cols) + "\n")
        csv_file.flush()

    # Anchor sample for the live projection: the first frame with progress>0 and a
    # battery reading. We fit a straight line from the anchor to the latest frame
    # (using the device's task-clock, clean_time, not wall-clock — it pauses when
    # the robot docks/charges). Progress isn't perfectly linear (big rooms clean
    # first), so ETA is indicative, not a stopwatch.
    anchor = {}  # {"ct","progress","battery"}

    def project(ct, progress, battery):
        if progress is None or battery is None or ct is None:
            return None, None
        if not anchor:
            if progress > 0:
                anchor.update(ct=ct, progress=progress, battery=battery)
            return None, None
        dct = ct - anchor["ct"]
        dprog = progress - anchor["progress"]
        if dct <= 0 or dprog <= 0:
            return None, None
        prog_rate = dprog / dct                       # %/sec
        drain_rate = (anchor["battery"] - battery) / dct  # %batt/sec
        eta_sec = (100 - progress) / prog_rate
        batt_needed = eta_sec * drain_rate
        return eta_sec / 60, batt_needed

    async with device_session(duid) as (device, props):
        start = datetime.now()
        print(f"Watching {device.name} — Ctrl-C to stop"
              + (f", logging to {out_path}" if out_path else ""))
        print(f"{'time':8}  {'elapsed':>7}  {'state':<16} {'bat':>4} {'fan':<9} "
              f"{'water':<7} {'mode':<11} {'clean':>7}  {'prog':>4}  {'eta':>11}")

        def on_update():
            s = props.status
            now = datetime.now()
            elapsed = (now - start).total_seconds()
            state = s.status.name.lower() if s.status else "?"
            fan = s.fan_level.name.lower() if s.fan_level else "?"
            water = s.water_level.name.lower() if s.water_level else "?"
            mode = s.clean_mode.name.lower() if s.clean_mode else "?"
            ct = s.clean_time or 0
            prog = s.cleaning_progress
            eta_min, batt_needed = project(s.clean_time, prog, s.battery)
            prog_s = f"{prog}%" if prog is not None else "?"
            if eta_min is not None:
                short = batt_needed > (s.battery or 0)  # won't finish on this charge
                eta_s = f"~{eta_min:4.0f}m {'⚠' if short else '✓'}{batt_needed:3.0f}%"
            else:
                eta_s = ""
            print(f"{now:%H:%M:%S}  {elapsed:7.1f}  {state:<16} "
                  f"{(s.battery if s.battery is not None else '?'):>3}% {fan:<9} "
                  f"{water:<7} {mode:<11} {ct // 60:>3}m{ct % 60:02d}s  {prog_s:>4}  {eta_s:>11}")
            if csv_file:
                row = [now.isoformat(timespec="seconds"), f"{elapsed:.1f}", state,
                       s.battery, fan, water, mode, ct, s.clean_area, prog,
                       f"{eta_min:.0f}" if eta_min is not None else None,
                       f"{batt_needed:.0f}" if batt_needed is not None else None,
                       s.fault]
                csv_file.write(",".join("" if v is None else str(v) for v in row) + "\n")
                csv_file.flush()

        remove = props.status.add_update_listener(on_update)
        try:
            await props.refresh()
            while True:
                await asyncio.sleep(interval)
                await props.refresh()
        except (KeyboardInterrupt, asyncio.CancelledError):
            pass
        finally:
            remove()
            if csv_file:
                csv_file.close()
                print(f"\nSaved telemetry to {out_path}")


async def cmd_watch_raw(duid: str | None, out_path: str | None, interval: int):
    """Capture EVERY decoded data-point the robot emits, not just status fields.

    Taps the device's decoded DPS stream one level below the StatusTrait (which
    models only 19 of ~114 data-points), so map/zone/record/schedule frames are
    captured too. Coexists with the device's own subscribe loop — the MQTT session
    fans one topic out to multiple listeners. JSON-per-frame to stdout and/or file.
    """

    out = open(out_path, "a") if out_path else None
    async with device_session(duid) as (device, props):
        start = datetime.now()
        print(f"Raw capture from {device.name} — every decoded data-point. Ctrl-C to stop"
              + (f", logging JSONL to {out_path}" if out_path else ""))

        async def keepalive():
            # REQUEST_DPS prompts the robot to dump everything; spontaneous pushes
            # arrive in between. Guards against silence when the robot is idle.
            try:
                while True:
                    await props.refresh()
                    await asyncio.sleep(interval)
            except asyncio.CancelledError:
                pass

        ka = asyncio.create_task(keepalive())
        frames = 0
        try:
            async for dps in stream_decoded_responses(props._channel):
                now = datetime.now()
                elapsed = (now - start).total_seconds()
                named = {(k.name if hasattr(k, "name") else str(k)): v for k, v in dps.items()}
                frames += 1
                print(f"[{now:%H:%M:%S} +{elapsed:6.1f}s] {len(named):>2} dp: "
                      f"{', '.join(named.keys())}")
                if out:
                    rec = {"time": now.isoformat(timespec="seconds"),
                           "elapsed_s": round(elapsed, 1), "dps": named}
                    out.write(json.dumps(rec, default=str) + "\n")
                    out.flush()
        except (KeyboardInterrupt, asyncio.CancelledError):
            pass
        finally:
            ka.cancel()
            if out:
                out.close()
                print(f"\nSaved {frames} frames to {out_path}")


def _classify_payload(payload):
    """Return (kind, body) for a raw MQTT payload — JSON if it parses, else base64."""
    import base64
    if isinstance(payload, (bytes, bytearray)):
        try:
            return "json", json.loads(payload.decode("utf-8"))
        except Exception:
            return "binary_b64", base64.b64encode(payload).decode("ascii")
    if isinstance(payload, str):
        try:
            return "json", json.loads(payload)
        except Exception:
            return "text", payload
    return "other", payload


async def cmd_watch_bytes(duid: str | None, out_path: str | None, interval: int):
    """Protocol-level tap: log EVERY RoborockMessage, decoded or not.

    One level below `watch --raw`. `--raw` taps the dps decoder, which silently
    drops any frame that isn't a JSON 'dps' message (it raises + `continue`s) —
    so binary frames like map_response (protocol 301) never reach it. This taps
    `subscribe_stream()` directly, capturing the raw RoborockMessage with its
    protocol tag and payload (JSON kept as-is, binary base64-encoded). This is the
    tool for catching map/zone data the OEM app triggers: we share the device's
    MQTT output topic, so robot responses to the app are broadcast to us too.
    """
    out = open(out_path, "a") if out_path else None
    async with device_session(duid) as (device, props):
        start = datetime.now()
        print(f"Byte-level capture from {device.name} — every MQTT frame (incl. binary). "
              f"Ctrl-C to stop" + (f", logging JSONL to {out_path}" if out_path else ""))
        print("Tip: now open the OEM app and view the map / tap around to trigger frames.")

        async def keepalive():
            try:
                while True:
                    await props.refresh()
                    await asyncio.sleep(interval)
            except asyncio.CancelledError:
                pass

        ka = asyncio.create_task(keepalive())
        frames = 0
        try:
            async for msg in props._channel.subscribe_stream():
                now = datetime.now()
                elapsed = (now - start).total_seconds()
                proto = msg.protocol
                pname = getattr(proto, "name", str(proto))
                pnum = getattr(proto, "value", proto)
                payload = msg.payload
                plen = len(payload) if payload is not None else 0
                kind, body = _classify_payload(payload)
                frames += 1
                # Flag the interesting non-dps frames loudly.
                flag = "  <-- NON-DPS" if kind != "json" or pnum not in (101, 102) else ""
                print(f"[{now:%H:%M:%S} +{elapsed:6.1f}s] proto={pnum}/{pname} "
                      f"len={plen:>5} {kind}{flag}")
                if out:
                    rec = {"time": now.isoformat(timespec="seconds"),
                           "elapsed_s": round(elapsed, 1),
                           "protocol": pname, "protocol_num": pnum,
                           "len": plen, "kind": kind, "payload": body}
                    out.write(json.dumps(rec, default=str) + "\n")
                    out.flush()
        except (KeyboardInterrupt, asyncio.CancelledError):
            pass
        finally:
            ka.cancel()
            if out:
                out.close()
                print(f"\nSaved {frames} frames to {out_path}")


async def cmd_map(duid: str | None, timeout: int = 30, out_prefix: str = "map"):
    """Capture live protocol-301 map frames and render the map.

    Taps the raw MQTT stream (like `watch --bytes`) and actively requests the map
    (MULTI_MAP), until it has a room-grid (`0101`) and/or path (`0201`) frame, or
    `timeout` elapses, then decodes/renders via decode_map.py. The room grid is
    available on demand (even docked); the path + live position only stream during a
    clean, so the path SVG is written only when a clean is active.

    `out_prefix` names the outputs: `<prefix>_rooms.png` (floor plan) and, when a
    clean is active, `<prefix>_path.svg` (route + position). Defaults to "map".
    """
    sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))
    import decode_map as dm

    best = {"grid": None, "path": None}
    async with device_session(duid) as (device, props):
        print(f"Capturing map frames from {device.name} (up to {timeout}s, Ctrl-C to stop)…")
        done = asyncio.Event()

        grace = {"task": None}

        async def collect():
            async for msg in props._channel.subscribe_stream():
                if getattr(msg.protocol, "value", msg.protocol) != 301:
                    continue
                payload = msg.payload
                if not payload:
                    continue
                # grid: match only the portable 2-byte sub-type prefix (bytes 2-5 are a
                # device-specific map id). path: full sig (its tail looks like fixed fields).
                if payload[:2].hex() == dm.GRID_PREFIX and (best["grid"] is None or len(payload) > len(best["grid"])):
                    best["grid"] = payload
                elif payload[:8].hex() == dm.PATH_SIG and (best["path"] is None or len(payload) > len(best["path"])):
                    best["path"] = payload
                if best["grid"] and best["path"]:
                    done.set()
                    return
                # Got the grid but no path yet — give the path a short window (it only
                # streams mid-clean), then finish so we don't sit out the whole timeout.
                if best["grid"] and grace["task"] is None:
                    async def finish():
                        await asyncio.sleep(6)
                        done.set()
                    grace["task"] = asyncio.create_task(finish())

        async def trigger():
            # Actively REQUEST the map (MULTI_MAP {"op":"list"}) so it arrives on demand —
            # the room grid streams even while docked/idle, not just mid-clean. refresh()
            # is a keepalive; the path (0201) only streams during an active clean.
            try:
                while not done.is_set():
                    try:
                        await props.command.send(B01_Q10_DP.MULTI_MAP, {"op": "list"})
                    except Exception:
                        pass
                    await props.refresh()
                    await asyncio.sleep(4)
            except asyncio.CancelledError:
                pass

        ct = asyncio.create_task(collect())
        tt = asyncio.create_task(trigger())
        try:
            await asyncio.wait_for(done.wait(), timeout=timeout)
        except (asyncio.TimeoutError, KeyboardInterrupt):
            pass
        finally:
            ct.cancel()
            tt.cancel()
            if grace["task"]:
                grace["task"].cancel()

    if not best["grid"] and not best["path"]:
        print("No map frames received — the robot may be offline. Try again.")
        return
    path_out = f"{out_prefix}_path.svg"
    rooms_out = f"{out_prefix}_rooms.png"
    if best["path"]:
        pts, _ = dm.parse_path(best["path"])
        pts = dm._drop_path_outlier(pts)   # strip the spurious leading sentinel (green-dot bug) — parity with decode_map.py; band-aid, OPEN QUESTION per DECISIONS s24
        if pts:
            with open(path_out, "w") as f:
                f.write(dm.render_path_svg(pts))
            print(f"  Robot position: {pts[-1]}  ·  path → {path_out}")
        else:
            print("  Path frame had no usable points after sentinel strip — skipping path render.")
    if best["grid"]:
        out = dm.decompress_grid(best["grid"])
        rooms, glen = dm.parse_rooms(out)
        grid = out[:glen]
        w, h = dm.find_width(grid)
        dm.render_grid_png(grid, w, h, rooms).save(rooms_out)
        names = ", ".join(rooms[r].replace("rr_", "") for r in sorted(rooms))
        print(f"  Rooms ({w}x{h}): {names}")
        print(f"  floor plan → {rooms_out}")


async def _capture_grid(props, timeout: int = 25):
    """Tap the 301 stream until a room-grid frame arrives; return its raw bytes.

    Matches only the portable `0101` sub-type prefix (bytes 2-5 are a device-specific
    map id, so the full 8-byte signature is NOT portable).
    """
    best = {"grid": None}
    done = asyncio.Event()

    async def collect():
        async for msg in props._channel.subscribe_stream():
            if getattr(msg.protocol, "value", msg.protocol) != 301:
                continue
            p = msg.payload
            if p and p[:2].hex() == "0101" and (best["grid"] is None or len(p) > len(best["grid"])):
                best["grid"] = p
                done.set()
                return

    async def trigger():
        try:
            while not done.is_set():
                try:
                    await props.command.send(B01_Q10_DP.MULTI_MAP, {"op": "list"})
                except Exception:
                    pass
                await props.refresh()
                await asyncio.sleep(4)
        except asyncio.CancelledError:
            pass

    ct = asyncio.create_task(collect())
    tt = asyncio.create_task(trigger())
    try:
        await asyncio.wait_for(done.wait(), timeout=timeout)
    except asyncio.TimeoutError:
        pass
    finally:
        ct.cancel()
        tt.cancel()
    return best["grid"]


def _room_directory(grid_raw):
    """Decode the room grid → {room_id: name}."""
    sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))
    import decode_map as dm
    return dm.parse_rooms(dm.decompress_grid(grid_raw))[0]


async def cmd_rooms(duid: str | None):
    async with device_session(duid) as (_device, props):
        grid = await _capture_grid(props)
        if not grid:
            print("No map frame received (try again, or during/after a clean).")
            return
        rooms = _room_directory(grid)
        print("Rooms on the current map (use name or id with `clean-rooms`):")
        for rid in sorted(rooms):
            print(f"  {rid}  {rooms[rid].replace('rr_', '')}")


async def cmd_clean_rooms(room_args: list[str], duid: str | None):
    """Start a room-selective clean via a one-time REST /jobs POST (TASKS #8).

    Posts a one-time schedule ~2 min from now so the robot starts in ~2 min.
    Use --dry-run to validate the POST end-to-end without moving the robot
    (posts the job, confirms it appears in list, then deletes it before it fires).
    """
    import struct as _struct
    from datetime import datetime, timedelta

    # Parse optional flags out of room_args
    def _pop(flag: str) -> str | None:
        if flag in room_args:
            i = room_args.index(flag)
            val = room_args[i + 1] if i + 1 < len(room_args) else None
            room_args[i:i + 2] = []
            return val
        return None

    room_args = list(room_args)
    dry_run   = "--dry-run" in room_args
    if dry_run:
        room_args.remove("--dry-run")
    fan_s   = _pop("--fan")
    water_s = _pop("--water")
    mode_s  = _pop("--mode")
    route_s = _pop("--route")
    count_s = _pop("--count")

    fan_code   = _rest_fan_code(fan_s) if fan_s else 3
    water_code = _resolve_enum(YXWaterLevel, water_s, "water level").code if water_s else 2
    mode_code  = _resolve_enum(YXCleanType,  mode_s,  "mode").code if mode_s else 1
    route_code  = _resolve_enum(YXCleanLine, route_s, "route").code if route_s else YXCleanLine.FAST.code
    clean_count = int(count_s) if count_s else 1

    if not room_args:
        sys.exit("Usage: ./vac.py clean-rooms <name|id>...  [options]  (see ./vac.py rooms)")

    creds = require_creds()

    # Phase 1: get duid + (only if needed) the room grid.
    # N02: room *names* need a live map frame to resolve; pure numeric ids don't. When every
    # arg is numeric we skip the grid capture, and open a minimal (silent, read-only) device
    # session only if we still need the duid. The grid is captured lazily later as a mapId
    # fallback if the existing jobs list doesn't already carry one.
    all_numeric = all(r.isdigit() for r in room_args)
    _duid = duid
    grid = None
    if not _duid or not all_numeric:
        async with device_session(duid) as (device, props):
            _duid = device.duid
            if not all_numeric:
                grid = await _capture_grid(props)
                if not grid:
                    sys.exit("Couldn't read the room map (no map frame). Try again.")

    rooms_map: dict[int, str] = {}
    ids: list[int] = []
    if all_numeric:
        ids = [int(r) for r in room_args]
    else:
        rooms_map = _room_directory(grid)
        name_to_ids: dict[str, list[int]] = {}
        for rid, name in rooms_map.items():
            name_to_ids.setdefault(name.replace("rr_", "").lower(), []).append(rid)
        for r in room_args:
            if r.isdigit():
                ids.append(int(r))
            elif r.lower() in name_to_ids:
                matched = name_to_ids[r.lower()]
                if len(matched) > 1:
                    # N01: a name can resolve to multiple rooms (e.g. two "toilet" rooms).
                    # Clean all of them, but say so — otherwise it's a silent surprise.
                    id_list = ", ".join(str(i) for i in matched)
                    print(f"Note: '{r}' matched {len(matched)} rooms (ids {id_list}); "
                          f"cleaning all. Use a numeric id to target just one.")
                ids.extend(matched)
            else:
                opts = ", ".join(sorted(name_to_ids))
                sys.exit(f"Unknown room '{r}'. Available: {opts} (or a numeric id). See ./vac.py rooms")
    ids = sorted(set(ids))
    labels = ", ".join(rooms_map.get(i, str(i)).replace("rr_", "") for i in ids)

    # Phase 2: REST /jobs POST (outside MQTT session)
    jobs_path = f"/user/devices/{_duid}/jobs"
    existing = await _schedule_request("GET", jobs_path, creds) or []
    map_id = next(
        (j["param"]["mapId"] for j in existing if (j.get("param") or {}).get("mapId")),
        None,
    )
    if map_id is None:
        if grid is None:
            # mapId not in the jobs list and we skipped the grid (N02) — capture it now (silent read).
            async with device_session(_duid) as (_, props):
                grid = await _capture_grid(props)
            if not grid:
                sys.exit("Couldn't read the room map (no map frame). Try again.")
        map_id = _struct.unpack(">I", grid[2:6])[0]

    # One-time cron a couple minutes out. A --dry-run posts the job DISABLED so it can
    # NEVER fire regardless of delete success/timing (the scheduler skips enabled:false
    # jobs) — this kills the delete-vs-fire race at the source (DECISIONS s18/s19), so a
    # real clean can use a short, prompt lead instead of a wide 5-min safety window.
    lead = 2
    fire = datetime.now() + timedelta(minutes=lead)
    cron = f"{fire.minute:02d} {fire.hour:02d} {fire.day} {fire.month} ?"

    body = {
        "id": "",
        "cron": cron,
        "repeated": False,
        "enabled": not dry_run,
        "param": {
            "mapId": map_id,
            "cleanRoute": route_code,
            "fanLevel": fan_code,
            "cleanMode": mode_code,
            "rooms": ids,
            "roomCount": len(ids),
            "waterLevel": water_code,
            "cleanCount": clean_count,
        },
    }

    existing_ids = {j["id"] for j in existing}
    await _schedule_request("POST", jobs_path, creds, body=body)
    # POST returns "done" — find the new job by diffing before/after
    updated = await _schedule_request("GET", jobs_path, creds) or []
    new_jobs = [j for j in updated if j["id"] not in existing_ids]
    job_id = new_jobs[0]["id"] if new_jobs else None

    if dry_run:
        if job_id:
            await _schedule_request("DELETE", f"{jobs_path}/{job_id}", creds)
        print(f"✓ Dry-run: POST 200 · job {job_id} created DISABLED (cannot fire) · "
              f"found in list · deleted.")
        return

    job_info = f" (job {job_id})" if job_id else ""
    print(f"✓ Room clean scheduled{job_info}: {labels}  →  fires in ~{lead} min  "
          f"[fan={fan_code} water={water_code} mode={mode_code} route={route_code}]")


# ── schedule REST API ────────────────────────────────────────────────────────

async def _schedule_request(method: str, path: str, creds: "Creds", body=None):
    """Authenticated REST call to Roborock API using Hawk auth."""
    import aiohttp
    user_data = UserData.from_dict(creds.user_data)
    rriot = user_data.rriot
    base_url = rriot.r.a.rstrip("/")
    # PUT/POST: sign compact JSON body; GET/DELETE: sign path only
    auth = _hawk_auth(rriot, path, json_body=body if body is not None else None)
    kw: dict = {"headers": {"Authorization": auth}}
    if body is not None:
        # Send compact JSON (no spaces) — must match the bytes we signed
        compact = json.dumps(body, separators=(',', ':'))
        kw["data"] = compact.encode()
        kw["headers"]["Content-Type"] = "application/json"
    async with aiohttp.ClientSession() as session:
        async with session.request(method, base_url + path, **kw) as resp:
            data = await resp.json()
    if not data.get("success"):
        sys.exit(f"Schedule API error: {data}")
    return data.get("result")


def _cron_string(time_str: str, days: str | None, once: bool) -> str:
    """Build a 5-field cron expression (MM HH DOM MON DOW) from CLI flags."""
    h, m = map(int, time_str.split(":"))
    if once:
        from datetime import date, timedelta, datetime as _dt
        now = _dt.now()
        d = date.today() if (now.hour, now.minute) < (h, m) else date.today() + timedelta(days=1)
        return f"{m:02d} {h:02d} {d.day} {d.month} ?"
    if days:
        _day = {"mon": "MON", "tue": "TUE", "wed": "WED", "thu": "THU",
                "fri": "FRI", "sat": "SAT", "sun": "SUN"}
        dow = ",".join(_day[d.strip().lower()[:3]] for d in days.split(","))
        return f"{m:02d} {h:02d} ? * {dow}"
    return f"{m:02d} {h:02d} * * ?"


def _describe_cron(cron: str) -> str:
    """Short human-readable summary of a cron string."""
    parts = cron.split()
    if len(parts) != 5:
        return cron
    m, h, dom, mon, dow = parts
    t = f"{int(h):02d}:{int(m):02d}"
    if dom == "?" :
        return f"weekly({dow}) {t}"
    if dom == "*":
        return f"daily {t}"
    return f"once {mon}/{dom} {t}"


async def cmd_schedule(sub: str, rest: list[str], duid: str | None, as_json: bool):
    creds = require_creds()

    async def _resolve_duid() -> str:
        """Return duid from arg or by opening a minimal device session."""
        if duid:
            return duid
        async with device_session(None) as (dev, _):
            return dev.duid

    if sub == "list":
        _duid = await _resolve_duid()
        path = f"/user/devices/{_duid}/jobs"
        jobs = await _schedule_request("GET", path, creds) or []
        if as_json:
            print(json.dumps(jobs, indent=2))
            return
        if not jobs:
            print("No schedules.")
            return
        for j in jobs:
            p = j.get("param") or {}
            rooms = p.get("rooms") or []
            room_s = f"rooms={rooms}" if rooms else "full clean"
            fan = p.get("fanLevel", "?")
            water = p.get("waterLevel", "?")
            flag = "✓" if j.get("enabled") else "✗"
            print(f"  {flag} [{j['id']}]  {_describe_cron(j['cron'])}  "
                  f"{room_s}  fan={fan} water={water}")
        return

    if sub in ("enable", "disable"):
        job_id = rest[0] if rest else None
        if not job_id:
            sys.exit(f"Usage: ./vac.py schedule {sub} <id>")
        _duid = await _resolve_duid()
        path = f"/user/devices/{_duid}/jobs"
        jobs = await _schedule_request("GET", path, creds) or []
        job = next((j for j in jobs if str(j["id"]) == job_id), None)
        if not job:
            sys.exit(f"Schedule {job_id} not found. "
                     f"Available ids: {[j['id'] for j in jobs]}")
        body = {k: v for k, v in job.items() if k not in ("id", "timeZoneId")}
        body["enabled"] = (sub == "enable")
        await _schedule_request("PUT", f"{path}/{job_id}", creds, body=body)
        print(f"Schedule {job_id} {'enabled' if sub == 'enable' else 'disabled'}.")
        return

    if sub == "delete":
        job_id = rest[0] if rest else None
        if not job_id:
            sys.exit("Usage: ./vac.py schedule delete <id>")
        _duid = await _resolve_duid()
        path = f"/user/devices/{_duid}/jobs/{job_id}"
        await _schedule_request("DELETE", path, creds)
        print(f"Schedule {job_id} deleted.")
        return

    if sub == "add":
        if "--time" not in rest:
            sys.exit("Usage: ./vac.py schedule add --time HH:MM [options]  (see --help)")
        time_str  = rest[rest.index("--time")  + 1]
        days      = rest[rest.index("--days")  + 1] if "--days"   in rest else None
        once      = "--once" in rest
        fan_s     = rest[rest.index("--fan")   + 1] if "--fan"    in rest else None
        water_s   = rest[rest.index("--water") + 1] if "--water"  in rest else None
        mode_s    = rest[rest.index("--mode")  + 1] if "--mode"   in rest else None
        route_s   = rest[rest.index("--route") + 1] if "--route"  in rest else None
        passes_s  = rest[rest.index("--passes")+ 1] if "--passes" in rest else None
        room_args: list[str] = []
        if "--rooms" in rest:
            i = rest.index("--rooms") + 1
            while i < len(rest) and not rest[i].startswith("--"):
                room_args.append(rest[i]); i += 1

        fan_code   = _rest_fan_code(fan_s) if fan_s else 3
        water_code = _resolve_enum(YXWaterLevel, water_s, "water level").code if water_s else 2
        mode_code  = _resolve_enum(YXCleanType,  mode_s,  "mode").code if mode_s else 1
        route_code  = _resolve_enum(YXCleanLine, route_s, "route").code if route_s else YXCleanLine.FAST.code
        passes     = int(passes_s) if passes_s else 1
        cron       = _cron_string(time_str, days, once)

        # Phase 1: device session — only to get duid and optionally capture the
        # room grid. Close the MQTT session before any REST write calls.
        import struct
        _duid = duid
        grid = None
        need_grid = bool(room_args)
        if not _duid or need_grid:
            async with device_session(duid) as (device, props):
                _duid = device.duid
                if need_grid:
                    grid = await _capture_grid(props)
                    if not grid:
                        sys.exit("Couldn't read the room map. Try again during/after a clean.")

        # Phase 2: REST calls outside the MQTT session.
        jobs_path = f"/user/devices/{_duid}/jobs"
        existing  = await _schedule_request("GET", jobs_path, creds) or []
        map_id = next(
            (j["param"]["mapId"] for j in existing if (j.get("param") or {}).get("mapId")),
            None,
        )

        room_ids: list[int] = []
        if map_id is None:
            if grid is None:
                # Need grid just for mapId; open a second brief session.
                async with device_session(_duid) as (_, props):
                    grid = await _capture_grid(props)
                if not grid:
                    sys.exit("Couldn't read the room map. Try again during/after a clean.")
            map_id = struct.unpack(">I", grid[2:6])[0]

        if room_args:
            if grid is None:
                sys.exit("Grid unavailable — cannot resolve room names.")
            rooms_map = _room_directory(grid)
            name_to_ids: dict[str, list[int]] = {}
            for rid, name in rooms_map.items():
                name_to_ids.setdefault(name.replace("rr_", "").lower(), []).append(rid)
            for r in room_args:
                if r.isdigit():
                    room_ids.append(int(r))
                elif r.lower() in name_to_ids:
                    matched = name_to_ids[r.lower()]
                    if len(matched) > 1:
                        # N01: name resolves to >1 room — schedule all of them, but say so.
                        id_list = ", ".join(str(i) for i in matched)
                        print(f"Note: '{r}' matched {len(matched)} rooms (ids {id_list}); "
                              f"scheduling all. Use a numeric id to target just one.")
                    room_ids.extend(matched)
                else:
                    sys.exit(f"Unknown room '{r}'. "
                             f"Available: {', '.join(sorted(name_to_ids))}. "
                             "See ./vac.py rooms")
            room_ids = sorted(set(room_ids))

        body = {
            "id": "",
            "cron": cron,
            "repeated": not once,
            "enabled": True,
            "param": {
                "mapId": map_id,
                "cleanRoute": route_code,
                "fanLevel": fan_code,
                "cleanMode": mode_code,
                "rooms": room_ids,
                "roomCount": len(room_ids),
                "waterLevel": water_code,
                "cleanCount": passes,
            },
        }
        await _schedule_request("POST", jobs_path, creds, body=body)

        room_label = f" rooms={room_ids}" if room_ids else " full clean"
        print(f"Schedule created: {_describe_cron(cron)}{room_label}")
        return

    sys.exit(f"Unknown schedule subcommand '{sub}'. "
             "Use: list, enable, disable, delete, add")


# ── action commands ───────────────────────────────────────────────────────────
# Each is a thin wrapper over run_action(); the lifecycle lives in device_session.

async def cmd_start(duid):
    await run_action(lambda p: p.vacuum.start_clean(), "Cleaning started.", duid)


async def cmd_stop(duid):
    await run_action(lambda p: p.vacuum.stop_clean(), "Stopped.", duid)


async def cmd_pause(duid):
    await run_action(lambda p: p.vacuum.pause_clean(), "Paused.", duid)


async def cmd_resume(duid):
    await run_action(lambda p: p.vacuum.resume_clean(), "Resumed.", duid)


async def cmd_dock(duid):
    await run_action(lambda p: p.vacuum.return_to_dock(), "Returning to dock.", duid)


async def cmd_dock_empty(duid):
    await run_action(lambda p: p.vacuum.empty_dustbin(), "Auto-empty triggered.", duid)


async def cmd_find(duid):
    await run_action(lambda p: p.command.send(B01_Q10_DP.SEEK, {}), "Locate signal sent.", duid)


def _resolve_enum(enum_cls, value: str, label: str):
    """Map a user string to an enum member, exiting with the valid options."""
    member = next((m for m in enum_cls if m.name.lower() == value.lower()), None)
    if member is None or member.name == "UNKNOWN":
        options = [m.name.lower() for m in enum_cls if m.name != "UNKNOWN"]
        sys.exit(f"Unknown {label} '{value}'. Choose: {', '.join(options)}")
    return member


# ── B01 FIX — REST /jobs fan-level scale ──────────────────────────────────────
# The MQTT `YXFanLevel` enum has a gap (max=4, then max_plus=8), but the REST /jobs
# API uses a compact contiguous 0–5 scale. Every captured /jobs body shows fan ∈
# {2,3,4,5}, never 8; codes 2/3/4 match the library 1:1 (balanced/turbo/max) and the
# app's stored "Max+" job (4818761) carries fanLevel=5. So `max_plus` must map to 5
# for REST — resolving it through `.code` would post 8, out of range → wrong/rejected
# suction on the headline feature. Fan codes 1–4 already match, so only max_plus needs
# remapping. (QA B01 / coord O21#1, O24: read-only contiguity evidence, ~90–95% conf;
# a live "set app to Max+" /jobs capture would make it certain but is not required.)
_REST_FAN_OVERRIDE = {"max_plus": 5}

def _rest_fan_code(fan_s: str) -> int:
    """REST /jobs fan code (contiguous 0–5), not the gapped MQTT YXFanLevel enum."""
    member = _resolve_enum(YXFanLevel, fan_s, "fan level")
    return _REST_FAN_OVERRIDE.get(member.name.lower(), member.code)
# ──────────────────────────────────────────────────────────────────────────────


async def cmd_fan(level: str, duid):
    lvl = _resolve_enum(YXFanLevel, level, "fan level")
    await run_action(lambda p: p.vacuum.set_fan_level(lvl), f"Fan set to {lvl.name.lower()}.", duid)


async def cmd_water(level: str, duid):
    lvl = _resolve_enum(YXWaterLevel, level, "water level")
    await run_action(
        lambda p: p.command.send(B01_Q10_DP.WATER_LEVEL, lvl.code),
        f"Water set to {lvl.name.lower()}.", duid,
    )


async def cmd_mode(mode: str, duid):
    m = _resolve_enum(YXCleanType, mode, "mode")
    await run_action(lambda p: p.vacuum.set_clean_mode(m), f"Mode set to {m.name.lower()}.", duid)


async def cmd_dnd(state: str, start: str | None, end: str | None, duid):
    if state == "off":
        await run_action(
            lambda p: p.command.send(B01_Q10_DP.NOT_DISTURB, 0),
            "Do Not Disturb disabled.", duid,
        )
        return
    if state != "on":
        sys.exit("Usage: ./vac.py dnd <on|off> [--start HH:MM] [--end HH:MM]")
    sh, sm = map(int, (start or "22:00").split(":"))
    eh, em = map(int, (end or "08:00").split(":"))
    payload = {"enable": 1, "startHour": sh, "startMinute": sm, "endHour": eh, "endMinute": em}
    await run_action(
        lambda p: p.command.send(B01_Q10_DP.NOT_DISTURB_DATA, payload),
        f"DND enabled: {sh:02d}:{sm:02d}–{eh:02d}:{em:02d}", duid,
    )


async def cmd_volume(level: str, duid):
    try:
        v = int(level)
        if not 0 <= v <= 100:
            raise ValueError
    except ValueError:
        sys.exit("Usage: ./vac.py volume <0-100>")
    await run_action(
        lambda p: p.command.send(B01_Q10_DP.VOLUME, v),
        f"Volume set to {v}.", duid, caveat=CLOUD_REVERT_NOTE,
    )


async def cmd_child_lock(state: str, duid):
    if state not in ("on", "off"):
        sys.exit("Usage: ./vac.py child-lock <on|off>")
    val = 1 if state == "on" else 0
    await run_action(
        lambda p: p.command.send(B01_Q10_DP.CHILD_LOCK, val),
        f"Child lock {'enabled' if val else 'disabled'}.", duid, caveat=CLOUD_REVERT_NOTE,
    )


async def cmd_boost(state: str, duid):
    if state not in ("on", "off"):
        sys.exit("Usage: ./vac.py boost <on|off>")
    val = 1 if state == "on" else 0
    await run_action(
        lambda p: p.command.send(B01_Q10_DP.AUTO_BOOST, val),
        f"Auto-boost {'enabled' if val else 'disabled'}.", duid, caveat=CLOUD_REVERT_NOTE,
    )


async def cmd_raw(dp_name: str, value_json: str | None, duid: str | None):
    try:
        dp = B01_Q10_DP[dp_name.upper()]
    except KeyError:
        available = "\n  ".join(d.name for d in B01_Q10_DP)
        sys.exit(f"Unknown DP '{dp_name}'. Available:\n  {available}")
    value = json.loads(value_json) if value_json else {}
    async with device_session(duid) as (_device, props):
        try:
            result = await asyncio.wait_for(props.command.send(dp, value), timeout=ACTION_TIMEOUT)
            print(json.dumps(result, indent=2, default=str) if result is not None else "Sent (no response).")
        except asyncio.TimeoutError:
            print("Command timed out (fire-and-forget commands return no response).")


async def cmd_login(email: str):
    client = RoborockApiClient(email)
    await client.request_code()
    code = input("Enter the 6-digit code sent to your email: ").strip()
    user_data = await client.code_login(code)
    base_url = getattr(getattr(client, "_iot_login_info", None), "base_url", None)
    save_creds(Creds(email=email, user_data=user_data.as_dict(), base_url=base_url))
    print(f"Login OK. Credentials saved to {CREDS_FILE}")
    print("Now run:  ./vac.py discover")


# ── CLI ───────────────────────────────────────────────────────────────────────

# ── daemon: command routing shared with the standalone path ─────────────────────
# Awaits exactly ONE command coroutine against whatever session device_session
# yields (the daemon's held one, or a fresh --force one). Usage guards mirror main()
# so a bad request returns a clean error instead of an IndexError. KEEP the command
# set in sync with main()'s dispatch + the daemon's read-only/stream classification.
_SIMPLE_CMDS = ("start", "stop", "pause", "resume", "dock", "dock-empty", "find")


async def _run_one(cmd, rest, duid, as_json):
    if cmd == "status":            await cmd_status(duid, as_json)
    elif cmd == "discover":        await cmd_discover(duid, as_json)
    elif cmd == "consumables":     await cmd_consumables(duid, as_json)
    elif cmd == "history":         await cmd_history(duid, as_json)
    elif cmd == "rooms":           await cmd_rooms(duid)
    elif cmd == "map":
        timeout = int(rest[rest.index("--timeout") + 1]) if "--timeout" in rest else 30
        out_prefix = rest[rest.index("--out") + 1] if "--out" in rest else "map"
        await cmd_map(duid, timeout, out_prefix)
    elif cmd in _SIMPLE_CMDS:
        await {"start": cmd_start, "stop": cmd_stop, "pause": cmd_pause,
               "resume": cmd_resume, "dock": cmd_dock, "dock-empty": cmd_dock_empty,
               "find": cmd_find}[cmd](duid)
    elif cmd == "fan":
        if not rest: sys.exit("Usage: ./vac.py fan <quiet|balanced|turbo|max|max_plus>")
        await cmd_fan(rest[0], duid)
    elif cmd == "water":
        if not rest: sys.exit("Usage: ./vac.py water <off|low|medium|high>")
        await cmd_water(rest[0], duid)
    elif cmd == "mode":
        if not rest: sys.exit("Usage: ./vac.py mode <vac_and_mop|vacuum|mop>")
        await cmd_mode(rest[0], duid)
    elif cmd == "volume":
        if not rest: sys.exit("Usage: ./vac.py volume <0-100>")
        await cmd_volume(rest[0], duid)
    elif cmd == "child-lock":
        if not rest: sys.exit("Usage: ./vac.py child-lock <on|off>")
        await cmd_child_lock(rest[0], duid)
    elif cmd == "boost":
        if not rest: sys.exit("Usage: ./vac.py boost <on|off>")
        await cmd_boost(rest[0], duid)
    elif cmd == "dnd":
        if not rest: sys.exit("Usage: ./vac.py dnd <on|off> [--start HH:MM] [--end HH:MM]")
        start = rest[rest.index("--start") + 1] if "--start" in rest else None
        end = rest[rest.index("--end") + 1] if "--end" in rest else None
        await cmd_dnd(rest[0], start, end, duid)
    elif cmd == "clean-rooms":
        if not rest: sys.exit("Usage: ./vac.py clean-rooms <name|id>... [--dry-run] ...")
        await cmd_clean_rooms(rest, duid)
    elif cmd == "raw":
        if not rest: sys.exit("Usage: ./vac.py raw <DP_NAME> [json_value]")
        await cmd_raw(rest[0], rest[1] if len(rest) > 1 else None, duid)
    elif cmd == "schedule":
        await cmd_schedule(rest[0] if rest else "list", rest[1:], duid, as_json)
    else:
        sys.exit(f"Unknown command: {cmd}")


# Streaming commands aren't request/response; the daemon serves them from its event
# bus. `watch --bytes` stays --force-only (needs the raw frame stream; a niche RE tool).
def _is_stream_cmd(cmd, rest):
    return cmd == "watch" and "--bytes" not in rest


# ── daemon: the server ──────────────────────────────────────────────────────────
class Daemon:
    """Holds one DeviceManager open and serves the CLI over a Unix socket.

    Reuses python-roborock's DeviceManager + FileCache (verify/login once; cache
    HomeData so reconnects don't burn the cloud's ~15/hr home_data bucket — the HA
    coordinator pattern) and the library's built-in MQTT reconnect/backoff. Commands
    run through the SAME cmd_* functions as the standalone path (via _INJECTED_SESSION
    + captured stdout), so daemon output is byte-identical to `--force` output.

    NOT YET LIVE-VALIDATED against the cloud (written offline while the account was
    rate-limited). The protocol/lifecycle are unit-tested; the cloud-hold + 135
    recovery need a live session to confirm. The `--force` path is the validated
    fallback meanwhile.
    """

    def __init__(self, duid, careful=False):
        self.duid = duid
        self.careful = careful            # stop the daemon COMPLETELY on the first 135/auth complaint
        self.halt_reason = None
        self.manager = None
        self.device = None
        self.props = None
        self.cache = None
        self.status_cache = {}        # DP name -> latest value
        self.last_update = None
        self.watchers = set()         # asyncio.Queue per streaming client
        self.cmd_lock = asyncio.Lock()
        self.unauthorized = False
        self.needs_login = False          # set after _MAX_RECONNECTS — stop retrying revoked creds
        self.reconnect_attempts = 0
        self.started_at = None
        self.last_error = None            # last diagnosed server issue (for `daemon status`)
        self.seen_dps = set()
        self.tap_events = None        # file: every decoded DP frame (JSONL)
        self.tap_novel = None         # file: first-seen DP names (JSONL)
        self.tap_bytes = None         # file: raw frames (JSONL)
        self._bytes_task = None
        self._tasks = []
        self._stop = asyncio.Event()

    # — connection lifecycle —
    async def connect(self):
        global _INJECTED_SESSION
        creds = require_creds()
        ud = UserData.from_dict(creds.user_data)
        params = UserParams(username=creds.email, user_data=ud, base_url=creds.base_url)
        self.cache = FileCache(CACHE_FILE)
        self.manager = await create_device_manager(params, cache=self.cache, prefer_cache=True)
        devices = await self.manager.discover_devices(prefer_cache=True)
        self.device = _select_device(devices, self.duid)
        self.props = getattr(self.device, "b01_q10_properties", None)
        if self.props is None:
            raise RuntimeError(f"'{self.device.name}' is not a B01/Q10 device")
        _INJECTED_SESSION = (self.device, self.props)
        self.unauthorized = False

    def _context(self) -> dict:
        """Current daemon state — attached to every diagnosed issue for context."""
        up = int((datetime.now() - self.started_at).total_seconds()) if self.started_at else None
        return {
            "device": getattr(self.device, "name", None),
            "uptime_s": up,
            "last_update": self.last_update.isoformat() if self.last_update else None,
            "reconnect_attempts": self.reconnect_attempts,
            "careful": self.careful,
            "watchers": len(self.watchers),
            "taps": [n for n, f in (("events", self.tap_events), ("novel", self.tap_novel),
                                    ("bytes", self.tap_bytes)) if f],
        }

    def _diagnose(self, where: str, exc: BaseException) -> dict:
        """Build + log a context-rich record of a server issue. Call from inside the `except`
        so the traceback is live. Returns the record (also kept as self.last_error)."""
        cls = _classify_error(exc)
        rec = {"when": datetime.now().isoformat(timespec="seconds"), "where": where,
               "type": type(exc).__name__, "error": str(exc), "reason_code": _reason_code(exc),
               "class": cls, "hint": _ERROR_HINTS.get(cls, _ERROR_HINTS["other"]),
               **self._context()}
        self.last_error = rec
        _log("SERVER ISSUE [%s] during %s\n"
             "  %s: %s  (reason_code=%s)\n"
             "  device=%s uptime=%ss last_update=%s reconnect_attempts=%s careful=%s watchers=%s taps=%s\n"
             "  hint: %s" % (
                 cls, where, rec["type"], rec["error"], rec["reason_code"],
                 rec["device"], rec["uptime_s"], rec["last_update"], rec["reconnect_attempts"],
                 rec["careful"], rec["watchers"], rec["taps"], rec["hint"]))
        if cls in ("other", "network"):       # unexpected → keep the full traceback for debugging
            tb = traceback.format_exc()
            if tb and "NoneType: None" not in tb:
                _log("traceback:\n" + tb)
        return rec

    def _trip(self, where: str, exc: BaseException) -> dict:
        """Record a cloud auth/rate-limit complaint (with full diagnostics). In CAREFUL mode this
        stops the daemon completely (clean shutdown, zero further cloud contact) and writes a
        context-rich halt marker so the reason survives the exit. Otherwise it flags for the
        supervisor to back off. Returns the diagnostic record."""
        rec = self._diagnose(where, exc)
        self.unauthorized = True
        if self.careful and not self._stop.is_set():
            self.halt_reason = f"{rec['class']} during {where}: {rec['error']}"
            try:
                HALT_PATH.write_text(
                    f"{rec['when']}  careful-mode halt: {self.halt_reason}\n"
                    "The daemon stopped on a cloud auth/rate-limit complaint. If this was a ban, "
                    "wait before restarting; if creds are revoked, run ./vac.py login. "
                    "Restart: ./vac.py daemon start\n\n"
                    "Full context:\n" + json.dumps(rec, indent=2, default=str) + "\n")
            except Exception:
                pass
            _log(f"CAREFUL MODE: stopping the daemon completely ({rec['class']} during {where}).")
            self._stop.set()
        return rec

    async def _reconnect(self):
        """Rebuild the manager with existing creds (used after a transient 135 cools)."""
        global _INJECTED_SESSION
        _INJECTED_SESSION = None
        try:
            if self.manager:
                await self.manager.close()
        except Exception:
            pass
        await self.connect()

    # — background: consume the decoded DP stream into cache + bus + taps —
    async def _consume(self):
        while not self._stop.is_set():
            try:
                async for dps in stream_decoded_responses(self.props._channel):
                    named = {(k.name if hasattr(k, "name") else str(k)): v
                             for k, v in dps.items()}
                    self.status_cache.update(named)
                    self.last_update = datetime.now()
                    rec = {"time": self.last_update.isoformat(timespec="seconds"), "dps": named}
                    for q in list(self.watchers):
                        q.put_nowait(rec)
                    if self.tap_events:
                        self.tap_events.write(json.dumps(rec, default=str) + "\n")
                        self.tap_events.flush()
                    if self.tap_novel:
                        fresh = [n for n in named if n not in self.seen_dps]
                        if fresh:
                            self.tap_novel.write(json.dumps(
                                {"time": rec["time"], "new_dps": fresh,
                                 "values": {n: named[n] for n in fresh}}, default=str) + "\n")
                            self.tap_novel.flush()
                    self.seen_dps.update(named)
            except asyncio.CancelledError:
                return
            except Exception as exc:
                if _is_throttle(exc):
                    self._trip("stream", exc)
                else:
                    self._diagnose("stream", exc)
                await asyncio.sleep(5)   # avoid a tight loop on persistent failure

    async def _consume_bytes(self):
        """Raw-frame consumer; runs only while a byte tap is open."""
        try:
            async for msg in self.props._channel.subscribe_stream():
                if not self.tap_bytes:
                    return
                payload = msg.payload
                kind, body = _classify_payload(payload)
                self.tap_bytes.write(json.dumps({
                    "time": datetime.now().isoformat(timespec="seconds"),
                    "protocol_num": getattr(msg.protocol, "value", msg.protocol),
                    "len": len(payload) if payload is not None else 0,
                    "kind": kind, "payload": body}, default=str) + "\n")
                self.tap_bytes.flush()
        except asyncio.CancelledError:
            return
        except Exception as exc:
            _log(f"byte-tap error: {exc}")

    async def _keepalive(self):
        """Prompt a full DP dump periodically so the cache/stream don't go stale when idle."""
        while not self._stop.is_set():
            # Don't poke a throttled/down session — that only adds connection noise the
            # server sees during a ban. Pause until the supervisor restores the session.
            if not (self.unauthorized or self.needs_login):
                try:
                    await self.props.refresh()
                except Exception as exc:
                    if _is_throttle(exc):
                        self._trip("keepalive", exc)
                    else:
                        self._diagnose("keepalive", exc)
            await asyncio.sleep(30)

    async def _supervisor(self):
        """After a 135 throttle, cool down (ESCALATING) then try one reconnect with existing
        creds. Give up after _MAX_RECONNECTS — retrying revoked creds forever is just noise to
        the server; require a manual `login`. Resets on success. (server-view, DECISIONS s21)"""
        while not self._stop.is_set():
            await asyncio.sleep(15)
            if not self.unauthorized or self.needs_login:
                continue
            delay = _RECONNECT_BACKOFF[min(self.reconnect_attempts, _MAX_RECONNECTS - 1)]
            _log(f"135 throttle: cooling down {delay}s before reconnect "
                 f"(attempt {self.reconnect_attempts + 1}/{_MAX_RECONNECTS})")
            for _ in range(delay // 5):          # sleep in slices so stop stays responsive
                if self._stop.is_set():
                    return
                await asyncio.sleep(5)
            try:
                await self._reconnect()           # rebuilds manager with existing creds
                self.reconnect_attempts = 0       # connect() also clears self.unauthorized
                _log("reconnect succeeded; cloud session restored")
            except Exception as exc:
                self.reconnect_attempts += 1
                self._diagnose(f"reconnect#{self.reconnect_attempts}/{_MAX_RECONNECTS}", exc)
                if self.reconnect_attempts >= _MAX_RECONNECTS:
                    self.needs_login = True       # stop retrying; require manual re-auth
                    _log("giving up reconnecting — credentials likely revoked. Run "
                         "`./vac.py login` then `./vac.py daemon restart`. Daemon now idle.")

    # — per-client handler —
    async def _handle(self, reader, writer):
        try:
            line = await reader.readline()
            if not line:
                return
            req = json.loads(line.decode())
        except Exception:
            return
        # version handshake — a stale daemon after `pip install -U` is detected here
        if req.get("v") != DAEMON_PROTO:
            await _send(writer, {"ok": False, "stale": True,
                                 "error": f"daemon protocol {DAEMON_PROTO} != client {req.get('v')}; "
                                          "restart it: ./vac.py daemon restart"})
            return

        kind = req.get("kind", "cmd")
        if kind == "ping":
            await _send(writer, {"ok": True, "data": {
                "proto": DAEMON_PROTO, "device": getattr(self.device, "name", None),
                "unauthorized": self.unauthorized, "needs_login": self.needs_login,
                "careful": self.careful,
                "uptime_s": (int((datetime.now() - self.started_at).total_seconds())
                             if self.started_at else None),
                "last_error": ({"when": self.last_error["when"], "where": self.last_error["where"],
                                "class": self.last_error["class"], "reason_code": self.last_error["reason_code"]}
                               if self.last_error else None),
                "last_update": self.last_update.isoformat() if self.last_update else None,
                "watchers": len(self.watchers),
                "taps": [n for n, f in (("events", self.tap_events),
                                        ("novel", self.tap_novel), ("bytes", self.tap_bytes)) if f]}})
            return
        if kind == "record":
            await _send(writer, {"ok": True, "data": self._set_taps(req.get("args", {}))})
            return
        if kind == "stream":
            await self._serve_stream(req, reader, writer)
            return

        # request/response command
        if self.needs_login:
            await _send(writer, {"ok": False, "error":
                "cloud credentials appear revoked (repeated 135). Run `./vac.py login`, then "
                "`./vac.py daemon restart`. (Daemon is idle — not retrying.)"})
            return
        if self.unauthorized:
            await _send(writer, {"ok": False, "error":
                "cloud session is rate-limited (135); daemon is cooling down and will retry. "
                "Wait a bit and re-run. If it persists, run ./vac.py login."})
            return
        cmd, rest = req.get("cmd"), req.get("rest", [])
        duid, as_json, cwd = req.get("duid"), req.get("as_json", False), req.get("cwd")
        async with self.cmd_lock:
            buf = io.StringIO()
            prev_cwd = os.getcwd()
            try:
                if cwd:
                    os.chdir(cwd)        # so map/--out files land in the CLIENT's dir
                with contextlib.redirect_stdout(buf):
                    await _run_one(cmd, rest, duid, as_json)
                resp = {"ok": True, "out": buf.getvalue()}
            except SystemExit as e:
                code = e.code
                resp = {"ok": (code in (None, 0)), "out": buf.getvalue(),
                        "error": None if code in (None, 0) else str(code)}
            except Exception as exc:
                where = f"command:{cmd}"
                # careful mode bails on ANY auth/rate complaint (incl. REST 401); the
                # backoff path only reacts to the MQTT 135 throttle.
                if (self.careful and _is_auth_or_rate(exc)) or _is_throttle(exc):
                    rec = self._trip(where, exc)
                else:
                    rec = self._diagnose(where, exc)
                resp = {"ok": False, "out": buf.getvalue(), "error": str(exc),
                        "error_type": rec["type"], "reason_code": rec["reason_code"],
                        "class": rec["class"], "hint": rec["hint"]}
            finally:
                os.chdir(prev_cwd)
        await _send(writer, resp)

    def _set_taps(self, args):
        def _toggle(attr, path):
            cur = getattr(self, attr)
            if path in (None, "", False):
                if cur:
                    cur.close(); setattr(self, attr, None)
                return "off"
            if cur:
                cur.close()
            setattr(self, attr, open(pathlib.Path(path).expanduser(), "a"))
            return f"-> {path}"
        out = {}
        if "events" in args: out["events"] = _toggle("tap_events", args["events"])
        if "novel" in args:  out["novel"] = _toggle("tap_novel", args["novel"])
        if "bytes" in args:
            out["bytes"] = _toggle("tap_bytes", args["bytes"])
            if self.tap_bytes and (self._bytes_task is None or self._bytes_task.done()):
                self._bytes_task = asyncio.create_task(self._consume_bytes())
        return out

    async def _serve_stream(self, req, reader, writer):
        q: asyncio.Queue = asyncio.Queue()
        self.watchers.add(q)
        # Reap promptly on client disconnect: a watch client is one-way after its request,
        # so reader EOF (b'') means it's gone. Without this the daemon only notices on the
        # NEXT frame-write, so a dead watcher lingers under an idle robot (s22 lazy-cleanup).
        eof = asyncio.ensure_future(reader.read())
        try:
            # NOTE: do NOT use _send() here — it closes the writer after sending, which
            # is correct for one-shot replies but kills a stream after the head (s22 bug).
            writer.write((json.dumps({"ok": True, "stream": True}) + "\n").encode())
            await writer.drain()
            while not writer.is_closing():
                getter = asyncio.ensure_future(q.get())
                done, _ = await asyncio.wait({getter, eof}, return_when=asyncio.FIRST_COMPLETED)
                if eof in done:                  # client disconnected — stop streaming
                    getter.cancel()
                    break
                rec = getter.result()
                writer.write((json.dumps(rec, default=str) + "\n").encode())
                await writer.drain()
        except (ConnectionResetError, BrokenPipeError, asyncio.CancelledError):
            pass
        finally:
            eof.cancel()
            self.watchers.discard(q)

    async def serve(self):
        self.started_at = datetime.now()
        try:
            await self.connect()
        except Exception as exc:
            if _is_throttle(exc):
                self._trip("startup-connect", exc)
            else:
                self._diagnose("startup-connect", exc)
            _log("startup connect failed; not opening socket — "
                 + ("careful mode, stopped." if self.careful else "wait and retry / check the log."))
            return                       # exit cleanly; never opened the socket
        self._tasks = [asyncio.create_task(c) for c in
                       (self._consume(), self._keepalive(), self._supervisor())]
        if SOCK_PATH.exists():
            SOCK_PATH.unlink()
        server = await asyncio.start_unix_server(self._handle, path=str(SOCK_PATH))
        os.chmod(SOCK_PATH, 0o600)
        PID_PATH.write_text(str(os.getpid()))
        _log(f"daemon up: {getattr(self.device,'name','?')} on {SOCK_PATH}")
        loop = asyncio.get_running_loop()
        for sig in (signal.SIGTERM, signal.SIGINT):
            loop.add_signal_handler(sig, self._stop.set)
        try:
            await self._stop.wait()
        finally:
            server.close()
            for t in self._tasks:
                t.cancel()
            try:
                if self.manager:
                    await self.manager.close()
            except Exception:
                pass
            for f in (self.tap_events, self.tap_novel, self.tap_bytes):
                if f:
                    f.close()
            for p in (SOCK_PATH, PID_PATH):
                if p.exists():
                    p.unlink()
            _log("daemon stopped")


def _log(msg):
    try:
        with open(LOG_PATH, "a") as f:
            f.write(f"[{datetime.now():%Y-%m-%d %H:%M:%S}] {msg}\n")
    except Exception:
        pass


async def _send(writer, obj):
    try:
        writer.write((json.dumps(obj, default=str) + "\n").encode())
        await writer.drain()
        writer.close()
    except Exception:
        pass


# ── daemon: client side (the thin CLI) ──────────────────────────────────────────
DAEMON_DOWN = object()   # sentinel: socket not reachable


async def _client_send(req: dict):
    """Send one request, return the parsed response dict, or DAEMON_DOWN if unreachable."""
    try:
        reader, writer = await asyncio.open_unix_connection(str(SOCK_PATH))
    except (FileNotFoundError, ConnectionRefusedError, OSError):
        return DAEMON_DOWN
    req["v"] = DAEMON_PROTO
    writer.write((json.dumps(req) + "\n").encode())
    await writer.drain()
    line = await reader.readline()
    writer.close()
    return json.loads(line.decode()) if line else {"ok": False, "error": "empty response"}


async def _client_stream(req: dict):
    """Open a streaming request (watch); print each event line until interrupted."""
    try:
        reader, writer = await asyncio.open_unix_connection(str(SOCK_PATH))
    except (FileNotFoundError, ConnectionRefusedError, OSError):
        return DAEMON_DOWN
    req["v"] = DAEMON_PROTO
    req["kind"] = "stream"
    writer.write((json.dumps(req) + "\n").encode())
    await writer.drain()
    first = await reader.readline()
    if not first:
        return {"ok": False, "error": "empty response"}
    head = json.loads(first.decode())
    if not head.get("ok"):
        return head
    rest = req.get("rest", [])
    raw = "--raw" in rest
    # honor --out: mirror each frame as a JSON line to the file (s22 — was ignored,
    # so `watch --raw --out log.jsonl` through the daemon wrote nothing).
    out_path = (rest[rest.index("--out") + 1]
                if "--out" in rest and rest.index("--out") + 1 < len(rest) else None)
    out_f = open(pathlib.Path(out_path).expanduser(), "a") if out_path else None
    try:
        while True:
            line = await reader.readline()
            if not line:
                break
            rec = json.loads(line.decode())
            if out_f:
                out_f.write(json.dumps(rec, default=str) + "\n")
                out_f.flush()
            if raw:
                print(json.dumps(rec, default=str))
            else:
                dps = rec.get("dps", {})
                keys = ", ".join(dps.keys())
                print(f"[{rec.get('time','')}] {len(dps)} dp: {keys}")
    except (KeyboardInterrupt, asyncio.CancelledError):
        pass
    finally:
        if out_f:
            out_f.close()
        writer.close()
    return {"ok": True}


_DAEMON_DOWN_MSG = (
    "vac daemon isn't running.\n"
    "  start it:           ./vac.py daemon start\n"
    "  or run this once standalone (opens its own MQTT session — avoid repeating,\n"
    "  it can hit the cloud rate-limit):   ./vac.py {cmd} --force\n"
    "Why a daemon: it holds ONE cloud connection so commands don't each reconnect.\n"
    "See the Daemon section of README.md."
)


def _client_main(cmd, rest, duid, as_json):
    """Route a command through the daemon. Returns True if handled, DAEMON_DOWN if not."""
    if _is_stream_cmd(cmd, rest):
        res = asyncio.run(_client_stream(
            {"cmd": cmd, "rest": rest, "duid": duid, "as_json": as_json}))
    else:
        res = asyncio.run(_client_send(
            {"kind": "cmd", "cmd": cmd, "rest": rest, "duid": duid,
             "as_json": as_json, "cwd": os.getcwd()}))
    if res is DAEMON_DOWN:
        return DAEMON_DOWN
    if res.get("stale"):
        sys.exit(res.get("error"))
    out = res.get("out", "")
    if out:
        sys.stdout.write(out)
    if not res.get("ok"):
        if res.get("error"):
            print(res["error"], file=sys.stderr)
        cls = res.get("class")
        if cls and cls not in (None, "other") and res.get("hint"):
            code = f", code {res['reason_code']}" if res.get("reason_code") else ""
            print(f"  [{cls}{code}] {res['hint']}", file=sys.stderr)
        sys.exit(1)
    return True


# ── daemon: lifecycle subcommand ────────────────────────────────────────────────
def _daemon_alive():
    if not PID_PATH.exists():
        return False
    try:
        pid = int(PID_PATH.read_text().strip())
        os.kill(pid, 0)        # signal 0 = liveness probe
        return True
    except (ValueError, ProcessLookupError, PermissionError):
        return False


def cmd_daemon(rest):
    sub = rest[0] if rest else "status"
    if sub == "run":                      # foreground server (what `start` launches)
        require_creds()
        try:
            asyncio.run(Daemon(None, careful="--careful" in rest).serve())
        except KeyboardInterrupt:
            pass
        return
    if sub == "start":
        if _daemon_alive():
            print("daemon already running."); return
        require_creds()
        careful = "--careful" in rest
        HALT_PATH.unlink(missing_ok=True)        # clear any prior careful-mode halt marker
        run_args = [sys.executable, os.path.abspath(__file__), "daemon", "run"]
        if careful:
            run_args.append("--careful")
        logf = open(LOG_PATH, "a")
        subprocess.Popen(run_args, stdout=logf, stderr=logf, stdin=subprocess.DEVNULL,
                         start_new_session=True)
        for _ in range(40):                # poll up to ~8s for the socket
            if SOCK_PATH.exists():
                pid = PID_PATH.read_text().strip() if PID_PATH.exists() else "?"
                print(f"daemon started (pid {pid}){' [careful]' if careful else ''}."); return
            if HALT_PATH.exists():         # a careful daemon can trip during startup connect
                print(f"daemon stopped immediately (careful mode): "
                      f"{HALT_PATH.read_text().splitlines()[0]}"); return
            time.sleep(0.2)
        print(f"daemon launched but socket didn't appear in 8s — check {LOG_PATH}")
        return
    if sub == "stop":
        if not PID_PATH.exists():
            print("daemon not running."); return
        try:
            pid = int(PID_PATH.read_text().strip())
            os.kill(pid, signal.SIGTERM)
            print(f"sent stop to daemon (pid {pid}).")
        except (ValueError, ProcessLookupError):
            print("daemon not running (stale pid file).")
            PID_PATH.unlink(missing_ok=True)
        return
    if sub == "restart":
        # Preserve the running daemon's careful mode across the restart (s22: restart
        # used to silently drop --careful). An explicit --careful on the restart wins.
        careful = "--careful" in rest
        if not careful:
            res = asyncio.run(_client_send({"kind": "ping"}))
            if isinstance(res, dict):
                careful = bool(res.get("data", {}).get("careful"))
        cmd_daemon(["stop"]); time.sleep(1.0)
        cmd_daemon(["start"] + (["--careful"] if careful else [])); return
    if sub == "status":
        if not _daemon_alive():
            if HALT_PATH.exists():
                print(f"daemon: stopped (careful-mode halt) — {HALT_PATH.read_text().splitlines()[0]}")
            else:
                print("daemon: stopped")
            return
        res = asyncio.run(_client_send({"kind": "ping"}))
        if res is DAEMON_DOWN:
            print("daemon: pid alive but socket unreachable (starting up or wedged?)"); return
        d = res.get("data", {})
        health = ("NEEDS LOGIN (run ./vac.py login)" if d.get("needs_login")
                  else "throttled/cooling-down" if d.get("unauthorized") else "ok")
        mode = " [careful]" if d.get("careful") else ""
        le = d.get("last_error")
        le_str = f" · last_error={le['class']}@{le['where']} ({le['when']})" if le else ""
        print(f"daemon: running{mode} · device={d.get('device')} · health={health} · "
              f"uptime={d.get('uptime_s')}s · last_update={d.get('last_update')} · "
              f"watchers={d.get('watchers')} · taps={d.get('taps')}{le_str}")
        return
    if sub == "record":
        # ./vac.py daemon record [--events FILE] [--novel FILE] [--bytes FILE] [--off]
        args = {}
        for key in ("events", "novel", "bytes"):
            flag = f"--{key}"
            if flag in rest:
                i = rest.index(flag)
                args[key] = rest[i + 1] if i + 1 < len(rest) and not rest[i + 1].startswith("--") else f"vacd_{key}.jsonl"
        if "--off" in rest:
            args = {"events": None, "novel": None, "bytes": None}
        if not args:
            print("Usage: ./vac.py daemon record [--events F] [--novel F] [--bytes F] | --off")
            return
        res = asyncio.run(_client_send({"kind": "record", "args": args}))
        if res is DAEMON_DOWN:
            print("daemon not running — start it first."); return
        print(f"taps: {res.get('data')}")
        return
    print("Usage: ./vac.py daemon <start|stop|restart|status|record>")


def parse_args():
    args = sys.argv[1:]
    if not args or args[0] in ("-h", "--help"):
        print(__doc__)
        sys.exit(0)
    duid = None
    as_json = False
    force = False
    if "--device" in args:
        i = args.index("--device")
        duid = args[i + 1]
        args = args[:i] + args[i + 2:]
    if "--json" in args:
        as_json = True
        args = [a for a in args if a != "--json"]
    if "--force" in args or "--no-daemon" in args:
        force = True
        args = [a for a in args if a not in ("--force", "--no-daemon")]
    return args[0], args[1:], duid, as_json, force


def _local_main(cmd, rest, duid, as_json):
    """Standalone path: each command opens its own cloud session. Used for `login`,
    for any command run with `--force`, and as the no-daemon fallback. This is the
    original validated single-shot behavior, unchanged."""

    def run(coro):
        """Run a command coroutine; turn a cloud rate-limit into a clean message (no retry —
        safe for write commands, which must not double-execute)."""
        try:
            return asyncio.run(coro)
        except Exception as exc:
            if _is_throttle(exc):
                sys.exit(_THROTTLE_MSG)
            raise

    def run_ro(factory, _delays=(0, 5, 15)):
        """Run a READ-ONLY (idempotent) command with backoff-retry on a transient throttle.
        `factory` must build a FRESH coroutine each call (a coroutine is awaitable only once)."""
        for delay in _delays:
            if delay:
                print(f"  cloud rate-limited; retrying in {delay}s…", file=sys.stderr)
                time.sleep(delay)
            try:
                return asyncio.run(factory())
            except Exception as exc:
                if _is_throttle(exc):
                    continue
                raise
        sys.exit(_THROTTLE_MSG)

    # Commands with no extra args (json-capable ones pass as_json).
    json_cmds = {"discover": cmd_discover, "status": cmd_status, "consumables": cmd_consumables,
                 "history": cmd_history}
    simple_cmds = {
        "start": cmd_start, "stop": cmd_stop, "pause": cmd_pause, "resume": cmd_resume,
        "dock": cmd_dock, "dock-empty": cmd_dock_empty, "find": cmd_find,
    }
    if cmd in json_cmds:
        # all read-only (discover/status/consumables/history) → safe to backoff-retry
        run_ro(lambda: json_cmds[cmd](duid, as_json))
    elif cmd in simple_cmds:
        run(simple_cmds[cmd](duid))
    elif cmd == "login":
        email = rest[rest.index("--email") + 1] if "--email" in rest else None
        if not email:
            sys.exit("Usage: ./vac.py login --email your@email.com")
        run(cmd_login(email))
    elif cmd == "fan":
        if not rest:
            sys.exit("Usage: ./vac.py fan <quiet|balanced|turbo|max|max_plus>")
        run(cmd_fan(rest[0], duid))
    elif cmd == "water":
        if not rest:
            sys.exit("Usage: ./vac.py water <off|low|medium|high>")
        run(cmd_water(rest[0], duid))
    elif cmd == "mode":
        if not rest:
            sys.exit("Usage: ./vac.py mode <vac_and_mop|vacuum|mop>")
        run(cmd_mode(rest[0], duid))
    elif cmd == "volume":
        if not rest:
            sys.exit("Usage: ./vac.py volume <0-100>")
        run(cmd_volume(rest[0], duid))
    elif cmd == "child-lock":
        if not rest:
            sys.exit("Usage: ./vac.py child-lock <on|off>")
        run(cmd_child_lock(rest[0], duid))
    elif cmd == "boost":
        if not rest:
            sys.exit("Usage: ./vac.py boost <on|off>")
        run(cmd_boost(rest[0], duid))
    elif cmd == "dnd":
        if not rest:
            sys.exit("Usage: ./vac.py dnd <on|off> [--start HH:MM] [--end HH:MM]")
        start = rest[rest.index("--start") + 1] if "--start" in rest else None
        end = rest[rest.index("--end") + 1] if "--end" in rest else None
        run(cmd_dnd(rest[0], start, end, duid))
    elif cmd == "watch":
        out = rest[rest.index("--out") + 1] if "--out" in rest else None
        interval = int(rest[rest.index("--interval") + 1]) if "--interval" in rest else 10
        if "--bytes" in rest:
            target = cmd_watch_bytes
        elif "--raw" in rest:
            target = cmd_watch_raw
        else:
            target = cmd_watch
        try:
            run_ro(lambda: target(duid, out, interval))
        except KeyboardInterrupt:
            pass
    elif cmd == "map":
        timeout = int(rest[rest.index("--timeout") + 1]) if "--timeout" in rest else 30
        out_prefix = rest[rest.index("--out") + 1] if "--out" in rest else "map"
        try:
            run_ro(lambda: cmd_map(duid, timeout, out_prefix))
        except KeyboardInterrupt:
            pass
    elif cmd == "rooms":
        run_ro(lambda: cmd_rooms(duid))
    elif cmd == "clean-rooms":
        if not rest:
            sys.exit("Usage: ./vac.py clean-rooms <name|id>... [--dry-run] [--fan F] [--water W] ...")
        run(cmd_clean_rooms(rest, duid))
    elif cmd == "raw":
        if not rest:
            sys.exit("Usage: ./vac.py raw <DP_NAME> [json_value]")
        run(cmd_raw(rest[0], rest[1] if len(rest) > 1 else None, duid))
    elif cmd == "schedule":
        sub = rest[0] if rest else "list"
        run(cmd_schedule(sub, rest[1:], duid, as_json))
    else:
        print(f"Unknown command: {cmd}")
        print(__doc__)
        sys.exit(1)


def main():
    cmd, rest, duid, as_json, force = parse_args()

    # Never go through the daemon: lifecycle control + interactive login.
    if cmd == "daemon":
        return cmd_daemon(rest)
    if cmd == "login":
        return _local_main(cmd, rest, duid, as_json)

    # `history --from-capture <file>` is fully offline — decode a capture, no session/daemon.
    if cmd == "history" and "--from-capture" in rest:
        i = rest.index("--from-capture")
        path = rest[i + 1] if i + 1 < len(rest) else None
        if not path:
            sys.exit("Usage: ./vac.py history --from-capture <capture.jsonl> [--json]")
        return cmd_history_from_capture(path, as_json)

    # `watch --bytes` is a raw-frame RE capture — keep it standalone (or use a daemon tap).
    if cmd == "watch" and "--bytes" in rest and not force:
        sys.exit("watch --bytes is a raw-frame capture — run it standalone with --force "
                 "(./vac.py watch --bytes --force), or capture via the daemon: "
                 "./vac.py daemon record --bytes cap.jsonl")

    # `--force` (or `--no-daemon`): run standalone, opening this command's own session.
    if force:
        return _local_main(cmd, rest, duid, as_json)

    # Default: thin client over the running daemon.
    if _client_main(cmd, rest, duid, as_json) is DAEMON_DOWN:
        sys.exit(_DAEMON_DOWN_MSG.format(cmd=cmd))


if __name__ == "__main__":
    main()
