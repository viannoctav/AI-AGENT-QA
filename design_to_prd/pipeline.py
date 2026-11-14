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


def run(cards: List[Dict[str, Any]], extra: str = "", name: str = "", llm=None, ocr_fn=None, cb=None,
        write: bool = True, prd_dir: Optional[Path] = None, out_base: Optional[Path] = None,
        progress: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    """cards: [{"nama", "teks", "images": [{"path", "name"}]}] urut sesuai halaman di dashboard."""
    if llm is None:
        from tools import llm as _llm
        llm = _llm
    if ocr_fn is None:
        from design_to_prd.ocr import read_text as ocr_fn
    from design_to_prd.ocr import clean_lines
    t0 = time.time()
    name = re.sub(r"\s+", " ", str(name or "")).strip() or "Desain"
    cards = [c for c in cards if (c.get("teks") or "").strip() or c.get("images")]
    if not cards and not (extra or "").strip():
        raise ValueError("Isi minimal satu halaman/fitur dengan gambar atau penjelasan.")
    for i, c in enumerate(cards, 1):
        c["nama"] = re.sub(r"\s+", " ", str(c.get("nama") or "")).strip() or f"Halaman {i}"

    if write:
        md_path, out_dir = reserve(name, prd_dir, out_base)
    else:
        import tempfile
        out_dir, md_path = Path(tempfile.mkdtemp()), Path("preview_dari_desain.md")
    try:
        P = progress if progress is not None else {}
        P.update({"phase": "siapkan", "screens_total": 0, "screens_done": 0, "screen_secs": [],
                  "texts_total": sum(1 for c in cards if (c.get("teks") or "").strip()) + (1 if (extra or "").strip() else 0),
                  "texts_done": 0})
        result = _run(cards, extra, name, llm, ocr_fn, clean_lines, cb, out_dir, t0, P)
        P["phase"] = "selesai"
        if write:
            result.update(_save(result, cards, extra, md_path, out_dir))
        _say(cb, f"Selesai: {result['stats']['screens']} layar dibaca, {len(result['document']['features'])} fitur, "
                 f"{sum(len(f['rules']) for f in result['document']['features'])} aturan, "
                 f"{len(result['document']['questions'])} hal untuk dicek.")
        return result
    except Exception:
        if write:
            shutil.rmtree(out_dir, ignore_errors=True)
        raise


def _run(cards, extra, name, llm, ocr_fn, clean_lines, cb, out_dir, t0, P):
    # 1) gambar -> layar
    all_screens, seen = [], {}
    n_img = sum(len(c.get("images") or []) for c in cards)
    if n_img:
        _say(cb, f"Menyiapkan {n_img} gambar: memotong papan alur menjadi layar dan membuang latar buram ...")
    for ci, c in enumerate(cards, 1):
        if c.get("images"):
            for s in imgs.prepare(c["images"], out_dir / "layar" / f"{ci:02d}", seen):
                s["card"] = c["nama"]
                all_screens.append(s)
    todo = [s for s in all_screens if not s["duplicate_of"]]
    dup = len(all_screens) - len(todo)
    P.update(phase="baca_teks", screens_total=len(todo))

    # 2) OCR (beberapa detik untuk semua layar)
    ocr: Dict[str, List[Dict[str, Any]]] = {}
    if todo:
        _say(cb, f"Membaca teks {len(todo)} layar dengan pembaca teks Windows" +
             (f" ({dup} layar kembar dilewati)" if dup else "") + " ...")
        ocr = ocr_fn([s["path"] for s in todo], out_dir / "kerja")
    # 3) AI memberi jenis (per layar)
    summaries, failed, empty, by_id = [], [], [], {}
    lab_cache: Dict[Any, Dict[str, Any]] = {}
    reused = 0
    P["phase"] = "kenali"
    for k, s in enumerate(todo, 1):
        ts = time.time()
        lines = clean_lines(ocr.get(s["path"], []), s["size"][1])
        s["ocr"] = lines
        where = f"gambar {s['image']}" + (f" layar {s['order']}" if s["of"] > 1 else "")
        sig = tuple(l["text"] for l in lines)
        if not lines:
            empty.append(where)
            lab = {"kind": "", "title_no": 0, "labels": {}, "ok": True}
        elif scr.is_cover(lines):  # bingkai sampul alur: cukup judulnya, tidak perlu AI
            lab = {"kind": "", "title_no": 0, "labels": {}, "ok": True}
        elif sig in lab_cache:  # layar dengan teks yang sama persis: jenisnya dipakai ulang, tidak ditanyakan lagi ke AI
            lab = lab_cache[sig]
            reused += 1
        else:
            _say(cb, f"Mengenali elemen layar {k}/{len(todo)} ({where}, {len(lines)} teks) ...")
            lab = lb.label_screen(llm, s["path"], lines)
            if not lab["ok"]:
                failed.append(where)
            else:
                lab_cache[sig] = lab
            P["screen_secs"].append(round(time.time() - ts, 1))
        by_id[s["id"]] = (s, lab)
        P["screens_done"] = k
    for s in all_screens:
        src = by_id.get(s["duplicate_of"] or s["id"])
        if not src:
            continue
        base, lab = src
        lines = base.get("ocr", [])
        lab = dict(lab)
        sm = scr.summarize({**s}, scr.build_elements(lines, lab), lab, s["card"])
        sm["cover"] = scr.is_cover(lines)
        sm["dup"] = bool(s["duplicate_of"])
        summaries.append(sm)
        s["labels"] = {str(k): v for k, v in lab["labels"].items()}
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

    # 5) penjelasan QA (per halaman + deskripsi tambahan): penjaga kutipan yang sama dengan Catatan Konversi ke PRD
    notes, rejected, missed, peran, produk, text_items = [], [], [], [], "", []
    for c in cards:
        if (c.get("teks") or "").strip():
            P["phase"] = "penjelasan"
            notes.append(read_notes(c["teks"], c["nama"], llm, cb, label=f"\"{c['nama']}\""))
            P["texts_done"] += 1
    if (extra or "").strip():
        P["phase"] = "penjelasan"
        notes.append(read_notes(extra, None, llm, cb, label="tambahan"))
        P["texts_done"] += 1
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
        if rules:
            features.append({"name": c["nama"], "description": (tf or {}).get("description", ""), "rules": rules})
    if nav:
        features.append({"name": "Navigasi", "description": "", "rules": nav})
    features += list(text_feats.values())
    doc["features"] = features
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
