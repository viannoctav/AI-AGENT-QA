"""Membaca kumpulan test case dari hasil run TƎRᗩ (Riwayat) atau dari file unggahan (Excel / JSON),
lalu menyeragamkan kolomnya. Kolom yang tidak ada ditandai kosong, bukan membuat proses gagal."""
import json
import re
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

FIELDS = ("no", "module", "sub", "category", "title", "pre", "steps", "data", "expected", "req", "priority")
LABELS = {"no": "No. TC", "module": "Module", "sub": "Sub Module", "category": "Jenis (Positive/Negative)",
          "title": "Test Case / Skenario", "pre": "Pre-condition", "steps": "Steps", "data": "Test Data",
          "expected": "Expected Result", "req": "Requirement ID", "priority": "Priority"}

# nama kolom yang dikenali (huruf kecil, tanpa tanda baca)
_COLS = {
    "no": ["tc no", "tc id", "test case id", "id", "no", "nomor", "no tc", "tc", "test id", "case id", "kode"],
    "module": ["module", "module menu", "modul", "menu", "fitur", "feature", "module feature"],
    "sub": ["sub module", "sub module menu", "submodule", "sub menu", "sub modul", "halaman", "screen", "frame",
            "screen frame", "page", "sub fitur", "element", "elemen"],
    "category": ["test case type", "type", "jenis", "tipe", "kategori", "category", "polarity", "positive negative"],
    "title": ["test case", "test case name", "test case title", "judul", "scenario", "skenario", "test scenario",
              "deskripsi", "description", "test case description", "nama test case", "title", "summary"],
    "pre": ["pre condition", "precondition", "preconditions", "pre conditions", "prasyarat", "kondisi awal"],
    "steps": ["test steps", "steps", "langkah", "langkah langkah", "step", "langkah pengujian", "test step"],
    "data": ["test data", "data", "data uji", "input data", "data pengujian"],
    "expected": ["expected result", "expected", "hasil yang diharapkan", "expected results", "hasil diharapkan",
                 "ekspektasi", "expected outcome", "hasil harapan"],
    "req": ["requirement id", "requirement", "req id", "requirement ids", "fr", "reference", "source reference"],
    "priority": ["priority", "prioritas", "severity"],
}
MAX_TCS = 5000


class LoadError(Exception):
    pass


def _key(s) -> str:
    return re.sub(r"[^a-z0-9]+", " ", str(s or "").lower()).strip()


def _clean(v) -> str:
    if v is None:
        return ""
    s = str(v).strip()
    return "" if s in ("-", "None") else s


def _finish(rows: List[Dict[str, Any]], source: str) -> List[Dict[str, Any]]:
    out = []
    for i, r in enumerate(rows, 1):
        tc = {f: _clean(r.get(f)) for f in FIELDS}
        if not tc["title"] and not tc["expected"] and not tc["steps"]:
            continue
        tc["no"] = tc["no"] or f"#{i}"
        out.append(tc)
    if len(out) > MAX_TCS:
        raise LoadError(f"{source}: terlalu banyak test case ({len(out)}). Maksimal {MAX_TCS}.")
    # nomor TC kembar di satu sumber diberi akhiran supaya tetap bisa dirujuk
    seen: Dict[str, int] = {}
    for tc in out:
        n = seen.get(tc["no"], 0)
        seen[tc["no"]] = n + 1
        if n:
            tc["no"] = f"{tc['no']} ({n + 1})"
    return out


def from_artifacts(data: Dict[str, Any], source: str = "hasil run") -> List[Dict[str, Any]]:
    """artifacts.json dari Generator Test Case PRD."""
    rows = []
    for t in data.get("tcs") or []:
        rows.append({"no": t.get("tc_no"), "module": t.get("module"), "sub": t.get("sub_label"),
                     "category": t.get("category"), "title": t.get("title"), "pre": t.get("preconditions"),
                     "steps": t.get("steps"), "data": t.get("test_data"), "expected": t.get("expected_result"),
                     "req": ", ".join(t.get("requirement_ids") or []), "priority": t.get("priority")})
    return _finish(rows, source)


