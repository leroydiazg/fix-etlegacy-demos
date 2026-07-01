"""
Port of the MSG_ReadBits/MSG_WriteBits layer from msg.c, built on top of et_huffman.py
"""
from et_huffman import Huff, huff_init_single, huff_addref, huff_offset_receive, huff_offset_transmit, BitIO
from msg_hdata import MSG_HDATA

GENTITYNUM_BITS = 10
MAX_GENTITIES = 1 << GENTITYNUM_BITS
ANIM_BITS = 10
FLOAT_INT_BITS = 13
FLOAT_INT_BIAS = 1 << (FLOAT_INT_BITS - 1)


def new_msg_huff():
    """Creates a fresh Huffman tree seeded exactly like MSG_initHuffman()."""
    huff = Huff()
    huff_init_single(huff)
    for i in range(256):
        for _ in range(MSG_HDATA[i]):
            huff_addref(huff, i)
    return huff


class BitStream:
    """
    Wraps BitIO + a Huffman tree, replicating MSG_ReadBits/MSG_WriteBits
    (non-oob mode, the one used for network/demo messages).
    """
    def __init__(self, data=b'', huff=None):
        self.bio = BitIO(data)
        self.huff = huff if huff is not None else new_msg_huff()
        self.maxbits = len(data) * 8  # updated if more space is needed

    def _ensure_capacity(self, extra_bits):
        needed_bytes = ((self.bio.bit + extra_bits) >> 3) + 2
        while len(self.bio.data) < needed_bytes:
            self.bio.data.append(0)
        self.maxbits = len(self.bio.data) * 8

    def read_bits(self, bits):
        signed = bits < 0
        if signed:
            bits = -bits

        value = 0
        nbits = 0
        if bits & 7:
            nbits = bits & 7
            for i in range(nbits):
                value |= (self.bio.get_bit() << i)
            bits -= nbits

        if bits:
            for i in range(0, bits, 8):
                get = huff_offset_receive(self.huff, self.huff.tree, self.bio, len(self.bio.data) * 8)
                value = value | (get << (i + nbits))

        total_bits = nbits + bits
        if signed and 0 < total_bits < 32:
            if value & (1 << (total_bits - 1)):
                value |= -1 ^ ((1 << total_bits) - 1)
        return value

    def write_bits(self, value, bits):
        signed = bits < 0
        if signed:
            bits = -bits

        value &= (0xffffffff >> (32 - bits))

        nbits = 0
        if bits & 7:
            nbits = bits & 7
            self._ensure_capacity(nbits)
            for i in range(nbits):
                self.bio.put_bit(value & 1)
                value >>= 1
            bits -= nbits

        if bits:
            for i in range(0, bits, 8):
                self._ensure_capacity(8)
                byte_val = value & 0xff
                huff_offset_transmit(self.huff, byte_val, self.bio, len(self.bio.data) * 8)
                value >>= 8

    # --- high-level helpers, matching MSG_Read*/MSG_Write* ---
    def read_byte(self):
        return self.read_bits(8) & 0xff

    def read_short(self):
        v = self.read_bits(16) & 0xffff
        if v >= 0x8000:
            v -= 0x10000
        return v

    def read_long(self):
        v = self.read_bits(32) & 0xffffffff
        if v >= 0x80000000:
            v -= 0x100000000
        return v

    def write_byte(self, v):
        self.write_bits(v & 0xff, 8)

    def write_short(self, v):
        self.write_bits(v & 0xffff, 16)

    def write_long(self, v):
        self.write_bits(v & 0xffffffff, 32)

    def read_string_bytes(self, max_len=8192):
        """Reads a null-terminated string byte by byte (like MSG_ReadString/ReadBigString)."""
        out = bytearray()
        while True:
            c = self.read_byte()
            if c == 0:
                break
            if len(out) >= max_len - 1:
                break
            out.append(c)
        return bytes(out)

    def write_string_bytes(self, data: bytes):
        for b in data:
            self.write_byte(b)
        self.write_byte(0)

    def bytes_consumed_rounded(self):
        return (self.bio.bit >> 3) + 1
