# agents/obligation_coverage_agent.py
"""
Coverage v2: dihitung per OBLIGATION & per ATOM aturan (bukan sekadar ID requirement muncul di TC).

Urutan: kumpulkan TC -> dedup (judul + test data) -> prioritas deterministik -> laporan.
Obligation yang gagal menghasilkan TC TIDAK diisi kerangka generik; dicatat di daftar `dropped_obs`
dan muncul di sheet REVIEW supaya bisa ditindaklanjuti.
"""

from collections import Counter
import re
from typing import Any, Dict, List, Optional

from tools import llm
from tools.tc_post import apply_priority, dedup_tcs
from tools.ui import ui


_REQ_ID = re.compile(r"^[A-Za-z]{1,6}-[\w.-]+$")


def _clean_req_ids(ids: List[str]) -> List[str]:
    """Hanya ID requirement sungguhan (FR-001, AC-3, ...). Label bebas seperti "MFA Setup State" bukan ID."""
    return [i for i in ids if _REQ_ID.match(str(i).strip())]


_LABEL_LINE = re.compile(r"^\s*([^:=\n]{2,40}?)\s*([:=])(.*)$")
MAP_SYSTEM = "Kamu QA analyst. Cocokkan label data uji dengan nama field di PRD. Jawab HANYA JSON valid."


def _words(text: str) -> set:
    return set(re.findall(r"[a-z0-9]+", (text or "").lower()))


def unify_field_labels(tcs: List[Dict[str, Any]], fields: List[str], known: Optional[set] = None,
                       use_ai: bool = True) -> int:
    """Label Test Data tulisan AI yang menyebut field yang sama dengan kata/bahasa lain ("Nama Penerima",
    "Kuantitas") diganti nama field persis dari PRD ("Recipient Name", "Cart Item Quantity").
      1) kata label adalah bagian dari tepat SATU nama field PRD -> langsung dipakai
      2) sisanya dicocokkan AI sekali jalan terhadap daftar nama field PRD ini (bahasa apa pun)
    Label yang sudah dibuat kode (known) dan yang tidak cocok ke field mana pun dibiarkan; nilai tidak disentuh."""
    fields = [f for f in dict.fromkeys(fields) if f and f != "-"]
    exact = {f.lower(): f for f in fields}
    known = {k.lower() for k in (known or set())}
    mapping: Dict[str, Optional[str]] = {}
    pending = []
    for t in tcs:
        for line in (t.get("test_data") or "").split("\n"):
            m = _LABEL_LINE.match(line)
            if not m:
                continue
            label = m.group(1).strip()
            low = label.lower()
            if low in exact or low in known or low in mapping or label in pending:
                continue
            hits = [f for f in fields if _words(label) and _words(label) <= _words(f)]
            if len(hits) == 1:
                mapping[low] = hits[0]
            else:
                pending.append(label)
    if pending and use_ai and fields:
        prompt = ("Nama field di PRD:\n- " + "\n- ".join(fields) + "\n\nLabel data uji:\n- " + "\n- ".join(pending[:60]) +
                  "\n\nUntuk setiap label, tulis nama field PRD yang dimaksud (persis seperti daftar), atau null bila "
                  "bukan salah satu field itu atau ragu.\n"
                  'FORMAT: {"map":{"<label>":"<nama field PRD atau null>"}}')
        data = llm.chat_json(llm.generation_model(), MAP_SYSTEM, prompt, temperature=0.0, num_predict=800)
        for k, v in ((data or {}).get("map") or {}).items() if isinstance(data, dict) else []:
            if isinstance(v, str) and v.strip().lower() in exact:
                mapping[str(k).strip().lower()] = exact[v.strip().lower()]
    changed = 0
    for t in tcs:
        lines = []
        for line in (t.get("test_data") or "").split("\n"):
            m = _LABEL_LINE.match(line)
            if m and mapping.get(m.group(1).strip().lower()):
                line = f"{mapping[m.group(1).strip().lower()]}{m.group(2)}{m.group(3)}"  # nilai tidak disentuh
                changed += 1
            lines.append(line)
        t["test_data"] = "\n".join(lines)
    return changed


def distinguish_titles(tcs: List[Dict[str, Any]]) -> int:
    """Judul yang sama persis untuk skenario berbeda -> ditambah pembeda: nilai Test Data yang berbeda
    di antara test case kembar itu (mis. "(Gateway result: FAILED)"), atau nama fiturnya."""
    def fields(t):
        out = {}
        for line in (t.get("test_data") or "").split("\n"):
            m = re.match(r"^\s*([^:\n]{1,40}):\s*(.+)$", line)
            if m:
                out[m.group(1).strip()] = m.group(2).strip()
        for k, v in re.findall(r"([A-Za-z][\w ]{1,40}?) bernilai ([^,;]+)", t.get("preconditions") or ""):
            out.setdefault(k.strip(), v.strip())  # kondisi decision table yang ada di Pre-condition
        return out

    groups: Dict[str, List[Dict[str, Any]]] = {}
    for t in tcs:
        groups.setdefault(t["title"].strip().lower(), []).append(t)
    n = 0
    for same in groups.values():
        if len(same) < 2:
            continue
        data = [fields(t) for t in same]
        keys = [k for k in dict.fromkeys(k for d in data for k in d) if len({d.get(k) for d in data}) > 1]
        feats = {t.get("sub_label") for t in same}
        for t, d in zip(same, data):
            extra = ", ".join(f"{k}: {d[k][:30]}" for k in keys if k in d)
            if not extra and len(feats) > 1 and t.get("sub_label") not in (None, "", "-"):
                extra = t["sub_label"]
            if extra:
                t["title"] = f"{t['title'].rstrip('. ')} ({extra})"
                n += 1
    return n


