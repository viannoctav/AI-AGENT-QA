"""PRD memakai format yang sama persis dengan Catatan Konversi ke PRD (dibaca generator test case).
Catatan review khusus desain: hal yang perlu dikonfirmasi, teks yang terbaca per layar, dan asal setiap aturan."""
import re
from typing import Any, Dict, List

from free_text_to_prd import render as ftr


def render_markdown(doc: Dict[str, Any]) -> str:
    md = ftr.render_markdown(doc)
    meta = doc.get("meta", {})
    purpose = (f"**Document Purpose:** Disusun otomatis dari {meta.get('source', 'desain')} ({meta.get('created', '')}). "
               "Teks di dalam tanda kutip disalin persis dari desain.")
    return re.sub(r"^\*\*Document Purpose:\*\*.*$", lambda m: purpose, md, count=1, flags=re.M)


def render_review(doc: Dict[str, Any], rejected: List[Dict[str, Any]], screens: List[Dict[str, Any]]) -> str:
    meta = doc.get("meta", {})
    title = doc.get("module") or "Desain"
    q = ftr._quote
    L: List[str] = [f"# Catatan Review — {title}", "",
                    f"Pendamping PRD yang disusun dari {meta.get('source', 'desain')} ({meta.get('created', '')}). "
                    "Isi file ini BUKAN bagian PRD dan tidak dipakai untuk membuat test case.", ""]
    qs = doc.get("questions") or []

    def q_line(x):
        where = f" ({x['fitur']})" if x.get("fitur") else ""
        src = f" — Penjelasan: {q(x['kutipan'])}" if x.get("kutipan") else ""
        return f"- {x['pertanyaan']}{where}{src}"

    groups = [("Perlu dikonfirmasi dari desain", [x for x in qs if x["jenis"] == "konfirmasi desain"]),
              ("Bertentangan", [x for x in qs if x["jenis"] == "bertentangan"]),
              ("Belum jelas (tanyakan ke tim)", [x for x in qs if x["jenis"] == "belum jelas"])]
    n = 0
    for head, xs in groups:
        n += 1
        L += [f"## {n}. {head}", ""] + ([q_line(x) for x in xs] or ["- Tidak ada."]) + [""]
    n += 1
    L += [f"## {n}. Penjelasan yang belum masuk PRD", "", "Tidak berhasil disusun menjadi aturan. Tambahkan manual bila perlu.", ""]
    L += [f"- Penjelasan {m['sumber']} baris {m['baris']}: {q(m['teks'])}" for m in doc.get("missed_lines") or []] or ["- Tidak ada."]
    n += 1
    L += ["", f"## {n}. Isian AI yang ditolak penjaga anti-karangan", "", "Tidak dimasukkan ke PRD.", ""]
    for r in rejected:
        L.append(f"- {ftr._txt(r.get('pernyataan') or '-')} Alasan: {r.get('alasan', '')}.")
    if not rejected:
        L.append("- Tidak ada.")
    n += 1
    L += ["", f"## {n}. Teks yang terbaca per layar", "",
          "Dibaca oleh pembaca teks Windows (persis seperti di desain, termasuk salah ketik). Jenis elemen ditentukan AI.", ""]
    for s in screens:
        where = f"{s['image']}" + (f" layar {s['order']}" if s["of"] > 1 else "")
        L.append(f"**{s['card']} — {where}" + (f" — {s['title']}" if s.get("title") else "") + "**")
        L.append("")
        if not s["elements"]:
            L.append("- (tidak ada teks terbaca)")
        for e in s["elements"]:
            st = f", {', '.join(e['keadaan'])}" if e["keadaan"] else ""
            L.append(f"- [{e['jenis']}{st}] {e['teks']}")
        L.append("")
    n += 1
    L += [f"## {n}. Asal setiap aturan", ""]
    for i, f in enumerate(doc.get("features", []), 1):
        for k, r in enumerate(f["rules"], 1):
            L.append(f"- FR-{i:03d} aturan {k}: {r.get('sumber') or '-'}")
    return "\n".join(L).rstrip() + "\n"
