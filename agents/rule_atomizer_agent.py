# agents/rule_atomizer_agent.py
"""
Rule Atomizer (v2): mengubah PRD menjadi ATOM aturan yang bisa diuji.

Atom = satu aturan terstruktur: {kind, params, text, requirement_ids, ...}
Kind: length_range | length_max | length_min | length_exact | count_max | count_trigger |
      duration_expiry | duration_lock | duration_tolerance | perf | single_use | required |
      unique | format | composition | whitespace | transition | invalid_transition |
      decision | edge | acceptance | flow | rule

Generik: tidak ada nama fitur/domain di-hardcode. Pola yang dipakai bersifat linguistik
(Inggris + Indonesia): "between A and B", "maximum N", "after N consecutive failed",
"expires after N minutes", "single-use", dst. Aturan yang tidak cocok pola apa pun tetap
menjadi atom kind=rule (1 obligation kualitatif), jadi tidak ada aturan yang hilang.
"""

import re
from typing import Any, Dict, List, Optional, Tuple

from tools.data_synthesizer import infer_data_type
from tools.ui import ui
from tools.prd_structure import (
    ID_RE, extract_bullets, extract_decisions, extract_transitions, parse_prd_markdown,
    strip_md, to_requirements_dict,
)

# ---------------------------------------------------------------------------
# Pola linguistik
# ---------------------------------------------------------------------------
UNIT = r"(characters?|chars?|karakter|digits?|angka)"
DUR_UNIT = r"(seconds?|secs?|detik|minutes?|mins?|menit|hours?|jam|days?|hari)"
_DUR_SEC = {"second": 1, "sec": 1, "detik": 1, "minute": 60, "min": 60, "menit": 60,
            "hour": 3600, "jam": 3600, "day": 86400, "hari": 86400}
FAIL_WORD = r"(?:failed|incorrect|invalid|unsuccessful|wrong|gagal|salah)"

_STOP = {
    "the", "and", "for", "with", "must", "may", "from", "that", "this", "have", "will", "when",
    "are", "not", "can", "only", "than", "into", "per", "any", "all", "has", "its", "via",
    "user", "users", "system", "after", "before", "each", "every", "one", "set", "new", "old",
    "yang", "dan", "untuk", "dengan", "pada", "atau", "dari", "dalam", "harus", "tidak",
    "should", "shall", "been", "being", "their", "there", "which", "also", "such", "then",
}


def _stem(w: str) -> str:
    for suf in ("ing", "ed", "es", "s"):
        if w.endswith(suf) and len(w) - len(suf) >= 4:
            return w[: -len(suf)]
    return w


def tokens(text: str) -> set:
    return {_stem(w) for w in re.findall(r"[a-zA-Z]{3,}", str(text).lower()) if w not in _STOP}


def _dur_seconds(num: str, unit: str) -> int:
    u = unit.lower().rstrip("s")
    return int(num) * _DUR_SEC.get(u, _DUR_SEC.get(unit.lower(), 1))


def _norm(text: str) -> str:
    t = strip_md(text).replace("\u2013", "-").replace("\u2014", "-").replace("\u2212", "-")
    t = t.replace("\u00b1", "+-")
    return t


def _unit_norm(u: str) -> str:
    u = u.lower()
    return "digit" if u.startswith(("digit", "angka")) else "karakter"


def _overlaps(span, used) -> bool:
    return any(not (span[1] <= a or span[0] >= b) for a, b in used)


def technique_for_text(text: str) -> str:
    t = text.lower()
    if re.search(r"gateway|dependency|dependencies|third[- ]party|outage|unreachable|unavailable|"
                 r"time ?out|crash|redis|provider|layanan eksternal|network drop", t):
        return "Integration / Dependency Failure"
    if re.search(r"encrypt|hash|plain ?text|secret|replay|fail[- ]closed|unauthori[sz]ed|bypass|"
                 r"hijack|inject|\blogs?\b|logged|audit|revok|enkripsi|sandi", t):
        return "Security"
    if re.search(r"\bstate\b|transition|status", t):
        return "State Transition"
    return "Equivalence Partitioning"


