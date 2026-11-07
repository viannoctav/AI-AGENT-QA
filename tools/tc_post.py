# tools/tc_post.py
"""
Post-processing deterministik (tanpa LLM) untuk hasil generate:

  - dedup_tcs()          : buang TC duplikat (judul + test data + kategori), traceability digabung
  - apply_priority()     : Positive -> High, Negative -> Medium (aturan Reference perusahaan)
  - select_obligations() : bila jumlah obligation > cap, pilih berbasis kuota teknik (bukan urutan prioritas)
  - is_generic_*()       : deteksi teks generik (expected/precondition) agar tidak lolos sebagai TC
"""

import re
from collections import OrderedDict, defaultdict
from difflib import SequenceMatcher
from typing import Any, Dict, List, Optional, Tuple

DEFAULT_PRIORITY_RULE = {"Positive": "High", "Negative": "Medium"}

# ------------------------------------------------------------------ teks generik
_GENERIC_EXPECTED = [re.compile(p, re.I) for p in (
    r"sesuai\s+(dengan\s+)?(deskripsi|aturan|requirement|prd|prosedur|spesifikasi)",
    r"\balur\s+berhasil\b",
    r"perilaku\s+sistem\s+sesuai",
    r"sistem\s+berjalan\s+(dengan\s+)?(normal|baik)",
)]
_GENERIC_PRECOND = [re.compile(p, re.I) for p in (
    r"kondisi\s+awal\s+sistem",
    r"sesuai\s+skenario",
    r"^siapkan\s+kondisi",
    r"^kondisi\s+awal\.?$",
)]
_EN_WORDS = re.compile(r"\b(must|shall|should|the|system|user|with|and|when|that|enforce|allow|only|for)\b", re.I)
_CJK = re.compile(r"[\u3040-\u30ff\u3400-\u9fff\uac00-\ud7af]")


def has_cjk(text: str) -> bool:
    return bool(_CJK.search(text or ""))


def is_generic_expected(text: str) -> bool:
    t = (text or "").strip()
    if not t:
        return True
    if any(p.search(t) for p in _GENERIC_EXPECTED):
        return True
    body = re.sub(r"^(berhasil|gagal|ditolak)\s*[.:,-]?\s*", "", t, flags=re.I).strip(" .")
    return len(body.split()) < 3  # "Berhasil." / "Gagal. Ditolak" tanpa hasil konkret


_TRUNCATED = re.compile(
    r"(tampil|tampilan|muncul|menampilkan|ditampilkan|memunculkan|keluar)\s+(sebuah\s+|suatu\s+)?"
    r"(pesan|notifikasi|peringatan|error)(\s+(error|kesalahan))?\s*[.:]?\s*$", re.I)


def is_truncated_expected(text: str) -> bool:
    """'Gagal, tampil pesan' / 'Gagal:' -> kalimat berhenti sebelum menyebut hasil/alasan konkret."""
    t = (text or "").strip()
    return bool(_TRUNCATED.search(t)) or t.endswith(":") or t.endswith(",")


_POS_START = re.compile(r"^\s*(berhasil|sukses|diterima)\b", re.I)
_NEG_WORDS = re.compile(r"\b(menolak|ditolak|penolakan)\b", re.I)


def is_self_contradicting(text: str) -> bool:
    """'Berhasil. Sistem menolak kode baru ...' -> diawali sukses tetapi memuat penolakan (kecuali dinegasikan: 'tidak menolak')."""
    t = text or ""
    if not _POS_START.search(t):
        return False
    for m in _NEG_WORDS.finditer(t):
        if re.search(r"(tidak|tanpa|belum|bukan)\s*$", t[max(0, m.start() - 8):m.start()].lower()):
            continue
        return True
    return False


