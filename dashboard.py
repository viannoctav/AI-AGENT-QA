#!/usr/bin/env python3
"""
Dashboard lokal AI QA Generator.

Jalankan:   python dashboard.py
Lalu buka:  http://127.0.0.1:8765  (terbuka otomatis)

Tidak butuh paket tambahan: server memakai modul bawaan Python.
Hanya bisa dibuka dari laptop ini (127.0.0.1). Tutup dengan Ctrl+C.

Opsi:
  python dashboard.py --import-outputs   salin hasil lama dari outputs/ ke Riwayat, lalu keluar
  python dashboard.py --port 8800        pakai port lain
  python dashboard.py --no-browser       jangan buka browser otomatis
"""

import argparse
import json
import mimetypes
import re
import shutil
import sys
import threading
import time
import traceback
import webbrowser
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, unquote, urlparse

ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT))

STATIC = ROOT / "dashboard"
RUNS = ROOT / "runs"
PRD_DIR = ROOT / "knowledge" / "prd"
OUTPUTS = ROOT / "outputs"
CONFIG = ROOT / "configs" / "ai.json"
RUNS.mkdir(exist_ok=True)

ACTIVE = {"id": None}
LOCK = threading.Lock()
RUN_ID_RE = re.compile(r"^[A-Za-z0-9_.-]{1,120}$")

# Pengaturan yang boleh diubah dari halaman Pengaturan: nama -> jenis nilai
EDITABLE = {
    "generation_model": str, "judge_model": str, "auto_model": str, "auto_model_kinds": list,
    "judge_enabled": bool, "batch_size": int, "max_attempts": int, "max_obligations": int,
    "num_ctx": int, "think": bool, "dedup": bool,
}


class ApiError(Exception):
    def __init__(self, status, message):
        super().__init__(message)
        self.status = status
        self.message = message


# ----------------------------------------------------------------------------- util
def read_json(path, default=None):
    try:
        return json.loads(Path(path).read_text(encoding="utf-8"))
    except Exception:
        return default


def write_json(path, data):
    tmp = Path(str(path) + ".tmp")
    tmp.write_text(json.dumps(data, ensure_ascii=False, indent=1, default=str), encoding="utf-8")
    tmp.replace(path)


def run_dir(run_id):
    if not RUN_ID_RE.match(run_id or ""):
        raise ApiError(404, "Run tidak ditemukan")
    d = RUNS / run_id
    if not (d / "run.json").exists():
        raise ApiError(404, "Run tidak ditemukan")
    return d


def prd_title(path):
    """Judul ramah dari baris '# ...' pertama di PRD, tanpa awalan 'PRD —'."""
    try:
        for line in Path(path).read_text(encoding="utf-8").splitlines()[:20]:
            if line.startswith("# "):
                t = re.sub(r"^#\s*(PRD\s*[—–:-]\s*)?", "", line).strip()
                return t or Path(path).stem
    except Exception:
        pass
    return Path(path).stem.replace("_", " ")


def settings():
    from tools import llm
    return llm.settings()


# ----------------------------------------------------------------------------- ollama
def ollama_models():
    """Daftar model yang terpasang: [{name, size}] atau None bila Ollama mati."""
    try:
        import ollama
        resp = ollama.list()
        items = resp["models"] if isinstance(resp, dict) else getattr(resp, "models", [])
        out = []
        for m in items:
            get = (lambda k: m.get(k)) if isinstance(m, dict) else (lambda k: getattr(m, k, None))
            name = get("model") or get("name")
            if name:
                out.append({"name": name, "size": get("size") or 0})
        return out
    except Exception:
        return None


def needed_models(cfg):
    need = {"Penulis test case": cfg.get("generation_model")}
    if cfg.get("judge_enabled", True):
        need["Pemeriksa"] = cfg.get("judge_model")
    if cfg.get("auto_model"):
        need["Kasus rumit"] = cfg.get("auto_model")
    return {k: v for k, v in need.items() if v}


def model_names(models):
    have = set()
    for m in models or []:
        have.add(m["name"])
        if m["name"].endswith(":latest"):
            have.add(m["name"][:-7])
    return have