def build_report(obligations: List[Dict[str, Any]], tcs: List[Dict[str, Any]], atoms: List[Dict[str, Any]],
                 requirements: Dict[str, Any]) -> Dict[str, Any]:
    req_ids = [r["id"] for r in requirements.get("requirements", []) if r.get("id")]
    covered_req = {rid for t in tcs for rid in t["requirement_ids"]}
    atom_ids = {a["atom_id"] for a in atoms}
    covered_atoms = {a for t in tcs for a in (t.get("atom_ids") or [t["atom_id"]])}
    covered_obs = {o for t in tcs for o in [t["ob_id"], *t.get("merged_ob_ids", [])]}
    flagged = [t for t in tcs if t.get("review_flag")]
    return {
        "obligations_total": len(obligations),
        "test_cases": len(tcs),
        "obligations_covered": len(covered_obs & {o["ob_id"] for o in obligations}),
        "atoms_total": len(atom_ids),
        "atoms_covered": len(covered_atoms & atom_ids),
        "requirements_total": len(req_ids),
        "requirements_covered": len([r for r in req_ids if r in covered_req]),
        "requirements_uncovered": [r for r in req_ids if r not in covered_req],
        "ac_ids": sorted(r for r in covered_req if r.startswith("AC-")),
        "by_technique": dict(Counter(t["technique"] for t in tcs)),
        "by_category": dict(Counter(t["category"] for t in tcs)),
        "by_priority": dict(Counter(t["priority"] for t in tcs)),
        "by_source": dict(Counter(t["source"] for t in tcs)),
        "by_kind": dict(Counter(t["kind"] for t in tcs)),
        "needs_review": len(flagged),
    }


def obligation_coverage_node(state: dict) -> dict:
    ui.stage("coverage")
    cfg = llm.settings()
    obs = state.get("obligations", [])
    by_id = {t["ob_id"]: t for t in state.get("accepted_tcs", [])}
    dropped = list(state.get("dropped_obs", []))
    dropped_ids = {d["ob_id"] for d in dropped}
    for ob in obs:  # jaring pengaman: catat, jangan isi TC generik
        if ob["ob_id"] not in by_id and ob["ob_id"] not in dropped_ids:
            dropped.append({"ob_id": ob["ob_id"], "scenario": ob["scenario"], "module": ob["module"],
                            "reason": "TC tidak terbentuk di loop generate"})
    ordered = [by_id[o["ob_id"]] for o in obs if o["ob_id"] in by_id]

    removed: List[Dict[str, Any]] = []
    if cfg.get("dedup", True):
        ordered, removed = dedup_tcs(ordered, float(cfg.get("dedup_threshold", 0.95)))
    changed = apply_priority(ordered, cfg.get("priority_rule"))
    known = {m.group(1).strip() for o in obs for line in (o.get("data_text") or "").split("\n")
             for m in [_LABEL_LINE.match(line)] if m}  # label buatan kode sudah pasti benar
    unify_field_labels(ordered, sorted({o.get("sub_label", "") for o in obs}), known)
    distinguish_titles(ordered)
    for t in ordered:
        t["requirement_ids"] = _clean_req_ids(t.get("requirement_ids", []))
    # TC yang hanya punya label (mis. "MFA Setup State") -> ID requirement dari TC lain di fitur yang sama
    by_feat: Dict[str, List[str]] = {}
    for t in ordered:
        for rid in t["requirement_ids"]:
            by_feat.setdefault(t.get("sub_label", ""), [])
            if rid not in by_feat[t.get("sub_label", "")]:
                by_feat[t.get("sub_label", "")].append(rid)
    for t in ordered:
        if not t["requirement_ids"] and by_feat.get(t.get("sub_label", "")):
            t["requirement_ids"] = list(by_feat[t["sub_label"]])

    report = build_report(obs, ordered, state.get("atoms", []), state.get("requirements", {}))
    judge_log = state.get("judge_log", [])
    last: Dict[str, str] = {}
    for e in judge_log:
        last[e["ob_id"]] = e["verdict"]  # verdict terakhir per obligation
    report["by_judge"] = dict(Counter(last.values()))
    report["dedup_removed"] = len(removed)
    report["dropped"] = len(dropped)
    ui.stage_done("coverage", f"{len(ordered)} TC, {len(removed)} duplikat digabung")
    ui.event("coverage", f"obligations {report['obligations_covered']}/{report['obligations_total']} | "
                         f"atoms {report['atoms_covered']}/{report['atoms_total']} | requirements "
                         f"{report['requirements_covered']}/{report['requirements_total']} | review={report['needs_review']} "
                         f"| dedup=-{len(removed)} | prioritas diubah={changed} | tanpa TC={len(dropped)}")
    return {"final_tcs": ordered, "final_v2_tcs": ordered, "report": report, "v2_report": report,
            "dropped_obs": dropped, "dedup_removed": removed, "judge_log": judge_log}
