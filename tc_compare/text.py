"""Lapis 1 (rapikan teks) dan alat ukur kemiripan tanpa AI. Semua Python bawaan."""
import math
import re
import unicodedata
from collections import Counter
from typing import Dict, Iterable, List, Set

# kata pembuka judul test case yang tidak menambah makna
_OPENERS = re.compile(
    r"^(verify|verifikasi|memverifikasi|validate|validasi|memvalidasi|check|cek|mengecek|memeriksa|periksa|ensure|"
    r"memastikan|pastikan|test|tes|menguji|uji|confirm|konfirmasi)\b( that| bahwa| jika| apakah| if)?\s*", re.I)

# kata bermakna sama (Indonesia/Inggris) -> satu bentuk. Dipakai untuk mencocokkan, bukan mengubah test case.
_SYN_GROUPS = [
    ("tampil", "tampilkan", "ditampilkan", "menampilkan", "muncul", "memunculkan", "displayed", "display", "shown",
     "show", "appears", "appear", "visible", "terlihat"),
    ("berhasil", "sukses", "success", "successful", "successfully", "valid"),
    ("gagal", "failed", "fail", "failure", "ditolak", "menolak", "tolak", "rejected", "reject", "invalid", "error"),
    ("tombol", "button", "btn", "cta"),
    ("kolom", "field", "isian", "input", "textbox", "inputan"),
    ("halaman", "page", "screen", "layar"),
    ("pesan", "message", "notifikasi", "notification", "alert", "toast"),
    ("klik", "click", "tap", "tekan", "pilih", "select", "choose"),
    ("isi", "mengisi", "diisi", "enter", "type", "fill", "masukkan", "memasukkan", "ketik"),
    ("kosong", "empty", "blank", "null"),
    ("wajib", "required", "mandatory", "harus"),
    ("simpan", "save", "menyimpan", "disimpan", "submit", "kirim"),
    ("hapus", "delete", "remove", "menghapus", "dihapus"),
    ("ubah", "edit", "update", "mengubah", "diubah", "perbarui"),
    ("tambah", "add", "create", "menambah", "ditambahkan", "buat", "membuat"),
    ("masuk", "login", "signin", "log-in"),
    ("keluar", "logout", "signout"),
    ("pengguna", "user", "users", "akun", "account"),
    ("kata-sandi", "password", "sandi", "katasandi", "pwd"),
    ("surel", "email", "e-mail"),
    ("karakter", "character", "characters", "char", "chars", "huruf"),
    ("maksimal", "maximum", "max", "maks", "paling banyak"),
    ("minimal", "minimum", "min", "paling sedikit"),
    ("angka", "digit", "digits", "numeric", "number", "nomor"),
    ("tidak", "not", "no", "bukan", "tanpa", "without", "cannot", "can't", "tak"),
]
_SYN: Dict[str, str] = {}
for grp in _SYN_GROUPS:
    for w in grp:
        _SYN[w] = grp[0]

_STOP = set("""a an the of to and or for with in on at by is are be as it this that from into dan atau yang untuk dengan
di ke dari pada oleh adalah akan sudah telah dapat bisa ini itu sebagai saat ketika sesuai secara agar supaya maka
para suatu sebuah se nya lalu kemudian then when should will""".split())

# kata yang menandai hasil positif / negatif (untuk mendeteksi hasil yang bertentangan)
_POS = {"berhasil", "tampil", "diterima", "accepted", "accept", "allowed", "boleh", "aktif", "enabled", "tersimpan"}
_NEG = {"gagal", "tidak", "disabled", "nonaktif", "blocked", "diblokir", "terkunci", "locked", "pesan"}


def fold(s: str) -> str:
    s = unicodedata.normalize("NFKD", str(s or "")).encode("ascii", "ignore").decode("ascii")
    return re.sub(r"\s+", " ", s.lower()).strip()


def strip_opener(title: str) -> str:
    t = fold(title)
    for _ in range(2):
        t = _OPENERS.sub("", t).strip(" :-")
    return t


