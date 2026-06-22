"""Offline tests for CLI helper functions in vac.py:
  • _int_arg          — guarded parse of integer CLI flags (--timeout / --interval) (#15)
  • _str_arg          — guarded parse of string CLI flags (--out / --start / --end / …) (#17)
  • _hhmm_arg         — guarded parse of HH:MM time flags
  • _spent_onetime_jobs — which fired one-time /jobs entries clean-rooms purges as clutter

Pure, no network/robot. Run: pytest test_code_quality.py  (or call the test fns directly).
"""
import vac


def _exits(fn, *a, **k) -> bool:
    """True iff calling fn(*a, **k) raises SystemExit (a clean CLI bail, not a traceback)."""
    try:
        fn(*a, **k)
        return False
    except SystemExit:
        return True


# ── _int_arg ────────────────────────────────────────────────────────────────────
def test_int_arg_parses_present_value():
    assert vac._int_arg(["--timeout", "45"], "--timeout", 30) == 45


def test_int_arg_returns_default_when_absent():
    assert vac._int_arg(["--out", "x"], "--timeout", 30) == 30


def test_int_arg_exits_cleanly_on_junk():
    assert _exits(vac._int_arg, ["--timeout", "soon"], "--timeout", 30)


def test_int_arg_exits_on_missing_value():
    assert _exits(vac._int_arg, ["--timeout"], "--timeout", 30)        # flag at end, no value


def test_int_arg_enforces_minimum():
    assert _exits(vac._int_arg, ["--interval", "0"], "--interval", 10)   # default minimum=1
    assert vac._int_arg(["--interval", "1"], "--interval", 10) == 1


# ── _str_arg ────────────────────────────────────────────────────────────────────
def test_str_arg_parses_present_value():
    assert vac._str_arg(["--out", "log.jsonl"], "--out") == "log.jsonl"


def test_str_arg_returns_default_when_absent():
    assert vac._str_arg(["--raw"], "--out") is None
    assert vac._str_arg(["--raw"], "--out", "map") == "map"


def test_str_arg_exits_on_missing_value():
    assert _exits(vac._str_arg, ["--out"], "--out")   # flag at end, no value → SystemExit


def test_str_arg_value_when_followed_by_other_args():
    # --out with a real value followed by another flag: correctly returns the value
    assert vac._str_arg(["--out", "file.jsonl", "--raw"], "--out") == "file.jsonl"


# ── _hhmm_arg ───────────────────────────────────────────────────────────────────
def test_hhmm_arg_parses_valid():
    assert vac._hhmm_arg("22:00", "--start") == (22, 0)
    assert vac._hhmm_arg("00:00", "--start") == (0, 0)
    assert vac._hhmm_arg("23:59", "--end") == (23, 59)


def test_hhmm_arg_exits_on_junk():
    assert _exits(vac._hhmm_arg, "not-a-time", "--start")
    assert _exits(vac._hhmm_arg, "noon", "--start")
    assert _exits(vac._hhmm_arg, "22", "--start")


def test_hhmm_arg_exits_on_out_of_range():
    assert _exits(vac._hhmm_arg, "25:00", "--start")   # hour out of range
    assert _exits(vac._hhmm_arg, "22:61", "--end")      # minute out of range
    assert _exits(vac._hhmm_arg, "24:00", "--start")    # exactly 24 is invalid (0-23 only)


# ── _spent_onetime_jobs ───────────────────────────────────────────────────────────
def test_spent_picks_only_fired_onetime_jobs():
    jobs = [
        {"id": "a", "repeated": False, "enabled": False},   # fired one-time -> spent
        {"id": "b", "repeated": False, "enabled": True},    # pending one-time -> keep
        {"id": "c", "repeated": True,  "enabled": False},   # disabled repeating schedule -> keep
        {"id": "d", "repeated": True,  "enabled": True},    # active repeating schedule -> keep
    ]
    assert [j["id"] for j in vac._spent_onetime_jobs(jobs)] == ["a"]


def test_spent_is_conservative_on_missing_keys():
    # Absent keys default to repeated=True / enabled=True -> never matched; an id is required.
    assert vac._spent_onetime_jobs([{"id": "x"}]) == []                       # both keys absent
    assert vac._spent_onetime_jobs([{"repeated": False, "enabled": False}]) == []  # no id
    assert vac._spent_onetime_jobs([]) == []


if __name__ == "__main__":
    for name, fn in sorted((n, f) for n, f in globals().items() if n.startswith("test")):
        fn(); print(f"PASS {name}")
    print("all code-quality helper tests passed")
