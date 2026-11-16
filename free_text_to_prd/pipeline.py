"""Alur: catatan -> (AI) ambil item per baris -> (kode) cek kutipan & angka -> (AI, sekali) ulang baris yang
terlewat -> (kode) kelompokkan per fitur -> (AI) pertanyaan terbuka -> (kode) susun Markdown format PRD."""
import json
import re
import time
from datetime import datetime
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional

from free_text_to_prd import guards, prompts
from free_text_to_prd.render import render_markdown, render_review

ROOT = Path(__file__).resolve().parent.parent
CHUNK_LINES = 25

_JENIS = {"field", "aturan", "akses", "status", "alur", "nonfungsional", "info"}


def _say(cb: Optional[Callable[[str], None]], msg: str) -> None:
    (cb or print)(msg)


def split_lines(text: str) -> List[str]:
    """Baris catatan apa adanya (baris kosong dipertahankan agar nomor baris tetap sama dengan teks asli)."""
    return str(text or "").replace("\r\n", "\n").replace("\r", "\n").split("\n")


def is_content(line: str) -> bool:
    """Baris yang membawa informasi (bukan kosong / judul kosong seperti "Role :")."""
    w = guards.words(line)
    if len(w) < 2:
        return False
    return not (line.strip().endswith(":") and len(w) <= 4)


def _numbered(lines: List[str], idx: List[int]) -> str:
    return "\n".join(f"[L{i + 1}] {lines[i]}" for i in idx if lines[i].strip())


def _chunks(lines: List[str]) -> List[List[int]]:
    """Potongan baris untuk AI; baris induk (judul/poin tanpa indentasi terakhir) ikut sebagai konteks."""
    idx = [i for i, l in enumerate(lines) if l.strip()]
    out = []
    for s in range(0, len(idx), CHUNK_LINES):
        part = idx[s:s + CHUNK_LINES]
        if s:
            parents = [i for i in idx[:s] if not lines[i].startswith((" ", "\t"))][-2:]
            part = parents + part
        out.append(part)
    return out


def extract(lines: List[str], idx: List[int], llm, cb=None) -> Dict[str, Any]:
    data = llm.chat_json(llm.generation_model(), prompts.SYSTEM, prompts.EXTRACT.format(notes=_numbered(lines, idx)),
                         temperature=0.0, num_predict=4000)
    return data if isinstance(data, dict) else {}


_KLIK = re.compile(r"\b(?:meng-?)?(?:klik|mengklik|menekan|tekan|pencet|tap|pilih menu)\s+"
                   r"(?:tombol|button|menu|link|tautan|icon|ikon)?\s*", re.I)
_PENGGUNA = re.compile(r"^(?:user|pengguna|qa|tester|admin)\s+", re.I)


def _aksi(nama: str) -> str:
    """Nama tombol/aksi dari catatan -> maksud bisnisnya ("Simpan" -> "menyimpan")."""
    t = re.sub(r"[\s,.;:]+$", "", str(nama or "").strip().strip('"\''))
    hasil = guards.intent(t)
    if hasil and " " not in hasil and len(t.split()) > 1:
        hasil += " " + t.split(" ", 1)[1]  # objeknya tetap dibawa: "Hapus data" -> "menghapus data"
    return hasil or f"menjalankan {t}"


