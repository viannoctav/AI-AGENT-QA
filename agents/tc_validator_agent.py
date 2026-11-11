# agents/tc_validator_agent.py
"""
TC Validator: validasi keras (tanpa LLM) untuk test case hasil generate.
Cek: struktur, istilah dari domain lain, status/state karangan, requirement ID dalam scope,
dan duplikat. TC valid dari percobaan sebelumnya pada submodule yang sama ikut dipertahankan.
"""

import json
import re
from difflib import SequenceMatcher
from pathlib import Path
from typing import Dict, List, Tuple

FORBIDDEN_FILE = Path("knowledge") / "forbidden_terms.json"
_DEFAULT_FORBIDDEN = [
    "behavior monitoring", "deep profiling", "monitored target", "monitored location",
    "transaction tracking", "customer profiling", "behavior analysis",
]

# Token HURUF BESAR >= 4 karakter (mis. FAILED_FINAL, TIDAK, DIPROSES)
_CAPS_RE = re.compile(r"\b[A-Z][A-Z_]{3,}\b")
_COMMON_CAPS = {
    "HTTP", "HTTPS", "JSON", "TRUE", "FALSE", "NULL", "NONE", "EMAIL", "POST", "GET",
    "PUT", "DELETE", "PATCH", "HTML", "CSRF", "TOKEN", "SMTP", "UUID", "ISO", "UTF",
}

DUPLICATE_THRESHOLD = 0.9

# Awal "expected result" yang menentukan polaritas skenario
_NEG_START = ("gagal", "tidak berhasil", "ditolak", "akses ditolak", "sistem menolak",
              "menolak", "tidak dapat", "tidak bisa", "tidak diizinkan",
              "sistem menampilkan pesan error", "sistem memblokir", "sistem mencegah",
              "tindakan ditolak")
_POS_START = ("berhasil",)


def load_forbidden_terms() -> List[str]:
    terms = list(_DEFAULT_FORBIDDEN)
    try:
        data = json.loads(FORBIDDEN_FILE.read_text(encoding="utf-8"))
        extra = data.get("terms", []) if isinstance(data, dict) else data
        terms.extend(str(t).lower().strip() for t in extra if str(t).strip())
    except Exception:
        pass
    return sorted(set(terms))


def validate_test_case_requirement_ids(
    test_case: Dict,
    target_requirement_ids: List[str]
) -> Tuple[bool, str]:
    tc_req_ids = test_case.get("requirement_ids", [])

    if not tc_req_ids:
        return False, f"TC '{test_case.get('title', 'unknown')}': missing requirement_ids"

    if not isinstance(tc_req_ids, list):
        return False, f"TC '{test_case.get('title', 'unknown')}': requirement_ids must be a list"

    target_set = set(str(rid).upper() for rid in target_requirement_ids)
    tc_set = set(str(rid).upper() for rid in tc_req_ids)

    out_of_scope = tc_set - target_set
    if out_of_scope:
        return False, (
            f"TC '{test_case.get('title', 'unknown')}': "
            f"out-of-scope requirements {sorted(out_of_scope)} not in target"
        )

    return True, ""


def validate_test_case_structure(test_case: Dict) -> Tuple[bool, str]:
    required_fields = ["title", "category", "preconditions", "steps", "expected_result"]

    for field in required_fields:
        if not test_case.get(field):
            return False, f"Missing required field: {field}"

    category = str(test_case.get("category", "")).strip().lower()
    if category not in ["positive", "negative"]:
        return False, f"Invalid category '{category}' (must be 'Positive' or 'Negative')"

    return True, ""


def _tc_text(test_case: Dict) -> str:
    return " ".join(
        str(test_case.get(k, ""))
        for k in ("title", "preconditions", "steps", "expected_result")
    )