# ---------------------------------------------------------------------------
# Ekstraksi atom dari SATU baris aturan
# ---------------------------------------------------------------------------
def extract_rule_atoms(text: str, ctx_title: str = "", is_nfr: bool = False) -> List[Dict[str, Any]]:
    t = _norm(text)
    low = t.lower()
    used: List[Tuple[int, int]] = []
    atoms: List[Dict[str, Any]] = []
    context = f"{ctx_title} {t}"

    def add(kind, params, text_=t, **extra):
        a = {"kind": kind, "params": params, "text": text_}
        a.update(extra)
        atoms.append(a)

    # --- performance: "95% ... within 500 ms"
    m = re.search(r"(\d+(?:\.\d+)?)\s*%[^.]*?(?:within|under|less than|dalam|kurang dari)\s+(\d+)\s*"
                  r"(ms|milliseconds?|s|seconds?|detik)\b", low)
    if m:
        ms = int(m.group(2)) * (1 if m.group(3).startswith("m") else 1000)
        add("perf", {"percent": float(m.group(1)), "ms": ms})
        used.append(m.span())

    http_codes = re.findall(r"http\s*(\d{3})", low)

    # --- length range / max / min / exact
    for pat in (rf"(?:between|antara)\s+(\d+)\s*(?:and|dan|to|sampai|hingga|-)\s*(\d+)\s*{UNIT}",
                rf"(\d+)\s*-\s*(\d+)\s*{UNIT}"):
        for m in re.finditer(pat, low):
            if _overlaps(m.span(), used):
                continue
            unit = _unit_norm(m.group(3))
            add("length_range", {"min": int(m.group(1)), "max": int(m.group(2)), "unit": unit},
                data_type=infer_data_type(context, unit))
            used.append(m.span())
    for m in re.finditer(rf"(?:max(?:imum)?|maks(?:imal|imum)?|at most|no more than|cannot exceed|"
                         rf"must not exceed|up to|tidak boleh lebih dari)\b[^\d.;]{{0,30}}?(\d+)\s*{UNIT}", low):
        if _overlaps(m.span(), used):
            continue
        unit = _unit_norm(m.group(2))
        add("length_max", {"max": int(m.group(1)), "unit": unit}, data_type=infer_data_type(context, unit))
        used.append(m.span())
    for m in re.finditer(rf"(?:min(?:imum)?|minimal|at least|no less than|paling sedikit)\b[^\d.;]{{0,30}}?(\d+)\s*{UNIT}", low):
        if _overlaps(m.span(), used):
            continue
        unit = _unit_norm(m.group(2))
        add("length_min", {"min": int(m.group(1)), "unit": unit}, data_type=infer_data_type(context, unit))
        used.append(m.span())
    for m in re.finditer(r"(?:set of|consists? of|terdiri dari|sebanyak)\s+(\d+)\s+[A-Za-z ]{0,30}?"
                         r"(codes?|items?|kode|entries|tokens?)", low):
        if _overlaps(m.span(), used):
            continue
        add("length_exact", {"n": int(m.group(1)), "unit": "item"}, direction="output",
            data_type="text")
        used.append(m.span())
    for pat in (rf"exactly\s+(\d+)[- ]?{UNIT}", rf"(\d+)[- ]{UNIT}"):
        for m in re.finditer(pat, low):
            if _overlaps(m.span(), used):
                continue
            unit = _unit_norm(m.group(2))
            direction = "output" if re.search(r"generat|menghasilkan|issued|returned|dibuat sistem", low) \
                and not re.search(r"enter|input|masukkan|provide|submit", low) else "input"
            add("length_exact", {"n": int(m.group(1)), "unit": unit}, direction=direction,
                data_type=infer_data_type(context, unit))
            used.append(m.span())

    # --- counts
    win = None
    wm = re.search(rf"(?:within|per|in the last|dalam|setiap|every)\s+(?:an?\s+|the\s+)?(\d+)[- ]?{DUR_UNIT}", low)
    if wm:
        win = _dur_seconds(wm.group(1), wm.group(2))
    consecutive = bool(re.search(r"consecutive|successive|berturut", low))
    count_done = False
    for pat in (rf"after\s+(?:the\s+)?(\d+)(?:st|nd|rd|th)?\s+(?:consecutive\s+|successive\s+)?{FAIL_WORD}",
                rf"(\d+)\s+(?:consecutive|successive|berturut-turut)\s+{FAIL_WORD}",
                rf"the\s+(\d+)(?:st|nd|rd|th)\s+(?:consecutive\s+)?{FAIL_WORD}",
                rf"setelah\s+(\d+)\s+kali\s+{FAIL_WORD}"):
        m = re.search(pat, low)
        if m and not _overlaps(m.span(), used):
            add("count_trigger", {"n": int(m.group(1)), "consecutive": consecutive})
            used.append(m.span())
            count_done = True
            break
    if not count_done:
        mx = r"(?:max(?:imum)?|maks(?:imal|imum)?|at most|up to|no more than|paling banyak)"
        cw = r"(requests?|attempts?|retries|resends?|tries|percobaan|permintaan|kali|times)"
        m = re.search(rf"{mx}\b[^.;\d]{{0,40}}?(\d+)\s+(?!%)[A-Za-z][A-Za-z /-]{{0,50}}?\b{cw}\b", low)
        if not m:
            m2 = re.search(rf"{mx}\b[^.;]{{0,80}}?\b{cw}\b[^.;\d]{{0,40}}?(\d+)\b", low)
            num = m2.group(2) if m2 else None
            span = m2.span() if m2 else None
        else:
            num, span = m.group(1), m.span()
        if num and span and not _overlaps(span, used):
            add("count_max", {"n": int(num)})
            used.append(span)
            count_done = True
    if count_done and win:
        for a in atoms:
            if a["kind"] in ("count_max", "count_trigger"):
                a["params"]["window_s"] = win
        for m in re.finditer(rf"(?:within|per|in the last|dalam|setiap|every)\s+(?:an?\s+|the\s+)?(\d+)[- ]?{DUR_UNIT}"
                             r"(?:\s+window)?", low):
            used.append(m.span())
    if count_done and http_codes:
        for a in atoms:
            if a["kind"] in ("count_max", "count_trigger"):
                a["params"]["http_status"] = int(http_codes[0])

    # --- single use
    single = re.search(r"exactly once|only once|single[- ]use|one[- ]time|used once|sekali pakai|hanya sekali|"
                       r"cannot be (?:re-?)?(?:used|submitted)|not be re-?used|cannot be reused|"
                       r"tidak (?:dapat|boleh) digunakan kembali|re-?use of|re-?submitted", low)
    single_window = None

    # --- durations
    for m in re.finditer(rf"(\d+)\s*[- ]?\s*{DUR_UNIT}\b", low):
        if _overlaps(m.span(), used):
            continue
        secs = _dur_seconds(m.group(1), m.group(2))
        if single:
            single_window = secs
            used.append(m.span())
            continue
        if re.search(r"tolerance|drift|toleransi|\+-", low):
            im = re.search(r"\+-\s*(\d+)\s*interval", low)
            add("duration_tolerance", {"interval_s": secs, "tolerance": int(im.group(1)) if im else 1})
            used.append(m.span())
        elif re.search(r"lock|cooldown|block|ban\b|kunci|blokir|suspend", low):
            add("duration_lock", {"t_s": secs})
            used.append(m.span())
        elif re.search(r"expire|expir|kadaluarsa|kedaluwarsa|valid for|valid until|berlaku|validity|lifetime|ttl", low):
            add("duration_expiry", {"t_s": secs})
            used.append(m.span())
    if single:
        atoms[:] = [a for a in atoms if not a["kind"].startswith("length_")]
        add("single_use", {"window_s": single_window} if single_window else {})

    # --- required / unique
    if re.fullmatch(r"\W*(required|wajib(?: diisi)?|mandatory)\W*", low) or \
            re.search(r"\b(is|are|must be) required\b|\bwajib diisi\b", low):
        add("required", {}, data_type=infer_data_type(context))
    if re.search(r"must be unique|unique within|harus unik|bersifat unik|\bunique\b", low):
        add("unique", {}, data_type=infer_data_type(context))

    # --- format
    fm = None
    if re.search(r"valid e-?mail|e-?mail format|format e-?mail|valid format|format (?:yang )?valid", low):
        fm = "email" if infer_data_type(context) == "email" else "generic"
    elif re.search(r"digits only|numeric only|only digits|hanya angka|hanya digit", low):
        fm = "digits_only"
    elif re.search(r"base[- ]?32", low):
        fm = "base32"
    elif re.search(r"alphanumeric|alfanumerik", low):
        fm = "alnum"
    if fm:
        output = bool(re.search(r"generat|menghasilkan|issued|returned", low))
        add("format", {"format": fm, "direction": "output" if output else "input"},
            data_type=infer_data_type(context, "digit" if fm == "digits_only" else ""))

    # --- composition (>= 2 kelas karakter)
    classes = []
    if re.search(r"uppercase|huruf besar|capital|mixed case", low):
        classes.append("upper")
    if re.search(r"lowercase|huruf kecil|mixed case", low):
        classes.append("lower")
    if re.search(r"numeric|\bnumber\b|\bdigit\b|\bangka\b", low) and not re.search(r"digits? only", low):
        classes.append("digit")
    if re.search(r"special char|karakter khusus|simbol|symbol", low):
        classes.append("special")
    if len(classes) >= 2:
        add("composition", {"classes": classes}, data_type=infer_data_type(context))

    # --- whitespace
    if re.search(r"whitespace|white space|\bspasi\b", low):
        add("whitespace", {}, data_type=infer_data_type(context))

    # --- enumerasi: "Label: a, b, c" -> satu obligation per butir; "must include a, b, c" -> gabungan
    em = re.match(r"^([^:]{3,60}?):\s*(.+?)\.?$", t)
    if em:
        parts = [p.strip(" .") for p in re.split(r",\s*(?:and\s+|dan\s+)?|\s+and\s+|\s+dan\s+", em.group(2)) if p.strip(" .")]
        if len(parts) >= 3 and all(len(p.split()) <= 5 for p in parts):
            add("enumeration", {"label": em.group(1).strip(), "items": parts, "mode": "each"},
                technique=technique_for_text(t))
    if not atoms:
        im = re.search(r"(?:must|should|shall|harus)\s+(?:include|includes|memuat|mencakup|berisi)\s+(.+?)\.?$", t, re.IGNORECASE)
        if im:
            parts = [p.strip(" .") for p in re.split(r",\s*(?:and\s+|dan\s+)?|\s+and\s+|\s+dan\s+", im.group(1)) if p.strip(" .")]
            if len(parts) >= 3 and all(len(p.split()) <= 5 for p in parts):
                add("enumeration", {"label": t[:im.start()].strip() or "payload", "items": parts, "mode": "all"},
                    technique=technique_for_text(t))

    if not atoms:
        add("rule", {}, technique=technique_for_text(t))
    return atoms