def _business(t: str) -> str:
    """Rapikan kalimat langkah layar menjadi kalimat aturan bisnis, tanpa mengubah istilah dari catatan."""
    s = t.strip()
    # "user klik tombol Simpan lalu muncul pesan X" -> "Pengguna dapat menyimpan ...; sistem menampilkan pesan X"
    m = re.match(r"^(?:user|pengguna)\s+(?:klik|mengklik|menekan|tekan|tap)\s+(?:tombol|button|menu)?\s*"
                 r"(.+?)\s*(?:,|\s)(?:lalu|kemudian|maka|terus|baru)\s+(.+)$", s, re.I)
    if m:
        akibat = re.sub(r"^(muncul|tampil|keluar)\b", "sistem menampilkan", m.group(2).strip(), flags=re.I)
        return f"Pengguna dapat {_aksi(m.group(1))}; bila berhasil {akibat.rstrip('.')}."
    m = re.match(r"^(?:user|pengguna)\s+(?:bisa|dapat|boleh)\s+" + _KLIK.pattern + r"(.+)$", s, re.I)
    if m:
        return f"Pengguna dapat {_aksi(m.group(1))}."
    return (s[0].upper() + s[1:]) if s and s[0].islower() else s


def _clean_item(it: Dict[str, Any]) -> Dict[str, Any]:
    j = str(it.get("jenis") or "").strip().lower()
    it["jenis"] = j if j in _JENIS else "aturan"
    for k in ("fitur", "pernyataan", "kutipan", "role", "aksi", "lingkup", "objek", "dari", "ke", "pemicu"):
        it[k] = re.sub(r"\s+", " ", str(it.get(k) or "")).strip()
    b = it.get("boleh")
    it["boleh"] = not (b is False or str(b).strip().lower() in ("false", "tidak", "no", "0"))
    return it


def run(text: str, name: str = "", source_name: str = "catatan", llm=None, cb=None,
        write: bool = True, prd_dir: Optional[Path] = None, out_dir: Optional[Path] = None) -> Dict[str, Any]:
    if llm is None:
        from tools import llm as _llm
        llm = _llm
    t0 = time.time()
    lines = split_lines(text)
    content = [i for i, l in enumerate(lines) if is_content(l)]
    if not content:
        raise ValueError("Catatan kosong atau terlalu pendek untuk disusun menjadi PRD.")

    accepted: List[Dict[str, Any]] = []
    rejected: List[Dict[str, Any]] = []
    produk, peran = "", []

    def take(data):
        nonlocal produk
        if not produk and str(data.get("produk") or "").strip():
            produk = str(data["produk"]).strip()
        for r in data.get("peran") or []:
            r = str(r).strip()
            if r and r not in peran:
                peran.append(r)
        for it in data.get("items") or []:
            if not isinstance(it, dict):
                continue
            it = _clean_item(it)
            ok, why, ln = guards.check_item(it, lines)
            it["baris"] = ln
            if ok:
                # dirapikan jadi kalimat aturan bisnis SETELAH lolos penjaga kutipan, supaya penjaganya
                # tetap menilai kalimat asli dari catatan
                it["pernyataan"] = _business(it["pernyataan"])
                if not any(guards.norm(a["pernyataan"]) == guards.norm(it["pernyataan"]) for a in accepted):
                    accepted.append(it)
            else:
                rejected.append({**it, "alasan": why})

    chunks = _chunks(lines)
    for n, idx in enumerate(chunks, 1):
        _say(cb, f"Membaca catatan bagian {n}/{len(chunks)} ...")
        take(extract(lines, idx, llm, cb))

    # baris berisi informasi yang belum diambil sama sekali -> ditanyakan ulang sekali (hanya baris itu)
    covered = {a["baris"] for a in accepted}
    missed = [i for i in content if i + 1 not in covered and not _named_only(lines[i], peran)]
    if missed:
        _say(cb, f"{len(missed)} baris belum terbaca, dibaca ulang ...")
        ctx = sorted(set(missed) | {j for i in missed for j in _parents(lines, i)})
        take(extract(lines, ctx, llm, cb))
        covered = {a["baris"] for a in accepted}
        missed = [i for i in content if i + 1 not in covered and not _named_only(lines[i], peran)]

    # role yang disebut AI tetapi tidak ada di catatan dibuang
    full = guards.norm(" ".join(lines))
    peran = [r for r in peran if guards._present(r, full)]

    doc = build_document(accepted, peran, produk, name, lines)
    names = peran + [f["name"] for f in doc["features"]] + [s["object"] for s in doc["states"]]
    missed = [i for i in missed if not _named_only(lines[i], names)]  # baris yang hanya nama fitur/role
    _say(cb, "Menyusun daftar pertanyaan untuk hal yang belum jelas ...")
    doc["questions"] = questions(lines, doc, llm)
    doc["missed_lines"] = [{"baris": i + 1, "teks": lines[i].strip()} for i in missed]
    doc["meta"] = {
        "source": source_name, "created": datetime.now().strftime("%Y-%m-%d %H:%M"),
        "model": llm.generation_model(), "seconds": round(time.time() - t0),
        "items_accepted": len(accepted), "items_rejected": len(rejected),
    }
    md = render_markdown(doc)
    review = render_review(doc, rejected)
    doc.pop("_trace", None)
    result = {"markdown": md, "review": review, "document": doc, "accepted": accepted, "rejected": rejected}
    if write:
        result.update(save(result, text, prd_dir, out_dir))
    _say(cb, f"Selesai: {len(doc['features'])} fitur, {sum(len(f['rules']) for f in doc['features'])} aturan, "
             f"{len(doc['questions'])} pertanyaan terbuka, {len(rejected)} item ditolak penjaga.")
    return result


