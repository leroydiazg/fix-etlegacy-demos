"""
Port of entityStateFields[] and MSG_ReadDeltaEntity/MSG_WriteDeltaEntity from msg.c.
We only need to preserve the content bit-for-bit (not interpret it semantically),
so we capture the integer values read and write them back identically.
"""
from et_msg import GENTITYNUM_BITS, FLOAT_INT_BITS, FLOAT_INT_BIAS

# (name, bits) -- 0 bits means "special float encoding"
ENTITY_STATE_FIELDS = [
    ("eType", 8), ("eFlags", 24), ("pos.trType", 8), ("pos.trTime", 32),
    ("pos.trDuration", 32), ("pos.trBase0", 0), ("pos.trBase1", 0), ("pos.trBase2", 0),
    ("pos.trDelta0", 0), ("pos.trDelta1", 0), ("pos.trDelta2", 0),
    ("apos.trType", 8), ("apos.trTime", 32), ("apos.trDuration", 32),
    ("apos.trBase0", 0), ("apos.trBase1", 0), ("apos.trBase2", 0),
    ("apos.trDelta0", 0), ("apos.trDelta1", 0), ("apos.trDelta2", 0),
    ("time", 32), ("time2", 32),
    ("origin0", 0), ("origin1", 0), ("origin2", 0),
    ("origin20", 0), ("origin21", 0), ("origin22", 0),
    ("angles0", 0), ("angles1", 0), ("angles2", 0),
    ("angles20", 0), ("angles21", 0), ("angles22", 0),
    ("otherEntityNum", GENTITYNUM_BITS), ("otherEntityNum2", GENTITYNUM_BITS),
    ("groundEntityNum", GENTITYNUM_BITS),
    ("loopSound", 8), ("constantLight", 32), ("dl_intensity", 32),
    ("modelindex", 9), ("modelindex2", 9), ("frame", 16), ("clientNum", 8),
    ("solid", 24), ("event", 10), ("eventParm", 8), ("eventSequence", 8),
    ("events0", 8), ("events1", 8), ("events2", 8), ("events3", 8),
    ("eventParms0", 8), ("eventParms1", 8), ("eventParms2", 8), ("eventParms3", 8),
    ("powerups", 16), ("weapon", 8), ("legsAnim", 10), ("torsoAnim", 10),
    ("density", 10), ("dmgFlags", 32), ("onFireStart", 32), ("onFireEnd", 32),
    ("nextWeapon", 8), ("teamNum", 8),
    ("effect1Time", 32), ("effect2Time", 32), ("effect3Time", 32),
    ("animMovetype", 4), ("aiState", 2),
]
NUM_ENTITY_FIELDS = len(ENTITY_STATE_FIELDS)


def read_delta_entity(bs):
    """
    Reads an svc_baseline (the entity-number bit must already have been read
    before calling this). Returns a list of events describing exactly what was
    read, bit by bit, so it can be re-written identically with write_delta_entity.
    """
    events = [("bit", bs.read_bits(1))]  # "remove"
    if events[-1][1] == 1:
        return events

    events.append(("bit", bs.read_bits(1)))  # "no delta"
    if events[-1][1] == 0:
        return events

    lc = bs.read_byte()
    events.append(("byte", lc))

    if lc > NUM_ENTITY_FIELDS or lc < 0:
        raise ValueError(f"invalid entityState field count: {lc}")

    for i in range(lc):
        name, fbits = ENTITY_STATE_FIELDS[i]
        changed = bs.read_bits(1)
        events.append(("bit", changed))
        if changed:
            if fbits == 0:
                nonzero = bs.read_bits(1)
                events.append(("bit", nonzero))
                if nonzero:
                    is_int = bs.read_bits(1)
                    events.append(("bit", is_int))
                    if is_int == 0:
                        trunc = bs.read_bits(FLOAT_INT_BITS)
                        events.append(("bits", FLOAT_INT_BITS, trunc))
                    else:
                        full = bs.read_bits(32)
                        events.append(("bits", 32, full))
            else:
                nonzero = bs.read_bits(1)
                events.append(("bit", nonzero))
                if nonzero:
                    val = bs.read_bits(fbits)
                    events.append(("bits", fbits, val))
    return events


def write_delta_entity(bs, events):
    idx = 0

    def next_ev():
        nonlocal idx
        e = events[idx]
        idx += 1
        return e

    tag, val = next_ev()
    bs.write_bits(val, 1)
    if val == 1:
        return

    tag, val = next_ev()
    bs.write_bits(val, 1)
    if val == 0:
        return

    tag, lc = next_ev()
    bs.write_byte(lc)

    for i in range(lc):
        name, fbits = ENTITY_STATE_FIELDS[i]
        tag, changed = next_ev()
        bs.write_bits(changed, 1)
        if changed:
            if fbits == 0:
                tag, nonzero = next_ev()
                bs.write_bits(nonzero, 1)
                if nonzero:
                    tag, is_int = next_ev()
                    bs.write_bits(is_int, 1)
                    if is_int == 0:
                        tag, nbits, trunc = next_ev()
                        bs.write_bits(trunc, FLOAT_INT_BITS)
                    else:
                        tag, nbits, full = next_ev()
                        bs.write_bits(full, 32)
            else:
                tag, nonzero = next_ev()
                bs.write_bits(nonzero, 1)
                if nonzero:
                    tag, nbits, val2 = next_ev()
                    bs.write_bits(val2, fbits)
