import glob
import os
import re
import pandas as pd

_REF_CACHE = []

_STOPWORDS = {
    "the", "and", "for", "with", "must", "may", "from", "that", "this", "have", "will", "when",
    "customer", "system", "rules", "rule", "include", "includes", "only", "than", "into",
    "yang", "dan", "untuk", "dengan", "pada", "atau", "dari", "dalam", "harus", "tidak",
    "verifikasi", "pengecekan", "pengujian", "valid", "invalid", "data", "input", "inputan",
}


def _load_reference_testcases():
    global _REF_CACHE
    if _REF_CACHE:
        return _REF_CACHE

    ref_files = sorted(glob.glob("Reference *.xlsx")) + sorted(
        glob.glob("knowledge/company_testcases/*.xlsx")
    )

    sources = [f for f in ref_files if os.path.exists(f)]
    try:  # file referensi yang dikunci dengan password dibuka di memori (lihat tools/vault.py)
        import io
        from tools import vault
        sources += [io.BytesIO(data) for _, data in vault.read_locked()]
    except Exception:
        pass

    loaded = []
    for f in sources:
        try:
            xls = pd.ExcelFile(f)
            df = pd.read_excel(xls, xls.sheet_names[0])
            df = df.rename(columns={c: str(c).strip() for c in df.columns})

            for _, row in df.iterrows():
                title = str(row.get("Test Title", "")).strip()
                pre = str(row.get("Preconditions", "")).strip()
                steps = str(row.get("Test Steps", "")).strip()
                exp = str(row.get("Expected Result", "")).strip()
                cat = str(row.get("Category", "")).strip()

                if title and title.lower() != "nan":
                    loaded.append(
                        {
                            "title": title,
                            "preconditions": pre if pre.lower() != "nan" else "-",
                            "steps": steps if steps.lower() != "nan" else "-",
                            "expected_result": exp if exp.lower() != "nan" else "",
                            "category": cat if cat.lower() != "nan" else "Positive",
                        }
                    )
        except Exception:
            pass

    _REF_CACHE = loaded
    return _REF_CACHE


def _keywords(text: str) -> set:
    words = re.findall(r"[a-zA-Z]{4,}", str(text).lower())
    return {w for w in words if w not in _STOPWORDS}


def get_relevant_company_tcs(query_text: str, top_k: int = 3, min_score: int = 4) -> list:
    """
    Ambil contoh TC referensi yang BENAR-BENAR relevan dengan requirement.
    query_text sebaiknya berisi judul + deskripsi requirement (bukan nama submodule),
    dan contoh hanya dipakai bila minimal `min_score` kata kunci unik cocok.
    Tidak ada fallback: lebih baik tanpa contoh daripada contoh dari domain lain.
    """
    all_tcs = _load_reference_testcases()
    if not all_tcs:
        return []

    query_kw = _keywords(query_text)
    if not query_kw:
        return []

    scored = []
    for tc in all_tcs:
        corpus_kw = _keywords(f"{tc['title']} {tc['expected_result']} {tc['preconditions']}")
        score = len(query_kw & corpus_kw)
        if score >= min_score:
            scored.append((score, tc))

    scored.sort(key=lambda x: x[0], reverse=True)
    return [tc for _, tc in scored[:top_k]]
