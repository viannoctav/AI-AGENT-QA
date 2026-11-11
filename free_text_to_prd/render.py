"""Susun PRD Markdown dengan format yang dibaca test case generator (sama seperti PRD contoh di knowledge/prd):
Document Information, Actors, Feature Overview, Functional Requirements (### FR-001 — Nama + Rules:),
Non-Functional Requirements, Key State Model, Decision Table Targets.
Hal yang diragukan (pertanyaan, isian yang ditolak, baris yang belum masuk, traceability) TIDAK masuk PRD;
semuanya ada di file catatan review terpisah (render_review)."""
import re
from typing import Any, Dict, List


def _txt(s: str) -> str:
    """Teks aman untuk bullet aturan: panah diganti kata supaya tidak terbaca sebagai transisi status."""
    s = re.sub(r"\s*(?:->|=>|→)\s*", " kemudian ", str(s or "")).strip()
    return s if s.endswith((".", "?", "!")) else s + "."


def _val(s: str) -> str:
    """Nilai kondisi decision table: '/' dan '=' adalah pemisah, jadi diganti."""
    return re.sub(r"\s+", " ", str(s).replace("/", " atau ").replace("=", " ")).strip()


def _quote(s: str) -> str:
    return "“" + re.sub(r"\s+", " ", str(s or "")).strip().replace("“", "'").replace("”", "'") + "”"


def render_markdown(doc: Dict[str, Any]) -> str:
    meta = doc.get("meta", {})
    title = doc.get("module") or doc.get("product") or "Catatan QA"
    L: List[str] = [f"# PRD — {title}", "", "## 1. Document Information", ""]
    if doc.get("product"):
        L.append(f"**Product:** {doc['product']}  ")
    L.append(f"**Module:** {doc.get('module') or title}  ")
    L.append(f"**Document Purpose:** Disusun otomatis dari catatan QA \"{meta.get('source', 'catatan')}\" "
             f"({meta.get('created', '')}).")
    if doc.get("roles"):
        L += ["", "---", "", "## 2. Actors", ""] + [f"- {r}" for r in doc["roles"]]
    L += ["", "---", "", "## 3. Feature Overview", ""]
    for o in doc.get("overview") or []:
        L.append(_txt(o))
        L.append("")
    names = [f["name"] for f in doc.get("features", [])]
    if names:
        L.append("Fitur yang tercatat: " + ", ".join(names) + ".")
    L += ["", "---", "", "## 4. Functional Requirements", ""]

    trace: List[str] = []
    for n, f in enumerate(doc.get("features", []), 1):
        rid = f"FR-{n:03d}"
        L += [f"### {rid} — {f['name']}", ""]
        if f.get("description"):
            L += [_txt(f["description"]), ""]
            if f.get("desc_item"):
                trace.append(f"- {rid} (deskripsi): {_quote(f['desc_item']['kutipan'])} (baris {f['desc_item']['baris']})")
        L.append("Rules:")
        for k, r in enumerate(f["rules"], 1):
            L.append(f"- {_txt(r['pernyataan'])}")
            trace.append(f"- {rid} aturan {k}: {_quote(r['kutipan'])} (baris {r['baris']})")
        L.append("")

    if doc.get("nfr"):
        L += ["---", "", "## 5. Non-Functional Requirements", ""]
        for n, f in enumerate(doc["nfr"], 1):
            rid = f"NFR-{n:03d}"
            L += [f"### {rid} — {f['name']}", "", "Rules:"]
            for k, r in enumerate(f["rules"], 1):
                L.append(f"- {_txt(r['pernyataan'])}")
                trace.append(f"- {rid} aturan {k}: {_quote(r['kutipan'])} (baris {r['baris']})")
            L.append("")

    if doc.get("states"):
        L += ["---", "", "## 7. Key State Model", ""]
        for s in doc["states"]:
            L += [f"### {s['object']}", ""]
            for t in s["transitions"]:
                note = f" ({t['pemicu']})" if t.get("pemicu") else ""
                L += [f"`{t['dari']} → {t['ke']}`{note}", ""]
                trace.append(f"- Status {s['object']} {t['dari']} ke {t['ke']}: {_quote(t['kutipan'])} (baris {t['baris']})")

    if doc.get("decision"):
        d = doc["decision"]
        L += ["---", "", "## 8. Decision Table Targets", "", f"### {d['title']}", "", "Conditions:"]
        for c in d["conditions"]:
            L.append(f"- {c['name']} = " + " / ".join(_val(v) for v in c["values"]))
        L += ["", "Expected behavior must follow the role access rules written in the Functional Requirements.", ""]

    doc["_trace"] = trace  # dipakai catatan review (file terpisah), tidak masuk PRD
    return "\n".join(L).rstrip() + "\n"


def render_review(doc: Dict[str, Any], rejected: List[Dict[str, Any]]) -> str:
    """Catatan review untuk QA, TERPISAH dari PRD: hal yang diragukan/belum jelas, isian AI yang ditolak, baris catatan
    yang belum masuk, dan asal setiap aturan. Tidak dibaca generator test case."""
    meta = doc.get("meta", {})
    title = doc.get("module") or "Catatan QA"
    L: List[str] = [f"# Catatan Review — {title}", "",
                    f"Pendamping PRD yang disusun dari catatan \"{meta.get('source', 'catatan')}\" ({meta.get('created', '')}). "
                    "Isi file ini BUKAN bagian PRD dan tidak dipakai untuk membuat test case.", ""]
    qs = doc.get("questions") or []
    conflict = [q for q in qs if q["jenis"] == "bertentangan"]
    unclear = [q for q in qs if q["jenis"] != "bertentangan"]

    def q_line(q):
        where = f" ({q['fitur']})" if q.get("fitur") else ""
        src = f" — Catatan: {_quote(q['kutipan'])}" if q.get("kutipan") else ""
        return f"- {q['pertanyaan']}{where}{src}"

    L += ["## 1. Bertentangan di catatan", ""] + ([q_line(q) for q in conflict] or ["- Tidak ada."]) + [""]
    L += ["## 2. Belum jelas (tanyakan ke tim)", ""] + ([q_line(q) for q in unclear] or ["- Tidak ada."]) + [""]
    missed = doc.get("missed_lines") or []
    L += ["## 3. Baris catatan yang belum masuk PRD", "",
          "Tidak berhasil disusun menjadi aturan. Tambahkan manual ke PRD bila memang aturan.", ""]
    L += [f"- Baris {m['baris']}: {_quote(m['teks'])}" for m in missed] or ["- Tidak ada."]
    L += ["", "## 4. Isian AI yang ditolak penjaga anti-karangan", "",
          "Tidak dimasukkan ke PRD. Bila ternyata benar, tambahkan manual ke PRD.", ""]
    for r in rejected:
        src = f" — kutipan AI: {_quote(r.get('kutipan'))}" if r.get("kutipan") else ""
        L.append(f"- {_txt(r.get('pernyataan') or '-')} Alasan: {r.get('alasan', '')}.{src}")
    if not rejected:
        L.append("- Tidak ada.")
    L += ["", "## 5. Asal setiap aturan (traceability)", ""] + (doc.get("_trace") or ["- Tidak ada."])
    return "\n".join(L).rstrip() + "\n"
