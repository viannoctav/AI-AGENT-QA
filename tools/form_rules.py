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


# ----------------------------------------------------------------------------- Server AI bersama
USERNAME_MIN, USERNAME_MAX = 3, 32
PASSWORD_MIN, PASSWORD_MAX = 8, 128
_USERNAME = re.compile(r"^[a-z][a-z0-9._-]*$")


def username_error(value) -> str:
    v = str(value or "")
    if not v.strip():
        return "Nama pengguna wajib diisi."
    if v != v.strip() or " " in v:
        return "Nama pengguna tidak boleh memakai spasi."
    if len(v) < USERNAME_MIN or len(v) > USERNAME_MAX:
        return f"Nama pengguna harus {USERNAME_MIN}–{USERNAME_MAX} karakter."
    if v != v.lower():
        return "Nama pengguna memakai huruf kecil semua."
    if not _USERNAME.match(v):
        return "Nama pengguna diawali huruf, lalu hanya huruf kecil, angka, titik, garis bawah, atau tanda minus."
    return ""


def password_error(value, username: str = "") -> str:
    v = str(value or "")
    if not v:
        return "Password wajib diisi."
    if len(v) < PASSWORD_MIN:
        return f"Password minimal {PASSWORD_MIN} karakter."
    if len(v) > PASSWORD_MAX:
        return f"Password maksimal {PASSWORD_MAX} karakter."
    if v != v.strip():
        return "Password tidak boleh diawali atau diakhiri spasi."
    if not re.search(r"[A-Za-z]", v) or not re.search(r"\d", v):
        return "Password harus berisi huruf dan angka."
    if username and username.lower() in v.lower():
        return "Password tidak boleh mengandung nama pengguna."
    if len(set(v.lower())) < 4:
        return "Password terlalu mudah ditebak."
    return ""


def server_url_error(value) -> str:
    """Alamat Server AI bersama, mis. http://100.101.102.103:11500 atau http://laptop-anggun:11500."""
    v = str(value or "").strip()
    if not v:
        return "Alamat server wajib diisi."
    if len(v) > 200:
        return "Alamat server terlalu panjang."
    m = re.fullmatch(r"(https?)://([A-Za-z0-9.-]+)(?::(\d{1,5}))?/?", v)
    if not m:
        return "Format alamat server salah. Contoh: http://100.101.102.103:11500"
    host, port = m.group(2), m.group(3)
    if host.startswith(("-", ".")) or host.endswith(("-", ".")) or ".." in host:
        return "Nama komputer di alamat server tidak valid."
    if port and not (1 <= int(port) <= 65535):
        return "Nomor port harus di antara 1 dan 65535."
    if re.fullmatch(r"[\d.]+", host):
        parts = host.split(".")
        if len(parts) != 4 or any(not p or int(p) > 255 for p in parts):
            return "Alamat IP tidak valid."
    return ""


def version_error(value, maximum: str = "") -> str:
    """Versi minimal TƎRᗩ (halaman admin Server AI): kosong = tidak dibatasi."""
    v = str(value or "").strip()
    if not v:
        return ""
    if not re.fullmatch(r"\d{1,4}\.\d{1,4}\.\d{1,4}", v):
        return "Format versi tiga angka dipisah titik, misalnya 1.1.0."
    if maximum and tuple(map(int, v.split("."))) > tuple(map(int, maximum.split("."))):
        return f"Versi minimal tidak boleh lebih baru dari versi server ini ({maximum})."
    return ""


MD_EXT = ("md", "markdown")
MD_MAX_BYTES = 2_000_000


def md_file_error(name, content) -> str:
    """File Markdown untuk MD Konversi ke PDF."""
    n = str(name or "").strip()
    if not n:
        return "Nama file wajib ada."
    ext = n.rsplit(".", 1)[-1].lower() if "." in n else ""
    if ext not in MD_EXT:
        return f"{n}: format harus .md."
    if not isinstance(content, str) or not content.strip():
        return f"{n}: file kosong."
    if len(content.encode("utf-8")) > MD_MAX_BYTES:
        return f"{n}: ukuran file maksimal 2 MB."
    if "\x00" in content or "�" in content[:2000]:
        return f"{n}: bukan file teks Markdown yang bisa dibaca."
    if _alnum(content) < 3:
        return f"{n}: tidak berisi teks yang bisa dijadikan PDF."
    return ""


# ----------------------------------------------------------------------------- Bandingkan test case
COMPARE_EXT = ("xlsx", "json")
COMPARE_MAX_BYTES = 20 * 1024 * 1024
LABEL_MIN, LABEL_MAX = 1, 30


def compare_file_error(name: str, n_bytes: int) -> str:
    ext = name.rsplit(".", 1)[-1].lower() if "." in name else ""
    if ext not in COMPARE_EXT:
        return f"{name}: format harus Excel (.xlsx) atau JSON (.json)."
    if n_bytes <= 0:
        return f"{name}: file kosong."
    if n_bytes > COMPARE_MAX_BYTES:
        return f"{name}: ukuran file maksimal 20 MB."
    return ""


def label_error(value, side: str) -> str:
    v = re.sub(r"\s+", " ", str(value or "")).strip()
    if not v:
        return f"Nama kumpulan {side} wajib diisi."
    if len(v) > LABEL_MAX:
        return f"Nama kumpulan {side} maksimal {LABEL_MAX} karakter."
    if any(c in FORBIDDEN or ord(c) < 32 for c in v):
        return f"Nama kumpulan {side} tidak boleh memakai karakter {' '.join(FORBIDDEN)}"
    if not any(c.isalnum() for c in v):
        return f"Nama kumpulan {side} harus mengandung huruf atau angka."
    return ""
