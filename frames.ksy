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

  As of 2026-06-16 · firmware 03.11.24 · sessions s5-s26. Per-field confidence is in each `doc:`
  (✅ confirmed / 🟡 plausible / ⬜ unknown). NOT a vendor spec. To verify against YOUR device, drop a
  captured frame's raw bytes into https://ide.kaitai.io/ . Context + open questions: PROTOCOL.md.
  Corrections/contradictions welcome.
seq:
  - id: sub_type
    type: u2
    enum: sub
    doc: "0101 = room/occupancy grid; 0201 = cleaning path. ✅ s5-s26."
  - id: body
    type:
      switch-on: sub_type
      cases:
        'sub::grid': grid_header
        'sub::path': path_header
enums:
  sub:
    0x0101: grid
    0x0201: path
types:
  grid_header:
    doc: "29-byte header then an LZ4 block. Bytes 0-1 (the sub_type) are consumed above."
    seq:
      - id: map_id
        size: 4
        doc: "Device-specific map id (constant per device/home; PLACEHOLDER when published). ✅ s5."
      - id: map_segmented_flag
        type: u1
        doc: |
          MAP-SEGMENTED / FINALIZED FLAG (🟡 s26). 0 while the map is still being built (no room
          records), 1 once it is finalized into rooms — verified byte6==1 iff rooms>0 on 89/89 frames of a
          from-scratch build (it flips the instant the room records appear). Earlier captures only saw
          already-built maps (always 1), which is why it was previously mislabeled "constant 0x01".
      - id: width
        type: u2
        doc: "Grid width in pixels. ✅ s25 — equals empirical row-stride detection on 424/424 captured frames."
      - id: height
        type: u2
        doc: "Grid height in pixels. ✅ s25 (same verification)."
      - id: unknown_11_24
        size: 14
        doc: |
          UNKNOWN header block (raw[11:25]). Observed sub-structure (🟡 s26): [11]=0x04 (steady state;
          0x00/0x02 in the first few tiny build frames); [12:14]=0x6901 const per map; [14] tracks ~10*H;
          [15]=0; [16]=0x05 const; [17]=session/mode flag;
          [18:22]=per-frame scan-progress counter; [22]=per-frame; [23:25]=0. NO bounding-box/origin is
          present here (exhaustive search, s25) — the map origin is NOT transmitted in the 301 stream.
      - id: declared_size
        type: u2
        doc: "Decompressed size = width*height + trailing room-record overhead. ✅ s25."
      - id: compressed_size
        type: u2
        doc: "LZ4 block length in bytes. ✅ s5."
      - id: lz4_body
        size: compressed_size
        doc: |
          LZ4-compressed occupancy grid (decompress externally). Decoded: pixel//4 = room_id, 243 = outside,
          249 = wall; followed by room-name records. ✅ s5-s6.
  path_header:
    doc: "16-byte header (incl. the 2-byte sub_type) then BE int16 (x,y) mm point pairs to end-of-frame."
    seq:
      - id: unknown_02
        type: u1
        doc: "UNKNOWN sub-header byte. ⬜"
      - id: clean_counter
        type: u1
        doc: "Per-clean counter (0x08 and 0x11 eras both observed); NOT a structure flag. 🟡 s23."
      - id: unknown_04_07
        size: 4
        doc: "UNKNOWN. ⬜"
      - id: point_count
        type: u2
        doc: "Declared number of path points. ✅ s6."
      - id: unknown_10_15
        size: 6
        doc: "UNKNOWN header tail (completes the 16-byte header). ⬜"
      - id: points
        type: point
        repeat: eos
        doc: |
          Cleaning path: last point = current robot position, first ≈ dock. OPEN (⬜ s24): 0x11+ firmware
          prepends a spurious sentinel ~(0,-1907) outside the map — strip via a gross-outlier test on pts[0].
  point:
    seq:
      - id: x
        type: s2
      - id: y
        type: s2
