#!/usr/bin/env python3
"""
Upgrade canary for python-roborock.

vac.py depends on several python-roborock *internals* (private functions, private
attributes, deep B01-specific module paths) that are not covered by any API-stability
promise. A version bump can move or rename them and break vac.py with a cryptic
mid-session error.

Run this AFTER any `pip install -U python-roborock` (and as a general sanity check):

    ./check_roborock_api.py        # uses the correct interpreter via the shebang

It imports every symbol vac.py relies on and verifies the shapes we assume. A clean
PASS means an upgrade is safe to keep; a FAIL tells you exactly which internal moved,
so you can fix the one adapter point in vac.py instead of debugging a stack trace.

Exit code 0 = all good, 1 = something we depend on changed.
"""
import importlib
import inspect
import sys

# (module, attribute, severity) — severity 'high' items are the private/deep internals
# most likely to move; 'med'/'low' are progressively safer.
SYMBOLS = [
    ("roborock", "B01Fault", "low"),
    ("roborock.data", "UserData", "low"),
    ("roborock.web_api", "RoborockApiClient", "low"),
    ("roborock.web_api", "_get_hawk_authentication", "high"),     # private fn
    ("roborock.devices.device_manager", "UserParams", "med"),
    ("roborock.devices.device_manager", "create_device_manager", "med"),
    ("roborock.devices.file_cache", "FileCache", "med"),
    ("roborock.devices.rpc.b01_q10_channel", "stream_decoded_responses", "high"),  # deep B01 internal
    ("roborock.mqtt.session", "MqttSessionUnauthorized", "med"),  # for rate-limit handling
    ("roborock.data.b01_q10.b01_q10_code_mappings", "B01_Q10_DP", "med"),
    ("roborock.data.b01_q10.b01_q10_code_mappings", "YXFanLevel", "med"),
    ("roborock.data.b01_q10.b01_q10_code_mappings", "YXWaterLevel", "med"),
    ("roborock.data.b01_q10.b01_q10_code_mappings", "YXCleanType", "med"),
]

# Specific enum members vac.py sends by name — a rename here breaks commands silently.
REQUIRED_DPS = [
    "MULTI_MAP", "START_CLEAN", "SEEK", "WATER_LEVEL", "FAN_LEVEL",
    "NOT_DISTURB", "NOT_DISTURB_DATA", "VOLUME", "CHILD_LOCK", "AUTO_BOOST",
]

failures = []
warnings = []


def check_symbol(module, attr, severity):
    try:
        mod = importlib.import_module(module)
    except Exception as e:
        failures.append(f"[{severity}] cannot import module {module!r}: {e}")
        return None
    if not hasattr(mod, attr):
        failures.append(f"[{severity}] {module}.{attr} is GONE (moved/renamed)")
        return None
    return getattr(mod, attr)


def main():
    print("python-roborock upgrade canary\n" + "-" * 32)
    try:
        import roborock
        print(f"interpreter : {sys.executable}")
        print(f"python      : {sys.version.split()[0]}")
        print(f"roborock at : {roborock.__file__}\n")
    except Exception as e:
        print(f"FATAL: `import roborock` failed: {e}")
        print("Are you on the right interpreter? Use ./check_roborock_api.py (conda env, Python >=3.11).")
        sys.exit(1)

    resolved = {}
    for module, attr, severity in SYMBOLS:
        obj = check_symbol(module, attr, severity)
        if obj is not None:
            resolved[(module, attr)] = obj

    # 1) _get_hawk_authentication signature — we call it as (rriot, path[, formdata, params]).
    hawk = resolved.get(("roborock.web_api", "_get_hawk_authentication"))
    if hawk is not None:
        params = list(inspect.signature(hawk).parameters)
        if params[:2] != ["rriot", "url"]:
            failures.append(
                f"[high] _get_hawk_authentication signature changed: {params} "
                "(vac.py calls it positionally as (rriot, path))"
            )

    # 2) B01_Q10_DP must still carry the DP names vac.py sends.
    dp = resolved.get(("roborock.data.b01_q10.b01_q10_code_mappings", "B01_Q10_DP"))
    if dp is not None:
        for name in REQUIRED_DPS:
            if not hasattr(dp, name):
                failures.append(f"[med] B01_Q10_DP.{name} is GONE (vac.py sends this DP)")

    # 3) Private channel surface: vac.py uses props._channel.subscribe_stream().
    #    We can't construct a live channel here, but we can confirm the channel class
    #    that stream_decoded_responses operates on still exposes subscribe_stream.
    try:
        chan_mod = importlib.import_module("roborock.devices.rpc.b01_q10_channel")
        classes = [c for _, c in inspect.getmembers(chan_mod, inspect.isclass)]
        if not any(hasattr(c, "subscribe_stream") for c in classes):
            # subscribe_stream may live on a base channel imported elsewhere; warn, don't fail.
            warnings.append(
                "could not confirm a channel class exposing `subscribe_stream` in "
                "b01_q10_channel (vac.py uses props._channel.subscribe_stream()); verify watch/map still run"
            )
    except Exception as e:
        warnings.append(f"could not introspect b01_q10_channel for subscribe_stream: {e}")

    print("RESULT")
    if warnings:
        for w in warnings:
            print(f"  WARN  {w}")
    if failures:
        for f in failures:
            print(f"  FAIL  {f}")
        print(f"\n{len(failures)} broken dependency(ies). vac.py will likely fail until the "
              "adapter points are updated. See DECISIONS 'dependency fragility' + CLAUDE.md.")
        sys.exit(1)
    print("  PASS  all internal symbols vac.py depends on are present and shaped as expected.")
    if warnings:
        print(f"  ({len(warnings)} warning(s) above — non-fatal, but worth a live smoke test.)")
    sys.exit(0)


if __name__ == "__main__":
    main()