def validate_no_hallucinated_features(
    test_case: Dict,
    prd_context: str = ""
) -> Tuple[bool, str]:
    """Tolak istilah dari domain lain, KECUALI istilah itu memang ada di PRD yang sedang dijalankan."""
    content = _tc_text(test_case).lower()
    prd_lower = str(prd_context or "").lower()

    for term in load_forbidden_terms():
        if term in content and term not in prd_lower:
            return False, f"TC contains foreign term '{term}' not in PRD"

    return True, ""


_ACRONYM = re.compile(r"\b[A-Z][A-Z0-9]{1,5}\b")
_TECH_ACRONYM = {"ID", "OK", "URL", "API", "PDF", "JPG", "JPEG", "PNG", "CSV", "XLSX", "UI", "QA", "HTTP", "HTTPS", "IP",
                 "MB", "KB", "GB", "WIB", "AM", "PM", "NA", "N/A"}


def foreign_acronyms(test_case: Dict, prd_context: str = "") -> List[str]:
    """Singkatan HURUF BESAR (mis. MFA, OTP, SKU) yang dipakai TC tetapi TIDAK ada di PRD ini -> kemungkinan istilah
    bocoran dari PRD/proyek lain. Nilai uji yang diketik QA (bagian setelah ':' di Test Data, teks berkutip) diabaikan."""
    if not prd_context:
        return []
    prd_tokens = {t.upper() for t in re.findall(r"\b[A-Za-z0-9]+\b", prd_context)}
    td_values = " ".join(l.split(":", 1)[1] for l in str(test_case.get("test_data") or "").splitlines() if ":" in l)
    text = " ".join([_tc_text(test_case), str(test_case.get("test_data") or "")])
    text = re.sub(r"['\"\u201c\u2018][^'\"\u201d\u2019]{1,60}['\"\u201d\u2019]", " ", text)
    values = set(_ACRONYM.findall(td_values))
    out = sorted({t for t in _ACRONYM.findall(text)
                  if t not in prd_tokens and t not in _TECH_ACRONYM and t not in values and not t.isdigit()
                  and not re.fullmatch(r"(FR|NFR|BR|AC|TC|OB)\d*", t)})
    return out


def validate_no_invented_states(test_case: Dict, prd_context: str = "") -> Tuple[bool, str]:
    """Tolak status/state berhuruf besar yang tidak ada di PRD (mis. 'TIDAK DIPROSES')."""
    if not prd_context:
        return True, ""

    prd_caps = set(_CAPS_RE.findall(prd_context))
    used = set(_CAPS_RE.findall(_tc_text(test_case)))
    # nilai yang DIINPUT QA (Test Data, teks berkutip, "dengan ABCDE") adalah data uji, bukan nama status
    data_src = " ".join([str(test_case.get("test_data") or "")] +
                        re.findall(r"['\"\u201c\u2018]([^'\"\u201d\u2019]{1,60})['\"\u201d\u2019]", _tc_text(test_case)) +
                        re.findall(r"\b(?:dengan|nilai|isi|masukkan|ketik|input)\s+([A-Z][A-Z_]{3,})\b", _tc_text(test_case), re.I))
    data_caps = set(_CAPS_RE.findall(data_src))
    invented = sorted(t for t in used if t not in prd_caps and t not in _COMMON_CAPS and t not in data_caps)

    if invented:
        return False, f"TC contains status/state not in PRD: {invented}"
    return True, ""


def autofix_category(tc: Dict) -> bool:
    """Samakan category dengan hasil yang diharapkan (mis. 'Gagal login...' pasti Negative)."""
    exp = str(tc.get("expected_result", "")).strip().lower()
    current = str(tc.get("category", "")).strip().capitalize()
    wanted = None
    if exp.startswith(_NEG_START):
        wanted = "Negative"
    elif exp.startswith(_POS_START):
        wanted = "Positive"
    if wanted and wanted != current:
        tc["category"] = wanted
        return True
    return False


def _norm_text(text: str) -> str:
    return re.sub(r"\s+", " ", re.sub(r"[^\w\s]", " ", str(text).lower())).strip()


