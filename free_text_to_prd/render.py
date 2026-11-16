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


# aturan yang bisa diuji angkanya/batasnya -> masuk tabel Business Rules
_CONSTRAINT = re.compile(
    r"\b(harus|wajib|minimal|maksimal|maksimum|minimum|tidak boleh|hanya|paling (?:banyak|sedikit)|batas|"
    r"kedaluwarsa|berakhir|sekali|unik|must|should|required|mandatory|at least|at most|maximum|max|minimum|min|"
    r"only|cannot|can\'t|expire[sd]?|valid|invalid|identical|unique|limit)\b", re.I)
_SKIP_BR = re.compile(r"^(dari |setelah |aksi lain|alur ini melewati|pengguna bisa membatalkan|"
                      r"pengguna dapat (?:membatalkan|menutup))", re.I)
# kalimat yang hanya mendaftar isi layar: bukan aturan yang bisa diuji
_SKIP_BR_ANY = re.compile(r"menampilkan daftar dengan kolom|status yang bisa muncul|bisa berpindah tab|"
                          r"bisa memilih|bisa membuka|di .+ tersedia|pilihan .+ yang terlihat", re.I)
_BR_FIELD = re.compile(r'^Aturan isian (".+?") di (.+?): (".+")\.?$', re.I)
_BR_FIELD2 = re.compile(r'^(.+?) wajib memenuhi aturan (".+")\.?$', re.I)
_BR_TEXT = re.compile(r'^(?:Aturan yang tertulis di|Di) (.+?)\s*(?::|tertulis(?: aturan)?)\s*(".+")\.?$', re.I)
_BR_PLAIN = re.compile(r'^Berlaku aturan (".+")\.?$', re.I)


def _br_text(t: str) -> str:
    """Padatkan kalimat aturan menjadi satu baris tabel: kutipan dulu, lokasinya di belakang."""
    m = _BR_FIELD.match(t)
    if m:
        return f"{m.group(3)} — isian {m.group(1)} pada {m.group(2)}."
    m = _BR_FIELD2.match(t)
    if m:
        return f"{m.group(2)} — berlaku untuk isian {m.group(1)}."
    m = _BR_PLAIN.match(t)
    if m:
        return f"{m.group(1)}"
    m = _BR_TEXT.match(t)
    if m:
        return f"{m.group(2)} — tertulis di {m.group(1)}."
    return t
_NUMBERY = re.compile(r"\b(\d+|karakter|character|digit|angka|menit|minute|jam|hour|detik|second|hari|day)\b", re.I)


def _cell(s: str) -> str:
    return re.sub(r"\s+", " ", str(s or "")).replace("|", "\\|").strip()


def business_rules(doc: Dict[str, Any]) -> List[str]:
    """Aturan yang bisa langsung diuji (ada batas, angka, kewajiban, atau larangan)."""
    out, seen = [], set()
    for f in doc.get("features", []):
        for r in f["rules"]:
            t = str(r.get("pernyataan") or "").strip()
            if r.get("jenis") in ("alur", "rincian") or not _CONSTRAINT.search(t):
                continue
            if _SKIP_BR_ANY.search(t) or (_SKIP_BR.match(t) and not _NUMBERY.search(t)):
                continue
            k = re.sub(r"[^a-z0-9]+", " ", t.lower()).strip()
            if k in seen:
                continue
            seen.add(k)
            out.append(_txt(_br_text(t)))
    return out[:80]


