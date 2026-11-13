"""Lapis 2-6: mencari pasangan test case A <-> B tanpa AI chat.

Setiap pasangan diberi skor kemiripan 0-1 dari judul, Test Data, hasil harapan, langkah, dan Sub Module
(ditambah kemiripan makna dari model embedding bila tersedia). Pasangan yang sudah jelas langsung diputuskan
kode; yang ragu ("zona abu-abu") diteruskan ke AI chat, atau ke "Perlu dicek" pada mode cepat."""
import heapq
import json
from typing import Any, Callable, Dict, List, Optional, Tuple

from tc_compare import text as T

STATUSES = ("sama", "berkaitan", "sebagian", "bertentangan", "berbeda", "perlu_dicek")
PAIRED = ("sama", "berkaitan", "sebagian", "bertentangan")
LABEL = {"sama": "Sama", "berkaitan": "Berkaitan", "sebagian": "Sebagian", "bertentangan": "Bertentangan",
         "berbeda": "Berbeda", "perlu_dicek": "Perlu dicek"}
BY = {"kode": "Kode", "makna": "Kode + kemiripan makna", "ai": "AI", "mode_cepat": "Kode (mode cepat)"}

DEFAULTS = {
    "high": 0.80,          # skor >= ini (dan hasil harapan sejalan) -> Sama, diputuskan kode
    "low": 0.30,           # skor < ini -> bukan pasangan
    "top_k": 3,            # kandidat pasangan teratas per test case
    "grey_per_tc": 2,      # pasangan ragu per test case yang dinilai AI
    "max_ai_pairs": 400,   # batas pasangan yang dinilai AI dalam satu perbandingan
    "ai_batch": 5,         # pasangan per panggilan AI
    "duplicate": 0.92,     # skor kembar di dalam satu kumpulan
    "semantic_weight": 0.5,
}


def settings() -> Dict[str, Any]:
    cfg = dict(DEFAULTS)
    try:
        from tools.ai_config import CONFIG_PATH
        data = json.loads(CONFIG_PATH.read_text(encoding="utf-8"))
        cfg.update({k: v for k, v in (data.get("compare") or {}).items() if k in DEFAULTS})
    except Exception:
        pass
    return cfg


# ----------------------------------------------------------------------------- lapis 1: rapikan
def prepare(tcs: List[Dict[str, Any]]) -> None:
    for t in tcs:
        title = T.strip_opener(t.get("title"))
        t["_t"] = T.tokens(title)
        t["_e"] = T.tokens(t.get("expected"))
        t["_s"] = T.tokens(t.get("steps"))
        t["_sub"] = set(T.tokens(t.get("sub") or t.get("module")))
        t["_dv"] = T.data_values(t.get("data"))
        t["_out"] = T.outcome(t.get("expected"), t.get("category"))
        t["_key"] = " ".join(t["_t"]) + "#" + T.data_key(t.get("data")) + "#" + " ".join(t["_e"])
        t["_emb_text"] = f"{t.get('sub') or ''}. {t.get('title') or ''}. Data: {t.get('data') or '-'}. " \
                         f"Hasil: {t.get('expected') or '-'}"[:1500]


class Scorer:
    def __init__(self, a: List[Dict[str, Any]], b: List[Dict[str, Any]], weight: float):
        docs = [t["_t"] for t in a + b] + [t["_e"] for t in a + b]
        self.tf = T.Tfidf(docs)
        self.weight = weight
        for t in a + b:
            t["_vt"], t["_ve"], t["_vs"] = self.tf.vec(t["_t"]), self.tf.vec(t["_e"]), self.tf.vec(t["_s"])

    def parts(self, x: Dict[str, Any], y: Dict[str, Any]) -> Dict[str, float]:
        if x["_dv"] and y["_dv"]:
            data = T.jaccard(x["_dv"], y["_dv"])
        elif not x["_dv"] and not y["_dv"]:
            data = 0.5  # sama-sama tanpa Test Data: netral
        else:
            data = 0.2
        sub = T.jaccard(x["_sub"], y["_sub"]) if x["_sub"] and y["_sub"] else 0.5
        p = {"judul": T.cosine(x["_vt"], y["_vt"]), "hasil": T.cosine(x["_ve"], y["_ve"]),
             "langkah": T.cosine(x["_vs"], y["_vs"]), "data": data, "sub": sub}
        lex = 0.40 * p["judul"] + 0.20 * p["hasil"] + 0.25 * p["data"] + 0.05 * p["langkah"] + 0.10 * p["sub"]
        if x.get("_emb") and y.get("_emb"):
            # skor cosinus model embedding jarang di bawah 0,5 untuk teks sejenis -> diregangkan ke 0..1
            p["makna"] = max(0.0, min(1.0, (T.vcos(x["_emb"], y["_emb"]) - 0.5) / 0.5))
            p["skor"] = (1 - self.weight) * lex + self.weight * p["makna"]
        else:
            p["skor"] = lex
        return p


