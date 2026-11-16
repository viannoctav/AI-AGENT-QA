"""Penjaga anti-karangan (kode, bukan AI).

Setiap item hasil AI hanya diterima bila:
  1. kutipannya benar-benar ada di catatan (baris yang disebut, atau baris tetangganya),
  2. semua angka di pernyataan ada di kutipan/baris sumber (tidak ada angka karangan),
  3. nama role / status yang disebut ada di catatan.
"""
import re
from typing import Any, Dict, List, Optional, Tuple

_WORD = re.compile(r"[a-z0-9]+")


def norm(text: str) -> str:
    t = str(text or "").lower().replace("’", "'").replace("‘", "'").replace("“", '"').replace("”", '"')
    t = re.sub(r"[*_`#>]", " ", t)
    return re.sub(r"\s+", " ", t).strip(" -•.\t")


def words(text: str) -> List[str]:
    return _WORD.findall(norm(text))


def numbers(text: str) -> List[str]:
    """Angka di teks (1.000.000 / 1,000,000 -> 1000000)."""
    t = re.sub(r"(?<=\d)[.,](?=\d{3}\b)", "", str(text or ""))
    return re.findall(r"\d+(?:[.,]\d+)?", t)


def find_quote(quote: str, lines: List[str], hint: Optional[int] = None) -> Optional[int]:
    """Nomor baris (1-based) tempat kutipan berada, atau None bila kutipan tidak ada di catatan.
    Cocok bila teksnya sama persis (setelah dirapikan), atau >= 85% kata kutipan ada berurutan di baris itu
    (AI kadang membuang tanda baca/mengubah huruf besar-kecil)."""
    q = norm(quote)
    if len(q) < 2:
        return None
    qw = words(q)
    order = list(range(len(lines)))
    if hint and 1 <= hint <= len(lines):  # cek baris yang disebut AI dan tetangganya lebih dulu
        near = [hint - 1, hint - 2, hint]
        order = [i for i in near if 0 <= i < len(lines)] + [i for i in order if i not in near]
    for i in order:
        ln = norm(lines[i])
        if not ln:
            continue
        if q in ln:
            return i + 1
        lw = words(ln)
        if qw and len(qw) >= 3:
            hit = sum(1 for w in qw if w in lw)
            if hit / len(qw) >= 0.85:
                return i + 1
    # kutipan yang melintasi dua baris berurutan
    for i in range(len(lines) - 1):
        two = norm(lines[i] + " " + lines[i + 1])
        if q in two:
            return i + 1
    return None


# kata umum (bahasa), bukan istilah catatan: boleh muncul di pernyataan walau tidak ada di catatan
_COMMON = set("""dapat bisa wajib harus hanya untuk dengan yang dan atau adalah akan oleh pada dari dalam ke di saat
setelah sebelum tidak boleh melakukan memiliki menggunakan menampilkan sistem aplikasi user pengguna data berupa
sebagai jika bila maka tersebut setiap semua seluruh lain baru miliknya sendiri berdasarkan per mengakses fitur
dibuat membuat dilakukan diisi mengisi isian berisi berlaku terdiri tahap jenis role field panjang karakter format
kemudian lalu juga serta mengubah ubah melihat lihat dipilih memilih pilihan opsi tersedia menyediakan the a an of
to and or for with can must only is are be by in on as all its own each per has have when after before
tepat jumlah akun minimal maksimal maksimum minimum berhasil gagal ditolak diterima sesuai nilai angka hari menit
detik jam kali percobaan halaman tombol pesan muncul tampil ditampilkan otomatis apabila sudah belum masih""".split())


def _key_terms(text: str) -> List[str]:
    return [w for w in words(text) if len(w) >= 4 and w not in _COMMON and not w.isdigit()]


def _in(term: str, vocab: set) -> bool:
    return term in vocab or any(len(v) >= 5 and (v.startswith(term[:5]) or term.startswith(v[:5])) for v in vocab)


