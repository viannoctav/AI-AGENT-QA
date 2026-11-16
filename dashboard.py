#!/usr/bin/env python3
"""
Dashboard lokal TƎRᗩ - Asisten QA berbasis AI.

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
from urllib.parse import parse_qs, quote, unquote, urlparse

ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT))

from tools import form_rules as FR  # noqa: E402  aturan validasi isian (sama dengan dashboard/app.js)
from tools import ai_source  # noqa: E402  AI di laptop ini atau Server AI bersama
from tools import version as VER  # noqa: E402  nomor versi TƎRᗩ dan catatan perubahan

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
    def __init__(self, status, message, field=None):
        super().__init__(message)
        self.status = status
        self.message = message
        self.field = field  # id isian di dashboard yang salah, supaya error tampil tepat di bawahnya


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
    """Daftar model yang terpasang: [{name, size}] atau None bila AI tidak bisa dihubungi."""
    return ai_source.probe()[0]


def ai_problem_text(problem):
    if ai_source.is_server():
        return {"login": "Belum masuk ke Server AI bersama atau sesi login habis. Masuk lagi di Pengaturan > Sumber AI.",
                "ditolak": "Server AI bersama menolak laptop ini. Pastikan Tailscale menyala dan sudah masuk.",
                "versi": "Versi TƎRᗩ di laptop ini terlalu lama untuk Server AI bersama. Minta folder TƎRᗩ terbaru ke pemilik server."}.get(
            problem, "Server AI bersama tidak bisa dihubungi. Pastikan Tailscale menyala dan Server AI temanmu berjalan.")
    return "Mesin AI lokal belum menyala. Buka aplikasi Ollama, lalu coba lagi."


def require_ai():
    models, problem = ai_source.probe()
    if models is None:
        raise ApiError(409 if problem else 503, ai_problem_text(problem))
    return models


def ai_state():
    """(model, info sumber AI) dalam satu pemeriksaan."""
    models, problem = ai_source.probe()
    return models, {**ai_source.status(), "problem": problem}


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
    models, source = ai_state()
    have = model_names(models)
    need = needed_models(cfg)
    prds = list_prds()
    return {
        "ollama": models is not None,
        "source": source,
        "reference": vault_info(),
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


def delete_prd(name):
    """Hapus file PRD dari knowledge/prd. Hasil test case dan salinan PRD di folder hasil konversi tidak ikut terhapus."""
    f = PRD_DIR / Path(name).name
    if not f.is_file() or f.suffix.lower() != ".md":
        raise ApiError(404, "Dokumen PRD tidak ditemukan (mungkin sudah dihapus dari folder).")
    if ACTIVE["id"]:
        info = read_json(RUNS / ACTIVE["id"] / "run.json") or {}
        if info.get("prd") == f.name:
            raise ApiError(409, "Dokumen ini sedang dipakai proses yang berjalan.")
    f.unlink()
    note = ""
    if _NOTES_FILE.match(f.name):
        note = "Salinannya masih ada di Riwayat (hasil konversi) dan bisa diunduh lagi."
    return {"ok": True, "note": note}


def upload_prd(body):
    name = Path(str(body.get("name") or "")).name
    content = body.get("content")
    if not name.lower().endswith(".md"):
        raise ApiError(400, "File PRD harus berformat .md", "prd-file")
    err = FR.prd_content_error(content)
    if err:
        raise ApiError(400, err, "prd-file")
    name = re.sub(r"[^A-Za-z0-9_.-]+", "_", name)
    if not re.search(r"[A-Za-z0-9]", Path(name).stem):
        raise ApiError(400, "Nama file PRD harus mengandung huruf atau angka.", "prd-file")
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
    if COMPARE["status"] == "berjalan":
        raise ApiError(409, "Bandingkan test case masih berjalan. Tunggu sampai selesai.")
    if NOTES["status"] == "berjalan":
        raise ApiError(409, "Penyusunan PRD dari catatan masih berjalan. Tunggu sampai selesai.")
    if DESIGN["status"] == "berjalan":
        raise ApiError(409, "Penyusunan PRD dari desain masih berjalan. Tunggu sampai selesai.")
    prd = Path(str(body.get("prd") or "")).name
    if not prd:
        raise ApiError(400, "Pilih dokumen PRD dulu.", "prd-select")
    if not prd.lower().endswith(".md") or not (PRD_DIR / prd).is_file():
        raise ApiError(400, "Dokumen PRD tidak ditemukan. Muat ulang halaman lalu pilih lagi.", "prd-select")
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
    models = require_ai()
    from tools import llm
    cfg = settings()
    cfg.update(generation_model=llm.generation_model(), judge_model=llm.judge_model(), auto_model=llm.auto_model())
    if body.get("no_judge"):
        cfg["judge_enabled"] = False
    missing = sorted({n for n in needed_models(cfg).values() if n not in model_names(models)})
    if missing:
        if ai_source.is_server():
            raise ApiError(409, "Model AI belum ada di Server AI bersama: " + ", ".join(missing)
                           + ". Minta pemilik server mengunduhnya, atau pilih model lain di Pengaturan.")
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
    if "generation_model" in values and not str(values.get("generation_model") or "").strip():
        raise ApiError(400, "Pilih AI penulis test case.", "c-gen")
    if "judge_model" in values and not str(values.get("judge_model") or "").strip():
        raise ApiError(400, "Pilih AI pemeriksa.", "c-judge")
    if str(values.get("auto_model") or "").strip() and "auto_model_kinds" in values and not values["auto_model_kinds"]:
        raise ApiError(400, "AI kasus rumit dipilih, jadi centang minimal satu pemakaiannya.", "c-kinds")
    fields = {"batch_size": "c-bs", "max_attempts": "c-ma", "max_obligations": "c-mo", "num_ctx": "c-ctx"}
    for k, fid in fields.items():
        if k in values:
            err = FR.number_error(k, values[k])
            if err:
                raise ApiError(400, err, fid)
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
    models, source = ai_state()
    return {"ollama": models is not None, "source": source,
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
_NOTES_FILE = re.compile(r"^[A-Za-z0-9_.-]+_dari_(?:catatan|desain)(?:_v\d+)?\.md$")  # PRD hasil konversi


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
    raw_name = str(body.get("name") or "")
    err = FR.name_error(raw_name)
    if err:
        raise ApiError(400, err, "nt-name")
    err = FR.notes_error(text)
    if err:
        raise ApiError(400, err, "nt-text")
    name = re.sub(r"\s+", " ", raw_name).strip()
    if ACTIVE["id"]:
        raise ApiError(409, "Masih ada proses pembuatan test case yang berjalan. Tunggu sampai selesai.")
    if NOTES["status"] == "berjalan":
        raise ApiError(409, "Penyusunan PRD sebelumnya masih berjalan.")
    if DESIGN["status"] == "berjalan":
        raise ApiError(409, "Penyusunan PRD dari desain masih berjalan. Tunggu sampai selesai.")
    if COMPARE["status"] == "berjalan":
        raise ApiError(409, "Bandingkan test case masih berjalan. Tunggu sampai selesai.")
    require_ai()
    NOTES.update({"status": "berjalan", "log": [], "result": None, "error": None,
                  "started": time.time(), "finished": None, "name": name})
    def go():
        keep_awake(True)
        _notes_worker(text, name)
    threading.Thread(target=go, daemon=True).start()
    return {"ok": True}


CONV_DIR = ROOT / "outputs" / "free_text_to_prd"
DESIGN_DIR = ROOT / "outputs" / "design_to_prd"
CONV_DIRS = {"catatan": CONV_DIR, "desain": DESIGN_DIR}


def _conv_dir(cid):
    for base in CONV_DIRS.values():
        d = base / Path(str(cid)).name
        if cid and (d / "analysis_metadata.json").is_file():
            return d
    raise ApiError(404, "Hasil konversi tidak ditemukan")


def list_conversions():
    out = []
    for kind, base in CONV_DIRS.items():
        if not base.is_dir():
            continue
        for d in base.iterdir():
            meta = read_json(d / "analysis_metadata.json") if d.is_dir() else None
            if not meta or not meta.get("prd_file"):
                continue
            meta["id"] = d.name
            meta["kind"] = meta.get("kind") or kind
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
    if NOTES["status"] == "berjalan" or DESIGN["status"] == "berjalan":
        raise ApiError(409, "Penyusunan PRD masih berjalan")
    d = _conv_dir(cid)
    meta = read_json(d / "analysis_metadata.json") or {}
    prd = PRD_DIR / Path(meta.get("prd_file", "")).name
    if _NOTES_FILE.match(prd.name) and prd.is_file():
        prd.unlink()
    shutil.rmtree(d, ignore_errors=True)
    if (NOTES.get("result") or {}).get("id") == cid:
        reset_notes()
    if (DESIGN.get("result") or {}).get("id") == cid:
        reset_design()
    return {"ok": True}


def reset_notes():
    if NOTES["status"] == "berjalan":
        raise ApiError(409, "Penyusunan PRD masih berjalan")
    NOTES.update({"status": "idle", "log": [], "result": None, "error": None, "started": None, "finished": None})
    return {"ok": True}


# ----------------------------------------------------------------------------- desain (gambar) -> PRD
DESIGN = {"status": "idle", "log": [], "result": None, "error": None, "started": None, "finished": None, "progress": {}}
UPLOADS = DESIGN_DIR / "_unggahan"
_UPLOAD_ID = re.compile(r"^[a-f0-9]{24}\.(?:png|jpg|jpeg|webp)$")
IMAGE_EXT = {"png", "jpg", "jpeg", "webp"}


def ocr_available():
    return sys.platform.startswith("win")


def _clean_uploads(max_age=2 * 86400):
    if UPLOADS.is_dir():
        for f in UPLOADS.iterdir():
            try:
                if time.time() - f.stat().st_mtime > max_age:
                    f.unlink()
            except OSError:
                pass


def upload_design_image(body):
    """Satu gambar per permintaan (base64). Dicek dengan Pillow, lalu dihitung jumlah layarnya untuk estimasi."""
    import base64
    import secrets
    name = Path(str(body.get("name") or "gambar.png")).name[:120]
    ext = name.rsplit(".", 1)[-1].lower() if "." in name else ""
    err = FR.image_name_error(name)
    if err:
        raise ApiError(400, err)
    data = str(body.get("data") or "")
    data = data.split(",", 1)[1] if data.startswith("data:") else data
    try:
        raw = base64.b64decode(data, validate=False)
    except Exception:
        raise ApiError(400, f"{name}: gambar tidak terbaca.")
    err = FR.image_size_error(name, len(raw))
    if err:
        raise ApiError(400, err)
    UPLOADS.mkdir(parents=True, exist_ok=True)
    _clean_uploads()
    fid = f"{secrets.token_hex(12)}.{ext}"
    f = UPLOADS / fid
    f.write_bytes(raw)
    try:
        from design_to_prd.images import count_screens, load  # juga membuka batas ukuran gambar besar
        from PIL import Image
        with Image.open(f) as im:
            im.verify()
        size = load(f).size
        err = FR.image_size_error(name, len(raw), *size)
        if err:
            raise ValueError(err)
        screens = count_screens(f)
    except ImportError as e:
        f.unlink(missing_ok=True)
        raise ApiError(500, f"Komponen pengolah gambar (Pillow) tidak ditemukan oleh Python yang menjalankan TƎRᗩ "
                            f"({sys.executable}). Jalankan TƎRᗩ lewat Jalankan_Tera.bat, atau pasang dengan: "
                            f"\"{sys.executable}\" -m pip install pillow. Detail: {e}")
    except ValueError as e:
        f.unlink(missing_ok=True)
        raise ApiError(400, str(e) if str(e).startswith(name) else f"{name}: rusak atau bukan gambar.")
    except Exception as e:
        f.unlink(missing_ok=True)
        raise ApiError(400, f"{name}: rusak atau bukan gambar ({type(e).__name__}).")
    return {"id": fid, "name": name, "screens": screens, "width": size[0], "height": size[1]}


def _design_worker(cards, extra, name, resume=None):
    from design_to_prd.pipeline import run as design_run
    try:
        res = design_run(cards, extra=extra, name=name, progress=DESIGN["progress"], resume=resume,
                         cb=lambda m: DESIGN["log"].append({"time": time.time(), "msg": m}))
        doc = res["document"]
        DESIGN["result"] = {
            "prd_file": Path(res["prd_path"]).name, "markdown": res["markdown"],
            "review_file": Path(res["review_path"]).name, "id": res["id"], "kind": "desain",
            "questions": doc["questions"],
            "missed_lines": [{"baris": m["baris"], "teks": f"{m['teks']} (penjelasan {m['sumber']})"} for m in doc["missed_lines"]],
            "rejected": [{"pernyataan": r.get("pernyataan"), "kutipan": r.get("kutipan"), "alasan": r.get("alasan")}
                         for r in res["rejected"]],
            "features": len(doc["features"]), "rules": sum(len(f["rules"]) for f in doc["features"]),
            "stats": res["stats"],
        }
        DESIGN["status"] = "selesai"
    except Exception as e:
        traceback.print_exc()
        DESIGN["error"] = str(e)
        DESIGN["status"] = "gagal"
    finally:
        DESIGN["finished"] = time.time()
        keep_awake(False)
        for c in cards:  # gambar unggahan sudah disalin ke folder hasil
            for im in c.get("images") or []:
                Path(im["path"]).unlink(missing_ok=True)


def design_interrupted():
    """Penyusunan PRD desain yang terhenti (mati di tengah / ditutup) dan masih bisa dilanjut per fitur."""
    from design_to_prd.pipeline import interrupted
    return {"items": interrupted() if DESIGN["status"] != "berjalan" else []}


def discard_design(body):
    from design_to_prd.pipeline import discard
    if DESIGN["status"] == "berjalan":
        raise ApiError(409, "Penyusunan PRD masih berjalan. Tunggu sampai selesai.")
    if not discard(str((body or {}).get("id") or "")):
        raise ApiError(404, "Proses terhenti itu sudah tidak ada.")
    return {"ok": True}


def resume_design(body):
    """Lanjutkan proses yang terhenti: fitur yang sudah selesai tidak dibaca ulang."""
    from design_to_prd.pipeline import interrupted
    rid = Path(str((body or {}).get("id") or "")).name
    item = next((x for x in interrupted() if x["id"] == rid), None)
    if not item:
        raise ApiError(404, "Proses terhenti itu sudah tidak ada. Susun ulang dari awal.")
    _design_busy_check()
    require_ai()
    DESIGN.update({"status": "berjalan", "log": [], "result": None, "error": None, "progress": {},
                   "started": time.time(), "finished": None, "name": item["nama"]})

    def go():
        keep_awake(True)
        _design_worker([], "", item["nama"], resume=rid)
    threading.Thread(target=go, daemon=True).start()
    return {"ok": True}


def _design_busy_check():
    if ACTIVE["id"]:
        raise ApiError(409, "Masih ada proses pembuatan test case yang berjalan. Tunggu sampai selesai.")
    if NOTES["status"] == "berjalan" or DESIGN["status"] == "berjalan":
        raise ApiError(409, "Masih ada penyusunan PRD yang berjalan. Tunggu sampai selesai.")
    if COMPARE["status"] == "berjalan":
        raise ApiError(409, "Bandingkan test case masih berjalan. Tunggu sampai selesai.")


def start_design(body):
    raw_name = str(body.get("name") or "")
    err = FR.name_error(raw_name)
    if err:
        raise ApiError(400, err, "dz-name")
    name = re.sub(r"\s+", " ", raw_name).strip()
    extra = str(body.get("extra") or "")
    err = FR.optional_text_error(extra, "Deskripsi tambahan")
    if err:
        raise ApiError(400, err, "dz-extra")
    raw_cards = [c for c in (body.get("cards") or []) if isinstance(c, dict)]
    names = [str(c.get("nama") or "") for c in raw_cards]
    dups = set(FR.duplicate_names(names))
    cards, used = [], set()
    for i, c in enumerate(raw_cards, 1):
        key = c.get("key", i)
        teks = str(c.get("teks") or "")
        nama = re.sub(r"\s+", " ", str(c.get("nama") or "")).strip()
        has_img = bool(c.get("images"))
        if not nama and not teks.strip() and not has_img:
            continue  # kartu kosong diabaikan
        err = FR.name_error(nama, f"Nama halaman / fitur ke-{i}")
        if err:
            raise ApiError(400, err, f"dn-{key}")
        if i - 1 in dups:
            raise ApiError(400, f"Nama halaman / fitur ke-{i} sama dengan halaman sebelumnya. Pakai nama yang berbeda.", f"dn-{key}")
        err = FR.optional_text_error(teks, f"Penjelasan halaman ke-{i}")
        if err:
            raise ApiError(400, err, f"dt-{key}")
        if not teks.strip() and not has_img:
            raise ApiError(400, f"Halaman ke-{i} belum berisi gambar atau penjelasan. Tambahkan salah satunya, atau hapus kartu ini.", f"di-{key}")
        images = []
        for im in c.get("images") or []:
            fid = Path(str((im or {}).get("id") or "")).name
            if not _UPLOAD_ID.match(fid) or not (UPLOADS / fid).is_file():
                raise ApiError(400, "Ada gambar yang belum selesai diunggah atau sudah kedaluwarsa. Tambahkan ulang gambarnya.")
            nm = Path(str(im.get("name") or fid)).name
            stem, ext, k = Path(nm).stem, Path(nm).suffix or "." + fid.rsplit(".", 1)[-1], 2
            while nm.lower() in used:  # nama file kembar antar gambar -> diberi nomor
                nm = f"{stem}_{k}{ext}"
                k += 1
            used.add(nm.lower())
            images.append({"path": str(UPLOADS / fid), "name": nm})
        cards.append({"nama": nama, "teks": teks, "images": images})
    if not cards:
        raise ApiError(400, "Isi minimal satu halaman/fitur dengan gambar atau penjelasan.", "dz-cards")
    if sum(len(c["teks"]) for c in cards) + len(extra) > FR.DESIGN_TOTAL_MAX:
        raise ApiError(400, "Total penjelasan terlalu panjang (maksimal 200.000 karakter).", "dz-extra")
    if any(c["images"] for c in cards) and not ocr_available():
        raise ApiError(400, "Membaca teks gambar memakai fitur bawaan Windows, jadi hanya bisa di laptop Windows.")
    _design_busy_check()
    require_ai()
    DESIGN.update({"status": "berjalan", "log": [], "result": None, "error": None, "progress": {},
                   "started": time.time(), "finished": None, "name": name})

    def go():
        keep_awake(True)
        _design_worker(cards, extra, name)
    threading.Thread(target=go, daemon=True).start()
    return {"ok": True}


def reset_design():
    if DESIGN["status"] == "berjalan":
        raise ApiError(409, "Penyusunan PRD masih berjalan")
    DESIGN.update({"status": "idle", "log": [], "result": None, "error": None, "started": None, "finished": None})
    return {"ok": True}


def read_prd(name):
    f = PRD_DIR / Path(name).name
    if not f.is_file() or f.suffix.lower() != ".md":
        raise ApiError(404, "PRD tidak ditemukan")
    return {"file": f.name, "content": f.read_text(encoding="utf-8"), "editable": bool(_NOTES_FILE.match(f.name))}


def save_prd(name, body):
    f = PRD_DIR / Path(name).name
    if not _NOTES_FILE.match(f.name) or not f.is_file():
        raise ApiError(403, "Hanya PRD hasil konversi (catatan atau desain) yang bisa diubah dari dashboard.")
    content = body.get("content")
    err = FR.prd_content_error(content)
    if err:
        raise ApiError(400, err, "nr-md")
    f.write_text(content.replace("\r\n", "\n"), encoding="utf-8")
    return {"file": f.name, "title": prd_title(f)}


# ----------------------------------------------------------------------------- Bandingkan test case
COMPARE = {"status": "idle", "log": [], "result": None, "error": None, "started": None, "finished": None,
           "progress": {}, "name": None, "mode": None}
COMPARE_DIR = ROOT / "outputs" / "tc_compare"
COMPARE_UPLOADS = {}  # token -> {name, tcs, mapping, missing, time}; hanya di memori, tidak disimpan


def compare_sources():
    """Hasil run yang selesai (bisa dipilih sebagai A atau B)."""
    out = []
    for r in list_runs():
        if r.get("status") != "selesai" or not (RUNS / r["id"] / "artifacts.json").exists() and not (RUNS / r["id"] / "test_cases.xlsx").exists():
            continue
        out.append({"id": r["id"], "title": r.get("prd_title") or r.get("prd"), "prd": r.get("prd"),
                    "finished": r.get("finished"), "test_cases": (r.get("report") or {}).get("test_cases")})
    return out


def compare_info():
    models = ai_source.probe()[0]
    from tools import embed
    return {**COMPARE, "now": time.time(), "ai": models is not None,
            "embed": embed.available(models), "embed_model": embed.model_name()}


def compare_upload(body):
    import base64
    import secrets
    from tc_compare.loader import LoadError, LABELS, load_upload, missing_fields
    name = Path(str(body.get("name") or "")).name[:120]
    field = "cmp-file-" + ("b" if body.get("side") == "b" else "a")
    data = str(body.get("data") or "")
    data = data.split(",", 1)[1] if data.startswith("data:") else data
    try:
        raw = base64.b64decode(data, validate=False)
    except Exception:
        raise ApiError(400, f"{name}: file tidak terbaca.", field)
    err = FR.compare_file_error(name or "file", len(raw))
    if err:
        raise ApiError(400, err, field)
    try:
        tcs, mapping = load_upload(name, raw)
    except LoadError as e:
        raise ApiError(400, str(e), field)
    while len(COMPARE_UPLOADS) >= 10:  # simpan maksimal 10 unggahan terakhir di memori
        COMPARE_UPLOADS.pop(min(COMPARE_UPLOADS, key=lambda k: COMPARE_UPLOADS[k]["time"]))
    token = secrets.token_hex(12)
    COMPARE_UPLOADS[token] = {"name": name, "tcs": tcs, "missing": missing_fields(tcs), "time": time.time()}
    cols = [f"{LABELS[f]} = {c}" for f, c in mapping.items() if not f.startswith("_") and f in LABELS]
    return {"token": token, "name": name, "count": len(tcs), "columns": cols, "sheet": mapping.get("_sheet"),
            "missing": COMPARE_UPLOADS[token]["missing"]}


def _compare_side(spec, side):
    from tc_compare.loader import LoadError, load_run, missing_fields
    S_ = side.upper()
    if not isinstance(spec, dict):
        raise ApiError(400, f"Pilih sumber test case {S_}.", f"cmp-src-{side}")
    label = re.sub(r"\s+", " ", str(spec.get("label") or "")).strip()
    err = FR.label_error(label, S_)
    if err:
        raise ApiError(400, err, f"cmp-label-{side}")
    if spec.get("kind") == "run":
        rid = str(spec.get("id") or "")
        if not rid:
            raise ApiError(400, f"Pilih hasil run untuk {S_}.", f"cmp-run-{side}")
        d = run_dir(rid)
        info = read_json(d / "run.json") or {}
        if info.get("status") != "selesai":
            raise ApiError(400, f"Hasil run {S_} belum selesai.", f"cmp-run-{side}")
        try:
            tcs = load_run(d)
        except LoadError as e:
            raise ApiError(400, str(e), f"cmp-run-{side}")
        return {"label": label, "tcs": tcs, "key": f"run:{rid}", "missing": missing_fields(tcs),
                "source": f"Riwayat: {info.get('prd_title') or info.get('prd')} ({fmt_time(info.get('finished'))})"}
    if spec.get("kind") == "file":
        up = COMPARE_UPLOADS.get(str(spec.get("token") or ""))
        if not up:
            raise ApiError(400, f"Unggah file test case untuk {S_} (atau unggah ulang bila TƎRᗩ sempat ditutup).", f"cmp-file-{side}")
        return {"label": label, "tcs": [dict(t) for t in up["tcs"]], "key": f"file:{spec.get('token')}",
                "missing": up["missing"], "source": f"File: {up['name']}"}
    raise ApiError(400, f"Pilih sumber test case {S_}: dari Riwayat atau unggah file.", f"cmp-src-{side}")


def fmt_time(t):
    try:
        return time.strftime("%d-%m-%Y %H:%M", time.localtime(float(t)))
    except Exception:
        return "-"


def _compare_worker(a, b, mode, name, use_embed):
    from tc_compare.pipeline import run as compare_run
    try:
        llm_mod = None
        if mode == "lengkap":
            from tools import llm as llm_mod
        embed_fn = None
        if use_embed:
            from tools import embed
            embed_fn = embed.make()
        res = compare_run(a, b, mode=mode, name=name, llm=llm_mod, embed_fn=embed_fn, progress=COMPARE["progress"],
                          cb=lambda m: COMPARE["log"].append({"time": time.time(), "msg": m}))
        COMPARE["result"] = res
        COMPARE["status"] = "selesai"
    except Exception as e:
        traceback.print_exc()
        COMPARE["error"] = str(e)
        COMPARE["status"] = "gagal"
    finally:
        COMPARE["finished"] = time.time()
        keep_awake(False)


def start_compare(body):
    if _busy():
        raise ApiError(409, "Masih ada proses lain yang berjalan. Bandingkan test case setelah proses itu selesai.")
    raw_name = str(body.get("name") or "").strip()
    if raw_name:
        err = FR.name_error(raw_name, "Nama perbandingan")
        if err:
            raise ApiError(400, err, "cmp-name")
    mode = body.get("mode") if body.get("mode") in ("lengkap", "cepat") else None
    if not mode:
        raise ApiError(400, "Pilih mode perbandingan.", "cmp-mode")
    a = _compare_side(body.get("a"), "a")
    b = _compare_side(body.get("b"), "b")
    if a["key"] == b["key"]:
        raise ApiError(400, "A dan B memakai sumber yang sama. Pilih dua kumpulan test case yang berbeda.", "cmp-src-b")
    if a["label"].lower() == b["label"].lower():
        raise ApiError(400, "Nama kumpulan A dan B harus berbeda.", "cmp-label-b")
    models, problem = ai_source.probe()
    from tools import embed
    use_embed = models is not None and embed.available(models)
    if mode == "lengkap" and models is None:
        raise ApiError(409, ai_problem_text(problem) + " Atau pilih Mode cepat.", "cmp-mode")
    name = re.sub(r"\s+", " ", raw_name) or f"{a['label']} vs {b['label']}"
    with LOCK:
        if _busy():
            raise ApiError(409, "Masih ada proses lain yang berjalan.")
        COMPARE.update({"status": "berjalan", "log": [], "result": None, "error": None, "progress": {},
                        "started": time.time(), "finished": None, "name": name, "mode": mode})

    def go():
        keep_awake(True)
        _compare_worker(a, b, mode, name, use_embed)
    threading.Thread(target=go, daemon=True).start()
    return {"ok": True}


def reset_compare():
    if COMPARE["status"] == "berjalan":
        raise ApiError(409, "Perbandingan masih berjalan")
    COMPARE.update({"status": "idle", "log": [], "result": None, "error": None, "started": None, "finished": None,
                    "progress": {}, "name": None, "mode": None})
    return {"ok": True}


def _compare_dir(cid):
    d = COMPARE_DIR / Path(str(cid or "")).name
    if not cid or not (d / "analysis_metadata.json").is_file():
        raise ApiError(404, "Hasil perbandingan tidak ditemukan")
    return d


def list_compares():
    out = []
    if COMPARE_DIR.is_dir():
        for d in COMPARE_DIR.iterdir():
            meta = read_json(d / "analysis_metadata.json") if d.is_dir() else None
            if meta:
                out.append({"id": d.name, "name": meta.get("name"), "time": meta.get("time"), "mode": meta.get("mode"),
                            "labels": meta.get("labels"), "stats": meta.get("stats"), "xlsx_file": meta.get("xlsx_file")})
    return sorted(out, key=lambda m: m.get("time") or 0, reverse=True)


def read_compare(cid):
    res = read_json(_compare_dir(cid) / "hasil.json")
    if not res:
        raise ApiError(404, "Hasil perbandingan tidak ditemukan")
    res["id"] = Path(cid).name
    return res


def delete_compare(cid):
    if COMPARE["status"] == "berjalan":
        raise ApiError(409, "Perbandingan masih berjalan")
    d = _compare_dir(cid)
    shutil.rmtree(d)
    if (COMPARE.get("result") or {}).get("id") == d.name:
        reset_compare()
    return {"ok": True}


# ----------------------------------------------------------------------------- MD Konversi ke PDF
MDPDF_DIR = ROOT / "outputs" / "md_pdf"


def md_to_pdf(body):
    """Markdown -> PDF saat itu juga (tanpa AI). PDF dikembalikan untuk diunduh dan dicatat di Riwayat."""
    import hashlib
    name, content = str(body.get("name") or ""), body.get("content")
    err = FR.md_file_error(name, content)
    if err:
        raise ApiError(400, err, "md-files")
    from tools.md_pdf import first_heading, markdown_to_pdf, pdf_name
    t0 = time.time()
    try:
        data, out_name = markdown_to_pdf(content), pdf_name(Path(name).name)
    except Exception as e:
        raise ApiError(500, f"{name}: gagal dijadikan PDF ({e}).")
    try:  # file yang sama dikonversi lagi (mis. Lihat lalu Unduh) tidak dicatat dua kali
        rid = hashlib.sha1((Path(name).name + "\0" + content).encode("utf-8")).hexdigest()[:16]
        d = MDPDF_DIR / rid
        d.mkdir(parents=True, exist_ok=True)
        (d / "hasil.pdf").write_bytes(data)
        write_json(d / "meta.json", {"kind": "mdpdf", "id": rid, "source": Path(name).name, "pdf_file": out_name,
                                     "title": first_heading(content) or "", "time": time.time(), "bytes": len(data),
                                     "pages": data.count(b"/Type /Page ") , "seconds": round(time.time() - t0, 1)})
    except Exception:
        traceback.print_exc()  # pencatatan gagal tidak boleh menggagalkan unduhan
    return data, out_name


def list_mdpdfs():
    out = []
    if MDPDF_DIR.is_dir():
        for d in MDPDF_DIR.iterdir():
            meta = read_json(d / "meta.json") if d.is_dir() else None
            if meta and (d / "hasil.pdf").is_file():
                out.append(meta)
    return sorted(out, key=lambda m: m.get("time") or 0, reverse=True)


def _mdpdf_dir(rid):
    d = MDPDF_DIR / Path(str(rid or "")).name
    if not rid or not (d / "meta.json").is_file():
        raise ApiError(404, "Hasil PDF tidak ditemukan")
    return d


def delete_mdpdf(rid):
    shutil.rmtree(_mdpdf_dir(rid))
    return {"ok": True}


# ----------------------------------------------------------------------------- pembaruan TƎRᗩ dari GitHub
def update_info(force=False):
    from tools import updater
    return updater.check(force=force)


def update_apply():
    from tools import updater
    if _busy():
        raise ApiError(409, "Masih ada proses yang berjalan. Perbarui TƎRᗩ setelah proses itu selesai.")
    try:
        return updater.apply()
    except updater.UpdateError as e:
        raise ApiError(409, str(e))


# ----------------------------------------------------------------------------- kunci file referensi perusahaan
def vault_info():
    from tools import vault
    return vault.status()


def vault_action(action, body):
    from tools import vault
    if ACTIVE["id"]:
        raise ApiError(409, "Tunggu sampai pembuatan test case selesai.")
    pw = str(body.get("password") or "")
    if action == "forget":
        vault.forget()
        return vault.status()
    if action == "lock" and not vault.status()["has_vault"]:  # password baru: wajib kuat dan diulang
        err = FR.password_error(pw)
        if err:
            raise ApiError(400, err, "vl-pass")
        if pw != str(body.get("password2") or ""):
            raise ApiError(400, "Ulangi password belum sama.", "vl-pass2")
    elif not pw:
        raise ApiError(400, "Password wajib diisi.", "vl-pass")
    elif len(pw) > FR.PASSWORD_MAX:
        raise ApiError(400, f"Password maksimal {FR.PASSWORD_MAX} karakter.", "vl-pass")
    try:
        if action == "lock":
            vault.lock(pw)
        elif action == "unlock":
            vault.unlock(pw)
        elif action == "restore":
            vault.restore(pw)
        else:
            raise ApiError(404, "Aksi tidak dikenal")
    except vault.VaultError as e:
        raise ApiError(400, str(e), "vl-pass")
    return vault.status()


# ----------------------------------------------------------------------------- sumber AI
def _busy():
    return bool(ACTIVE["id"]) or NOTES["status"] == "berjalan" or DESIGN["status"] == "berjalan" \
        or COMPARE["status"] == "berjalan"


def source_info():
    models, problem = ai_source.probe()
    return {**ai_source.status(), "problem": problem, "ok": models is not None}


def source_login(body):
    if _busy():
        raise ApiError(409, "Sumber AI tidak bisa diganti selama ada proses yang berjalan.")
    url, user, pw = str(body.get("url") or "").strip(), str(body.get("username") or "").strip(), str(body.get("password") or "")
    for field, err in (("sa-url", FR.server_url_error(url)), ("sa-user", FR.username_error(user)),
                       ("sa-pass", "" if pw else "Password wajib diisi.")):
        if err:
            raise ApiError(400, err, field)
    if len(pw) > FR.PASSWORD_MAX:
        raise ApiError(400, f"Password maksimal {FR.PASSWORD_MAX} karakter.", "sa-pass")
    try:
        ai_source.login(url, user, pw)
    except ConnectionError as e:
        raise ApiError(502, str(e), "sa-url")
    except PermissionError as e:
        raise ApiError(401, str(e), "sa-pass")
    return source_info()


def source_logout():
    if _busy():
        raise ApiError(409, "Tidak bisa keluar selama ada proses yang berjalan.")
    ai_source.logout()
    return source_info()


def source_local():
    if _busy():
        raise ApiError(409, "Sumber AI tidak bisa diganti selama ada proses yang berjalan.")
    ai_source.use_local()
    return source_info()


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
route("GET", "/api/design")(lambda h, q: {**DESIGN, "now": time.time()})
route("POST", "/api/design")(lambda h, q: start_design(h.json_body()))
route("POST", "/api/design/reset")(lambda h, q: reset_design())
route("POST", "/api/design/images")(lambda h, q: upload_design_image(h.json_body(limit=60_000_000)))
route("GET", "/api/design/terhenti")(lambda h, q: design_interrupted())
route("POST", "/api/design/lanjut")(lambda h, q: resume_design(h.json_body()))
route("POST", "/api/design/buang")(lambda h, q: discard_design(h.json_body()))
route("GET", "/api/compare")(lambda h, q: compare_info())
route("POST", "/api/compare")(lambda h, q: start_compare(h.json_body()))
route("POST", "/api/compare/reset")(lambda h, q: reset_compare())
route("POST", "/api/compare/upload")(lambda h, q: compare_upload(h.json_body(limit=30_000_000)))
route("GET", "/api/compare/sources")(lambda h, q: compare_sources())
route("GET", "/api/compares")(lambda h, q: list_compares())
route("GET", "/api/compares/(?P<cid>[^/]+)")(lambda h, q, cid: read_compare(unquote(cid)))
route("DELETE", "/api/compares/(?P<cid>[^/]+)")(lambda h, q, cid: delete_compare(unquote(cid)))
route("GET", "/api/mdpdfs")(lambda h, q: list_mdpdfs())
route("DELETE", "/api/mdpdfs/(?P<rid>[^/]+)")(lambda h, q, rid: delete_mdpdf(unquote(rid)))
route("GET", "/api/update")(lambda h, q: update_info(force=(q.get("cek") or [""])[0] == "1"))
route("POST", "/api/update/apply")(lambda h, q: update_apply())
route("GET", "/api/vault")(lambda h, q: vault_info())
route("POST", "/api/vault/(?P<action>lock|unlock|restore|forget)")(lambda h, q, action: vault_action(action, h.json_body()))
route("GET", "/api/about")(lambda h, q: {"version": VER.current(), "changelog": VER.changelog(), "source": ai_source.status()})
route("GET", "/api/ai-source")(lambda h, q: source_info())
route("POST", "/api/ai-source/login")(lambda h, q: source_login(h.json_body()))
route("POST", "/api/ai-source/logout")(lambda h, q: source_logout())
route("POST", "/api/ai-source/local")(lambda h, q: source_local())
route("GET", "/api/prds/(?P<name>[^/]+)")(lambda h, q, name: read_prd(unquote(name)))
route("DELETE", "/api/prds/(?P<name>[^/]+)")(lambda h, q, name: delete_prd(unquote(name)))
route("PUT", "/api/prds/(?P<name>[^/]+)")(lambda h, q, name: save_prd(unquote(name), h.json_body()))


class Handler(BaseHTTPRequestHandler):
    server_version = "AIQADashboard/1.0"

    def log_message(self, fmt, *args):  # tidak membanjiri terminal
        pass

    # ---- helpers
    def json_body(self, limit=3_000_000):
        n = int(self.headers.get("Content-Length") or 0)
        if n > limit:
            raise ApiError(413, "Permintaan terlalu besar" + (" (gambar maksimal sekitar 40 MB)" if limit > 3_000_000 else ""))
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

    def send_pdf(self, data, name):
        self.send_response(200)
        self.send_header("Content-Type", "application/pdf")
        self.send_header("Content-Length", str(len(data)))
        self.send_header("Cache-Control", "no-store")
        plain = name.encode("ascii", "replace").decode().replace("?", "_").replace('"', "")
        self.send_header("Content-Disposition", f"attachment; filename=\"{plain}\"; filename*=UTF-8''{quote(name)}")
        self.end_headers()
        self.wfile.write(data)

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
            m = re.fullmatch(r"/api/compares/([^/]+)/xlsx", path)
            if method == "GET" and m:
                d = _compare_dir(unquote(m.group(1)))
                meta = read_json(d / "analysis_metadata.json") or {}
                f = d / Path(meta.get("xlsx_file") or "").name
                if not f.is_file():
                    raise ApiError(404, "File Excel tidak ditemukan")
                return self.send_file(f, f.name)
            m = re.fullmatch(r"/api/mdpdfs/([^/]+)/pdf", path)
            if method == "GET" and m:
                d = _mdpdf_dir(unquote(m.group(1)))
                meta = read_json(d / "meta.json") or {}
                return self.send_file(d / "hasil.pdf", Path(meta.get("pdf_file") or "hasil.pdf").name)
            if method == "POST" and path == "/api/md-pdf":
                return self.send_pdf(*md_to_pdf(self.json_body()))
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
            self.send_json({"detail": e.message, **({"field": e.field} if e.field else {})}, e.status)
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
    ap = argparse.ArgumentParser(description="TƎRᗩ - Asisten QA berbasis AI (dashboard lokal)")
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
    try:
        print(f"TƎRᗩ versi {VER.current()} berjalan di {url}")
    except UnicodeEncodeError:  # jendela lama yang tidak mendukung huruf khusus
        print(f"TERA berjalan di {url}")
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