def is_copied_expected(tc: Dict, others: List[Dict], min_len: int = 40) -> bool:
    """Expected result panjang yang identik dengan TC milik requirement LAIN = copy-paste LLM."""
    exp = _norm_text(tc.get("expected_result", ""))
    if len(exp) < min_len:
        return False
    reqs = _req_set(tc)
    for other in others:
        o_reqs = _req_set(other)
        if reqs and o_reqs and not (reqs & o_reqs) and _norm_text(other.get("expected_result", "")) == exp:
            return True
    return False



# ---------------------------------------------------------------------------
# Perapian & cek kewajaran isi TC (deterministik)
# ---------------------------------------------------------------------------
_ID = r"(?:NFR|FR|BR)-\d{3}"
_NEG_TITLE = ("kosong", "tidak valid", "salah", "kadaluwarsa", "kedaluwarsa", "expired", "tidak sesuai")
_RECOVERY = ("benar", "lalu", "kemudian", "setelah", "fallback", "backup", "cadangan", "berhasil")
_FLOW_SKIP = re.compile(
    r"mfa|otp|totp|sms|backup|cadangan|step-?up|token|sesi|session|logout|disable|nonaktif|aktifkan|enroll|ubah|ganti|reset",
    re.IGNORECASE,
)
_SQUOTED = re.compile(r"(?<![\w])'([^'\n]{3,})'(?![\w])")
_QUOTED = re.compile(r'["\u201c]([^"\u201c\u201d]{3,})["\u201d]')


def clean_title(title: str) -> str:
    """Buang ID requirement dari judul (ID ada di kolom traceability, bukan di judul)."""
    t = str(title or "")
    t = re.sub(rf"\s*\(\s*(?:{_ID}\s*[,/&]?\s*)+\)", "", t)
    t = re.sub(rf"\b(?:sesuai|dengan|untuk|pada)\s+requirement\s+{_ID}\b", "", t, flags=re.IGNORECASE)
    t = re.sub(rf"\b(?:untuk|pada|sesuai)\s+{_ID}\s*:?", "", t, flags=re.IGNORECASE)
    t = re.sub(rf"\s*[-\u2013:]?\s*\b{_ID}\b", "", t)
    t = re.sub(r"\s+", " ", t).strip(" -:,")
    return t


def strip_invented_messages(tc: Dict, prd_context: str) -> bool:
    """
    Pesan yang dikutip di expected result hanya boleh pesan yang memang didefinisikan PRD:
    ditulis dalam tanda kutip di PRD, atau berupa frasa pendek yang ada di PRD.
    Kalimat aturan panjang yang cuma disalin dari PRD (bukan pesan UI), dan kutipan yang
    tidak ada di PRD, dibuang.
    """
    if not prd_context:
        return False
    prd_norm = _norm_text(prd_context)
    prd_quoted = {_norm_text(m) for m in _QUOTED.findall(prd_context)}
    exp = str(tc.get("expected_result", ""))
    changed = False

    def repl(m):
        nonlocal changed
        msg = _norm_text(m.group(1))
        defined_as_message = msg in prd_quoted or (msg in prd_norm and len(msg.split()) <= 6)
        if defined_as_message:
            return m.group(0)
        changed = True
        return ""

    new_exp = _SQUOTED.sub(repl, _QUOTED.sub(repl, exp))
    if changed:
        new_exp = re.sub(r"\s+([.,])", r"\1", new_exp)
        new_exp = re.sub(r"\s+", " ", new_exp).strip()
        tc["expected_result"] = new_exp
    return changed


