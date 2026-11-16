"""Alur: gambar -> (kode) potong papan alur & latar buram -> (OCR Windows) baca teks -> (AI) beri jenis tiap teks
-> (kode) susun isi layar jadi aturan; penjelasan QA -> (AI + penjaga kutipan) aturan -> (kode) PRD + catatan review."""
import json
import re
import shutil
import time
from datetime import datetime
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional

from free_text_to_prd import guards
from free_text_to_prd import pipeline as ft
from design_to_prd import images as imgs
from design_to_prd import labels as lb
from design_to_prd import screens as scr
from design_to_prd.render import render_markdown, render_review

ROOT = Path(__file__).resolve().parent.parent
OUT_BASE = ROOT / "outputs" / "design_to_prd"
PRD_DIR = ROOT / "knowledge" / "prd"


def _say(cb, msg):
    (cb or print)(msg)


def reserve(name: str, prd_dir: Optional[Path] = None, out_base: Optional[Path] = None):
    """Nama file PRD + folder hasil (tidak pernah menimpa PRD/konversi lama)."""
    prd_dir, base = prd_dir or PRD_DIR, out_base or OUT_BASE
    slug = ft.slugify(name) + "_dari_desain"
    md = prd_dir / f"{slug}.md"
    n = 2
    while md.exists() or (base / md.stem).exists():
        md = prd_dir / f"{slug}_v{n}.md"
        n += 1
    out = base / md.stem
    out.mkdir(parents=True)
    return md, out


def read_notes(text: str, feature: Optional[str], llm, cb=None, label: str = "") -> Dict[str, Any]:
    """Penjelasan QA -> item aturan dengan penjaga kutipan yang sama seperti Catatan Konversi ke PRD."""
    lines = ft.split_lines(text)
    content = [i for i, l in enumerate(lines) if ft.is_content(l)]
    acc, rej, peran, produk = [], [], [], ""
    if not content:
        return {"lines": lines, "accepted": acc, "rejected": rej, "missed": [], "peran": peran, "produk": produk}

    def take(data):
        nonlocal produk
        produk = produk or str(data.get("produk") or "").strip()
        for r in data.get("peran") or []:
            r = str(r).strip()
            if r and r not in peran:
                peran.append(r)
        for it in data.get("items") or []:
            if not isinstance(it, dict):
                continue
            it = ft._clean_item(it)
            ok, why, ln = guards.check_item(it, lines)
            it["baris"] = ln
            it["sumber"] = f"penjelasan {label}, baris {ln}" if ln else f"penjelasan {label}"
            if feature:  # penjelasan di kartu halaman: semua aturannya milik halaman itu
                it["fitur"] = feature
            if ok:
                if not any(guards.norm(a["pernyataan"]) == guards.norm(it["pernyataan"]) for a in acc):
                    acc.append(it)
            else:
                rej.append({**it, "alasan": why})

    chunks = ft._chunks(lines)
    for n, idx in enumerate(chunks, 1):
        _say(cb, f"Membaca penjelasan {label}" + (f" bagian {n}/{len(chunks)}" if len(chunks) > 1 else "") + " ...")
        take(ft.extract(lines, idx, llm, cb))
    covered = {a["baris"] for a in acc}
    missed = [i for i in content if i + 1 not in covered and not ft._named_only(lines[i], peran)]
    if missed:
        _say(cb, f"{len(missed)} baris penjelasan {label} belum terbaca, dibaca ulang ...")
        ctx = sorted(set(missed) | {j for i in missed for j in ft._parents(lines, i)})
        take(ft.extract(lines, ctx, llm, cb))
        covered = {a["baris"] for a in acc}
        missed = [i for i in content if i + 1 not in covered and not ft._named_only(lines[i], peran)]
    full = guards.norm(" ".join(lines))
    peran = [r for r in peran if guards._present(r, full)]
    return {"lines": lines, "accepted": acc, "rejected": rej, "peran": peran, "produk": produk,
            "missed": [{"sumber": label, "baris": i + 1, "teks": lines[i].strip()} for i in missed]}