def _opposite(x, y) -> bool:
    return bool(x["_out"] and y["_out"] and x["_out"] != y["_out"])


# ----------------------------------------------------------------------------- lapis 2-5: putuskan dengan kode
def decide(x: Dict[str, Any], y: Dict[str, Any], p: Dict[str, float], cfg: Dict[str, Any]) -> Optional[Tuple[str, str, str]]:
    """(status, diputuskan_oleh, alasan) bila sudah jelas; None bila ragu."""
    by = "makna" if "makna" in p else "kode"
    if x["_key"] == y["_key"]:
        return "sama", "kode", "Judul, Test Data, dan hasil harapan sama persis setelah dirapikan."
    same_data = bool(x["_dv"]) and x["_dv"] == y["_dv"]
    if same_data and p["judul"] >= 0.5 and _opposite(x, y):
        return "bertentangan", "kode", (f"Test Data sama ({x.get('data')}) dan skenarionya mirip, tetapi hasil harapan "
                                        f"berlawanan: A {'berhasil' if x['_out'] == 'pos' else 'gagal/ditolak'}, "
                                        f"B {'berhasil' if y['_out'] == 'pos' else 'gagal/ditolak'}.")
    if p["skor"] >= cfg["high"] and p["hasil"] >= 0.45 and not _opposite(x, y) and (p["data"] >= 0.5):
        return "sama", by, f"Sangat mirip (skor {p['skor']:.2f}): judul, Test Data, dan hasil harapan sejalan."
    if p["skor"] < cfg["low"]:
        return "berbeda", by, f"Kemiripan rendah (skor {p['skor']:.2f})."
    return None


def candidates(a: List[Dict[str, Any]], b: List[Dict[str, Any]], scorer: Scorer, cfg: Dict[str, Any],
               cb: Optional[Callable[[int, int], None]] = None) -> Dict[Tuple[int, int], Dict[str, float]]:
    """Kandidat pasangan: top-k dari sisi A dan dari sisi B. Hanya dibandingkan dengan Sub Module yang mirip
    (bila Sub Module tidak cocok sama sekali, dibandingkan dengan semua)."""
    scores: Dict[Tuple[int, int], Dict[str, float]] = {}
    best_b: Dict[int, List[Tuple[float, int]]] = {}
    for i, x in enumerate(a):
        pool = [j for j, y in enumerate(b) if not x["_sub"] or not y["_sub"] or T.jaccard(x["_sub"], y["_sub"]) >= 0.2]
        if not pool:
            pool = range(len(b))
        row = []
        for j in pool:
            p = scorer.parts(x, b[j])
            row.append((p["skor"], j, p))
        row.sort(key=lambda r: -r[0])
        for s, j, p in row[: cfg["top_k"]]:
            if s >= cfg["low"] or (s >= cfg["low"] * 0.8 and x["_key"] == b[j]["_key"]):
                scores[(i, j)] = p
        for s, j, p in row:  # simpan hanya top-k terbaik per test case B (hemat memori)
            h = best_b.setdefault(j, [])
            if len(h) < cfg["top_k"]:
                heapq.heappush(h, (s, i))
            elif s > h[0][0]:
                heapq.heapreplace(h, (s, i))
        if cb and (i % 25 == 0 or i == len(a) - 1):
            cb(i + 1, len(a))
    for j, lst in best_b.items():  # sisi B juga mendapat top-k-nya sendiri
        for s, i in lst:
            if s >= cfg["low"] and (i, j) not in scores:
                scores[(i, j)] = scorer.parts(a[i], b[j])
    return scores


def duplicates(tcs: List[Dict[str, Any]], scorer: Scorer, cfg: Dict[str, Any]) -> List[Dict[str, Any]]:
    """Test case kembar di dalam satu kumpulan (penulisan beda, isi sama)."""
    out = []
    groups: Dict[str, List[int]] = {}
    for i, t in enumerate(tcs):
        groups.setdefault(" ".join(sorted(t["_sub"])), []).append(i)
    for idx in groups.values():
        for k, i in enumerate(idx):
            for j in idx[k + 1:]:
                x, y = tcs[i], tcs[j]
                if x["_key"] == y["_key"]:
                    out.append({"a": x["no"], "b": y["no"], "skor": 1.0, "alasan": "Isi sama persis setelah dirapikan."})
                    continue
                if x["_dv"] != y["_dv"] or _opposite(x, y):
                    continue
                p = scorer.parts(x, y)
                if p["skor"] >= cfg["duplicate"] and p["hasil"] >= 0.6:
                    out.append({"a": x["no"], "b": y["no"], "skor": round(p["skor"], 2),
                                "alasan": "Judul dan hasil harapan hampir sama dengan Test Data yang sama."})
    return out
