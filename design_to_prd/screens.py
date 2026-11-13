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


def build_elements(lines: List[Dict[str, Any]], lab: Dict[str, Any]) -> List[Dict[str, Any]]:
    out = []
    for i, ln in enumerate(lines, 1):
        jenis, states = lab["labels"].get(i, ("teks", []))
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
        if i["no"] in used:
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


def rules_for(g: Dict[str, Any], nav_seen: set) -> List[Dict[str, Any]]:
    """Aturan PRD untuk satu layar (gabungan). Kalimat memakai teks persis dari desain dalam tanda kutip."""
    name, src = g["name"], ", ".join(g["sources"])
    R: List[Dict[str, Any]] = []

    def add(text, quote, jenis="aturan", extra=None):
        R.append({"jenis": jenis, "fitur": g["card"], "pernyataan": text, "kutipan": quote, "baris": 0,
                  "sumber": f"gambar {src}", **(extra or {})})

    layar = f"layar {q(name)}" if not name.startswith(("Menu aksi", "Notifikasi", "Layar ")) else name
    if g["notif"]:
        head, rest = g["notif"][0], g["notif"][1:]
        add(f"Notifikasi {q(head)}" + (f" dengan pesan {qlist(rest)}" if rest else "") + " tampil sesuai desain.", head)
    if g["title"] and g["kind"] != "notifikasi":
        t = g["texts"][:10]
        add(f"Pada {layar} tampil judul {q(g['title'])}" + (f" dan teks {qlist(t)}" if t else "") + ".", g["title"])
    elif g["texts"] and not g["notif"]:
        add(f"Pada {layar} tampil teks {qlist(g['texts'])}.", g["texts"][0])
    for f in g["fields"]:
        if f["kind"] in ("toggle", "checkbox", "radio"):
            kind = {"toggle": "toggle", "checkbox": "kotak centang", "radio": "pilihan bulat"}[f["kind"]]
            s = f"Field {q(f['name'])} berupa {kind}" + (f" {q(f['toggle_text'])}" if f["toggle_text"] and f["toggle_text"] != f["name"] else "")
            if "aktif" in f["states"] and "nonaktif" not in f["states"]:
                s += " yang tampil dalam keadaan aktif pada desain"
        elif f["kind"] == "dropdown":
            s = f"Field {q(f['name'])} berupa pilihan (dropdown)"
            if f["placeholder"]:
                s += f" dengan teks awal {q(f['placeholder'])}"
            if f["values"]:
                s += f"; pilihan yang terlihat di desain: {qlist(f['values'])}"
        else:
            s = f"Field {q(f['name'])} tersedia di {layar}"
            if f["placeholder"] and f["placeholder"] != f["name"]:
                s += f" dengan placeholder {q(f['placeholder'])}"
            if f["values"]:
                s += f"; contoh isian di desain: {qlist(f['values'])}"
        if "nonaktif" in f["states"]:
            s += "; pada desain field ini tampak nonaktif (abu-abu)"
        add(s + ".", f["name"], "field")
        for h in f["help"]:
            add(f"Di bawah field {q(f['name'])} tertulis {q(h)}.", h, "field")
    for m in g["messages"]:
        add(f"Pada {layar} tertulis {q(m)}.", m)
    if g["buttons"]:
        add(f"Pada {layar} tersedia tombol {qlist([b for b, _ in g['buttons']])}{_states_note(g['buttons'])}.", g["buttons"][0][0])
    if g["links"]:
        add(f"Pada {layar} tersedia tautan {qlist(g['links'])}.", g["links"][0])
    if g["tabs"]:
        add(f"Pada {layar} tersedia tab {qlist([t for t, _ in g['tabs']])}{_states_note(g['tabs'])}.", g["tabs"][0][0])
    if g["menus"]:
        items = [m for m, _ in g["menus"]]
        if name == "Menu aksi" or len(items) <= 6:
            add(f"{'Menu aksi' if name == 'Menu aksi' else f'Menu pada {layar}'} berisi pilihan {qlist(items)}"
                f"{_states_note(g['menus'])}.", items[0])
        else:
            key = tuple(guards.norm(x) for x in items)
            if key not in nav_seen:  # menu navigasi yang sama di banyak layar cukup sekali
                nav_seen.add(key)
                sel = [m for m, st in g["menus"] if "terpilih" in st]
                R.append({"jenis": "aturan", "fitur": "Navigasi", "pernyataan":
                          f"Menu navigasi berisi {qlist(items, 20)}" + (f"; menu {q(sel[0])} tampil terpilih saat membuka {layar}" if sel else "") + ".",
                          "kutipan": items[0], "baris": 0, "sumber": f"gambar {src}"})
    if g["status"]:
        add(f"Pada {layar} tampil status {qlist(g['status'])}.", g["status"][0])
    cols = [c for c in g["columns"]]
    if cols:
        add(f"Tabel pada {layar} memiliki kolom {qlist(cols, 20)}.", cols[0])
        for c, vals in g["columns"].items():
            distinct = list(dict.fromkeys(vals))
            if 1 <= len(distinct) <= 6 and len(vals) >= 2:
                add(f"Kolom {q(c)} pada tabel {layar} berisi nilai seperti {qlist(distinct)}.", distinct[0])
    return R


def flow_rules(screens: List[Dict[str, Any]], card: str) -> List[Dict[str, Any]]:
    """Urutan layar dalam satu gambar papan alur (kiri ke kanan) sesuai yang digambar desainer."""
    out = []
    by_img: Dict[str, List[Dict[str, Any]]] = {}
    for s in screens:
        if s["of"] > 1:
            by_img.setdefault(s["image"], []).append(s)
    for img, ss in by_img.items():
        names = []
        for s in sorted(ss, key=lambda x: x["order"]):
            n = screen_name(s)
            n = n if n.startswith(("Menu aksi", "Notifikasi", "Layar ")) else f"layar {q(n)}"
            if not names or names[-1] != n:
                names.append(n)
        if len(names) >= 2:
            out.append({"jenis": "alur", "fitur": card, "baris": 0, "kutipan": "", "sumber": f"urutan gambar {img}",
                        "pernyataan": f"Urutan tampilan pada desain: {', kemudian '.join(names)}."})
    return out


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