# --------------------------------------------------------------------------- titik simpan per fitur
# Bagian berat (OCR + AI) dikerjakan satu fitur demi satu fitur dan disimpan setiap fitur selesai.
# Kalau proses mati/ditutup di tengah, fitur yang sudah jadi tidak perlu diulang; PRD-nya tetap satu,
# digabung di akhir dari semua fitur.

def _ck_dir(out_dir: Path) -> Path:
    return out_dir / "kerja" / "checkpoint"


def _ck_write(out_dir: Path, nama: str, data: Dict[str, Any]) -> None:
    d = _ck_dir(out_dir)
    d.mkdir(parents=True, exist_ok=True)
    tmp = d / (nama + ".tmp")
    tmp.write_text(json.dumps(data, ensure_ascii=False, default=str), encoding="utf-8")
    tmp.replace(d / nama)  # ditulis ke file sementara dulu: kalau mati di tengah, simpanan lama tidak rusak


def _ck_read(out_dir: Path, nama: str) -> Optional[Dict[str, Any]]:
    f = _ck_dir(out_dir) / nama
    if not f.is_file():
        return None
    try:
        return json.loads(f.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None


def _card_sig(c: Dict[str, Any]) -> str:
    """Sidik isi kartu: kalau nama/penjelasan/gambarnya berubah, simpanan lama tidak dipakai lagi."""
    import hashlib
    s = json.dumps([c.get("nama") or "", c.get("teks") or "",
                    [Path(i["name"]).name for i in c.get("images") or []]], ensure_ascii=False)
    return hashlib.sha1(s.encode("utf-8")).hexdigest()[:16]


def _state_write(out_dir: Path, name: str, extra: str, cards: List[Dict[str, Any]], prd_file: str, status: str) -> None:
    _ck_write(out_dir, "state.json", {
        "versi": 1, "nama": name, "extra": extra, "prd_file": prd_file, "status": status, "waktu": time.time(),
        "kartu": [{"nama": c["nama"], "teks": c.get("teks") or "",
                   "gambar": [{"path": str(i["path"]), "name": i["name"]} for i in c.get("images") or []]}
                  for c in cards]})


def _state_status(out_dir: Path, status: str) -> None:
    st = _ck_read(out_dir, "state.json")
    if st:
        _ck_write(out_dir, "state.json", {**st, "status": status, "waktu": time.time()})


def _stage_sources(cards: List[Dict[str, Any]], out_dir: Path) -> List[Dict[str, Any]]:
    """Gambar unggahan disalin ke folder hasil sebelum diproses, supaya proses bisa dilanjut
    walau gambar di folder unggahan sudah dibersihkan."""
    dst_dir = out_dir / "source" / "gambar"
    dst_dir.mkdir(parents=True, exist_ok=True)
    out = []
    for c in cards:
        images = []
        for im in c.get("images") or []:
            dst = dst_dir / Path(im["name"]).name
            if not dst.exists() and Path(im["path"]).is_file():
                shutil.copy2(im["path"], dst)
            images.append({"path": str(dst), "name": im["name"]})
        out.append({**c, "images": images})
    return out


def interrupted(out_base: Optional[Path] = None) -> List[Dict[str, Any]]:
    """Daftar penyusunan PRD desain yang terhenti dan masih bisa dilanjut."""
    base = out_base or OUT_BASE
    out = []
    for d in sorted(base.glob("*"), key=lambda p: p.name):
        st = _ck_read(d, "state.json") if d.is_dir() else None
        if not st or st.get("status") not in ("berjalan", "terhenti") or st.get("versi") != 1:
            continue
        total = len(st.get("kartu") or [])
        done = sum(1 for i in range(1, total + 1) if (_ck_dir(d) / f"fitur_{i:02d}.json").is_file())
        out.append({"id": d.name, "nama": st.get("nama") or d.name, "fitur_selesai": done, "fitur_total": total,
                    "waktu": st.get("waktu") or 0,
                    "fitur_berikut": (st["kartu"][done]["nama"] if done < total else "")})
    return sorted(out, key=lambda x: -x["waktu"])


def discard(run_id: str, out_base: Optional[Path] = None) -> bool:
    """Buang proses terhenti beserta hasil setengah jadinya."""
    d = (out_base or OUT_BASE) / Path(run_id).name
    if not (_ck_dir(d) / "state.json").is_file():
        return False
    shutil.rmtree(d, ignore_errors=True)
    return True


def run(cards: List[Dict[str, Any]], extra: str = "", name: str = "", llm=None, ocr_fn=None, cb=None,
        write: bool = True, prd_dir: Optional[Path] = None, out_base: Optional[Path] = None,
        progress: Optional[Dict[str, Any]] = None, resume: Optional[str] = None) -> Dict[str, Any]:
    """cards: [{"nama", "teks", "images": [{"path", "name"}]}] urut sesuai halaman di dashboard.
    resume: id folder hasil yang terhenti -> kartu, nama, dan penjelasan dibaca dari simpanannya."""
    if llm is None:
        from tools import llm as _llm
        llm = _llm
    if ocr_fn is None:
        from design_to_prd.ocr import read_text as ocr_fn
    from design_to_prd.ocr import clean_lines
    t0 = time.time()
    if resume:
        if not write:
            raise ValueError("Proses yang terhenti hanya bisa dilanjut saat hasilnya disimpan.")
        out_dir = (out_base or OUT_BASE) / Path(resume).name
        st = _ck_read(out_dir, "state.json")
        if not st or st.get("versi") != 1:
            raise ValueError("Proses yang terhenti tidak ditemukan lagi. Susun ulang dari awal.")
        name, extra = st["nama"], st.get("extra") or ""
        cards = [{"nama": k["nama"], "teks": k.get("teks") or "",
                  "images": [i for i in (k.get("gambar") or []) if Path(i["path"]).is_file()]}
                 for k in st.get("kartu") or []]
        hilang = sum(len(k.get("gambar") or []) for k in st.get("kartu") or []) - sum(len(c["images"]) for c in cards)
        if hilang:
            raise ValueError(f"{hilang} gambar asli sudah tidak ada di folder hasil, jadi proses ini tidak bisa "
                             f"dilanjut. Buang proses terhenti ini lalu susun ulang dari awal.")
        md_path = (prd_dir or PRD_DIR) / st["prd_file"]
    name = re.sub(r"\s+", " ", str(name or "")).strip() or "Desain"
    cards = [c for c in cards if (c.get("teks") or "").strip() or c.get("images")]
    if not cards and not (extra or "").strip():
        raise ValueError("Isi minimal satu halaman/fitur dengan gambar atau penjelasan.")
    for i, c in enumerate(cards, 1):
        c["nama"] = re.sub(r"\s+", " ", str(c.get("nama") or "")).strip() or f"Halaman {i}"

    if write and not resume:
        md_path, out_dir = reserve(name, prd_dir, out_base)
        cards = _stage_sources(cards, out_dir)
        _state_write(out_dir, name, extra, cards, md_path.name, "berjalan")
    elif not write:
        import tempfile
        out_dir, md_path = Path(tempfile.mkdtemp()), Path("preview_dari_desain.md")
    try:
        P = progress if progress is not None else {}
        P.update({"phase": "siapkan", "screens_total": 0, "screens_done": 0, "screen_secs": [],
                  "texts_total": sum(1 for c in cards if (c.get("teks") or "").strip()) + (1 if (extra or "").strip() else 0),
                  "texts_done": 0, "cards_total": len(cards), "cards_done": 0, "card_name": ""})
        result = _run(cards, extra, name, llm, ocr_fn, clean_lines, cb, out_dir, t0, P, write)
        P["phase"] = "selesai"
        if write:
            result.update(_save(result, cards, extra, md_path, out_dir))
        _say(cb, f"Selesai: {result['stats']['screens']} layar dibaca, {len(result['document']['features'])} fitur, "
                 f"{sum(len(f['rules']) for f in result['document']['features'])} aturan, "
                 f"{len(result['document']['questions'])} hal untuk dicek.")
        return result
    except Exception:
        if write and not resume and not any(_ck_dir(out_dir).glob("fitur_*.json")):
            shutil.rmtree(out_dir, ignore_errors=True)  # belum ada fitur yang jadi: tidak ada yang bisa dilanjut
        elif write:
            _state_status(out_dir, "terhenti")
        raise


def _lab_of(s: Dict[str, Any]) -> Dict[str, Any]:
    """Jenis elemen hasil AI yang tersimpan -> bentuk yang dipakai kode."""
    return {"kind": "", "title_no": 0, "ok": bool(s.get("label_ok", True)),
            "labels": {int(k): (v[0], v[1]) for k, v in (s.get("labels") or {}).items()}}


def _phase_a(cards, extra, llm, ocr_fn, clean_lines, cb, out_dir, P, write):
    """OCR + AI per fitur, disimpan setiap fitur selesai. Fitur yang sudah tersimpan tidak dikerjakan lagi."""
    done: Dict[int, Dict[str, Any]] = {}
    seen: Dict[str, str] = {}
    lab_cache: Dict[Any, Dict[str, Any]] = {}
    if write:
        for ci, c in enumerate(cards, 1):
            ck = _ck_read(out_dir, f"fitur_{ci:02d}.json")
            if not ck or ck.get("sidik") != _card_sig(c) or not all(Path(s["path"]).is_file() for s in ck.get("layar") or []):
                continue
            done[ci] = ck
            for s in ck["layar"]:
                if s.get("digest"):
                    seen.setdefault(s["digest"], s["duplicate_of"] or s["id"])
                if not s["duplicate_of"] and s.get("ocr"):
                    lab_cache.setdefault(tuple(l["text"] for l in s["ocr"]), _lab_of(s))
    if done:
        _say(cb, f"Melanjutkan proses: {len(done)} dari {len(cards)} fitur sudah selesai sebelumnya, tidak dibaca ulang.")
        P["cards_done"] = len(done)

    # 1) gambar -> layar (murah, selalu diulang untuk fitur yang belum selesai)
    pending = [(ci, c) for ci, c in enumerate(cards, 1) if ci not in done]
    prepared: Dict[int, List[Dict[str, Any]]] = {}
    n_img = sum(len(c.get("images") or []) for _, c in pending)
    if n_img:
        _say(cb, f"Menyiapkan {n_img} gambar: memotong papan alur menjadi layar dan membuang latar buram ...")
    for ci, c in pending:
        prepared[ci] = []
        for s in imgs.prepare(c.get("images") or [], out_dir / "layar" / f"{ci:02d}", seen):
            s["card"] = c["nama"]
            prepared[ci].append(s)
    todo_all = [s for v in prepared.values() for s in v if not s["duplicate_of"]]
    dup = sum(1 for v in prepared.values() for s in v if s["duplicate_of"])
    P.update(phase="baca_teks", screens_total=len(todo_all))
    if todo_all:
        _say(cb, f"Membaca teks {len(todo_all)} layar dengan pembaca teks Windows" +
             (f" ({dup} layar kembar dilewati)" if dup else "") + " ...")

    # 2) per fitur: OCR -> AI beri jenis -> penjelasan QA -> simpan
    k = 0
    for ci, c in pending:
        P["card_name"] = c["nama"]
        scrs = prepared[ci]
        todo = [s for s in scrs if not s["duplicate_of"]]
        if len(pending) > 1:
            _say(cb, f"Fitur \"{c['nama']}\" ({ci}/{len(cards)}): {len(todo)} layar.")
        P["phase"] = "baca_teks"
        ocr = ocr_fn([s["path"] for s in todo], out_dir / "kerja") if todo else {}
        P["phase"] = "kenali"
        for s in todo:
            ts = time.time()
            lines = clean_lines(ocr.get(s["path"], []), s["size"][1])
            s["ocr"] = lines
            where = f"gambar {s['image']}" + (f" layar {s['order']}" if s["of"] > 1 else "")
            sig = tuple(l["text"] for l in lines)
            k += 1
            if not lines or scr.is_cover(lines):  # kosong atau bingkai sampul alur: tidak perlu AI
                lab = {"kind": "", "title_no": 0, "labels": {}, "ok": True}
            elif sig in lab_cache:  # layar dengan teks yang sama persis: jenisnya dipakai ulang, tidak ditanyakan lagi ke AI
                lab = lab_cache[sig]
            else:
                _say(cb, f"Mengenali elemen layar {k}/{len(todo_all)} ({where}, {len(lines)} teks) ...")
                lab = lb.label_screen(llm, s["path"], lines)
                if lab["ok"]:
                    lab_cache[sig] = lab
                P["screen_secs"].append(round(time.time() - ts, 1))
            s["labels"] = {str(x): v for x, v in lab["labels"].items()}
            s["label_ok"] = bool(lab["ok"])
            P["screens_done"] = k
        notes = None
        if (c.get("teks") or "").strip():
            P["phase"] = "penjelasan"
            notes = read_notes(c["teks"], c["nama"], llm, cb, label=f"\"{c['nama']}\"")
            P["texts_done"] += 1
        if write:
            _ck_write(out_dir, f"fitur_{ci:02d}.json", {"nama": c["nama"], "sidik": _card_sig(c),
                                                        "layar": scrs, "notes": notes})
        done[ci] = {"nama": c["nama"], "layar": scrs, "notes": notes}
        P["cards_done"] = len(done)

    # 3) penjelasan tambahan (bukan milik fitur tertentu)
    extra_ck = _ck_read(out_dir, "tambahan.json") if write else None
    if (extra or "").strip():
        if extra_ck and extra_ck.get("sidik") == _card_sig({"teks": extra}):
            notes_extra = extra_ck["notes"]
        else:
            P["phase"] = "penjelasan"
            notes_extra = read_notes(extra, None, llm, cb, label="tambahan")
            P["texts_done"] += 1
            if write:
                _ck_write(out_dir, "tambahan.json", {"sidik": _card_sig({"teks": extra}), "notes": notes_extra})
    else:
        notes_extra = None

    screens = [s for ci in sorted(done) for s in done[ci]["layar"]]
    notes = [done[ci]["notes"] for ci in sorted(done) if done[ci].get("notes")] + ([notes_extra] if notes_extra else [])
    return {"screens": screens, "notes": notes,
            "n_img": sum(len(c.get("images") or []) for c in cards)}


def _run(cards, extra, name, llm, ocr_fn, clean_lines, cb, out_dir, t0, P, write=True):
    A = _phase_a(cards, extra, llm, ocr_fn, clean_lines, cb, out_dir, P, write)
    all_screens, n_img = A["screens"], A["n_img"]
    todo = [s for s in all_screens if not s["duplicate_of"]]
    dup = len(all_screens) - len(todo)

    # gabung semua fitur: isi layar -> ringkasan layar (kode saja, cepat, selalu dihitung ulang)
    summaries, failed, empty = [], [], []
    by_id = {s["id"]: s for s in todo}
    for s in todo:
        where = f"gambar {s['image']}" + (f" layar {s['order']}" if s["of"] > 1 else "")
        if not s.get("ocr"):
            empty.append(where)
        elif not s.get("label_ok", True):
            failed.append(where)
    for s in all_screens:
        base = by_id.get(s["duplicate_of"] or s["id"])
        if not base:
            continue
        lines = base.get("ocr") or []
        lab = _lab_of(base)
        sm = scr.summarize({**s}, scr.build_elements(lines, lab), lab, s["card"])
        sm["cover"] = scr.is_cover(lines)
        sm["dup"] = bool(s["duplicate_of"])
        summaries.append(sm)
        s["labels"] = base.get("labels") or {}
        s["ocr"] = lines

    # 4) aturan dari desain, per halaman/fitur. Layar kembar di halaman lain tidak diulang aturannya.
    ui: Dict[str, List[Dict[str, Any]]] = {}
    nav: List[Dict[str, Any]] = []
    nav_seen: set = set()
    sig_seen: set = set()
    described: set = set()
    for c in cards:  # aturan disusun per alur bisnis; layar yang sudah dijelaskan tidak diulang
        sc = [x for x in summaries if x["card"] == c["nama"]]
        rules: List[Dict[str, Any]] = []
        for r in scr.card_rules(c["nama"], sc, nav_seen, described):
            (nav if r["fitur"] == "Navigasi" else rules).append(r)
        ui[c["nama"]] = rules

    # 5) penjelasan QA (sudah dibaca per fitur di atas, dengan penjaga kutipan yang sama seperti Catatan ke PRD)
    notes, rejected, missed, peran, produk, text_items = A["notes"], [], [], [], "", []
    for r in notes:
        text_items += r["accepted"]
        rejected += r["rejected"]
        missed += r["missed"]
        produk = produk or r["produk"]
        peran += [p for p in r["peran"] if p not in peran]
    for it in text_items:
        for k in ("role", "aksi", "lingkup", "objek", "dari", "ke", "pemicu"):
            it.setdefault(k, "")
        it.setdefault("boleh", True)
    doc = ft.build_document(text_items, peran, produk, name, None)

    # gabung: fitur = halaman (urut seperti di dashboard); aturan desain dulu, lalu aturan dari penjelasan
    text_feats = {f["name"]: f for f in doc["features"]}
    features = []
    for c in cards:
        tf = text_feats.pop(c["nama"], None) or next(
            (text_feats.pop(k) for k in list(text_feats) if guards.similar(k, c["nama"]) >= 0.8), None)
        rules = list(ui.get(c["nama"], []))
        if tf:
            rules += [r for r in tf["rules"] if not any(guards.norm(r["pernyataan"]) == guards.norm(x["pernyataan"]) for x in rules)]
        # satu FR per halaman/area; tiap alur jadi sub-judul di dalam FR (Module = area, Sub Module = alur)
        if rules:
            features.append({"name": c["nama"], "description": (tf or {}).get("description", ""), "rules": rules})
    features += list(text_feats.values())
    doc["features"] = features
    td, td_seen = [], set()  # contoh isian yang benar-benar tertulis di desain -> panduan data uji
    # nama layar atau nama alur kadang terbaca sebagai nama field; jangan dipakai sebagai nama field data uji
    bukan_field = {guards.norm(scr.screen_name(sm)) for sm in summaries} | {guards.norm(c["nama"]) for c in cards}
    bukan_field.discard("")
    for sm in summaries:
        if sm.get("dup"):
            continue
        for f in sm.get("fields") or []:
            ex = (f.get("placeholder") or "").strip()
            nm = (f.get("name") or "").strip()
            k = guards.norm(nm)
            if not ex or not nm or k in td_seen or guards.norm(ex) == k or len(ex) > 80 or k in bukan_field:
                continue
            if not re.search(r"@|\d|\b(e\.?g\.?|contoh|mis\.)", ex, re.I):
                continue  # "Select a role", "Search customer": petunjuk, bukan contoh data
            td_seen.add(k)
            td.append({"field": nm, "example": ex})
    doc["test_data"] = td
    sets, st_seen = [], set()  # kumpulan status yang terlihat di desain -> bahan uji perpindahan status
    for sm in summaries:
        where = scr.screen_name(sm)
        if sm.get("dup") or where.startswith("Layar ") or scr._is_mail_client(sm):
            continue
        vals, vseen = [], set()
        for v in (sm.get("status") or []):
            v = str(v).strip()
            # status = label pendek tanpa angka/persen (bukan kalimat atau nilai statistik)
            if not (2 <= len(v) <= 24 and len(v.split()) <= 3 and re.search(r"[A-Za-z]", v)) or re.search(r"[%]|\d", v):
                continue
            if guards.norm(v) not in vseen:
                vseen.add(guards.norm(v))
                vals.append(v)
        k = frozenset(vseen)
        if len(vals) >= 2 and k not in st_seen:
            st_seen.add(k)
            sets.append({"where": where, "values": vals})
    doc["status_sets"] = sets

    # tabel acuan field: tiap isian yang terlihat di desain, beserta keterangan yang tertulis di sebelahnya
    fref, fseen = [], set()
    for sm in summaries:
        where = scr.screen_name(sm)
        if sm.get("dup") or scr._is_mail_client(sm):
            continue
        for f in sm.get("fields") or []:
            nm = (f.get("name") or "").strip()
            k = (guards.norm(sm.get("card") or ""), guards.norm(where), guards.norm(nm))
            if not nm or k in fseen:
                continue
            fseen.add(k)
            ket = []
            if f.get("kind") in ("dropdown", "radio", "toggle", "checkbox"):
                ket.append({"dropdown": "pilihan", "radio": "pilihan", "toggle": "saklar", "checkbox": "centang"}[f["kind"]])
            if [v for v in (f.get("values") or []) if v]:
                ket.append("pilihan di desain: " + ", ".join(str(v) for v in f["values"] if v)[:120])
            for h in (f.get("help") or [])[:2]:
                ket.append(str(h))
            if (f.get("placeholder") or "").strip() and guards.norm(f["placeholder"]) != guards.norm(nm):
                ket.append(f"contoh isian: {f['placeholder']}")
            if "nonaktif" in (f.get("states") or []):
                ket.append("tampak nonaktif di desain")
            fref.append({"area": sm.get("card") or "", "where": where, "field": nm, "note": "; ".join(ket)[:220]})
    doc["fields_ref"] = fref

    # notifikasi beserta pemicunya, dari kalimat alur yang sudah disusun
    fb, fbseen = [], set()
    for r in [x for f in features for x in f["rules"]]:
        t = r["pernyataan"]
        m = re.match(r"Sistem menampilkan notifikasi \"([^\"]+)\"(.*)$", t)
        kapan = ""
        if m:
            after = re.search(r"setelah (.+?)\.?$", m.group(2) or "")
            kapan = (after.group(1) if after else "").strip()
        else:  # notifikasi yang disebut sebagai hasil di dalam kalimat alur
            m = re.search(r"(?:Setelah itu|Bila berhasil,) sistem menampilkan notifikasi \"([^\"]+)\"", t)
            layar = re.match(r"Pada ((?:form|layar|menu)[^,]*?)(?: yang bertuliskan .*?)?, pengguna", t)
            aksi = re.findall(r"(?:menekan|membuka) \"([^\"]+)\"", t)
            niat = re.match(r"Pengguna dapat ([^.]+?)(?: dengan mengisi| dari | melalui )", t)
            if niat:
                kapan = f"pengguna {niat.group(1)}"
            elif aksi:
                kapan = f"pengguna menekan \"{aksi[-1]}\"" + (f" di {layar.group(1)}" if layar else "")
        if not m or guards.norm(m.group(1)) in fbseen:
            continue
        fbseen.add(guards.norm(m.group(1)))
        fb.append({"notif": m.group(1), "when": kapan, "area": r.get("fitur") or ""})
    doc["feedback"] = fb

    # struktur navigasi jadi tabel tersendiri, bukan FR: menu bukan kebutuhan yang diuji satu per satu
    nav_rows = []
    for r in nav:
        isi = re.findall(r'"([^"]+)"', r["pernyataan"])
        if isi:
            nav_rows.append({"area": r.get("alur") or "Navigasi utama", "items": isi[:40]})
    doc["nav_rows"] = nav_rows
    items = [r for f in features for r in f["rules"]]

    P["phase"] = "susun"
    _say(cb, "Menyusun daftar hal yang perlu dicek ...")
    qs = scr.design_questions(summaries, failed, empty)
    text_lines = [l for r in notes for l in r["lines"]]
    if any(l.strip() for l in text_lines):
        qs += ft.questions(text_lines, doc, llm)
    doc["questions"] = qs[:30]
    doc["missed_lines"] = missed
    doc["meta"] = {"source": f"desain ({len(all_screens)} layar dari {n_img} gambar)" + (" dan penjelasan QA" if notes else ""),
                   "created": datetime.now().strftime("%Y-%m-%d %H:%M"), "model": llm.generation_model(),
                   "seconds": round(time.time() - t0), "items_accepted": len(items), "items_rejected": len(rejected)}
    md = render_markdown(doc)
    review = render_review(doc, rejected, summaries)
    stats = {"images": n_img, "screens": len(all_screens), "screens_read": len(todo), "duplicates": dup,
             "labels_failed": len(failed)}
    return {"markdown": md, "review": review, "document": doc, "accepted": items, "rejected": rejected,
            "screens": all_screens, "summaries": summaries, "stats": stats}


def _save(result, cards, extra, md_path: Path, out_dir: Path) -> Dict[str, str]:
    from free_text_to_prd.pdf import markdown_to_pdf
    doc = result["document"]
    md_path.parent.mkdir(parents=True, exist_ok=True)
    md_path.write_text(result["markdown"], encoding="utf-8")
    for sub in ("source/gambar", "intermediate", "prd"):
        (out_dir / sub).mkdir(parents=True, exist_ok=True)
    for c in cards:
        for im in c.get("images") or []:
            dst = out_dir / "source" / "gambar" / Path(im["name"]).name
            if not dst.exists() and Path(im["path"]).is_file():
                shutil.copy2(im["path"], dst)
    (out_dir / "source" / "penjelasan.json").write_text(json.dumps({
        "halaman": [{"nama": c["nama"], "penjelasan": c.get("teks") or "",
                     "gambar": [Path(i["name"]).name for i in c.get("images") or []]} for c in cards],
        "deskripsi_tambahan": extra or ""}, ensure_ascii=False, indent=1), encoding="utf-8")
    (out_dir / "intermediate" / "layar.json").write_text(json.dumps([
        {k: v for k, v in s.items() if k in ("id", "image", "order", "card", "focused", "duplicate_of", "ocr", "labels")}
        for s in result["screens"]], ensure_ascii=False, indent=1, default=str), encoding="utf-8")
    (out_dir / "intermediate" / "extracted_information.json").write_text(
        json.dumps({"accepted": result["accepted"], "rejected": result["rejected"]}, ensure_ascii=False, indent=1,
                   default=str), encoding="utf-8")
    (out_dir / "intermediate" / "catatan_review.md").write_text(result["review"], encoding="utf-8")
    (out_dir / "prd" / md_path.name).write_text(result["markdown"], encoding="utf-8")
    shutil.rmtree(out_dir / "kerja", ignore_errors=True)
    review_path = out_dir / f"{md_path.stem}_catatan_review.pdf"
    review_path.write_bytes(markdown_to_pdf(result["review"], f"Catatan Review - {doc['module']}"))
    meta = {**doc["meta"], **result["stats"], "kind": "desain", "id": out_dir.name, "module": doc["module"],
            "prd_file": md_path.name, "review_file": review_path.name, "time": time.time(),
            "features": len(doc["features"]), "rules": sum(len(f["rules"]) for f in doc["features"]),
            "questions": len(doc["questions"]),
            "conflicts": sum(1 for q in doc["questions"] if q["jenis"] == "bertentangan"),
            "missed": len(doc["missed_lines"])}
    (out_dir / "analysis_metadata.json").write_text(json.dumps(meta, ensure_ascii=False, indent=1), encoding="utf-8")
    return {"prd_path": str(md_path), "out_dir": str(out_dir), "review_path": str(review_path), "id": out_dir.name}