def preflight():
    from tools import llm
    cfg = settings()
    cfg["generation_model"] = llm.generation_model()
    cfg["judge_model"] = llm.judge_model()
    cfg["auto_model"] = llm.auto_model()
    models = ollama_models()
    have = model_names(models)
    need = needed_models(cfg)
    prds = list_prds()
    return {
        "ollama": models is not None,
        "models": [{"role": r, "name": n, "ok": n in have} for r, n in need.items()],
        "missing": sorted({n for n in need.values() if n not in have}),
        "prd_count": len(prds),
        "active_run": ACTIVE["id"],
        "ready": models is not None and all(n in have for n in need.values()) and not ACTIVE["id"] and len(prds) > 0,
    }


# ----------------------------------------------------------------------------- PRD
def list_prds():
    PRD_DIR.mkdir(parents=True, exist_ok=True)
    out = []
    for p in sorted(PRD_DIR.glob("*.md")):
        out.append({"file": p.name, "title": prd_title(p), "size": p.stat().st_size})
    return out


def upload_prd(body):
    name = Path(str(body.get("name") or "")).name
    content = body.get("content")
    if not name.lower().endswith(".md"):
        raise ApiError(400, "File PRD harus berformat .md")
    if not isinstance(content, str) or not content.strip():
        raise ApiError(400, "Isi file kosong")
    if len(content.encode("utf-8")) > 2_000_000:
        raise ApiError(400, "File terlalu besar (maksimal 2 MB)")
    name = re.sub(r"[^A-Za-z0-9_.-]+", "_", name)
    target = PRD_DIR / name
    if target.exists():
        raise ApiError(409, f"Sudah ada PRD bernama {name}")
    target.write_text(content, encoding="utf-8")
    return {"file": name, "title": prd_title(target)}


# ----------------------------------------------------------------------------- runs
def list_runs():
    runs = []
    for d in RUNS.iterdir():
        info = read_json(d / "run.json") if d.is_dir() else None
        if info:
            runs.append(info)
    runs.sort(key=lambda r: r.get("started") or r.get("finished") or 0, reverse=True)
    return runs


def run_tcs(run_id):
    art = read_json(run_dir(run_id) / "artifacts.json", {}) or {}
    return art.get("tcs", [])


def run_review(run_id):
    art = read_json(run_dir(run_id) / "artifacts.json", {}) or {}
    tcs = art.get("tcs", [])
    obs = {o.get("ob_id"): o for o in art.get("obligations", [])}
    return {
        "tcs": [t for t in tcs if t.get("review_flag")],
        "dropped": [{**d, "requirement_ids": obs.get(d.get("ob_id"), {}).get("requirement_ids", [])}
                    for d in art.get("dropped", [])],
        "merged": art.get("dedup_removed", []),
    }


def delete_run(run_id):
    d = run_dir(run_id)
    if ACTIVE["id"] == run_id:
        raise ApiError(409, "Run yang sedang berjalan tidak bisa dihapus")
    shutil.rmtree(d)
    return {"ok": True}


def import_outputs(verbose=True):
    """Salin pasangan *_artifacts.json + Excel dari outputs/ ke runs/ (sekali per file)."""
    count = 0
    for art in OUTPUTS.glob("*_artifacts.json"):
        stem = art.name[: -len("_artifacts.json")]
        stamp = time.strftime("%Y%m%d-%H%M%S", time.localtime(art.stat().st_mtime))
        run_id = f"{stamp}-{re.sub(r'[^A-Za-z0-9]+', '-', stem)[:40].strip('-')}"
        d = RUNS / run_id
        if d.exists():
            continue
        data = read_json(art, {}) or {}
        d.mkdir(parents=True)
        shutil.copy(art, d / "artifacts.json")
        excel = sorted(OUTPUTS.glob(f"{stem}_test_cases*.xlsx"), key=lambda p: p.stat().st_mtime)
        if excel:
            shutil.copy(excel[-1], d / "test_cases.xlsx")
        prd_file = PRD_DIR / f"{stem}.md"
        write_json(d / "run.json", {
            "id": run_id, "prd": f"{stem}.md",
            "prd_title": prd_title(prd_file) if prd_file.exists() else stem.replace("_", " "),
            "status": "selesai", "started": None, "finished": art.stat().st_mtime,
            "imported": True, "models": {}, "overrides": {}, "progress": {},
            "report": data.get("report", {}), "has_tcs": bool(data.get("tcs")),
        })
        count += 1
        if verbose:
            print("diimpor:", run_id)
    return count


