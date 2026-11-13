"""Penyimpanan akun, sesi login, dan catatan pemakaian Server AI (folder data/server_ai, tidak dinaikkan ke GitHub).
Password disimpan sebagai hash scrypt; token login disimpan sebagai hash sha256, jadi file ini bocor pun
password dan token aslinya tidak terbaca."""
import hashlib
import hmac
import json
import os
import secrets
import threading
import time
from pathlib import Path
from typing import Any, Dict, List, Optional

ROOT = Path(__file__).resolve().parents[1]
DATA = ROOT / "data" / "server_ai"
TOKEN_DAYS = 30
MAX_FAILS, LOCK_MINUTES = 5, 15
_SCRYPT = dict(n=2 ** 14, r=8, p=1, dklen=32)


class StoreError(Exception):
    def __init__(self, status: int, message: str, field: Optional[str] = None):
        super().__init__(message)
        self.status, self.message, self.field = status, message, field


def _hash_pw(password: str, salt: bytes) -> str:
    return hashlib.scrypt(password.encode("utf-8"), salt=salt, **_SCRYPT).hex()


def _token_key(token: str) -> str:
    return hashlib.sha256(token.encode("utf-8")).hexdigest()


class Store:
    def __init__(self, folder: Path = DATA):
        self.folder = Path(folder)
        self.folder.mkdir(parents=True, exist_ok=True)
        self.file = self.folder / "akun.json"
        self.usage_file = self.folder / "pemakaian.jsonl"
        self.settings_file = self.folder / "pengaturan.json"
        self.lock = threading.Lock()
        self.fails: Dict[str, List[float]] = {}  # kunci -> [jumlah gagal, terkunci sampai]
        self.data = self._load()
        self._dummy = _hash_pw("x", b"0" * 16)

    # ---- file
    def _load(self) -> Dict[str, Any]:
        try:
            d = json.loads(self.file.read_text(encoding="utf-8"))
            d.setdefault("users", {})
            d.setdefault("tokens", {})
            return d
        except FileNotFoundError:
            return {"users": {}, "tokens": {}}

    # ---- pengaturan server
    def settings(self) -> Dict[str, Any]:
        try:
            d = json.loads(self.settings_file.read_text(encoding="utf-8"))
            return d if isinstance(d, dict) else {}
        except Exception:
            return {}

    def save_settings(self, values: Dict[str, Any]) -> None:
        with self.lock:
            d = {**self.settings(), **values}
            tmp = self.settings_file.with_suffix(".tmp")
            tmp.write_text(json.dumps(d, ensure_ascii=False, indent=1), encoding="utf-8")
            os.replace(tmp, self.settings_file)

    def _save(self) -> None:
        tmp = self.file.with_suffix(".tmp")
        tmp.write_text(json.dumps(self.data, ensure_ascii=False, indent=1), encoding="utf-8")
        os.replace(tmp, self.file)

    # ---- akun (admin)
    def list_users(self) -> List[Dict[str, Any]]:
        stats = self.usage_stats()
        with self.lock:
            now = time.time()
            out = []
            for name, u in sorted(self.data["users"].items()):
                sessions = sum(1 for t in self.data["tokens"].values() if t["user"] == name and t["exp"] > now)
                out.append({"username": name, "active": u.get("active", True), "created": u.get("created"),
                            "version": u.get("version") or "",
                            "last_login": u.get("last_login"), "sessions": sessions,
                            "locked": self._locked_until(name) > now, **stats.get(name, {})})
            return out

    def create_user(self, username: str, password: str) -> None:
        with self.lock:
            if username in self.data["users"]:
                raise StoreError(409, "Nama pengguna sudah dipakai.", "u-name")
            salt = secrets.token_bytes(16)
            self.data["users"][username] = {"salt": salt.hex(), "hash": _hash_pw(password, salt), "active": True,
                                            "created": time.time()}
            self._save()

    def _user(self, username: str) -> Dict[str, Any]:
        u = self.data["users"].get(username)
        if not u:
            raise StoreError(404, "Akun tidak ditemukan.")
        return u

    def set_password(self, username: str, password: str) -> None:
        with self.lock:
            u = self._user(username)
            salt = secrets.token_bytes(16)
            u.update(salt=salt.hex(), hash=_hash_pw(password, salt))
            self._revoke(username)  # semua perangkat harus login ulang dengan password baru
            self.fails.pop(username, None)
            self._save()

    def set_active(self, username: str, active: bool) -> None:
        with self.lock:
            self._user(username)["active"] = bool(active)
            if not active:
                self._revoke(username)
            self._save()

    def delete_user(self, username: str) -> None:
        with self.lock:
            self._user(username)
            del self.data["users"][username]
            self._revoke(username)
            self._save()

    def _revoke(self, username: str) -> None:
        self.data["tokens"] = {k: t for k, t in self.data["tokens"].items() if t["user"] != username}

    # ---- login
    def _locked_until(self, key: str) -> float:
        f = self.fails.get(key)
        return f[1] if f else 0.0

    def _fail(self, key: str) -> None:
        f = self.fails.setdefault(key, [0, 0.0])
        f[0] += 1
        if f[0] >= MAX_FAILS:
            f[1] = time.time() + LOCK_MINUTES * 60
            f[0] = 0

    def login(self, username: str, password: str, ip: str, version: str = "") -> Dict[str, Any]:
        now = time.time()
        with self.lock:
            for key in (username, f"ip:{ip}"):
                until = self._locked_until(key)
                if until > now:
                    menit = max(1, round((until - now) / 60))
                    raise StoreError(429, f"Terlalu banyak percobaan gagal. Coba lagi {menit} menit lagi.")
            u = self.data["users"].get(username)
            # hitung hash walau akun tidak ada, supaya lama respons tidak membocorkan nama pengguna yang terdaftar
            ok = hmac.compare_digest(_hash_pw(password, bytes.fromhex(u["salt"])) if u else self._dummy,
                                     u["hash"] if u else "-")
            if not ok:
                self._fail(username)
                self._fail(f"ip:{ip}")
                raise StoreError(401, "Nama pengguna atau password salah.")
            if not u.get("active", True):
                raise StoreError(403, "Akun ini sedang dinonaktifkan admin.")
            self.fails.pop(username, None)
            self.fails.pop(f"ip:{ip}", None)
            token = secrets.token_urlsafe(32)
            exp = now + TOKEN_DAYS * 86400
            self.data["tokens"] = {k: t for k, t in self.data["tokens"].items() if t["exp"] > now}
            self.data["tokens"][_token_key(token)] = {"user": username, "exp": exp, "created": now}
            u["last_login"] = now
            if version:
                u["version"] = version[:20]
            self._save()
            return {"token": token, "username": username, "expires": exp}

    def check(self, token: str) -> Optional[str]:
        if not token:
            return None
        with self.lock:
            t = self.data["tokens"].get(_token_key(token))
            if not t or t["exp"] <= time.time():
                return None
            u = self.data["users"].get(t["user"])
            if not u or not u.get("active", True):
                return None
            return t["user"]

    def token_info(self, token: str) -> Optional[Dict[str, Any]]:
        with self.lock:
            t = self.data["tokens"].get(_token_key(token or ""))
            return dict(t) if t else None

    def logout(self, token: str) -> None:
        with self.lock:
            if self.data["tokens"].pop(_token_key(token or ""), None):
                self._save()

    # ---- pemakaian (tanpa isi permintaan)
    def log_usage(self, entry: Dict[str, Any]) -> None:
        line = json.dumps(entry, ensure_ascii=False)
        with self.lock:
            with self.usage_file.open("a", encoding="utf-8") as f:
                f.write(line + "\n")

    def usage_stats(self, since: Optional[float] = None) -> Dict[str, Dict[str, Any]]:
        out: Dict[str, Dict[str, Any]] = {}
        if not self.usage_file.exists():
            return out
        since = since if since is not None else time.time() - 30 * 86400
        with self.usage_file.open(encoding="utf-8") as f:
            for line in f:
                try:
                    e = json.loads(line)
                except Exception:
                    continue
                if e.get("t", 0) < since:
                    continue
                s = out.setdefault(e.get("user", "?"), {"requests": 0, "seconds": 0.0, "tokens": 0, "last_used": 0})
                s["requests"] += 1
                s["seconds"] += float(e.get("secs") or 0)
                s["tokens"] += int(e.get("tokens_in") or 0) + int(e.get("tokens_out") or 0)
                if e.get("ver") and e.get("t", 0) >= s["last_used"]:
                    s["version"] = str(e["ver"])  # versi TƎRᗩ yang terakhir dipakai akun ini
                s["last_used"] = max(s["last_used"], e.get("t", 0))
        return out
