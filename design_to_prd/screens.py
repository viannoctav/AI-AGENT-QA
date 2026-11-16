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
        def _blocks(o):  # yang di bawahnya tampak isian form -> baris ini kemungkinan label, bukan tombol
            t2 = str(o.get("text") or "").strip()
            return not (_ACTION.match(t2) or _LINKISH.search(t2) or "?" in t2 or len(t2.split()) > 8)

        nothing_below = not any(0 < o["y"] - (ln["y"] + ln["h"]) <= 4 * ln["h"] and abs(o["x"] - ln["x"]) <= 80
                                and _blocks(o) for o in lines if o is not ln)
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
        if " " not in t and (len(t) < 4 or re.search(r"[a-z][A-Z]", t) or not re.search(r"[aeiou]", t, re.I)):
            continue  # satu kata yang tidak berbentuk kata (biasanya ikon/logo yang terbaca OCR)
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
_GREETING = re.compile(r"^(welcome|hi\b|hello|halo|hai\b|selamat\b|good (morning|afternoon|evening))|!$", re.I)


def screen_name(s: Dict[str, Any]) -> str:
    if s["kind"] == "notifikasi" and (s["title"] or s["notif"]):
        return f"Notifikasi {q(s['title'] or s['notif'][0])}"
    if s["title"]:
        # judul berupa sapaan/seruan tidak berguna di PRD: pakai nama aksi utamanya bila ada
        if _GREETING.search(s["title"].strip()) and s["fields"]:
            main = [b for b, _ in s["buttons"] if not _SECONDARY.match(b)]
            if main:
                return main[-1]
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
_MAILBOX = {"inbox", "sent", "drafts", "spam", "starred", "trash", "archive", "junk", "snoozed", "kotak masuk", "terkirim"}


def _is_mail_client(g: Dict[str, Any]) -> bool:
    """Layar aplikasi email (mis. mockup Gmail): isi emailnya dipakai, tetapi menu dan tombol aplikasinya diabaikan."""
    items = {guards.norm(m) for m, _ in g["menus"]} | {guards.norm(t) for t, _ in g["tabs"]}
    return len(items & _MAILBOX) >= 3


def _is_form(g: Dict[str, Any]) -> bool:
    return sum(1 for f in g["fields"] if f["kind"] in ("input", "dropdown", "") ) >= 1 and g.get("n_lines", 0) <= BIG_SCREEN


_SECONDARY = re.compile(r"^(cancel|batal|close|tutup|back|kembali|previous|sebelumnya|discard|buang|skip|lewati|"
                        r"later|nanti|no\b|tidak|keluar|logout|sign ?out)", re.I)


_BEHAVIOUR = re.compile(r"\b(will|akan|cannot|can't|tidak bisa|tidak akan|undone|dibatalkan|dihapus|permanen|"
                        r"berlaku|expire[sd]?|kedaluwarsa|otomatis|automatically|reserved|dikirim|sent to)\b", re.I)


def _is_rule_text(t: str) -> bool:
    """Kalimat di layar yang benar-benar berisi aturan/akibat, bukan sekadar keterangan atau basa-basi."""
    return bool(_RULEISH.search(t) or _BEHAVIOUR.search(t))


def _buttons(g: Dict[str, Any]):
    """(tombol utama, tombol batal/kembali) di satu layar."""
    main, alt = [], []
    for b, st in g["buttons"]:
        (alt if _SECONDARY.match(b) else main).append((b, st))
    return main, alt


_LOGOUT = re.compile(r"^(log ?out|sign ?out|keluar)\b", re.I)
_LOGIN_SCREEN = re.compile(r"\b(log ?in|sign ?in|masuk)\b", re.I)


def _stem(w: str) -> str:
    w = re.sub(r"[^a-z0-9]", "", w.lower())
    return re.sub(r"(ed|ing|s)$", "", w) if len(w) > 4 else w


def _overlap(text: str, words: set) -> int:
    return len({_stem(w) for w in guards.norm(text).split()} & words)


def _words(*texts) -> set:
    return {_stem(w) for t in texts for w in guards.norm(t or "").split()} - {"the", "a", "an", "your", "my"}


def _trigger(g: Dict[str, Any], nxt: Optional[Dict[str, Any]]):
    """(teks aksi, dari_tombol, cocok_dengan_layar_berikutnya) yang membawa pengguna ke layar berikutnya."""
    btns = [b for b, _ in g["buttons"]]
    cands = btns + list(g["links"]) + [m for m, _ in g["menus"]]
    if nxt is not None and cands:
        goal = _words(nxt.get("name"), nxt.get("title"))
        if _LOGIN_SCREEN.search(f"{nxt.get('name') or ''} {nxt.get('title') or ''}"):
            out = next((c for c in cands if _LOGOUT.match(c)), "")  # keluar dari aplikasi -> kembali ke halaman masuk
            if out:
                return out, out in btns, True
        best, hit = "", 0
        for c in cands:
            n = _overlap(c, goal)
            if n > hit:
                best, hit = c, n
        if best:
            return best, best in btns, True
    main, _ = _buttons(g)
    return (main[-1][0], True, False) if main else ("", False, False)


