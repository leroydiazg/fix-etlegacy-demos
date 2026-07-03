"""
Diagnostic-only: MSG_ReadDeltaPlayerstate port (playerStateFields[] table +
array reads for stats/persistant/holdable/powerups/ammo/ammoclip).
Used to fully walk svc_snapshot messages so we can pinpoint exactly where
a demo's byte stream desyncs, past the point our shipped tool touches.
"""
from et_msg import GENTITYNUM_BITS, ANIM_BITS, FLOAT_INT_BITS

# (name, bits) -- 0 means "special float", negative means signed integer
PLAYER_STATE_FIELDS = [
    ("commandTime", 32), ("pm_type", 8), ("bobCycle", 8), ("pm_flags", 16),
    ("pm_time", -16),
    ("origin0", 0), ("origin1", 0), ("origin2", 0),
    ("velocity0", 0), ("velocity1", 0), ("velocity2", 0),
    ("weaponTime", -16), ("weaponDelay", -16), ("grenadeTimeLeft", -16),
    ("gravity", 16), ("leanf", 0), ("speed", 16),
    ("delta_angles0", 16), ("delta_angles1", 16), ("delta_angles2", 16),
    ("groundEntityNum", GENTITYNUM_BITS),
    ("legsTimer", 16), ("torsoTimer", 16),
    ("legsAnim", ANIM_BITS), ("torsoAnim", ANIM_BITS),
    ("movementDir", 8), ("eFlags", 24), ("eventSequence", 8),
    ("events0", 8), ("events1", 8), ("events2", 8), ("events3", 8),
    ("eventParms0", 8), ("eventParms1", 8), ("eventParms2", 8), ("eventParms3", 8),
    ("clientNum", 8),
    ("weapons0", 32), ("weapons1", 32),
    ("weapon", 7), ("weaponstate", 4), ("weapAnim", 10),
    ("viewangles0", 0), ("viewangles1", 0), ("viewangles2", 0),
    ("viewheight", -8),
    ("damageEvent", 8), ("damageYaw", 8), ("damagePitch", 8), ("damageCount", 8),
    ("mins0", 0), ("mins1", 0), ("mins2", 0),
    ("maxs0", 0), ("maxs1", 0), ("maxs2", 0),
    ("crouchMaxZ", 0), ("crouchViewHeight", 0), ("standViewHeight", 0),
    ("deadViewHeight", 0), ("runSpeedScale", 0), ("sprintSpeedScale", 0),
    ("crouchSpeedScale", 0), ("friction", 0),
    ("viewlocked", 8), ("viewlocked_entNum", 16),
    ("nextWeapon", 8), ("teamNum", 8),
    ("onFireStart", 32), ("curWeapHeat", 8), ("aimSpreadScale", 8),
    ("serverCursorHint", 8), ("serverCursorHintVal", 8),
    ("classWeaponTime", 32), ("identifyClient", 8), ("identifyClientHealth", 8),
    ("aiState", 2),
]
NUM_PS_FIELDS = len(PLAYER_STATE_FIELDS)

MAX_STATS = 16
MAX_PERSISTANT = 16
MAX_HOLDABLE = 16
MAX_POWERUPS = 16


