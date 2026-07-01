# fix_et_demo — fix ET:Legacy demos that crash with "bad command byte"

## What it does

Fixes ET:Legacy `.dm_84` demo recordings from servers that write a
malformed `mod_version` value into `CS_SERVERINFO` (e.g. `"2.83"`
instead of `"2.83.2"`). That malformed value crashes the official
ET:Legacy client with "bad command byte" during demo playback, because
`CG_ParseDemoVersion()` always expects `major.minor.patch` and calls
`strtok()` three times — if a part is missing, it passes `NULL` into
`Q_atoi()`, which is undefined behaviour (crash).

The script implements ET's adaptive Huffman codec in Python (a faithful
port of the official ET:Legacy `huffman.c` / `msg.c`), verified with a
bit-for-bit round-trip against an official demo (including all
baseline delta-compressed entities). It locates `mod_version` inside
the first message (the gamestate), normalizes it to 3 numeric parts
(padding whatever is missing with `.0`), and re-encodes **only that
first message**. The rest of the file is copied through unchanged, via
streaming, without loading it entirely into memory — so it works fine
on large demos.

If the demo's `mod_version` is already well-formed, the script leaves
it untouched and tells you that the crash (if it persists) has a
different cause — typically a genuine entity/map incompatibility
between the mod that recorded the demo and the official engine, which
this script cannot fix.

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

- `fix_et_demo.py` — main script (CLI)
- `et_huffman.py` — port of the adaptive Huffman algorithm (huffman.c)
- `et_msg.py` — message bit read/write layer (msg.c)
- `et_entity.py` — entity field table and delta encoding
- `msg_hdata.py` — initial Huffman weight table (256 values)

All `.py` files must be kept in the same directory.

## Limitations

- This only fixes the specific `mod_version` issue. If "bad command
  byte" comes from a different cause (e.g. the mod that recorded the
  demo added entity fields the official engine doesn't know about),
  the script will report "no issue found" but won't be able to fix
  it — that would require the exact source of the mod that recorded
  the demo.
- Tested against ET:Legacy 2.8x `.dm_84` demos. Other protocol
  versions are not supported.