def leaked_test_values(precondition: str, data_text: str) -> list:
    """Nilai uji (>=5 karakter, mengandung angka/simbol) yang ikut tertulis di prekondisi."""
    pre = (precondition or "").lower()
    out = []
    for line in (data_text or "").splitlines():
        if ":" not in line:
            continue
        v = line.split(":", 1)[1].strip()
        if len(v) >= 5 and not re.search(r"\s", v) and not re.fullmatch(r"[A-Z0-9_]+", v) \
                and re.search(r"[\d@#_.]", v) and v.lower() in pre:
            out.append(v)
    return out


def strip_leaked(precondition: str, data_text: str) -> str:
    """Ganti nilai uji yang bocor di prekondisi dengan rujukan ke kolom Test Data (tanpa memanggil LLM)."""
    for v in leaked_test_values(precondition, data_text):
        precondition = re.sub(re.escape(v), "nilai pada Test Data", precondition, flags=re.I)
    return precondition


def is_generic_precondition(text: str) -> bool:
    t = (text or "").strip()
    if not t or t == "-":
        return False  # "-" = memang tidak ada prekondisi (gaya Reference)
    return any(p.search(t) for p in _GENERIC_PRECOND)


def english_ratio_high(text: str) -> bool:
    """Judul yang menyalin kalimat PRD berbahasa Inggris (>=2 kata fungsi Inggris)."""
    return len(_EN_WORDS.findall(text or "")) >= 2


# ------------------------------------------------------------------ priority
def apply_priority(tcs: List[Dict[str, Any]], rule: Optional[Dict[str, str]] = None) -> int:
    """Set priority deterministik dari kategori. Return jumlah TC yang berubah."""
    rule = rule or DEFAULT_PRIORITY_RULE
    changed = 0
    for t in tcs:
        want = rule.get(t.get("category", ""))
        if want and t.get("priority") != want:
            t["priority"] = want
            changed += 1
    return changed


# ------------------------------------------------------------------ dedup
_SOURCE_RANK = {"llm": 0, "template": 1, "llm-unverified": 2, "skeleton": 3}


def _norm(s: Any) -> str:
    s = str(s or "").lower()
    s = re.sub(r"[^\w\s]", " ", s)
    return re.sub(r"\s+", " ", s).strip()


def _norm_data(s: Any) -> str:
    n = _norm(s)
    return "" if n in ("", "-", "nan") else n


def _nums(s: str) -> Tuple[str, ...]:
    return tuple(sorted(re.findall(r"\d+", s or "")))


def _key(t: Dict[str, Any]) -> Tuple[str, str, str]:
    return (_norm(t.get("title")), _norm_data(t.get("test_data")), t.get("category", ""))


def _same_expected(a: Dict[str, Any], b: Dict[str, Any]) -> bool:
    return _norm(a.get("expected_result")) == _norm(b.get("expected_result"))


def _feat(t: Dict[str, Any]) -> str:
    """Fitur yang diuji (Sub Module); Module/Menu sama untuk satu PRD."""
    sub = t.get("sub_label")
    return f"{t.get('module')}/{sub}" if sub and sub != "-" else str(t.get("module"))


def _is_dup(a: Dict[str, Any], b: Dict[str, Any], threshold: float) -> bool:
    if a.get("category") != b.get("category"):
        return False
    if _norm_data(a.get("test_data")) != _norm_data(b.get("test_data")):
        return False
    ta, tb = _norm(a.get("title")), _norm(b.get("title"))
    if ta == tb:
        # judul+data sama. Bila data kosong, wajib satu modul atau expected sama
        # (hindari menggabung "login berhasil" milik dua modul berbeda).
        return _feat(a) == _feat(b)  # fitur berbeda (mis. kode cadangan vs token reset) tidak pernah digabung
    if _nums(ta) != _nums(tb) or _feat(a) != _feat(b):
        return False
    return SequenceMatcher(None, ta, tb).ratio() >= threshold


def _ids(t: Dict[str, Any], key_one: str, key_many: str) -> List[str]:
    out = list(t.get(key_many) or [])
    if t.get(key_one) and t[key_one] not in out:
        out.insert(0, t[key_one])
    return out


