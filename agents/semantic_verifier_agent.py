# agents/semantic_verifier_agent.py
"""
Semantic Verifier - BLOCKING.

Lapisan 1 (deterministik): struktur, polaritas vs awalan expected, angka klaim vs obligation,
                            istilah asing/state karangan (memakai validator lama).
Lapisan 2 (LLM judge)     : apakah TC bertentangan LANGSUNG dengan teks aturan PRD? (model berbeda
                            bila dikonfigurasi di configs/ai.json -> judge_model)
TC yang gagal dikembalikan ke Expander dengan feedback. Setelah batas percobaan:
  - gagal "lunak" (teks generik / hanya juri tidak sepakat) -> TC LLM tetap dipakai + flag PERLU REVIEW
  - gagal "keras" (polaritas/angka/state salah)             -> template deterministik NON-generik, bila tidak
                                                               ada -> obligation dicatat "tanpa TC" (tidak ada TC generik)
Juri LLM hanya dipakai untuk obligation yang polaritasnya TIDAK ditetapkan kode (Auto) atau jenis aturan
non-deterministik; boundary/durasi/panjang/format sudah dijamin kode (nilai uji & polaritas tetap).
"""

import re
from typing import Any, Dict, List, Optional, Tuple

from agents.obligation_expander_agent import template_precondition, template_steps, template_tc
from agents.tc_validator_agent import (
    _NEG_START, apply_autofixes, clean_title, foreign_acronyms, validate_no_hallucinated_features, validate_no_invented_states,
)
from tools import llm
from tools.tc_post import (english_ratio_high, has_cjk, is_generic_expected, is_generic_precondition,
                           is_self_contradicting, is_truncated_expected, strip_leaked)
from tools.tc_normalize import format_test_data, has_placeholder, normalize_tc
from tools.ui import ui

_CLAIM = re.compile(r"(\d+)\s*(karakter|digit|menit|detik|jam|hari|kali|percobaan|request|permintaan|ms\b|%|item|kode)", re.I)
_REVIEW_KINDS = {"decision", "edge", "whitespace"}
# jenis aturan yang polaritas + nilai ujinya sudah dipastikan KODE -> tidak perlu juri LLM
DET_KINDS = {"required", "format", "length_max", "length_min", "length_exact", "length_range", "composition",
             "unique", "count_trigger", "count_max", "duration_lock", "duration_expiry", "duration_tolerance",
             "single_use", "perf", "invalid_transition", "enumeration"}


def needs_judge(ob: Dict[str, Any]) -> bool:
    """Default (judge_scope=auto): juri hanya untuk obligation yang polaritasnya belum ditetapkan kode."""
    if llm.settings().get("judge_scope", "auto") == "all":
        return not ((ob["kind"] in DET_KINDS or ob["kind"] == "decision") and ob["polarity"] in ("Positive", "Negative"))
    return ob["polarity"] == "Auto"


def _s(v: Any) -> str:
    if isinstance(v, list):
        return "\n".join(str(x) for x in v)
    return str(v or "").strip()


