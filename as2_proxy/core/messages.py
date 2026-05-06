"""
Build Java-serialized request objects for the Mendelson AS2 client-server protocol.

Field ordering: Java serializes fields in alphabetical order by field name.
Back-references: once Ljava/lang/String; is written as a TC_STRING, subsequent
  occurrences use TC_REFERENCE (0x71) + 4-byte handle.

All class UIDs confirmed from javap and from capturing real client traffic:
  All Mendelson classes: sUID = 1
  [C (char[]): sUID = 0xb02666b0e25d84ac  (JVM-computed for primitive array)

Handle allocation (BASE = 0x7e0000):
  Each TC_CLASSDESC, TC_OBJECT, TC_ARRAY, TC_STRING written gets a handle.
  We track this carefully to emit correct back-references.
"""

import io
import os
import struct
import socket

# Confirmed from real Java client capture
_CHAR_ARRAY_SUID = 0xb02666b0e25d84ac  # signed: -5665338936636769108

# All Mendelson classes use sUID=1
_SUID = 1
_BASE_HANDLE = 0x7e0000

# Fully qualified class names
_CSM  = "de.mendelson.util.clientserver.messages.ClientServerMessage"
_LRQ  = "de.mendelson.util.clientserver.messages.LoginRequest"
_QRQR = "de.mendelson.util.clientserver.messages.QuitRequest"
_PLRQ = "de.mendelson.comm.as2.partner.clientserver.PartnerListRequest"
_MORQ = "de.mendelson.comm.as2.message.clientserver.MessageOverviewRequest"
_MLRQ = "de.mendelson.comm.as2.message.clientserver.MessageLogRequest"
_MPRQ = "de.mendelson.comm.as2.message.clientserver.MessagePayloadRequest"
_MOF  = "de.mendelson.comm.as2.message.MessageOverviewFilter"
_STR  = "Ljava/lang/String;"


class _W:
    """Low-level Java serial stream writer with handle tracking."""

    def __init__(self):
        self._buf = io.BytesIO()
        self._handle = _BASE_HANDLE
        self._buf.write(b'\xac\xed\x00\x05')  # magic + version
        self._str_handle: dict[str, int] = {}  # interned class-name strings

    def _alloc(self) -> int:
        h = self._handle
        self._handle += 1
        return h

    # primitives
    def u8(self, v):   self._buf.write(struct.pack("B", v))
    def u16(self, v):  self._buf.write(struct.pack(">H", v))
    def i32(self, v):  self._buf.write(struct.pack(">i", v))
    def i64(self, v):  self._buf.write(struct.pack(">q", v))
    def bool_(self, v): self._buf.write(b'\x01' if v else b'\x00')

    def null(self):    self._buf.write(b'\x70')

    def _raw_utf(self, s: str):
        """2-byte-length-prefixed UTF-8, no TC tag, no handle (inside classdesc)."""
        b = s.encode("utf-8")
        self.u16(len(b))
        self._buf.write(b)

    def new_string(self, s: str) -> int:
        """TC_STRING + 2-byte length + UTF-8 bytes. Returns the handle."""
        b = s.encode("utf-8")
        self._buf.write(b'\x74')
        self.u16(len(b))
        self._buf.write(b)
        return self._alloc()

    def ref(self, handle: int):
        """TC_REFERENCE + 4-byte handle."""
        self._buf.write(b'\x71')
        self._buf.write(struct.pack(">I", handle))

    def class_name_ref(self, class_name: str):
        """
        Write the class-name descriptor for an L/[ field.
        If we've already written this string, emit a back-reference.
        Otherwise write TC_STRING and record the handle.
        """
        if class_name in self._str_handle:
            self.ref(self._str_handle[class_name])
        else:
            h = self.new_string(class_name)
            self._str_handle[class_name] = h

    def classdesc(self, classname: str, suid: int, sc: int, fields: list) -> int:
        """
        Write TC_CLASSDESC block. Returns the handle allocated for it.
        fields: list of (type_char, field_name) or (type_char, field_name, class_desc_str)
        """
        self._buf.write(b'\x72')
        self._raw_utf(classname)
        self._buf.write(struct.pack(">q", suid))
        h = self._alloc()

        self._buf.write(bytes([sc]))
        self.u16(len(fields))
        for f in fields:
            tc, name = f[0], f[1]
            self._buf.write(tc.encode())
            self._raw_utf(name)
            if tc in ('L', '['):
                self.class_name_ref(f[2])

        self._buf.write(b'\x78')  # TC_ENDBLOCKDATA
        return h

    def char_array(self, s: str):
        """Write a Java char[] value."""
        self._buf.write(b'\x75')   # TC_ARRAY
        self.classdesc("[C", _CHAR_ARRAY_SUID, 0x02, [])
        self.null()                # no super
        self._alloc()              # object handle for the array
        self.i32(len(s))
        for ch in s:
            self.u16(ord(ch))

    def begin_object(self) -> int:
        """TC_OBJECT. Returns the handle that will be assigned after class desc."""
        self._buf.write(b'\x73')
        # handle is allocated when classdesc is written
        return self._handle  # preview only

    def getvalue(self) -> bytes:
        return self._buf.getvalue()


