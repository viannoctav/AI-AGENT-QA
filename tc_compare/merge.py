"""Gabungkan dua kumpulan test case menjadi satu, memakai hasil pencocokan dari pipeline perbandingan.

Aturan gabung:
  sama            -> dipakai yang dari A (PRD asli dianggap acuan), dicatat bahwa B punya test case yang sama
  sebagian /
  berkaitan /
  perlu_dicek     -> dua-duanya disimpan dan diberi tanda, biar QA yang memutuskan
  bertentangan    -> dua-duanya disimpan dan ditandai jelas: hasil harapannya berbeda, wajib diputuskan orang
  hanya di satu   -> disimpan apa adanya
  kembar          -> satu saja yang disimpan
Isi test case TIDAK PERNAH diubah. Yang ditambahkan hanya kolom Asal dan Catatan gabung.
"""
from typing import Any, Dict, List, Tuple

from tc_compare import match as M

TANDA = {
    "sama": "Sama dengan {sisi}: dipakai yang dari {acuan}.",
    "sebagian": "Mirip sebagian dengan {sisi}: salah satunya mungkin bisa dibuang, cek dulu.",
    "berkaitan": "Berkaitan dengan {sisi}: fitur sama, aspek yang diuji berbeda.",
    "perlu_dicek": "Mirip dengan {sisi}, belum pasti sama: cek sendiri.",
    "bertentangan": "BERTENTANGAN dengan {sisi}: skenario sama tetapi hasil harapannya berbeda.",
}
PERLU_ORANG = ("bertentangan", "perlu_dicek", "sebagian")


def _no(t: Dict[str, Any], label: str, urut: int) -> str:
    """Rujukan test case di kolom catatan: nama kumpulan + nomor aslinya bila ada."""
    asli = str(t.get("no") or "").strip()
    return f"{label} {asli}" if asli else f"{label} #{urut}"


def merge(pairs: List[Dict[str, Any]], dups: Dict[str, List[Dict[str, Any]]],
          A: List[Dict[str, Any]], B: List[Dict[str, Any]], la: str, lb: str) -> Dict[str, Any]:
    """pairs: pasangan mentah (masih punya indeks ai/bi). -> {"rows", "stats"} siap ditulis ke Excel."""
    buang_b: Dict[int, int] = {}          # test case B yang diwakili test case A (status "sama")
    catatan_a: Dict[int, List[str]] = {}
    catatan_b: Dict[int, List[str]] = {}
    juga_di_b: Dict[int, bool] = {}
    cek_a: Dict[int, bool] = {}
    cek_b: Dict[int, bool] = {}

    for r in pairs:
        st = r.get("status")
        if st not in M.PAIRED and st != "perlu_dicek":
            continue
        ai, bi = r["ai"], r["bi"]
        no_a, no_b = _no(A[ai], la, ai + 1), _no(B[bi], lb, bi + 1)
        if st == "sama":
            if bi not in buang_b:  # satu test case B hanya boleh diwakili satu test case A
                buang_b[bi] = ai
                juga_di_b[ai] = True
                catatan_a.setdefault(ai, []).append(TANDA["sama"].format(sisi=no_b, acuan=la))
            continue
        catatan_a.setdefault(ai, []).append(TANDA[st].format(sisi=no_b))
        catatan_b.setdefault(bi, []).append(TANDA[st].format(sisi=no_a))
        if st in PERLU_ORANG:
            cek_a[ai] = cek_b[bi] = True

    # pada tiap pasangan kembar, yang dibuang nomor keduanya ("b"), yang pertama tetap masuk
    kembar_a = {str(d["b"]) for d in ((dups or {}).get("a") or [])}
    kembar_b = {str(d["b"]) for d in ((dups or {}).get("b") or [])}

    rows: List[Dict[str, Any]] = []
    n_sama = len(buang_b)

    def tambah(t: Dict[str, Any], asal: str, catatan: List[str], perlu_cek: bool) -> None:
        bersih = {k: v for k, v in t.items() if not k.startswith("_")}  # buang data kerja pencocokan
        unik = list(dict.fromkeys(catatan))  # catatan yang sama tidak ditulis dua kali
        rows.append({**bersih, "asal": asal, "catatan_gabung": " ".join(unik) if unik else "-",
                     "perlu_cek": perlu_cek})

    for i, t in enumerate(A):
        if str(t.get("no") or "") in kembar_a:
            continue  # kembar di dalam A: cukup satu yang masuk
        tambah(t, f"{la} + {lb}" if juga_di_b.get(i) else la, catatan_a.get(i, []), bool(cek_a.get(i)))
    for i, t in enumerate(B):
        if i in buang_b or str(t.get("no") or "") in kembar_b:
            continue
        tambah(t, lb, catatan_b.get(i, []), bool(cek_b.get(i)))

    stats = {
        "total": len(rows),
        "dari_a": sum(1 for r in rows if r["asal"] == la),
        "dari_b": sum(1 for r in rows if r["asal"] == lb),
        "sama": n_sama,
        "perlu_cek": sum(1 for r in rows if r["perlu_cek"]),
        "bertentangan": sum(1 for r in rows if "BERTENTANGAN" in r["catatan_gabung"]),
        "kembar_dibuang": len(kembar_a) + len(kembar_b),
        "sebelum": len(A) + len(B),
    }
    return {"rows": rows, "stats": stats}


