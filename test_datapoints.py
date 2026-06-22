#!/usr/bin/env python3
"""Drift guard for datapoints.json (CAPABILITIES #21c).

OFFLINE — imports the python-roborock library only (no device, no cloud). Regenerates the
index and asserts the committed datapoints.json still matches, so a library upgrade that
adds/renames a DP or changes a YX enum is caught loudly (the DP-layer analog of
check_roborock_api.py for internals). If this fails after an upgrade, run:
    python gen_datapoints.py > datapoints.json
"""
import json
import pathlib

import gen_datapoints


def test_regenerates_and_matches():
    live = gen_datapoints.build()
    committed = json.loads(
        pathlib.Path(__file__).with_name("datapoints.json").read_text(encoding="utf-8"))
    assert live == committed, (
        "datapoints.json is STALE vs the installed python-roborock — "
        "run: python gen_datapoints.py > datapoints.json")


def test_shape():
    d = gen_datapoints.build()
    assert d["datapoint_count"] == len(d["datapoints"])
    assert d["datapoint_count"] >= 100, d["datapoint_count"]
    for e in d["datapoints"]:
        assert e["name"] and e["key"], e
    assert "YXFanLevel" in d["value_enums"]
    assert d["value_enums"]["YXFanLevel"], "expected non-empty YXFanLevel labels"


if __name__ == "__main__":
    import sys
    fails = 0
    for _name, _fn in sorted(globals().items()):
        if _name.startswith("test_") and callable(_fn):
            try:
                _fn()
                print(f"PASS {_name}")
            except AssertionError as e:
                fails += 1
                print(f"FAIL {_name}: {e}")
    sys.exit(1 if fails else 0)
