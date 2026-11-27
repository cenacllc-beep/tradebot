"""The NVIDIA key kept on this PC, only if the user ticks the box on the settings page (`.\\run settings`; added
2026-11-27 so the PC can word its own reports when Claude is unavailable, ops/README.md "When Claude is unavailable").

Design (code review 2026-11-27: user-scope DPAPI usually fails in Task Scheduler's S4U runs, which have no loaded user
profile and no user credentials):
- the key is encrypted with Windows DPAPI in MACHINE scope (CRYPTPROTECT_LOCAL_MACHINE), with a fixed extra input;
- it is kept in %USERPROFILE%\\.tradebot\\nvidia.key, OUTSIDE the project folder (a path inside it is refused);
- the file's NTFS permissions are cut to the current user only: icacls with a fixed argument list removes inheritance
  and grants only this user full control; they are read back and checked after writing and before every use.
Trade-off: machine scope means any process running as an administrator (or SYSTEM) on this PC could decrypt the file;
the file permissions keep other, non-administrator users out. TO CONFIRM ON THE PC: one real scheduled (S4U) run must
show "Wording: AI" in logs\\report_latest.md; until then this is untested on Windows.

The key is never written to the folder, a log, a report or a page, and nothing here prints it. Off Windows there is no
DPAPI: store() refuses unless a fake is injected (tests), and permissions are checked with POSIX mode 0600.
Standard library only (ctypes, subprocess). Never touches the trading files, the Kalshi key or its settings."""
import os, sys, subprocess

HERE = os.path.dirname(os.path.abspath(__file__))
PROJECT = os.path.dirname(HERE)
ENTROPY = b"tradebot-nvidia-key-v1"     # an extra input to DPAPI, so another program's blob cannot be swapped in
CRYPTPROTECT_UI_FORBIDDEN = 0x1         # never show a prompt (scheduled jobs have no window)
CRYPTPROTECT_LOCAL_MACHINE = 0x4        # machine scope: works in S4U runs (see the trade-off above)
FLAGS = CRYPTPROTECT_UI_FORBIDDEN | CRYPTPROTECT_LOCAL_MACHINE

# load_status() results, each shown on the report's Wording line
OK, MISSING, DECRYPT, PERMISSION, UNSUPPORTED = "ok", "missing", "decrypt", "permission", "unsupported"
STATUS_TEXT = {
    MISSING: "no NVIDIA key kept on this PC",
    DECRYPT: "the key file on this PC could not be decrypted",
    PERMISSION: "the key file's permissions are not limited to your account, or it could not be read",
    UNSUPPORTED: "keeping a key needs Windows",
}


def default_path():
    return os.path.join(os.path.expanduser("~"), ".tradebot", "nvidia.key")


def _outside_project(path):
    """True when path is not inside the project folder (the key must never be in it); links are resolved first."""
    p, root = os.path.normcase(os.path.realpath(path)), os.path.normcase(os.path.realpath(PROJECT))
    try:
        return os.path.commonpath([p, root]) != root
    except ValueError:   # different drives on Windows
        return True


