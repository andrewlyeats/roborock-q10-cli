#!/usr/bin/env python3
"""Generate datapoints.json — a machine-readable index of the B01/Q10 data-points + value
enums, sourced from the python-roborock library (authoritative for NAMES, KEYS, and the YX*
value-enum label sets) with a 'documented in DP_DICTIONARY.md' flag.

CAPABILITIES #21(c). This is the additive, machine-consumable analog of frames.ksy (which indexes the
frame headers): it lets a porter / status panel enumerate every DP name+key and the value-enum
labels without scraping markdown. **DP_DICTIONARY.md stays the canonical reference** for the
MEANINGS, confidence tiers, numeric codes, provenance, and open questions — deliberately NOT
duplicated here (the prose provenance is the durable value; see PROTOCOL 2026-06-17).

Run (regenerate after a python-roborock upgrade, like check_roborock_api.py):
    /path/to/python gen_datapoints.py > datapoints.json

Offline: imports the library only — no device, no cloud.
"""
import json
import pathlib
import sys

from roborock.data.b01_q10 import b01_q10_code_mappings as m

_DD = pathlib.Path(__file__).with_name("DP_DICTIONARY.md")
_DD_TEXT = _DD.read_text(encoding="utf-8") if _DD.exists() else ""


def datapoint_entries():
    entries = []
    for d in m.B01_Q10_DP:
        v = d.value
        if isinstance(v, (tuple, list)):
            key, code = v[0], (v[1] if len(v) > 1 else None)
        else:
            key, code = v, None
        entries.append({
            "name": d.name,
            "key": key,
            "code": code,                       # numeric code if the library carries one, else null
            "documented": d.name in _DD_TEXT,   # catalogued in DP_DICTIONARY.md?
        })
    entries.sort(key=lambda e: e["name"])
    return entries


def value_enums():
    out = {}
    for n in sorted(dir(m)):
        if not n.startswith("YX"):
            continue
        e = getattr(m, n)
        try:
            members = list(e)
        except TypeError:
            continue
        out[n] = [{"name": x.name, "value": x.value} for x in members]
    return out


def build():
    entries = datapoint_entries()
    return {
        "schema": "roborock-b01-q10-datapoints/1",
        "generated_by": "gen_datapoints.py (from python-roborock B01_Q10_DP + YX* enums)",
        "note": ("Names/keys/enum labels are authoritative (the library). MEANINGS, confidence "
                 "tiers, numeric codes, provenance, and open questions live in DP_DICTIONARY.md "
                 "— the canonical reference; this file is the machine-readable index only "
                 "(the DP-layer analog of frames.ksy)."),
        "datapoint_count": len(entries),
        "documented_count": sum(1 for e in entries if e["documented"]),
        "datapoints": entries,
        "value_enums": value_enums(),
    }


if __name__ == "__main__":
    json.dump(build(), sys.stdout, indent=2, ensure_ascii=False)
    sys.stdout.write("\n")
