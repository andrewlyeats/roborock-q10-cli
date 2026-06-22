"""Offline test for the time-window codec (vac._encode/_decode_time_window).

Pure byte math, no network/robot. Run: pytest test_dnd_window.py  (or call the test fns directly).
The SAMPLE blobs are real app-wire captures (s30, the s30 app-wire capture). A 6-byte base64 blob
[flag, startH, startM, endH, endM, trail], flag 0xfc=on / 0x00=off — NOT the JSON object the pre-s30
cmd_dnd sent. The format is SHARED by DND (DP 33 NOT_DISTURB_DATA) and off-peak charging
(DP 106/107 VALLEY_POINT_CHARGING_DATA[_UP]) — see OFFPEAK_SAMPLES. See PROTOCOL 2026-06-19.
"""
import base64

import vac

# (b64, on, start, end) — both rows captured from the iOS app's own COMMON(101).33 writes (DND, DP 33).
SAMPLES = [
    ("/BYACAAA", True,  "22:00", "08:00"),   # fc 16 00 08 00 00
    ("ABcACAAA", False, "23:00", "08:00"),   # 00 17 00 08 00 00
]

# Off-peak charging (DP 106/107) captures — SAME 6-byte layout as DND, differing only in the trail byte
# (0x00/0x01, meaning unknown). Proves _decode_time_window is shared. (b64, on, start, end, trail)
OFFPEAK_SAMPLES = [
    ("/BYACAAA", True, "22:00", "08:00", 0),   # fc 16 00 08 00 00
    ("/BYACAAB", True, "22:00", "08:00", 1),   # fc 16 00 08 00 01 — same window, trail=1
]


def test_encode_matches_captured_app_blobs_byte_exact():
    for b64, on, start, end in SAMPLES:
        sh, sm = map(int, start.split(":"))
        eh, em = map(int, end.split(":"))
        assert vac._encode_time_window(on, sh, sm, eh, em) == b64


def test_decode_inverts_encode():
    for b64, on, start, end in SAMPLES:
        d = vac._decode_time_window(b64)
        assert d == {"on": on, "start": start, "end": end}


def test_flag_byte_is_fc_on_00_off():
    assert base64.b64decode(vac._encode_time_window(True, 22, 0, 8, 0))[0] == 0xfc
    assert base64.b64decode(vac._encode_time_window(False, 22, 0, 8, 0))[0] == 0x00


def test_round_trip_arbitrary_window():
    b64 = vac._encode_time_window(True, 1, 30, 6, 45)
    assert vac._decode_time_window(b64) == {"on": True, "start": "01:30", "end": "06:45"}


def test_offpeak_shares_the_dnd_window_format():
    # The off-peak charging window (DP 106/107) decodes with the SAME codec; the trail byte is ignored.
    for b64, on, start, end, _trail in OFFPEAK_SAMPLES:
        assert vac._decode_time_window(b64) == {"on": on, "start": start, "end": end}


def test_trail_byte_does_not_change_the_decoded_window():
    # /BYACAAA (trail 0) and /BYACAAB (trail 1) are the same 22:00-08:00 window.
    assert vac._decode_time_window("/BYACAAA") == vac._decode_time_window("/BYACAAB")


def test_malformed_blob_is_safe():
    assert vac._decode_time_window("not-base64!!") == {}
    assert vac._decode_time_window("AA==") == {}          # too short (1 byte)


if __name__ == "__main__":
    for name, fn in sorted((n, f) for n, f in globals().items() if n.startswith("test")):
        fn(); print(f"PASS {name}")
    print("all dnd-window codec tests passed")