def _parents(lines: List[str], i: int) -> List[int]:
    """Baris induk (indentasi lebih kecil) di atas baris i, sebagai konteks."""
    out, ind = [], len(lines[i]) - len(lines[i].lstrip())
    for j in range(i - 1, -1, -1):
        if not lines[j].strip():
            continue
        jind = len(lines[j]) - len(lines[j].lstrip())
        if jind < ind:
            out.append(j)
            ind = jind
            if ind == 0:
                break
    return out


def _named_only(line: str, peran: List[str]) -> bool:
    """Baris yang hanya nama role/judul (mis. "2. Admin") sudah terwakili di daftar role."""
    t = re.sub(r"^\s*(?:[-*•]|\d+[.)])\s*", "", line).strip(" :")
    return any(guards.norm(t) == guards.norm(r) or guards.similar(t, r) >= 0.8 for r in peran)


# ---------------------------------------------------------------------------
# pengelompokan (kode)
# ---------------------------------------------------------------------------
def _canon(name: str, canon: List[str]) -> str:
    n = guards.norm(name)
    for c in canon:
        cn = guards.norm(c)
        if n == cn or guards.similar(n, cn) >= 0.67 or (len(n) >= 4 and (n in cn or cn in n)):
            return c
    canon.append(name)
    return name


def _state(name: str) -> str:
    return re.sub(r"[^A-Z0-9]+", "_", str(name).upper()).strip("_")