def _worker(run_id, prd_file, overrides):
    from run import run_pipeline
    from tools import llm
    from tools.cancel import RunCancelled
    from tools.ui import ui

    d = RUNS / run_id
    info = read_json(d / "run.json")
    log = (d / "events.jsonl").open("a", encoding="utf-8")
    lock = threading.Lock()

    def on_event(e):
        with lock:
            log.write(json.dumps(e, ensure_ascii=False, default=str) + "\n")
            log.flush()
            if e.get("type") == "progress":
                info["progress"] = {k: e.get(k) for k in ("done", "total", "retry", "dropped", "judged", "sources")}
                write_json(d / "run.json", info)

    try:
        llm.set_overrides(overrides)
        info["models"] = {"gen": llm.generation_model(), "auto": llm.auto_model(),
                          "judge": llm.judge_model() if llm.settings().get("judge_enabled", True) else ""}
        write_json(d / "run.json", info)
        ui.configure(plain=True)
        ui.start(info["prd_title"], info["models"]["gen"], info["models"]["judge"], info["models"]["auto"])
        ui.subscribe(on_event)
        final = run_pipeline(str(PRD_DIR / prd_file), str(d), overrides)
        for f in d.glob("*_artifacts.json"):
            f.replace(d / "artifacts.json")
        excel = sorted(d.glob("*_test_cases*.xlsx"))
        if excel:
            excel[-1].replace(d / "test_cases.xlsx")
            OUTPUTS.mkdir(exist_ok=True)
            shutil.copy(d / "test_cases.xlsx", OUTPUTS / f"{Path(prd_file).stem}_test_cases_v2.xlsx")
        info.update(status="selesai", report=final.get("report") or final.get("v2_report") or {}, has_tcs=True)
        on_event({"type": "done", "time": time.time(), "report": info["report"]})
    except RunCancelled:
        info["status"] = "dibatalkan"
        on_event({"type": "cancelled", "time": time.time()})
    except Exception as e:
        info.update(status="gagal", error=str(e))
        traceback.print_exc()
        on_event({"type": "error", "time": time.time(), "message": str(e)})
    finally:
        info["finished"] = time.time()
        write_json(d / "run.json", info)
        try:
            ui.unsubscribe(on_event)
        except Exception:
            pass
        llm.set_overrides({})
        log.close()
        ACTIVE["id"] = None


def start_run(body):
    prd = Path(str(body.get("prd") or "")).name
    cap = body.get("cap")
    if cap not in (None, ""):
        try:
            cap = int(cap)
        except (TypeError, ValueError):
            raise ApiError(400, "Jumlah skenario harus angka")
        if cap < 1:
            raise ApiError(400, "Jumlah skenario minimal 1")
    else:
        cap = None
    models = ollama_models()
    if models is None:
        raise ApiError(409, "Mesin AI lokal belum menyala. Buka aplikasi Ollama, lalu coba lagi.")
    from tools import llm
    cfg = settings()
    cfg.update(generation_model=llm.generation_model(), judge_model=llm.judge_model(), auto_model=llm.auto_model())
    if body.get("no_judge"):
        cfg["judge_enabled"] = False
    missing = sorted({n for n in needed_models(cfg).values() if n not in model_names(models)})
    if missing:
        raise ApiError(409, "Model AI belum terpasang: " + ", ".join(missing) + ". Unduh dengan: ollama pull <nama>")
    with LOCK:
        if ACTIVE["id"]:
            raise ApiError(409, "Masih ada proses yang berjalan. Tunggu sampai selesai atau hentikan dulu.")
        if not (PRD_DIR / prd).is_file() or not prd.endswith(".md"):
            raise ApiError(400, "Dokumen PRD tidak ditemukan")
        overrides = {}
        if cap:
            overrides["max_obligations"] = cap
        if body.get("no_judge"):
            overrides["judge_enabled"] = False
        run_id = f"{time.strftime('%Y%m%d-%H%M%S')}-{re.sub(r'[^A-Za-z0-9]+', '-', Path(prd).stem)[:40].strip('-')}"
        d = RUNS / run_id
        d.mkdir(parents=True)
        info = {"id": run_id, "prd": prd, "prd_title": prd_title(PRD_DIR / prd), "status": "berjalan",
                "started": time.time(), "finished": None, "overrides": overrides, "models": {},
                "progress": {}, "report": {}}
        write_json(d / "run.json", info)
        (d / "events.jsonl").touch()
        ACTIVE["id"] = run_id
    threading.Thread(target=_worker, args=(run_id, prd, overrides), daemon=True).start()
    return info


