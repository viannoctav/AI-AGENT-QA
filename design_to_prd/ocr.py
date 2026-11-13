"""Membaca teks gambar dengan OCR bawaan Windows (tanpa install, tanpa internet, tanpa AI).
OCR hanya membaca huruf yang benar-benar ada di gambar, jadi tidak bisa mengarang dan salah ketik tetap terbaca."""
import json
import re
import subprocess
import sys
from pathlib import Path
from typing import Any, Dict, List

from PIL import Image

MAX_DIM = 2600  # batas aman ukuran gambar untuk OCR Windows
PS1 = Path(__file__).resolve().parent / "ocr_windows.ps1"


class OcrError(RuntimeError):
    pass


def read_text(paths: List[str], work_dir: Path) -> Dict[str, List[Dict[str, Any]]]:
    """{path: [{"text", "x", "y", "w", "h"}]} dengan posisi dalam piksel gambar asli."""
    if not sys.platform.startswith("win"):
        raise OcrError("Pembaca teks (OCR) bawaan Windows hanya tersedia di Windows.")
    work_dir.mkdir(parents=True, exist_ok=True)
    big, scale = [], {}
    for i, p in enumerate(paths):
        im = Image.open(p)
        k = min(2.0, MAX_DIM / max(im.size))  # diperbesar: huruf kecil lebih terbaca
        b = work_dir / f"ocr_{i:03d}.png"
        (im.resize((int(im.width * k), int(im.height * k)), Image.LANCZOS) if k > 1.05 else im).save(b)
        big.append(b)
        scale[str(b)] = (p, k if k > 1.05 else 1.0)
    lst = work_dir / "ocr_daftar.txt"
    lst.write_text("\n".join(str(b) for b in big), encoding="utf-8")
    res_file = work_dir / "ocr_hasil.json"
    res_file.unlink(missing_ok=True)
    cmd = ["powershell.exe", "-NoProfile", "-ExecutionPolicy", "Bypass", "-File", str(PS1),
           "-List", str(lst), "-Out", str(res_file)]
    try:
        p = subprocess.run(cmd, capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=120 + 5 * len(paths),
                           creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
    except Exception as e:
        raise OcrError(f"Pembaca teks Windows tidak bisa dijalankan: {e}")
    if not res_file.exists():
        raise OcrError("Pembaca teks Windows gagal: " + ((p.stderr or p.stdout or "").strip()[-600:] or "tanpa pesan"))
    data = json.loads(res_file.read_text(encoding="utf-8-sig"))
    if data.get("error"):
        raise OcrError(f"{data['error']}. Pasang bahasa Inggris (English) di Windows: Settings > Time & language > "
                       f"Language & region > Add a language.")
    results = data.get("results") or []
    if isinstance(results, dict):
        results = [results]
    out: Dict[str, List[Dict[str, Any]]] = {}
    for r in results:
        f = r.get("file")
        if isinstance(f, dict):  # PowerShell kadang membungkus teks beserta info tambahannya
            f = f.get("value", "")
        lines = r.get("lines") or []
        if isinstance(lines, dict):
            lines = [lines]
        orig, k = scale.get(str(f), scale.get(str(Path(f)), (None, 1.0)))
        if orig is None:
            continue
        out[orig] = [{"text": str(ln.get("text") or ""), "x": round(ln.get("x", 0) / k), "y": round(ln.get("y", 0) / k),
                      "w": round(ln.get("w", 0) / k), "h": round(ln.get("h", 0) / k)} for ln in lines]
    for b in big:
        b.unlink(missing_ok=True)
    return out


_ICON_PREFIX = re.compile(r"^(\S)\s+(?=\S)")
_URL = re.compile(r"\b[\w-]+\.(?:com|id|net|org|io|co|app|dev|local)\b(?:/\S*)?|https?://", re.I)


def clean_lines(lines: List[Dict[str, Any]], height: int) -> List[Dict[str, Any]]:
    """Rapikan hasil OCR (kode, bukan AI):
    - ikon yang terbaca sebagai huruf di depan teks dibuang ("Q Search" -> "Search"), teks asli tetap disimpan;
    - potongan yang hanya simbol ikon ("x", "0+", ">") dibuang;
    - bingkai browser mockup (tab, alamat URL) di bagian paling atas dibuang."""
    url_bottom = 0
    for ln in lines:
        if _URL.search(ln["text"]) and ln["y"] < height * 0.15:
            url_bottom = max(url_bottom, ln["y"] + ln["h"] + 6)
    out = []
    for ln in lines:
        raw = re.sub(r"\s+", " ", ln["text"]).strip()
        if url_bottom and ln["y"] + ln["h"] <= url_bottom:
            continue
        t = raw
        m = _ICON_PREFIX.match(t)
        if m:
            first, rest = m.group(1), t[m.end():]
            single_word = len(rest.split()) == 1
            if (not first.isalnum()) or (first.isalpha() and first not in "AI" and rest[:1].isupper()) \
                    or (first.isdigit() and single_word and rest[:1].isupper()):
                t = rest
        if not re.search(r"[A-Za-z0-9]", t) or (len(t) <= 2 and not t.isdigit() and not t.isalpha()) or \
                (len(t) == 1 and not t.isdigit()):
            continue
        out.append({**ln, "text": t, "raw": raw})
    return _join_wrapped(out)


def _join_wrapped(lines: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """Satu kalimat yang terpotong ke baris berikutnya ("... at least 8" + "characters") digabung lagi."""
    out: List[Dict[str, Any]] = []
    for ln in sorted(lines, key=lambda l: (l["y"], l["x"])):
        prev = next((p for p in reversed(out) if abs(p["x"] - ln["x"]) <= 8
                     and 0 <= ln["y"] - (p["y"] + p["h"]) <= 0.9 * max(p["h"], ln["h"])
                     and abs(p["h"] - ln["h"]) <= 4), None)
        if prev and not prev["text"].rstrip().endswith((".", "!", "?", ":")) and ln["text"][:1].islower():
            x1 = max(prev["x"] + prev["w"], ln["x"] + ln["w"])
            prev.update(text=f"{prev['text']} {ln['text']}", raw=f"{prev['raw']} {ln['raw']}",
                        w=x1 - prev["x"], h=ln["y"] + ln["h"] - prev["y"])
            continue
        out.append(dict(ln))
    return out
