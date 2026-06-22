#!/usr/bin/env python3
"""Regression test for the CLEAN_RECORD parser + history --from-capture (s24).

The 12-field map was cross-validated against an 18-record corpus (PROTOCOL s24).
Run: ./test_history.py   (conda interp; never bare python3)
"""
import vac

# DP_DICTIONARY canonical example: 27 min, 12.05 m2, water off, vacuum, daily route, 1 pass, completed.
EX = "76e6xhie6a2b6269_1781226271_27_19_6692_12053_4_00_02_01_1_1"


def test_decode():
    r = vac._decode_clean_record(EX)
    assert r is not None, "decode returned None"
    assert r["duration_min"] == 27, r
    assert r["area_m2"] == 12.053, r
    assert r["water"] == "off", r          # field 7 = water (vacuum -> off)
    assert r["mode"] == "vacuum", r        # field 8 = mode
    assert r["route"] == "daily", r        # field 9 = route
    assert r["passes"] == 1, r
    assert r["ok"] is True, r
    # field-7 water=4 -> "custom" (the possible 4th level seen in the corpus)
    r4 = vac._decode_clean_record(EX.replace("_00_02_01_1_1", "_04_01_01_1_0"))
    assert r4["water"] == "custom" and r4["mode"] == "vac_and_mop" and r4["ok"] is False, r4
    # malformed -> None, never raises
    assert vac._decode_clean_record("not_a_record") is None
    assert vac._decode_clean_record("a_b_c") is None


if __name__ == "__main__":
    test_decode()
    print("PASS: CLEAN_RECORD decode (fields + water=custom + malformed-safe)")
