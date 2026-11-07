# agents/export_agent.py
"""
Export. Kolom mengikuti template perusahaan (+ Test Steps setelah Pre-condition), lalu kolom
tambahan: Technique, Priority, Obligation ID, Review Flag. File output diberi suffix
sehingga tidak menimpa hasil pipeline lama.
  Module/Menu     = modul/menu PRD (sama untuk satu PRD)
  Sub Module/Menu = fitur yang diuji (judul requirement), "-" bila tidak ada
"""

import json
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List

import openpyxl
from openpyxl.styles import Alignment, Border, Font, PatternFill, Side

from tools import llm
from tools.ui import ui

_HEADERS = ["TC No.", "Module/Menu", "Sub Module/Menu", "Test Case Type", "Test Case", "Pre-condition",
            "Test Steps", "Test Data", "Expected Result", "Actual Result", "Status", "Notes", "Requirement ID",
            "Technique", "Priority", "Obligation ID", "Review Flag"]
_WIDTHS = [10, 24, 28, 12, 46, 36, 48, 36, 46, 18, 12, 22, 22, 26, 10, 12, 44]


def create_excel(tcs: List[Dict[str, Any]], report: Dict[str, Any], requirements: Dict[str, Any],
                    prd_name: str, output_dir: str = "outputs", dropped: List[Dict[str, Any]] = None,
                    removed: List[Dict[str, Any]] = None) -> str:
    dropped = dropped or []
    removed = removed or []
    wb = openpyxl.Workbook()
    ws = wb.active
    ws.title = "TEST CASES"
    for i, w in enumerate(_WIDTHS, 1):
        ws.column_dimensions[openpyxl.utils.get_column_letter(i)].width = w

    hfill = PatternFill("solid", start_color="366092", end_color="366092")
    hfont = Font(bold=True, color="FFFFFF", size=11)
    mfill = PatternFill("solid", start_color="D9E1F2", end_color="D9E1F2")
    sfill = PatternFill("solid", start_color="E2EFDA", end_color="E2EFDA")
    flagfill = PatternFill("solid", start_color="FFF2CC", end_color="FFF2CC")
    thin = Side(style="thin")
    border = Border(left=thin, right=thin, top=thin, bottom=thin)
    center = Alignment(horizontal="center", vertical="center", wrap_text=True)
    left = Alignment(horizontal="left", vertical="top", wrap_text=True)

    meta = [("Latest Test Date", datetime.now().strftime("%Y-%m-%d %H:%M:%S")), ("PIC QA", "AI QA Generator"),
            ("Test Template version", "2.0"), ("Test environment", "Development"), ("URL", ""),
            ("Browser Type", "Chrome / Firefox / Safari")]
    row = 1
    for k, v in meta:
        ws.cell(row, 1, k).font = Font(bold=True, size=10)
        ws.cell(row, 1).fill = mfill
        ws.cell(row, 2, v)
        row += 1
    row += 1
    for c, h in enumerate(_HEADERS, 1):
        cell = ws.cell(row, c, h)
        cell.font, cell.fill, cell.alignment, cell.border = hfont, hfill, center, border
    header_row = row
    row += 1

    groups: Dict[str, List[Dict[str, Any]]] = {}
    for t in tcs:  # tcs sudah berurutan sesuai obligation (urutan dokumen PRD); baris judul per fitur
        sub = t.get("sub_label")
        groups.setdefault(sub if sub and sub != "-" else (t.get("module") or "General"), []).append(t)

    n = 0
    for grp, items in groups.items():
        ws.cell(row, 1, grp).font = Font(bold=True, size=11, color="375623")
        ws.cell(row, 1).fill = sfill
        ws.merge_cells(start_row=row, start_column=1, end_row=row, end_column=len(_HEADERS))
        row += 1
        for t in items:
            n += 1
            t["tc_no"] = f"TC-{n:03d}"
            vals = [t["tc_no"], t.get("module") or "General", t.get("sub_label") or "-", t.get("category", ""),
                    t.get("title", ""), t.get("preconditions", "") or "-", t.get("steps", "") or "-",
                    t.get("test_data", "") or "-",
                    t.get("expected_result", ""), "", "",
                    ("Digabung dari duplikat: " + ", ".join(t["merged_ob_ids"])) if t.get("merged_ob_ids") else "",
                    ", ".join(t.get("requirement_ids", [])), t.get("technique", ""), t.get("priority", ""),
                    ", ".join([t.get("ob_id", ""), *t.get("merged_ob_ids", [])]), t.get("review_flag", "")]
            for c, v in enumerate(vals, 1):
                cell = ws.cell(row, c, v)
                cell.border = border
                cell.alignment = center if c in (1, 4, 14, 15, 16) else left
                cell.font = Font(size=10)
            if t.get("review_flag"):
                ws.cell(row, len(_HEADERS)).fill = flagfill
            row += 1
    ws.freeze_panes = f"A{header_row + 1}"
    ws.auto_filter.ref = f"A{header_row}:{openpyxl.utils.get_column_letter(len(_HEADERS))}{row - 1}"

    # ---- SUMMARY
    sm = wb.create_sheet("SUMMARY")
    sm.column_dimensions["A"].width = 38
    sm.column_dimensions["B"].width = 26
    r = 1
    sm.cell(r, 1, "TEST SUITE SUMMARY").font = Font(bold=True, size=14)
    r += 2

    def put(label, value):
        nonlocal r
        sm.cell(r, 1, label).font = Font(bold=True)
        sm.cell(r, 1).fill = mfill
        c = sm.cell(r, 2, value)
        c.alignment = center
        r += 1

    cat = report.get("by_category", {})
    put("Total Test Cases", report.get("test_cases", len(tcs)))
    put("Positive Cases", cat.get("Positive", 0))
    put("Negative Cases", cat.get("Negative", 0))
    put("Technique Used", len(report.get("by_technique", {})))
    put("Obligation Covered", f"{report.get('obligations_covered', 0)}/{report.get('obligations_total', 0)}")
    put("Rule Atom Covered", f"{report.get('atoms_covered', 0)}/{report.get('atoms_total', 0)}")
    put("Requirement Covered (ID)", f"{report.get('requirements_covered', 0)}/{report.get('requirements_total', 0)}")
    put("Uncovered Requirement", ", ".join(report.get("requirements_uncovered", [])) or "-")
    put("TC Perlu Review", report.get("needs_review", 0))
    put("Duplikat Digabung", report.get("dedup_removed", len(removed)))
    put("Obligation Tanpa TC", report.get("dropped", len(dropped)))
    for _v, _n in sorted((report.get("by_judge") or {}).items()):
        put(f"Juri: {_v}", _n)
    put("Sumber: LLM terverifikasi", report.get("by_source", {}).get("llm", 0))
    put("Sumber: Template otomatis", report.get("by_source", {}).get("template", 0))
    put("Sumber: LLM tidak terverifikasi", report.get("by_source", {}).get("llm-unverified", 0))
    put("Sumber: Kerangka otomatis", report.get("by_source", {}).get("skeleton", 0))
    r += 1
    for title, key in (("Per Teknik", "by_technique"), ("Per Prioritas", "by_priority"), ("Per Jenis Aturan", "by_kind")):
        sm.cell(r, 1, title).font = Font(bold=True, size=12)
        r += 1
        for k, v in sorted(report.get(key, {}).items(), key=lambda x: -x[1]):
            sm.cell(r, 1, k)
            sm.cell(r, 2, v).alignment = center
            r += 1
        r += 1

    # ---- TRACEABILITY
    tr = wb.create_sheet("TRACEABILITY")
    for i, (h, w) in enumerate((("Requirement ID", 16), ("Judul", 44), ("Jumlah TC", 12), ("TC No.", 70)), 1):
        tr.cell(1, i, h).font = hfont
        tr.cell(1, i).fill = hfill
        tr.column_dimensions[openpyxl.utils.get_column_letter(i)].width = w
    by_req: Dict[str, List[str]] = {}
    for t in tcs:
        for rid in t.get("requirement_ids", []):
            by_req.setdefault(rid, []).append(t.get("tc_no", ""))
    titles = {x["id"]: x.get("title", "") for x in requirements.get("requirements", [])}
    ids = list(titles) + sorted(k for k in by_req if k not in titles)
    for i, rid in enumerate(ids, 2):
        tr.cell(i, 1, rid)
        tr.cell(i, 2, titles.get(rid, ""))
        tr.cell(i, 3, len(by_req.get(rid, [])))
        tr.cell(i, 4, ", ".join(by_req.get(rid, [])) or "BELUM TER-COVER").alignment = left

    # ---- REVIEW
    rv = wb.create_sheet("REVIEW")
    for i, (h, w) in enumerate((("TC No.", 10), ("Test Case", 60), ("Alasan Review", 90)), 1):
        rv.cell(1, i, h).font = hfont
        rv.cell(1, i).fill = hfill
        rv.column_dimensions[openpyxl.utils.get_column_letter(i)].width = w
    j = 2
    for t in tcs:
        if t.get("review_flag"):
            rv.cell(j, 1, t.get("tc_no", ""))
            rv.cell(j, 2, t.get("title", "")).alignment = left
            rv.cell(j, 3, t["review_flag"]).alignment = left
            j += 1

    for d in dropped:
        rv.cell(j, 1, d.get("ob_id", ""))
        rv.cell(j, 2, d.get("scenario", "")).alignment = left
        rv.cell(j, 3, "TIDAK ADA TC - " + d.get("reason", "")).alignment = left
        rv.cell(j, 3).fill = flagfill
        j += 1
    for d in removed:
        rv.cell(j, 1, d.get("ob_id", ""))
        rv.cell(j, 2, d.get("title", "")).alignment = left
        rv.cell(j, 3, f"Duplikat digabung ke {d.get('kept_ob_id')}").alignment = left
        j += 1

    out = Path(output_dir)
    out.mkdir(parents=True, exist_ok=True)
    suffix = llm.settings().get("output_suffix", "_v2")
    path = out / f"{prd_name.replace(' ', '_')}_test_cases{suffix}.xlsx"
    wb.save(str(path))
    return str(path)


def export_node(state: dict) -> dict:
    ui.stage("export")
    tcs = state.get("final_tcs") or state.get("final_v2_tcs") or []
    report = state.get("report") or state.get("v2_report") or {}
    prd_name = state.get("prd_name", "Test_Suite")
    output_dir = state.get("output_dir", "outputs")
    path = create_excel(tcs, report, state.get("requirements", {}), prd_name, output_dir,
                        state.get("dropped_obs", []), state.get("dedup_removed", []))
    dbg = Path(output_dir) / f"{prd_name.replace(' ', '_')}_artifacts.json"
    try:
        dbg.write_text(json.dumps({
            "atoms": state.get("atoms", []), "obligations": state.get("obligations", []),
            "tcs": tcs, "report": report, "dropped": state.get("dropped_obs", []),
            "dedup_removed": state.get("dedup_removed", []),
            "judge_log": state.get("judge_log", [])}, ensure_ascii=False, indent=1, default=list), encoding="utf-8")
    except Exception as e:
        ui.event("export", f"gagal menulis artifacts json: {e}", "red")
    ui.stage_done("export", path)
    ui.event("export", path, "green")
    return {"output_path": path}