def check_item(item: Dict[str, Any], lines: List[str]) -> Tuple[bool, str, Optional[int]]:
    """(diterima, alasan penolakan, nomor baris sumber)."""
    quote = str(item.get("kutipan") or "").strip()
    stmt = str(item.get("pernyataan") or "").strip()
    if not quote or not stmt:
        return False, "kutipan atau pernyataan kosong", None
    hint = item.get("baris")
    try:
        hint = int(hint)
    except (TypeError, ValueError):
        hint = None
    line_no = find_quote(quote, lines, hint)
    if not line_no:
        return False, "kutipan tidak ditemukan di catatan (kemungkinan dikarang AI)", None
    src = " ".join(lines[max(0, line_no - 2):line_no + 1])  # baris sumber + tetangga (konteks daftar/sub-poin)
    allowed = set(numbers(quote)) | set(numbers(src))
    extra = [n for n in numbers(stmt) if n not in allowed]
    if extra:
        return False, f"angka {', '.join(extra)} tidak ada di catatan", line_no
    # pernyataan tidak boleh membawa istilah yang tidak ada di catatan sama sekali (paraphrase boleh, isi baru tidak)
    vocab = set(words(" ".join(lines)))
    terms = _key_terms(stmt)
    absent = [t for t in terms if not _in(t, vocab)]
    if len(terms) >= 2 and len(absent) / len(terms) > 0.67:
        return False, f"pernyataan memuat hal yang tidak ada di catatan ({', '.join(absent[:4])})", line_no
    # kutipan pendek (1-2 kata) tidak cukup sebagai dasar: isi pernyataan harus ada di sekitar baris itu
    if len(words(quote)) < 3 and terms:
        near = set(words(" ".join(lines[max(0, line_no - 3):line_no + 2])))
        if sum(1 for t in terms if _in(t, near)) / len(terms) < 0.67:
            return False, "kutipan terlalu pendek dan isi pernyataan tidak ada di baris sekitarnya", line_no
    full = norm(" ".join(lines))
    for key in ("role", "dari", "ke"):
        val = str(item.get(key) or "").strip()
        if val and not _present(val, full):
            return False, f'"{val}" tidak disebut di catatan', line_no
    return True, "", line_no


def _present(name: str, full_norm: str) -> bool:
    w = words(name)
    if not w:
        return True
    return norm(name) in full_norm or sum(1 for x in w if x in full_norm.split()) / len(w) >= 0.75


def similar(a: str, b: str) -> float:
    wa, wb = set(words(a)), set(words(b))
    if not wa or not wb:
        return 0.0
    return len(wa & wb) / len(wa | wb)


# kata kerja pada tombol/aksi -> maksud bisnisnya, dipakai Desain ke PRD dan Catatan ke PRD, supaya aturan berbunyi "Pengguna dapat menambahkan user",
# bukan "pengguna menekan tombol Add user". Hanya kata kerja yang jelas; selain itu kalimat alur dipakai apa adanya.
_VERBS = [
    (r"^(?:add|create|new|tambah)\b", "menambahkan"), (r"^(?:save|simpan|apply|terapkan)\b", "menyimpan"),
    (r"^(?:update|perbarui|ubah|edit|change)\b", "mengubah"), (r"^(?:delete|remove|hapus)\b", "menghapus"),
    (r"^(?:reset)\b", "mengatur ulang"), (r"^(?:resend|kirim ulang)\b", "mengirim ulang"),
    (r"^(?:send|submit|kirim)\b", "mengirim"), (r"^(?:export|download|unduh)\b", "mengunduh"),
    (r"^(?:upload|unggah)\b", "mengunggah"), (r"^(?:confirm|konfirmasi)\b", "mengonfirmasi"),
    (r"^(?:approve|setujui)\b", "menyetujui"), (r"^(?:reject|decline|tolak)\b", "menolak"),
    (r"^(?:assign)\b", "menugaskan"), (r"^(?:invite|undang)\b", "mengundang"),
    (r"^(?:print|cetak)\b", "mencetak"), (r"^(?:filter|search|cari)\b", "menyaring daftar"),
    (r"^(?:book|schedule|jadwal)\b", "menjadwalkan"), (r"^(?:pay|bayar|checkout)\b", "melakukan pembayaran"),
    (r"^(?:activate|aktifkan)\b", "mengaktifkan"), (r"^(?:deactivate|nonaktifkan|disable)\b", "menonaktifkan"),
]
_GENERIC = {"changes", "change", "data", "info", "information", "all", "now", "it", "this", "perubahan", "semua"}
_LOGIN_ACT = re.compile(r"^(log ?in|sign ?in|masuk)\b", re.I)
_LOGOUT_ACT = re.compile(r"^(log ?out|sign ?out|keluar)\b", re.I)


def intent(btn: str, title: str = "") -> str:
    """Maksud bisnis dari sebuah tombol, mis. "Add user" -> "menambahkan user". "" bila tidak yakin."""
    t = re.sub(r"\s+", " ", str(btn or "")).strip()
    if not t:
        return ""
    if _LOGIN_ACT.match(t):
        return "masuk ke aplikasi"
    if _LOGOUT_ACT.match(t):
        return "keluar dari aplikasi"
    for pat, verb in _VERBS:
        m = re.match(pat, t, re.I)
        if not m:
            continue
        obj = re.sub(r"[?!.]+$", "", t[m.end():].strip(" -:·").strip())
        if obj.lower() in _GENERIC or not obj:
            # "Save changes" tidak menyebut objeknya: ambil dari judul layar, mis. "Edit user" -> "mengubah user"
            dari_judul = intent(title) if title and norm(title) != norm(t) else ""
            return dari_judul or verb
        return f"{verb} {obj}".strip()
    return ""
