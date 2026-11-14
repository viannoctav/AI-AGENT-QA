"""Menyusun isi layar dari teks OCR + jenis dari AI (murni kode): pasangan label-isian, tombol, tabel, notifikasi,
lalu menjadikannya aturan PRD. Setiap aturan hanya memakai teks yang benar-benar terbaca dari gambar."""
import re
from typing import Any, Dict, List, Optional

from free_text_to_prd import guards

INPUTS = ("placeholder", "isian", "dropdown", "toggle", "checkbox", "radio")
_PICK = re.compile(r"^(select|pilih|choose|--|search|cari)\b", re.I)


def q(s: str) -> str:
    return '"' + re.sub(r"\s+", " ", str(s)).strip().replace('"', "'") + '"'


def qlist(xs: List[str], limit: int = 12) -> str:
    xs = list(dict.fromkeys(x for x in xs if x))[:limit]
    return ", ".join(q(x) for x in xs)


_MONTH = r"(jan|feb|mar|apr|mei|may|jun|jul|agu|aug|sep|okt|oct|nov|des|dec)[a-z]*"
_DATEISH = re.compile(rf"^\s*(\d{{1,2}}\s+)?({_MONTH}\s+)?(19|20)\d{{2}}\s*$|^\s*\d{{1,2}}\s+{_MONTH}\s*$|^\s*v?\d+(\.\d+)+\s*$", re.I)
# kata kerja yang lazim menjadi teks tombol (Inggris dan Indonesia)
_ACTION = re.compile(
    r"^(log ?in|log ?out|sign ?in|sign ?up|sign ?out|masuk|keluar|daftar|register|save|simpan|submit|kirim|send|cancel|batal|"
    r"close|tutup|add|tambah|create|buat|new|edit|ubah|update|perbarui|delete|hapus|remove|reset|confirm|konfirmasi|"
    r"apply|terapkan|next|lanjut|selanjutnya|back|kembali|previous|sebelumnya|continue|done|selesai|ok|oke|yes|ya|no|tidak|"
    r"export|ekspor|import|impor|download|unduh|upload|unggah|filter|search|cari|print|cetak|pay|bayar|checkout|book|pesan|"
    r"approve|setujui|reject|tolak|verify|verifikasi|resend|retry|coba|view|lihat|select|pilih|change|ganti|assign|start|mulai|"
    r"finish|complete|refund|void|share|bagikan|copy|salin|generate|publish|archive|restore|enable|disable|activate|deactivate)\b", re.I)
_PLACEHOLDER = re.compile(r"^(e\.?g\.?|mis\.|contoh|enter\b|masukkan|input\b|type\b|ketik|select\b|pilih|choose|search|cari|"
                          r"full name|your )|@example\.|x{2,}[- ]?x{2,}|^dd[/-]mm|^--", re.I)
_RULEISH = re.compile(r"\b(must|should|required|at least|at most|minimum|maximum|max\.?|min\.?|cannot|can't|invalid|"
                      r"harus|wajib|minimal|maksimal|tidak boleh|tidak valid|expire|kedaluwarsa)\b", re.I)
_LINKISH = re.compile(r"\?\s+\w+(\s+\w+){0,2}$")  # "Already have an account? Login"


def is_cover(lines: List[Dict[str, Any]]) -> str:
    """Bingkai sampul di papan alur: hanya judul alur + tanggal/tahun/versi. Mengembalikan judul alurnya."""
    texts = [str(l.get("text") or "").strip() for l in lines if str(l.get("text") or "").strip()]
    if not 1 <= len(texts) <= 3:
        return ""
    named = [t for t in texts if not _DATEISH.match(t)]
    if len(named) == 1 and len(named) < len(texts) and 2 <= len(named[0]) <= 60:
        return named[0]
    return ""