def _allowed_numbers(ob: Dict[str, Any], prd_context: str = "") -> set:
    base = set(ob.get("numbers_allowed", []))
    allowed = set(base) | {0, 1, 2}
    for n in base:
        allowed.update({n * 60, n * 3600})
        for div in (60, 3600, 86400):
            if n >= div and n % div == 0:
                allowed.add(n // div)
    for r in ob.get("related_rules", []):
        allowed.update(int(x) for x in re.findall(r"\d+", r))
    return allowed


# padanan satuan Indonesia <-> Inggris (bahasa, bukan isi PRD): dipakai untuk membaca angka+satuan di PRD apa pun
_UNIT_STEM = {"menit": "minute", "minute": "minute", "detik": "second", "second": "second", "sec": "second",
              "jam": "hour", "hour": "hour", "hari": "day", "day": "day", "karakter": "char", "character": "char",
              "char": "char", "digit": "digit", "kali": "attempt", "percobaan": "attempt", "attempt": "attempt",
              "time": "attempt", "failure": "attempt", "retry": "attempt", "ms": "ms", "millisecond": "ms",
              "%": "%", "percent": "%", "persen": "%", "item": "item", "request": "request", "permintaan": "request"}
_PRD_NUM_CACHE: Dict[int, Tuple[set, Dict[str, int]]] = {}


def _unit_of(word: str) -> str:
    w = (word or "").lower().rstrip("s") if word not in ("ms",) else word
    for k, v in _UNIT_STEM.items():
        if w == k or w.startswith(k):
            return v
    return ""


def prd_numbers(prd_context: str) -> Tuple[set, Dict[str, int]]:
    """Semua angka di PRD (+-1 untuk uji batas, konversi menit/detik) dan nilai terbesar per satuan."""
    key = hash(prd_context or "")
    if key in _PRD_NUM_CACHE:
        return _PRD_NUM_CACHE[key]
    text = re.sub(r"(?<=\d)[.,](?=\d{3}\b)", "", prd_context or "")  # Rp1,000,000 -> 1000000
    nums: set = set()
    top: Dict[str, int] = {}
    for m in re.finditer(r"(\d+)(?:\s*(?:-|\u2013|to|and|sampai|hingga)\s*(\d+))?\s*(%|[A-Za-z]+)?", text):
        vals = [int(x) for x in (m.group(1), m.group(2)) if x]
        unit = _unit_of(m.group(3) or "")
        for v in vals:
            nums.update({v - 1, v, v + 1})
            if unit in ("minute", "hour"):
                nums.update({v * 60, v * 60 + 1, v * 3600})
            if unit:
                top[unit] = max(top.get(unit, 0), v)
    _PRD_NUM_CACHE[key] = (nums, top)
    return nums, top


def step_number_ok(num: int, unit: str, ob: Dict[str, Any], prd_context: str) -> bool:
    """Angka di Test Steps wajar bila: ada di obligation, ada di PRD (termasuk +-1 batas), atau masih di bawah
    batas terbesar PRD untuk satuan yang sama (mis. 'tunggu 10 detik' untuk aturan 'dalam 30 detik')."""
    if num in _allowed_numbers(ob):
        return True
    nums, top = prd_numbers(prd_context)
    u = _unit_of(unit)
    if num in nums:
        return True
    if u == "second" and "minute" in top and num <= top["minute"] * 60 + 1:
        return True
    return bool(u) and u in top and num <= top[u] + 1


def _step_numbers_stripped(steps: str) -> str:
    return re.sub(r"(?m)^\s*\d+[.)]\s*", "", steps)


def format_steps(value: Any) -> str:
    """list / string bernomor / string satu baris -> "1. ...\n2. ..." (nomor dibuat ulang berurutan)."""
    if isinstance(value, (list, tuple)):
        items = [str(x).strip() for x in value]
    else:
        text = str(value or "").strip()
        if not text or text == "-":
            return ""
        if "\n" in text:
            items = text.split("\n")
        else:  # "1. a 2. b 3. c" dalam satu baris
            items = re.split(r"\s+(?=\d+[.)]\s)", text)
    out = []
    for it in items:
        it = re.sub(r"^\s*(?:\d+[.)]|[-*\u2022])\s*", "", str(it)).strip()
        if it:
            out.append(it[:1].upper() + it[1:])
    return "\n".join(f"{i}. {x}" for i, x in enumerate(out, 1))


def _covers(text: str, required: str) -> bool:
    """Kondisi wajib sudah tertulis (boleh dengan kalimat lain): semua kata pentingnya ada -> tidak ditulis dobel."""
    words = [w for w in re.findall(r"[a-z0-9_]+", required.lower()) if len(w) > 2 and w not in ("kondisi", "bernilai", "awal", "state")]
    have = text.lower()
    return bool(words) and sum(w in have for w in words) >= 0.8 * len(words)


def normalize(raw: Dict[str, Any], ob: Dict[str, Any]) -> Dict[str, Any]:
    tc = {
        "title": _s(raw.get("title")),
        "preconditions": _s(raw.get("preconditions")),
        "steps": format_steps(raw.get("steps")),
        "expected_result": _s(raw.get("expected_result")),
        "test_data": format_test_data(raw.get("test_data")),
    }
    if tc["title"] and not tc["title"].lower().startswith("verifikasi"):
        tc["title"] = "Verifikasi " + tc["title"][:1].lower() + tc["title"][1:]
    tc["title"] = clean_title(tc["title"])
    if tc["preconditions"] in ("", "-"):
        tc["preconditions"] = ob.get("precondition") or tc["preconditions"]
    if ob.get("precondition") and not _covers(tc["preconditions"], ob["precondition"]):
        tc["preconditions"] = f"{ob['precondition']}; {tc['preconditions']}"
    # data uji yang sudah ditetapkan kode selalu menang (tidak bisa diubah LLM)
    if ob.get("data_text"):
        tc["test_data"] = ob["data_text"]
    elif not tc["test_data"]:
        tc["test_data"] = "-"
    return normalize_tc(tc, ob)


def _polarity_of(expected: str) -> Optional[str]:
    e = expected.strip().lower()
    if e.startswith("berhasil"):
        return "Positive"
    if e.startswith(_NEG_START) or e.startswith("diblokir") or e.startswith("terkunci"):
        return "Negative"
    return None


def check_tc(tc: Dict[str, Any], ob: Dict[str, Any], prd_context: str) -> List[str]:
    issues: List[str] = []
    if not tc["title"] or len(tc["title"]) < 12:
        issues.append("title kosong/terlalu pendek")
    if not tc["expected_result"]:
        issues.append("expected_result kosong")
    else:
        pol = _polarity_of(tc["expected_result"])
        want = ob["polarity"]
        if pol is None:
            issues.append('expected_result harus diawali "Berhasil" atau "Gagal"/"Ditolak"')
        elif want in ("Positive", "Negative") and pol != want:
            issues.append(f'polaritas {want} tetapi expected_result diawali sebagai {pol}')

    allowed = _allowed_numbers(ob, prd_context)
    for field in ("title", "expected_result"):
        for num, unit in _CLAIM.findall(tc[field]):
            if int(num) not in allowed:
                issues.append(f'angka "{num} {unit}" di {field} tidak sesuai obligation (boleh: {sorted(set(ob.get("numbers_allowed", [])))})')
                break

    probe = {**tc, "category": "Positive"}
    ok, msg = validate_no_hallucinated_features(probe, prd_context)
    if not ok:
        issues.append(msg)
    ok, msg = validate_no_invented_states(probe, prd_context)
    if not ok:
        issues.append(msg)
    return issues


def soft_issues(tc: Dict[str, Any], ob: Dict[str, Any]) -> List[str]:
    """Masalah kualitas teks yang butuh LLM menulis ulang. (Prekondisi generik/kosong diperbaiki otomatis di _finalize.)"""
    out: List[str] = []
    if is_generic_expected(tc["expected_result"]):
        out.append("expected_result terlalu generik; sebutkan hasil konkret yang teramati (halaman/pesan/state/data)")
    elif is_truncated_expected(tc["expected_result"]):
        out.append('expected_result terpotong (mis. "tampil pesan" tanpa isi); sebutkan apa yang terjadi dan alasannya')
    if has_placeholder(tc["test_data"]):
        out.append('test_data berisi placeholder "sesuai aturan PRD" (tidak executable); tulis nilai konkret atau "-"')
    # judul yang mengklaim posisi batas berlawanan dengan polaritas obligation:
    # "melebihi batas" pada skenario yang DITERIMA, atau "tepat (di batas)" pada skenario yang DITOLAK
    # (kecuali aturannya sendiri "tepat N", mis. kode pos tepat 5 digit)
    title_l = tc["title"].lower()
    support = f"{ob.get('scenario', '')} {ob.get('rule_text', '')} {ob.get('expect_text') or ''}".lower()
    if ob["polarity"] == "Positive" and re.search(r"melebihi batas|di atas batas|lebih dari batas", title_l):
        out.append('title menyebut nilai melebihi batas, padahal skenario ini nilai yang diterima; samakan dengan skenario')
    elif ob["polarity"] == "Negative" and re.search(r"\btepat\b", title_l) and \
            not re.search(r"\btepat\b|exactly|\bkurang\b|\blebih\b|below|above|di bawah|di atas", support) \
            and ob["kind"] != "length_exact":
        out.append('title menyebut nilai tepat di batas, padahal skenario ini nilai yang ditolak; samakan dengan skenario')
    if is_self_contradicting(tc["expected_result"]):
        out.append("expected_result bertentangan (diawali Berhasil tetapi memuat penolakan/gagal); tulis satu hasil yang konsisten")
    # Test Steps tidak lagi jadi alasan tulis ulang (mahal di CPU): kosong / kurang langkah wajib
    # diperbaiki otomatis di fix_steps(). Angka karangan di steps hanya ditandai di Review Flag.
    if english_ratio_high(tc["title"]):
        out.append("title masih berbahasa Inggris/menyalin aturan; tulis ulang dalam Bahasa Indonesia yang ringkas")
    return out


JUDGE_SYSTEM = ("Kamu auditor QA yang teliti dan adil. Tugasmu menilai apakah sebuah test case BERTENTANGAN "
                "dengan aturan PRD. Jawab HANYA JSON valid. Semua teks (termasuk reason) wajib Bahasa Indonesia; "
                "dilarang memakai bahasa lain.")

_JUDGE_RULES = """Periksa SATU test case terhadap aturan PRD. Jawab pertanyaan berikut, JANGAN memberi vonis sendiri:
1. keputusan_sistem: dengan DATA UJI dan skenario TC ini, apa yang dilakukan SISTEM menurut PRD?
   "DIPROSES" = aksi berjalan (data diterima, nilai/biaya dihitung, status berubah/menunggu konfirmasi atau persetujuan).
   "DITOLAK"  = sistem menolak/memblokir aksi, menampilkan error, atau proses gagal/tidak diotorisasi.
   "TIDAK JELAS" = PRD tidak cukup untuk memutuskan.
   Pola (X, N, A, B, E, Y = nama/angka dari PRD yang sedang diuji):
           aturan "X kedaluwarsa harus ditolak", data X kedaluwarsa -> DITOLAK.
           aturan "X maksimal N", data N+1 -> DITOLAK; data N -> DIPROSES.
           aturan "saat E, status berpindah dari A ke B", kejadian E -> DIPROSES.
           aturan "biaya Y selalu dikenakan", memilih Y -> DIPROSES (biaya dikenakan).
2. relevan: true bila judul/langkah/data TC memang menguji skenario ini; false bila TC menguji hal lain.
3. salah_fakta: SALIN PERSIS potongan kalimat dari "TC expected" yang menyebut nilai/status/biaya/jumlah yang
   BERTENTANGAN langsung dengan kalimat PRD (mis. expected "biaya Rp0" padahal PRD "selalu dikenai biaya").
   Isi "" bila tidak ada. Expected yang kurang detail (tidak menyebut teks pesan error, nama tombol, tampilan)
   BUKAN salah fakta. Nilai batas pada skenario sudah benar, jangan dihitung ulang.
4. aturan: kalimat PRD yang kamu pakai sebagai dasar (singkat, boleh bahasa asli PRD).
5. reason: penjelasan maksimal 20 kata, Bahasa Indonesia.
"Aturan terkait" hanya konteks tambahan.
FORMAT: {"keputusan_sistem":"DIPROSES|DITOLAK|TIDAK JELAS","relevan":true,"salah_fakta":"","aturan":"...","reason":"..."}
"""

_LACK_DETAIL = re.compile(r"tidak (menyebut|disebutkan|mencantumkan|ada pesan)|tanpa (detail|pesan|menyebut)|kurang detail|"
                          r"tidak spesifik|pesan (error|kesalahan) tidak", re.I)
_HASIL = {"diproses": "Positive", "ditolak": "Negative", "berhasil": "Positive", "gagal": "Negative"}


def _quotes_expected(fragment: str, expected: str) -> bool:
    """salah_fakta harus benar-benar kutipan dari expected (bukan karangan juri)."""
    f = set(re.findall(r"[a-z0-9]+", fragment.lower()))
    e = set(re.findall(r"[a-z0-9]+", expected.lower()))
    return bool(f) and len(f & e) / len(f) >= 0.6


def judge_one(ob: Dict[str, Any], tc: Dict[str, Any]) -> Tuple[str, str]:
    """AI menjawab fakta (hasil menurut PRD, relevan, kutipan yang salah); VONIS dihitung kode.
    Satu test case per panggilan: tidak ada jawaban yang tertukar antar test case, dan instruksi di awal
    prompt yang selalu sama dibaca ulang dari cache Ollama sehingga tetap cepat."""
    rules = [ob["rule_text"]] + ob.get("aliases", [])[:2]
    prompt = (_JUDGE_RULES + "\nAturan PRD:\n- " + "\n- ".join(rules) +
              ("\nAturan terkait:\n- " + "\n- ".join(ob.get("related_rules", [])[:12 if ob["kind"] == "decision" else 3])
               if ob.get("related_rules") else "") +
              f"\nSkenario: {ob['scenario']}\nData uji: {ob.get('data_text') or '-'}\n"
              f"Kondisi awal: {ob.get('precondition') or '-'}\n"
              f"TC judul: {tc['title']}\nTC langkah: {tc['steps']}\nTC data uji: {tc.get('test_data') or '-'}\n"
              f"TC expected: {tc['expected_result']}")
    jm = llm.auto_model() if llm.is_heavy(ob) else llm.judge_model()
    data = llm.chat_json(jm, JUDGE_SYSTEM, prompt, temperature=0.0, num_predict=350)
    if not isinstance(data, dict):
        return "UNSURE", "juri tidak memberi jawaban"
    reason = str(data.get("reason") or "").strip()
    aturan = str(data.get("aturan") or "").strip()
    if has_cjk(reason + aturan):
        return "UNSURE", "jawaban juri bukan Bahasa Indonesia"
    if data.get("relevan") is False or str(data.get("relevan")).strip().lower() == "false":
        return "UNRELATED", reason or "TC tidak menguji skenario ini"
    expected = tc.get("expected_result") or ""
    wrong = str(data.get("salah_fakta") or "").strip().strip('"')
    if wrong and not _LACK_DETAIL.search(wrong + " " + reason) and _quotes_expected(wrong, expected):
        return "CONTRADICTS", f'expected "{wrong[:80]}" bertentangan dengan PRD: {aturan[:120] or reason}'
    exp_pol = _polarity_of(expected)
    known = ob["polarity"] in ("Positive", "Negative")
    should = ob["polarity"] if known else _HASIL.get(str(data.get("keputusan_sistem") or data.get("hasil_prd") or "").strip().lower())
    if should and exp_pol and should != exp_pol:
        word = "memproses" if should == "Positive" else "menolak"
        if ob["kind"] == "decision" or known:
            return "CONTRADICTS", f"menurut PRD sistem seharusnya {word}: {aturan[:120] or reason}"
        # aturan tunggal (bukan kombinasi): dari 2 run nyata, hampir semua penilaian ARAH oleh model kecil di sini keliru
        # (mis. "kuantitas non-numerik tidak valid" dinilai "diproses"). Untuk jenis ini AI pemeriksa tetap memeriksa
        # relevansi dan kutipan fakta yang salah, tetapi arah hasil tidak dipakai sebagai tanda.
        return "CONSISTENT", f"arah hasil tidak dinilai untuk aturan tunggal; {reason}"
    if not known and not should:
        return "UNSURE", reason or "PRD tidak cukup jelas untuk skenario ini"
    return "CONSISTENT", reason


def judge(items: List[Tuple[Dict[str, Any], Dict[str, Any]]]) -> Dict[str, Tuple[str, str]]:
    """items: [(ob, tc)]. Return {ob_id: (verdict, reason)}. Diperiksa satu per satu."""
    return {ob["ob_id"]: judge_one(ob, tc) for ob, tc in items}


def _finalize(ob: Dict[str, Any], tc: Dict[str, Any], flag: Optional[str], source: str) -> Dict[str, Any]:
    pol = _polarity_of(tc["expected_result"])
    category = ob["polarity"] if ob["polarity"] in ("Positive", "Negative") else (pol or "Positive")
    flags = []
    if flag:
        flags.append(flag)
    if tc.get("_note"):
        flags.append(tc["_note"])
    if ob.get("derived"):
        flags.append("Diturunkan otomatis dari state model (asumsi) - konfirmasi ke PO")
    if ob.get("flag_note"):
        flags.append(ob["flag_note"])
    if ob["kind"] in _REVIEW_KINDS and ob["polarity"] == "Auto":
        flags.append("Ekspektasi disimpulkan dari aturan terkait (PRD tidak menyebut hasil eksplisit) - konfirmasi")
    pre = tc["preconditions"]
    if not pre or is_generic_precondition(pre):
        # kalimat generik diganti persiapan standar (buka aplikasi + halaman fitur + kondisi wajib dari kode)
        pre = template_precondition(ob)
    return {
        "ob_id": ob["ob_id"], "atom_id": ob["atom_id"], "kind": ob["kind"], "module": ob["module"],
        "sub_label": ob["sub_label"], "technique": ob["technique"], "priority": ob["priority"],
        "requirement_ids": list(ob["requirement_ids"]), "category": category,
        "title": tc["title"], "preconditions": pre, "steps": tc["steps"],
        "test_data": tc["test_data"], "expected_result": tc["expected_result"],
        "review_flag": " | ".join(flags), "source": source,
    }


# langkah PEMERIKSAAN hasil (bukan aksi): "Pastikan ...", "Periksa status ...", "Sistem menampilkan ...".
# "Klik tombol Verifikasi", "Verifikasi kode OTP", "Periksa email masuk" tetap dianggap aksi.
_CHECK_STEP = re.compile(r"^(pastikan|amati|lihat\s+apakah|konfirmasi\s+bahwa|"
                         r"(verifikasi|periksa|cek|validasi)\s+(apakah|bahwa|status|hasil|tampilan|pesan|detail|riwayat|data\s+yang)|"
                         r"sistem\s+(menampilkan|menolak|menerima|mengubah|menyimpan)|hasil(nya)?\s)", re.I)
_SUBMIT_STEP = re.compile(r"\b(klik|tekan|tap|kirim|simpan|submit|bayar|lanjut|konfirmasi|verifikasi\s+kode)\b", re.I)


_STEP_VALUE = re.compile(r"(?:menjadi|dengan nilai|dengan|nilai)\s+['\"\u201c\u2018]([^'\"\u201d\u2019]{1,60})['\"\u201d\u2019]"
                         r"|(?:menjadi|dengan nilai)\s+(-?\d+(?:[.,]\d+)?)\b", re.I)


def fill_test_data_from_steps(tc: Dict[str, Any], ob: Dict[str, Any]) -> None:
    """Test Data kosong tetapi nilai yang diinput tertulis di steps (mis. "Ubah kuantitas menjadi 0")
    -> nilai dipindah ke Test Data dengan nama field dari PRD (fitur obligation)."""
    if str(tc.get("test_data") or "").strip() not in ("", "-") or ob["kind"] in ("transition", "invalid_transition"):
        return
    vals = []
    for m in _STEP_VALUE.finditer(tc.get("steps") or ""):
        v = (m.group(1) or m.group(2) or "").strip()
        if v and v not in vals and not re.search(r"test data|pre-condition", v, re.I):
            vals.append(v)
    if not vals:
        return
    field = ob.get("sub_label") if ob.get("sub_label") not in (None, "", "-") else "Nilai input"
    tc["test_data"] = "\n".join(f"{field}: {v}" for v in vals[:3])


def fix_steps(tc: Dict[str, Any], ob: Dict[str, Any], prd_context: str = "") -> Optional[str]:
    """Perbaikan Test Steps TANPA memanggil AI lagi:
    kosong -> pola bawaan; langkah verifikasi ("Pastikan ...") dibuang (hasil hanya di Expected Result);
    langkah wajib dari kode yang hilang -> disisipkan; kurang dari 2 langkah -> dilengkapi.
    Return catatan untuk Review Flag (atau None)."""
    if not tc.get("steps", "").strip():
        tc["steps"] = template_steps(ob)
        return None
    hint = ob.get("step_hint") or ""
    items = [re.sub(r"^\s*\d+[.)]\s*", "", l).strip() for l in tc["steps"].splitlines() if l.strip()]
    keep = [x for x in items if not _CHECK_STEP.match(x) or (hint and x.lower().startswith(hint.lower()[:20]))]
    if not keep:  # semua langkah berupa pemeriksaan -> pola aksi bawaan untuk jenis aturan ini
        keep = [re.sub(r"^\s*\d+[.)]\s*", "", l).strip() for l in template_steps(ob).splitlines() if l.strip()]
    items = keep
    if hint and [n for n in re.findall(r"\d+", hint) if n not in re.findall(r"\d+", " ".join(items))]:
        items.insert(len(items) - 1 if len(items) > 1 else len(items), hint)  # sebelum aksi pemicu terakhir
    if len(items) < 2:
        feat = ob.get("sub_label") if ob.get("sub_label") not in (None, "", "-") else ob.get("module", "fitur")
        if _SUBMIT_STEP.search(items[0]) or items[0] == hint:
            m = re.search(r"State awal\s*=\s*([A-Z_]+)", ob.get("precondition") or "")
            items.insert(0, f"Buka detail data berstatus {m.group(1)}" if m else "Lengkapi data sesuai Pre-condition dan Test Data")
        else:
            items.append("Klik tombol untuk mengirim/menyimpan")
    tc["steps"] = format_steps(items)
    steps = tc["steps"]
    for num, unit in _CLAIM.findall(_step_numbers_stripped(steps)):
        if not step_number_ok(int(num), unit, ob, prd_context):
            return f'Angka "{num} {unit}" di Test Steps tidak ada di PRD - pastikan'
    return None


def verify_batch(batch: List[Dict[str, Any]], drafts: Dict[str, Dict[str, Any]], prd_context: str,
                 attempt: int, max_attempts: int):
    """
    Return (accepted, failed, feedback, dropped, stats).
      dropped = [{ob_id, scenario, module, reason}]  -> obligation tanpa TC (tidak ada TC generik)
      stats   = {judged, skipped, overruled}
    """
    cfg = llm.settings()
    accepted: List[Dict[str, Any]] = []
    failed: List[Dict[str, Any]] = []
    dropped: List[Dict[str, Any]] = []
    feedback: Dict[str, str] = {}
    pending: List[Tuple[Dict[str, Any], Dict[str, Any]]] = []
    last_tc: Dict[str, Dict[str, Any]] = {}
    numeric_only: set = set() # satu-satunya masalah keras: angka tidak ada di PRD (flow/perf)
    soft_only: set = set()    # gagal hanya karena kualitas teks
    judge_only: set = set()   # gagal hanya karena juri
    stats = {"judged": 0, "skipped": 0, "overruled": 0, "log": []}

    for ob in batch:
        raw = drafts.get(ob["ob_id"])
        if not raw:
            failed.append(ob)
            feedback[ob["ob_id"]] = "test case untuk obligation ini tidak dikembalikan"
            continue
        tc = normalize(raw, ob)
        probe = {**tc, "category": "Positive", "requirement_ids": ob["requirement_ids"]}
        apply_autofixes(probe, prd_context)
        tc["expected_result"] = probe["expected_result"]
        tc["title"] = probe["title"]
        # perbaikan otomatis (tanpa retry LLM): nilai uji bocor di prekondisi; expected generik/terpotong -> inti dari kode
        if ob["kind"] not in ("transition", "invalid_transition"):
            tc["preconditions"] = strip_leaked(tc["preconditions"], ob.get("data_text", ""))
        if (is_generic_expected(tc["expected_result"]) or is_truncated_expected(tc["expected_result"])) \
                and ob.get("expect_text") and not is_generic_expected(ob["expect_text"]):
            tpl = template_tc(ob)
            if tpl:
                tc["expected_result"] = normalize(tpl, ob)["expected_result"]
            elif ob["polarity"] == "Auto":  # hasil analisis PRD (decision table) dipakai apa adanya
                tc["expected_result"] = ob["expect_text"]
        step_note = fix_steps(tc, ob, prd_context)
        fill_test_data_from_steps(tc, ob)
        if step_note:
            tc["_note"] = step_note
        last_tc[ob["ob_id"]] = tc
        hard = check_tc(tc, ob, prd_context)
        soft = soft_issues(tc, ob)
        alien = foreign_acronyms(tc, prd_context)
        if alien:  # istilah dari PRD/proyek lain (mis. "MFA" di modul yang tidak membahas MFA) -> tulis ulang
            soft = soft + [f"istilah {', '.join(alien)} tidak ada di PRD ini; hapus atau ganti dengan istilah dari PRD"]
        if hard:
            failed.append(ob)
            if (ob["kind"] in ("flow", "perf") and all(h.startswith("angka") for h in hard)) or \
                    (ob["polarity"] == "Auto" and all(h.startswith(("angka", "expected_result harus diawali")) for h in hard)):
                numeric_only.add(ob["ob_id"])  # diterima dengan flag PERLU REVIEW, tidak dibuang
            feedback[ob["ob_id"]] = "; ".join(hard + soft)
        elif soft:
            failed.append(ob)
            soft_only.add(ob["ob_id"])
            feedback[ob["ob_id"]] = "; ".join(soft)
        else:
            pending.append((ob, tc))

    # ---- juri LLM: hanya untuk obligation yang butuh (polaritas Auto / aturan non-deterministik)
    later = str(cfg.get("judge_timing", "akhir")).lower() == "akhir"
    to_judge = [(ob, tc) for ob, tc in pending if cfg["judge_enabled"] and needs_judge(ob) and not later]
    judge_end_ids = {ob["ob_id"] for ob, _ in pending if cfg["judge_enabled"] and needs_judge(ob) and later}
    stats["skipped"] = len(pending) - len(to_judge)
    verdicts: Dict[str, Tuple[str, str]] = {}
    size = max(1, int(cfg["judge_batch"]))
    for i in range(0, len(to_judge), size):
        chunk = to_judge[i:i + size]
        stats["judged"] += len(chunk)
        verdicts.update(judge(chunk))

    judged_ids = {ob["ob_id"] for ob, _ in to_judge}
    for ob, tc in pending:
        judged = ob["ob_id"] in judged_ids
        verdict, reason = verdicts.get(ob["ob_id"], ("UNSURE", "juri tidak memberi jawaban") if judged else ("CONSISTENT", ""))
        if judged and has_cjk(reason):  # model keluar jalur bahasa -> penilaian tidak dapat dipercaya
            ui.event("judge", f"{ob['ob_id']}: jawaban juri bukan Bahasa Indonesia -> UNSURE", "dim")
            verdict, reason = "UNSURE", "jawaban juri bukan Bahasa Indonesia"
            stats["overruled"] += 1
        if judged:
            stats["log"].append({"ob_id": ob["ob_id"], "attempt": attempt + 1, "verdict": verdict, "reason": reason})
        blocking = verdict == "CONTRADICTS" or (verdict == "UNRELATED" and ob["polarity"] == "Auto")
        if blocking:
            failed.append(ob)
            judge_only.add(ob["ob_id"])
            feedback[ob["ob_id"]] = f"juri {verdict}: {reason}".strip()
            last_tc[ob["ob_id"]] = tc
        else:
            flag = None
            if verdict == "UNRELATED":
                flag = f"Juri menilai TC kurang relevan: {reason}"
            elif verdict == "UNSURE":
                flag = "Juri tidak yakin - tinjau manual" + (f": {reason}" if reason else "")
            done = _finalize(ob, tc, flag, "llm")
            if ob["ob_id"] in judge_end_ids:
                done["_judge"] = True  # diperiksa AI pemeriksa sekali jalan setelah semua kelompok selesai
            accepted.append(done)

    # ---- percobaan habis
    if failed and attempt + 1 >= max_attempts:
        for ob in failed:
            oid = ob["ob_id"]
            why = feedback.get(oid, "tidak lolos verifikasi")
            first = why.split("; ")[0][:120]  # flag cukup alasan utama
            if oid in last_tc and (oid in soft_only or oid in judge_only or oid in numeric_only):
                accepted.append(_finalize(ob, last_tc[oid], f"PERLU REVIEW - {first}", "llm-unverified"))
                continue
            tpl = template_tc(ob)  # sudah menolak template generik
            if tpl:
                tc = normalize(tpl, ob)
                accepted.append(_finalize(ob, tc, f"Template otomatis (LLM gagal verifikasi: {first})", "template"))
            elif oid in last_tc:  # coverage tetap 100%: draf terakhir dipakai, ditandai untuk dicek manual
                accepted.append(_finalize(ob, last_tc[oid], f"PERLU REVIEW - {first}", "llm-unverified"))
            else:
                dropped.append({"ob_id": oid, "scenario": ob["scenario"], "module": ob["module"],
                                "reason": why[:240]})
        failed = []
        feedback = {}
    return accepted, failed, feedback, dropped, stats


JUDGE_FLAG_PREFIX = ("PERLU REVIEW - juri", "Juri menilai", "Juri tidak yakin")


def apply_verdict(t: Dict[str, Any], ob: Dict[str, Any], verdict: str, reason: str, judge_log: List[Dict[str, Any]]) -> None:
    """Tulis hasil AI pemeriksa ke test case (tanda Perlu dicek) dan ke judge_log."""
    if has_cjk(reason):
        verdict, reason = "UNSURE", "jawaban juri bukan Bahasa Indonesia"
    judge_log.append({"ob_id": t["ob_id"], "attempt": "akhir", "verdict": verdict, "reason": reason})
    if verdict == "CONSISTENT" and ob["polarity"] == "Auto" and ob.get("expect_text") and t.get("review_flag"):
        # hasil dianalisis dari PRD saat desain DAN AI pemeriksa (model lain) menilai sama -> tidak perlu dicek
        t["review_flag"] = " | ".join(x for x in t["review_flag"].split(" | ")
                                      if not x.startswith(("Ekspektasi disimpulkan", "Kondisi bertanda N/A"))) or None
    flag = {"CONTRADICTS": f"PERLU REVIEW - juri CONTRADICTS: {reason}",
            "UNRELATED": f"Juri menilai TC kurang relevan: {reason}",
            "UNSURE": "Juri tidak yakin - tinjau manual" + (f": {reason}" if reason else "")}.get(verdict)
    if flag:
        t["review_flag"] = " | ".join(x for x in (flag, t.get("review_flag")) if x)
        if verdict == "CONTRADICTS":
            t["source"] = "llm-unverified"
        ui.event("judge", f"{t['ob_id']} -> {verdict}", "yellow")


def judge_end_node(state: dict) -> dict:
    """AI pemeriksa dijalankan SEKALI setelah semua test case ditulis (judge_timing = "akhir").
    Model pemeriksa hanya dimuat sekali, bukan bergantian dengan model penulis di setiap kelompok.
    Hasil yang bertentangan / tidak relevan / ragu -> ditandai Perlu dicek (tidak ditulis ulang)."""
    tcs = list(state.get("accepted_tcs", []))
    obs = {o["ob_id"]: o for o in state.get("obligations", [])}
    todo = [t for t in tcs if t.pop("_judge", False) and t["ob_id"] in obs]
    judge_log = list(state.get("judge_log", []))
    if not todo:
        return {"accepted_tcs": tcs}
    ui.stage("generate", f"AI pemeriksa memeriksa {len(todo)} test case")
    todo.sort(key=lambda t: llm.is_heavy(obs[t["ob_id"]]))  # model pemeriksa utama dulu, model besar sesudahnya
    size = max(1, int(llm.settings()["judge_batch"]))
    for i in range(0, len(todo), size):
        chunk = todo[i:i + size]
        same = [c for c in chunk if llm.is_heavy(obs[c["ob_id"]]) == llm.is_heavy(obs[chunk[0]["ob_id"]])]
        verdicts = judge([(obs[t["ob_id"]], t) for t in same])
        if len(same) < len(chunk):
            verdicts.update(judge([(obs[t["ob_id"]], t) for t in chunk if t not in same]))
        for t in chunk:
            verdict, reason = verdicts.get(t["ob_id"], ("UNSURE", "juri tidak memberi jawaban"))
            apply_verdict(t, obs[t["ob_id"]], verdict, reason, judge_log)
        ui.event("judge", f"diperiksa {min(i + size, len(todo))}/{len(todo)}", "dim")
    return {"accepted_tcs": tcs, "judge_log": judge_log}


def semantic_verifier_node(state: dict) -> dict:
    batch = state.get("current_batch", [])
    attempt = state.get("batch_attempt", 0)
    max_attempts = int(llm.settings()["max_attempts"])
    accepted, failed, feedback, dropped, stats = verify_batch(
        batch, state.get("draft_map", {}), state.get("prd_context", ""), attempt, max_attempts)
    done = list(state.get("accepted_tcs", [])) + accepted
    all_dropped = list(state.get("dropped_obs", [])) + dropped
    judge_log = list(state.get("judge_log", [])) + stats.get("log", [])
    ui.batch_result(accepted, retry=len(failed), dropped=len(dropped), judged=stats["judged"],
                    skipped=stats["skipped"], overruled=stats["overruled"])
    for d in dropped:
        ui.event("verifier", f"{d['ob_id']} tidak menghasilkan TC: {d['reason'][:70]}", "red")
    return {"accepted_tcs": done, "dropped_obs": all_dropped, "judge_log": judge_log, "current_batch": failed,
            "batch_feedback": feedback, "batch_attempt": attempt + 1 if failed else 0}