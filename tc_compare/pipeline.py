"""Orkestrator Bandingkan test case: urutan lapis dari yang paling murah (kode) ke yang paling mahal (AI chat)."""
import json
import re
import shutil
import time
from datetime import datetime
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional

from tc_compare import match as M

ROOT = Path(__file__).resolve().parents[1]
OUT_BASE = ROOT / "outputs" / "tc_compare"
EMBED_BATCH = 32


def _say(cb, msg):
    if cb:
        cb(msg)


def _slug(s: str) -> str:
    s = re.sub(r"[^\w\s-]", "", s, flags=re.U).strip().lower()
    return re.sub(r"[\s_-]+", "_", s)[:60] or "perbandingan"


def pct(v) -> str:
    """84.4 -> "84,4%" (format Indonesia)."""
    return (f"{v:.1f}".rstrip("0").rstrip(".") if isinstance(v, (int, float)) else str(v)).replace(".", ",") + "%"


def _public(t: Dict[str, Any]) -> Dict[str, Any]:
    return {k: v for k, v in t.items() if not k.startswith("_")}


def embed_all(tcs: List[Dict[str, Any]], embed_fn, P, cb) -> None:
    texts = [t["_emb_text"] for t in tcs]
    P.update(emb_total=len(texts), emb_done=0)
    vecs: List[List[float]] = []
    for i in range(0, len(texts), EMBED_BATCH):
        vecs.extend(embed_fn(texts[i:i + EMBED_BATCH]))
        P["emb_done"] = min(len(texts), i + EMBED_BATCH)
    if len(vecs) != len(tcs):
        raise RuntimeError("jumlah hasil tidak sesuai")
    for t, v in zip(tcs, vecs):
        t["_emb"] = v