# ---------------------------------------------------------------------------
# LoginRequest
# ---------------------------------------------------------------------------
# Confirmed field order (alphabetical): clientType(I), clientId(L), clientOSName(L),
#   password([C), username(L)
# Super ClientServerMessage fields (alphabetical): _syncRequest(Z), referenceId(J), pid(L)
# Data written super-first:
#   _syncRequest, referenceId, pid | clientType, clientId, clientOSName, password, username

def build_login_request(user: str, password: str) -> bytes:
    w = _W()
    w.begin_object()

    # LoginRequest classdesc
    w.classdesc(_LRQ, _SUID, 0x02, [
        ('I', 'clientType'),
        ('L', 'clientId',    _STR),
        ('L', 'clientOSName', _STR),
        ('[', 'password',    '[C'),
        ('L', 'username',    _STR),
    ])

    # ClientServerMessage classdesc (super)
    w.classdesc(_CSM, _SUID, 0x02, [
        ('Z', '_syncRequest'),
        ('J', 'referenceId'),
        ('L', 'pid', _STR),
    ])
    w.null()  # no superclass

    # --- data: super fields first ---
    w.bool_(False)           # _syncRequest
    w.i64(1)                 # referenceId (real client always starts at 1)
    w.new_string(_pid())     # pid

    # --- data: LoginRequest fields ---
    w.i32(0)                 # clientType = 0
    w.null()                 # clientId = null (real client sends null here)
    w.null()                 # clientOSName = null (real client sends null)
    w.char_array(password)   # password char[]
    w.new_string(user)       # username

    return w.getvalue()


# ---------------------------------------------------------------------------
# QuitRequest
# ---------------------------------------------------------------------------
# Fields (alphabetical): user(L)

def build_quit_request(user: str) -> bytes:
    w = _W()
    w.begin_object()

    w.classdesc(_QRQR, _SUID, 0x02, [
        ('L', 'user', _STR),
    ])
    w.classdesc(_CSM, _SUID, 0x02, [
        ('Z', '_syncRequest'),
        ('J', 'referenceId'),
        ('L', 'pid', _STR),
    ])
    w.null()

    w.bool_(False)
    w.i64(2)
    w.new_string(_pid())
    w.new_string(user)

    return w.getvalue()


# ---------------------------------------------------------------------------
# PartnerListRequest
# ---------------------------------------------------------------------------
# Fields (alphabetical): additionalListOptionInt(I), additionalListOptionStr(L),
#   listOption(I), requestedDataCompleteness(I)

def build_partner_list_request(list_option: int = 0) -> bytes:
    w = _W()
    w.begin_object()

    w.classdesc(_PLRQ, _SUID, 0x02, [
        ('I', 'additionalListOptionInt'),
        ('L', 'additionalListOptionStr', _STR),
        ('I', 'listOption'),
        ('I', 'requestedDataCompleteness'),
    ])
    w.classdesc(_CSM, _SUID, 0x02, [
        ('Z', '_syncRequest'),
        ('J', 'referenceId'),
        ('L', 'pid', _STR),
    ])
    w.null()

    w.bool_(False)
    w.i64(3)
    w.new_string(_pid())

    w.i32(0)       # additionalListOptionInt
    w.null()       # additionalListOptionStr
    w.i32(list_option)
    w.i32(0)       # requestedDataCompleteness: FULL

    return w.getvalue()