def fill_labels(lines: List[Dict[str, Any]], lab: Dict[str, Any]) -> Dict[int, Any]:
    """AI sering hanya memberi jenis pada sebagian teks. Sisanya dilengkapi kode dari pola yang pasti
    (kata kerja tombol, teks petunjuk isian, kalimat aturan). Jenis dari AI tidak pernah ditimpa."""
    labels = dict(lab.get("labels") or {})
    n = len(lines)
    if not n:
        return labels
    bottom = max(l["y"] + l["h"] for l in lines)
    top = min(l["y"] for l in lines)
    span = max(1, bottom - top)
    label_nos = [i for i, (j, _) in labels.items() if j == "label"]
    for i, ln in enumerate(lines, 1):
        if i in labels:
            continue
        t = str(ln.get("text") or "").strip()
        words = t.split()
        if not t:
            continue
        under_label = any(0 <= ln["y"] - (lines[k - 1]["y"] + lines[k - 1]["h"]) <= max(70, 4 * lines[k - 1]["h"])
                          and abs(ln["x"] - lines[k - 1]["x"]) <= 80 for k in label_nos)
        nothing_below = not any(0 < o["y"] - (ln["y"] + ln["h"]) <= 4 * ln["h"] and abs(o["x"] - ln["x"]) <= 80
                                for o in lines if o is not ln)
        if _PLACEHOLDER.search(t) and len(words) <= 6 and (under_label or n <= 40):
            labels[i] = ("placeholder", [])
        elif _LINKISH.search(t) and len(words) <= 9 and n <= 60:
            labels[i] = ("link", [])
        elif _RULEISH.search(t) and len(words) >= 3 and n <= 60:
            labels[i] = ("pesan", [])
        elif len(words) <= 3 and len(t) <= 28 and _ACTION.match(t) and not t.endswith((".", ":", "?")) and n <= 60 \
                and (ln["y"] - top) / span >= 0.5 and nothing_below:
            labels[i] = ("tombol", [])  # kata kerja pendek di paruh bawah layar
    return labels


def guess_title(lines: List[Dict[str, Any]], labels: Dict[int, Any]) -> int:
    """Nomor baris judul bila AI tidak menentukannya: teks terbesar di bagian atas (bukan logo huruf besar semua)."""
    if not lines:
        return 0
    top = min(l["y"] for l in lines)
    span = max(1, max(l["y"] + l["h"] for l in lines) - top)
    cands = []
    for i, ln in enumerate(lines, 1):
        t = str(ln.get("text") or "").strip()
        if labels.get(i, ("teks",))[0] not in ("teks", "judul") or not 3 <= len(t) <= 48:
            continue
        if (ln["y"] - top) / span > 0.4 and i > 3:
            continue
        if not re.search(r"[A-Za-z]{3}", t) or (t.isupper() and len(t.split()) <= 2) or t.endswith((".", ",")):
            continue
        if sum(c.isdigit() for c in t) > 0.25 * len(t) or re.match(r"^(rp|idr|usd|\$)\s?\d", t, re.I) or _DATEISH.match(t):
            continue  # tanggal/nominal bukan judul layar
        cands.append((ln["y"], ln["h"], i))
    if not cands:
        return 0
    cands.sort()
    first = cands[0]
    bigger = [c for c in cands[1:4] if c[1] >= 1.25 * first[1]]  # judul jelas lebih besar dari teks pertama
    return (max(bigger, key=lambda c: c[1]) if bigger else first)[2]


def guess_kind(lines: List[Dict[str, Any]], labels: Dict[int, Any]) -> str:
    """Jenis layar bila AI tidak menentukannya: toast 1-3 baris, atau menu aksi berisi pilihan pendek."""
    texts = [str(l.get("text") or "").strip() for l in lines]
    if not 1 <= len(texts) <= 4 or any(labels.get(i, ("teks",))[0] in ("label", "placeholder", "isian") for i in range(1, len(texts) + 1)):
        return ""
    if len(texts) >= 2 and all(len(t.split()) <= 3 and not t.endswith((".", "!", "?")) for t in texts) \
            and sum(1 for t in texts if _ACTION.match(t)) >= len(texts) - 1:
        return "menu"
    if len(texts) <= 3 and (texts[0].endswith("!") or (len(texts) >= 2 and texts[-1].endswith(".") and len(texts[0].split()) <= 6)):
        return "notifikasi"
    return ""