def edge_cases(doc: Dict[str, Any]) -> List[str]:
    """Area edge case yang memang punya dasar di PRD ini (bukan daftar umum)."""
    txt = " ".join(r["pernyataan"] for f in doc.get("features", []) for r in f["rules"]
                   if r.get("jenis") != "rincian").lower()
    out = []
    add = lambda c, s: out.append(s) if c else None
    add(re.search(r"\b(minimal|maksimal|minimum|maximum|at least|at most|karakter|character|digit|panjang|length)\b", txt),
        "Nilai tepat di batas minimum dan maksimum, serta satu di bawah dan satu di atas batas.")
    add(re.search(r"\b(wajib|required|harus diisi|mandatory)\b", txt), "Isian wajib dikosongkan atau hanya diisi spasi.")
    add(re.search(r"\b(angka|digit|numeric|nomor|telepon|phone|kode pos|postal)\b", txt),
        "Huruf, tanda baca, dan nilai desimal pada isian yang hanya boleh angka.")
    add(re.search(r"\b(email|surel)\b", txt), "Format email yang tidak valid.")
    add(re.search(r"\b(expire|kedaluwarsa|berakhir|menit|minute|jam|hour)\b", txt),
        "Kode atau tautan yang dipakai tepat sebelum dan sesudah masa berlakunya habis.")
    add(re.search(r"\b(percobaan|attempts?|retry|terkunci|lockout|limit)\b", txt),
        "Percobaan tepat di batas dan satu di atas batas yang diizinkan.")
    add(doc.get("states"), "Perpindahan status yang tidak diizinkan.")
    add(re.search(r"\b(pilihan|dropdown|opsi|option)\b", txt), "Pilihan dikosongkan atau diisi nilai di luar daftar.")
    out += ["Spasi di awal dan akhir isian.",
            "Tombol kirim ditekan dua kali berturut-turut.",
            "Data berubah di tengah proses (mis. data dihapus pengguna lain sebelum disimpan)."]
    return out


COVERAGE = ["Positive Testing", "Negative Testing", "Equivalence Partitioning", "Boundary Value Analysis",
            "Decision Table", "State Transition", "Edge Case Testing"]


def _flow_groups(rules: List[Dict[str, Any]]) -> List[tuple]:
    """Aturan satu FR dikelompokkan per alur (sub-judul), urut sesuai kemunculannya."""
    out: List[tuple] = []
    for r in rules:
        key = (r.get("alur") or "").strip()
        if not out or out[-1][0] != key:
            out.append((key, []))
        out[-1][1].append(r)
    gab: List[tuple] = []  # alur yang sama muncul lagi di belakang -> digabung ke kelompok pertamanya
    for key, items in out:
        prev = next((g for g in gab if g[0] == key), None)
        (prev[1].extend(items) if prev else gab.append((key, list(items))))
    return gab


def _accept(rules: List[Dict[str, Any]]) -> List[str]:
    """Acceptance Criteria per FR: diambil dari hasil yang tertulis di aturannya, bukan dikarang."""
    out: List[str] = []
    for r in rules:
        t = str(r.get("pernyataan") or "")
        m = re.match(r"Pengguna dapat (.+?)\.\s*Bila berhasil, (.+?)\.\s*$", t)
        if m:
            aksi = m.group(1)
            mf = re.search(r"dengan mengisi (.+)$", aksi)
            if mf:
                fs = re.findall(r'"[^"]+"', mf.group(1))
                if len(fs) > 3:  # daftar field panjang dipendekkan supaya kriterianya tetap terbaca
                    aksi = aksi[: mf.start(1)] + ", ".join(fs[:3]) + " dan isian lainnya"
            out.append(f"Setelah pengguna {aksi}, {m.group(2)}.")
            continue
        m = re.match(r'Sistem menampilkan notifikasi "([^"]+)"(?:.*?)setelah (.+?)\.?$', t)
        if m:
            out.append(f"Setelah {m.group(2)}, notifikasi \u201c{m.group(1)}\u201d muncul.")
            continue
        m = re.match(r"(.+?) wajib memenuhi aturan \"(.+?)\"\.?$", t)
        if m:
            out.append(f"Isian {m.group(1)} yang tidak memenuhi \u201c{m.group(2)}\u201d ditolak.")
    hasil, seen = [], set()
    for x in out:
        k = re.sub(r"\W+", " ", x.lower()).strip()
        if k not in seen:
            seen.add(k)
            hasil.append(x)
    return hasil[:8]