# ---------------------------------------------------------------------------
# MessageOverviewRequest
# ---------------------------------------------------------------------------
# Fields (alphabetical): filter(L), messageId(L)
# MessageOverviewFilter fields (alphabetical):
#   direction(I), endTime(J), limit(I), messageType(I), showFinished(Z),
#   showLocalStation(L), showPartner(L), showPending(Z), showStopped(Z),
#   startTime(J), userdefinedId(L)

_PARTNER_CLS = "Lde/mendelson/comm/as2/partner/Partner;"
_MOF_CLS     = "Lde/mendelson/comm/as2/message/MessageOverviewFilter;"

def build_message_overview_request(
    limit: int = 50,
    start_time_ms: int = 0,
    end_time_ms: int = 0,
    show_finished: bool = True,
    show_pending: bool = True,
    show_stopped: bool = True,
    direction: int = 0,
    message_type: int = 0,
) -> bytes:
    w = _W()
    w.begin_object()

    w.classdesc(_MORQ, _SUID, 0x02, [
        ('L', 'filter',    _MOF_CLS),
        ('L', 'messageId', _STR),
    ])
    w.classdesc(_CSM, _SUID, 0x02, [
        ('Z', '_syncRequest'),
        ('J', 'referenceId'),
        ('L', 'pid', _STR),
    ])
    w.null()

    # super data
    w.bool_(False)
    w.i64(3)
    w.new_string(_pid())

    # filter field — inline MessageOverviewFilter TC_OBJECT
    w._buf.write(b'\x73')  # TC_OBJECT
    w.classdesc(_MOF, _SUID, 0x02, [
        ('I', 'direction'),
        ('J', 'endTime'),
        ('I', 'limit'),
        ('I', 'messageType'),
        ('Z', 'showFinished'),
        ('L', 'showLocalStation', _PARTNER_CLS),
        ('L', 'showPartner',      _PARTNER_CLS),
        ('Z', 'showPending'),
        ('Z', 'showStopped'),
        ('J', 'startTime'),
        ('L', 'userdefinedId',    _STR),
    ])
    w.null()   # no super for MessageOverviewFilter
    w._alloc() # object handle

    # MessageOverviewFilter data
    w.i32(direction)
    w.i64(end_time_ms)
    w.i32(limit)
    w.i32(message_type)
    w.bool_(show_finished)
    w.null()   # showLocalStation
    w.null()   # showPartner
    w.bool_(show_pending)
    w.bool_(show_stopped)
    w.i64(start_time_ms)
    w.null()   # userdefinedId

    # messageId field of MessageOverviewRequest
    w.null()

    return w.getvalue()


# ---------------------------------------------------------------------------
# MessageLogRequest  — fields: messageId(L)
# ---------------------------------------------------------------------------

def build_message_log_request(message_id: str) -> bytes:
    w = _W()
    w.begin_object()

    w.classdesc(_MLRQ, _SUID, 0x02, [
        ('L', 'messageId', _STR),
    ])
    w.classdesc(_CSM, _SUID, 0x02, [
        ('Z', '_syncRequest'),
        ('J', 'referenceId'),
        ('L', 'pid', _STR),
    ])
    w.null()

    w.bool_(False)
    w.i64(3)
    w.new_string(_pid())
    w.new_string(message_id)

    return w.getvalue()


# ---------------------------------------------------------------------------
# MessagePayloadRequest  — fields: messageId(L)
# ---------------------------------------------------------------------------

def build_message_payload_request(message_id: str) -> bytes:
    w = _W()
    w.begin_object()

    w.classdesc(_MPRQ, _SUID, 0x02, [
        ('L', 'messageId', _STR),
    ])
    w.classdesc(_CSM, _SUID, 0x02, [
        ('Z', '_syncRequest'),
        ('J', 'referenceId'),
        ('L', 'pid', _STR),
    ])
    w.null()

    w.bool_(False)
    w.i64(3)
    w.new_string(_pid())
    w.new_string(message_id)

    return w.getvalue()


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _pid() -> str:
    try:
        return f"{os.getpid()}@{socket.gethostname()}"
    except Exception:
        return f"{os.getpid()}@localhost"