def dedup_tcs(tcs: List[Dict[str, Any]], threshold: float = 0.95
              ) -> Tuple[List[Dict[str, Any]], List[Dict[str, Any]]]:
    """
    Gabungkan TC duplikat. Yang dipertahankan: sumber terbaik (llm > template > ...), posisi tetap di
    urutan pertama kemunculan. requirement_ids / obligation / atom dari duplikat digabung ke TC yang dipakai,
    sehingga coverage & traceability tidak turun.
    Return (unik, removed) ; removed = [{ob_id, kept_ob_id, title}].
    """
    groups: "OrderedDict[int, List[Dict[str, Any]]]" = OrderedDict()
    exact: Dict[Tuple[str, str, str], int] = {}
    for t in tcs:
        gid = None
        k = _key(t)
        if k in exact and _is_dup(groups[exact[k]][0], t, threshold):
            gid = exact[k]
        else:
            for g, members in groups.items():
                if _is_dup(members[0], t, threshold):
                    gid = g
                    break
        if gid is None:
            gid = len(groups)
            groups[gid] = []
            exact.setdefault(k, gid)
        groups[gid].append(t)

    unique: List[Dict[str, Any]] = []
    removed: List[Dict[str, Any]] = []
    for members in groups.values():
        best = min(members, key=lambda m: (_SOURCE_RANK.get(m.get("source", "llm"), 9), members.index(m)))
        if len(members) == 1:
            best.setdefault("merged_ob_ids", [])
            best["atom_ids"] = _ids(best, "atom_id", "atom_ids")
            unique.append(best)
            continue
        req: List[str] = []
        obs: List[str] = []
        atoms: List[str] = []
        for m in members:
            for r in m.get("requirement_ids", []):
                if r not in req:
                    req.append(r)
            for o in _ids(m, "ob_id", "merged_ob_ids"):
                if o not in obs:
                    obs.append(o)
            for a in _ids(m, "atom_id", "atom_ids"):
                if a not in atoms:
                    atoms.append(a)
            if m is not best:
                removed.append({"ob_id": m.get("ob_id"), "kept_ob_id": best.get("ob_id"), "title": m.get("title", "")})
        best["requirement_ids"] = req
        best["merged_ob_ids"] = [o for o in obs if o != best.get("ob_id")]
        best["atom_ids"] = atoms
        unique.append(best)
    return unique, removed


# ------------------------------------------------------------------ cap berbasis kuota
def select_obligations(obs: List[Dict[str, Any]], cap: Optional[int]) -> List[Dict[str, Any]]:
    """
    Jika len(obs) <= cap (atau cap kosong) -> semua dipakai.
    Jika tidak: (1) pastikan tiap atom aturan punya >=1 obligation, lalu (2) isi sisa kuota
    round-robin antar teknik. Urutan dokumen PRD dipertahankan.
    """
    if not cap or len(obs) <= int(cap):
        return list(obs)
    cap = int(cap)
    chosen: Dict[str, Dict[str, Any]] = OrderedDict()

    by_atom: Dict[str, List[Dict[str, Any]]] = OrderedDict()
    for o in obs:
        by_atom.setdefault(o["atom_id"], []).append(o)
    tech_count: Dict[str, int] = defaultdict(int)
    for cands in by_atom.values():  # (1) satu per atom, pilih teknik yang paling sedikit terwakili
        if len(chosen) >= cap:
            break
        o = min(cands, key=lambda c: (tech_count[c["technique"]], cands.index(c)))
        chosen[o["ob_id"]] = o
        tech_count[o["technique"]] += 1

    by_tech: Dict[str, List[Dict[str, Any]]] = defaultdict(list)  # (2) round-robin teknik
    for o in obs:
        if o["ob_id"] not in chosen:
            by_tech[o["technique"]].append(o)
    queues = sorted(by_tech.values(), key=lambda q: (tech_count[q[0]["technique"]], len(q)))
    while len(chosen) < cap and any(queues):
        for q in queues:
            if q and len(chosen) < cap:
                o = q.pop(0)
                chosen[o["ob_id"]] = o
    return [o for o in obs if o["ob_id"] in chosen]