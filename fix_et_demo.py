#!/usr/bin/env python3
"""
fix_et_demo.py -- Fixes ET:Legacy demos (.dm_84) that crash with
"bad command byte" / "Illegible server message" on playback, when the
cause is that the recording server wrote a malformed "mod_version"
configstring.

This works around a known ET:Legacy bug: CG_ParseDemoVersion() calls
strtok(versionStr, ".") three times, expecting major.minor.patch. If the
server sent something like "2.83" (missing the patch part), the third
strtok() call returns NULL, and Q_atoi(NULL) -> strtol(NULL, ...) is
undefined behaviour and crashes the client.

CG_ParseDemoVersion() re-runs every time cgame (re)initializes during
playback -- not just once at the very start. Servers commonly re-send
CS_SERVERINFO (and therefore mod_version) mid-demo via a "cs 0 ..."
command -- e.g. on a map_restart or a warmup-to-match transition -- so a
malformed mod_version can crash playback well into the demo even if the
very first frame looked fine. This script scans the ENTIRE file for:
  - the initial gamestate's own CS_SERVERINFO configstring, and
  - every later "cs 0 ..." command that re-broadcasts it,
and fixes mod_version in all of them. Frames that don't need touching
are copied through unchanged without full decoding, so this stays fast
even on large, many-frame demos.

Usage:
    python3 fix_et_demo.py input.dm_84 [output.dm_84]

If no output path is given, "<input>_fixed.dm_84" is generated.

No external dependencies (Python 3 standard library only).
"""
import sys
import os

from et_message import patch_demo_file, fix_mod_version


def main():
    if len(sys.argv) < 2:
        print(__doc__)
        sys.exit(1)

    input_path = sys.argv[1]
    if len(sys.argv) >= 3:
        output_path = sys.argv[2]
    else:
        base, ext = os.path.splitext(input_path)
        output_path = f"{base}_fixed{ext}"

    if not os.path.isfile(input_path):
        print(f"Error: file '{input_path}' does not exist")
        sys.exit(1)

    try:
        patch_demo_file(input_path, output_path, fix_mod_version)
    except Exception as e:
        print(f"\nERROR: {e}")
        sys.exit(1)


if __name__ == "__main__":
    main()
