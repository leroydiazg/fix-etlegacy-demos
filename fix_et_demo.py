#!/usr/bin/env python3
"""
fix_et_demo.py -- Fixes ET:Legacy demos (.dm_84) that crash with
"bad command byte" on playback, when the cause is that the recording
server wrote a malformed "mod_version" configstring.

This works around a known ET:Legacy bug: CG_ParseDemoVersion() calls
strtok(versionStr, ".") three times, expecting major.minor.patch. If the
server sent something like "2.83" (missing the patch part), the third
strtok() call returns NULL, and Q_atoi(NULL) -> strtol(NULL, ...) is
undefined behaviour and crashes the client.

Usage:
    python3 fix_et_demo.py input.dm_84 [output.dm_84]

If no output path is given, "<input>_fixed.dm_84" is generated.

No external dependencies (Python 3 standard library only).
"""
import struct
import sys
import os

from et_msg import BitStream, GENTITYNUM_BITS
from et_entity import read_delta_entity, write_delta_entity

SVC_EOF = 8
SVC_CONFIGSTRING = 3
SVC_BASELINE = 4

CS_SERVERINFO = 0  # configstring index for serverinfo


def decode_gamestate(msgdata):
    """Decodes the first full message (gamestate) into a list of events."""
    bs = BitStream(msgdata)
    events = []

    events.append(("long", bs.read_long()))          # reliableAcknowledge

    cmd = bs.read_byte()
    events.append(("byte", cmd))
    if cmd != 2:  # svc_gamestate
        raise ValueError(f"First message is not svc_gamestate (cmd={cmd}); "
                          f"this demo might have a different format than expected.")

    events.append(("long", bs.read_long()))          # serverCommandSequence

    configstrings = []

    while True:
        cmd2 = bs.read_byte()
        events.append(("byte", cmd2))
        if cmd2 == SVC_EOF:
            break
        elif cmd2 == SVC_CONFIGSTRING:
            csnum = bs.read_short()
            events.append(("short", csnum))
            cs = bs.read_string_bytes()
            events.append(("string", cs))
            configstrings.append((len(events) - 1, csnum, cs))
        elif cmd2 == SVC_BASELINE:
            entnum = bs.read_bits(GENTITYNUM_BITS)
            events.append(("bits", GENTITYNUM_BITS, entnum))
            ent_events = read_delta_entity(bs)
            events.append(("entity", ent_events))
        else:
            raise ValueError(
                f"Unexpected command byte ({cmd2}) while decoding the gamestate. "
                f"This indicates a bit-level desync: the demo may use entity "
                f"fields that differ from official ET:Legacy (a real protocol "
                f"incompatibility, not just a version-string issue)."
            )

    events.append(("long", bs.read_long()))   # clientNum
    events.append(("long", bs.read_long()))   # checksumFeed
    events.append(("byte", bs.read_byte()))   # final svc_EOF

    return events, configstrings


def encode_gamestate(events):
    bs = BitStream(b"")
    for ev in events:
        kind = ev[0]
        if kind == "long":
            bs.write_long(ev[1])
        elif kind == "byte":
            bs.write_byte(ev[1])
        elif kind == "short":
            bs.write_short(ev[1])
        elif kind == "string":
            bs.write_string_bytes(ev[1])
        elif kind == "bits":
            bs.write_bits(ev[2], ev[1])
        elif kind == "entity":
            write_delta_entity(bs, ev[1])
        else:
            raise ValueError(f"Unknown event type: {kind}")
    nbytes = (bs.bio.bit + 7) >> 3
    return bytes(bs.bio.data[:nbytes])


def fix_mod_version(cs_bytes):
    """
    If mod_version doesn't have 3 numeric parts (major.minor.patch), pad
    the missing ones with "0". Returns (new_configstring, changed, info).
    """
    key = b"\\mod_version\\"
    idx = cs_bytes.find(key)
    if idx == -1:
        return cs_bytes, False, "no mod_version key found"

    start = idx + len(key)
    end = cs_bytes.find(b"\\", start)
    if end == -1:
        end = len(cs_bytes)
    old_val = cs_bytes[start:end]

    stripped = old_val.lstrip(b"vV")
    parts = [p for p in stripped.split(b".")]

    if len(parts) >= 3 and all(p.isdigit() for p in parts[:3]):
        return cs_bytes, False, f"mod_version already valid: {old_val!r}"

    # normalize: drop non-numeric leftover parts, pad with 0
    numeric_parts = []
    for p in parts:
        if p.isdigit():
            numeric_parts.append(p)
    while len(numeric_parts) < 3:
        numeric_parts.append(b"0")

    new_val = b".".join(numeric_parts[:3])
    new_cs = cs_bytes[:start] + new_val + cs_bytes[end:]
    return new_cs, True, f"{old_val!r} -> {new_val!r}"


def patch_events(events, configstrings):
    changed = False
    for pos, csnum, cs in configstrings:
        if csnum == CS_SERVERINFO:
            new_cs, did_change, info = fix_mod_version(cs)
            print(f"  cs[{csnum}] (CS_SERVERINFO): {info}")
            if did_change:
                events[pos] = ("string", new_cs)
                changed = True
    return changed


def fix_demo_file(input_path, output_path):
    with open(input_path, "rb") as f:
        header = f.read(8)
        if len(header) < 8:
            raise ValueError("File is too small / corrupted.")
        seq, length = struct.unpack("<ii", header)
        if length <= 0 or length > 10_000_000:
            raise ValueError(f"Suspicious first-message length: {length}")
        msgdata = f.read(length)
        rest_start = f.tell()

    print(f"Analyzing '{input_path}' ...")
    events, configstrings = decode_gamestate(msgdata)

    print("Configstrings of interest found:")
    changed = patch_events(events, configstrings)

    if not changed:
        print("\nNo mod_version formatting issue detected.")
        print("If the demo still crashes, the cause is something else (not the version string).")
        return False

    new_msgdata = encode_gamestate(events)

    # Sanity check: re-decode what we're about to write, to catch any
    # encoding bug before touching the output file.
    decode_gamestate(new_msgdata)

    new_header = struct.pack("<ii", seq, len(new_msgdata))

    # Efficient copy: write the new frame 0, then stream the rest of the
    # file in chunks without loading it entirely into memory (important
    # for large demos).
    with open(input_path, "rb") as fin, open(output_path, "wb") as fout:
        fout.write(new_header)
        fout.write(new_msgdata)
        fin.seek(rest_start)
        while True:
            chunk = fin.read(1024 * 1024)
            if not chunk:
                break
            fout.write(chunk)

    print(f"\nSaved: {output_path}")
    print(f"  Original frame 0: {length} bytes -> new: {len(new_msgdata)} bytes")
    return True


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
        fix_demo_file(input_path, output_path)
    except Exception as e:
        print(f"\nERROR: {e}")
        sys.exit(1)


if __name__ == "__main__":
    main()