# ---------------------------------------------------------------------------
# Merge restatement (BR / AC) & duplikat lintas item
# ---------------------------------------------------------------------------
_NUMKEYS = ("min", "max", "n", "t_s", "window_s", "interval_s", "percent", "ms", "tolerance")


def _numkey(atom: Dict[str, Any]) -> tuple:
    p = atom.get("params", {})
    return tuple(sorted((k, p[k]) for k in _NUMKEYS if k in p))


def _containment(a: set, b: set, denom: str = "a") -> float:
    if not a or not b:
        return 0.0
    inter = len(a & b)
    return inter / (len(a) if denom == "a" else min(len(a), len(b)))


def merge_atoms(atoms: List[Dict[str, Any]], restatement_types=("BR", "AC")) -> List[Dict[str, Any]]:
    # document frequency token (jumlah sumber berbeda yang memuat token) untuk mendeteksi token "langka"
    df: Dict[str, set] = {}
    for a in atoms:
        for tk in tokens(a["text"]):
            df.setdefault(tk, set()).add(a.get("source"))
    rare = {tk for tk, srcs in df.items() if len(srcs) <= 4}

    kept: List[Dict[str, Any]] = []
    for b in atoms:
        if b["kind"] in ("transition", "invalid_transition", "decision", "edge"):
            kept.append(b)
            continue
        is_restate = b.get("item_type") in restatement_types
        tb_rule = tokens(b["text"])
        best, best_score = None, 0.0
        for a in kept:
            if a.get("source") == b.get("source"):
                continue
            same_kind = a["kind"] == b["kind"]
            soft_kind = is_restate and {a["kind"], b["kind"]} <= {"rule", "flow", "acceptance"}
            if not (same_kind or soft_kind):
                continue
            numeric = bool(_numkey(b))
            if numeric and _numkey(a) != _numkey(b):
                continue
            if is_restate:
                score = _containment(tb_rule | tokens(b.get("item_title", "")), a["ctx_tokens"], "a")
                thr = 0.34
            else:
                # antar FR/NFR: hanya aturan bernilai angka yang sama DAN berbagi >=2 token langka
                if not numeric or a.get("item_type") in restatement_types:
                    continue
                shared_rare = (tb_rule & tokens(a["text"])) & rare
                if len(shared_rare) < 1:
                    continue
                score = _containment(tb_rule, tokens(a["text"]), "min")
                thr = 0.5
            if score >= thr and score > best_score:
                best, best_score = a, score
        if best is not None:
            for rid in b["requirement_ids"]:
                if rid not in best["requirement_ids"]:
                    best["requirement_ids"].append(rid)
            best.setdefault("aliases", []).append({"source": b.get("source"), "text": b["text"]})
            if b["kind"] in ("count_max", "count_trigger") and b["params"].get("http_status") \
                    and "http_status" not in best["params"]:
                best["params"]["http_status"] = b["params"]["http_status"]
        else:
            kept.append(b)
    return kept


