"""Sumber AI yang dipakai TƎRᗩ di laptop ini:
- "lokal": Ollama di laptop ini (configs/ai.json -> ollama.host)
- "server": Server AI bersama milik teman, lewat Tailscale, wajib login.

Pilihan dan token login disimpan di configs/sumber_ai.json (tidak dinaikkan ke GitHub).
Password tidak pernah disimpan; hanya token login yang berlaku 30 hari."""
import json
import os
import urllib.error
import urllib.request
from typing import Any, Dict, List, Optional, Tuple

from tools import version as VER
from tools.ai_config import ROOT_DIR, ollama_settings

CONF = ROOT_DIR / "configs" / "sumber_ai.json"
LOCAL_DEFAULT = "http://127.0.0.1:11434"


class AccessError(RuntimeError):
    """Server AI bersama menolak (login habis, akun nonaktif). Tidak ada gunanya diulang."""


def load() -> Dict[str, Any]:
    try:
        d = json.loads(CONF.read_text(encoding="utf-8"))
        return d if isinstance(d, dict) else {"mode": "lokal"}
    except Exception:
        return {"mode": "lokal"}


def _save(d: Dict[str, Any]) -> None:
    CONF.parent.mkdir(parents=True, exist_ok=True)
    tmp = CONF.with_suffix(".tmp")
    tmp.write_text(json.dumps(d, ensure_ascii=False, indent=2), encoding="utf-8")
    os.replace(tmp, CONF)


def is_server() -> bool:
    return load().get("mode") == "server"


def local_host() -> str:
    try:
        o = ollama_settings()
        return o.get("base_url") or o.get("host") or LOCAL_DEFAULT
    except Exception:
        return LOCAL_DEFAULT


def connection() -> Tuple[str, Dict[str, str]]:
    """(alamat, header) untuk berbicara dengan AI sesuai sumber yang dipilih."""
    d = load()
    if d.get("mode") == "server":
        if not d.get("url") or not d.get("token"):
            raise AccessError("Belum masuk ke Server AI bersama. Buka Pengaturan > Sumber AI lalu masuk.")
        return d["url"].rstrip("/"), {"Authorization": f"Bearer {d['token']}", "X-Tera-Version": VER.current()}
    return local_host(), {}


def client(timeout: Optional[float] = None):
    """ollama.Client yang sudah membawa token login bila memakai server bersama."""
    from ollama import Client
    host, headers = connection()
    try:
        return Client(host=host, timeout=timeout, headers=headers)
    except TypeError:  # versi pustaka ollama lama yang belum menerima headers
        c = Client(host=host, timeout=timeout)
        c._client.headers.update(headers)
        return c


def is_auth_error(e: Exception) -> bool:
    return isinstance(e, AccessError) or getattr(e, "status_code", None) in (401, 403, 426)


def auth_message(e: Exception) -> str:
    if getattr(e, "status_code", None) == 426:  # versi TƎRᗩ terlalu lama: pesan dari server sudah jelas
        return str(getattr(e, "error", None) or e)
    return ("Server AI bersama menolak permintaan: sesi login habis atau akun dinonaktifkan. "
            "Masuk lagi di Pengaturan > Sumber AI.")


def _request(method: str, url: str, body: Optional[dict] = None, headers: Optional[dict] = None,
             timeout: float = 10) -> Tuple[int, Any]:
    data = json.dumps(body).encode("utf-8") if body is not None else None
    req = urllib.request.Request(url, data=data, method=method,
                                 headers={**({"Content-Type": "application/json"} if data else {}), **(headers or {})})
    opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))  # langsung, tidak lewat proxy kantor
    try:
        with opener.open(req, timeout=timeout) as r:
            raw = r.read()
            status = r.status
    except urllib.error.HTTPError as e:
        raw, status = e.read(), e.code
    try:
        return status, json.loads(raw.decode("utf-8") or "null")
    except Exception:
        return status, None


