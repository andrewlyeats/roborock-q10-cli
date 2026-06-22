"""Offline test for the daemon stale-shadow warning behind `status` (vac._shadow_staleness).

Pure age math, no network/robot. Run: pytest test_status_stale.py  (or call the test fns directly).
Context: a long-running daemon served an 88-min-old "idle/75%" shadow as if live (no warning); the
fix ages the daemon's last live frame and warns past STALE_AFTER_S. See PROTOCOL/CAPABILITIES 2026-06-19.
"""
import asyncio
import contextlib
import io
import json
from datetime import datetime, timedelta

import vac

NOW = datetime(2026, 6, 19, 15, 0, 0)   # fixed reference; the helper takes `now`, so no clock mocking


def _at(seconds_ago):
    return NOW - timedelta(seconds=seconds_ago)


def test_none_last_update_is_unknown_no_warning():
    # No frame yet -> age unknown, NO warning: cmd_status only reaches here with a populated
    # status, so a None clock is a startup race (a frame just arrived), not real staleness.
    age, banner = vac._shadow_staleness(None, NOW)
    assert age is None and banner is None


def test_fresh_frame_no_warning():
    # A frame from 10s ago (healthy daemon streams every ~15–30s) -> fresh, no banner.
    age, banner = vac._shadow_staleness(_at(10), NOW)
    assert age == 10
    assert banner is None


def test_boundary_at_threshold_is_fresh():
    # Exactly at the threshold counts as fresh (age <= threshold), so no false positive at the edge.
    age, banner = vac._shadow_staleness(_at(vac.STALE_AFTER_S), NOW)
    assert age == vac.STALE_AFTER_S
    assert banner is None


def test_just_over_threshold_warns_in_seconds():
    # Just past the threshold but under 2 min -> banner labelled in seconds.
    age, banner = vac._shadow_staleness(_at(95), NOW)
    assert age == 95
    assert banner is not None
    assert "95 s old" in banner and "offline or sleeping" in banner


def test_minutes_label_cutover_at_120s():
    # At/over 2 min the label switches to minutes (cleaner than "120 s").
    age, banner = vac._shadow_staleness(_at(120), NOW)
    assert age == 120
    assert banner is not None and "2 min old" in banner


def test_the_real_incident_88_minutes_stale():
    # The bug that motivated this fix: an 88-min-old shadow served as live "idle/75%".
    age, banner = vac._shadow_staleness(_at(88 * 60), NOW)
    assert age == 88 * 60
    assert banner is not None and "88 min old" in banner


def test_custom_threshold_is_honored():
    # The threshold is a parameter, so callers/tests can tighten it.
    assert vac._shadow_staleness(_at(70), NOW, threshold_s=60)[1] is not None   # stale at 60s
    assert vac._shadow_staleness(_at(70), NOW, threshold_s=90)[1] is None       # fresh at 90s


# ── wiring test: the daemon-served path (getter-global -> cmd_status -> output) ──────────────
# Drives cmd_status through a faked injected session (no robot/network), exactly as the daemon
# does via _run_one, and asserts the staleness warning is surfaced. Guards the plumbing, not the math.
class _FakeEnum:
    def __init__(self, name): self.name = name


class _FakeStatus:
    """Minimal stand-in for props.status: 'populated' (battery+state set) like a daemon's held shadow."""
    def __init__(self):
        self.status = _FakeEnum("idle")     # the stale "idle/75%" the incident served
        self.battery = 75
        self.fan_level = self.water_level = self.clean_mode = None
        self.clean_task_type = self.back_type = None
        self.clean_time = self.clean_area = self.cleaning_progress = None
        self.fault = None

    def add_update_listener(self, fn):
        return lambda: None                 # fetch_status registers then removes a listener


class _FakeProps:
    def __init__(self): self.status = _FakeStatus()
    async def refresh(self): pass           # the daemon path: status is already populated (cached)


def _run_status_json(last_update_getter):
    """Run cmd_status(as_json=True) with a faked injected daemon session; return the parsed JSON."""
    prev_sess, prev_lu = vac._INJECTED_SESSION, vac._INJECTED_LAST_UPDATE
    vac._INJECTED_SESSION = (object(), _FakeProps())
    vac._INJECTED_LAST_UPDATE = last_update_getter
    buf = io.StringIO()
    try:
        with contextlib.redirect_stdout(buf):
            asyncio.run(vac.cmd_status(None, as_json=True))
    finally:
        vac._INJECTED_SESSION, vac._INJECTED_LAST_UPDATE = prev_sess, prev_lu
    return json.loads(buf.getvalue())


def test_cmd_status_flags_stale_daemon_shadow():
    # The incident: daemon holds an 88-min-old frame -> status JSON carries the warning, not a clean read.
    # Anchor to real now: cmd_status computes age against its own datetime.now() (not the fixed NOW above).
    out = _run_status_json(lambda: datetime.now() - timedelta(minutes=88))
    assert out["state"] == "idle" and out["battery"] == 75      # still returns the last-known values...
    assert out["stale"] is True                                 # ...but explicitly flagged stale
    assert out["warning"] and "88 min old" in out["warning"]
    assert abs(out["data_age_s"] - 88 * 60) < 2                 # ~88 min (± the call's sub-ms gap)


def test_cmd_status_fresh_daemon_shadow_no_warning():
    # A frame seconds old -> no warning; data_age_s present, stale False.
    out = _run_status_json(lambda: datetime.now())
    assert out["stale"] is False and out["warning"] is None
    assert out["data_age_s"] is not None and out["data_age_s"] < vac.STALE_AFTER_S


if __name__ == "__main__":
    for name, fn in sorted((n, f) for n, f in globals().items() if n.startswith("test")):
        fn(); print(f"PASS {name}")
    print("all status-stale warning tests passed")