def render_markdown(doc: Dict[str, Any]) -> str:
    meta = doc.get("meta", {})
    title = doc.get("module") or doc.get("product") or "Catatan QA"
    L: List[str] = [f"# PRD \u2014 {title}", ""]
    num = {"n": 0}

    def sec(judul: str, garis: bool = True) -> None:
        num["n"] += 1
        if garis:
            if L and L[-1].strip():
                L.append("")
            L.extend(["---", ""])
        L.extend([f"## {num['n']}. {judul}", ""])

    sec("Document Information", False)
    if doc.get("product"):
        L.append(f"**Product:** {doc['product']}  ")
    L.append(f"**Module:** {doc.get('module') or title}  ")
    L.append(f"**Document Purpose:** Disusun otomatis dari {meta.get('source', 'catatan')} "
             f"({meta.get('created', '')}). Teks di dalam tanda kutip disalin persis dari sumbernya; "
             f"hal yang tidak terbaca di sumber tidak ditambahkan sendiri.")
    sec("Actors")
    L += [f"- {r}" for r in (doc.get("roles") or ["Pengguna aplikasi"])]
    sec("Feature Overview")
    for o in doc.get("overview") or []:
        L += [_txt(o), ""]
    names = [f["name"] for f in doc.get("features", [])]
    if names:
        L.append("Fitur yang tercakup: " + ", ".join(names) + ".")
    flows = []
    for f in doc.get("features", []):
        for r in f["rules"]:
            a = (r.get("alur") or "").strip()
            if a and a not in flows:
                flows.append(a)
    if flows:
        L += ["", "Alur yang tercakup: " + ", ".join(flows[:40]) + "."]
    L.append("")

    if doc.get("nav_rows"):
        sec("Navigation Structure")
        L += ["Nama menu disalin dari sumber. Perilaku tiap menu di luar fitur di bawah tidak dijabarkan di dokumen ini.",
              "", "| Area | Menu yang terlihat |", "|---|---|"]
        for r in doc["nav_rows"][:10]:
            L.append(f"| {_cell(r.get('area') or 'Navigasi utama')} | " + _cell(", ".join(r["items"][:30])) + " |")
        L.append("")

    trace: List[str] = []
    fr_ids: List[tuple] = []
    sec("Functional Requirements")
    for n, f in enumerate(doc.get("features", []), 1):
        rid = f"FR-{n:03d}"
        fr_ids.append((rid, f))
        L += [f"### {rid} \u2014 {f['name']}", ""]
        if f.get("description"):
            L += [_txt(f["description"]), ""]
            if f.get("desc_item"):
                trace.append(f"- {rid} (deskripsi): {_quote(f['desc_item']['kutipan'])} (baris {f['desc_item']['baris']})")
        pakai = [x for x in f["rules"] if x.get("jenis") != "rincian"]
        k = 0
        for alur, items in _flow_groups(pakai):
            if alur:
                L += [f"**{alur}**", ""]
            else:
                L.append("Rules:")
            for r in items:
                if r.get("jenis") == "alur" and r["pernyataan"].startswith("Alur ini melewati"):
                    # urutan layar = konteks, bukan kebutuhan yang diuji: ditulis miring supaya tidak
                    # ikut menjadi test case sendiri (generator hanya membaca butir berpoin)
                    L += [f"*{_txt(r['pernyataan'])}*", ""]
                    continue
                k += 1
                L.append(f"- {_txt(r['pernyataan'])}")
                trace.append(f"- {rid} aturan {k}: {_quote(r['kutipan'])} (baris {r['baris']})")
            L.append("")
        ac = _accept(pakai)
        if ac:
            L += ["*Acceptance Criteria:*", ""] + [f"- {x}" for x in ac] + [""]

    if doc.get("nfr"):
        sec("Non-Functional Requirements")
        for n, f in enumerate(doc["nfr"], 1):
            rid = f"NFR-{n:03d}"
            L += [f"### {rid} \u2014 {f['name']}", "", "Rules:"]
            for k, r in enumerate(f["rules"], 1):
                L.append(f"- {_txt(r['pernyataan'])}")
                trace.append(f"- {rid} aturan {k}: {_quote(r['kutipan'])} (baris {r['baris']})")
            L.append("")

    brs = business_rules(doc)
    if brs:
        sec("Business Rules")
        L += ["| ID | Business Rule |", "|---|---|"]
        L += [f"| BR-{n:03d} | {_cell(b)} |" for n, b in enumerate(brs, 1)]
        L.append("")

    if doc.get("fields_ref"):
        sec("Data & Field Reference")
        L += ["Field yang terlihat di sumber. Aturan yang tidak tertulis (panjang maksimum, format nomor telepon, "
              "kebijakan password selain yang tercantum) belum ditentukan dan perlu dikonfirmasi.", "",
              "| Area | Layar | Field | Keterangan dari sumber |", "|---|---|---|---|"]
        for r in doc["fields_ref"][:80]:
            L.append(f"| {_cell(r.get('area'))} | {_cell(r.get('where'))} | {_cell(r['field'])} | "
                     f"{_cell(r.get('note') or '-')} |")
        L.append("")

    if doc.get("feedback"):
        sec("System Feedback & States")
        L += ["Notifikasi yang terlihat di sumber beserta pemicunya.", "", "| Notifikasi | Muncul setelah |", "|---|---|"]
        for r in doc["feedback"][:40]:
            L.append(f"| {_cell(r['notif'])} | {_cell(r.get('when') or '-')} |")
        L.append("")

    if doc.get("status_sets") and not doc.get("states"):
        sec("Key State Model")
        L += ["Status yang terlihat di sumber. Perpindahan antarstatus belum tentu lengkap, konfirmasi ke tim:", ""]
        for st in doc["status_sets"][:20]:
            L.append(f"- {st['where']}: " + ", ".join(f"`{v}`" for v in st["values"][:14]))
        L.append("")

    if doc.get("states"):
        sec("Key State Model")
        for s in doc["states"]:
            L += [f"### {s['object']}", ""]
            for t in s["transitions"]:
                note = f" ({t['pemicu']})" if t.get("pemicu") else ""
                L += [f"`{t['dari']} \u2192 {t['ke']}`{note}", ""]
                trace.append(f"- Status {s['object']} {t['dari']} ke {t['ke']}: {_quote(t['kutipan'])} (baris {t['baris']})")

    if doc.get("decision"):
        d = doc["decision"]
        sec("Decision Table Targets")
        L += [f"### {d['title']}", "", "Conditions:"]
        for c in d["conditions"]:
            L.append(f"- {c['name']} = " + " / ".join(_val(v) for v in c["values"]))
        L += ["", "Expected behavior must follow the role access rules written in the Functional Requirements.", ""]

    sec("Edge-Case Areas")
    L += ["Area edge case yang relevan untuk PRD ini:", ""] + [f"- {e}" for e in edge_cases(doc)] + [""]

    sec("Expected QA Coverage")
    L += ["Test case yang disusun dari PRD ini diharapkan mencakup:", ""] + [f"- {c}" for c in COVERAGE]
    L += ["", "Jumlah test case ditentukan dari kerumitan requirement, bukan jumlah tetap per kategori.", ""]

    td = doc.get("test_data") or []
    sec("Test Data Guidance")
    L += ["Data uji harus data buatan yang aman dipakai QA, bukan data asli pengguna.", ""]
    if td:
        L.append("Contoh isian yang terlihat di sumber:")
        L += [f"- {d['field']}: `{_cell(d['example'])}`" for d in td[:25]]
        L.append("")
    L += ["Untuk pengujian batas, nilai yang dibuat harus benar-benar memenuhi kondisi batas yang diuji.", ""]

    feats = [(rid, f) for rid, f in fr_ids if any(r.get("jenis") != "rincian" for r in f.get("rules") or [])]
    if feats:
        sec("Acceptance Criteria")
        L += ["Modul ini diterima bila:", ""]
        for n, (rid, f) in enumerate(feats, 1):
            L.append(f"{n}. Semua aturan {f['name']} ({rid}) terpenuhi, termasuk penolakan isian dan kondisi "
                     f"yang tidak diizinkan.")
        L.append("")

    qs = [x for x in (doc.get("questions") or []) if (x.get("pertanyaan") or "").strip()]
    if qs:
        sec("Open Points")
        L += ["Hal yang belum bisa dipastikan dari sumber. Ditulis sebagai pertanyaan untuk PO/tim, "
              "**bukan** sebagai kebutuhan yang diuji:", ""]
        L += [f"- {_txt(x['pertanyaan'])}" for x in qs[:20]]
        L.append("")

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
    det = [(f["name"], r) for f in doc.get("features", []) for r in f["rules"] if r.get("jenis") == "rincian"]
    if det:
        L += ["", "## 5. Rincian isi layar (bukan bagian PRD)", "",
              "Daftar elemen yang terlihat di desain: tombol lain, kolom tabel, menu, tab, status, dan contoh isian. "
              "Tidak dimasukkan ke PRD supaya PRD tetap berisi alur dan aturan. Tambahkan manual bila memang perlu diuji.", ""]
        L += [f"- {name}: {_txt(r['pernyataan'])}" for name, r in det[:400]]
    L += ["", "## 6. Asal setiap aturan (traceability)", ""] + (doc.get("_trace") or ["- Tidak ada."])
    return "\n".join(L).rstrip() + "\n"
