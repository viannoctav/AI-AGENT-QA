#!/usr/bin/env python3
"""
Dashboard lokal Tera - Asisten QA berbasis AI.

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
            if info.get("finished") and "active_sec" not in info and (d / "events.jsonl").exists():
                info["active_sec"], info["paused_sec"] = active_seconds(d / "events.jsonl")  # riwayat lama
                try:
                    write_json(d / "run.json", info)
                except Exception:
                    pass
            runs.append(info)
    runs.sort(key=lambda r: r.get("started") or r.get("finished") or 0, reverse=True)
    return runs


# kolom Excel -> kunci test case (hasil lama yang JSON-nya belum menyimpan daftar test case)
_XLS_COLS = {
    "tc no.": "tc_no", "module/menu": "module", "sub module/menu": "sub_label", "test case type": "category",
    "test case": "title", "pre-condition": "preconditions", "test steps": "steps", "test data": "test_data",
    "expected result": "expected_result", "requirement id": "requirement_ids", "technique": "technique",
    "priority": "priority", "obligation id": "ob_id", "review flag": "review_flag",
}
_XLS_CACHE = {}


def tcs_from_excel(path):
    """Baca sheet TEST CASES dari Excel hasil generator. Baris judul kelompok (bukan TC-xxx) dilewati."""
    path = Path(path)
    if not path.exists():
        return []
    key = (str(path), path.stat().st_mtime)
    if key in _XLS_CACHE:
        return _XLS_CACHE[key]
    try:
        import openpyxl
        wb = openpyxl.load_workbook(path, read_only=True, data_only=True)
        ws = wb["TEST CASES"] if "TEST CASES" in wb.sheetnames else wb.worksheets[0]
        cols, out = None, []
        for row in ws.iter_rows(values_only=True):
            cells = ["" if v is None else str(v).strip() for v in row]
            if cols is None:
                low = [c.lower() for c in cells]
                if "tc no." in low:
                    cols = {i: _XLS_COLS[c] for i, c in enumerate(low) if c in _XLS_COLS}
                continue
            t = {k: cells[i] if i < len(cells) else "" for i, k in cols.items()}
            if not re.match(r"^[A-Z]+-\d+", t.get("tc_no", "")):
                continue
            t["requirement_ids"] = [x.strip() for x in t.get("requirement_ids", "").split(",") if x.strip()]
            for k in ("preconditions", "steps", "test_data"):
                if t.get(k) == "-":
                    t[k] = ""
            out.append(t)
        wb.close()
    except Exception:
        traceback.print_exc()
        out = []
    _XLS_CACHE.clear()
    _XLS_CACHE[key] = out
    return out


def _art_and_tcs(run_id):
    d = run_dir(run_id)
    art = read_json(d / "artifacts.json", {}) or {}
    tcs = art.get("tcs") or tcs_from_excel(d / "test_cases.xlsx")
    return art, tcs


def run_tcs(run_id):
    return _art_and_tcs(run_id)[1]


def run_review(run_id):
    art, tcs = _art_and_tcs(run_id)
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
            "report": data.get("report", {}), "has_tcs": bool(data.get("tcs")) or bool(excel),
        })
        count += 1
        if verbose:
            print("diimpor:", run_id)
    return count


JUDGE_SEC_DEFAULT = 22      # hanya bila belum ada riwayat: detik per test case untuk AI pemeriksa di akhir
HEAVY_SLOWER_DEFAULT = 2.5  # hanya bila belum ada riwayat: model kasus rumit dibanding model penulis utama


IDLE_GAP = 900  # jeda tanpa kabar > 15 menit = laptop tidur/terhenti, tidak dihitung sebagai waktu kerja


def active_clock(times):
    """Waktu kejadian -> waktu kerja kumulatif (jeda > IDLE_GAP dibuang). Panjang list sama."""
    out, acc, prev = [], 0.0, None
    for t in times:
        if prev is not None:
            dt = t - prev
            acc += dt if 0 <= dt <= IDLE_GAP else 0
        out.append(acc)
        prev = t
    return out


def active_seconds(events_path):
    """(waktu kerja, waktu terjeda) satu proses dari events.jsonl."""
    try:
        times = [json.loads(l).get("time") for l in Path(events_path).read_text(encoding="utf-8").splitlines() if l.strip()]
    except Exception:
        return None, None
    times = [t for t in times if isinstance(t, (int, float))]
    if len(times) < 2:
        return None, None
    act = active_clock(times)[-1]
    return round(act), round(max(0, times[-1] - times[0] - act))


def keep_awake(on):
    """Windows: cegah laptop tidur otomatis selama proses berjalan (layar boleh mati). Tidak mencegah tutup laptop."""
    try:
        import ctypes
        flags = 0x80000000 | (0x00000001 if on else 0)  # ES_CONTINUOUS | ES_SYSTEM_REQUIRED
        ctypes.windll.kernel32.SetThreadExecutionState(flags)
        return True
    except Exception:
        return False


def learned_rates(exclude=None, last=3):
    """Kecepatan nyata laptop ini dari riwayat proses (runs/*/events.jsonl), rata-rata beberapa proses terakhir:
      judge_sec   = detik per test case di tahap AI pemeriksa akhir
      heavy_ratio = berapa kali lebih lambat skenario rumit (model besar) dibanding skenario biasa
    Belum ada riwayat -> nilai bawaan di atas."""
    judge, heavy = [], []
    for d in sorted((p for p in RUNS.iterdir() if p.is_dir() and p.name != exclude), reverse=True):
        try:
            ev = [json.loads(l) for l in (d / "events.jsonl").read_text(encoding="utf-8").splitlines() if l.strip()]
        except Exception:
            continue
        clock = dict(zip(map(id, ev), active_clock([e.get("time") or 0 for e in ev])))  # tanpa jeda laptop tidur
        start = next((e for e in ev if e.get("type") == "stage" and str(e.get("detail", "")).startswith("AI pemeriksa memeriksa")), None)
        marks = [e for e in ev if e.get("type") == "log" and e.get("tag") == "judge" and "diperiksa" in str(e.get("msg", ""))]
        if start and marks:
            m = re.search(r"diperiksa (\d+)/", marks[-1]["msg"])
            span = clock[id(marks[-1])] - clock[id(start)]
            if m and int(m.group(1)) and span > 0:
                judge.append(span / int(m.group(1)))
        hv = next((e for e in ev if e.get("type") == "log" and e.get("tag") == "designer"
                   and re.search(r"(\d+) \(decision/edge\)", str(e.get("msg", "")))), None)
        prog = [(clock[id(e)], e.get("done") or 0, e.get("total") or 0) for e in ev if e.get("type") == "progress"]
        if hv and prog and prog[-1][1] >= prog[-1][2] > 0:
            n_heavy = int(re.search(r"(\d+) \(decision/edge\)", hv["msg"]).group(1))
            split = prog[-1][2] - n_heavy
            t_split = next((t for t, dn, _ in prog if dn >= split), None)
            if n_heavy and split > 0 and t_split and t_split > prog[0][0]:
                light = (t_split - prog[0][0]) / split
                heavy_rate = (prog[-1][0] - t_split) / n_heavy
                if light > 0:
                    heavy.append(heavy_rate / light)
        if len(judge) >= last and len(heavy) >= last:
            break
    avg = lambda xs, dflt: sum(xs[:last]) / len(xs[:last]) if xs else dflt
    return {"judge_sec": avg(judge, JUDGE_SEC_DEFAULT), "heavy_ratio": avg(heavy, HEAVY_SLOWER_DEFAULT)}


RATES = {"judge_sec": JUDGE_SEC_DEFAULT, "heavy_ratio": HEAVY_SLOWER_DEFAULT}  # diperbarui di awal setiap proses


def estimate_eta(samples, done, total, heavy=0, window=6):
    """Sisa waktu (detik) dari kecepatan beberapa kelompok TERAKHIR, bukan sejak awal.
    Waktu memuat model & membaca PRD tidak ikut dihitung (baru mulai dari event progress pertama).
    Skenario rumit di akhir dihitung lebih lambat. None = belum cukup data."""
    if not total or done >= total or len(samples) < 2:
        return None
    recent = samples[-window:]
    (t0, d0), (t1, d1) = recent[0], recent[-1]
    if d1 <= d0 or t1 <= t0:
        return None
    rate = (d1 - d0) / (t1 - t0)
    remaining = total - done
    light_left = max(0, total - heavy - done)
    if light_left > 0:  # masih di fase model utama: sisa skenario rumit diperkirakan lebih lambat
        return round((light_left + (remaining - light_left) * RATES["heavy_ratio"]) / rate)
    return round(remaining / rate)


def estimate_judge_eta(samples, window=4):
    """Sisa waktu tahap AI pemeriksa dari kecepatan beberapa kelompok pemeriksaan terakhir."""
    if len(samples) < 2:
        t, x, y = samples[-1]
        return round((y - x) * RATES["judge_sec"]) if y > x else None
    (t0, x0, _), (t1, x1, y) = samples[-window:][0], samples[-1]
    if x1 >= y:
        return None
    if x1 <= x0 or t1 <= t0:
        return round((y - x1) * RATES["judge_sec"])
    return round((y - x1) / ((x1 - x0) / (t1 - t0)))


def _worker(run_id, prd_file, overrides):
    from run import run_pipeline
    from tools import llm
    from tools.cancel import RunCancelled
    from tools.ui import ui

    d = RUNS / run_id
    info = read_json(d / "run.json")
    log = (d / "events.jsonl").open("a", encoding="utf-8")
    lock = threading.Lock()
    samples = []          # (waktu, jumlah selesai) dari event progress -> kecepatan terbaru
    try:
        RATES.update(learned_rates(exclude=run_id))  # kecepatan nyata laptop ini dari proses sebelumnya
    except Exception:
        pass
    heavy = {"n": 0}      # skenario rumit yang ditulis model besar di akhir (lebih lambat)
    judge = {"planned": 0, "samples": []}  # AI pemeriksa di akhir: jumlah rencana + progres "diperiksa x/y"

    wall = {"prev": None, "acc": 0.0}  # jam kerja: jeda laptop tidur tidak ikut menghitung kecepatan

    def work_time(t):
        if wall["prev"] is not None and 0 <= t - wall["prev"] <= IDLE_GAP:
            wall["acc"] += t - wall["prev"]
        wall["prev"] = t
        return wall["acc"]

    def on_event(e):
        with lock:
            wt = work_time(e.get("time") or time.time())
            if e.get("type") == "log" and e.get("tag") == "designer":
                m = re.search(r"(\d+) \(decision/edge\)", str(e.get("msg", "")))
                if m:
                    heavy["n"] = int(m.group(1))
                m = re.search(r"judge_planned=(\d+)", str(e.get("msg", "")))
                if m:
                    judge["planned"] = int(m.group(1))
            if e.get("type") == "log" and e.get("tag") == "judge":
                m = re.search(r"diperiksa (\d+)/(\d+)", str(e.get("msg", "")))
                if m:
                    judge["samples"].append((wt, int(m.group(1)), int(m.group(2))))
                    eta = estimate_judge_eta(judge["samples"])
                    if eta is not None:
                        info["progress"].update(eta=eta, eta_at=e.get("time"), phase="pemeriksaan")
                        write_json(d / "run.json", info)
                        e["eta"] = eta
            if e.get("type") == "progress":
                samples.append((wt, e.get("done") or 0))
                e["eta"] = estimate_eta(samples, e.get("done") or 0, e.get("total") or 0, heavy["n"])
                if judge["planned"] and not judge["samples"]:  # pemeriksaan di akhir ikut dihitung
                    if e["eta"] is not None:
                        e["eta"] += round(judge["planned"] * RATES["judge_sec"])
                    elif (e.get("done") or 0) >= (e.get("total") or 1):
                        e["eta"] = round(judge["planned"] * RATES["judge_sec"])
            log.write(json.dumps(e, ensure_ascii=False, default=str) + "\n")
            log.flush()
            if e.get("type") == "progress":
                info["progress"] = {k: e.get(k) for k in ("done", "total", "retry", "dropped", "judged", "sources", "eta")}
                info["progress"]["eta_at"] = e.get("time")
                write_json(d / "run.json", info)

    try:
        info["keep_awake"] = keep_awake(True)
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
            target = OUTPUTS / f"{Path(prd_file).stem}_test_cases_v2.xlsx"
            try:
                shutil.copy(d / "test_cases.xlsx", target)
                if (d / "artifacts.json").exists():  # pasangan Excel + JSON di outputs tetap dari proses yang sama
                    shutil.copy(d / "artifacts.json", OUTPUTS / f"{Path(prd_file).stem}_artifacts.json")
            except OSError as e:  # mis. file lama sedang dibuka di Excel -> hasil tetap aman di folder runs
                on_event({"type": "log", "time": time.time(), "tag": "export",
                          "msg": f"gagal menyalin ke {target.name} (tutup file itu di Excel): {e}", "style": "yellow"})
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
        keep_awake(False)
        info["finished"] = time.time()
        log.flush()
        info["active_sec"], info["paused_sec"] = active_seconds(d / "events.jsonl")
        write_json(d / "run.json", info)
        try:
            ui.unsubscribe(on_event)
        except Exception:
            pass
        llm.set_overrides({})
        log.close()
        ACTIVE["id"] = None


def start_run(body):
    if NOTES["status"] == "berjalan":
        raise ApiError(409, "Penyusunan PRD dari catatan masih berjalan. Tunggu sampai selesai.")
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
# ----------------------------------------------------------------------------- catatan QA -> PRD
NOTES = {"status": "idle", "log": [], "result": None, "error": None, "started": None, "finished": None}
_NOTES_FILE = re.compile(r"^[A-Za-z0-9_.-]+_dari_catatan(?:_v\d+)?\.md$")


def _notes_worker(text, name):
    from free_text_to_prd.pipeline import run as notes_run
    try:
        res = notes_run(text, name=name, source_name=f"{name} (ditempel di dashboard)",
                        cb=lambda m: NOTES["log"].append({"time": time.time(), "msg": m}))
        doc = res["document"]
        NOTES["result"] = {
            "prd_file": Path(res["prd_path"]).name, "markdown": res["markdown"],
            "review_file": Path(res["review_path"]).name, "id": res["id"],
            "questions": doc["questions"], "missed_lines": doc["missed_lines"],
            "rejected": [{"pernyataan": r.get("pernyataan"), "kutipan": r.get("kutipan"), "alasan": r.get("alasan")}
                         for r in res["rejected"]],
            "features": len(doc["features"]), "rules": sum(len(f["rules"]) for f in doc["features"]),
        }
        NOTES["status"] = "selesai"
    except Exception as e:
        traceback.print_exc()
        NOTES["error"] = str(e)
        NOTES["status"] = "gagal"
    finally:
        NOTES["finished"] = time.time()
        keep_awake(False)


def start_notes(body):
    text = str(body.get("text") or "")
    name = re.sub(r"\s+", " ", str(body.get("name") or "")).strip()[:80]
    if len(text.strip()) < 20:
        raise ApiError(400, "Catatan terlalu pendek. Tempel catatan QA lengkapnya.")
    if len(text) > 200_000:
        raise ApiError(400, "Catatan terlalu panjang (maksimal sekitar 200 ribu karakter).")
    if not name:
        raise ApiError(400, "Isi nama modul, misalnya \"Berita Acara\".")
    if ACTIVE["id"]:
        raise ApiError(409, "Masih ada proses pembuatan test case yang berjalan. Tunggu sampai selesai.")
    if NOTES["status"] == "berjalan":
        raise ApiError(409, "Penyusunan PRD sebelumnya masih berjalan.")
    if ollama_models() is None:
        raise ApiError(503, "AI lokal (Ollama) belum menyala.")
    NOTES.update({"status": "berjalan", "log": [], "result": None, "error": None,
                  "started": time.time(), "finished": None, "name": name})
    def go():
        keep_awake(True)
        _notes_worker(text, name)
    threading.Thread(target=go, daemon=True).start()
    return {"ok": True}


CONV_DIR = ROOT / "outputs" / "free_text_to_prd"


def _conv_dir(cid):
    d = CONV_DIR / Path(cid).name
    if not cid or not (d / "analysis_metadata.json").is_file():
        raise ApiError(404, "Hasil konversi tidak ditemukan")
    return d


def list_conversions():
    out = []
    if CONV_DIR.is_dir():
        for d in CONV_DIR.iterdir():
            meta = read_json(d / "analysis_metadata.json") if d.is_dir() else None
            if not meta or not meta.get("prd_file"):
                continue
            meta["id"] = d.name
            meta["prd_exists"] = (PRD_DIR / meta["prd_file"]).is_file()
            meta.setdefault("time", (d / "analysis_metadata.json").stat().st_mtime)
            out.append(meta)
    return sorted(out, key=lambda m: m.get("time") or 0, reverse=True)


def conversion_file(cid, kind):
    d = _conv_dir(cid)
    meta = read_json(d / "analysis_metadata.json") or {}
    if kind == "prd":
        f = PRD_DIR / Path(meta.get("prd_file", "")).name
        if not f.is_file():  # PRD sudah dihapus dari daftar -> salinan di folder konversi
            f = d / "prd" / Path(meta.get("prd_file", "")).name
    else:
        f = d / Path(meta.get("review_file", "")).name
        if not f.is_file() or f.suffix != ".pdf":  # konversi lama: buat PDF dari catatan review
            from free_text_to_prd.pdf import markdown_to_pdf
            src = next((p for p in [d / "intermediate" / "catatan_review.md", *d.glob("*_catatan_review.md")] if p.is_file()), None)
            if not src:
                raise ApiError(404, "Catatan review tidak ditemukan")
            f = d / (Path(meta.get("prd_file", "catatan")).stem + "_catatan_review.pdf")
            f.write_bytes(markdown_to_pdf(src.read_text(encoding="utf-8"), f"Catatan Review - {meta.get('module', '')}"))
    if not f.is_file():
        raise ApiError(404, "File tidak ditemukan")
    return f


def delete_conversion(cid):
    if NOTES["status"] == "berjalan":
        raise ApiError(409, "Penyusunan PRD masih berjalan")
    d = _conv_dir(cid)
    meta = read_json(d / "analysis_metadata.json") or {}
    prd = PRD_DIR / Path(meta.get("prd_file", "")).name
    if _NOTES_FILE.match(prd.name) and prd.is_file():
        prd.unlink()
    shutil.rmtree(d, ignore_errors=True)
    if (NOTES.get("result") or {}).get("id") == cid:
        reset_notes()
    return {"ok": True}


def reset_notes():
    if NOTES["status"] == "berjalan":
        raise ApiError(409, "Penyusunan PRD masih berjalan")
    NOTES.update({"status": "idle", "log": [], "result": None, "error": None, "started": None, "finished": None})
    return {"ok": True}


def read_prd(name):
    f = PRD_DIR / Path(name).name
    if not f.is_file() or f.suffix.lower() != ".md":
        raise ApiError(404, "PRD tidak ditemukan")
    return {"file": f.name, "content": f.read_text(encoding="utf-8"), "editable": bool(_NOTES_FILE.match(f.name))}


def save_prd(name, body):
    f = PRD_DIR / Path(name).name
    if not _NOTES_FILE.match(f.name) or not f.is_file():
        raise ApiError(403, "Hanya PRD hasil penyusunan catatan yang bisa diubah dari dashboard.")
    content = body.get("content")
    if not isinstance(content, str) or len(content.strip()) < 20:
        raise ApiError(400, "Isi PRD kosong")
    f.write_text(content.replace("\r\n", "\n"), encoding="utf-8")
    return {"file": f.name, "title": prd_title(f)}


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
route("GET", "/api/notes")(lambda h, q: NOTES)
route("POST", "/api/notes/reset")(lambda h, q: reset_notes())
route("GET", "/api/conversions")(lambda h, q: list_conversions())
route("DELETE", "/api/conversions/(?P<cid>[^/]+)")(lambda h, q, cid: delete_conversion(unquote(cid)))
route("POST", "/api/notes")(lambda h, q: start_notes(h.json_body()))
route("GET", "/api/prds/(?P<name>[^/]+)")(lambda h, q, name: read_prd(unquote(name)))
route("PUT", "/api/prds/(?P<name>[^/]+)")(lambda h, q, name: save_prd(unquote(name), h.json_body()))


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
            m = re.fullmatch(r"/api/conversions/([^/]+)/(review|prd)", path)
            if method == "GET" and m:
                f = conversion_file(unquote(m.group(1)), m.group(2))
                return self.send_file(f, f.name)
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


class QuietServer(ThreadingHTTPServer):
    """Browser sering menutup koneksi cadangan yang belum terpakai (WinError 10053/10054).
    Itu normal dan tidak memengaruhi proses, jadi tidak perlu dicetak sebagai error."""
    daemon_threads = True

    def handle_error(self, request, client_address):
        err = sys.exc_info()[1]
        if isinstance(err, (ConnectionAbortedError, ConnectionResetError, BrokenPipeError, TimeoutError)):
            return
        super().handle_error(request, client_address)


def recover_stale_runs():
    """Run yang tertulis 'berjalan' padahal server baru dinyalakan = terputus saat server mati."""
    for d in RUNS.iterdir():
        info = read_json(d / "run.json") if d.is_dir() else None
        if info and info.get("status") == "berjalan":
            info.update(status="terputus", finished=info.get("finished") or time.time(),
                        error="Server dashboard ditutup saat proses masih berjalan")
            write_json(d / "run.json", info)


def main():
    ap = argparse.ArgumentParser(description="Tera - Asisten QA berbasis AI (dashboard lokal)")
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

    server = QuietServer(("127.0.0.1", args.port), Handler)
    url = f"http://127.0.0.1:{args.port}"
    print(f"Tera berjalan di {url}")
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