def fix_preconditions(tc: Dict) -> bool:
    """Tes login/registrasi tidak boleh berprekondisi 'sudah login'."""
    pre = str(tc.get("preconditions", "")).lower()
    title = str(tc.get("title", "")).lower()
    if not re.search(r"sudah login|telah login|berhasil login|sudah masuk", pre):
        return False
    if _FLOW_SKIP.search(title):
        return False
    # hanya test case yang MENGUJI login/registrasi itu sendiri (bukan "daftar pengajuan" atau "data masuk")
    if re.search(r"\bregist(rasi|er|ration)?\b|pendaftaran akun|daftar akun|\bsign ?up\b|membuat akun baru", title):
        tc["preconditions"] = "User belum login dan belum memiliki akun"
    elif re.search(r"\b(login|log in|sign ?in)\b|masuk ke (akun|aplikasi|sistem)", title):
        tc["preconditions"] = "User sudah memiliki akun terdaftar dan belum login"
    else:
        return False
    return True


def apply_autofixes(tc: Dict, prd_context: str = "") -> List[str]:
    """Perbaikan otomatis yang aman. Mengembalikan daftar catatan perbaikan."""
    notes = []
    if autofix_category(tc):
        notes.append(f"category diperbaiki menjadi {tc['category']} (mengikuti expected result)")
    new_title = clean_title(tc.get("title", ""))
    if new_title != tc.get("title"):
        tc["title"] = new_title
        notes.append("ID requirement dibuang dari judul")
    if strip_invented_messages(tc, prd_context):
        notes.append("kutipan pesan yang tidak ada di PRD dibuang")
    if fix_preconditions(tc):
        notes.append("prekondisi diperbaiki")
    return notes


def _example_values(text: str) -> List[str]:
    vals = re.findall(r"contoh\s*:\s*['\"\u2018\u201c]?([^)\n'\"\u2019\u201d]+)", text, flags=re.IGNORECASE)
    vals += re.findall(r"['\u2018]([^'\u2019\n]{3,})['\u2019]", text)
    return [v.strip() for v in vals if v.strip()]


def validate_consistency(tc: Dict) -> Tuple[bool, str]:
    """Tolak TC yang isinya bertentangan dengan dirinya sendiri."""
    title = str(tc.get("title", "")).lower()
    exp = str(tc.get("expected_result", "")).strip().lower()

    # 0) Teks template/placeholder yang bocor dari prompt
    if re.search(r"usulan langkah|\[langkah|\btodo\b|lorem ipsum", f"{title} {tc.get('steps', '')}", flags=re.IGNORECASE):
        return False, "Placeholder: langkah/judul berisi teks template, bukan langkah nyata"

    # 1) Judul skenario gagal, tetapi hasilnya "Berhasil"
    if exp.startswith("berhasil") and any(w in title for w in _NEG_TITLE) \
            and not any(w in title for w in _RECOVERY):
        return False, "Contradiction: judul skenario gagal tetapi expected result 'Berhasil'"

    # 2) Klaim panjang karakter tidak cocok dengan contoh data
    text = f"{tc.get('title', '')} {tc.get('steps', '')}"
    examples = _example_values(str(tc.get("steps", "")))
    if examples:
        m = re.search(r"(?:lebih dari|melebihi|>)\s*(\d+)\s*karakter", text, flags=re.IGNORECASE)
        if m and all(len(v) <= int(m.group(1)) for v in examples):
            return False, f"Contradiction: judul/langkah menyebut > {m.group(1)} karakter tetapi contoh data lebih pendek"
        m = re.search(r"kurang dari\s*(\d+)\s*karakter", text, flags=re.IGNORECASE)
        if m and all(len(v) >= int(m.group(1)) for v in examples):
            return False, f"Contradiction: judul/langkah menyebut < {m.group(1)} karakter tetapi contoh data lebih panjang"

    return True, ""


def _signature(tc: Dict) -> str:
    text = f"{tc.get('title', '')} {tc.get('steps', '')} {tc.get('expected_result', '')}"
    return re.sub(r"\s+", " ", re.sub(r"[^\w\s]", " ", text.lower())).strip()


def _req_set(tc: Dict) -> set:
    ids = tc.get("requirement_ids", []) or []
    return {str(r).upper() for r in ids}