def build_elements(lines: List[Dict[str, Any]], lab: Dict[str, Any]) -> List[Dict[str, Any]]:
    labels = fill_labels(lines, lab)
    if not lab.get("kind"):
        lab["kind"] = guess_kind(lines, labels)
    if lab.get("kind") == "menu":
        labels = {i: (("menu", []) if labels.get(i, ("teks",))[0] in ("teks", "tombol") else labels[i]) for i in range(1, len(lines) + 1)}
    if not lab.get("title_no") and lab.get("kind") not in ("menu", "notifikasi"):
        lab["title_no"] = guess_title(lines, labels)
    out = []
    for i, ln in enumerate(lines, 1):
        jenis, states = labels.get(i, ("teks", []))
        out.append({**ln, "no": i, "jenis": jenis, "states": tuple(states)})
    return [e for e in out if e["jenis"] not in ("ikon", "abaikan")]


def _below(a, b, max_gap):
    """b berada tepat di bawah a (sejajar kiri/bertumpuk horizontal)."""
    gap = b["y"] - (a["y"] + a["h"])
    xov = min(a["x"] + a["w"], b["x"] + b["w"]) - max(a["x"], b["x"])
    return -4 <= gap <= max_gap and (xov > -8 or abs(a["x"] - b["x"]) <= 60)


def summarize(sc: Dict[str, Any], elems: List[Dict[str, Any]], lab: Dict[str, Any], card: str) -> Dict[str, Any]:
    by_no = {e["no"]: e for e in elems}
    title = by_no.get(lab.get("title_no") or 0, {}).get("text") or \
        next((e["text"] for e in elems if e["jenis"] == "judul"), "")
    kind = lab.get("kind") or ""
    labels = [e for e in elems if e["jenis"] == "label"]
    inputs = [e for e in elems if e["jenis"] in INPUTS]
    used = set()
    fields = []
    # label -> isian terdekat di bawahnya
    pairs = sorted(((i["y"] - (l["y"] + l["h"]), l["no"], i["no"]) for l in labels for i in inputs
                    if _below(l, i, max(60, 3 * l["h"]))))
    lab_of = {}
    for _, ln, iv in pairs:
        if ln in lab_of or iv in used:
            continue
        lab_of[ln] = iv
        used.add(iv)
    for l in labels:
        f = {"name": l["text"], "anchor": [l], "kind": "", "placeholder": "", "values": [], "states": list(l["states"]),
             "help": [], "toggle_text": ""}
        if l["no"] in lab_of:
            _fill(f, by_no[lab_of[l["no"]]])
        fields.append(f)
    for i in inputs:
        if i["no"] in used or i["jenis"] == "isian":  # nilai tanpa label (mis. data profil) bukan isian form
            continue
        f = {"name": i["text"], "anchor": [], "kind": "", "placeholder": "", "values": [], "states": [], "help": [],
             "toggle_text": ""}
        _fill(f, i)
        if f["kind"] in ("toggle", "checkbox", "radio"):
            f["name"] = i["text"]
        fields.append(f)
    # teks bantuan/validasi -> field di atasnya
    loose_msgs = []
    for m in (e for e in elems if e["jenis"] == "pesan"):
        best = None
        for f in fields:
            for a in f["anchor"]:
                if _below(a, m, 80) and (best is None or a["y"] > best[1]):
                    best = (f, a["y"])
        if best:
            best[0]["help"].append(m["text"])
        else:
            loose_msgs.append(m["text"])
    # tabel: isi sel -> kolom dengan pusat x terdekat
    heads = [e for e in elems if e["jenis"] == "kolom_tabel"]
    columns = {h["text"]: [] for h in heads}
    if heads:
        hy = min(h["y"] for h in heads)
        for e in elems:
            if e["jenis"] in ("isi_tabel", "status") and e["y"] > hy:
                cx = e["x"] + e["w"] / 2
                h = min(heads, key=lambda h: abs(h["x"] + h["w"] / 2 - cx) if abs(h["x"] - e["x"]) < 260 else 1e9)
                if abs(h["x"] - e["x"]) < 260:
                    columns[h["text"]].append(e["text"])
    in_table = {e["no"] for e in elems if heads and e["jenis"] in ("isi_tabel", "status") and e["y"] > min(h["y"] for h in heads)}
    pick = lambda j: [e for e in elems if e["jenis"] == j]
    texts = [e["text"] for e in elems if e["jenis"] in ("judul", "teks") and e["text"] != title]
    notif = pick("notifikasi")
    if kind == "notifikasi" and not notif:
        notif = [e for e in elems if e["jenis"] in ("judul", "teks", "pesan")]
    return {
        "id": sc["id"], "image": sc["image"], "order": sc["order"], "of": sc["of"], "card": card,
        "title": title, "kind": kind, "fields": fields,
        "buttons": [(e["text"], e["states"]) for e in pick("tombol")],
        "links": [e["text"] for e in pick("link")], "tabs": [(e["text"], e["states"]) for e in pick("tab")],
        "menus": [(e["text"], e["states"]) for e in pick("menu")],
        "status": [e["text"] for e in pick("status") if e["no"] not in in_table],
        "columns": columns, "messages": loose_msgs, "notif": [e["text"] for e in notif],
        "texts": texts if kind != "notifikasi" else [],
        "elements": [{"teks": e["text"], "jenis": e["jenis"], "keadaan": list(e["states"])} for e in elems],
        "cover": "", "n_lines": len(elems),
    }


