import struct
from et_msg import BitStream, GENTITYNUM_BITS
from et_entity import read_delta_entity, write_delta_entity
from et_playerstate import read_delta_playerstate, write_delta_playerstate

CS_SERVERINFO = 0  # configstring index for serverinfo
TARGET_MOD_VERSION_SUFFIX = b".2"


def fix_mod_version(cs_bytes):
    """
    If mod_version doesn't have 3 clean numeric parts (major.minor.patch),
    keep the ENTIRE original value as-is and just append ".2" at the end
    (e.g. "2.83-dirty" -> "2.83-dirty.2"). This guarantees a 3rd
    strtok(".") token exists (so CG_ParseDemoVersion() never passes NULL
    into Q_atoi/strtol), without trying to parse or clean up the original
    string at all.
    Returns (new_configstring, changed, info).
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

    parts = old_val.lstrip(b"vV").split(b".")
    if len(parts) >= 3 and all(p.isdigit() for p in parts[:3]):
        return cs_bytes, False, f"mod_version already valid: {old_val!r}"

    new_val = old_val + TARGET_MOD_VERSION_SUFFIX
    new_cs = cs_bytes[:start] + new_val + cs_bytes[end:]
    return new_cs, True, f"{old_val!r} -> {new_val!r}"


SVC_NOP = 1
SVC_GAMESTATE = 2
SVC_CONFIGSTRING = 3
SVC_BASELINE = 4
SVC_SERVERCOMMAND = 5
SVC_DOWNLOAD = 6
SVC_SNAPSHOT = 7
SVC_EOF = 8

MAX_GENTITIES_MINUS_1 = 1023


def decode_gamestate_body(bs, events):
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
            raise ValueError(f"gamestate: unexpected cmd2={cmd2}")
    events.append(("long", bs.read_long()))   # clientNum
    events.append(("long", bs.read_long()))   # checksumFeed
    return configstrings


def encode_gamestate_body(bs, events, idx):
    while True:
        kind, cmd2 = events[idx]; idx += 1
        bs.write_byte(cmd2)
        if cmd2 == SVC_EOF:
            break
        elif cmd2 == SVC_CONFIGSTRING:
            kind, csnum = events[idx]; idx += 1
            bs.write_short(csnum)
            kind, cs = events[idx]; idx += 1
            bs.write_string_bytes(cs)
        elif cmd2 == SVC_BASELINE:
            kind, nbits, entnum = events[idx]; idx += 1
            bs.write_bits(entnum, nbits)
            kind, ent_events = events[idx]; idx += 1
            write_delta_entity(bs, ent_events)
    kind, client_num = events[idx]; idx += 1
    bs.write_long(client_num)
    kind, checksum_feed = events[idx]; idx += 1
    bs.write_long(checksum_feed)
    return idx


def decode_snapshot_body(bs, events):
    events.append(("long", bs.read_long()))   # serverTime
    events.append(("byte", bs.read_byte()))   # deltaNum
    events.append(("byte", bs.read_byte()))   # snapFlags
    arealen = bs.read_byte()
    events.append(("byte", arealen))
    if arealen < 0 or arealen > 64:
        raise ValueError(f"snapshot: invalid areamask length {arealen}")
    area = bytes(bs.read_byte() for _ in range(arealen))
    events.append(("rawbytes", area))
    ps_events = read_delta_playerstate(bs)
    events.append(("playerstate", ps_events))
    ent_list = []
    while True:
        newnum = bs.read_bits(GENTITYNUM_BITS)
        if newnum >= MAX_GENTITIES_MINUS_1:
            ent_list.append(("term", newnum))
            break
        ent_events = read_delta_entity(bs)
        ent_list.append(("ent", newnum, ent_events))
    events.append(("entlist", ent_list))


def encode_snapshot_body(bs, events, idx):
    kind, server_time = events[idx]; idx += 1
    bs.write_long(server_time)
    kind, delta_num = events[idx]; idx += 1
    bs.write_byte(delta_num)
    kind, snap_flags = events[idx]; idx += 1
    bs.write_byte(snap_flags)
    kind, arealen = events[idx]; idx += 1
    bs.write_byte(arealen)
    kind, area = events[idx]; idx += 1
    for b in area:
        bs.write_byte(b)
    kind, ps_events = events[idx]; idx += 1
    write_delta_playerstate(bs, ps_events)
    kind, ent_list = events[idx]; idx += 1
    for item in ent_list:
        if item[0] == "term":
            bs.write_bits(item[1], GENTITYNUM_BITS)
        else:
            _, newnum, ent_events = item
            bs.write_bits(newnum, GENTITYNUM_BITS)
            write_delta_entity(bs, ent_events)
    return idx


def decode_message(msgdata):
    """
    Decodes ANY frame's message (not just gamestates) into a flat event
    list, tracking which events are "cs 0 ..." server commands (so their
    embedded CS_SERVERINFO value can be patched) and which are the
    initial gamestate's own configstrings.
    """
    bs = BitStream(msgdata)
    events = []
    events.append(("long", bs.read_long()))  # reliableAcknowledge

    patch_targets = []  # list of (tag, event_index): "gamestate_cs" or "cs_command"

    while True:
        cmd = bs.read_byte()
        events.append(("byte", cmd))
        if cmd == SVC_EOF:
            break
        elif cmd == SVC_NOP:
            pass
        elif cmd == SVC_SERVERCOMMAND:
            events.append(("long", bs.read_long()))
            s = bs.read_string_bytes()
            events.append(("string", s))
            if _is_cs0_command(s):
                patch_targets.append(("cs_command", len(events) - 1))
        elif cmd == SVC_GAMESTATE:
            events.append(("long", bs.read_long()))  # serverCommandSequence
            configstrings = decode_gamestate_body(bs, events)
            for pos, csnum, cs in configstrings:
                if csnum == CS_SERVERINFO:
                    patch_targets.append(("gamestate_cs", pos))
            top_eof = bs.read_byte()  # top-level message terminator
            events.append(("byte", top_eof))
            break
        elif cmd == SVC_SNAPSHOT:
            decode_snapshot_body(bs, events)
        else:
            raise ValueError(f"top-level: unexpected/illegible cmd={cmd}")

    return events, patch_targets


def _is_cs0_command(s):
    """True if `s` is a 'cs 0 ...' command (a configstring update for index 0, CS_SERVERINFO)."""
    parts = s.split(b" ", 2)
    if len(parts) < 2 or parts[0] != b"cs":
        return False
    return parts[1] == b"0"


def _extract_quoted_value(s):
    """
    Given b'cs 0 "\\...\\..."', return (prefix_bytes, value_bytes, suffix_bytes)
    so the value can be replaced in place. Handles the common quoted form;
    falls back to "everything after the 2nd token" if unquoted.
    """
    parts = s.split(b" ", 2)
    rest = parts[2] if len(parts) == 3 else b""
    if rest[:1] == b'"' and rest[-1:] == b'"' and len(rest) >= 2:
        prefix = s[:len(s) - len(rest)] + b'"'
        value = rest[1:-1]
        suffix = b'"'
        return prefix, value, suffix
    else:
        prefix = s[:len(s) - len(rest)]
        return prefix, rest, b""


def encode_message(events):
    bs = BitStream(b"")
    idx = 0

    def next_ev():
        nonlocal idx
        e = events[idx]
        idx += 1
        return e

    kind, reliable_ack = next_ev()
    bs.write_long(reliable_ack)

    while True:
        kind, cmd = next_ev()
        bs.write_byte(cmd)
        if cmd == SVC_EOF:
            break
        elif cmd == SVC_NOP:
            pass
        elif cmd == SVC_SERVERCOMMAND:
            kind, seq = next_ev()
            bs.write_long(seq)
            kind, s = next_ev()
            bs.write_string_bytes(s)
        elif cmd == SVC_GAMESTATE:
            kind, scs = next_ev()
            bs.write_long(scs)
            idx = encode_gamestate_body(bs, events, idx)
            kind, top_eof = next_ev()
            bs.write_byte(top_eof)
            break
        elif cmd == SVC_SNAPSHOT:
            idx = encode_snapshot_body(bs, events, idx)
        else:
            raise ValueError(f"encode: unknown top-level cmd={cmd}")

    nbytes = (bs.bio.bit >> 3) + 1
    return bytes(bs.bio.data[:nbytes])


def fast_scan_frame(msgdata):
    """
    Cheaply determines whether a frame's message needs full decode/patch,
    without paying the cost of parsing entity/playerstate deltas when it
    isn't necessary.

    Relies on a real engine invariant (SV_SendMessageToClient in
    sv_snapshot.c): SV_UpdateServerCommandsToClient() always runs before
    SV_WriteSnapshotToClient(), so a svc_serverCommand entry can never
    appear AFTER a svc_snapshot within the same message. This means once
    we see a snapshot (or download) with no matching 'cs 0' command so
    far, nothing later in the frame could need patching either, and we
    can stop without parsing the (expensive) snapshot body at all.

    Returns one of:
      ("none",)              -- nothing to patch, safe to copy verbatim
      ("gamestate",)          -- contains svc_gamestate, needs full parse
      ("needs_patch",)        -- a leading 'cs 0' command needs patching
    """
    bs = BitStream(msgdata)
    bs.read_long()  # reliableAcknowledge
    while True:
        cmd = bs.read_byte()
        if cmd == SVC_EOF:
            return ("none",)
        elif cmd == SVC_NOP:
            continue
        elif cmd == SVC_SERVERCOMMAND:
            bs.read_long()
            s = bs.read_string_bytes()
            if _is_cs0_command(s):
                return ("needs_patch",)
        elif cmd == SVC_GAMESTATE:
            return ("gamestate",)
        else:
            # svc_snapshot, svc_download, or anything else: per the
            # engine's send order, no further serverCommand can follow,
            # so there is nothing left in this frame worth patching.
            return ("none",)


def patch_demo_file(input_path, output_path, fix_mod_version, log=print):
    """
    Walks the ENTIRE demo file (not just the first frame), patching
    mod_version wherever it appears: the initial gamestate's own
    CS_SERVERINFO, and any later 'cs 0 ...' command that re-broadcasts it
    (e.g. servers commonly do this on map_restart / warmup-to-match
    transitions). Frames that don't need touching are copied through
    unchanged without full decoding, so this stays fast even on large,
    many-frame demos.
    """
    with open(input_path, "rb") as f:
        data = f.read()

    log(f"Analyzing '{input_path}' ({len(data):,} bytes) ...")

    out = bytearray()
    pos = 0
    frame_idx = 0
    patched_count = 0
    any_changed = False

    while pos + 8 <= len(data):
        seq, length = struct.unpack_from("<ii", data, pos)

        if length == -1:
            out.extend(data[pos:])
            pos = len(data)
            break

        if length < 0 or pos + 8 + length > len(data):
            log(f"  frame {frame_idx} (offset {pos}): corrupt frame length "
                f"({length}); stopping scan, copying the rest through unchanged.")
            out.extend(data[pos:])
            pos = len(data)
            break

        msgdata = data[pos + 8: pos + 8 + length]

        try:
            kind = fast_scan_frame(msgdata)[0]
        except Exception:
            kind = "gamestate"  # be conservative: force a full parse attempt

        if kind == "none":
            out.extend(data[pos:pos + 8 + length])
        else:
            try:
                events, patch_targets = decode_message(msgdata)
                changed = patch_message(events, patch_targets, fix_mod_version,
                                         log=lambda m: log(f"  frame {frame_idx} (offset {pos}): {m.strip()}"))
                if changed:
                    new_msgdata = encode_message(events)
                    # sanity round-trip check before trusting the new bytes
                    decode_message(new_msgdata)
                    new_header = struct.pack("<ii", seq, len(new_msgdata))
                    out.extend(new_header)
                    out.extend(new_msgdata)
                    patched_count += 1
                    any_changed = True
                else:
                    out.extend(data[pos:pos + 8 + length])
            except Exception as e:
                log(f"  frame {frame_idx} (offset {pos}): failed to parse/patch "
                    f"({e}); copying through unchanged.")
                out.extend(data[pos:pos + 8 + length])

        pos += 8 + length
        frame_idx += 1

    if pos < len(data):
        out.extend(data[pos:])

    log(f"\nScanned {frame_idx} frame(s), patched {patched_count} of them.")

    if not any_changed:
        log("No mod_version formatting issue detected anywhere in the file.")
        return False

    with open(output_path, "wb") as f:
        f.write(out)

    log(f"Saved: {output_path}")
    return True


def patch_message(events, patch_targets, fix_mod_version, log=None):
    """
    Applies fix_mod_version to every CS_SERVERINFO-like value found in
    this message: either the gamestate's own configstring[0], or any
    'cs 0 ...' server command that re-broadcasts it later in the demo.
    Mutates `events` in place. Returns True if anything changed.
    """
    changed = False
    for tag, idx in patch_targets:
        kind, content = events[idx]
        if tag == "gamestate_cs":
            new_cs, did_change, info = fix_mod_version(content)
            if log:
                log(f"  gamestate cs[0] (CS_SERVERINFO): {info}")
            if did_change:
                events[idx] = ("string", new_cs)
                changed = True
        elif tag == "cs_command":
            prefix, value, suffix = _extract_quoted_value(content)
            new_value, did_change, info = fix_mod_version(value)
            if log:
                log(f"  'cs 0' command (mid-demo CS_SERVERINFO resend): {info}")
            if did_change:
                new_full = prefix + new_value + suffix
                events[idx] = ("string", new_full)
                changed = True
    return changed