def tokens(s: str) -> List[str]:
    out = []
    for w in re.findall(r"[a-z0-9]+(?:[-'][a-z0-9]+)*", fold(s)):
        w = _SYN.get(w, w)
        if w in _STOP or (len(w) == 1 and not w.isdigit()):
            continue
        if len(w) > 4 and not w.isdigit():  # imbuhan sederhana: "fields"/"field", "ditampilkan" sudah disinonimkan
            w = re.sub(r"(nya|kan|lah|ing|ed|es|s)$", "", w) or w
        out.append(w)
    return out


def norm_text(s: str) -> str:
    return " ".join(tokens(s))


def numbers(s: str) -> Set[str]:
    return set(re.findall(r"\d+(?:[.,]\d+)?", str(s or "")))


def data_values(s: str) -> Set[str]:
    """Nilai di Test Data ("Email: a@b.com; Umur: 30" -> {"a@b.com", "30"}). Urutan tidak berpengaruh."""
    raw = str(s or "").strip()
    if not raw or raw in ("-", "contoh"):
        return set()
    parts = re.split(r"[;\n]|,(?=\s*[A-Za-z][\w ]{0,30}:)", raw)
    vals = set()
    for p in parts:
        v = p.split(":", 1)[1] if ":" in p else p
        stripped = fold(v).strip(" \"'")
        if stripped:
            vals.add(stripped)
        elif re.search(r"[\"']\s*[\"']", v):  # Email: "" -> nilai kosong yang sengaja diuji
            vals.add("<kosong>")
    return vals


def data_key(s: str) -> str:
    return "|".join(sorted(data_values(s)))


def jaccard(a: Iterable, b: Iterable) -> float:
    a, b = set(a), set(b)
    if not a and not b:
        return 1.0
    if not a or not b:
        return 0.0
    return len(a & b) / len(a | b)


class Tfidf:
    """Kemiripan kata berbobot: kata yang jarang (khas) lebih berarti daripada kata umum."""

    def __init__(self, docs: List[List[str]]):
        n = max(1, len(docs))
        df = Counter(w for d in docs for w in set(d))
        self.idf = {w: math.log((1 + n) / (1 + c)) + 1 for w, c in df.items()}

    def vec(self, toks: List[str]) -> Dict[str, float]:
        tf = Counter(toks)
        v = {w: c * self.idf.get(w, 1.0) for w, c in tf.items()}
        norm = math.sqrt(sum(x * x for x in v.values())) or 1.0
        return {w: x / norm for w, x in v.items()}


def cosine(a: Dict[str, float], b: Dict[str, float]) -> float:
    if not a or not b:
        return 0.0
    if len(a) > len(b):
        a, b = b, a
    return sum(x * b.get(w, 0.0) for w, x in a.items())


def vcos(a: List[float], b: List[float]) -> float:
    if not a or not b:
        return 0.0
    num = sum(x * y for x, y in zip(a, b))
    da = math.sqrt(sum(x * x for x in a)) or 1.0
    db = math.sqrt(sum(y * y for y in b)) or 1.0
    return num / (da * db)


def outcome(expected: str, category: str = "") -> str:
    """'pos' / 'neg' / '' dari hasil harapan (dan jenis Positive/Negative bila ada)."""
    c = fold(category)
    if c.startswith("pos"):
        return "pos"
    if c.startswith("neg"):
        return "neg"
    toks = tokens(expected)
    pos = neg = 0
    skip = False
    for i, w in enumerate(toks):
        if skip:
            skip = False
            continue
        if w == "tidak" and i + 1 < len(toks) and toks[i + 1] in _POS:  # "tidak tampil" = negatif
            neg += 1
            skip = True
        elif w in _NEG:
            neg += 1
        elif w in _POS:
            pos += 1
    if neg > pos:
        return "neg"
    if pos > neg:
        return "pos"
    return ""
