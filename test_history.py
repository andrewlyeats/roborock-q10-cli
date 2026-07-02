#!/usr/bin/env python3
"""Regression test for the CLEAN_RECORD parser (DP 52 op:list 12-field string).

Field map is AUTHORITATIVE — read from the ss07 app's own parser (`setHoldData`, 2026-06-24);
pos-7 (cleanMode/SCOPE) and pos-8 (workMode) are HARDWARE-SEALED 2026-06-26 (pos-7 ground-truthed
vs the app's Settings->Cleaning History scope labels; pos-8 = the ACTUAL work done {1,2,3}).
This SUPERSEDES the earlier positional guess (which mislabeled pathLen÷1000 as the area and
shifted mode/route/pass/status by one). See DP_DICTIONARY CLEAN_RECORD detail + PROTOCOL 2026-06-26.

Run: ./test_history.py   (conda interp; never bare python3)
"""
import vac

# 12 fields: 0 id · 1 ts · 2 cleanTime(min) · 3 cleanArea(m²) · 4 mapLen · 5 pathLen · 6 virtualLen
#            · 7 cleanMode(SCOPE) · 8 workMode · 9 cleaningResult · 10 startMethod · 11 collectDust
def _rec(scope=0, work=2, result=1, start=1):
    return f"76e6xhie6a2b6269_1781226271_27_19_6692_12053_4_{scope:02d}_{work:02d}_{result:02d}_{start}_1"


def test_decode_fields():
    r = vac._decode_clean_record(_rec())
    assert r is not None, "decode returned None"
    assert r["minutes"] == 27, r
    assert r["area_m2"] == 19, r            # pos-3 = the m² the app shows (NOT pathLen÷1000)
    assert r["map_len"] == 6692 and r["path_len"] == 12053 and r["virtual_len"] == 4, r
    assert r["work"] == "vacuum", r
    assert r["result"] == "completed", r
    assert r["start"] == "app", r
    assert r["dust"] == 1, r


def test_scope_labels():
    # pos-7 = clean SCOPE, app-ground-truthed 2026-06-26 (NOT the old zone/segment guess);
    # value 2 is unused on ss07 -> falls back to the raw token, never guessed.
    assert vac._decode_clean_record(_rec(scope=0))["type"] == "full"
    assert vac._decode_clean_record(_rec(scope=1))["type"] == "selective_room"
    assert vac._decode_clean_record(_rec(scope=3))["type"] == "zone"
    assert vac._decode_clean_record(_rec(scope=4))["type"] == "spot"
    assert vac._decode_clean_record(_rec(scope=2))["type"] == "02"   # unmapped -> raw token


def test_work_labels():
    assert vac._decode_clean_record(_rec(work=1))["work"] == "vac+mop"
    assert vac._decode_clean_record(_rec(work=2))["work"] == "vacuum"
    assert vac._decode_clean_record(_rec(work=3))["work"] == "mop"


def test_malformed_safe():
    assert vac._decode_clean_record("not_a_record") is None
    assert vac._decode_clean_record("a_b_c") is None


if __name__ == "__main__":
    test_decode_fields()
    test_scope_labels()
    test_work_labels()
    test_malformed_safe()
    print("PASS: CLEAN_RECORD decode (authoritative 12-field map + sealed scope/work labels)")