# ---------------------------------------------------------------------------
# Artefak: state model, decision table, edge case, acceptance criteria
# ---------------------------------------------------------------------------
_EDGE_TITLE = re.compile(r"edge|corner|boundary|kasus tepi|kasus batas|skenario khusus", re.IGNORECASE)
_ACCEPT_TITLE = re.compile(r"acceptance|kriteria (?:penerimaan|keberterimaan)|definition of done", re.IGNORECASE)
_SKIP_TITLE = re.compile(r"coverage|overview|actors?|document information|informasi dokumen|glossary|"
                         r"test data|data uji|purpose|tujuan|changelog|revision", re.IGNORECASE)


def _guess_requirement_ids(text: str, items: List[Dict[str, Any]], top: int = 2, thr: float = 0.25) -> List[str]:
    explicit = [m for m in re.findall(ID_RE, text) if any(m == it["id"] for it in items)]
    if explicit:
        return list(dict.fromkeys(explicit))[:3]
    tk = tokens(text)
    scored = []
    for it in items:
        if it["type"] == "BR":
            continue
        ctx = tokens(f"{it['title']} {it['description']} {' '.join(it['rules'])}")
        title_t = tokens(it["title"])
        score = _containment(tk, ctx, "a") + 0.5 * _containment(tk, title_t, "a")
        scored.append((score, it["id"]))
    scored.sort(reverse=True)
    return [rid for sc, rid in scored[:top] if sc >= thr]


