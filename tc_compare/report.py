"""Laporan Excel hasil Bandingkan test case."""
import re
from typing import Any, Dict, List

import openpyxl
from openpyxl.styles import Alignment, Border, Font, PatternFill, Side

from tc_compare.match import BY, LABEL

HEAD = PatternFill("solid", start_color="2E3358", end_color="2E3358")
SOFT = PatternFill("solid", start_color="ECE6FE", end_color="ECE6FE")
FILLS = {"sama": "E3F1E9", "berkaitan": "EEF4FF", "sebagian": "FFF6DD", "bertentangan": "FBE4E2", "perlu_dicek": "FCEFD9"}
THIN = Side(style="thin", color="DCDCEA")
BORDER = Border(left=THIN, right=THIN, top=THIN, bottom=THIN)
WRAP = Alignment(wrap_text=True, vertical="top")


def _sheet_name(s: str, used: set) -> str:
    s = re.sub(r"[\[\]:*?/\\]", " ", s).strip()[:31] or "Sheet"
    base, k = s, 2
    while s.lower() in used:
        s = f"{base[:28]} {k}"
        k += 1
    used.add(s.lower())
    return s


def _table(ws, headers: List[str], rows: List[List[Any]], widths: List[int], fills: List[str] = None):
    for c, h in enumerate(headers, 1):
        cell = ws.cell(1, c, h)
        cell.font, cell.fill, cell.alignment, cell.border = Font(bold=True, color="FFFFFF"), HEAD, WRAP, BORDER
        ws.column_dimensions[openpyxl.utils.get_column_letter(c)].width = widths[c - 1]
    for r, row in enumerate(rows, 2):
        for c, v in enumerate(row, 1):
            cell = ws.cell(r, c, v)
            cell.alignment, cell.border = WRAP, BORDER
            if fills and fills[r - 2]:
                cell.fill = PatternFill("solid", start_color=fills[r - 2], end_color=fills[r - 2])
    ws.freeze_panes = "A2"
    if rows:
        ws.auto_filter.ref = f"A1:{openpyxl.utils.get_column_letter(len(headers))}{len(rows) + 1}"


