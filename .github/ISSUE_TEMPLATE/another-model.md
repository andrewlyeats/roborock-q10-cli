---
name: Report from another Roborock model
about: Share what works (or doesn't) on a Roborock model other than the tested Q10 S5+
title: "[model] "
labels: device-report
---

Thanks for testing on another device — this is exactly the kind of report that grows coverage.

**Device**
- Model string (e.g. `roborock.vacuum.ss07`):
- Protocol version (`pv`, e.g. `B01`):
- Firmware version:

**What works / what doesn't**
- Commands that worked:
- Commands that errored or did nothing (paste the message):

**Observations**
- New or different data-point (DP) names / enum values you saw (`./vac.py watch --raw`):
- Anything that differs from `DP_DICTIONARY.md` / `CAPABILITIES.md`:

> ⚠️ **Scrub before pasting.** Remove NET_INFO (IP/MAC/SSID), the device serial, and any tokens
> from captures. Prefer pasting decoded DP rows over a raw dump.