def run(a: Dict[str, Any], b: Dict[str, Any], mode: str = "lengkap", name: str = "", llm=None,
        embed_fn: Optional[Callable[[List[str]], List[List[float]]]] = None, cb=None,
        progress: Optional[Dict[str, Any]] = None, write: bool = True, out_base: Path = OUT_BASE) -> Dict[str, Any]:
    """a, b: {"label", "source", "tcs": [...]} -> hasil perbandingan (disimpan ke outputs/tc_compare/)."""
    t0 = time.time()
    P = progress if progress is not None else {}
    P.update(phase="rapikan", emb_total=0, emb_done=0, ai_total=0, ai_done=0, ai_secs=[], match_done=0, match_total=0)
    cfg = M.settings()
    A, B = a["tcs"], b["tcs"]
    la, lb = a["label"], b["label"]
    notes: List[str] = []
    _say(cb, f"Membaca {len(A)} test case {la} dan {len(B)} test case {lb}.")
    M.prepare(A)
    M.prepare(B)

    # lapis 6 (didahulukan supaya skor sudah memakai makna): kemiripan makna
    semantic = False
    if embed_fn:
        P["phase"] = "makna"
        _say(cb, "Menghitung kemiripan makna (model embedding)...")
        try:
            embed_all(A + B, embed_fn, P, cb)
            semantic = True
        except Exception as e:
            for t in A + B:
                t.pop("_emb", None)
            notes.append(f"Kemiripan makna dilewati ({str(e)[:160]}). Pencocokan memakai kemiripan kata saja.")
            _say(cb, notes[-1])
    else:
        notes.append("Model embedding belum tersedia, jadi kemiripan makna dilewati. Kalimat yang beda kata tetapi "
                     "sama maksud lebih banyak masuk Perlu dicek.")

    # lapis 2-5: kandidat + keputusan kode
    P["phase"] = "cocokkan"
    P["match_total"] = len(A)
    scorer = M.Scorer(A, B, cfg["semantic_weight"])
    cands = M.candidates(A, B, scorer, cfg, cb=lambda d, n: P.update(match_done=d))
    pairs: List[Dict[str, Any]] = []
    grey: List[Dict[str, Any]] = []
    for (i, j), p in cands.items():
        rec = {"ai": i, "bi": j, "a": A[i]["no"], "b": B[j]["no"], "skor": round(p["skor"], 3),
               "bagian": {k: round(v, 2) for k, v in p.items() if k != "skor"}}
        d = M.decide(A[i], B[j], p, cfg)
        if d:
            rec.update(status=d[0], by=d[1], alasan=d[2])
            pairs.append(rec)
        else:
            grey.append(rec)
    sure_a = {r["ai"] for r in pairs if r["status"] == "sama"}
    sure_b = {r["bi"] for r in pairs if r["status"] == "sama"}
    grey.sort(key=lambda r: -r["skor"])
    per_a: Dict[int, int] = {}
    per_b: Dict[int, int] = {}
    to_judge, skipped = [], []
    for r in grey:
        if r["ai"] in sure_a and r["bi"] in sure_b:
            continue  # keduanya sudah punya pasangan pasti: tidak perlu AI
        if per_a.get(r["ai"], 0) >= cfg["grey_per_tc"] and per_b.get(r["bi"], 0) >= cfg["grey_per_tc"]:
            continue
        per_a[r["ai"]] = per_a.get(r["ai"], 0) + 1
        per_b[r["bi"]] = per_b.get(r["bi"], 0) + 1
        (to_judge if len(to_judge) < cfg["max_ai_pairs"] else skipped).append(r)
    decided_by_code = len(pairs)
    _say(cb, f"Kode memutuskan {decided_by_code} pasangan; {len(to_judge) + len(skipped)} pasangan masih ragu.")

    # lapis 7: AI chat untuk pasangan ragu (mode lengkap)
    if mode == "lengkap" and to_judge and llm is not None:
        P["phase"] = "ai"
        size = max(1, int(cfg["ai_batch"]))
        batches = [to_judge[k:k + size] for k in range(0, len(to_judge), size)]
        P.update(ai_total=len(batches), ai_done=0)
        _say(cb, f"AI menilai {len(to_judge)} pasangan ragu dalam {len(batches)} kelompok.")
        from tc_compare.judge import judge_batch
        for n, bt in enumerate(batches, 1):
            s0 = time.time()
            verdicts = judge_batch([{"a": A[r["ai"]], "b": B[r["bi"]]} for r in bt], llm)
            for r, v in zip(bt, verdicts):
                r.update(status=v["status"], alasan=v["alasan"],
                         by="ai" if not v["alasan"].startswith("AI tidak memberi") else "kode")
            P["ai_secs"].append(time.time() - s0)
            P["ai_done"] = n
            _say(cb, f"Kelompok {n} dari {len(batches)} dinilai AI.")
        pairs.extend(to_judge)
    else:
        for r in to_judge:
            r.update(status="perlu_dicek", by="mode_cepat",
                     alasan=f"Mirip sebagian (skor {r['skor']:.2f}). Mode cepat tidak memakai AI chat: putuskan sendiri.")
        pairs.extend(to_judge)
    for r in skipped:
        r.update(status="perlu_dicek", by="kode",
                 alasan=f"Mirip sebagian (skor {r['skor']:.2f}), melewati batas {cfg['max_ai_pairs']} pasangan yang dinilai AI.")
    pairs.extend(skipped)

    # ringkasan per test case
    P["phase"] = "simpulkan"
    result = summarize(A, B, la, lb, pairs, scorer, cfg)
    result.update(name=name or f"{la} vs {lb}", mode=mode, semantic=semantic, notes=notes,
                  sources={"a": {"label": la, "source": a.get("source", ""), "count": len(A), "missing": a.get("missing", [])},
                           "b": {"label": lb, "source": b.get("source", ""), "count": len(B), "missing": b.get("missing", [])}},
                  stats={**result["stats"], "decided_by_code": decided_by_code, "judged_by_ai": len(to_judge) if mode == "lengkap" else 0,
                         "seconds": round(time.time() - t0)})
    result["conclusion"] = conclusion_text(result)
    result["ai_summary"] = None
    if mode == "lengkap" and llm is not None:
        try:
            from tc_compare.judge import conclude
            result["ai_summary"] = conclude(facts(result), llm)
        except Exception as e:
            from tools import ai_source
            if ai_source.is_auth_error(e):
                raise
    result["stats"]["seconds"] = round(time.time() - t0)
    if write:
        result.update(_save(result, a, b, out_base))
    P["phase"] = "selesai"
    _say(cb, f"Selesai dalam {result['stats']['seconds']} detik.")
    return result


