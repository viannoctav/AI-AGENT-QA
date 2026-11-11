# agents/obligation_expander_agent.py
"""
Obligation Expander: LLM hanya menulis TEKS test case (judul, prekondisi, langkah uji, test data, expected).
Skenario, nilai uji, polaritas, dan requirement_ids ditetapkan KODE (Test Designer) dan tidak
boleh diubah LLM. Template deterministik tersedia sebagai fallback.
"""

import json
import re
from typing import Any, Dict, List, Optional

from tools import llm
from tools.tc_post import is_generic_expected
from tools.ui import ui

SYSTEM = (
    "Kamu QA Engineer senior. Kamu menulis test case Bahasa Indonesia yang presisi, ringkas, dan "
    "TIDAK mengarang fitur, pesan error, atau status yang tidak ada di aturan. Output hanya JSON valid."
)


def _lc_first(s: str) -> str:
    return s[:1].lower() + s[1:] if s else s


def _style_examples(batch: List[Dict[str, Any]], k: int = 3) -> str:
    """Contoh TC perusahaan (Reference) yang relevan, hanya sebagai acuan GAYA penulisan."""
    try:
        from tools.company_tc_retriever import get_relevant_company_tcs
        query = " ".join(f"{o['rule_text']} {o['scenario']}" for o in batch)
        ex = get_relevant_company_tcs(query, top_k=k)
    except Exception:
        return ""
    if not ex:
        return ""
    lines = ["\nGAYA PENULISAN JUDUL, PREKONDISI & EXPECTED RESULT PERUSAHAAN (contoh, tiru gaya & tingkat detailnya, JANGAN salin isi/angkanya):"]
    for e in ex:
        pre = e.get("preconditions") or "-"
        lines.append(f"- Judul: {e['title']} | Prekondisi: {pre} | Expected: {e['expected_result']}")
    return "\n".join(lines) + "\n"


def _format_ob(ob: Dict[str, Any], feedback: Optional[str]) -> str:
    lines = [
        f"### {ob['ob_id']}",
        f"Fitur: {ob.get('sub_label') if ob.get('sub_label') not in (None, '', '-') else ob.get('module', '-')}",
        f"Skenario: {ob['scenario']}",
        f"Polaritas: {ob['polarity']}  |  Teknik: {ob['technique']}",
        f"Aturan PRD: {ob['rule_text']}",
    ]
    for a in ob.get("aliases", [])[:2]:
        lines.append(f"Aturan setara: {a}")
    for r in ob.get("related_rules", [])[:3]:
        lines.append(f"Aturan terkait: {r}")
    if ob.get("data_text"):
        lines.append("Nilai uji (SUDAH DITETAPKAN, jangan diubah/ditulis ulang):\n" + ob["data_text"])
    if ob.get("step_hint"):
        lines.append(f"Langkah wajib (harus tertulis di steps, angka/urutan jangan diubah): {ob['step_hint']}")
    if ob.get("precondition"):
        lines.append(f"Kondisi wajib di preconditions: {ob['precondition']}")
    if ob.get("expect_text"):
        lines.append(f"Hasil yang diharapkan (inti): {ob['expect_text']}")
    if feedback:
        lines.append(f"PERBAIKI (hasil verifikasi sebelumnya): {feedback}")
    return "\n".join(lines)


def _prompt_examples(batch: List[Dict[str, Any]]) -> Dict[str, str]:
    """Contoh di instruksi dibangun dari obligation yang sedang ditulis (nama fitur/field/status dari PRD ini),
    supaya istilah dari PRD lain tidak terbawa ke test case."""
    feat = next((o.get("sub_label") for o in batch if o.get("sub_label") not in (None, "", "-")), None) \
        or (batch[0].get("module") if batch else None) or "fitur"
    field = None
    for o in batch:
        m = re.match(r"\s*([^:\n]{2,40}):", o.get("data_text") or "")
        if m:
            field = m.group(1).strip()
            break
    field = field or feat
    state = None
    for o in batch:
        m = re.search(r"State awal\s*=\s*([A-Z_]+)", o.get("precondition") or "")
        if m:
            state = m.group(1)
            break
    return {
        "pre": f"Membuka aplikasi dan login dengan akun yang sesuai; berada di halaman yang memuat {feat}",
        "field": f'["Isi field {field} dengan nilai pada Test Data", "Isi field wajib lainnya dengan data valid", "Klik tombol Simpan"]',
        "wait": '["Lakukan aksi yang memulai batas waktu", "Tunggu sesuai durasi di Langkah wajib", "Lanjutkan aksi berikutnya", "Klik tombol pemicu"]',
        "state": f'["Buka detail data berstatus {state or "<status awal>"}", "Klik tombol aksi yang mengubah status", "Klik Ya pada konfirmasi"]',
        "dt": '["Pilih/isi setiap kondisi sesuai Test Data", "Klik tombol pemicu proses"]',
        "td": f'"{field}: <nilai>"',
    }


