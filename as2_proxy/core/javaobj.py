"""
Minimal Java object serialization writer and reader for the Mendelson AS2
client-server protocol.

We only implement the subset of the Java serialization spec needed to talk to
this specific server.  The spec lives at:
  https://docs.oracle.com/javase/8/docs/platform/serialization/spec/protocol.html

Wire format per message:
  [4-byte BE uint: compressed length] [zlib-deflated Java serial stream]

The Java serial stream always starts with magic 0xACED 0x0005.

Notation used in comments:
  TC_*  = type-code constants from the spec
  sUID  = serialVersionUID
"""

import io
import struct
import zlib

# ---------------------------------------------------------------------------
# Constants from the Java serialization spec
# ---------------------------------------------------------------------------
STREAM_MAGIC   = b'\xac\xed'
STREAM_VERSION = b'\x00\x05'

TC_NULL        = b'\x70'
TC_REFERENCE   = b'\x71'  # back-reference
TC_CLASSDESC   = b'\x72'
TC_OBJECT      = b'\x73'
TC_STRING      = b'\x74'
TC_ARRAY       = b'\x75'
TC_CLASS       = b'\x76'
TC_ENDBLOCKDATA= b'\x78'
TC_RESET       = b'\x79'
TC_BLOCKDATA   = b'\x77'
TC_EXCEPTION   = b'\x7b'
TC_LONGSTRING  = b'\x7c'
TC_PROXYCLASSDESC = b'\x7d'
TC_ENUM        = b'\x7e'

SC_SERIALIZABLE   = 0x02
SC_WRITE_METHOD   = 0x01  # has writeObject

BASE_WIRE_HANDLE  = 0x7e0000  # first handle assigned after stream header


# ---------------------------------------------------------------------------
# Writer
# ---------------------------------------------------------------------------

class JavaWriter:
    """Builds a Java serialization stream incrementally."""

    def __init__(self):
        self._buf = io.BytesIO()
        self._handle = BASE_WIRE_HANDLE
        self._written_classes: dict[str, int] = {}  # classname -> handle
        self._write_magic()

    def _write_magic(self):
        self._buf.write(STREAM_MAGIC + STREAM_VERSION)

    def _next_handle(self) -> int:
        h = self._handle
        self._handle += 1
        return h

    # -- primitives --

    def u8(self, v: int):   self._buf.write(struct.pack("B", v))
    def u16(self, v: int):  self._buf.write(struct.pack(">H", v))
    def u32(self, v: int):  self._buf.write(struct.pack(">I", v))
    def i32(self, v: int):  self._buf.write(struct.pack(">i", v))
    def i64(self, v: int):  self._buf.write(struct.pack(">q", v))
    def bool_(self, v: bool): self._buf.write(b'\x01' if v else b'\x00')

    def utf(self, s: str):
        """TC_STRING + 2-byte length + UTF-8 bytes, assigned a handle."""
        b = s.encode("utf-8")
        self._buf.write(TC_STRING)
        self.u16(len(b))
        self._buf.write(b)
        self._next_handle()

    def _utf_raw(self, s: str):
        """2-byte-length-prefixed UTF-8, no TC_STRING, no handle (used inside class descriptors)."""
        b = s.encode("utf-8")
        self.u16(len(b))
        self._buf.write(b)

    def null(self):
        self._buf.write(TC_NULL)

    # -- class descriptor --

    def class_desc(self, classname: str, suid: int, sc_flags: int, fields: list):
        """
        Write a TC_CLASSDESC block.
        fields: list of (type_code_char, field_name, class_name_for_objects)
          type_code_char: 'B','C','D','F','I','J','S','Z' for primitives,
                          'L' for Object, '[' for array
          class_name_for_objects: the classname string written after the field name
                                  for L/[ types (e.g. "Ljava/lang/String;")
        """
        if classname in self._written_classes:
            # emit a reference
            self._buf.write(TC_REFERENCE)
            self.u32(self._written_classes[classname])
            return

        self._buf.write(TC_CLASSDESC)
        self._utf_raw(classname)
        self.i64(suid)
        handle = self._next_handle()
        self._written_classes[classname] = handle

        self._buf.write(bytes([sc_flags]))
        self.u16(len(fields))
        for field in fields:
            type_code = field[0]
            fname = field[1]
            self._buf.write(type_code.encode())
            self._utf_raw(fname)
            if type_code in ('L', '['):
                # classname descriptor is a TC_STRING
                self.utf(field[2])

        self._buf.write(TC_ENDBLOCKDATA)

    def super_desc(self, classname: str, suid: int, sc_flags: int, fields: list):
        """Same as class_desc but used for the superclass chain."""
        self.class_desc(classname, suid, sc_flags, fields)

    def no_super(self):
        self._buf.write(TC_NULL)

    # -- object wrapper --

    def begin_object(self) -> int:
        self._buf.write(TC_OBJECT)
        h = self._next_handle()  # handle for the object itself is assigned after classDesc
        return h

    def getvalue(self) -> bytes:
        return self._buf.getvalue()