def probe() -> Tuple[Optional[List[Dict[str, Any]]], str]:
    """(daftar model [{name, size}] atau None, masalah). Masalah: "" | "mati" | "login" | "ditolak" | "versi"."""
    try:
        host, headers = connection()
    except AccessError:
        return None, "login"
    try:
        if is_server():
            _refresh_versions(host, headers)
        status, data = _request("GET", f"{host}/api/tags", headers=headers, timeout=6)
    except Exception:
        return None, "mati"
    if status == 401:
        return None, "login"
    if status == 403:
        return None, "ditolak"
    if status == 426:
        return None, "versi"
    if status != 200 or not isinstance(data, dict):
        return None, "mati"
    out = []
    for m in data.get("models") or []:
        name = m.get("model") or m.get("name")
        if name:
            out.append({"name": name, "size": m.get("size") or 0})
    return out, ""


def _refresh_versions(host: str, headers: Dict[str, str]) -> None:
    """Catat versi TƎRᗩ milik server dan versi minimal yang diwajibkannya (untuk pemberitahuan versi baru)."""
    try:
        code, data = _request("GET", f"{host}/", headers=headers, timeout=4)
    except Exception:
        return
    if code != 200 or not isinstance(data, dict):
        return
    d = load()
    new = {"server_version": data.get("server_version") or "", "min_version": data.get("min_version") or ""}
    if any(d.get(k, "") != v for k, v in new.items()):
        d.update(new)
        _save(d)


def status() -> Dict[str, Any]:
    """Untuk ditampilkan (tanpa token)."""
    d = load()
    mine, srv, need = VER.current(), d.get("server_version") or "", d.get("min_version") or ""
    server = d.get("mode") == "server"
    return {"mode": d.get("mode") or "lokal", "url": d.get("url") or "", "username": d.get("username") or "",
            "logged_in": bool(d.get("token")), "expires": d.get("expires"), "version": mine,
            "server_version": srv if server else "", "min_version": need if server else "",
            "update_available": server and VER.older(mine, srv), "too_old": server and VER.older(mine, need)}


def login(url: str, username: str, password: str) -> Dict[str, Any]:
    url = url.strip().rstrip("/")
    try:
        status_code, data = _request("POST", f"{url}/auth/login",
                                     {"username": username, "password": password, "version": VER.current()},
                                     {"X-Tera-Version": VER.current()}, timeout=12)
    except Exception:
        raise ConnectionError("Server tidak bisa dihubungi. Pastikan Tailscale menyala dan sudah masuk, "
                              "alamatnya benar, dan Server AI di komputer temanmu sedang berjalan.")
    if status_code == 200 and isinstance(data, dict) and data.get("token"):
        _save({"mode": "server", "url": url, "username": data.get("username") or username,
               "token": data["token"], "expires": data.get("expires"),
               "server_version": data.get("server_version") or "", "min_version": data.get("min_version") or ""})
        return status()
    msg = (data or {}).get("detail") or (data or {}).get("error") if isinstance(data, dict) else None
    if status_code == 404 or not msg:
        raise ConnectionError("Alamat ini bukan Server AI TƎRᗩ. Periksa lagi alamat dari pemilik server.")
    raise PermissionError(msg)


def logout() -> Dict[str, Any]:
    d = load()
    if d.get("url") and d.get("token"):
        try:
            _request("POST", f"{d['url']}/auth/logout", {}, {"Authorization": f"Bearer {d['token']}"}, timeout=5)
        except Exception:
            pass  # tetap keluar di laptop ini walau server tidak bisa dihubungi
    d.pop("token", None)
    d.pop("expires", None)
    d["mode"] = "server" if d.get("url") else "lokal"
    _save(d)
    return status()


def use_local() -> Dict[str, Any]:
    d = load()
    d["mode"] = "lokal"
    _save(d)
    return status()


def use_server() -> Dict[str, Any]:
    d = load()
    d["mode"] = "server"
    _save(d)
    return status()

