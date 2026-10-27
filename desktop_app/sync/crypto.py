"""Windows DPAPI encryption for the sync token.

Uses ctypes to call CryptProtectData/CryptUnprotectData directly so no extra
dependency (e.g. `cryptography`) is required. On non-Windows platforms it
falls back to base64 (obfuscation only, clearly not secure).

Storage format:
    "d:<base64>"  -> DPAPI encrypted payload
    "u1:<base64>" -> non-Windows fallback (plain base64)
"""

import base64
import ctypes
import ctypes.wintypes

_CRYPTPROTECT_UI_FORBIDDEN = 0x01


class DATA_BLOB(ctypes.Structure):
    _fields_ = [
        ("cbData", ctypes.wintypes.DWORD),
        ("pbData", ctypes.POINTER(ctypes.c_char)),
    ]


def _is_windows():
    return hasattr(ctypes, "windll")


def _blob_from_bytes(data):
    buf = ctypes.create_string_buffer(data, len(data))
    return DATA_BLOB(len(data), ctypes.cast(buf, ctypes.POINTER(ctypes.c_char)))


def _free_blob(blob):
    if blob and blob.pbData:
        try:
            ctypes.windll.kernel32.LocalFree(blob.pbData)
        except Exception:  # noqa: BLE001
            pass


def encode(plaintext):
    """Encrypt a secret string, returning a portable storage value."""
    if not plaintext:
        return ""
    value = plaintext.encode("utf-8")

    if not _is_windows():
        return "u1:" + base64.b64encode(value).decode("ascii")

    crypt32 = ctypes.windll.crypt32
    in_blob = _blob_from_bytes(value)
    out_blob = DATA_BLOB()
    ok = crypt32.CryptProtectData(
        ctypes.byref(in_blob),
        "NASS sync token",
        None,
        None,
        None,
        _CRYPTPROTECT_UI_FORBIDDEN,
        ctypes.byref(out_blob),
    )
    if not ok:
        raise OSError("DPAPI CryptProtectData failed")
    try:
        return "d:" + base64.b64encode(
            ctypes.string_at(out_blob.pbData, int(out_blob.cbData))
        ).decode("ascii")
    finally:
        _free_blob(out_blob)


def decode(stored):
    """Decrypt a value produced by :func:`encode`. Empty on failure."""
    if not stored:
        return ""
    if stored.startswith("u1:"):
        try:
            return base64.b64decode(stored[3:]).decode("utf-8")
        except Exception:  # noqa: BLE001
            return ""
    if not stored.startswith("d:") or not _is_windows():
        return ""

    crypt32 = ctypes.windll.crypt32
    try:
        raw = base64.b64decode(stored[2:])
    except Exception:  # noqa: BLE001
        return ""
    in_blob = _blob_from_bytes(raw)
    out_blob = DATA_BLOB()
    ok = crypt32.CryptUnprotectData(
        ctypes.byref(in_blob),
        None,
        None,
        None,
        None,
        _CRYPTPROTECT_UI_FORBIDDEN,
        ctypes.byref(out_blob),
    )
    if not ok:
        return ""
    try:
        return ctypes.string_at(out_blob.pbData, int(out_blob.cbData)).decode("utf-8")
    except Exception:  # noqa: BLE001
        return ""
    finally:
        _free_blob(out_blob)