def atomize(structure: Dict[str, Any]) -> Dict[str, Any]:
    items = structure["items"]
    atoms: List[Dict[str, Any]] = []
    transitions: List[Dict[str, Any]] = []

    # 1) atom dari item ber-ID
    for it in items:
        ctx_tokens = tokens(f"{it['title']} {it['description']} {' '.join(it['rules'])}")
        base = {
            "requirement_ids": [it["id"]], "source": it["id"], "item_type": it["type"],
            "item_title": it["title"], "module": it["title"], "ctx_tokens": ctx_tokens,
        }
        made = 0
        if it["description"] and it["rules"] and it["type"] != "NFR":
            atoms.append({**base, "kind": "flow", "params": {}, "text": it["description"]})
            made += 1
        subs = it.get("rule_subs") or []
        for i_r, rule in enumerate(it["rules"]):
            sub = subs[i_r] if i_r < len(subs) else ""
            for a in extract_rule_atoms(rule, ctx_title=it["title"], is_nfr=(it["type"] == "NFR")):
                atoms.append({**base, **a, "requirement_ids": list(base["requirement_ids"]),
                              "sub_title": sub})  # alur asal aturan -> Sub Module/Menu
                made += 1
        for e in extract_transitions(it.get("transition_lines", [])):
            transitions.append({**e, "ids": [it["id"]], "ctx": it["title"], "from_item": True})
        if made == 0 and not it.get("transition_lines"):
            atoms.append({**base, "kind": "flow", "params": {}, "text": it["title"] or it["id"]})

    atoms = merge_atoms(atoms)

    # 2) artefak (non-ID)
    ac_counter = 0
    edge_counter = 0
    for art in structure["artifacts"]:
        title = art["title"]
        lines = art["lines"]
        art_edges = extract_transitions(lines)
        decs = extract_decisions(lines)
        bullets = extract_bullets(lines)
        label = title or art["parent"]
        if art_edges:
            for e in art_edges:
                transitions.append({**e, "ids": [], "ctx": label, "from_item": False})
            continue
        if decs:
            note = ""
            for _l in lines:
                _t = re.sub(r"[*_`]", "", _l).strip()
                if re.match(r"(expected\s+(behavior|behaviour|outcome|result)|perilaku\s+yang\s+diharapkan)", _t, re.I):
                    note = _t
                    break
            ids = _guess_requirement_ids(" ".join([title] + [c["name"] for c in decs]), items, top=3, thr=0.2)
            atoms.append({
                "kind": "decision", "params": {"conditions": decs, "title": title, "note": note}, "text": f"Decision table: {title}",
                "requirement_ids": ids or [label], "source": f"DT:{title}", "item_type": "DT",
                "item_title": title, "module": title, "ctx_tokens": set(),
            })
            continue
        if _SKIP_TITLE.search(title) or _SKIP_TITLE.search(art["parent"] or "") and not (
                _EDGE_TITLE.search(title) or _ACCEPT_TITLE.search(title)):
            continue
        if _EDGE_TITLE.search(title) and bullets:
            for b in bullets:
                edge_counter += 1
                ids = _guess_requirement_ids(b, items, top=2, thr=0.2)
                atoms.append({
                    "kind": "edge", "params": {}, "text": b, "requirement_ids": ids or [f"EC-{edge_counter:02d}"],
                    "source": f"EC-{edge_counter:02d}", "item_type": "EC", "item_title": title, "module": title,
                    "ctx_tokens": set(),
                })
            continue
        if _ACCEPT_TITLE.search(title) and bullets:
            pre = []
            for b in bullets:
                ac_counter += 1
                pre.append({
                    "kind": "acceptance", "params": {}, "text": b, "requirement_ids": [f"AC-{ac_counter:02d}"],
                    "source": f"AC-{ac_counter:02d}", "item_type": "AC", "item_title": b, "module": title,
                    "ctx_tokens": tokens(b),
                })
            merged = merge_atoms(atoms + pre)
            # atom AC yang tidak ter-merge menjadi rule biasa
            for a in merged:
                if a.get("kind") == "acceptance":
                    a["kind"] = "rule"
                    a["technique"] = technique_for_text(a["text"])
            atoms = merged
            continue

    # 3) transisi -> atom (dedupe edge lintas sumber)
    edge_map: Dict[Tuple[str, str], Dict[str, Any]] = {}
    for e in transitions:
        key = (e["from"], e["to"])
        cur = edge_map.get(key)
        if not cur:
            edge_map[key] = {"from": e["from"], "to": e["to"], "note": e["note"], "ids": list(e["ids"]),
                             "labels": [e["ctx"]], "art_label": None if e["from_item"] else e["ctx"]}
        else:
            for i in e["ids"]:
                if i not in cur["ids"]:
                    cur["ids"].append(i)
            if e["note"] and not cur["note"]:
                cur["note"] = e["note"]
            if not e["from_item"] and not cur["art_label"]:
                cur["art_label"] = e["ctx"]
            cur["labels"].append(e["ctx"])
    parent: Dict[str, str] = {}

    def find(x):
        parent.setdefault(x, x)
        while parent[x] != x:
            parent[x] = parent[parent[x]]
            x = parent[x]
        return x

    for (a, b) in edge_map:
        parent[find(a)] = find(b)
    comp_label: Dict[str, str] = {}
    for (a, b), e in edge_map.items():
        r = find(a)
        if e["art_label"] and r not in comp_label:
            comp_label[r] = e["art_label"]
    for (a, b), e in edge_map.items():
        r = find(a)
        machine = comp_label.get(r) or e["labels"][0]
        e["machine"] = machine
        e["root"] = r
        ids = e["ids"] or _guess_requirement_ids(f"{machine} {e['note']}", items, top=1, thr=0.2) or [machine]
        atoms.append({
            "kind": "transition", "params": {"from": e["from"], "to": e["to"], "note": e["note"], "machine": machine},
            "text": f"{e['from']} -> {e['to']}" + (f" ({e['note']})" if e["note"] else ""),
            "requirement_ids": ids, "source": f"ST:{e['from']}>{e['to']}", "item_type": "ST",
            "item_title": machine, "module": machine, "ctx_tokens": set(),
        })
    # transisi tidak valid (diturunkan, diberi flag derived)
    comps: Dict[str, List[str]] = {}
    for (a, b), e in edge_map.items():
        comps.setdefault(find(a), [])
        for s in (a, b):
            if s not in comps[find(a)]:
                comps[find(a)].append(s)
    for root, states in comps.items():
        out_deg = {s: 0 for s in states}
        for (a, b) in edge_map:
            if find(a) == root:
                out_deg[a] += 1
        cands = []
        for (a, b) in list(edge_map):
            if find(a) == root and (b, a) not in edge_map:
                cands.append((b, a))                       # kebalikan transisi yang ada
        for s in states:
            if out_deg[s] == 0:
                for t in states:
                    if t != s and (s, t) not in edge_map and (s, t) not in cands:
                        cands.append((s, t))               # keluar dari state terminal
        machine = comp_label.get(root) or next(e["machine"] for (a, b), e in edge_map.items() if find(a) == root)
        for (a, b) in cands[:4]:
            ids = next((e["ids"] for (x, y), e in edge_map.items() if find(x) == root and e["ids"]), None) or [machine]
            atoms.append({
                "kind": "invalid_transition", "params": {"from": a, "to": b, "machine": machine},
                "text": f"{a} -> {b} (tidak didefinisikan di state model)", "requirement_ids": ids,
                "source": f"IT:{a}>{b}", "item_type": "ST", "item_title": machine, "module": machine,
                "ctx_tokens": set(), "derived": True,
            })

    for i, a in enumerate(atoms, 1):
        a["atom_id"] = f"A-{i:03d}"
        a.pop("ctx_tokens", None)
    return {"atoms": atoms}


