"""Aturan validasi isian dashboard TƎRᗩ (dipakai server; aturan yang sama ada di dashboard/app.js bagian VALIDASI).
Setiap fungsi mengembalikan pesan error berbahasa Indonesia, atau "" bila isian benar."""
import re
from typing import List, Optional

FORBIDDEN = '\\/:*?"<>|'
MODULE_MIN, MODULE_MAX = 3, 80
NOTES_MIN_CHARS, NOTES_MIN_WORDS, NOTES_MAX = 20, 3, 200_000
OPTIONAL_MIN_CHARS, OPTIONAL_MAX = 10, 50_000
DESIGN_TOTAL_MAX = 200_000
IMAGE_EXT = ("png", "jpg", "jpeg", "webp")
IMAGE_MAX_BYTES = 40 * 1024 * 1024
IMAGE_MIN_W, IMAGE_MIN_H = 120, 40
PRD_MAX_BYTES = 2_000_000
NUMBERS = {  # kunci pengaturan: (label, minimal, maksimal, boleh kosong)
    "batch_size": ("Skenario per kelompok", 1, 20, False),
    "max_attempts": ("Batas menulis ulang", 1, 10, False),
    "max_obligations": ("Jumlah skenario maksimum", 1, 10_000, True),
    "num_ctx": ("Kapasitas teks per permintaan", 2048, 131_072, False),
}


def _alnum(s: str) -> int:
    return sum(1 for c in s if c.isalnum())


def name_error(value, label: str = "Nama modul") -> str:
    """Nama modul / nama halaman: dipakai sebagai nama file dan judul, jadi dibatasi."""
    v = re.sub(r"\s+", " ", str(value or "")).strip()
    if not v:
        return f"{label} wajib diisi."
    if re.search(r"[\r\n\t]", str(value or "").strip()):
        return f"{label} harus satu baris."
    if len(v) < MODULE_MIN:
        return f"{label} minimal {MODULE_MIN} karakter."
    if len(v) > MODULE_MAX:
        return f"{label} maksimal {MODULE_MAX} karakter."
    if any(c in FORBIDDEN or ord(c) < 32 for c in v):
        return f"{label} tidak boleh memakai karakter {' '.join(FORBIDDEN)}"
    if not any(c.isalpha() for c in v):
        return f"{label} harus mengandung huruf, tidak boleh hanya angka atau simbol."
    return ""


def _readable(v: str) -> bool:
    letters = [c.lower() for c in v if c.isalnum()]
    return len(set(letters)) >= 4  # "aaaaaaa" atau "1111111" bukan kalimat


def notes_error(value, label: str = "Catatan QA") -> str:
    v = str(value or "")
    if not v.strip():
        return f"{label} wajib diisi."
    if len(v) > NOTES_MAX:
        return f"{label} terlalu panjang (maksimal {NOTES_MAX:,} karakter).".replace(",", ".")
    if _alnum(v) < NOTES_MIN_CHARS or len(v.split()) < NOTES_MIN_WORDS:
        return f"{label} terlalu pendek. Minimal {NOTES_MIN_CHARS} huruf/angka dan {NOTES_MIN_WORDS} kata."
    if not _readable(v):
        return f"{label} tidak berisi kalimat yang bisa dibaca."
    return ""


def optional_text_error(value, label: str) -> str:
    """Kolom opsional (penjelasan, deskripsi tambahan): boleh kosong; kalau diisi harus bisa dibaca."""
    v = str(value or "")
    if not v.strip():
        return ""
    if len(v) > OPTIONAL_MAX:
        return f"{label} terlalu panjang (maksimal {OPTIONAL_MAX:,} karakter).".replace(",", ".")
    if _alnum(v) < OPTIONAL_MIN_CHARS:
        return f"{label} terlalu pendek untuk disusun menjadi aturan (minimal {OPTIONAL_MIN_CHARS} huruf/angka). Kosongkan bila tidak perlu."
    if not _readable(v):
        return f"{label} tidak berisi kalimat yang bisa dibaca."
    return ""


def image_name_error(name: str) -> str:
    ext = name.rsplit(".", 1)[-1].lower() if "." in name else ""
    if ext not in IMAGE_EXT:
        return f"{name}: format harus PNG, JPG, atau WEBP."
    return ""


def image_size_error(name: str, n_bytes: int, width: Optional[int] = None, height: Optional[int] = None) -> str:
    if n_bytes <= 0:
        return f"{name}: file kosong."
    if n_bytes > IMAGE_MAX_BYTES:
        return f"{name}: ukuran file maksimal 40 MB."
    if width is not None and height is not None and (width < IMAGE_MIN_W or height < IMAGE_MIN_H):
        return f"{name}: gambar terlalu kecil untuk dibaca (minimal {IMAGE_MIN_W}×{IMAGE_MIN_H} piksel)."
    return ""


def prd_content_error(content, require_items: bool = True) -> str:
    if not isinstance(content, str) or not content.strip():
        return "Isi PRD kosong."
    if len(content.encode("utf-8")) > PRD_MAX_BYTES:
        return "PRD terlalu besar (maksimal 2 MB)."
    if not re.search(r"^#\s+\S", content, re.M):
        return "PRD harus punya judul di baris paling atas, diawali tanda # (mis. \"# Nama Modul\")."
    if require_items:
        try:
            from tools.prd_structure import parse_prd_markdown
            items = parse_prd_markdown(content).get("items") or []
        except Exception:
            items = []
        if not items:
            return "Tidak ditemukan requirement di PRD ini. Setiap requirement ditulis sebagai judul seperti \"### FR-001 Nama Fitur\"."
    return ""


def number_error(key: str, value) -> str:
    label, lo, hi, optional = NUMBERS[key]
    if value is None or value == "":
        return "" if optional else f"{label} wajib diisi."
    if isinstance(value, bool) or not isinstance(value, int):
        return f"{label} harus angka bulat."
    if value < lo or value > hi:
        return f"{label} harus di antara {lo:,} dan {hi:,}.".replace(",", ".")
    if key == "num_ctx" and value % 1024:
        return f"{label} harus kelipatan 1024 (mis. 4096, 8192, 16384)."
    return ""


def duplicate_names(names: List[str]) -> List[int]:
    """Indeks nama yang sudah dipakai kartu sebelumnya (tidak peka huruf besar/kecil)."""
    seen, dup = set(), []
    for i, n in enumerate(names):
        k = re.sub(r"\s+", " ", str(n or "")).strip().lower()
        if k and k in seen:
            dup.append(i)
        seen.add(k)
    return dup
