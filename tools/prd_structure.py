# tools/prd_structure.py
"""
Parser struktur PRD generik (tanpa LLM, tanpa hardcode domain).

Output:
  items      : requirement ber-ID (heading "FR-001 — Judul" atau baris tabel "| BR-001 | aturan |")
  artifacts  : section TANPA ID (state model, decision table, edge case, acceptance criteria, ...)
  hints      : contoh data uji dari section "Test Data Guidance" (label -> nilai)

Semua pola bersifat struktural (heading, bullet, tabel, panah transisi), bukan nama domain.
"""

import re
from typing import Any, Dict, List, Optional, Tuple

ID_RE = r"[A-Z][A-Z0-9]{1,5}-\d{1,4}"
_HEADING = re.compile(r"^(#{1,6})\s+(.*?)\s*#*\s*$")
_ID_HEADING = re.compile(rf"^(?P<id>{ID_RE})\s*(?:[\u2014\u2013:\-]+)\s*(?P<title>.+)$")
_BULLET = re.compile(r"^(\s*)(?:[-*\u2022]|\d+[.)])\s+(.*)$")
_RULES_LABEL = re.compile(r"^\**\s*(rules?|aturan|ketentuan|conditions?)\s*\**\s*:\s*\**$", re.IGNORECASE)
_SECTION_NUM = re.compile(r"^\d+(?:\.\d+)*\.?\s+")
_STATE_TOKEN = re.compile(r"^[A-Z][A-Z0-9_]{2,}$")
_STATE_WORDS = re.compile(r"^[A-Za-z][A-Za-z0-9_]*(?: [A-Za-z0-9_]+){0,2}$")


def strip_md(text: str) -> str:
    t = str(text or "")
    t = t.replace("**", "").replace("__", "").replace("`", "")
    return re.sub(r"\s+", " ", t).strip()


def item_type(rid: str) -> str:
    rid = str(rid).upper()
    if rid.startswith("NFR"):
        return "NFR"
    if rid.startswith("BR"):
        return "BR"
    return "FR"


# ---------------------------------------------------------------------------
# Transisi state: "A → B → C", "→ D" (lanjutan baris sebelumnya), "A -> B (catatan)"
# ---------------------------------------------------------------------------
def _parse_state_part(part: str) -> Optional[Tuple[str, str]]:
    part = part.strip()
    m = re.match(r"^(.*?)\s*(?:\((.*)\))?\s*$", part)
    if not m:
        return None
    name, note = m.group(1).strip(), (m.group(2) or "").strip()
    if not name:
        return None
    if _STATE_TOKEN.match(name) or (_STATE_WORDS.match(name) and len(name) <= 30):
        return name, note
    return None


def extract_transitions(lines: List[str]) -> List[Dict[str, str]]:
    edges: List[Dict[str, str]] = []
    prev: Optional[str] = None
    for raw in lines:
        s = raw.strip()
        if not s:
            continue  # baris kosong tidak memutus rantai panah
        t = strip_md(s).replace("->", "\u2192").replace("=>", "\u2192")
        t = re.sub(r"^[-*\u2022]\s+", "", t)
        if "\u2192" not in t:
            m = re.fullmatch(r"([A-Z][A-Z0-9_]{2,})(?:\s*\((.*)\))?", t)
            prev = m.group(1) if m else None
            continue
        parts = [p.strip() for p in t.split("\u2192")]
        states: List[Tuple[str, str]] = []
        ok = True
        for i, p in enumerate(parts):
            if p == "":
                if i == 0 and prev:
                    states.append((prev, ""))
                    continue
                ok = False
                break
            parsed = _parse_state_part(p)
            if not parsed:
                ok = False
                break
            states.append(parsed)
        if not ok or len(states) < 2:
            prev = None
            continue
        for i in range(len(states) - 1):
            edges.append({"from": states[i][0], "to": states[i + 1][0], "note": states[i + 1][1]})
        prev = states[-1][0]
    return edges