def is_near_duplicate(tc: Dict, others: List[Dict], threshold: float = DUPLICATE_THRESHOLD) -> bool:
    """
    Duplikat = kategori sama, menguji requirement yang sama, memakai angka/nilai uji yang sama,
    dan isinya (judul+langkah+hasil) hampir identik. TC untuk requirement berbeda, atau dengan
    nilai uji berbeda (mis. 50 vs 51 karakter), BUKAN duplikat.
    """
    cat = str(tc.get("category", "")).strip().lower()
    sig = _signature(tc)
    nums = sorted(re.findall(r"\d+", sig))
    reqs = _req_set(tc)
    for other in others:
        if str(other.get("category", "")).strip().lower() != cat:
            continue
        o_reqs = _req_set(other)
        if reqs and o_reqs and not (reqs & o_reqs):
            continue
        o_sig = _signature(other)
        if sorted(re.findall(r"\d+", o_sig)) != nums:
            continue
        if SequenceMatcher(None, sig, o_sig).ratio() >= threshold:
            return True
    return False


def tc_validator_node(state: dict) -> dict:
    draft_tcs = state.get("draft_tcs", [])
    current_submodule = state.get("current_submodule", {}) or {}
    target_req_ids = current_submodule.get("requirement_ids", [])
    submodule_name = current_submodule.get("submodule_name", "Unknown")
    prd_context = state.get("prd_context", "")

    # TC valid dari percobaan sebelumnya (retry fokus requirement yang masih kosong)
    carried = list(state.get("valid_tcs", []) or [])

    print("\n" + "=" * 70)
    print("✅ TC VALIDATOR - Hard Validation")
    print("=" * 70)
    print(f"\n📋 Submodule: {submodule_name}")
    print(f"🎯 Target Requirements: {target_req_ids}")
    print(f"📊 Test Cases to Validate: {len(draft_tcs)} (dipertahankan dari percobaan sebelumnya: {len(carried)})")

    valid_tcs = list(carried)
    invalid_tcs = []
    validation_errors = []

    for i, tc in enumerate(draft_tcs, 1):
        tc_title = str(tc.get("title", f"TC-{i}")).replace("\n", " ")
        print(f"\n  [{i}] {tc_title[:90]}")

        errors = []

        for note in apply_autofixes(tc, prd_context):
            print(f"      ↻ {note}")

        ok, err = validate_test_case_structure(tc)
        if not ok:
            errors.append(f"Structure: {err}")

        ok, err = validate_no_hallucinated_features(tc, prd_context)
        if not ok:
            errors.append(f"Hallucination: {err}")

        ok, err = validate_no_invented_states(tc, prd_context)
        if not ok:
            errors.append(f"InventedState: {err}")

        ok, err = validate_test_case_requirement_ids(tc, target_req_ids)
        if not ok:
            errors.append(f"Scope: {err}")

        ok, err = validate_consistency(tc)
        if not ok:
            errors.append(err)

        if not errors and is_near_duplicate(tc, valid_tcs):
            errors.append("Duplicate: hampir identik dengan TC yang sudah diterima")

        if not errors and is_copied_expected(tc, valid_tcs):
            errors.append("CopiedExpected: expected result sama persis dengan TC requirement lain")

        if errors:
            print("      ❌ REJECTED")
            for e in errors:
                print(f"         - {e}")
            invalid_tcs.append({"tc": tc, "errors": errors})
            validation_errors.extend(errors)
        else:
            print("      ✅ ACCEPTED")
            valid_tcs.append(tc)

    new_valid = len(valid_tcs) - len(carried)
    print("\n" + "=" * 70)
    print("📊 Validation Summary:")
    print(f"   ✅ Valid baru: {new_valid}/{len(draft_tcs)}   (total valid submodule: {len(valid_tcs)})")
    print(f"   ❌ Invalid:    {len(invalid_tcs)}/{len(draft_tcs)}")
    print("=" * 70 + "\n")

    return {
        "valid_tcs": valid_tcs,
        "invalid_tcs": invalid_tcs,
        "validation_errors": validation_errors,
    }