def _result(nxt: Optional[Dict[str, Any]]) -> str:
    """Apa yang terjadi sesudahnya, dilihat dari layar berikutnya."""
    if nxt is None:
        return ""
    lbl = _step_label(nxt)
    if lbl.startswith("notifikasi"):
        head = nxt["title"] or (nxt["notif"][0] if nxt["notif"] else "")
        rest = [x for x in nxt["notif"] if x != head][:2]
        if not head:
            return ""
        return f"sistem menampilkan notifikasi {q(head)}" + (f" dengan pesan {qlist(rest, 2)}" if rest else "")
    if lbl == "layar berikutnya":
        return ""
    return f"sistem membuka {lbl}"


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


_NOISE = re.compile(r"%|\brow\(s\)|\bvs\b|\bPage \d|\d+\s+of\s+\d+|^\W*\d", re.I)


def _is_hint(t: str, title: str = "") -> bool:
    """Kalimat petunjuk di layar (dipakai sebagai keterangan), bukan angka tabel atau statistik."""
    return (len(t.split()) >= 5 and not _is_rule_text(t) and not _NOISE.search(t)
            and guards.norm(t) != guards.norm(title or "") and bool(re.match(r"[A-Za-z]", t.strip())))


_intent = guards.intent  # pemetaan tombol -> maksud bisnis (dipakai bersama dengan Catatan ke PRD)
_LOGIN_ACT, _LOGOUT_ACT = guards._LOGIN_ACT, guards._LOGOUT_ACT


def intro_of(what: str, hint: str = "") -> str:
    """Pembuka kalimat kebutuhan: "Pada form "Login" (bertuliskan "...")"."""
    return f"Pada {what}" + (f" yang bertuliskan {q(hint)}" if hint else "")


