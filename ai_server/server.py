"""Server AI TƎRᗩ (jalankan lewat Server_AI_dan_Admin_Akun.bat atau: python -m ai_server).

Alur: laptop teman -> Tailscale (terenkripsi) -> server ini (wajib login) -> Ollama di mesin yang sama (127.0.0.1).
- Hanya menerima koneksi dari jaringan Tailscale (100.64.0.0/10, fd7a:115c:a1e0::/48) dan dari mesin ini sendiri.
- Ollama tetap hanya mendengar 127.0.0.1, jadi satu-satunya jalan masuk ke AI adalah lewat login di sini.
- Halaman admin (buat/nonaktifkan/hapus akun) hanya bisa dibuka dari mesin server ini.
- Yang dicatat hanya siapa, kapan, model apa, berapa lama, dan berapa token. Isi permintaan tidak disimpan."""
import argparse
import http.client
import ipaddress
import json
import re
import shutil
import socket
import subprocess
import sys
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Optional, Tuple
from urllib.parse import unquote, urlparse

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from ai_server.store import Store, StoreError  # noqa: E402
from tools import form_rules as FR  # noqa: E402
from tools import version as VER  # noqa: E402

DEFAULT_PORT = 11500
BODY_LIMIT = 120 * 1024 * 1024  # permintaan berisi gambar (Desain Konversi ke PRD) bisa besar
ALLOWED_NETS = [ipaddress.ip_network(n) for n in ("100.64.0.0/10", "fd7a:115c:a1e0::/48")]
# Jalur Ollama yang boleh dipakai. Unduh/hapus/buat model (pull, delete, create, push, copy) sengaja tidak dibuka.
PROXY = {("GET", "/api/version"), ("GET", "/api/tags"), ("GET", "/api/ps"),
         ("POST", "/api/show"), ("POST", "/api/chat"), ("POST", "/api/embed"), ("POST", "/api/embeddings")}
ADMIN_HTML = Path(__file__).resolve().parent / "admin.html"
LOGO = ROOT / "dashboard" / "tera.ico"


def upstream_from_config() -> str:
    try:
        cfg = json.loads((ROOT / "configs" / "ai.json").read_text(encoding="utf-8"))
        return (cfg.get("ollama") or {}).get("host") or "http://127.0.0.1:11434"
    except Exception:
        return "http://127.0.0.1:11434"


def _addr(ip: str):
    try:
        a = ipaddress.ip_address(str(ip).split("%")[0])
    except ValueError:
        return None
    return getattr(a, "ipv4_mapped", None) or a


def is_local(ip: str) -> bool:
    a = _addr(ip)
    return bool(a and a.is_loopback)


def is_allowed(ip: str) -> bool:
    a = _addr(ip)
    return bool(a and (a.is_loopback or any(a.version == n.version and a in n for n in ALLOWED_NETS)))


def tailscale_ip() -> Optional[str]:
    """Alamat Tailscale mesin ini (100.x.y.z), atau None bila Tailscale belum terpasang/masuk."""
    cands = [shutil.which("tailscale"), r"C:\Program Files\Tailscale\tailscale.exe",
             "/Applications/Tailscale.app/Contents/MacOS/Tailscale"]
    for exe in [c for c in cands if c and Path(c).exists()]:
        try:
            out = subprocess.run([exe, "ip", "-4"], capture_output=True, text=True, timeout=8,
                                 creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0)).stdout
            ip = (out or "").strip().splitlines()[0].strip() if (out or "").strip() else ""
            if ip and is_allowed(ip):
                return ip
        except Exception:
            continue
    return None


def port_open(host: str, port: int) -> bool:
    try:
        with socket.create_connection((host, port), timeout=1.5):
            return True
    except OSError:
        return False


_STORE: Optional[Store] = None


def version_info() -> dict:
    return {"server_version": VER.current(),
            "min_version": (_STORE.settings().get("min_version") if _STORE else "") or ""}


class Gateway:
    def __init__(self, port: int, upstream: str, store: Store):
        self.port, self.store = port, store
        u = urlparse(upstream)
        self.up_host, self.up_port = u.hostname or "127.0.0.1", u.port or 11434
        self.started = time.time()

    def ollama_ok(self) -> bool:
        try:
            c = http.client.HTTPConnection(self.up_host, self.up_port, timeout=4)
            c.request("GET", "/api/version")
            ok = c.getresponse().status == 200
            c.close()
            return ok
        except Exception:
            return False

    def info(self) -> dict:
        ts = tailscale_ip()
        exposed = bool(ts) and port_open(ts, self.up_port)  # Ollama bisa dibuka langsung tanpa login?
        return {"tailscale_ip": ts, "address": f"http://{ts}:{self.port}" if ts else None, "port": self.port,
                "ollama": self.ollama_ok(), "ollama_exposed": exposed, "started": self.started}