def conclusion(stats: Dict[str, Any], la: str, lb: str) -> str:
    t = (f"{stats['sebelum']} test case dari dua kumpulan digabung menjadi {stats['total']}. "
         f"{stats['sama']} pasang dinilai sama, jadi yang dipakai hanya yang dari {la}. "
         f"{stats['dari_a']} test case berasal dari {la} saja dan {stats['dari_b']} dari {lb} saja.")
    if stats["kembar_dibuang"]:
        t += f" {stats['kembar_dibuang']} test case kembar di dalam satu kumpulan ikut dibuang."
    if stats["bertentangan"]:
        t += (f" {stats['bertentangan']} test case bertentangan (skenario sama, hasil harapan berbeda) "
              f"dan wajib kamu putuskan sendiri.")
    if stats["perlu_cek"]:
        t += f" {stats['perlu_cek']} test case diberi tanda untuk dicek: lihat kolom Catatan gabung."
    return t


# --------------------------------------------------------------------------- Excel hasil gabungan
_HEADERS = ["TC No.", "Module/Menu", "Sub Module/Menu", "Test Case Type", "Test Case", "Pre-condition",
            "Test Steps", "Test Data", "Expected Result", "Actual Result", "Status", "Notes",
            "Asal", "Catatan gabung"]
_WIDTHS = [10, 24, 28, 14, 46, 34, 48, 32, 44, 16, 12, 20, 22, 52]