def _fill(f, i):
    j = i["jenis"]
    f["anchor"].append(i)
    f["states"] = list(dict.fromkeys(f["states"] + list(i["states"])))
    if j == "placeholder":
        f["kind"], f["placeholder"] = "input", i["text"]
    elif j == "isian":
        f["kind"] = "input"
        f["values"].append(i["text"])
    elif j == "dropdown":
        f["kind"] = "dropdown"
        if _PICK.match(i["text"]):
            f["placeholder"] = i["text"]
        else:
            f["values"].append(i["text"])
    else:
        f["kind"], f["toggle_text"] = j, i["text"]


# ---------------------------------------------------------------------------
# gabung layar yang sama (mis. form kosong dan form terisi) lalu jadi aturan
# ---------------------------------------------------------------------------
def screen_name(s: Dict[str, Any]) -> str:
    if s["kind"] == "notifikasi" and (s["title"] or s["notif"]):
        return f"Notifikasi {q(s['title'] or s['notif'][0])}"
    if s["title"]:
        return s["title"]
    if s["kind"] == "menu" or (s["menus"] and not s["fields"] and not s["buttons"] and len(s["menus"]) <= 8):
        return "Menu aksi"
    if s["notif"]:
        return f"Notifikasi {q(s['notif'][0])}"
    return f"Layar {s['id']}"


