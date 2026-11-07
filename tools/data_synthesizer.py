# tools/data_synthesizer.py
"""
Sintesis nilai uji deterministik (tanpa LLM). Panjang nilai SELALU persis sesuai permintaan,
jadi judul "100 karakter" pasti berisi data 100 karakter.

Tipe data: email, phone, password, digits, alnum, text
"""

import math
import re
from typing import Dict, List, Optional

_EMAIL_RE = re.compile(r"^[A-Za-z0-9._%+-]+@([A-Za-z0-9-]+\.)+[A-Za-z]{2,}$")

DATA_LABEL = {
    "email": "Email",
    "phone": "Nomor telepon",
    "password": "Password",
    "digits": "Nilai numerik",
    "alnum": "Kode alfanumerik",
    "text": "Nilai input",
}


def infer_data_type(context: str, unit: str = "") -> str:
    c = str(context or "").lower()
    if re.search(r"e-?mail|surel", c):
        return "email"
    if re.search(r"phone|telepon|telpon|\bhp\b|msisdn|nomor ponsel", c):
        return "phone"
    if re.search(r"password|kata sandi|passcode|\bpin\b", c):
        return "password"
    if unit == "digit":
        return "digits"
    if re.search(r"alphanumeric|alfanumerik", c):
        return "alnum"
    return "text"


def _digits(n: int, seed: str = "628123456789") -> str:
    base = (seed * (n // len(seed) + 1))[:n]
    return base


def make_email(n: int) -> str:
    """Email valid dengan panjang total tepat n (local<=64, label<=63)."""
    if n < 7:
        return "a@b.co"[:max(n, 1)]
    tld = ".test"
    remaining = n - 1 - len(tld)          # tanpa '@' dan '.test'
    local = max(1, min(64, remaining // 2 if remaining > 20 else remaining - 1))
    dom = remaining - local               # panjang bagian domain (termasuk titik antar label)
    if dom < 1:
        local, dom = remaining - 1, 1
    k = max(1, math.ceil((dom + 1) / 61))  # jumlah label
    letters = dom - (k - 1)
    while letters < k:                     # tiap label minimal 1 huruf
        k -= 1
        letters = dom - (k - 1)
    base, extra = divmod(letters, k)
    labels = []
    for i in range(k):
        ln = base + (1 if i < extra else 0)
        labels.append(("d" * ln))
    local_part = ("qa" + "x" * local)[:local] if local >= 2 else "q"
    email = f"{local_part}@{'.'.join(labels)}{tld}"
    if len(email) != n or not _EMAIL_RE.match(email):
        email = ("q" * (n - 13)) + "@example.test" if n > 13 else "qa@example.test"[:n]
    return email


def make_password(n: int) -> str:
    """Password yang memenuhi komposisi (upper, lower, digit, special) dengan panjang n."""
    core = "Aa1@"
    filler = "Qwerty7#xYz"
    if n <= 0:
        return ""
    if n < 4:
        return core[:n]
    return (core + (filler * (n // len(filler) + 1)))[: n]


def make_alnum(n: int) -> str:
    pool = "A1B2C3D4E5F6G7H8J9K0"
    return (pool * (n // len(pool) + 1))[:n]


def make_text(n: int) -> str:
    return ("a" * n)


def make_value(data_type: str, n: int, hints: Optional[Dict[str, str]] = None) -> str:
    n = max(0, int(n))
    if data_type == "email":
        return make_email(n)
    if data_type == "phone":
        return _digits(n)
    if data_type == "password":
        return make_password(n)
    if data_type == "digits":
        return _digits(n, "583920")
    if data_type == "alnum":
        return make_alnum(n)
    return make_text(n)


def baseline_valid(data_type: str, hints: Optional[Dict[str, str]] = None, length: int = 0) -> str:
    """Nilai valid 'normal'. Pakai contoh dari section Test Data PRD bila ada & cocok panjangnya."""
    hints = hints or {}
    keys = {
        "email": ("email",), "phone": ("phone", "telepon"), "password": ("password",),
        "digits": ("otp", "code"), "alnum": ("backup", "code"), "text": (),
    }.get(data_type, ())
    for label, val in hints.items():
        if any(k in label for k in keys):
            if not length or len(val) == length:
                return val
    return make_value(data_type, length or {"email": 24, "phone": 12, "password": 16,
                                            "digits": 6, "alnum": 8}.get(data_type, 10))


# ----- nilai tidak valid per kelas ekuivalen ------------------------------------------
def invalid_email_variants() -> List[Dict[str, str]]:
    return [
        {"label": "tanpa karakter @", "value": "user.qa.test.example.test"},
        {"label": "tanpa domain setelah @", "value": "user.qa.test@"},
        {"label": "mengandung spasi", "value": "user qa@example.test"},
        {"label": "dua karakter @", "value": "user@@example.test"},
    ]


def with_non_digit(valid_digits: str) -> str:
    if not valid_digits:
        return "A"
    return valid_digits[:-1] + "A" if len(valid_digits) > 1 else "A"


def with_symbol(valid: str) -> str:
    if not valid:
        return "#"
    return valid[:-1] + "#" if len(valid) > 1 else "#"


def password_missing_class(length: int, missing: str) -> str:
    """Password panjang `length` yang SENGAJA tidak punya satu kelas karakter."""
    pools = {
        "upper": "ABCDEFGHJKLMNPQRSTUVWXYZ",
        "lower": "abcdefghjkmnpqrstuvwxyz",
        "digit": "23456789",
        "special": "@#$%",
    }
    order = ["upper", "lower", "digit", "special"]
    present = [c for c in order if c != missing]
    seq = ""
    i = 0
    while len(seq) < length:
        pool = pools[present[i % len(present)]]
        seq += pool[(i // len(present)) % len(pool)]
        i += 1
    return seq[:length]


def fmt_duration(seconds: int) -> str:
    """Format durasi Indonesia: 899 -> '14 menit 59 detik'."""
    seconds = int(seconds)
    if seconds <= 0:
        return "0 detik"
    parts = []
    for name, size in (("hari", 86400), ("jam", 3600), ("menit", 60), ("detik", 1)):
        q, seconds = divmod(seconds, size)
        if q:
            parts.append(f"{q} {name}")
    return " ".join(parts)
