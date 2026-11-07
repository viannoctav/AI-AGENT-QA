# tc_workflows/tc_graph.py
"""
Graph v2 (additive).

parse+atomize -> design -> [prepare_batch -> expand -> verify -> (retry|next|done)]* -> coverage(dedup, prioritas) -> export
"""

from langgraph.graph import END, StateGraph

from agents.export_agent import export_node
from agents.obligation_coverage_agent import obligation_coverage_node
from agents.obligation_expander_agent import obligation_expander_node
from agents.rule_atomizer_agent import rule_atomizer_node
from agents.semantic_verifier_agent import semantic_verifier_node
from agents.test_designer_agent import test_designer_node
from tc_workflows.state import TCStateV2
from tools import cancel, llm
from tools.tc_post import select_obligations
from tools.ui import ui


def atomize_node(state: dict) -> dict:
    ui.stage("atomize", "membaca struktur PRD")
    return rule_atomizer_node(state)


def design_node(state: dict) -> dict:
    ui.stage("design", "menyusun obligation")
    out = test_designer_node(state)
    cap = llm.settings().get("max_obligations")
    total = len(out["obligations"])
    if cap and total > int(cap):
        out["obligations"] = select_obligations(out["obligations"], int(cap))  # kuota teknik, bukan urutan prioritas
        out["ob_queue"] = list(out["obligations"])
        ui.event("designer", f"dibatasi max_obligations={cap} dari {total} (kuota per teknik, tiap atom min. 1)", "yellow")
    if llm.auto_model():
        # obligation "heavy" (decision/edge/whitespace Auto) ditulis & dijuri auto_model PALING AKHIR -> model hanya berganti sekali
        light = [o for o in out["obligations"] if not llm.is_heavy(o)]
        heavy = [o for o in out["obligations"] if llm.is_heavy(o)]
        out["ob_queue"] = light + heavy
        ui.event("designer", f"{len(light)} obligation -> {llm.generation_model()}, {len(heavy)} (decision/edge) -> {llm.auto_model()}")
    ui.set_total(len(out["obligations"]))
    ui.stage_done("design", f"{len(out['obligations'])} obligation")
    out.update({"accepted_tcs": [], "dropped_obs": [], "judge_log": [], "current_batch": [], "batch_attempt": 0,
                "batch_feedback": {}, "draft_map": {}})
    return out


def prepare_batch_node(state: dict) -> dict:
    cancel.check()
    ui.stage("generate", "LLM menulis TC per batch")
    queue = list(state.get("ob_queue", []))
    size = int(llm.settings()["batch_size"])
    batch = []
    while queue and len(batch) < size:
        if batch and (queue[0].get("sub_label") != batch[0].get("sub_label")
                      or llm.is_heavy(queue[0]) != llm.is_heavy(batch[0])):
            break
        batch.append(queue.pop(0))
    return {"ob_queue": queue, "current_batch": batch, "batch_attempt": 0, "batch_feedback": {}, "draft_map": {}}


def route_after_verify(state: dict) -> str:
    if state.get("current_batch"):
        return "expand"
    if state.get("ob_queue"):
        return "prepare_batch"
    return "coverage"


def build_graph():
    g = StateGraph(TCStateV2)
    g.add_node("atomize", atomize_node)
    g.add_node("design", design_node)
    g.add_node("prepare_batch", prepare_batch_node)
    g.add_node("expand", obligation_expander_node)
    g.add_node("verify", semantic_verifier_node)
    g.add_node("coverage", obligation_coverage_node)
    g.add_node("export", export_node)
    g.set_entry_point("atomize")
    g.add_edge("atomize", "design")
    g.add_edge("design", "prepare_batch")
    g.add_edge("prepare_batch", "expand")
    g.add_edge("expand", "verify")
    g.add_conditional_edges("verify", route_after_verify,
                            {"expand": "expand", "prepare_batch": "prepare_batch", "coverage": "coverage"})
    g.add_edge("coverage", "export")
    g.add_edge("export", END)
    return g.compile()


tc_graph = build_graph()