# ---------------------------------------------------------------------------
# Decision table: bullet "Nama Kondisi = Nilai A / Nilai B / Nilai C"
# ---------------------------------------------------------------------------
def extract_decisions(lines: List[str]) -> List[Dict[str, Any]]:
    """Kondisi decision table. Mendukung: "Nama = A / B", "Nama a / b", dan "Nama" (tanpa nilai,
    hanya bila section punya label "Conditions:")."""
    has_label = any(re.match(r"^\**\s*(conditions?|kondisi)\s*\**\s*:", strip_md(l), re.IGNORECASE) for l in lines)
    conds = []
    for raw in lines:
        m = _BULLET.match(raw)
        if not m:
            continue
        body = strip_md(m.group(2)).rstrip(".")
        dm = re.match(r"^([^=]{2,60}?)\s*=\s*(.+)$", body)
        if dm:
            values = [v.strip() for v in re.split(r"\s*/\s*|\s*\|\s*", dm.group(2)) if v.strip()]
            if len(values) >= 2:
                conds.append({"name": dm.group(1).strip(), "values": values})
            continue
        if not has_label:
            continue
        if "/" in body:
            parts = [x.strip() for x in body.split("/") if x.strip()]
            if len(parts) >= 2:
                words = parts[0].split()
                name = " ".join(words[:-1]) if len(words) >= 2 else parts[0]
                values = ([words[-1]] if len(words) >= 2 else [parts[0]]) + parts[1:]
                conds.append({"name": name, "values": values if len(values) >= 2 else ["memenuhi", "tidak memenuhi"],
                              **({} if len(values) >= 2 else {"no_values": True})})
            continue
        if 2 <= len(body) <= 60 and not body.endswith(":"):
            # PRD tidak menyebut nilainya -> diisi AI dari isi PRD (infer_decision_values), ini hanya cadangan
            conds.append({"name": body, "values": ["memenuhi / valid", "tidak memenuhi / invalid"], "no_values": True})
    # nama kondisi kembar dalam satu tabel ("Coupon present / absent" dan "Coupon active / expired") -> diberi
    # pembeda dari nilainya, supaya Test Data dan analisis nilai tidak tertukar
    names = [c["name"].lower() for c in conds]
    for c in conds:
        if names.count(c["name"].lower()) > 1 and not c.get("no_values"):
            c["name"] = f"{c['name']} ({' / '.join(map(str, c['values']))})"
    return conds if len(conds) >= 2 else []


def extract_bullets(lines: List[str]) -> List[str]:
    out: List[str] = []
    for raw in lines:
        m = _BULLET.match(raw)
        if m:
            out.append(strip_md(m.group(2)))
        elif out and raw.startswith("  ") and raw.strip():
            out[-1] = out[-1] + " " + strip_md(raw)
    return out


def extract_hints(lines: List[str]) -> Dict[str, str]:
    hints: Dict[str, str] = {}
    for raw in lines:
        m = re.match(r"^\s*(?:[-*\u2022]\s*)?([^:`]{2,40}?)\s*:\s*[^`]*?`([^`]+)`", raw)
        if m:
            hints[strip_md(m.group(1)).lower()] = m.group(2).strip()
    return hints


# ---------------------------------------------------------------------------
# Tabel
# ---------------------------------------------------------------------------
def _table_rows(lines: List[str]) -> List[List[str]]:
    rows = []
    for ln in lines:
        s = ln.strip()
        if not s.startswith("|"):
            continue
        cells = [strip_md(c) for c in s.strip("|").split("|")]
        if all(re.fullmatch(r":?-{2,}:?", c) or c == "" for c in cells):
            continue
        rows.append(cells)
    return rows


# ---------------------------------------------------------------------------
# Item ber-ID
# ---------------------------------------------------------------------------
def _is_transition_line(line: str) -> bool:
    t = strip_md(line).replace("->", "\u2192")
    return "\u2192" in t and len(t) < 160