def build_prompt(batch: List[Dict[str, Any]], hints: Dict[str, str], feedback: Dict[str, str]) -> str:
    hint_txt = "\n".join(f"- {k}: {v}" for k, v in (hints or {}).items()) or "-"
    ex = _prompt_examples(batch)
    blocks = "\n\n".join(_format_ob(ob, feedback.get(ob["ob_id"])) for ob in batch)
    style_txt = _style_examples(batch)
    return f"""Tulis SATU test case untuk SETIAP obligation di bawah (jumlah test case = {len(batch)}).

ATURAN WAJIB:
1. Kembalikan ob_id persis sama. Jangan menambah/menghapus obligation.
2. title: diawali "Verifikasi", maksimal 120 karakter, Bahasa Indonesia (terjemahkan aturan berbahasa Inggris, jangan menyalin kalimatnya), idealnya <= 80 karakter, menyebut objek/fitur spesifik dari PRD. Hanya memakai angka yang ada di Skenario. Jangan tulis ID requirement, nomor telepon, email, atau kode di judul.
3. preconditions = PERSIAPAN yang dilakukan SEBELUM steps dan biasanya sama untuk banyak test case: membuka aplikasi/URL, login dengan akun yang sesuai (JANGAN login untuk test case login/registrasi), menuju halaman fitur, dan keadaan akun/data yang dibutuhkan. Contoh: "{ex['pre']}". JANGAN memuat nilai uji (email/password/kode/nomor yang diuji) dan JANGAN bertentangan dengan tujuan test case. DILARANG frasa generik seperti "kondisi awal sistem sesuai skenario".
4. steps = 2-8 langkah uji (array string) yang dilakukan QA SETELAH preconditions, HANYA AKSI berupa kalimat perintah (isi, pilih, klik, tunggu, masukkan). DILARANG langkah verifikasi seperti "Pastikan...", "Verifikasi...", "Periksa...", "Amati..." (hasil hanya ditulis di expected_result), dan jangan mengulang preconditions. Langkah terakhir adalah aksi yang memicu hasil. Nama tombol/halaman boleh disimpulkan secara wajar bila PRD tidak menyebutnya. Jika ada "Langkah wajib", isinya (termasuk angka) harus tertulis di steps. Contoh:
   - field input: {ex['field']}
   - batas waktu: {ex['wait']}
   - perubahan status: {ex['state']}
   - decision table: {ex['dt']}
5. test_data = HANYA nilai yang diinput atau dipilih QA (teks, angka, tanggal, email, pilihan dropdown, file yang diunggah), satu per baris "Nama field: nilai", dengan nama field persis seperti di PRD dan TIDAK diterjemahkan (mis. {ex['td']}), bukan label umum seperti "Nilai input". Nilai yang diketik/dipilih di steps (mis. 0, 'abc') WAJIB juga ditulis di test_data. Waktu tunggu, jumlah percobaan, urutan aksi, dan keadaan akun BUKAN test data (masukkan ke steps/preconditions). Jika sudah ada "Nilai uji", isi test_data dengan "" (nilainya dipakai otomatis). Jika memang tidak ada yang diinput, isi "-".
6. expected_result: kalimat pertama diawali TEPAT "Berhasil" (polaritas Positive) atau "Gagal"/"Ditolak" (polaritas Negative). Untuk polaritas Auto, pilih berdasarkan Aturan PRD. Jangan mengarang pesan error; kutip pesan hanya jika ada di aturan.
7. Jangan memakai angka/ambang yang tidak ada di Skenario, Langkah wajib, atau Aturan PRD.
8. expected_result: hasil konkret yang bisa diamati (halaman tujuan, pesan/penolakan, perubahan state, data tersimpan/tidak). Untuk decision table sebutkan status akhir yang terlihat (status/nilai yang tertulis di PRD). DILARANG frasa "sesuai deskripsi/aturan/requirement/ketentuan", "konsisten dengan kondisi awal", "alur berhasil", atau hanya "Berhasil."/"Gagal.".
9. Untuk penolakan, sebutkan APA yang terjadi dan ALASANNYA (mis. "Gagal. Sistem menolak <data> karena <alasan sesuai aturan PRD> dan tetap di halaman yang sama"). Jika PRD tidak menyebut teks pesan, cukup tulis "menampilkan pesan kesalahan" disertai alasan.
10. expected_result tidak boleh bertentangan: jika diawali "Berhasil" jangan memuat penolakan/gagal, dan sebaliknya.

CONTOH DATA SINTETIS dari PRD:
{hint_txt}
{style_txt}
OBLIGATION:
{blocks}

FORMAT OUTPUT (JSON):
{{"test_cases":[{{"ob_id":"OB-001","title":"Verifikasi ...","preconditions":"...","steps":["...","..."],"test_data":"","expected_result":"Berhasil ..."}}]}}"""


