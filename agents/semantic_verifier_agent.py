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

from agents.obligation_expander_agent import template_precondition, template_tc
from agents.tc_validator_agent import (
    _NEG_START, apply_autofixes, clean_title, validate_no_hallucinated_features, validate_no_invented_states,
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
    if ob.get("precondition") and ob["precondition"].lower() not in tc["preconditions"].lower():
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
    support = f"{ob.get('scenario', '')} {ob.get('rule_text', '')} {ob.get('expect_text') or ''}".lower()
    for phrase in ("tepat", "melebihi batas"):
        if phrase in tc["title"].lower() and phrase not in support:
            out.append(f'title memuat frasa "{phrase}" yang tidak ada di skenario; samakan dengan skenario')
            break
    if is_self_contradicting(tc["expected_result"]):
        out.append("expected_result bertentangan (diawali Berhasil tetapi memuat penolakan/gagal); tulis satu hasil yang konsisten")
    n_steps = len([l for l in tc.get("steps", "").splitlines() if l.strip()])
    if n_steps < 2:
        out.append("steps kosong/kurang; tulis 2-8 langkah uji berupa kalimat perintah (isi field, klik tombol, tunggu, dst.)")
    elif n_steps > 10:
        out.append("steps terlalu panjang; ringkas menjadi maksimal 8 langkah")
    hint = ob.get("step_hint") or ""
    missing = [n for n in re.findall(r"\d+", hint) if n not in re.findall(r"\d+", tc.get("steps", ""))]
    if hint and missing:
        out.append(f'steps belum memuat langkah wajib "{hint}"; tuliskan beserta angkanya')
    else:
        allowed = _allowed_numbers(ob)
        for num, unit in _CLAIM.findall(_step_numbers_stripped(tc.get("steps", ""))):
            if int(num) not in allowed:
                out.append(f'angka "{num} {unit}" di steps tidak ada di skenario/aturan')
                break
    if english_ratio_high(tc["title"]):
        out.append("title masih berbahasa Inggris/menyalin aturan; tulis ulang dalam Bahasa Indonesia yang ringkas")
    return out


JUDGE_SYSTEM = ("Kamu auditor QA yang teliti dan adil. Tugasmu menilai apakah sebuah test case BERTENTANGAN "
                "dengan aturan PRD. Jawab HANYA JSON valid. Semua teks (termasuk reason) wajib Bahasa Indonesia; "
                "dilarang memakai bahasa lain.")

_JUDGE_RULES = """Definisi (polaritas sudah ditetapkan kode dan SUDAH BENAR, jangan dipertanyakan):
- Positive = sistem MENERIMA / proses BERHASIL.   Negative = sistem MENOLAK / memblokir / GAGAL.
Verdict:
- CONSISTENT : expected result sejalan dengan polaritas dan aturan PRD.
- CONTRADICTS: expected result berlawanan dengan polaritas yang ditetapkan, atau melanggar aturan PRD secara langsung.
- UNRELATED  : TC sama sekali tidak menguji skenario/aturan tersebut.
- UNSURE     : informasi tidak cukup untuk memutuskan.
Pedoman: nilai batas/angka pada skenario sudah benar, JANGAN dihitung ulang. Jika kamu tidak bisa memutuskan, jawab UNSURE (jangan menebak CONSISTENT).
Contoh:
- Aturan "kode berlaku 5 menit"; skenario kode dipakai pada menit ke-6; polaritas Negative; expected "Gagal. Kode ditolak karena kedaluwarsa" -> CONSISTENT.
- Aturan "kata sandi minimal 8 karakter"; skenario 7 karakter; polaritas Negative; expected "Berhasil. Kata sandi tersimpan" -> CONTRADICTS.
"""


def judge(items: List[Tuple[Dict[str, Any], Dict[str, Any]]]) -> Dict[str, Tuple[str, str]]:
    """items: [(ob, tc)]. Return {ob_id: (verdict, reason)}."""
    blocks = []
    for ob, tc in items:
        rules = [ob["rule_text"]] + ob.get("aliases", [])[:2] + ob.get("related_rules", [])[:2]
        blocks.append(
            f"### {ob['ob_id']}\nAturan PRD:\n- " + "\n- ".join(rules) +
            f"\nSkenario: {ob['scenario']}\nPolaritas ditetapkan: {ob['polarity']}\n"
            f"Data uji: {ob.get('data_text') or '-'}\n"
            f"TC judul: {tc['title']}\nTC langkah: {tc['steps']}\nTC expected: {tc['expected_result']}"
        )
    prompt = (_JUDGE_RULES + "\nReason maksimal 15 kata, Bahasa Indonesia.\n\n" + "\n\n".join(blocks) +
              '\n\nFORMAT: {"results":[{"ob_id":"OB-001","verdict":"CONSISTENT","reason":"..."}]}')
    jm = llm.auto_model() if items and all(llm.is_heavy(o) for o, _ in items) else llm.judge_model()
    data = llm.chat_json(jm, JUDGE_SYSTEM, prompt, temperature=0.0, num_predict=1200)
    out: Dict[str, Tuple[str, str]] = {}
    res = data.get("results", []) if isinstance(data, dict) else (data if isinstance(data, list) else [])
    for r in res:
        if isinstance(r, dict) and r.get("ob_id"):
            v = str(r.get("verdict", "UNSURE")).strip().upper()
            out[str(r["ob_id"]).strip()] = (v if v in ("CONSISTENT", "CONTRADICTS", "UNRELATED", "UNSURE") else "UNSURE",
                                            str(r.get("reason", "")))
    return out


def _finalize(ob: Dict[str, Any], tc: Dict[str, Any], flag: Optional[str], source: str) -> Dict[str, Any]:
    pol = _polarity_of(tc["expected_result"])
    category = ob["polarity"] if ob["polarity"] in ("Positive", "Negative") else (pol or "Positive")
    flags = []
    if flag:
        flags.append(flag)
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
        last_tc[ob["ob_id"]] = tc
        hard = check_tc(tc, ob, prd_context)
        soft = soft_issues(tc, ob)
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
    to_judge = [(ob, tc) for ob, tc in pending if cfg["judge_enabled"] and needs_judge(ob)]
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
            accepted.append(_finalize(ob, tc, flag, "llm"))

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
            else:
                dropped.append({"ob_id": oid, "scenario": ob["scenario"], "module": ob["module"],
                                "reason": why[:240]})
        failed = []
        feedback = {}
    return accepted, failed, feedback, dropped, stats


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