def build_document(items: List[Dict[str, Any]], peran: List[str], produk: str, name: str,
                   lines: Optional[List[str]] = None) -> Dict[str, Any]:
    items = sorted(items, key=lambda x: (x.get("baris") or 0))
    canon: List[str] = []
    features: Dict[str, Dict[str, Any]] = {}
    overview: List[str] = []
    nfr: Dict[str, List[Dict[str, Any]]] = {}
    transitions: Dict[str, List[Dict[str, Any]]] = {}
    access: List[Dict[str, Any]] = []
    last_feat = ""

    for it in items:
        j = it["jenis"]
        if j == "info" and not it["fitur"]:
            overview.append(it["pernyataan"])
            continue
        if j == "akses" and it["role"]:
            if it["role"] not in peran:
                peran.append(it["role"])
            access.append(it)
        ln = (lines or [])[it["baris"] - 1] if lines and it.get("baris") and it["baris"] <= len(lines) else ""
        sub_point = ln.startswith((" ", "\t"))  # sub-poin ikut fitur induknya; baris lepas = ketentuan umum
        feat_raw = it["fitur"] or ("Hak Akses Role" if j == "akses" else
                                   (last_feat if sub_point and last_feat else "Ketentuan Umum"))
        feat = _canon(feat_raw, canon)
        last_feat = feat if it["fitur"] else last_feat
        if j == "nonfungsional":
            nfr.setdefault(feat, []).append(it)
            continue
        if j == "status" and it["dari"] and it["ke"] and guards.norm(it["dari"]) != guards.norm(it["ke"]):
            obj = _canon(it["objek"] or feat, canon) if it["objek"] else feat
            transitions.setdefault(obj, []).append(it)
            continue
        f = features.setdefault(feat, {"name": feat, "description": "", "rules": []})
        if j == "info" and not f["description"]:
            f["description"] = it["pernyataan"]
            f["desc_item"] = it
            continue
        if not any(guards.similar(it["pernyataan"], r["pernyataan"]) >= 0.9 for r in f["rules"]):
            f["rules"].append(it)

    # fitur yang hanya punya deskripsi -> deskripsinya jadi aturan (supaya tetap teruji)
    for f in features.values():
        if not f["rules"] and f.get("desc_item"):
            f["rules"].append(f.pop("desc_item"))
            f["description"] = ""

    # tabel hak akses: hanya bila catatan menyebut >= 2 role dan >= 2 aksi
    roles = [r for r in peran if any(guards.similar(r, a["role"]) >= 0.6 for a in access)] or []
    actions: List[str] = []
    for a in access:
        if a["aksi"] and not any(guards.similar(a["aksi"], x) >= 0.6 for x in actions):
            actions.append(a["aksi"])
    decision = None
    if len(roles) >= 2 and len(actions) >= 2:
        decision = {"title": "Hak Akses per Role", "conditions": [
            {"name": "Role", "values": roles},
            {"name": "Aksi", "values": actions[:6]},
        ]}

    return {
        "product": produk, "module": name or produk or (next(iter(features), "") if features else "Catatan QA"),
        "roles": peran, "overview": overview, "features": list(features.values()),
        "nfr": [{"name": k, "rules": v} for k, v in nfr.items()],
        "states": [{"object": k, "transitions": [{**t, "dari": _state(t["dari"]), "ke": _state(t["ke"])} for t in v]}
                   for k, v in transitions.items()],
        "decision": decision,
    }


# ---------------------------------------------------------------------------
# pertanyaan terbuka (AI + penjaga kode)
# ---------------------------------------------------------------------------
def questions(lines: List[str], doc: Dict[str, Any], llm) -> List[Dict[str, str]]:
    draft = []
    for f in doc["features"]:
        draft.append(f"Fitur {f['name']}: " + "; ".join(r["pernyataan"] for r in f["rules"]))
    for s in doc["states"]:
        draft.append(f"Status {s['object']}: " + "; ".join(f"{t['dari']} -> {t['ke']}" for t in s["transitions"]))
    data = llm.chat_json(llm.generation_model(), prompts.SYSTEM,
                         prompts.QUESTIONS.format(notes="\n".join(l for l in lines if l.strip()), draft="\n".join(draft)),
                         temperature=0.0, num_predict=1800)
    out: List[Dict[str, str]] = []
    for q in (data or {}).get("pertanyaan", []) if isinstance(data, dict) else []:
        if not isinstance(q, dict):
            continue
        text = re.sub(r"\s+", " ", str(q.get("pertanyaan") or "")).strip()
        if len(text) < 8 or any(guards.similar(text, o["pertanyaan"]) >= 0.8 for o in out):
            continue
        kind = "bertentangan" if "tentang" in str(q.get("jenis", "")).lower() else "belum jelas"
        quote = str(q.get("kutipan") or "").strip()
        if kind == "bertentangan" and not guards.find_quote(quote, lines):
            kind, quote = "belum jelas", ""  # klaim pertentangan tanpa bukti dari catatan tidak dipakai
        out.append({"fitur": str(q.get("fitur") or "").strip(), "jenis": kind, "pertanyaan": text, "kutipan": quote})
    # pemeriksaan kode: fitur tanpa aturan konkret
    for f in doc["features"]:
        if len(f["rules"]) == 1 and f["rules"][0]["jenis"] == "info":
            out.append({"fitur": f["name"], "jenis": "belum jelas",
                        "pertanyaan": f"Aturan/validasi untuk {f['name']} belum dijelaskan di catatan. Apa saja ketentuannya?",
                        "kutipan": ""})
    return out[:20]