# ---------- DPAPI ----------
class WinDPAPI(object):
    """CryptProtectData / CryptUnprotectData through ctypes, machine scope, with declared argument types."""

    def __init__(self):
        import ctypes
        from ctypes import wintypes
        self.ct = ctypes

        class BLOB(ctypes.Structure):
            _fields_ = [("cbData", wintypes.DWORD), ("pbData", ctypes.POINTER(ctypes.c_char))]
        self.BLOB = BLOB
        PB = ctypes.POINTER(BLOB)
        self.crypt32 = ctypes.WinDLL("crypt32", use_last_error=True)
        self.kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
        for name in ("CryptProtectData", "CryptUnprotectData"):
            fn = getattr(self.crypt32, name)
            fn.argtypes = [PB, wintypes.LPCWSTR if name == "CryptProtectData" else ctypes.c_void_p, PB,
                           ctypes.c_void_p, ctypes.c_void_p, wintypes.DWORD, PB]
            fn.restype = wintypes.BOOL
        self.kernel32.LocalFree.argtypes = [ctypes.c_void_p]
        self.kernel32.LocalFree.restype = ctypes.c_void_p

    def _call(self, fn, data):
        ct = self.ct
        buf = ct.create_string_buffer(data, len(data))
        ebuf = ct.create_string_buffer(ENTROPY, len(ENTROPY))
        src = self.BLOB(len(data), ct.cast(buf, ct.POINTER(ct.c_char)))
        ent = self.BLOB(len(ENTROPY), ct.cast(ebuf, ct.POINTER(ct.c_char)))
        out = self.BLOB()
        try:
            if fn == "protect":
                ok = self.crypt32.CryptProtectData(ct.byref(src), u"tradebot NVIDIA key", ct.byref(ent), None, None,
                                                   FLAGS, ct.byref(out))
            else:
                ok = self.crypt32.CryptUnprotectData(ct.byref(src), None, ct.byref(ent), None, None, FLAGS, ct.byref(out))
            if not ok:
                raise OSError("DPAPI %s failed (Windows error %d)" % (fn, ct.get_last_error()))
            try:
                return ct.string_at(out.pbData, out.cbData)
            finally:
                ct.memset(out.pbData, 0, out.cbData)   # the plain key (unprotect) is not left in freed memory
                self.kernel32.LocalFree(ct.cast(out.pbData, ct.c_void_p))
        finally:
            ct.memset(buf, 0, len(data))

    def protect(self, data):
        return self._call("protect", data)

    def unprotect(self, data):
        return self._call("unprotect", data)


def _dpapi(dpapi):
    if dpapi is not None:
        return dpapi
    if os.name != "nt":
        return None
    return WinDPAPI()


def supported(dpapi=None):
    return dpapi is not None or os.name == "nt"


# ---------- file permissions ----------
def _user():
    """DOMAIN\\user of this process (Windows), for icacls."""
    dom, name = os.environ.get("USERDOMAIN", ""), os.environ.get("USERNAME", "")
    if not name:
        import getpass
        name = getpass.getuser()
    return "%s\\%s" % (dom, name) if dom else name


def _aces(out, path):
    """The principals icacls lists for path: [(principal, rights)]."""
    rows = []
    for ln in (out or "").splitlines():
        s = ln.strip()
        if not s or s.lower().startswith("successfully processed"):
            continue
        if s.lower().startswith(path.lower()):
            s = s[len(path):].strip()
        if ":" in s:
            who, rights = s.rsplit(":", 1)   # an unexpected line keeps extra text in `who` and fails the check
            rows.append((who.strip(), rights.strip()))
    return rows


def win_restrict(path, run=subprocess.run, user=None):
    """icacls with a fixed argv: no inherited entries, only this user with full control. (ok, message)."""
    user = user or _user()
    try:
        r = run(["icacls", path, "/inheritance:r", "/grant:r", "%s:(F)" % user], capture_output=True, text=True,
                timeout=30)
    except Exception as ex:  # noqa: BLE001
        return False, "icacls could not run (%s)" % type(ex).__name__
    if r.returncode != 0:
        return False, "icacls refused (exit %s)" % r.returncode
    return win_check(path, run, user)


def win_check(path, run=subprocess.run, user=None):
    """(ok, message): the file's permissions list only this user (SYSTEM is tolerated)."""
    user = (user or _user()).lower()
    try:
        r = run(["icacls", path], capture_output=True, text=True, timeout=30)
    except Exception as ex:  # noqa: BLE001
        return False, "icacls could not run (%s)" % type(ex).__name__
    if r.returncode != 0:
        return False, "icacls could not read the permissions (exit %s)" % r.returncode
    aces = _aces(r.stdout, path)
    others = [w for w, _ in aces if w.lower() not in (user, "nt authority\\system")]
    if not aces or others or user not in [w.lower() for w, _ in aces]:
        return False, "the permissions also allow: %s" % (", ".join(others) or "nobody named")
    if any("(i)" in rt.lower() for _, rt in aces):
        return False, "inherited permissions remain"
    return True, "permissions: only your account"