def _norm_id(raw: Any) -> str:
    m = re.search(r"OB\s*[-_ ]?\s*(\d+)", str(raw or ""), re.I)
    return f"OB-{int(m.group(1)):03d}" if m else ""


def expand_batch(batch: List[Dict[str, Any]], hints: Dict[str, str], feedback: Optional[Dict[str, str]] = None,
                 attempt: int = 0) -> Dict[str, Dict[str, Any]]:
    feedback = feedback or {}
    # percobaan terakhir: tulis satu-satu supaya satu obligation bermasalah tidak menggagalkan yang lain
    if len(batch) > 1 and attempt + 1 >= int(llm.settings()["max_attempts"]):
        merged: Dict[str, Dict[str, Any]] = {}
        for ob in batch:
            merged.update(expand_batch([ob], hints, feedback, attempt))
        return merged
    prompt = build_prompt(batch, hints, feedback)
    data = llm.chat_json(llm.model_for(batch), SYSTEM, prompt,
                            temperature=llm.settings()["temperature"] + 0.1 * attempt)
    out: Dict[str, Dict[str, Any]] = {}
    items: List[Any] = []
    if isinstance(data, dict):
        items = data.get("test_cases") or data.get("testcases") or data.get("results") or []
        if not items and data.get("title"):  # model mengembalikan satu TC tanpa pembungkus
            items = [data]
    elif isinstance(data, list):
        items = data
    items = [it for it in items if isinstance(it, dict)]
    for it in items:
        oid = _norm_id(it.get("ob_id"))
        if oid:
            out[oid] = it
    if len(batch) == 1 and not out and len(items) == 1:  # satu obligation, satu draft, id hilang/salah
        out[batch[0]["ob_id"]] = items[0]
    return out


def template_tc(ob: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    """Fallback deterministik. Hanya untuk obligation dengan polaritas & ekspektasi yang sudah pasti."""
    if ob["polarity"] not in ("Positive", "Negative") or not ob.get("expect_text"):
        return None
    if is_generic_expected(ob["expect_text"]):
        return None  # template generik dibuang: lebih baik LLM menulis ulang / ditandai review
    pos = ob["polarity"] == "Positive"
    expect = ob["expect_text"].rstrip(".")
    return {
        "title": "Verifikasi " + _lc_first(ob["scenario"]),
        "preconditions": template_precondition(ob),
        "steps": template_steps(ob),
        "expected_result": ("Berhasil. " if pos else "Gagal. ") + expect + ".",
        "test_data": "",
    }


def _feature(ob: Dict[str, Any]) -> str:
    sub = ob.get("sub_label")
    return sub if sub and sub != "-" else ob.get("module", "fitur terkait")


def template_precondition(ob: Dict[str, Any]) -> str:
    base = f"Membuka aplikasi dan berada di halaman {_feature(ob)}"
    return f"{base}; {ob['precondition']}" if ob.get("precondition") else base


def template_steps(ob: Dict[str, Any]) -> str:
    """Langkah uji pola bawaan: tetap bisa dijalankan (memakai Test Data dan Langkah wajib dari kode)."""
    steps = []
    hint = ob.get("step_hint") or ""
    if ob.get("data_text"):
        steps.append("Isi field sesuai nilai pada kolom Test Data")
        steps.append("Isi field wajib lainnya dengan data valid")
    if hint.lower().startswith("periksa"):
        steps.append("Jalankan proses yang menghasilkan data tersebut")
        steps.append(hint)
    elif hint:
        if ob.get("data_text"):
            steps.append("Klik tombol untuk mengirim/menyimpan")
        else:  # minimal 2 langkah: buka data/halaman dulu, lalu aksi wajibnya
            m = re.search(r"State awal\s*=\s*([A-Z_]+)", ob.get("precondition") or "")
            steps.append(f"Buka detail data berstatus {m.group(1)}" if m else "Lengkapi data sesuai Pre-condition dan Test Data")
        steps.append(hint)
    else:
        if not ob.get("data_text"):
            steps.append(f"Jalankan skenario: {_lc_first(ob['scenario'])}")
        steps.append("Klik tombol untuk mengirim/menyimpan")
    return "\n".join(f"{i}. {x}" for i, x in enumerate(steps, 1))


def obligation_expander_node(state: dict) -> dict:
    batch = state.get("current_batch", [])
    fb = state.get("batch_feedback", {})
    attempt = state.get("batch_attempt", 0)
    drafts = expand_batch(batch, state.get("hints", {}), fb, attempt)
    ui.batch_start([o["ob_id"] for o in batch], attempt + 1)
    if len(drafts) < len(batch):
        ui.event("expander", f"draft {len(drafts)}/{len(batch)} (attempt {attempt + 1})", "yellow")
    return {"draft_map": drafts}