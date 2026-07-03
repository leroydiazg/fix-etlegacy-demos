# fix_et_demo — fix ET:Legacy demos that crash with "bad command byte" / "Illegible server message"

## What it does

Fixes ET:Legacy `.dm_84` demo recordings from servers that write a
malformed `mod_version` value into `CS_SERVERINFO` (e.g. `"2.83"` or
`"2.83-dirty"` instead of a clean `"X.Y.Z"`). That malformed value
crashes the official ET:Legacy client during demo playback, because
`CG_ParseDemoVersion()` always expects `major.minor.patch` and calls
`strtok()` three times — if a part is missing, it passes `NULL` into
`Q_atoi()`, which is undefined behaviour (crash).

Crucially, `CG_ParseDemoVersion()` re-runs every time cgame
(re)initializes during playback, not just once at the start. Servers
commonly re-broadcast `CS_SERVERINFO` mid-demo via a `cs 0 ...` command
— for example on a `map_restart`, or a warmup-to-match transition — so a
malformed `mod_version` can crash playback well into the demo even if
the very first frame looked perfectly fine. This tool scans the
**entire** file, not just the first frame: it finds and fixes
`mod_version` in the initial gamestate's `CS_SERVERINFO` **and** in
every later `cs 0 ...` resend.

The script implements ET's adaptive Huffman codec, message layer,
entity delta, and playerState delta in Python (a faithful port of the
official ET:Legacy `huffman.c` / `msg.c`), verified with bit-for-bit
round-trip tests against real demos (including all snapshot, entity,
and playerState content, not just configstrings). Frames that don't
need patching are copied straight through without full decoding, so
this stays fast even on large, many-frame demos (tens of MB / tens of
thousands of frames process in seconds).

If a demo's `mod_version` is already well-formed everywhere it appears,
the script leaves it untouched and tells you that the crash (if it
persists) has a different cause — typically a genuine entity/protocol
incompatibility between the mod that recorded the demo and the official
engine, which this script cannot fix.

## Requirements

Python 3 standard library only (3.7+). Nothing else to install.

## Usage

```bash
python3 fix_et_demo.py input.dm_84
```

This produces `input_fixed.dm_84` in the same directory.

Or specifying the output path:

```bash
python3 fix_et_demo.py input.dm_84 output.dm_84
```

## Files

- `fix_et_demo.py` — CLI entry point
- `et_message.py` — generic per-frame decode/encode/patch (serverCommand,
  gamestate, snapshot) and the full-file scan/patch driver
- `et_huffman.py` — port of the adaptive Huffman algorithm (huffman.c)
- `et_msg.py` — message bit read/write layer (msg.c)
- `et_entity.py` — entity field table and delta encoding
- `et_playerstate.py` — playerState field table and delta encoding
- `msg_hdata.py` — initial Huffman weight table (256 values)

All `.py` files must be kept in the same directory.

## Limitations

- This only fixes the specific `mod_version` issue. If the crash comes
  from a different cause (e.g. the mod that recorded the demo added
  entity or playerState fields the official engine doesn't know about),
  the script will report "no issue found" but won't be able to fix it —
  that would require the exact source of the mod that recorded the
  demo.
- Tested against ET:Legacy 2.8x `.dm_84` demos. Other protocol versions
  are not supported.