def start_ollama(gw: "Gateway") -> bool:
    """Nyalakan Ollama di mesin ini bila belum menyala, dan pastikan hanya mendengar 127.0.0.1."""
    if gw.ollama_ok():
        return True
    exe = shutil.which("ollama") or next((p for p in (Path.home() / "AppData/Local/Programs/Ollama/ollama.exe",)
                                          if p.exists()), None)
    if not exe:
        return False
    import os
    env = {**os.environ, "OLLAMA_HOST": f"127.0.0.1:{gw.up_port}"}
    env.setdefault("OLLAMA_KEEP_ALIVE", "30m")
    subprocess.Popen([str(exe), "serve"], env=env, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                     creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
    for _ in range(40):
        time.sleep(0.75)
        if gw.ollama_ok():
            return True
    return False


def keep_awake() -> None:
    """Windows: cegah komputer server tidur otomatis selama Server AI berjalan (layar boleh mati)."""
    try:
        import ctypes
        ctypes.windll.kernel32.SetThreadExecutionState(0x80000000 | 0x00000001)
    except Exception:
        pass


class ApiError(Exception):
    def __init__(self, status, message, field=None):
        super().__init__(message)
        self.status, self.message, self.field = status, message, field


def make_handler(gw: Gateway):
    global _STORE
    store = _STORE = gw.store

    class Handler(BaseHTTPRequestHandler):
        server_version = "TeraServerAI/1.0"
        sys_version = ""

        def log_message(self, fmt, *args):
            pass

        @property
        def ip(self) -> str:
            return self.client_address[0]

        # ---- helpers
        def send_json(self, data, status=200):
            raw = json.dumps(data, ensure_ascii=False).encode("utf-8")
            self.send_response(status)
            self.send_header("Content-Type", "application/json; charset=utf-8")
            self.send_header("Content-Length", str(len(raw)))
            self.send_header("Cache-Control", "no-store")
            self.end_headers()
            self.wfile.write(raw)

        def read_body(self, limit=64_000) -> bytes:
            try:
                n = int(self.headers.get("Content-Length") or 0)
            except ValueError:
                raise ApiError(400, "Permintaan tidak valid.")
            if n > limit:
                raise ApiError(413, "Permintaan terlalu besar.")
            return self.rfile.read(n) if n > 0 else b""

        def json_body(self) -> dict:
            try:
                d = json.loads(self.read_body().decode("utf-8") or "{}")
            except ApiError:
                raise
            except Exception:
                raise ApiError(400, "Format data tidak valid.")
            if not isinstance(d, dict):
                raise ApiError(400, "Format data tidak valid.")
            return d

        def bearer(self) -> str:
            h = self.headers.get("Authorization") or ""
            return h[7:].strip() if h.lower().startswith("bearer ") else ""

        def client_version(self) -> str:
            return (self.headers.get("X-Tera-Version") or "").strip()[:20]

        def check_version(self, version: str) -> None:
            need = store.settings().get("min_version") or ""
            if need and VER.older(version, need):
                raise ApiError(426, f"TƎRᗩ di laptopmu versi {version or 'lama'}, sedangkan Server AI ini mewajibkan "
                                    f"minimal versi {need}. Minta folder TƎRᗩ terbaru ke pemilik server.")

        def require_user(self) -> str:
            user = store.check(self.bearer())
            if not user:
                raise ApiError(401, "Sesi login tidak berlaku. Masuk lagi di Pengaturan TƎRᗩ.")
            self.check_version(self.client_version())
            return user

        def require_admin(self, api: bool) -> None:
            # Halaman admin hanya dari mesin ini. Cek Host melindungi dari situs lain yang menyamar (DNS rebinding);
            # header khusus memaksa browser menolak permintaan lintas situs (CSRF).
            host = (self.headers.get("Host") or "").rsplit(":", 1)[0].strip("[]").lower()
            if not is_local(self.ip) or host not in ("127.0.0.1", "localhost", "::1"):
                raise ApiError(403, "Halaman admin hanya bisa dibuka dari komputer server.")
            if api and self.headers.get("X-Tera-Admin") != "1":
                raise ApiError(403, "Permintaan admin ditolak.")

        # ---- dispatch
        def handle_any(self, method: str):
            path = unquote(urlparse(self.path).path)
            try:
                if not is_allowed(self.ip):
                    raise ApiError(403, "Akses hanya lewat Tailscale.")
                if path.startswith("/admin"):
                    return self.admin(method, path)
                if (method, path) in PROXY:
                    return self.proxy(method, path, self.require_user())
                if method == "GET" and path in ("/", "/ping"):
                    return self.send_json({"service": "tera-server-ai", "ok": True, **version_info()})
                if method == "POST" and path == "/auth/login":
                    d = self.json_body()
                    u, p = str(d.get("username") or ""), str(d.get("password") or "")
                    if not u or not p or len(u) > 64 or len(p) > 256:
                        raise ApiError(400, "Nama pengguna dan password wajib diisi.")
                    ver = str(d.get("version") or self.client_version())[:20]
                    self.check_version(ver)
                    res = store.login(u.strip().lower(), p, self.ip, ver)
                    return self.send_json({**res, **version_info()})
                if method == "POST" and path == "/auth/logout":
                    store.logout(self.bearer())
                    return self.send_json({"ok": True})
                if method == "GET" and path == "/auth/me":
                    user = self.require_user()
                    t = store.token_info(self.bearer()) or {}
                    return self.send_json({"username": user, "expires": t.get("exp"), **version_info()})
                if path.startswith("/api/"):
                    raise ApiError(403, "Perintah ini tidak dibuka di Server AI bersama.")
                raise ApiError(404, "Alamat tidak dikenal.")
            except (ApiError, StoreError) as e:
                body = {"error": e.message, "detail": e.message}
                if getattr(e, "field", None):
                    body["field"] = e.field
                try:
                    self.send_json(body, e.status)
                except Exception:
                    pass
            except (BrokenPipeError, ConnectionResetError):
                pass
            except Exception as e:
                try:
                    self.send_json({"error": f"Kesalahan di server: {e}", "detail": f"Kesalahan di server: {e}"}, 500)
                except Exception:
                    pass

        def do_GET(self):
            self.handle_any("GET")

        def do_POST(self):
            self.handle_any("POST")

        def do_DELETE(self):
            self.handle_any("DELETE")

        def do_PUT(self):
            self.handle_any("PUT")

        # ---- teruskan ke Ollama
        def proxy(self, method: str, path: str, user: str):
            body = self.read_body(BODY_LIMIT) if method == "POST" else b""
            model = ""
            if body:
                try:
                    model = str(json.loads(body).get("model") or "")[:120]
                except Exception:
                    raise ApiError(400, "Format data tidak valid.")
            t0 = time.time()
            try:
                conn = http.client.HTTPConnection(gw.up_host, gw.up_port, timeout=3600)
                conn.request(method, path, body=body or None,
                             headers={"Content-Type": "application/json"} if body else {})
                resp = conn.getresponse()
            except OSError:
                raise ApiError(503, "Mesin AI (Ollama) di server sedang mati. Hubungi pemilik server.")
            self.send_response(resp.status)
            for k in ("Content-Type", "Content-Length"):
                if resp.getheader(k):
                    self.send_header(k, resp.getheader(k))
            self.send_header("Connection", "close")
            self.end_headers()
            tail = b""
            try:
                while True:
                    chunk = resp.read1(65536) if hasattr(resp, "read1") else resp.read(65536)
                    if not chunk:
                        break
                    self.wfile.write(chunk)
                    self.wfile.flush()
                    if path == "/api/chat":
                        tail = (tail + chunk)[-8192:]
            finally:
                conn.close()
            if path in ("/api/chat", "/api/embed", "/api/embeddings"):  # embedding dicatat tanpa jumlah token
                stats = {}
                for line in reversed(tail.decode("utf-8", "replace").strip().splitlines()):
                    try:
                        stats = json.loads(line)
                        break
                    except Exception:
                        continue
                store.log_usage({"t": round(t0), "user": user, "ver": self.client_version(), "model": model,
                                 "status": resp.status,
                                 "secs": round(time.time() - t0, 1),
                                 "tokens_in": stats.get("prompt_eval_count") or 0,
                                 "tokens_out": stats.get("eval_count") or 0})

        # ---- admin (hanya dari mesin server)
        def admin(self, method: str, path: str):
            if method == "GET" and path in ("/admin", "/admin/"):
                self.require_admin(api=False)
                raw = ADMIN_HTML.read_bytes()
                self.send_response(200)
                self.send_header("Content-Type", "text/html; charset=utf-8")
                self.send_header("Content-Length", str(len(raw)))
                self.send_header("Cache-Control", "no-store")
                self.send_header("Content-Security-Policy", "default-src 'self'; style-src 'unsafe-inline'; script-src 'unsafe-inline'; img-src 'self' data:")
                self.end_headers()
                return self.wfile.write(raw)
            if method == "GET" and path == "/admin/logo.ico" and LOGO.exists():
                raw = LOGO.read_bytes()
                self.send_response(200)
                self.send_header("Content-Type", "image/x-icon")
                self.send_header("Content-Length", str(len(raw)))
                self.end_headers()
                return self.wfile.write(raw)
            self.require_admin(api=True)
            if method == "GET" and path == "/admin/api/state":
                return self.send_json({**gw.info(), **version_info(), "users": store.list_users()})
            if method == "POST" and path == "/admin/api/settings":
                v = str(self.json_body().get("min_version") or "").strip()
                err = FR.version_error(v, VER.current())
                if err:
                    raise ApiError(400, err, "s-minver")
                store.save_settings({"min_version": v})
                return self.send_json({"ok": True, **version_info()})
            if method == "POST" and path == "/admin/api/users":
                d = self.json_body()
                u, p, p2 = str(d.get("username") or ""), str(d.get("password") or ""), str(d.get("password2") or "")
                err = FR.username_error(u)
                if err:
                    raise ApiError(400, err, "u-name")
                err = FR.password_error(p, u)
                if err:
                    raise ApiError(400, err, "u-pass")
                if p != p2:
                    raise ApiError(400, "Ulangi password belum sama.", "u-pass2")
                store.create_user(u, p)
                return self.send_json({"ok": True})
            m = re.fullmatch(r"/admin/api/users/([^/]+)(?:/(password|active))?", path)
            if m:
                name, what = m.group(1), m.group(2)
                if method == "DELETE" and not what:
                    store.delete_user(name)
                    return self.send_json({"ok": True})
                if method == "POST" and what == "active":
                    store.set_active(name, bool(self.json_body().get("active")))
                    return self.send_json({"ok": True})
                if method == "POST" and what == "password":
                    d = self.json_body()
                    p, p2 = str(d.get("password") or ""), str(d.get("password2") or "")
                    err = FR.password_error(p, name)
                    if err:
                        raise ApiError(400, err, "r-pass")
                    if p != p2:
                        raise ApiError(400, "Ulangi password belum sama.", "r-pass2")
                    store.set_password(name, p)
                    return self.send_json({"ok": True})
            raise ApiError(404, "Alamat tidak dikenal.")

    return Handler


class Server(ThreadingHTTPServer):
    daemon_threads = True
    allow_reuse_address = not sys.platform.startswith("win")  # di Windows SO_REUSEADDR membolehkan program lain merebut port


def bind(port: int, handler) -> Server:
    """Dengar di semua alamat (IPv4+IPv6 bila bisa); penyaringan alamat dilakukan di setiap permintaan."""
    try:
        class Server6(Server):
            address_family = socket.AF_INET6

            def server_bind(self):
                try:
                    self.socket.setsockopt(socket.IPPROTO_IPV6, socket.IPV6_V6ONLY, 0)
                except Exception:
                    pass
                super().server_bind()
        return Server6(("::", port), handler)
    except OSError:
        return Server(("0.0.0.0", port), handler)


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description="Server AI TƎRᗩ")
    ap.add_argument("--port", type=int, default=DEFAULT_PORT)
    ap.add_argument("--no-browser", action="store_true")
    a = ap.parse_args(argv)
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass
    gw = Gateway(a.port, upstream_from_config(), Store())
    try:
        srv = bind(a.port, make_handler(gw))
    except OSError:
        admin = f"http://127.0.0.1:{a.port}/admin"
        print(f"\n[!] Port {a.port} sudah dipakai: Server AI sudah berjalan di jendela lain.")
        if port_open("127.0.0.1", a.port) and not a.no_browser:
            print(f"    Membuka halaman admin yang sudah berjalan: {admin}")
            try:
                import webbrowser
                webbrowser.open(admin)
            except Exception:
                pass
        return 1
    if not gw.ollama_ok():
        print("Menyalakan Ollama...", flush=True)
        start_ollama(gw)
    keep_awake()
    info = gw.info()
    admin = f"http://127.0.0.1:{a.port}/admin"
    print("\n==============================================================")
    print("  Server AI TƎRᗩ berjalan. JANGAN tutup jendela ini.")
    print("==============================================================")
    print(f"  Versi TƎRᗩ: {VER.current()}")
    print(f"  Halaman admin (hanya dari komputer ini): {admin}")
    if info["address"]:
        print(f"  Alamat untuk teman (isi di Pengaturan TƎRᗩ): {info['address']}")
    else:
        print("  [!] Tailscale belum terpasang atau belum masuk. Teman belum bisa terhubung.")
    if not info["ollama"]:
        print("  [!] Ollama belum menyala di komputer ini.")
    if info["ollama_exposed"]:
        print("  [!] PERINGATAN: Ollama terbuka ke jaringan (OLLAMA_HOST=0.0.0.0?). Orang bisa melewati login.")
        print("      Hapus pengaturan OLLAMA_HOST lalu nyalakan ulang Ollama.")
    print("  Untuk mematikan: tekan Ctrl+C atau tutup jendela ini.\n")
    if not a.no_browser:
        try:
            import webbrowser
            webbrowser.open(admin)
        except Exception:
            pass
    try:
        srv.serve_forever()
    except KeyboardInterrupt:
        pass
    return 0
