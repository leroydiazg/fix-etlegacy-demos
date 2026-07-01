"""
Faithful Python port of ET:Legacy's adaptive Huffman algorithm (huffman.c).
Translated line-by-line to guarantee bit-for-bit compatibility.
"""

HMAX = 256
NYT = 256           # Not Yet Transmitted
INTERNAL_NODE = 257


class Ref:
    """Equivalent to node_t** (a mutable box holding a pointer to a node)."""
    __slots__ = ('node',)
    def __init__(self, node=None):
        self.node = node


class Node:
    __slots__ = ('left', 'right', 'parent', 'next', 'prev', 'head', 'weight', 'symbol')
    def __init__(self):
        self.left = self.right = self.parent = None
        self.next = self.prev = None
        self.head = None  # Ref
        self.weight = 0
        self.symbol = 0


class Huff:
    """Equivalent to huff_t (a single tree: compressor or decompressor)."""
    def __init__(self):
        self.tree = None
        self.lhead = None
        self.ltail = None
        self.loc = [None] * (HMAX + 1)
        self.freelist = []  # stack of reusable Refs

    def get_ppnode(self):
        if self.freelist:
            return self.freelist.pop()
        return Ref()

    def free_ppnode(self, ref):
        ref.node = None
        self.freelist.append(ref)


def swap(huff, node1, node2):
    par1 = node1.parent
    par2 = node2.parent

    if par1:
        if par1.left is node1:
            par1.left = node2
        else:
            par1.right = node2
    else:
        huff.tree = node2

    if par2:
        if par2.left is node2:
            par2.left = node1
        else:
            par2.right = node1
    else:
        huff.tree = node1

    node1.parent = par2
    node2.parent = par1


def swaplist(node1, node2):
    par1 = node1.next
    node1.next = node2.next
    node2.next = par1

    par1 = node1.prev
    node1.prev = node2.prev
    node2.prev = par1

    if node1.next is node1:
        node1.next = node2
    if node2.next is node2:
        node2.next = node1
    if node1.next:
        node1.next.prev = node1
    if node2.next:
        node2.next.prev = node2
    if node1.prev:
        node1.prev.next = node1
    if node2.prev:
        node2.prev.next = node2


def increment(huff, node):
    if node is None:
        return

    if node.next is not None and node.next.weight == node.weight:
        lnode = node.head.node
        if lnode is not node.parent:
            swap(huff, lnode, node)
        swaplist(lnode, node)

    if node.prev is not None and node.prev.weight == node.weight:
        node.head.node = node.prev
    else:
        node.head.node = None
        huff.free_ppnode(node.head)

    node.weight += 1

    if node.next is not None and node.next.weight == node.weight:
        node.head = node.next.head
    else:
        node.head = huff.get_ppnode()
        node.head.node = node

    if node.parent is not None:
        increment(huff, node.parent)
        if node.prev is node.parent:
            swaplist(node, node.parent)
            if node.head.node is node:
                node.head.node = node.parent


def huff_addref(huff, ch):
    if huff.loc[ch] is None:
        tnode = Node()
        tnode2 = Node()

        tnode2.symbol = INTERNAL_NODE
        tnode2.weight = 1
        tnode2.next = huff.lhead.next
        if huff.lhead.next is not None:
            huff.lhead.next.prev = tnode2
            if huff.lhead.next.weight == 1:
                tnode2.head = huff.lhead.next.head
            else:
                tnode2.head = huff.get_ppnode()
                tnode2.head.node = tnode2
        else:
            tnode2.head = huff.get_ppnode()
            tnode2.head.node = tnode2
        huff.lhead.next = tnode2
        tnode2.prev = huff.lhead

        tnode.symbol = ch
        tnode.weight = 1
        tnode.next = huff.lhead.next
        if huff.lhead.next is not None:
            huff.lhead.next.prev = tnode
            if huff.lhead.next.weight == 1:
                tnode.head = huff.lhead.next.head
            else:
                tnode.head = huff.get_ppnode()
                tnode.head.node = tnode2
        else:
            tnode.head = huff.get_ppnode()
            tnode.head.node = tnode
        huff.lhead.next = tnode
        tnode.prev = huff.lhead
        tnode.left = tnode.right = None

        if huff.lhead.parent is not None:
            if huff.lhead.parent.left is huff.lhead:
                huff.lhead.parent.left = tnode2
            else:
                huff.lhead.parent.right = tnode2
        else:
            huff.tree = tnode2

        tnode2.right = tnode
        tnode2.left = huff.lhead

        tnode2.parent = huff.lhead.parent
        huff.lhead.parent = tnode.parent = tnode2

        huff.loc[ch] = tnode

        increment(huff, tnode2.parent)
    else:
        increment(huff, huff.loc[ch])


def huff_init_single(huff):
    """Equivalent to half of Huff_Init (for a single compressor or decompressor tree)."""
    node = Node()
    huff.tree = huff.lhead = huff.ltail = node
    huff.loc[NYT] = node
    node.symbol = NYT
    node.weight = 0
    node.next = node.prev = None
    node.parent = node.left = node.right = None


class BitIO:
    """LSB-first bit reader/writer, matching Huff_getBit/putBit."""
    def __init__(self, data=b'', bitpos=0):
        self.data = bytearray(data)
        self.bit = bitpos

    def get_bit(self):
        x = self.bit >> 3
        y = self.bit & 7
        t = (self.data[x] >> y) & 0x1
        self.bit += 1
        return t

    def put_bit(self, bit):
        x = self.bit >> 3
        y = self.bit & 7
        while len(self.data) <= x:
            self.data.append(0)
        if y == 0:
            self.data[x] = 0
        self.data[x] |= (bit << y)
        self.bit += 1


def huff_offset_receive(huff, node, bio, maxoffset):
    """Returns the decoded symbol by walking the tree bit by bit."""
    while node is not None and node.symbol == INTERNAL_NODE:
        if bio.bit >= maxoffset:
            return 0
        if bio.get_bit():
            node = node.right
        else:
            node = node.left
    if node is None:
        return 0
    return node.symbol


def _send(node, child, bio, maxoffset):
    if node.parent is not None:
        _send(node.parent, node, bio, maxoffset)
    if child is not None:
        if bio.bit >= maxoffset:
            bio.bit = maxoffset + 1
            return
        if node.right is child:
            bio.put_bit(1)
        else:
            bio.put_bit(0)


def huff_offset_transmit(huff, ch, bio, maxoffset):
    _send(huff.loc[ch], None, bio, maxoffset)
