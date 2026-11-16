# tools/tc_normalize.py
"""
Normalisasi deterministik (tanpa LLM) yang dipanggil di verifier setelah draft LLM dibaca.
Hanya perbaikan yang AMAN (tidak mengubah makna):

  - judul: buang bocoran format contoh ("... | Expected: ..."), penanda internal "(Kombinasi N)",
           dan angka telanjang di ujung judul yang tidak ada di skenario/aturan/data (indeks posisi batch)
  - test_data: dict/list/JSON -> baris "Label: nilai"
  - expected: pemisah eksplisit ("Gagal, ..." / "Berhasil: ...") jadi "Gagal. ..."; "A = B" mentah -> "A bernilai B";
              "Berhasil <kata benda subjek>" -> "Berhasil. <Subjek> ..." (tidak pernah menyisipkan titik setelah "Gagal"
              berdasarkan kata subjek, karena "Gagal login ..." / "Gagal akses ..." bukan kalimat dua bagian)
  - prekondisi: "State awal = X; State awal pengguna adalah X" -> satu kalimat
"""

import ast
import json
import re
from typing import Any, Dict, Set

_LEAK = re.compile(r"\s*\|\s*(expected(\s+result)?|hasil\s+yang\s+diharapkan)\s*:.*$", re.I | re.S)
_COMBO = re.compile(r"\s*[\(\[]\s*kombinasi\s*#?\s*\d+\s*[\)\]]\s*$|\s+kombinasi\s*#?\s*\d+\s*$", re.I)
_TRAIL_NUM = re.compile(r"(?<=[^\d\s#])\s+#?(\d{1,4})\s*$")


# kata benda yang pasti berperan sebagai SUBJEK bila langsung mengikuti "Berhasil" ("Berhasil token akses ...")
_BERHASIL_SUBJ = {
    "sistem", "kode", "token", "semua", "seluruh", "permintaan", "kunci", "data", "pengguna", "akun", "nilai",
    "input", "status", "state", "hitungan", "notifikasi", "halaman", "sesi", "event", "log", "proses",
    "penguncian", "pengaturan", "perubahan", "password", "email", "pesan",
}


def _ints(*texts: Any) -> Set[int]:
    out: Set[int] = set()
    for t in texts:
        out.update(int(x) for x in re.findall(r"\d+", str(t or "")) if len(x) < 9)
    return out


def format_test_data(value: Any) -> str:
    """dict / list / string JSON atau repr dict Python -> baris 'Label: nilai'."""
    data = value
    if isinstance(value, str):
        s = value.strip()
        if s[:1] not in ("{", "["):
            return s
        data = None
        for loader in (json.loads, ast.literal_eval):
            try:
                data = loader(s)
                break
            except Exception:
                continue
        if data is None:
            return s
    if isinstance(data, dict):
        lines = []
        for k, v in data.items():
            # nama kunci apa adanya; penyamaan dengan nama field PRD dilakukan di tahap coverage (unify_field_labels)
            label = str(k).replace("_", " ").strip()
            label = label[:1].upper() + label[1:]
            lines.append(f"{label}: {format_test_data(v) if isinstance(v, (dict, list)) else v}")
        return "\n".join(lines)
    if isinstance(data, list):
        return "\n".join(format_test_data(x) if isinstance(x, (dict, list)) else str(x) for x in data)
    return str(value or "").strip()


# judul test case menguji fitur, bukan "alur": "Verifikasi alur keluar aplikasi" -> "Verifikasi keluar aplikasi"
_ALUR = re.compile(r"\b(alur|flow)\s+(?=\S)", re.I)


def clean_title(title: str, keep: Set[int]) -> str:
    t = _LEAK.sub("", title or "").strip()
    t = _ALUR.sub("", t).strip()
    t = _COMBO.sub("", t).strip()
    m = _TRAIL_NUM.search(t)
    if m and int(m.group(1)) not in keep:
        t = t[:m.start()].rstrip(" ,;:-")
    t = _COMBO.sub("", t).strip()
    return t


def clean_expected(text: str) -> str:
    t = (text or "").strip()
    if not t:
        return t
    t = re.sub(r"(?<=\w)\s=\s(?=\w)", " bernilai ", t)
    m = re.match(r"^(Berhasil|Gagal|Ditolak)(\s*)([,:;]|\s-\s)\s*(.*)$", t, re.S)
    if m:  # pemisah eksplisit -> "Gagal. Tampil ..."
        rest = m.group(4)
        return f"{m.group(1)}. {rest[:1].upper() + rest[1:]}" if rest else f"{m.group(1)}."
    m = re.match(r"^(Berhasil)\s+([A-Za-z]+)\b(.*)$", t, re.S)
    if m and m.group(2).lower() in _BERHASIL_SUBJ:
        return f"Berhasil. {m.group(2).capitalize()}{m.group(3)}"
    return t


def clean_preconditions(pre: str) -> str:
    p = (pre or "").strip()
    m = re.match(r"^State awal\s*=\s*([A-Za-z0-9_]+)\s*;\s*(.+)$", p, re.S)
    if m and m.group(1).lower() in m.group(2).lower():
        return m.group(2).strip()
    return p


def has_placeholder(text: str) -> bool:
    return bool(re.search(r"sesuai\s+aturan\s+PRD", text or "", re.I))


def normalize_tc(tc: Dict[str, Any], ob: Dict[str, Any]) -> Dict[str, Any]:
    scenario = re.sub(r"#\s*\d+", "", ob.get("scenario", ""))  # indeks "kombinasi #N" bukan angka bermakna
    keep = _ints(scenario, ob.get("rule_text"), ob.get("expect_text"), ob.get("data_text"), tc.get("test_data"),
                 *[a for a in ob.get("aliases", [])])
    tc["title"] = clean_title(tc.get("title", ""), keep)
    tc["expected_result"] = clean_expected(tc.get("expected_result", ""))
    tc["preconditions"] = clean_preconditions(tc.get("preconditions", ""))
    return tc