def cancel_run(run_id):
    from tools import cancel
    run_dir(run_id)
    if ACTIVE["id"] != run_id:
        raise ApiError(409, "Run ini tidak sedang berjalan")
    cancel.CANCEL.set()
    return {"ok": True}


# ----------------------------------------------------------------------------- config
def get_config():
    from tools import llm
    cfg = settings()
    out = {k: cfg.get(k) for k in EDITABLE}
    out["generation_model"] = llm.generation_model()
    out["judge_model"] = llm.judge_model()
    out["auto_model"] = llm.auto_model()
    out["priority_rule"] = cfg.get("priority_rule")
    return out


def put_config(values):
    if ACTIVE["id"]:
        raise ApiError(409, "Tunggu proses selesai sebelum mengubah pengaturan")
    if not isinstance(values, dict):
        raise ApiError(400, "Format pengaturan tidak valid")
    data = read_json(CONFIG)
    if data is None:
        raise ApiError(500, "configs/ai.json tidak bisa dibaca. Pulihkan dari configs/ai.json.bak")
    v2 = data.setdefault("v2", {})
    for k, v in values.items():
        kind = EDITABLE.get(k)
        if kind is None:
            raise ApiError(400, f"Pengaturan '{k}' tidak dikenal")
        if k == "max_obligations" and v is None:
            v2[k] = None
            continue
        if not isinstance(v, kind) or (kind is int and isinstance(v, bool)):
            raise ApiError(400, f"Nilai '{k}' tidak sesuai jenisnya")
        if kind is int and v < 1:
            raise ApiError(400, f"Nilai '{k}' minimal 1")
        if kind is list and not all(isinstance(x, str) for x in v):
            raise ApiError(400, f"Nilai '{k}' tidak valid")
        v2[k] = v
    shutil.copy(CONFIG, CONFIG.with_suffix(".json.bak"))
    CONFIG.write_text(json.dumps(data, indent=2, ensure_ascii=False), encoding="utf-8")
    return {"ok": True}


def models_info():
    cfg = get_config()
    use = {}
    for label, key in (("Menulis test case", "generation_model"), ("Memeriksa ulang", "judge_model"),
                       ("Kasus rumit", "auto_model")):
        if cfg.get(key):
            use.setdefault(cfg[key], []).append(label)
    from tools.ai_config import ollama_settings
    try:
        emb = ollama_settings().get("embedding_model")
    except Exception:
        emb = None
    if emb:
        use.setdefault(emb, []).append("Mencari contoh test case perusahaan")
    models = ollama_models()
    return {"ollama": models is not None,
            "models": [{**m, "use": use.get(m["name"]) or use.get(m["name"].replace(":latest", "")) or []}
                       for m in (models or [])]}


# ----------------------------------------------------------------------------- overview
def overview():
    runs = list_runs()
    done = [r for r in runs if r.get("status") == "selesai"]
    active = read_json(RUNS / ACTIVE["id"] / "run.json") if ACTIVE["id"] else None
    last = done[0] if done else None
    trend = []
    if last:
        same = [r for r in done if r.get("prd") == last.get("prd")][:6]
        trend = [{"id": r["id"], "finished": r.get("finished"),
                  "needs_review": (r.get("report") or {}).get("needs_review"),
                  "test_cases": (r.get("report") or {}).get("test_cases")} for r in reversed(same)]
    return {"active": active, "last": last, "trend": trend, "run_count": len(runs), "preflight": preflight()}


