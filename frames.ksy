meta:
  id: roborock_b01_301
  title: Roborock Q10 (B01) protocol-301 map frame headers
  file-extension: bin
  endian: be
  license: CC0-1.0
  ks-version: "0.10"
doc: |
  UNOFFICIAL reverse-engineered schema for the binary protocol-301 frames a Roborock Q10 (B01,
  roborock.vacuum.ss07) streams over MQTT while cleaning. HEADERS ONLY — Kaitai has no native LZ4,
  so the grid body is left raw (decompress externally to declared_size bytes).

  As of 2026-06-22 · firmware 03.11.24. Per-field confidence is in each `doc:`
  (✅ confirmed / 🟡 plausible / ⬜ unknown). NOT a vendor spec. To verify against YOUR device, drop a
  captured frame's raw bytes into https://ide.kaitai.io/ . Context + open questions: PROTOCOL.md.
  Corrections/contradictions welcome.
seq:
  - id: sub_type
    type: u2
    enum: sub
    doc: "0101 = room/occupancy grid; 0201 = cleaning path; 0301 = full-map alternate/master grid layer (same codec as 0101); 0401 = per-room sub-grids (small bounding boxes, same codec). ✅"
  - id: body
    type:
      switch-on: sub_type
      cases:
        'sub::grid': grid_header
        'sub::path': path_header
        'sub::grid_alt': grid_header
        'sub::grid_room': grid_header
enums:
  sub:
    0x0101: grid
    0x0201: path
    0x0301: grid_alt
    0x0401: grid_room
types:
  grid_header:
    doc: "Header then an LZ4 block. Bytes 0-1 (the sub_type) are consumed above. Used by 0101 (room/occupancy grid), 0301 (full-map alternate/master layer), and 0401 (per-room sub-grids) — all share the identical codec. ✅"
    seq:
      - id: map_id
        size: 4
        doc: "Device-specific map id (constant per device/home; PLACEHOLDER when published). ✅"
      - id: map_segmented_flag
        type: u1
        doc: |
          MAP-SEGMENTED / FINALIZED FLAG (🟡). 0 while the map is still being built (no room
          records), 1 once it is finalized into rooms — verified byte6==1 iff rooms>0 on 89/89 frames of a
          from-scratch build (it flips the instant the room records appear). Earlier captures only saw
          already-built maps (always 1), which is why it was previously mislabeled "constant 0x01".
      - id: width
        type: u2
        doc: "Grid width in pixels. ✅ — equals empirical row-stride detection on 424/424 captured frames."
      - id: height
        type: u2
        doc: "Grid height in pixels. ✅ (same verification)."
      - id: x_min
        type: s2
        doc: "Map origin X, raw s16 BE in 5-mm header-units (= 2 path-units each). Per-map constant; differs across maps. ✅ decode_map.py reads it via origin_from_header(): oy = -2*x_min (multiply the RAW s16 by 2 → path-units). NOT divide-by-10 — the validated transform multiplies by 2, so a literal /10 gives a badly wrong origin. Auto-fit is the fallback."
      - id: y_min
        type: s2
        doc: "Map origin Y, raw s16 BE in 5-mm header-units (= 2 path-units each). Per-map constant; differs across maps. ✅ Read with x_min: ox = 2*y_min (raw s16 ×2 → path-units)."
      - id: resolution
        type: u2
        doc: "Grid resolution u16 BE, divide by 100 to get m/px. Always 5 -> 0.05 m/px = 50 mm/px. ✅"
      - id: charge_x
        type: u2
        doc: "Dock/charger X in header coordinate units (same 5-mm scale as x_min/y_min; subtract x_min for origin-relative position). ✅"
      - id: charge_y
        type: u2
        doc: "Dock/charger Y in header coordinate units (same 5-mm scale as x_min/y_min). ✅"
      - id: charge_phi
        type: s2
        doc: "Dock heading in degrees (negate the raw value). ✅"
      - id: declared_size_high
        type: u2
        doc: "High u16 of a u32 declared-size field; observed always 0x0000. Low u16 follows as declared_size. 🟡"
      - id: declared_size
        type: u2
        doc: "Decompressed size = width*height + trailing room-record overhead. ✅"
      - id: compressed_size
        type: u2
        doc: "LZ4 block length in bytes. ✅"
      - id: lz4_body
        size: compressed_size
        doc: |
          LZ4-compressed occupancy grid (decompress externally). Decoded: pixel//4 = room_id, 243 = outside,
          249 = wall; followed by room-name records. ✅
  path_header:
    doc: |
      14-byte header (incl. the 2-byte sub_type) then BE int16 (x,y) path-unit pairs (≈2.5 mm/unit, not true
      mm) to end-of-frame. Raw pose extraction starts at byte 14 (point_count is then EXACT — verified 850/850
      frames across 10 captures). NOTE: decode_map.py's render pipeline instead reads from byte 16 (a render-path
      legacy, flagged for refactor); that offset is a renderer choice, not the frame structure.
    seq:
      - id: path_epoch
        type: u2
        doc: |
          Path-epoch counter: resets on power-cycle, +1 per new traversal (undock / relocalize / clean-start);
          a skip >1 ⇒ the robot moved while uncaptured. ✅ (The old "byte-3 clean_counter" 0x08/0x11 were just
          the low byte of this u16 at epochs 8/17.)
      - id: const_04_07
        size: 4
        doc: "Constant 0x00020000 across 3,440 captured path frames. ✅ Semantics unnamed."
      - id: point_count
        type: u2
        doc: "Number of path points. ✅ (== actual (x,y) pairs when parsing from byte 14; reads one higher only against the byte-16 render offset.)"
      - id: heading_deg
        type: s2
        doc: |
          Live firmware SLAM heading, DEGREES (0=+x, +90=+y, ±180=−x, −90=−y). ✅ This header field IS the
          "missing heading DP". Accuracy: drive-mode 1–2° (long straight runs); teleop 8.7° mae; clean-mode
          per-frame is NOISY (~18–52°, capture-dependent) — NOT a tight regime. A localization loss (FAULT 556)
          snaps it to 0° with the pose at ≈(0,0). NB the official app does NOT read this field — it recomputes
          heading from path geometry; we use the firmware field directly for closed-loop nav.
      - id: const_12_13
        type: u2
        doc: "Constant 0x0000 across 3,440 captured path frames. ✅ Semantics unnamed."
      - id: points
        type: point
        repeat: eos
        doc: |
          Cleaning path: last point = current robot position, first ≈ dock. Some autonomous dock-rooted cleans
          prepend one stray leading point ≈ the map origin (e.g. (-3,0)); strip via a gross-outlier test on
          pts[0]. Absent on teleop/heartbeat and map-builds. OPEN (⬜): what triggers it.
  point:
    seq:
      - id: x
        type: s2
      - id: y
        type: s2