def summarize(A, B, la, lb, pairs, scorer, cfg) -> Dict[str, Any]:
    by_a: Dict[int, List[Dict[str, Any]]] = {}
    by_b: Dict[int, List[Dict[str, Any]]] = {}
    for r in pairs:
        by_a.setdefault(r["ai"], []).append(r)
        by_b.setdefault(r["bi"], []).append(r)

    def side_state(rows):
        if any(r["status"] in M.PAIRED for r in rows):
            return "berpasangan"
        if any(r["status"] == "perlu_dicek" for r in rows):
            return "perlu_dicek"
        return "sendiri"

    def best(rows):
        rows = sorted(rows or [], key=lambda r: -r["skor"])
        return rows[0] if rows else None

    only_a, only_b = [], []
    st_a = {i: side_state(by_a.get(i, [])) for i in range(len(A))}
    st_b = {j: side_state(by_b.get(j, [])) for j in range(len(B))}
    for i, t in enumerate(A):
        if st_a[i] == "sendiri":
            bb = best(by_a.get(i))
            only_a.append({**_public(t), "mirip": bb["b"] if bb else "", "mirip_skor": bb["skor"] if bb else None,
                           "alasan": f"Tidak ada pasangan yang memadai di {lb}."})
    for j, t in enumerate(B):
        if st_b[j] == "sendiri":
            bb = best(by_b.get(j))
            only_b.append({**_public(t), "mirip": bb["a"] if bb else "", "mirip_skor": bb["skor"] if bb else None,
                           "alasan": f"Tidak ada pasangan yang memadai di {la}."})
    keep = [r for r in pairs if r["status"] != "berbeda"]
    keep.sort(key=lambda r: (["bertentangan", "sama", "sebagian", "berkaitan", "perlu_dicek"].index(r["status"]), r["ai"], -r["skor"]))
    for r in keep:
        x, y = A[r["ai"]], B[r["bi"]]
        r["a_tc"], r["b_tc"] = _public(x), _public(y)
    paired_a = sum(1 for s in st_a.values() if s == "berpasangan")
    paired_b = sum(1 for s in st_b.values() if s == "berpasangan")
    pct = lambda n, d: round(100 * n / d, 1) if d else 0.0
    dup_a, dup_b = M.duplicates(A, scorer, cfg), M.duplicates(B, scorer, cfg)
    count = lambda s: sum(1 for r in keep if r["status"] == s)
    return {
        "labels": {"a": la, "b": lb},
        "pairs": [{k: v for k, v in r.items() if k not in ("ai", "bi")} for r in keep],
        "only_a": only_a, "only_b": only_b,
        "duplicates": {"a": dup_a, "b": dup_b},
        "stats": {"a_total": len(A), "b_total": len(B), "a_paired": paired_a, "b_paired": paired_b,
                  "a_coverage": pct(paired_a, len(A)), "b_coverage": pct(paired_b, len(B)),
                  "a_only": len(only_a), "b_only": len(only_b),
                  "a_review": sum(1 for s in st_a.values() if s == "perlu_dicek"),
                  "b_review": sum(1 for s in st_b.values() if s == "perlu_dicek"),
                  "sama": count("sama"), "berkaitan": count("berkaitan"), "sebagian": count("sebagian"),
                  "bertentangan": count("bertentangan"), "perlu_dicek": count("perlu_dicek"),
                  "dup_a": len(dup_a), "dup_b": len(dup_b)},
    }


def facts(r: Dict[str, Any]) -> Dict[str, Any]:
    s, la, lb = r["stats"], r["labels"]["a"], r["labels"]["b"]
    return {f"Jumlah test case {la}": s["a_total"], f"Jumlah test case {lb}": s["b_total"],
            f"{la} yang punya pasangan": f"{s['a_paired']} ({pct(s['a_coverage'])})",
            f"{lb} yang punya pasangan": f"{s['b_paired']} ({pct(s['b_coverage'])})",
            f"Hanya di {la}": s["a_only"], f"Hanya di {lb}": s["b_only"],
            "Pasangan sama": s["sama"], "Pasangan berkaitan": s["berkaitan"], "Pasangan sebagian": s["sebagian"],
            "Pasangan bertentangan (hasil harapan berbeda)": s["bertentangan"], "Pasangan perlu dicek": s["perlu_dicek"],
            f"Test case kembar di {la}": s["dup_a"], f"Test case kembar di {lb}": s["dup_b"]}