# ----------------------------------------------------------------------------- HTTP
ROUTES = []


def route(method, pattern):
    def deco(fn):
        ROUTES.append((method, re.compile(f"^{pattern}$"), fn))
        return fn
    return deco


route("GET", "/api/overview")(lambda h, q: overview())
route("GET", "/api/preflight")(lambda h, q: preflight())
route("GET", "/api/prds")(lambda h, q: list_prds())
route("POST", "/api/prds")(lambda h, q: upload_prd(h.json_body()))
route("GET", "/api/runs")(lambda h, q: list_runs())
route("POST", "/api/runs")(lambda h, q: start_run(h.json_body()))
route("GET", "/api/runs/(?P<run_id>[^/]+)")(lambda h, q, run_id: read_json(run_dir(run_id) / "run.json"))
route("DELETE", "/api/runs/(?P<run_id>[^/]+)")(lambda h, q, run_id: delete_run(run_id))
route("GET", "/api/runs/(?P<run_id>[^/]+)/tcs")(lambda h, q, run_id: run_tcs(run_id))
route("GET", "/api/runs/(?P<run_id>[^/]+)/review")(lambda h, q, run_id: run_review(run_id))
route("POST", "/api/runs/(?P<run_id>[^/]+)/cancel")(lambda h, q, run_id: cancel_run(run_id))
route("GET", "/api/config")(lambda h, q: get_config())
route("PUT", "/api/config")(lambda h, q: put_config(h.json_body()))
route("GET", "/api/models")(lambda h, q: models_info())


