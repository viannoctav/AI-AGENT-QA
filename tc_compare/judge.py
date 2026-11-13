"""Lapis 7: AI chat hanya menilai pasangan yang masih ragu, beberapa pasangan sekaligus.

Penjaga: AI hanya boleh memakai status yang sudah ditentukan, hanya untuk nomor pasangan yang dikirim,
dan wajib memberi alasan. Jawaban yang tidak memenuhi syarat menjadi "Perlu dicek", bukan ditebak."""
import re
from typing import Any, Dict, List, Optional

from tc_compare.match import STATUSES

SYSTEM = """Kamu QA senior. Kamu membandingkan pasangan test case dari dua kumpulan (A dan B).
Nilai apakah kedua test case di setiap pasangan menguji tujuan yang sama. Kalimat boleh berbeda bahasa atau gaya.
Jangan menebak: bila informasinya tidak cukup, pakai status perlu_dicek. Jawab hanya dengan JSON."""

PROMPT = """Status yang boleh dipakai:
- sama: tujuan uji, data, dan hasil harapan pada dasarnya sama (kalimat boleh berbeda)
- berkaitan: fitur atau elemen sama, tetapi menguji aspek yang berbeda
- sebagian: salah satu hanya mencakup sebagian tujuan test case lainnya
- bertentangan: skenario dan data sama, tetapi hasil harapannya berbeda atau berlawanan
- berbeda: tidak berhubungan cukup kuat
- perlu_dicek: informasi tidak cukup untuk memutuskan

Pasangan:
{pairs}

Jawab dengan JSON persis berformat:
{{"hasil": [{{"no": 1, "status": "sama", "alasan": "satu kalimat: bagian yang sama atau berbeda"}}]}}
Satu objek untuk setiap nomor pasangan di atas."""


def _short(s: Any, n: int = 220) -> str:
    s = re.sub(r"\s+", " ", str(s or "-")).strip()
    return s if len(s) <= n else s[: n - 3] + "..."


def _side(label: str, t: Dict[str, Any]) -> str:
    return (f"{label} ({t['no']}): Sub Module: {_short(t.get('sub'), 80)} | Jenis: {_short(t.get('category'), 20)} | "
            f"Judul: {_short(t.get('title'))} | Data: {_short(t.get('data'), 160)} | "
            f"Hasil: {_short(t.get('expected'))}")


def judge_batch(batch: List[Dict[str, Any]], llm, model: Optional[str] = None) -> List[Dict[str, str]]:
    """batch: [{"a": tc, "b": tc}] -> [{"status", "alasan"}] dengan panjang sama."""
    pairs = "\n\n".join(f"[{k}]\n{_side('A', p['a'])}\n{_side('B', p['b'])}" for k, p in enumerate(batch, 1))
    data = llm.chat_json(model or llm.generation_model(), SYSTEM, PROMPT.format(pairs=pairs),
                         temperature=0.0, num_predict=180 + 110 * len(batch))
    out = [{"status": "perlu_dicek", "alasan": "AI tidak memberi keputusan yang valid untuk pasangan ini."} for _ in batch]
    items = (data or {}).get("hasil") if isinstance(data, dict) else data if isinstance(data, list) else None
    for it in items or []:
        if not isinstance(it, dict):
            continue
        try:
            k = int(it.get("no"))
        except (TypeError, ValueError):
            continue
        status = str(it.get("status") or "").strip().lower().replace(" ", "_")
        alasan = re.sub(r"\s+", " ", str(it.get("alasan") or "")).strip()
        if not 1 <= k <= len(batch) or status not in STATUSES or len(alasan) < 8:
            continue  # nomor di luar daftar, status karangan, atau tanpa alasan -> tetap Perlu dicek
        out[k - 1] = {"status": status, "alasan": alasan[:400]}
    return out


CONCLUDE = """Tulis ringkasan hasil perbandingan dua kumpulan test case dalam bahasa Indonesia yang sederhana,
3 sampai 5 kalimat, untuk QA. Pakai HANYA angka dan fakta di bawah, jangan menambah angka lain.

Fakta:
{facts}

Jawab dengan JSON: {{"ringkasan": "..."}}"""


def conclude(facts: Dict[str, Any], llm) -> Optional[str]:
    """Kalimat ringkasan dari AI. Ditolak bila memuat angka yang tidak ada di fakta."""
    lines = "\n".join(f"- {k}: {v}" for k, v in facts.items())
    data = llm.chat_json(llm.generation_model(), "Kamu QA senior yang menulis ringkas dan tepat. Jawab hanya JSON.",
                         CONCLUDE.format(facts=lines), temperature=0.1, num_predict=500)
    text = str((data or {}).get("ringkasan") or "").strip() if isinstance(data, dict) else ""
    if len(text) < 40:
        return None
    allowed = set(re.findall(r"\d+(?:[.,]\d+)?", lines))
    if any(n not in allowed for n in re.findall(r"\d+(?:[.,]\d+)?", text)):
        return None  # angka karangan -> pakai ringkasan dari kode
    return text
