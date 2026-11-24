"""Just enough of the JVM class-file format (JVMS chapter 4) to be ground truth for the realm:
names, flags, fields, methods, and each method's invoke and field instructions with their lines.

Kept apart from verify.py so the truth is read by code that shares nothing with the appliance.
"""
import struct

ACC_INTERFACE, ACC_ANNOTATION, ACC_ENUM, ACC_SYNTHETIC = 0x0200, 0x2000, 0x4000, 0x1000

# Operand bytes after each opcode, for every fixed-length instruction (JVMS 6.5).
_LEN = {}
for op in range(0, 256):
    _LEN[op] = 0
for op in (0x10, 0x12, 0x15, 0x16, 0x17, 0x18, 0x19, 0x36, 0x37, 0x38, 0x39, 0x3a, 0xa9, 0xbc):
    _LEN[op] = 1
for op in (0x11, 0x13, 0x14, 0x84, 0xb2, 0xb3, 0xb4, 0xb5, 0xb6, 0xb7, 0xb8, 0xbb, 0xbd, 0xc0, 0xc1,
           0xc6, 0xc7, 0xa7, 0xa8) + tuple(range(0x99, 0xa7)):
    _LEN[op] = 2
for op in (0xc5,):
    _LEN[op] = 3
for op in (0xb9, 0xba, 0xc8, 0xc9):
    _LEN[op] = 4

FIELD_OPS = {0xb2: "READ", 0xb4: "READ", 0xb3: "WRITE", 0xb5: "WRITE"}
INVOKE_OPS = (0xb6, 0xb7, 0xb8, 0xb9)


def binary(internal):
    return internal.replace("/", ".")


class ClassFile:
    def __init__(self, data):
        self.d, self.p = data, 8
        n = self._u2()
        self.cp = [None] * n
        i = 1
        while i < n:
            tag = self._u1()
            if tag == 1:
                ln = self._u2(); self.cp[i] = ("utf8", self.d[self.p:self.p + ln].decode("utf-8", "replace")); self.p += ln
            elif tag in (3, 4):
                self.p += 4
            elif tag in (5, 6):
                self.p += 8; i += 1
            elif tag in (7, 8, 16, 19, 20):
                self.cp[i] = ("ref1", self._u2())
            elif tag in (9, 10, 11, 12, 17, 18):
                self.cp[i] = ("ref2", self._u2(), self._u2())
            elif tag == 15:
                self.p += 1; self.cp[i] = ("mh", self._u2())
            else:
                raise ValueError(f"constant tag {tag}")
            i += 1
        self.access = self._u2()
        self.name = binary(self._class(self._u2()))
        sup = self._u2()
        self.superclass = binary(self._class(sup)) if sup else None
        self.interfaces = [binary(self._class(self._u2())) for _ in range(self._u2())]
        self.fields = [self._member(False) for _ in range(self._u2())]
        self.methods = [self._member(True) for _ in range(self._u2())]

    def _u1(self):
        v = self.d[self.p]; self.p += 1; return v

    def _u2(self):
        v = struct.unpack_from(">H", self.d, self.p)[0]; self.p += 2; return v

    def _u4(self):
        v = struct.unpack_from(">I", self.d, self.p)[0]; self.p += 4; return v

    def utf(self, i):
        return self.cp[i][1]

    def _class(self, i):
        return self.utf(self.cp[i][1])

    def ref(self, i):
        """(owner, name, descriptor) of a Fieldref / Methodref / InterfaceMethodref."""
        _, ci, nti = self.cp[i]
        _, ni, di = self.cp[nti]
        return binary(self._class(ci)), self.utf(ni), self.utf(di)

    def _member(self, method):
        flags, name, desc = self._u2(), self.utf(self._u2()), self.utf(self._u2())
        m = {"flags": flags, "name": name, "desc": desc, "ops": [], "lines": []}
        for _ in range(self._u2()):
            an, ln = self.utf(self._u2()), self._u4()
            end = self.p + ln
            if method and an == "Code":
                self._code(m)
            self.p = end
        return m

    def _code(self, m):
        self.p += 4
        ln = self._u4(); start = self.p; code = self.d[start:start + ln]; self.p += ln
        handlers = self._u2()
        self.p += 8 * handlers
        lines = []
        for _ in range(self._u2()):
            an, aln = self.utf(self._u2()), self._u4()
            end = self.p + aln
            if an == "LineNumberTable":
                lines += [(self._u2(), self._u2()) for _ in range(self._u2())]
            self.p = end
        lines.sort()
        m["lines"] = sorted({l for _, l in lines})

        def line_at(pc):
            ln_ = None
            for spc, l in lines:
                if spc <= pc: ln_ = l
                else: break
            return ln_

        pc = 0
        while pc < len(code):
            op = code[pc]
            if op in FIELD_OPS or op in INVOKE_OPS:
                idx = struct.unpack_from(">H", code, pc + 1)[0]
                kind = FIELD_OPS.get(op, "CALL")
                m["ops"].append((kind,) + self.ref(idx) + (line_at(pc),))
            if op == 0xaa:  # tableswitch
                q = (pc + 4) & ~3
                lo, hi = struct.unpack_from(">ii", code, q + 4)
                pc = q + 12 + 4 * (hi - lo + 1)
            elif op == 0xab:  # lookupswitch
                q = (pc + 4) & ~3
                n = struct.unpack_from(">i", code, q + 4)[0]
                pc = q + 8 + 8 * n
            elif op == 0xc4:  # wide
                pc += 6 if code[pc + 1] == 0x84 else 4
            else:
                pc += 1 + _LEN[op]