class Handler(BaseHTTPRequestHandler):
    server_version = "AIQADashboard/1.0"

    def log_message(self, fmt, *args):  # tidak membanjiri terminal
        pass

    # ---- helpers
    def json_body(self):
        n = int(self.headers.get("Content-Length") or 0)
        if n > 3_000_000:
            raise ApiError(413, "Permintaan terlalu besar")
        try:
            return json.loads(self.rfile.read(n).decode("utf-8") or "{}")
        except Exception:
            raise ApiError(400, "Format data tidak valid")

    def send_json(self, data, status=200):
        raw = json.dumps(data, ensure_ascii=False, default=str).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(raw)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(raw)

    def send_file(self, path, download_name=None):
        ctype = mimetypes.guess_type(str(path))[0] or "application/octet-stream"
        if ctype.startswith("text/") or ctype in ("application/javascript", "application/json"):
            ctype += "; charset=utf-8"
        data = Path(path).read_bytes()
        self.send_response(200)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(data)))
        self.send_header("Cache-Control", "no-store")
        if download_name:
            self.send_header("Content-Disposition", f'attachment; filename="{download_name}"')
        self.end_headers()
        self.wfile.write(data)

    # ---- dispatch
    def handle_any(self, method):
        url = urlparse(self.path)
        path = unquote(url.path)
        query = parse_qs(url.query)
        try:
            m = re.match(r"^/api/runs/([^/]+)/events$", path)
            if method == "GET" and m:
                return self.stream_events(m.group(1))
            m = re.match(r"^/api/runs/([^/]+)/files/(test_cases\.xlsx|artifacts\.json)$", path)
            if method == "GET" and m:
                d = run_dir(m.group(1))
                f = d / m.group(2)
                if not f.exists():
                    raise ApiError(404, "File tidak ditemukan untuk run ini")
                info = read_json(d / "run.json", {})
                stem = Path(info.get("prd", "hasil")).stem
                return self.send_file(f, f"{stem}_{m.group(2)}")
            if path.startswith("/api/"):
                for meth, rx, fn in ROUTES:
                    mm = rx.match(path)
                    if meth == method and mm:
                        return self.send_json(fn(self, query, **mm.groupdict()))
                raise ApiError(404, "Alamat tidak dikenal")
            if method != "GET":
                raise ApiError(405, "Metode tidak didukung")
            return self.serve_static(path)
        except ApiError as e:
            self.send_json({"detail": e.message}, e.status)
        except (BrokenPipeError, ConnectionResetError):
            pass
        except Exception as e:
            traceback.print_exc()
            try:
                self.send_json({"detail": f"Terjadi kesalahan di server: {e}"}, 500)
            except Exception:
                pass

    def serve_static(self, path):
        rel = "index.html" if path in ("", "/") else path.lstrip("/")
        f = (STATIC / rel).resolve()
        if STATIC.resolve() not in f.parents and f != STATIC.resolve():
            raise ApiError(404, "Tidak ditemukan")
        if not f.is_file():
            raise ApiError(404, "Halaman tidak ditemukan")
        self.send_file(f)

    def stream_events(self, run_id):
        d = run_dir(run_id)
        f = d / "events.jsonl"
        try:
            start = int(self.headers.get("Last-Event-ID") or 0)
        except ValueError:
            start = 0
        self.send_response(200)
        self.send_header("Content-Type", "text/event-stream; charset=utf-8")
        self.send_header("Cache-Control", "no-store")
        self.send_header("Connection", "keep-alive")
        self.end_headers()
        sent, pos, idle = start, 0, 0
        try:
            while True:
                lines = []
                if f.exists():
                    with f.open(encoding="utf-8") as fh:
                        fh.seek(pos)
                        chunk = fh.read()
                        if chunk:
                            complete = chunk[: chunk.rfind("\n") + 1]
                            pos += len(complete.encode("utf-8"))
                            lines = [x for x in complete.split("\n") if x.strip()]
                for line in lines:
                    sent_idx = sent
                    sent += 1
                    if sent_idx < start:
                        continue
                    self.wfile.write(f"id: {sent}\ndata: {line}\n\n".encode("utf-8"))
                if lines:
                    self.wfile.flush()
                    idle = 0
                if ACTIVE["id"] != run_id and not lines:
                    self.wfile.write(b"event: end\ndata: {}\n\n")
                    self.wfile.flush()
                    return
                idle += 1
                if idle % 15 == 0:
                    self.wfile.write(b": tetap terhubung\n\n")
                    self.wfile.flush()
                time.sleep(1)
        except (BrokenPipeError, ConnectionResetError, ConnectionAbortedError):
            return

    def do_GET(self):
        self.handle_any("GET")

    def do_POST(self):
        self.handle_any("POST")

    def do_PUT(self):
        self.handle_any("PUT")

    def do_DELETE(self):
        self.handle_any("DELETE")


def recover_stale_runs():
    """Run yang tertulis 'berjalan' padahal server baru dinyalakan = terputus saat server mati."""
    for d in RUNS.iterdir():
        info = read_json(d / "run.json") if d.is_dir() else None
        if info and info.get("status") == "berjalan":
            info.update(status="terputus", finished=info.get("finished") or time.time(),
                        error="Server dashboard ditutup saat proses masih berjalan")
            write_json(d / "run.json", info)


def main():
    ap = argparse.ArgumentParser(description="Dashboard lokal AI QA Generator")
    ap.add_argument("--port", type=int, default=8765)
    ap.add_argument("--no-browser", action="store_true")
    ap.add_argument("--import-outputs", action="store_true")
    args = ap.parse_args()

    if args.import_outputs:
        n = import_outputs()
        print(f"{n} hasil diimpor ke folder runs/.")
        return
    recover_stale_runs()
    if not any(RUNS.iterdir()):
        import_outputs(verbose=False)

    server = ThreadingHTTPServer(("127.0.0.1", args.port), Handler)
    server.daemon_threads = True
    url = f"http://127.0.0.1:{args.port}"
    print(f"Dashboard berjalan di {url}")
    print("Biarkan jendela ini terbuka selama dashboard dipakai. Tekan Ctrl+C untuk menutup.")
    if not args.no_browser:
        threading.Timer(1.2, lambda: webbrowser.open(url)).start()
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\nDashboard ditutup.")
    finally:
        server.server_close()


if __name__ == "__main__":
    main()