# ---------------------------------------------------------------------------
# simpan
# ---------------------------------------------------------------------------
def slugify(name: str) -> str:
    s = re.sub(r"[^a-z0-9]+", "_", guards.norm(name)).strip("_")
    return (s or "catatan_qa")[:60]


def save(result: Dict[str, Any], text: str, prd_dir: Optional[Path] = None, out_dir: Optional[Path] = None) -> Dict[str, str]:
    """PRD -> knowledge/prd (muncul di daftar PRD dashboard). Semua pendamping -> outputs/free_text_to_prd/<nama PRD>/,
    satu folder per konversi (dipakai juga oleh menu Riwayat)."""
    from free_text_to_prd.pdf import markdown_to_pdf
    doc = result["document"]
    slug = slugify(doc["module"]) + "_dari_catatan"
    prd_dir = prd_dir or ROOT / "knowledge" / "prd"
    base = out_dir or ROOT / "outputs" / "free_text_to_prd"
    prd_dir.mkdir(parents=True, exist_ok=True)
    md_path = prd_dir / f"{slug}.md"
    n = 2
    while md_path.exists() or (base / md_path.stem).exists():  # PRD / konversi lama tidak pernah ditimpa
        md_path = prd_dir / f"{slug}_v{n}.md"
        n += 1
    out_dir = base / md_path.stem
    md_path.write_text(result["markdown"], encoding="utf-8")
    for sub in ("source", "intermediate", "prd"):
        (out_dir / sub).mkdir(parents=True, exist_ok=True)
    (out_dir / "source" / "original_input.txt").write_text(text, encoding="utf-8")
    (out_dir / "intermediate" / "extracted_information.json").write_text(
        json.dumps({"accepted": result["accepted"], "rejected": result["rejected"]}, ensure_ascii=False, indent=1),
        encoding="utf-8")
    (out_dir / "intermediate" / "clarification_items.json").write_text(
        json.dumps({"questions": doc["questions"], "missed_lines": doc["missed_lines"]}, ensure_ascii=False, indent=1),
        encoding="utf-8")
    (out_dir / "intermediate" / "catatan_review.md").write_text(result["review"], encoding="utf-8")
    (out_dir / "prd" / md_path.name).write_text(result["markdown"], encoding="utf-8")
    review_path = out_dir / f"{md_path.stem}_catatan_review.pdf"
    review_path.write_bytes(markdown_to_pdf(result["review"], f"Catatan Review - {doc['module']}"))
    (out_dir / "prd" / "product_requirements_document.json").write_text(
        json.dumps(doc, ensure_ascii=False, indent=1, default=str), encoding="utf-8")
    meta = {**doc["meta"], "id": out_dir.name, "module": doc["module"], "prd_file": md_path.name,
            "review_file": review_path.name, "time": time.time(),
            "features": len(doc["features"]), "rules": sum(len(f["rules"]) for f in doc["features"]),
            "questions": len(doc["questions"]),
            "conflicts": sum(1 for q in doc["questions"] if q["jenis"] == "bertentangan"),
            "missed": len(doc["missed_lines"])}
    (out_dir / "analysis_metadata.json").write_text(json.dumps(meta, ensure_ascii=False, indent=1), encoding="utf-8")
    return {"prd_path": str(md_path), "out_dir": str(out_dir), "review_path": str(review_path), "id": out_dir.name}