def merge(screens: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    groups: Dict[str, Dict[str, Any]] = {}
    for s in screens:
        key = guards.norm(screen_name(s))
        g = groups.get(key)
        if not g:
            groups[key] = g = {**s, "name": screen_name(s), "fields": [], "sources": [], "buttons": [], "menus": [],
                               "tabs": [], "links": [], "status": [], "messages": [], "notif": [], "texts": [],
                               "columns": {}}
        g["sources"].append(f"{s['image']} layar {s['order']}" if s["of"] > 1 else s["image"])
        for f in s["fields"]:
            m = next((x for x in g["fields"] if guards.norm(x["name"]) == guards.norm(f["name"])), None)
            if not m:
                g["fields"].append({k: (list(v) if isinstance(v, list) else v) for k, v in f.items() if k != "anchor"})
                continue
            m["kind"] = m["kind"] or f["kind"]
            m["placeholder"] = m["placeholder"] or f["placeholder"]
            m["toggle_text"] = m["toggle_text"] or f["toggle_text"]
            for k in ("values", "states", "help"):
                m[k] = list(dict.fromkeys(m[k] + f[k]))
        for k in ("buttons", "menus", "tabs", "links", "status", "messages", "notif", "texts"):
            g[k] = list(dict.fromkeys(g[k] + s[k]))
        for c, vals in s["columns"].items():
            g["columns"][c] = g["columns"].get(c, []) + vals
    return list(groups.values())


def _states_note(items):
    notes = []
    for text, st in items:
        if "nonaktif" in st:
            notes.append(f"{q(text)} tampak nonaktif")
        elif "merah" in st:
            notes.append(f"{q(text)} tampil merah")
        elif "terpilih" in st:
            notes.append(f"{q(text)} tampil terpilih")
    return f" ({'; '.join(notes)})" if notes else ""


# ---------------------------------------------------------------------------
# alur bisnis: bingkai sampul di papan alur = nama alur; layar sesudahnya = langkah alur itu
# ---------------------------------------------------------------------------
BIG_SCREEN = 40  # layar dengan teks sebanyak ini biasanya halaman daftar/dasbor: teks lepasnya tidak dijadikan aturan


def _is_form(g: Dict[str, Any]) -> bool:
    return sum(1 for f in g["fields"] if f["kind"] in ("input", "dropdown", "") ) >= 1 and g.get("n_lines", 0) <= BIG_SCREEN


def _step_label(g: Dict[str, Any]) -> str:
    name = g.get("name") or screen_name(g)
    if g["kind"] == "notifikasi" or name.startswith("Notifikasi"):
        head = g["title"] or (g["notif"][0] if g["notif"] else "")
        rest = [x for x in g["notif"] if x != head][:1]
        return f"notifikasi {q(head)}" + (f" ({q(rest[0])})" if rest else "") if head else "notifikasi"
    if name == "Menu aksi":
        return f"menu aksi ({qlist([m for m, _ in g['menus']], 6)})"
    if name.startswith("Layar "):
        return "layar berikutnya"
    return f"{'form' if _is_form(g) else 'layar'} {q(name)}"


def split_flows(screens: List[Dict[str, Any]], card: str) -> List[Dict[str, Any]]:
    """[{name, screens}] sesuai urutan gambar. Tanpa bingkai sampul, satu gambar papan alur = satu alur."""
    flows: List[Dict[str, Any]] = []
    cur = None
    last_img = None
    for s in screens:
        if s.get("cover"):
            cur = {"name": s["cover"], "screens": [], "named": True, "image": s["image"]}
            flows.append(cur)
            last_img = s["image"]
            continue
        if cur is None or (s["image"] != last_img and not cur["named"]):
            cur = {"name": "", "screens": [], "named": False, "image": s["image"]}
            flows.append(cur)
        last_img = s["image"]
        cur["screens"].append(s)
    return [f for f in flows if f["screens"]]


def card_rules(card: str, screens: List[Dict[str, Any]], nav_seen: set, described: set) -> List[Dict[str, Any]]:
    """Aturan PRD satu halaman/fitur, disusun per alur bisnis (bukan per elemen).
    `described`: layar yang isinya sudah dijelaskan (di alur atau fitur sebelumnya) tidak diulang."""
    R: List[Dict[str, Any]] = []

    def add(text, quote, src, jenis="aturan", fitur=None):
        if not any(guards.norm(r["pernyataan"]) == guards.norm(text) for r in R):
            R.append({"jenis": jenis, "fitur": fitur or card, "pernyataan": text, "kutipan": quote, "baris": 0,
                      "sumber": f"gambar {src}"})

    for fl in split_flows(screens, card):
        groups = merge(fl["screens"])  # layar yang sama di dalam satu alur (form kosong dan terisi) digabung
        order: List[Dict[str, Any]] = []
        for s in fl["screens"]:
            g = next(x for x in groups if guards.norm(x["name"]) == guards.norm(screen_name(s)))
            if not order or order[-1] is not g:
                order.append(g)
        flow_name = fl["name"]
        pre = f"Alur {q(flow_name)}: " if flow_name else "Alur: "
        src_flow = fl["image"]
        steps = [_step_label(g) for g in order]
        steps = [x for i, x in enumerate(steps) if i == 0 or x != steps[i - 1]]
        if len(steps) >= 2:
            add(pre + ", lalu ".join(steps[:14]) + (", dan seterusnya" if len(steps) > 14 else "") + ".",
                flow_name or order[0]["title"], src_flow, "alur")
        elif flow_name:
            add(f"{pre}{steps[0]}.", flow_name, src_flow, "alur")
        prev = None
        seen_steps: List[Dict[str, Any]] = []
        for g in order:
            seen_steps.append(g)
            name, src = g["name"], ", ".join(g["sources"][:3])
            what = _step_label(g)
            ctx = f" pada alur {q(flow_name)}" if flow_name else ""
            if what.startswith("notifikasi"):
                head = g["title"] or (g["notif"][0] if g["notif"] else "")
                rest = [x for x in g["notif"] if x != head]
                if head:
                    after = ""
                    # pemicu: layar sebelumnya bila tombolnya senada dengan isi notifikasi, selain itu form terakhir
                    stem = lambda w: re.sub(r"(ed|d|e|s)$", "", w.lower().strip("!?.,")) if len(w) > 3 else w.lower()
                    verb = stem(head.split()[-1]) if head.split() else ""
                    cand = [p for p in reversed(seen_steps[-5:-1]) if not _step_label(p).startswith(("notifikasi", "menu aksi"))]
                    trig = next((p for p in cand if verb and any(stem(b.split()[0]) == verb for b, _ in p["buttons"] if b.split())), None) \
                        or next((p for p in cand if _is_form(p)), None) or (cand[0] if cand else None)
                    if trig is not None:
                        btn = [b for b, _ in trig["buttons"]]
                        after = f" setelah aksi di {_step_label(trig)}" + (f" (tombol {qlist(btn[-2:])})" if btn else "")
                    add(f"Sistem menampilkan notifikasi {q(head)}" + (f" dengan pesan {qlist(rest, 3)}" if rest else "")
                        + f"{after}{ctx}.", head, src)
                prev = g
                continue
            big = g.get("n_lines", 0) > BIG_SCREEN
            key = (guards.norm(name),) if big else (guards.norm(name), tuple(sorted(guards.norm(f["name"]) for f in g["fields"])))
            if key in described or name.startswith("Layar ") and not (g["fields"] or g["buttons"]):
                prev = g
                continue
            described.add(key)
            if name == "Menu aksi":
                add(f"Menu aksi{ctx} berisi pilihan {qlist([m for m, _ in g['menus']], 10)}{_states_note(g['menus'])}.",
                    g["menus"][0][0] if g["menus"] else "", src)
                prev = g
                continue
            fields = [f for f in g["fields"] if f["name"]]
            if fields and not big and (_is_form(g) or not g["menus"]):
                parts = []
                for f in fields[:24]:
                    note = {"dropdown": "pilihan", "toggle": "saklar", "checkbox": "kotak centang", "radio": "pilihan bulat"}.get(f["kind"], "")
                    if "nonaktif" in f["states"]:
                        note = (note + ", " if note else "") + "tampak nonaktif"
                    parts.append(q(f["name"]) + (f" ({note})" if note else ""))
                add(f"{what[0].upper()}{what[1:]} berisi isian {', '.join(parts)}.", fields[0]["name"], src, "field")
                hints = [(f["name"], f["placeholder"]) for f in fields if f["placeholder"] and guards.norm(f["placeholder"]) != guards.norm(f["name"])]
                if hints:
                    add(f"Teks petunjuk isian di {what}: " + "; ".join(f"{q(n)} bertuliskan {q(p)}" for n, p in hints[:10]) + ".",
                        hints[0][1], src, "field")
                for f in fields:
                    opts = [v for v in f["values"] if v] if f["kind"] == "dropdown" else []
                    if len(opts) >= 2:
                        add(f"Pilihan {q(f['name'])} di {what} yang terlihat di desain: {qlist(opts, 10)}.", opts[0], src, "field")
                    for h in f["help"]:
                        add(f"Aturan isian {q(f['name'])} di {what}: {q(h)}.", h, src)
            for m in [m for m in g["messages"] if len(m.split()) >= 3][:8]:
                add(f"Di {what} tertulis aturan {q(m)}.", m, src)
            acts = []
            if g["buttons"]:
                acts.append(f"tombol {qlist([b for b, _ in g['buttons']], 10)}{_states_note(g['buttons'])}")
            if g["links"] and not big:
                acts.append(f"tautan {qlist(g['links'], 6)}")
            if g["tabs"]:
                acts.append(f"tab {qlist([t for t, _ in g['tabs']], 10)}{_states_note(g['tabs'])}")
            if acts:
                add(f"Aksi yang tersedia di {what}: {'; '.join(acts)}.", (g["buttons"] or [(g["links"] or g["tabs"] or [("",)])[0]])[0][0]
                    if g["buttons"] else (g["links"][0] if g["links"] else g["tabs"][0][0]), src)
            if g["menus"]:
                items = [m for m, _ in g["menus"]]
                if len(items) <= 6:
                    add(f"Menu di {what} berisi pilihan {qlist(items)}{_states_note(g['menus'])}.", items[0], src)
                else:
                    k2 = frozenset(guards.norm(x) for x in items)
                    if not any(len(k2 & o) / len(k2 | o) >= 0.5 for o in nav_seen):  # menu navigasi yang sama cukup sekali
                        nav_seen.add(k2)
                        add(f"Menu navigasi berisi {qlist(items, 20)}.", items[0], src, fitur="Navigasi")
            cols = list(g["columns"])
            if cols:
                add(f"Daftar di {what} menampilkan kolom {qlist(cols, 14)}.", cols[0], src)
            if g["status"]:
                add(f"Status yang ditampilkan di {what}: {qlist(g['status'], 10)}.", g["status"][0], src)
            if not big:  # kalimat keterangan di layar kecil (modal, email, halaman info) biasanya berisi aturan
                said = [t for t in g["texts"] if len(t.split()) >= 5][:6]
                for t in said:
                    add(f"Di {what} tertulis {q(t)}.", t, src)
            prev = g
    return R


def design_questions(screens: List[Dict[str, Any]], labels_failed: List[str], empty: List[str]) -> List[Dict[str, str]]:
    out, seen = [], set()
    for s in screens:
        for f in s["fields"]:
            if "nonaktif" in f["states"] and (s["card"], f["name"]) not in seen:
                seen.add((s["card"], f["name"]))
                out.append({"fitur": s["card"], "jenis": "konfirmasi desain", "kutipan": "",
                            "pertanyaan": f"Field {q(f['name'])} tampak abu-abu (nonaktif) di desain {s['image']}. "
                                          f"Kapan field ini aktif, dan apakah memang sengaja nonaktif?"})
        for b, st in s["buttons"]:
            if "nonaktif" in st and (s["card"], b) not in seen:
                seen.add((s["card"], b))
                out.append({"fitur": s["card"], "jenis": "konfirmasi desain", "kutipan": "",
                            "pertanyaan": f"Tombol {q(b)} tampak nonaktif di desain {s['image']}. Kapan tombol ini bisa diklik?"})
    for x in labels_failed:
        out.append({"fitur": "", "jenis": "konfirmasi desain", "kutipan": "",
                    "pertanyaan": f"AI tidak berhasil mengenali jenis elemen di {x}; teksnya tetap dicatat sebagai teks biasa. Periksa bagian ini di PRD."})
    for x in empty:
        out.append({"fitur": "", "jenis": "konfirmasi desain", "kutipan": "",
                    "pertanyaan": f"Tidak ada teks yang terbaca di {x}. Bila layar ini penting, jelaskan isinya di kolom penjelasan."})
    return out