# ---------------------------------------------------------------------------
# Reader
# ---------------------------------------------------------------------------

class JavaReader:
    """
    Reads a Java serialization stream and returns Python objects.
    Only the types actually returned by the Mendelson server are handled.
    """

    def __init__(self, data: bytes):
        self._buf = io.BytesIO(data)
        self._handles: list = []
        magic = self._buf.read(2)
        version = self._buf.read(2)
        if magic != STREAM_MAGIC:
            raise ValueError(f"Bad stream magic: {magic.hex()}")

    def read_object(self):
        tc = self._buf.read(1)
        if tc == TC_NULL:
            return None
        if tc == TC_STRING:
            return self._read_string_body()
        if tc == TC_OBJECT:
            return self._read_ordinary_object()
        if tc == TC_ARRAY:
            return self._read_array()
        if tc == TC_REFERENCE:
            return self._read_reference()
        if tc == TC_ENUM:
            return self._read_enum()
        if tc == TC_CLASSDESC:
            # encountered inline — skip
            return self._read_class_desc_body()
        raise ValueError(f"Unhandled TC byte: {tc.hex()} at offset {self._buf.tell()}")

    # -- internal --

    def _read_string_body(self) -> str:
        length = struct.unpack(">H", self._buf.read(2))[0]
        s = self._buf.read(length).decode("utf-8", errors="replace")
        self._handles.append(s)
        return s

    def _read_reference(self):
        handle = struct.unpack(">I", self._buf.read(4))[0]
        idx = handle - BASE_WIRE_HANDLE
        return self._handles[idx]

    def _read_class_desc_body(self) -> dict:
        """Read a class descriptor and return a meta dict."""
        length = struct.unpack(">H", self._buf.read(2))[0]
        classname = self._buf.read(length).decode("utf-8")
        suid = struct.unpack(">q", self._buf.read(8))[0]
        desc = {"classname": classname, "suid": suid}
        self._handles.append(desc)

        sc_flags = struct.unpack("B", self._buf.read(1))[0]
        field_count = struct.unpack(">H", self._buf.read(2))[0]
        fields = []
        for _ in range(field_count):
            type_code = self._buf.read(1).decode()
            fname_len = struct.unpack(">H", self._buf.read(2))[0]
            fname = self._buf.read(fname_len).decode("utf-8")
            class_name = None
            if type_code in ('L', '['):
                class_name = self.read_object()  # TC_STRING for the class name
            fields.append({"type": type_code, "name": fname, "class": class_name})
        desc["fields"] = fields
        desc["sc_flags"] = sc_flags
        self._read_class_annotations()
        # super class desc
        tc = self._buf.read(1)
        if tc == TC_NULL:
            desc["super"] = None
        elif tc == TC_CLASSDESC:
            desc["super"] = self._read_class_desc_body()
        elif tc == TC_REFERENCE:
            desc["super"] = self._read_reference()
        else:
            desc["super"] = None  # unknown
        return desc

    def _read_class_annotations(self):
        while True:
            tc = self._buf.read(1)
            if tc == TC_ENDBLOCKDATA:
                return
            # skip other annotation content (blockdata etc.)
            if tc == TC_BLOCKDATA:
                n = struct.unpack("B", self._buf.read(1))[0]
                self._buf.read(n)
            elif tc == TC_STRING:
                self._read_string_body()
            elif tc == TC_OBJECT:
                self._read_ordinary_object()
            elif tc == TC_NULL:
                pass
            else:
                # give up parsing annotations safely
                return

    def _read_ordinary_object(self) -> dict:
        tc = self._buf.read(1)
        if tc == TC_CLASSDESC:
            desc = self._read_class_desc_body()
        elif tc == TC_REFERENCE:
            desc = self._read_reference()
        elif tc == TC_NULL:
            return None
        else:
            raise ValueError(f"Expected class desc in object, got {tc.hex()}")

        obj = {"_class": desc["classname"], "_desc": desc}
        self._handles.append(obj)
        self._read_class_data(desc, obj)
        return obj

    def _read_class_data(self, desc: dict, obj: dict):
        """Read fields for this class and all its superclasses."""
        # depth-first: super first
        if desc.get("super"):
            self._read_class_data(desc["super"], obj)
        for field in desc.get("fields", []):
            obj[field["name"]] = self._read_field_value(field["type"])

    def _read_field_value(self, type_code: str):
        if type_code == 'B': return struct.unpack("b", self._buf.read(1))[0]
        if type_code == 'C': return struct.unpack(">H", self._buf.read(2))[0]
        if type_code == 'D': return struct.unpack(">d", self._buf.read(8))[0]
        if type_code == 'F': return struct.unpack(">f", self._buf.read(4))[0]
        if type_code == 'I': return struct.unpack(">i", self._buf.read(4))[0]
        if type_code == 'J': return struct.unpack(">q", self._buf.read(8))[0]
        if type_code == 'S': return struct.unpack(">h", self._buf.read(2))[0]
        if type_code == 'Z': return self._buf.read(1) != b'\x00'
        if type_code in ('L', '['):
            return self.read_object()
        raise ValueError(f"Unknown field type: {type_code!r}")

    def _read_array(self):
        tc = self._buf.read(1)
        if tc == TC_CLASSDESC:
            desc = self._read_class_desc_body()
        elif tc == TC_REFERENCE:
            desc = self._read_reference()
        else:
            raise ValueError(f"Array: expected class desc, got {tc.hex()}")
        size = struct.unpack(">i", self._buf.read(4))[0]
        arr = []
        self._handles.append(arr)
        # component type from class name e.g. "[Ljava/lang/String;"
        classname = desc.get("classname", "") if isinstance(desc, dict) else str(desc)
        comp_type = 'L'  # default
        if classname.startswith("["):
            comp_type = classname[1]
        for _ in range(size):
            arr.append(self._read_field_value(comp_type))
        return arr

    def _read_enum(self):
        # class desc
        tc = self._buf.read(1)
        if tc == TC_CLASSDESC:
            desc = self._read_class_desc_body()
        elif tc == TC_REFERENCE:
            desc = self._read_reference()
        placeholder = {"_enum": True}
        self._handles.append(placeholder)
        const_name = self.read_object()
        placeholder["value"] = const_name
        return placeholder


# ---------------------------------------------------------------------------
# Frame codec (the transport layer wrapping each message)
# ---------------------------------------------------------------------------

def encode_frame(java_stream: bytes) -> bytes:
    compressed = zlib.compress(java_stream)
    return struct.pack(">I", len(compressed)) + compressed


def decode_frame(data: bytes) -> bytes:
    return zlib.decompress(data)


def read_frame(sock) -> bytes:
    hdr = _recv_exactly(sock, 4)
    (n,) = struct.unpack(">I", hdr)
    return decode_frame(_recv_exactly(sock, n))


def send_frame(sock, java_stream: bytes):
    sock.sendall(encode_frame(java_stream))


def _recv_exactly(sock, n: int) -> bytes:
    buf = bytearray()
    while len(buf) < n:
        chunk = sock.recv(n - len(buf))
        if not chunk:
            raise ConnectionError("Connection closed unexpectedly")
        buf.extend(chunk)
    return bytes(buf)