def write_excel(rows: List[Dict[str, Any]], stats: Dict[str, Any], labels: Tuple[str, str],
                nama: str, path) -> str:
    """Satu file test case gabungan, memakai template yang sama dengan hasil Generator Test Case."""
    import openpyxl
    from datetime import datetime
    from openpyxl.styles import Alignment, Border, Font, PatternFill, Side

    wb = openpyxl.Workbook()
    ws = wb.active
    ws.title = "TEST CASES"
    for i, w in enumerate(_WIDTHS, 1):
        ws.column_dimensions[openpyxl.utils.get_column_letter(i)].width = w
    hfill = PatternFill("solid", start_color="366092", end_color="366092")
    mfill = PatternFill("solid", start_color="D9E1F2", end_color="D9E1F2")
    sfill = PatternFill("solid", start_color="E2EFDA", end_color="E2EFDA")
    cekfill = PatternFill("solid", start_color="FFF2CC", end_color="FFF2CC")
    lawanfill = PatternFill("solid", start_color="FCE4D6", end_color="FCE4D6")
    thin = Side(style="thin")
    border = Border(left=thin, right=thin, top=thin, bottom=thin)
    center = Alignment(horizontal="center", vertical="center", wrap_text=True)
    left = Alignment(horizontal="left", vertical="top", wrap_text=True)

    meta = [("Latest Test Date", datetime.now().strftime("%Y-%m-%d %H:%M:%S")), ("PIC QA", "AI QA Generator"),
            ("Test Template version", "2.0"), ("Sumber", f"Gabungan: {labels[0]} + {labels[1]}"),
            ("Test environment", "Development"), ("Browser Type", "Chrome / Firefox / Safari")]
    row = 1
    for k, v in meta:
        ws.cell(row, 1, k).font = Font(bold=True, size=10)
        ws.cell(row, 1).fill = mfill
        ws.cell(row, 2, v)
        row += 1
    row += 1
    for c, h in enumerate(_HEADERS, 1):
        cell = ws.cell(row, c, h)
        cell.font, cell.fill, cell.alignment, cell.border = Font(bold=True, color="FFFFFF", size=11), hfill, center, border
    row += 1

    groups: Dict[str, List[Dict[str, Any]]] = {}
    for t in rows:
        key = str(t.get("sub") or t.get("module") or "Lainnya").strip() or "Lainnya"
        groups.setdefault(key, []).append(t)
    n = 0
    for grp, items in groups.items():
        ws.cell(row, 1, grp).font = Font(bold=True, size=11, color="375623")
        ws.cell(row, 1).fill = sfill
        ws.merge_cells(start_row=row, start_column=1, end_row=row, end_column=len(_HEADERS))
        row += 1
        for t in items:
            n += 1
            vals = [f"TC-{n:03d}", t.get("module") or "General", t.get("sub") or "-", t.get("category") or "",
                    t.get("title") or "", t.get("pre") or "-", t.get("steps") or "-", t.get("data") or "-",
                    t.get("expected") or "-", "", "", "", t.get("asal") or "", t.get("catatan_gabung") or "-"]
            for c, v in enumerate(vals, 1):
                cell = ws.cell(row, c, v)
                cell.alignment = center if c in (1, 4, 11) else left
                cell.border = border
                cell.font = Font(size=10)
            if "BERTENTANGAN" in (t.get("catatan_gabung") or ""):
                ws.cell(row, len(_HEADERS)).fill = lawanfill
            elif t.get("perlu_cek"):
                ws.cell(row, len(_HEADERS)).fill = cekfill
            row += 1

    ws2 = wb.create_sheet("RINGKASAN")
    ws2.column_dimensions["A"].width = 42
    ws2.column_dimensions["B"].width = 58
    isi = [("Nama gabungan", nama), ("Kumpulan A", labels[0]), ("Kumpulan B", labels[1]),
           ("Test case sebelum digabung", stats["sebelum"]), ("Test case setelah digabung", stats["total"]),
           (f"Dipakai dari {labels[0]} saja", stats["dari_a"]), (f"Dipakai dari {labels[1]} saja", stats["dari_b"]),
           ("Pasangan yang dinilai sama (B tidak ikut)", stats["sama"]),
           ("Test case kembar yang dibuang", stats["kembar_dibuang"]),
           ("Bertentangan (wajib diputuskan orang)", stats["bertentangan"]),
           ("Diberi tanda untuk dicek", stats["perlu_cek"])]
    for i, (k, v) in enumerate(isi, 1):
        ws2.cell(i, 1, k).font = Font(bold=True, size=10)
        ws2.cell(i, 1).fill = mfill
        ws2.cell(i, 2, v).alignment = Alignment(wrap_text=True, vertical="top")
    ws2.cell(len(isi) + 2, 1, "Catatan").font = Font(bold=True, size=10)
    ws2.cell(len(isi) + 2, 2, conclusion(stats, labels[0], labels[1])).alignment = Alignment(wrap_text=True, vertical="top")

    wb.save(str(path))
    return str(path)