def read_delta_playerstate(bs):
    """Reads one svc_snapshot's playerstate delta, returning raw events."""
    events = []

    lc = bs.read_byte()
    events.append(("byte", lc))
    if lc > NUM_PS_FIELDS or lc < 0:
        raise ValueError(f"invalid playerState field count: {lc}")

    for i in range(lc):
        fbits = PLAYER_STATE_FIELDS[i][1]
        changed = bs.read_bits(1)
        events.append(("bit", changed))
        if changed:
            if fbits == 0:
                is_int = bs.read_bits(1)
                events.append(("bit", is_int))
                if is_int == 0:
                    trunc = bs.read_bits(FLOAT_INT_BITS)
                    events.append(("bits", FLOAT_INT_BITS, trunc))
                else:
                    full = bs.read_bits(32)
                    events.append(("bits", 32, full))
            else:
                val = bs.read_bits(fbits)
                events.append(("bits", fbits, val))

    any_arrays = bs.read_bits(1)
    events.append(("bit", any_arrays))
    if any_arrays:
        for max_count, tag in [(MAX_STATS, "stats"), (MAX_PERSISTANT, "persistant"),
                                (MAX_HOLDABLE, "holdable"), (MAX_POWERUPS, "powerups")]:
            has_it = bs.read_bits(1)
            events.append(("bit", has_it))
            if has_it:
                mask = bs.read_short()
                events.append(("short", mask))
                for i in range(max_count):
                    if mask & (1 << i):
                        if tag == "powerups":
                            v = bs.read_long()
                            events.append(("long", v))
                        else:
                            v = bs.read_short()
                            events.append(("short", v))

    any_ammo = bs.read_bits(1)
    events.append(("bit", any_ammo))
    if any_ammo:
        for j in range(4):
            has_it = bs.read_bits(1)
            events.append(("bit", has_it))
            if has_it:
                mask = bs.read_short()
                events.append(("short", mask))
                for i in range(16):
                    if mask & (1 << i):
                        v = bs.read_short()
                        events.append(("short", v))

    for j in range(4):
        has_it = bs.read_bits(1)
        events.append(("bit", has_it))
        if has_it:
            mask = bs.read_short()
            events.append(("short", mask))
            for i in range(16):
                if mask & (1 << i):
                    v = bs.read_short()
                    events.append(("short", v))

    return events


def write_delta_playerstate(bs, events):
    idx = 0

    def next_ev():
        nonlocal idx
        e = events[idx]
        idx += 1
        return e

    tag, lc = next_ev()
    bs.write_byte(lc)

    for i in range(lc):
        fbits = PLAYER_STATE_FIELDS[i][1]
        tag, changed = next_ev()
        bs.write_bits(changed, 1)
        if changed:
            if fbits == 0:
                tag, is_int = next_ev()
                bs.write_bits(is_int, 1)
                if is_int == 0:
                    tag, nbits, trunc = next_ev()
                    bs.write_bits(trunc, FLOAT_INT_BITS)
                else:
                    tag, nbits, full = next_ev()
                    bs.write_bits(full, 32)
            else:
                tag, nbits, val = next_ev()
                bs.write_bits(val, fbits)

    tag, any_arrays = next_ev()
    bs.write_bits(any_arrays, 1)
    if any_arrays:
        for max_count, tagname in [(MAX_STATS, "stats"), (MAX_PERSISTANT, "persistant"),
                                    (MAX_HOLDABLE, "holdable"), (MAX_POWERUPS, "powerups")]:
            tag, has_it = next_ev()
            bs.write_bits(has_it, 1)
            if has_it:
                tag, mask = next_ev()
                bs.write_short(mask)
                for i in range(max_count):
                    if mask & (1 << i):
                        tag, v = next_ev()
                        if tagname == "powerups":
                            bs.write_long(v)
                        else:
                            bs.write_short(v)

    tag, any_ammo = next_ev()
    bs.write_bits(any_ammo, 1)
    if any_ammo:
        for j in range(4):
            tag, has_it = next_ev()
            bs.write_bits(has_it, 1)
            if has_it:
                tag, mask = next_ev()
                bs.write_short(mask)
                for i in range(16):
                    if mask & (1 << i):
                        tag, v = next_ev()
                        bs.write_short(v)

    for j in range(4):
        tag, has_it = next_ev()
        bs.write_bits(has_it, 1)
        if has_it:
            tag, mask = next_ev()
            bs.write_short(mask)
            for i in range(16):
                if mask & (1 << i):
                    tag, v = next_ev()
                    bs.write_short(v)