def write_excel(res: Dict[str, Any], path) -> None:
    from tc_compare.pipeline import pct
    la, lb = res["labels"]["a"], res["labels"]["b"]
    s = res["stats"]
    wb = openpyxl.Workbook()
    used: set = set()
    ws = wb.active
    ws.title = _sheet_name("Ringkasan", used)
    ws.column_dimensions["A"].width = 42
    ws.column_dimensions["B"].width = 90
    rows = [("Perbandingan", res["name"]), ("Mode", "Lengkap (kode + AI)" if res["mode"] == "lengkap" else "Cepat (tanpa AI chat)"),
            (f"Sumber {la}", res["sources"]["a"]["source"]), (f"Sumber {lb}", res["sources"]["b"]["source"]),
            (f"Jumlah test case {la}", s["a_total"]), (f"Jumlah test case {lb}", s["b_total"]),
            (f"{la} yang punya pasangan", f"{s['a_paired']} ({pct(s['a_coverage'])})"),
            (f"{lb} yang punya pasangan", f"{s['b_paired']} ({pct(s['b_coverage'])})"),
            (f"Hanya di {la}", s["a_only"]), (f"Hanya di {lb}", s["b_only"]),
            ("Pasangan sama", s["sama"]), ("Pasangan berkaitan", s["berkaitan"]), ("Pasangan sebagian", s["sebagian"]),
            ("Pasangan bertentangan", s["bertentangan"]), ("Pasangan perlu dicek", s["perlu_dicek"]),
            (f"Kembar di {la}", s["dup_a"]), (f"Kembar di {lb}", s["dup_b"]),
            ("Diputuskan kode", s.get("decided_by_code", 0)), ("Dinilai AI", s.get("judged_by_ai", 0)),
            ("Kemiripan makna", "Dipakai" if res.get("semantic") else "Tidak dipakai")]
    r = 1
    for k, v in rows:
        ws.cell(r, 1, k).font = Font(bold=True)
        ws.cell(r, 1).fill = SOFT
        ws.cell(r, 2, v).alignment = WRAP
        r += 1
    r += 1
    ws.cell(r, 1, "Kesimpulan").font = Font(bold=True, size=12)
    r += 1
    for line in ([res["ai_summary"]] if res.get("ai_summary") else []) + res["conclusion"]["summary"]:
        ws.cell(r, 1, line).alignment = WRAP
        ws.merge_cells(start_row=r, start_column=1, end_row=r, end_column=2)
        ws.row_dimensions[r].height = 32
        r += 1
    r += 1
    ws.cell(r, 1, "Rekomendasi").font = Font(bold=True, size=12)
    r += 1
    for i, line in enumerate(res["conclusion"]["recommendations"] + res["conclusion"]["limits"] + res.get("notes", []), 1):
        ws.cell(r, 1, f"{i}. {line}").alignment = WRAP
        ws.merge_cells(start_row=r, start_column=1, end_row=r, end_column=2)
        ws.row_dimensions[r].height = 32
        r += 1

    def pair_rows(status_filter):
        out, fills = [], []
        for p in res["pairs"]:
            if p["status"] not in status_filter:
                continue
            x, y = p["a_tc"], p["b_tc"]
            out.append([LABEL[p["status"]], p["skor"], BY.get(p["by"], p["by"]), p["alasan"],
                        x["no"], x.get("sub"), x.get("title"), x.get("data"), x.get("expected"),
                        y["no"], y.get("sub"), y.get("title"), y.get("data"), y.get("expected")])
            fills.append(FILLS.get(p["status"]))
        return out, fills

    heads = ["Status", "Skor", "Diputuskan oleh", "Alasan",
             f"{la}: No", f"{la}: Sub Module", f"{la}: Test Case", f"{la}: Test Data", f"{la}: Expected Result",
             f"{lb}: No", f"{lb}: Sub Module", f"{lb}: Test Case", f"{lb}: Test Data", f"{lb}: Expected Result"]
    widths = [13, 7, 18, 46, 10, 22, 40, 26, 40, 10, 22, 40, 26, 40]
    for title, flt in (("Berpasangan", ("sama", "berkaitan", "sebagian", "bertentangan")),
                       ("Bertentangan", ("bertentangan",)), ("Perlu dicek", ("perlu_dicek",))):
        rows_, fills = pair_rows(flt)
        _table(wb.create_sheet(_sheet_name(title, used)), heads, rows_, widths, fills)
    for side, label, other in (("only_a", la, lb), ("only_b", lb, la)):
        rows_ = [[t["no"], t.get("module"), t.get("sub"), t.get("category"), t.get("title"), t.get("data"),
                  t.get("expected"), t.get("req"), f"{t['mirip']} (skor {t['mirip_skor']:.2f})" if t.get("mirip") else "-"]
                 for t in res[side]]
        _table(wb.create_sheet(_sheet_name(f"Hanya di {label}", used)),
               ["No", "Module", "Sub Module", "Jenis", "Test Case", "Test Data", "Expected Result", "Requirement",
                f"Paling mirip di {other}"], rows_, [10, 22, 24, 11, 44, 28, 44, 14, 22])
    dup = [[la, d["a"], d["b"], d["skor"], d["alasan"]] for d in res["duplicates"]["a"]] + \
          [[lb, d["a"], d["b"], d["skor"], d["alasan"]] for d in res["duplicates"]["b"]]
    _table(wb.create_sheet(_sheet_name("Kembar", used)), ["Kumpulan", "Test case", "Kembar dengan", "Skor", "Alasan"],
           dup, [18, 14, 14, 8, 60])
    wb.save(path)