def rule_atomizer_node(state: dict) -> dict:
    """LangGraph node: PRD -> atoms (+ requirements dict kompatibel)."""
    prd = state.get("prd_context", "")
    structure = parse_prd_markdown(prd)
    requirements = state.get("requirements")
    if not structure["items"]:
        # PRD tanpa ID terstruktur: fallback ke parser LLM milik pipeline lama
        from agents.requirement_parser_agent import parse_requirements
        requirements = requirements or parse_requirements(prd, state.get("prd_name", "prd"))
        structure = {"items": _items_from_requirements(requirements), "artifacts": structure["artifacts"],
                     "hints": structure["hints"], "module_name": structure.get("module_name", "General")}
    else:
        requirements = to_requirements_dict(structure)
    result = atomize(structure)
    atoms = result["atoms"]
    by_kind: Dict[str, int] = {}
    for a in atoms:
        by_kind[a["kind"]] = by_kind.get(a["kind"], 0) + 1
    ui.stage("atomize", f"{len(structure['items'])} item, {len(atoms)} atom")
    ui.event("atomizer", f"items={len(structure['items'])} atoms={len(atoms)} kinds={by_kind}")
    return {"requirements": requirements, "prd_structure": structure, "atoms": atoms, "hints": structure["hints"]}


def _items_from_requirements(requirements: Dict[str, Any]) -> List[Dict[str, Any]]:
    items = []
    for i, r in enumerate(requirements.get("requirements", [])):
        rid = str(r.get("id", f"REQ-{i + 1:03d}")).upper()
        rules = r.get("business_rules") or r.get("rules") or []
        items.append({"id": rid, "type": "NFR" if rid.startswith("NFR") else ("BR" if rid.startswith("BR") else "FR"),
                      "title": r.get("title", rid), "description": r.get("description", ""),
                      "rules": [str(x) for x in rules], "section": "", "order": i, "transition_lines": []})
    return items