def card_rules(card: str, screens: List[Dict[str, Any]], nav_seen: set, described: set) -> List[Dict[str, Any]]:
    """Aturan PRD satu halaman/fitur, disusun per alur bisnis (bukan per elemen).
    `described`: layar yang isinya sudah dijelaskan (di alur atau fitur sebelumnya) tidak diulang."""
    R: List[Dict[str, Any]] = []

    # satu fitur (FR) = satu area/halaman; tiap alur jadi sub-judul di dalamnya, supaya kolom Module/Sub Module
    # di test case terisi benar (Module = area, Sub Module = alur)
    cur = {"fitur": card, "alur": ""}

    def add(text, quote, src, jenis="aturan", fitur=None, alur=None):  # jenis "rincian" -> hanya catatan review
        if not any(guards.norm(r["pernyataan"]) == guards.norm(text) for r in R):
            R.append({"jenis": jenis, "fitur": fitur or cur["fitur"], "alur": cur["alur"] if alur is None else alur,
                      "pernyataan": text, "kutipan": quote, "baris": 0, "sumber": f"gambar {src}"})

    for fl in split_flows(screens, card):
        groups = merge(fl["screens"])  # layar yang sama di dalam satu alur (form kosong dan terisi) digabung
        order: List[Dict[str, Any]] = []
        for s in fl["screens"]:
            g = next(x for x in groups if guards.norm(x["name"]) == guards.norm(screen_name(s)))
            if not order or order[-1] is not g:
                order.append(g)
        flow_name = fl["name"]
        cur["fitur"] = card
        cur["alur"] = flow_name if flow_name and guards.norm(flow_name) != guards.norm(card) else ""
        src_flow = fl["image"]
        steps = [_step_label(g) for g in order]
        steps = [x for i, x in enumerate(steps) if i == 0 or x != steps[i - 1]]
        if len(steps) >= 3:  # peta singkat alurnya, supaya urutan layar tetap terbaca di PRD
            add("Alur ini melewati " + " lalu ".join(steps[:14]) + (", dan seterusnya" if len(steps) > 14 else "") + ".",
                flow_name or order[0]["title"], src_flow, "alur")
        prev = None
        seen_steps: List[Dict[str, Any]] = []
        for pos, g in enumerate(order):
            seen_steps.append(g)
            nxt = order[pos + 1] if pos + 1 < len(order) else None
            name, src = g["name"], ", ".join(g["sources"][:3])
            what = _step_label(g)
            ctx = f" pada alur {q(flow_name)}" if flow_name else ""
            if what.startswith("notifikasi"):
                head = g["title"] or (g["notif"][0] if g["notif"] else "")
                rest = [x for x in g["notif"] if x != head]
                if head:
                    after = ""
                    # pemicu: layar sebelumnya bila tombolnya senada dengan isi notifikasi, selain itu form terakhir
                    goal = _words(head, *rest)
                    cand = [p for p in reversed(seen_steps[-5:-1]) if not _step_label(p).startswith(("notifikasi", "menu aksi"))]
                    scored = []
                    for p in cand:  # tombol lebih kuat daripada tautan/menu sebagai pemicu notifikasi
                        acts = [(b, 2) for b, _ in p["buttons"]] + [(m, 1) for m, _ in p["menus"]] + [(l, 1) for l in p["links"]]
                        best = max(((_overlap(a, goal) * w, a) for a, w in acts), default=(0, ""))
                        # judul layar yang senada dengan isi notifikasi ikut menguatkan ("Service hours updated!")
                        scored.append((best[0] + 2 * _overlap(p["title"] or "", goal), best[1], p))
                    hit = max(scored, key=lambda x: x[0], default=(0, "", None))
                    trig, act = (hit[2], hit[1]) if hit[0] else (next((p for p in cand if _is_form(p)), None) or (cand[0] if cand else None), "")
                    if trig is not None:
                        if not act:
                            btn = [b for b, _ in trig["buttons"] if not _SECONDARY.match(b)]
                            act = btn[-1] if btn else ""
                        after = f" setelah pengguna menekan {q(act)} di {_step_label(trig)}" if act else f" setelah {_step_label(trig)}"
                    # bila notifikasi ini sudah disebut sebagai hasil di kalimat alurnya, jangan diulang
                    if not any(f"notifikasi {q(head)}" in r["pernyataan"] for r in R):
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
                add(f"Untuk setiap baris pada daftar, pengguna dapat memilih aksi "
                    f"{qlist([m for m, _ in g['menus']], 10)}{_states_note(g['menus'])}.",
                    g["menus"][0][0] if g["menus"] else "", src)
                prev = g
                continue
            fields = [f for f in g["fields"] if f["name"]]
            form_fields = fields if (not big and (_is_form(g) or not g["menus"])) else []
            main_btn, alt_btn = _buttons(g)
            trig, trig_is_button, trig_matched = _trigger(g, nxt)
            hasil = _result(nxt)
            side = ""
            if trig and not trig_is_button and not trig_matched:  # tautan sampingan: jangan diklaim membawa ke layar berikutnya
                side, trig = trig, ""
            # satu kalimat kebutuhan yang mengalir: apa yang diisi, apa yang ditekan, dan apa hasilnya
            hint = next((t for t in g["texts"] + g["messages"] if _is_hint(t, g["title"])), "")
            langkah = []
            if form_fields:
                pilih = [f for f in form_fields[:14] if f["kind"] in ("dropdown", "radio")]
                atur = [f for f in form_fields[:14] if f["kind"] in ("toggle", "checkbox")]
                isi = [f for f in form_fields[:14] if f not in pilih and f not in atur]
                if isi:
                    langkah.append("mengisi " + qlist([f["name"] for f in isi], 10))
                if pilih:
                    langkah.append("memilih " + qlist([f["name"] for f in pilih], 6))
                if atur:
                    langkah.append("mengatur " + qlist([f["name"] for f in atur], 6))
                mati = [f["name"] for f in form_fields if "nonaktif" in f["states"]]
                if mati:
                    add(f"Di {what}, {qlist(mati, 6)} tampak nonaktif pada desain.", mati[0], src)
            if nxt is not None and nxt["name"] == "Menu aksi":  # aksinya sudah disebut di kalimat menu aksi
                langkah, trig, hasil = [], "", ""
            elif trig:
                langkah.append(f"{'menekan' if trig_is_button else 'membuka'} {q(trig)}")
            maksud = _intent(trig, g["title"]) if (trig_is_button or _LOGIN_ACT.match(trig or "")
                                                   or _LOGOUT_ACT.match(trig or "")) else ""
            data = [l.split(" ", 1)[1] for l in langkah if l.split(" ", 1)[0] in ("mengisi", "memilih", "mengatur")]
            if maksud:
                # aturan bisnis: siapa boleh melakukan apa, datanya apa, akibatnya apa
                kalimat = f"Pengguna dapat {maksud}"
                kalimat += (f" dengan mengisi {'; '.join(data)}" if data else f" dari {what}") + "."
                if hasil:
                    kalimat += f" Bila berhasil, {hasil}."
                add(kalimat, (form_fields[0]["name"] if form_fields else trig) or name, src, "alur")
            elif langkah:
                kalimat = f"{intro_of(what, hint)}, pengguna {', lalu '.join(langkah)}."
                if hasil:
                    kalimat += f" Setelah itu {hasil}."
                add(kalimat, (form_fields[0]["name"] if form_fields else trig) or name, src, "alur")
            elif hasil:
                add(f"Setelah {what}, {hasil}.", name, src, "alur")
            elif hint:
                add(f"Berlaku aturan {q(hint)}." if _is_rule_text(hint) else f"Di {what} tertulis {q(hint)}.",
                    hint, src, "aturan" if _is_rule_text(hint) else "rincian")
            if maksud and hint:  # keterangan layar tetap tercatat, tapi tidak menyetir kalimat aturannya
                add(f"Berlaku aturan {q(hint)}." if _is_rule_text(hint) else f"Di {what} tertulis {q(hint)}.",
                    hint, src, "aturan" if _is_rule_text(hint) else "rincian")
            if side:
                add(f"Di {what} tersedia juga {q(side)} sebagai jalan keluar lain.", side, src)
            mail = _is_mail_client(g)
            lain = [] if mail else [b for b, _ in main_btn if b != trig]
            if lain:
                add(f"Aksi lain di {what}: {qlist(lain, 8)}{_states_note([x for x in main_btn if x[0] != trig])}.",
                    lain[0], src, "rincian")
            if alt_btn:
                if form_fields:
                    add(f"Pengguna dapat membatalkan proses di {what} lewat {qlist([b for b, _ in alt_btn], 4)}, "
                        f"dan perubahan yang belum disimpan tidak diterapkan.", alt_btn[0][0], src)
                else:
                    add(f"Pengguna dapat menutup {what} lewat {qlist([b for b, _ in alt_btn], 4)} tanpa mengubah data.",
                        alt_btn[0][0], src)
            if form_fields:
                hints = [(f["name"], f["placeholder"]) for f in form_fields
                         if f["placeholder"] and guards.norm(f["placeholder"]) != guards.norm(f["name"])]
                if hints:  # contoh isian sudah ada di bagian Test Data Guidance PRD
                    add(f"Contoh isian di {what}: " + "; ".join(f"{q(n)} bertuliskan {q(p)}" for n, p in hints[:10]) + ".",
                        hints[0][1], src, "rincian")
                for f in form_fields:
                    opts = [v for v in f["values"] if v] if f["kind"] == "dropdown" else []
                    if len(opts) >= 2:
                        add(f"Pilihan {q(f['name'])} di {what} yang terlihat di desain: {qlist(opts, 10)}.", opts[0], src, "field")
                    for h in f["help"]:
                        add(f"{f['name']} wajib memenuhi aturan {q(h)}.", h, src)
            for m in [m for m in g["messages"] if len(m.split()) >= 3 and m != hint][:8]:
                aturan = _is_rule_text(m)  # teks biasa (sapaan/penjelasan) hanya jadi catatan, bukan aturan PRD
                add(f"Berlaku aturan {q(m)}." if aturan else f"Di {what} tertulis {q(m)}.",
                    m, src, "aturan" if aturan else "rincian")
            if g["tabs"] and not mail:
                add(f"Di {what} pengguna bisa berpindah tab {qlist([t for t, _ in g['tabs']], 10)}{_states_note(g['tabs'])}.",
                    g["tabs"][0][0], src, "rincian")
            if g["menus"] and not mail:
                items = [m for m, _ in g["menus"]]
                if len(items) <= 6:
                    add(f"Dari {what} pengguna bisa memilih {qlist(items)}{_states_note(g['menus'])}.", items[0], src)
                else:
                    k2 = frozenset(guards.norm(x) for x in items)
                    if not any(len(k2 & o) / len(k2 | o) >= 0.5 for o in nav_seen):
                        nav_seen.add(k2)
                        add(f"Dari menu navigasi pengguna bisa membuka {qlist(items, 20)}.", items[0], src, "rincian",
                            "Navigasi", alur=card)  # alur dipakai sebagai nama area di tabel Navigation Structure
            cols = [] if mail else list(g["columns"])
            if cols:
                add(f"{what[0].upper()}{what[1:]} menampilkan daftar dengan kolom {qlist(cols, 14)}.", cols[0], src, "rincian")
            if g["status"] and not mail:  # status dirangkum di bagian Key State Model PRD
                add(f"Status yang bisa muncul di {what}: {qlist(g['status'], 10)}.", g["status"][0], src, "rincian")
            if not big:  # kalimat keterangan di layar kecil (modal, email, halaman info)
                for t in [t for t in g["texts"] if len(t.split()) >= 5 and t != hint][:6]:
                    add(f"Berlaku aturan {q(t)}." if _is_rule_text(t) else f"Di {what} tertulis {q(t)}.",
                        t, src, "aturan" if _is_rule_text(t) else "rincian")
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
