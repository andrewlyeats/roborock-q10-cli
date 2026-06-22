"""Offline test for the REST device-shadow decode behind `status --quick` (vac._shadow_summary).

Pure decode, no network/robot. Run: pytest test_status_quick.py  (or call the test fns directly).
The SHADOW fixture is a real response captured live (s28): robot charging, 85%, fan 3.
"""
import vac

# Live shadow `GET /devices/{duid}/shadow` result (keys are stringified v1 dp ids).
SHADOW = {"135": 0, "121": 8, "122": 85, "123": 3, "125": 10, "136": 1,
          "126": 11, "137": 1, "127": 11, "138": 0, "139": 5}


def test_decodes_state_battery_fan_consumables():
    s = vac._shadow_summary(SHADOW)
    assert s["state"] == "charging"      # 121=8 via RoborockStateCode (the v1 state space)
    assert s["state_code"] == 8
    assert s["battery"] == 85            # 122
    assert s["fan_power"] == 3           # 123
    assert s["main_brush"] == 10         # 125
    assert s["side_brush"] == 11         # 126
    assert s["filter"] == 11             # 127


def test_labels_v1_ids_and_buckets_b01_extras():
    s = vac._shadow_summary(SHADOW)
    # 121–135 get v1 RoborockDataProtocol names (lowercase); 136–139 are beyond the v1 enum -> extras.
    assert s["dps"]["state"] == 8
    assert s["dps"]["battery"] == 85
    assert set(s["extras"]) == {136, 137, 138, 139}


def test_unknown_state_and_nonnumeric_keys_are_safe():
    # Unknown state code -> the lib defaults to 'unknown' (no crash); a non-numeric key is filtered out.
    s = vac._shadow_summary({"121": 9999, "weirdKey": "x", "122": 50})
    assert s["state"] == "unknown"       # RoborockStateCode defaults unknown codes to 'unknown'
    assert s["state_code"] == 9999       # raw code preserved
    assert s["battery"] == 50            # non-numeric "weirdKey" filtered out, numeric kept


def test_empty_shadow_is_all_none():
    s = vac._shadow_summary({})
    assert s["state"] is None and s["battery"] is None and s["extras"] == {}


if __name__ == "__main__":
    for name, fn in sorted((n, f) for n, f in globals().items() if n.startswith("test")):
        fn(); print(f"PASS {name}")
    print("all status-quick decode tests passed")