_SUBHEAD = re.compile(r"^\*\*(.+?)\*\*\s*$")
_AC_LABEL = re.compile(r"^[*_\s]*acceptance criteria[*_\s:]*$", re.IGNORECASE)
# baris miring utuh (*...*) = catatan konteks, mis. urutan layar pada PRD dari desain: bukan kebutuhan yang diuji
_NOTE_LINE = re.compile(r"^\*[^*].*[^*]\*$")


def _parse_item_body(lines: List[str]) -> Dict[str, Any]:
    desc_lines: List[str] = []
    rules: List[str] = []
    rule_subs: List[str] = []
    acceptance: List[str] = []
    transition_lines: List[str] = []
    in_table = False
    last_bullet = False
    sub = ""        # sub-judul alur di dalam FR -> jadi Sub Module/Menu di test case
    in_ac = False   # daftar Acceptance Criteria: ringkasan aturan di atasnya, jangan dihitung dua kali
    for raw in lines:
        s = raw.rstrip()
        if not s.strip():
            last_bullet = False
            continue
        if s.strip().startswith("|"):
            in_table = True
            continue
        if _is_transition_line(s) or re.fullmatch(r"\s*`[A-Z][A-Z0-9_]{2,}`\s*", s):
            transition_lines.append(s)
            continue
        if _NOTE_LINE.match(s.strip()):
            last_bullet = False
            continue
        if _AC_LABEL.match(s.strip()):
            in_ac, last_bullet = True, False
            continue
        sh = _SUBHEAD.match(s.strip())
        if sh and not _RULES_LABEL.match(strip_md(s)):
            sub, in_ac, last_bullet = strip_md(sh.group(1)), False, False
            continue
        if _RULES_LABEL.match(strip_md(s)):
            sub, in_ac, last_bullet = "", False, False
            continue
        m = _BULLET.match(s)
        if m:
            if in_ac:
                acceptance.append(strip_md(m.group(2)))
                last_bullet = False
                continue
            rules.append(strip_md(m.group(2)))
            rule_subs.append(sub)
            last_bullet = True
            continue
        if last_bullet and s.startswith("  "):
            rules[-1] = rules[-1] + " " + strip_md(s)
            continue
        label = strip_md(s)
        if label.endswith(":") and len(label) <= 80:
            last_bullet = False
            continue  # label seperti "Supported states:" bukan aturan
        desc_lines.append(label)
        last_bullet = False
    return {
        "description": " ".join(desc_lines).strip(),
        "rules": rules,
        "rule_subs": rule_subs,
        "acceptance": acceptance,
        "transition_lines": transition_lines,
        "has_table": in_table,
    }


def _split_sentences(text: str) -> List[str]:
    parts = re.split(r"(?<=[.!?])\s+(?=[A-Z])", text.strip())
    return [p.strip() for p in parts if p.strip()]