def posix_restrict(path):
    try:
        os.chmod(path, 0o600)
    except OSError as ex:
        return False, "chmod failed (%s)" % type(ex).__name__
    return posix_check(path)


def posix_check(path):
    try:
        mode = os.stat(path).st_mode & 0o777
    except OSError as ex:
        return False, "cannot read the permissions (%s)" % type(ex).__name__
    return (mode & 0o077) == 0, "mode %o" % mode


def _acl(acl):
    """(restrict, check) functions for this system, or the injected pair."""
    if acl is not None:
        return acl
    if os.name == "nt":
        return win_restrict, win_check
    return posix_restrict, posix_check


# ---------- store, load, remove ----------
def exists(path=None):
    return os.path.isfile(path or default_path())


def store(key, dpapi=None, path=None, acl=None):
    """Encrypt and save the key, then cut its permissions to this user and check them. (ok, message); the message never
    contains the key. On any failure the file is removed."""
    path = path or default_path()
    if not _outside_project(path):
        return False, "Refused: the key file would be inside the project folder."
    d = _dpapi(dpapi)
    if d is None:
        return False, "Keeping the key on this PC needs Windows (DPAPI)."
    restrict, _check = _acl(acl)
    tmp = "%s.%d.tmp" % (path, os.getpid())
    try:
        raw = key.encode("utf-8")
        blob = d.protect(raw)
        if raw in blob:
            return False, "Refused: the encryption returned the key unchanged."
        os.makedirs(os.path.dirname(path), exist_ok=True)
        fd = os.open(tmp, os.O_WRONLY | os.O_CREAT | os.O_TRUNC | getattr(os, "O_BINARY", 0), 0o600)
        with os.fdopen(fd, "wb") as f:
            f.write(blob)
        os.replace(tmp, path)
    except Exception as ex:  # noqa: BLE001
        for p in (tmp,):
            try:
                os.remove(p)
            except OSError:
                pass
        return False, "Could not keep the key on this PC (%s)." % type(ex).__name__
    ok, why = restrict(path)
    if not ok:
        try:
            os.remove(path)
        except OSError:
            pass
        return False, "Not kept: the key file's permissions could not be limited to your account (%s)." % why
    return True, "Kept on this PC, encrypted, the file readable by your account only (%s)." % path


def load_status(dpapi=None, path=None, acl=None):
    """(key or None, status): OK, MISSING, DECRYPT, PERMISSION or UNSUPPORTED. Never prints the key."""
    path = path or default_path()
    if not _outside_project(path):
        return None, PERMISSION
    if not os.path.exists(path):
        return None, MISSING
    d = _dpapi(dpapi)
    if d is None:
        return None, UNSUPPORTED
    _restrict, check = _acl(acl)
    try:
        ok, _why = check(path)
    except Exception:  # noqa: BLE001
        ok = False
    if not ok:
        return None, PERMISSION
    try:
        with open(path, "rb") as f:
            blob = f.read(64 * 1024)
    except OSError:
        return None, PERMISSION
    try:
        key = d.unprotect(blob).decode("utf-8").strip()
    except Exception:  # noqa: BLE001
        return None, DECRYPT
    return (key, OK) if key else (None, DECRYPT)


def load(dpapi=None, path=None, acl=None):
    """The decrypted key, or None."""
    return load_status(dpapi, path, acl)[0]


def remove(path=None):
    """Delete the key file. (ok, message)."""
    path = path or default_path()
    if not os.path.exists(path):
        return True, "No key was kept on this PC."
    try:
        os.remove(path)
    except OSError as ex:
        return False, "Could not remove the key file (%s)." % type(ex).__name__
    return True, "Removed the key from this PC."


if __name__ == "__main__":   # status only; never prints the key
    print("A key is kept on this PC (encrypted)." if exists() else "No key is kept on this PC.")
    sys.exit(0)
