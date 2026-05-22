"""Native macOS process inspection via libproc ctypes bindings.

Replaces subprocess calls to pgrep, ps, and lsof with direct libproc
function calls, eliminating fork overhead for faster detection.
"""

from __future__ import annotations

import ctypes
import ctypes.util

from claudewatch.backend.core.process.models import ProcessEntry, ProcessInfo

# libproc bindings

_libproc_path = ctypes.util.find_library("libproc")
if _libproc_path is None:
    _libproc_path = "/usr/lib/libproc.dylib"

_libproc = ctypes.CDLL(_libproc_path, use_errno=True)

# Constants
PROC_ALL_PIDS = 1
PROC_PIDTASKALLINFO = 2
PROC_PIDVNODEPATHINFO = 9
MAXPATHLEN = 4096
_PROC_NAME_BUF = 256  # generous buffer for proc_name

# dev_t bit layout on macOS (see sys/types.h)
_DEV_MAJOR_SHIFT = 24
_DEV_MAJOR_MASK = 0xFF
_DEV_MINOR_MASK = 0xFFFFFF
_PTY_MAJOR = 16  # pseudo-terminal major device number

# Struct offsets — verified empirically on macOS ARM64.
# proc_pidinfo(PROC_PIDTASKALLINFO) returns 232 bytes.
# Fields from proc_bsdinfo: ppid @ offset 16, tdev @ offset 108.
_TASKALLINFO_SIZE = 232
_PBSD_PPID_OFFSET = 16
_PBSD_TDEV_OFFSET = 108

# proc_vnodepathinfo: the CWD vnode path starts at the vip_path field.
# struct vnode_info_path = vnode_info (152 bytes) + path[MAXPATHLEN]
# struct proc_vnodepathinfo = vip_cdir (vnode_info_path) + vip_rdir (vnode_info_path)
# vip_cdir.vip_path offset = 152
_VNODEPATHINFO_SIZE = 2352
_VIP_CDIR_PATH_OFFSET = 152

# Function prototypes

# int proc_listpids(uint32_t type, uint32_t typeinfo, void *buffer, int buffersize)
_libproc.proc_listpids.argtypes = [
    ctypes.c_uint32,
    ctypes.c_uint32,
    ctypes.c_void_p,
    ctypes.c_int,
]
_libproc.proc_listpids.restype = ctypes.c_int

# int proc_pidinfo(int pid, int flavor, uint64_t arg, void *buffer, int buffersize)
_libproc.proc_pidinfo.argtypes = [
    ctypes.c_int,
    ctypes.c_int,
    ctypes.c_uint64,
    ctypes.c_void_p,
    ctypes.c_int,
]
_libproc.proc_pidinfo.restype = ctypes.c_int

# int proc_name(int pid, void *buffer, uint32_t buffersize)
_libproc.proc_name.argtypes = [ctypes.c_int, ctypes.c_void_p, ctypes.c_uint32]
_libproc.proc_name.restype = ctypes.c_int

# int proc_pidpath(int pid, void *buffer, uint32_t buffersize)
_libproc.proc_pidpath.argtypes = [ctypes.c_int, ctypes.c_void_p, ctypes.c_uint32]
_libproc.proc_pidpath.restype = ctypes.c_int


# Internal helpers


def _list_all_pids() -> list[int]:
    """Return a list of all PIDs on the system."""
    # First call with NULL buffer returns the needed buffer size in bytes.
    buf_size = _libproc.proc_listpids(PROC_ALL_PIDS, 0, None, 0)
    if buf_size <= 0:
        return []

    # Allocate buffer (each PID is a uint32 = 4 bytes). Add headroom for new procs.
    n_pids = buf_size // ctypes.sizeof(ctypes.c_uint32) + 16
    pid_buf = (ctypes.c_uint32 * n_pids)()

    ret = _libproc.proc_listpids(
        PROC_ALL_PIDS,
        0,
        ctypes.byref(pid_buf),
        ctypes.sizeof(pid_buf),
    )
    if ret <= 0:
        return []

    count = ret // ctypes.sizeof(ctypes.c_uint32)
    return [int(pid_buf[i]) for i in range(count) if pid_buf[i] != 0]


def _proc_pidpath(pid: int) -> str:
    """Get the full executable path for a PID."""
    buf = ctypes.create_string_buffer(MAXPATHLEN)
    ret = _libproc.proc_pidpath(pid, buf, MAXPATHLEN)
    if ret <= 0:
        return ""
    return buf.value.decode("utf-8", errors="replace")


def _dev_to_tty(dev: int) -> str:
    """Convert a dev_t to a TTY name string.

    Returns "??" for non-PTY or invalid devices, matching ps behaviour.
    """
    if dev in (0, -1, 0xFFFFFFFF):
        return "??"
    major = (dev >> _DEV_MAJOR_SHIFT) & _DEV_MAJOR_MASK
    minor = dev & _DEV_MINOR_MASK
    if major == _PTY_MAJOR:
        return f"ttys{minor:03d}"
    return "??"


# Public API