def parse_prd_markdown(text: str) -> Dict[str, Any]:
    lines = str(text or "").replace("\r", "").split("\n")

    # 1) pecah jadi section
    sections: List[Dict[str, Any]] = []
    stack: List[Tuple[int, str]] = []
    cur: Optional[Dict[str, Any]] = None
    in_code = False
    for ln in lines:
        if ln.strip().startswith("```"):
            in_code = not in_code
            if cur is not None:
                cur["lines"].append(ln)
            continue
        m = None if in_code else _HEADING.match(ln)
        if m:
            level = len(m.group(1))
            raw_title = strip_md(m.group(2))
            title_nonum = _SECTION_NUM.sub("", raw_title)
            idm = _ID_HEADING.match(title_nonum)
            while stack and stack[-1][0] >= level:
                stack.pop()
            parent = stack[-1][1] if stack else ""
            title = idm.group("title").strip() if idm else title_nonum
            stack.append((level, title))
            cur = {
                "level": level, "title": title, "id": idm.group("id") if idm else None,
                "parent": parent, "lines": [],
            }
            sections.append(cur)
        else:
            if cur is None:
                cur = {"level": 0, "title": "", "id": None, "parent": "", "lines": []}
                sections.append(cur)
            cur["lines"].append(ln)

    items: List[Dict[str, Any]] = []
    artifacts: List[Dict[str, Any]] = []
    hints: Dict[str, str] = {}
    seen_ids = set()

    def add_item(rid, title, description, rules, section, transition_lines=None, rule_subs=None):
        rid = rid.upper()
        if rid in seen_ids:
            return
        seen_ids.add(rid)
        items.append({
            "id": rid, "type": item_type(rid), "title": title, "description": description,
            "rules": rules, "section": section, "order": len(items),
            "transition_lines": transition_lines or [],
            "rule_subs": list(rule_subs or []),  # sub-judul alur per aturan (Sub Module/Menu)
        })

    for sec in sections:
        body = sec["lines"]
        if sec["id"]:
            parsed = _parse_item_body(body)
            rules = parsed["rules"]
            desc = parsed["description"]
            if not rules and desc:
                sents = _split_sentences(desc)
                if len(sents) >= 1:
                    rules, desc = sents, ""
            add_item(sec["id"], sec["title"], desc, rules, sec["parent"], parsed["transition_lines"],
                     parsed.get("rule_subs"))
            continue

        # tabel dengan ID di kolom pertama -> item
        rows = _table_rows(body)
        table_items = 0
        for cells in rows:
            if cells and re.fullmatch(ID_RE, cells[0]) and len(cells) >= 2:
                rule_text = " - ".join(c for c in cells[1:] if c)
                add_item(cells[0], rule_text[:70], "", [rule_text], sec["title"] or sec["parent"])
                table_items += 1

        content = [l for l in body if l.strip() and not l.strip().startswith("|")]
        if not content:
            continue
        title_l = sec["title"].lower()
        if re.search(r"test data|data uji|sample data|contoh data", title_l):
            hints.update(extract_hints(body))
        artifacts.append({
            "title": sec["title"], "parent": sec["parent"], "level": sec["level"],
            "lines": body, "order": len(artifacts),
        })

    return {"items": items, "artifacts": artifacts, "hints": hints, "module_name": extract_module_name(lines)}


_META_MODULE = re.compile(r"^\s*[-*]?\s*\**\s*(module|modul|menu|feature|fitur)\s*\**\s*:\s*\**\s*(.+?)\s*$", re.I)


def extract_module_name(lines: List[str]) -> str:
    """Nama modul/menu PRD untuk kolom Module/Menu.
    Urutan: baris metadata "**Module:** X" di awal dokumen -> judul H1 tanpa awalan "PRD -"."""
    for ln in lines[:60]:
        m = _META_MODULE.match(strip_md(ln) if "**" not in ln else ln.replace("**", ""))
        if m and 2 <= len(m.group(2).strip()) <= 80:
            return strip_md(m.group(2)).rstrip(".")
    for ln in lines[:20]:
        m = _HEADING.match(ln)
        if m and len(m.group(1)) == 1:
            t = strip_md(m.group(2))
            t = re.sub(r"^(PRD|Product Requirements? Document)\s*[\u2014\u2013:\-]*\s*", "", t, flags=re.I)
            return t.strip() or "General"
    return "General"


def to_requirements_dict(structure: Dict[str, Any]) -> Dict[str, Any]:
    """Bentuk kompatibel dengan dict `requirements` milik pipeline lama."""
    reqs = []
    for it in structure.get("items", []):
        reqs.append({
            "id": it["id"], "type": it["type"], "title": it["title"],
            "description": it["description"], "business_rules": list(it["rules"]),
        })
    return {"requirements": reqs}