def conclusion_text(r: Dict[str, Any]) -> Dict[str, Any]:
    """Kesimpulan dan rekomendasi dari angka (kode, selalu tersedia)."""
    s, la, lb = r["stats"], r["labels"]["a"], r["labels"]["b"]
    gap = abs(s["a_coverage"] - s["b_coverage"])
    if s["a_coverage"] >= 80 and s["b_coverage"] >= 80:
        overall = f"{la} dan {lb} sebagian besar menguji hal yang sama."
    elif s["a_coverage"] < 40 and s["b_coverage"] < 40:
        overall = f"{la} dan {lb} menguji hal yang sangat berbeda; hanya sedikit test case yang berpasangan."
    else:
        overall = f"{la} dan {lb} berkaitan, tetapi cakupannya tidak sama."
    lines = [overall,
             f"{s['a_paired']} dari {s['a_total']} test case {la} ({pct(s['a_coverage'])}) punya pasangan di {lb}; "
             f"{s['b_paired']} dari {s['b_total']} test case {lb} ({pct(s['b_coverage'])}) punya pasangan di {la}."]
    if gap >= 20:
        wider = la if s["a_total"] > s["b_total"] else lb
        lines.append(f"{wider} memiliki cakupan yang lebih luas.")
    recs = []
    if s["bertentangan"]:
        recs.append(f"Periksa {s['bertentangan']} pasangan bertentangan: skenario dan datanya sama tetapi hasil harapannya berbeda. "
                    f"Tentukan hasil yang benar bersama tim atau Product Owner.")
    if s["a_only"]:
        recs.append(f"{s['a_only']} test case hanya ada di {la}. Pastikan memang dibutuhkan (mis. detail tampilan) atau tambahkan ke {lb}.")
    if s["b_only"]:
        recs.append(f"{s['b_only']} test case hanya ada di {lb}. Pastikan memang dibutuhkan (mis. aturan bisnis) atau tambahkan ke {la}.")
    if s["perlu_dicek"]:
        recs.append(f"{s['perlu_dicek']} pasangan perlu dicek manual karena kemiripannya belum cukup jelas.")
    if s["dup_a"] or s["dup_b"]:
        recs.append(f"Gabungkan test case kembar: {s['dup_a']} di {la}, {s['dup_b']} di {lb}.")
    if not recs:
        recs.append("Tidak ada temuan yang perlu ditindaklanjuti.")
    return {"summary": lines, "recommendations": recs,
            "limits": ["Persentase cakupan hanya menunjukkan hubungan antar test case, bukan kualitas aplikasi.",
                       "Status dari AI adalah saran; keputusan akhir tetap di QA."]}


# ----------------------------------------------------------------------------- simpan
def reserve_dir(name: str, out_base: Path = OUT_BASE) -> Path:
    out_base.mkdir(parents=True, exist_ok=True)
    d = out_base / f"{_slug(name)}_{datetime.now().strftime('%Y%m%d-%H%M%S')}"
    k = 2
    while d.exists():
        d = out_base / f"{d.name}_{k}"
        k += 1
    return d


def _save(result, a, b, out_base: Path) -> Dict[str, Any]:
    d = reserve_dir(result["name"], out_base)
    d.mkdir(parents=True)
    try:
        from tc_compare.report import write_excel
        xlsx = d / f"{_slug(result['name'])}_perbandingan.xlsx"
        write_excel(result, xlsx)
        (d / "hasil.json").write_text(json.dumps(result, ensure_ascii=False, indent=1), encoding="utf-8")
        snap = {"a": [_public(t) for t in a["tcs"]], "b": [_public(t) for t in b["tcs"]]}
        (d / "sumber.json").write_text(json.dumps(snap, ensure_ascii=False), encoding="utf-8")
        meta = {"kind": "perbandingan", "name": result["name"], "time": time.time(), "mode": result["mode"],
                "labels": result["labels"], "sources": result["sources"], "stats": result["stats"],
                "xlsx_file": xlsx.name, "semantic": result["semantic"]}
        try:
            from tools import llm
            meta["model"] = llm.generation_model() if result["mode"] == "lengkap" else None
        except Exception:
            pass
        (d / "analysis_metadata.json").write_text(json.dumps(meta, ensure_ascii=False, indent=1), encoding="utf-8")
    except Exception:
        shutil.rmtree(d, ignore_errors=True)
        raise
    return {"id": d.name, "xlsx_file": xlsx.name}