def get_process_info(pids: list[int]) -> dict[int, ProcessInfo]:
    """Get tty, ppid, and full executable path for a list of PIDs.

    Returns a dict mapping PID -> ProcessInfo.
    Replacement for ``ps -o pid=,tty=,ppid=,comm= -p <pids>``.
    """
    if not pids:
        return {}

    result: dict[int, ProcessInfo] = {}
    info_buf = ctypes.create_string_buffer(_TASKALLINFO_SIZE)

    for pid in pids:
        ret = _libproc.proc_pidinfo(
            pid,
            PROC_PIDTASKALLINFO,
            0,
            ctypes.byref(info_buf),
            _TASKALLINFO_SIZE,
        )
        if ret < _TASKALLINFO_SIZE:
            # Process may have exited; skip it.
            continue

        raw = info_buf.raw
        ppid = int.from_bytes(raw[_PBSD_PPID_OFFSET : _PBSD_PPID_OFFSET + 4], "little")
        tdev = int.from_bytes(raw[_PBSD_TDEV_OFFSET : _PBSD_TDEV_OFFSET + 4], "little")
        tty = _dev_to_tty(tdev)
        comm = _proc_pidpath(pid)

        result[pid] = ProcessInfo(tty=tty, ppid=ppid, comm=comm)

    return result


def get_cwds(pids: list[int]) -> dict[int, str]:
    """Get the current working directory for a list of PIDs.

    Returns a dict mapping PID -> CWD path string.
    Replacement for ``lsof -a -d cwd -p <pids> -Fn``.
    """
    if not pids:
        return {}

    result: dict[int, str] = {}
    vnode_buf = ctypes.create_string_buffer(_VNODEPATHINFO_SIZE)

    for pid in pids:
        ret = _libproc.proc_pidinfo(
            pid,
            PROC_PIDVNODEPATHINFO,
            0,
            ctypes.byref(vnode_buf),
            _VNODEPATHINFO_SIZE,
        )
        if ret < _VNODEPATHINFO_SIZE:
            continue

        raw = vnode_buf.raw
        # Extract null-terminated path from the vip_cdir.vip_path field
        path_bytes = raw[_VIP_CDIR_PATH_OFFSET : _VIP_CDIR_PATH_OFFSET + MAXPATHLEN]
        null_idx = path_bytes.find(b"\x00")
        if null_idx > 0:
            cwd = path_bytes[:null_idx].decode("utf-8", errors="replace")
            if cwd:
                result[pid] = cwd

    return result


def get_ppid(pid: int) -> int:
    """Get the parent PID for a single process.

    Replacement for ``ps -o ppid= -p <pid>``. Returns 0 on failure.
    """
    info_buf = ctypes.create_string_buffer(_TASKALLINFO_SIZE)
    ret = _libproc.proc_pidinfo(
        pid,
        PROC_PIDTASKALLINFO,
        0,
        ctypes.byref(info_buf),
        _TASKALLINFO_SIZE,
    )
    if ret < _TASKALLINFO_SIZE:
        return 0
    raw = info_buf.raw
    return int.from_bytes(raw[_PBSD_PPID_OFFSET : _PBSD_PPID_OFFSET + 4], "little")


def get_single_process_info(pid: int) -> ProcessInfo | None:
    """Get tty, ppid, and comm for a single PID.

    Replacement for ``ps -o ppid=,comm= -p <pid>``. Returns None on failure.
    """
    info_buf = ctypes.create_string_buffer(_TASKALLINFO_SIZE)
    ret = _libproc.proc_pidinfo(
        pid,
        PROC_PIDTASKALLINFO,
        0,
        ctypes.byref(info_buf),
        _TASKALLINFO_SIZE,
    )
    if ret < _TASKALLINFO_SIZE:
        return None
    raw = info_buf.raw
    ppid = int.from_bytes(raw[_PBSD_PPID_OFFSET : _PBSD_PPID_OFFSET + 4], "little")
    tdev = int.from_bytes(raw[_PBSD_TDEV_OFFSET : _PBSD_TDEV_OFFSET + 4], "little")
    tty = _dev_to_tty(tdev)
    comm = _proc_pidpath(pid)
    return ProcessInfo(tty=tty, ppid=ppid, comm=comm)


def list_all_processes() -> list[ProcessEntry]:
    """Return pid, ppid, tty, comm for every process on the system.

    Replacement for ``ps -eo pid,ppid,tty,comm``.
    """
    all_pids = _list_all_pids()
    result: list[ProcessEntry] = []
    info_buf = ctypes.create_string_buffer(_TASKALLINFO_SIZE)

    for pid in all_pids:
        ret = _libproc.proc_pidinfo(
            pid,
            PROC_PIDTASKALLINFO,
            0,
            ctypes.byref(info_buf),
            _TASKALLINFO_SIZE,
        )
        if ret < _TASKALLINFO_SIZE:
            continue
        raw = info_buf.raw
        ppid = int.from_bytes(raw[_PBSD_PPID_OFFSET : _PBSD_PPID_OFFSET + 4], "little")
        tdev = int.from_bytes(raw[_PBSD_TDEV_OFFSET : _PBSD_TDEV_OFFSET + 4], "little")
        tty = _dev_to_tty(tdev)
        comm = _proc_pidpath(pid)
        result.append(ProcessEntry(pid=pid, tty=tty, ppid=ppid, comm=comm))

    return result
