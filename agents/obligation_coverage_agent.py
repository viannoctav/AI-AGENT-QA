# agents/obligation_coverage_agent.py
"""
Coverage v2: dihitung per OBLIGATION & per ATOM aturan (bukan sekadar ID requirement muncul di TC).

Urutan: kumpulkan TC -> dedup (judul + test data) -> prioritas deterministik -> laporan.
Obligation yang gagal menghasilkan TC TIDAK diisi kerangka generik; dicatat di daftar `dropped_obs`
dan muncul di sheet REVIEW supaya bisa ditindaklanjuti.
"""

from collections import Counter
from typing import Any, Dict, List

from tools import llm
from tools.tc_post import apply_priority, dedup_tcs
from tools.ui import ui


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

    report = build_report(obs, ordered, state.get("atoms", []), state.get("requirements", {}))
    report["dedup_removed"] = len(removed)
    report["dropped"] = len(dropped)
    ui.stage_done("coverage", f"{len(ordered)} TC, {len(removed)} duplikat digabung")
    ui.event("coverage", f"obligations {report['obligations_covered']}/{report['obligations_total']} | "
                         f"atoms {report['atoms_covered']}/{report['atoms_total']} | requirements "
                         f"{report['requirements_covered']}/{report['requirements_total']} | review={report['needs_review']} "
                         f"| dedup=-{len(removed)} | prioritas diubah={changed} | tanpa TC={len(dropped)}")
    return {"final_tcs": ordered, "final_v2_tcs": ordered, "report": report, "v2_report": report,
            "dropped_obs": dropped, "dedup_removed": removed}