def from_json(raw: bytes, source: str) -> Tuple[List[Dict[str, Any]], Dict[str, str]]:
    try:
        data = json.loads(raw.decode("utf-8-sig"))
    except Exception:
        raise LoadError(f"{source}: bukan file JSON yang valid.")
    if isinstance(data, dict) and isinstance(data.get("tcs"), list):
        return from_artifacts(data, source), {f: f for f in ("no", "sub", "title", "data", "expected")}
    items = data if isinstance(data, list) else next((v for v in data.values() if isinstance(v, list)), None) \
        if isinstance(data, dict) else None
    if not items or not all(isinstance(x, dict) for x in items):
        raise LoadError(f"{source}: isi JSON harus berupa daftar test case.")
    mapping = _map_columns(list({k for x in items for k in x.keys()}))
    rows = [{f: x.get(col) for f, col in mapping.items()} for x in items]
    return _finish(rows, source), mapping


def _map_columns(headers: List[str]) -> Dict[str, str]:
    mapping: Dict[str, str] = {}
    keyed = [(h, _key(h)) for h in headers if _key(h)]
    for field, names in _COLS.items():  # nama persis lebih dulu, baru yang mengandung
        hit = next((h for h, k in keyed if k in names and h not in mapping.values()), None)
        if not hit and field not in ("no", "data", "req"):
            hit = next((h for h, k in keyed if any(n in k for n in names if len(n) > 3) and h not in mapping.values()), None)
        if hit:
            mapping[field] = hit
    return mapping


def from_excel(raw: bytes, source: str) -> Tuple[List[Dict[str, Any]], Dict[str, str]]:
    import io
    import openpyxl
    try:
        wb = openpyxl.load_workbook(io.BytesIO(raw), read_only=True, data_only=True)
    except Exception:
        raise LoadError(f"{source}: file Excel tidak bisa dibuka (rusak, terkunci kata sandi, atau bukan .xlsx).")
    best = None
    for ws in wb.worksheets:
        rows = []
        for i, r in enumerate(ws.iter_rows(values_only=True)):
            rows.append(list(r))
            if i > 6000:
                break
        for hi, r in enumerate(rows[:40]):  # baris judul kolom ada di 40 baris pertama
            headers = [str(c).strip() if c is not None else "" for c in r]
            mapping = _map_columns([h for h in headers if h])
            if "title" in mapping and ("expected" in mapping or "steps" in mapping):
                score = len(mapping) + (5 if "TEST CASES" in ws.title.upper() else 0)
                if not best or score > best[0]:
                    best = (score, ws.title, headers, mapping, rows[hi + 1:])
                break
    wb.close()
    if not best:
        raise LoadError(f"{source}: kolom test case tidak ditemukan. Excel minimal punya kolom judul test case "
                        f"(mis. \"Test Case\" atau \"Skenario\") dan \"Expected Result\" atau \"Steps\".")
    _, sheet, headers, mapping, body = best
    idx = {f: headers.index(col) for f, col in mapping.items()}
    rows = []
    for r in body:
        vals = {f: (r[i] if i < len(r) else None) for f, i in idx.items()}
        filled = [c for c in r if c not in (None, "")]
        if len(filled) <= 1:  # baris judul kelompok (mis. nama fitur) atau baris kosong
            continue
        rows.append(vals)
    return _finish(rows, source), {**mapping, "_sheet": sheet}


def load_upload(name: str, raw: bytes) -> Tuple[List[Dict[str, Any]], Dict[str, str]]:
    ext = name.rsplit(".", 1)[-1].lower() if "." in name else ""
    if ext == "xlsx":
        tcs, mapping = from_excel(raw, name)
    elif ext == "json":
        tcs, mapping = from_json(raw, name)
    else:
        raise LoadError(f"{name}: format harus .xlsx atau .json.")
    if not tcs:
        raise LoadError(f"{name}: tidak ada test case yang terbaca.")
    return tcs, mapping


def load_run(run_dir: Path) -> List[Dict[str, Any]]:
    f = Path(run_dir) / "artifacts.json"
    if f.is_file():
        tcs = from_artifacts(json.loads(f.read_text(encoding="utf-8")), Path(run_dir).name)
        if tcs:
            return tcs
    x = Path(run_dir) / "test_cases.xlsx"
    if x.is_file():
        return from_excel(x.read_bytes(), x.name)[0]
    raise LoadError("Hasil run ini tidak punya test case yang bisa dibaca.")


def missing_fields(tcs: List[Dict[str, Any]]) -> List[str]:
    """Kolom penting yang kosong di semua test case (ditampilkan sebagai catatan, bukan error)."""
    return [LABELS[f] for f in ("sub", "data", "expected", "category") if not any(t.get(f) for t in tcs)]
