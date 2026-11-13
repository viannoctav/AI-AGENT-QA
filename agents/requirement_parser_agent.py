import hashlib
import json
import re
from pathlib import Path


from tools.ai_config import ollama_settings

# Path untuk menyimpan cache
CACHE_DIR = Path("knowledge/cache")
CACHE_FILE = CACHE_DIR / "parsed_requirements_cache.json"

# ============================================================
# REQUIREMENT INVENTORY
# ============================================================

REQUIREMENT_ID_PATTERN = re.compile(
    r"\b(?:FR|NFR|BR)-\d+\b",
    re.IGNORECASE,
)


def _extract_requirement_inventory(prd_context: str):
    text = prd_context or ""
    ids = []
    seen = set()

    for match in REQUIREMENT_ID_PATTERN.finditer(text):
        requirement_id = match.group(0).upper()

        if requirement_id in seen:
            continue

        seen.add(requirement_id)
        ids.append(requirement_id)

    return ids


def _expected_type(requirement_id: str):
    if requirement_id.startswith("NFR-"):
        return "Non Functional"

    if requirement_id.startswith("BR-"):
        return "Business Rule"

    return "Functional"


def _build_batches(items, batch_size=6):
    return [
        items[index:index + batch_size]
        for index in range(0, len(items), batch_size)
    ]


# ============================================================
# JSON PARSING
# ============================================================

def _parse_json_response(content: str):
    raw = (content or "").strip()

    try:
        return json.loads(raw)

    except json.JSONDecodeError:
        pass

    fenced = re.fullmatch(
        r"```(?:json)?\s*(.*?)\s*```",
        raw,
        flags=re.IGNORECASE | re.DOTALL,
    )

    if fenced:
        return json.loads(fenced.group(1))

    raise ValueError(
        "LLM response bukan JSON valid."
    )


# ============================================================
# NORMALIZATION
# ============================================================

def _normalize_requirement(
    item,
    requirement_id
):
    if not isinstance(item, dict):
        raise ValueError(
            f"{requirement_id}: requirement bukan object."
        )

    actual_id = str(
        item.get("id", "")
    ).strip().upper()

    if actual_id != requirement_id:
        raise ValueError(
            f"Expected {requirement_id}, "
            f"received {actual_id or '<empty>'}"
        )

    expected_type = _expected_type(
        requirement_id
    )

    actual_type = str(
        item.get("type", "")
    ).strip()

    if actual_type != expected_type:
        # ⚠️ LLM classification mismatch - log but don't fail
        print(
            f"⚠️  {requirement_id}: LLM classified as '{actual_type}', "
            f"expected '{expected_type}' - using expected type."
        )
        # Continue with expected_type (from ID prefix)

    actor = item.get(
        "actor",
        []
    )

    if not isinstance(actor, list):
        actor = [actor]

    business_rules = item.get(
        "business_rules",
        []
    )

    if not isinstance(
        business_rules,
        list
    ):
        business_rules = [business_rules]

    acceptance_criteria = item.get(
        "acceptance_criteria",
        []
    )

    if not isinstance(
        acceptance_criteria,
        list
    ):
        acceptance_criteria = [
            acceptance_criteria
        ]

    return {
        "id": requirement_id,
        "type": expected_type,
        "actor": [
            str(value).strip()
            for value in actor
            if str(value).strip()
        ],
        "module": str(
            item.get(
                "module",
                ""
            )
        ).strip(),
        "title": str(
            item.get(
                "title",
                ""
            )
        ).strip(),
        "description": str(
            item.get(
                "description",
                ""
            )
        ).strip(),
        "business_rules": business_rules,
        "acceptance_criteria": [
            str(value).strip()
            for value in acceptance_criteria
            if str(value).strip()
        ],
    }


def _normalize_batch(
    result,
    expected_ids
):
    if not isinstance(
        result,
        dict
    ):
        raise ValueError(
            "LLM result harus object."
        )

    requirements = result.get(
        "requirements",
        []
    )

    if not isinstance(
        requirements,
        list
    ):
        raise ValueError(
            "'requirements' harus array."
        )

    by_id = {}

    for item in requirements:

        if not isinstance(
            item,
            dict
        ):
            continue

        requirement_id = str(
            item.get(
                "id",
                ""
            )
        ).strip().upper()

        if not requirement_id:
            continue

        if requirement_id in by_id:
            raise ValueError(
                "Duplicate requirement ID: "
                + requirement_id
            )

        by_id[
            requirement_id
        ] = item

    expected_set = set(
        expected_ids
    )

    actual_set = set(
        by_id
    )

    extra_ids = sorted(
        actual_set - expected_set
    )

    missing_ids = [
        item
        for item in expected_ids
        if item not in by_id
    ]

    if extra_ids:
        raise ValueError(
            "LLM menghasilkan ID "
            "di luar batch: "
            + ", ".join(extra_ids)
        )

    if missing_ids:
        raise ValueError(
            "Requirement hilang pada batch: "
            + ", ".join(missing_ids)
        )

    return [
        _normalize_requirement(
            by_id[requirement_id],
            requirement_id,
        )
        for requirement_id in expected_ids
    ]


# ============================================================
# DETERMINISTIC SOURCE CLEANUP
# ============================================================

def _extract_global_module(prd_context):
    for line in (prd_context or "").splitlines():
        line = line.strip()

        if not line.startswith("# "):
            continue

        module = line[2:].strip()

        module = re.sub(
            r"\s+PRD\s*$",
            "",
            module,
            flags=re.IGNORECASE
        ).strip()

        if module:
            return module

    return ""


def _extract_global_actors(prd_context):
    text = prd_context or ""
    lines = text.splitlines()

    actors = []
    inside_actors = False

    for line in lines:
        stripped = line.strip()

        if re.match(
            r"^##+\s+Actors\b",
            stripped,
            flags=re.IGNORECASE
        ):
            inside_actors = True
            continue

        if inside_actors and re.match(
            r"^##+\s+",
            stripped
        ):
            break

        if inside_actors:
            match = re.match(
                r"^[-*]\s+(.+?)\s*$",
                stripped
            )

            if match:
                actor = match.group(1).strip()

                if actor and actor not in actors:
                    actors.append(actor)

    return actors


def _source_title(requirement_id, source_text):
    text = source_text or ""

    heading = re.search(
        rf"^###\s+{re.escape(requirement_id)}\s+[—-]\s+(.+?)\s*$",
        text,
        flags=re.IGNORECASE | re.MULTILINE
    )

    if heading:
        return heading.group(1).strip()

    br_match = re.search(
        rf"^{re.escape(requirement_id)}\s*:\s*(.+?)\s*$",
        text,
        flags=re.IGNORECASE | re.MULTILINE
    )

    if br_match:
        return br_match.group(1).strip()

    return ""


def _clean_requirement_value(value):
    if isinstance(value, str):
        return value.strip()

    if isinstance(value, dict):

        for key in (
            "description",
            "rule",
            "criteria",
            "title",
            "source_text"
        ):
            candidate = value.get(key)

            if isinstance(candidate, str):
                candidate = candidate.strip()

                if candidate:
                    return candidate

        return json.dumps(
            value,
            ensure_ascii=False
        )

    return str(value).strip()


def _clean_requirement_list(values):
    if not isinstance(values, list):
        values = [values]

    cleaned = []

    for value in values:
        text = _clean_requirement_value(value)

        if text and text not in cleaned:
            cleaned.append(text)

    return cleaned


def _clean_parsed_requirement(
    item,
    requirement_id,
    source_by_id,
    prd_context
):
    source_text = source_by_id.get(
        requirement_id,
        ""
    )

    global_module = _extract_global_module(
        prd_context
    )

    global_actors = _extract_global_actors(
        prd_context
    )

    source_title = _source_title(
        requirement_id,
        source_text
    )

    inferred_actors = [
        actor
        for actor in global_actors
        if re.search(
            rf"\b{re.escape(actor)}\b",
            source_text,
            flags=re.IGNORECASE
        )
    ]

    actor_values = inferred_actors

    if not actor_values:
        actor_values = _clean_requirement_list(
            item.get("actor", [])
        )

    title = (
        source_title
        or str(
            item.get(
                "title",
                ""
            )
        ).strip()
    )

    module = (
        global_module
        or str(
            item.get(
                "module",
                ""
            )
        ).strip()
    )

    description = str(
        item.get(
            "description",
            ""
        )
    ).strip()

    if not description:
        description = source_text.strip()

    return {
        "id": requirement_id,
        "type": _expected_type(
            requirement_id
        ),
        "actor": actor_values,
        "module": module,
        "title": title,
        "description": description,
        "business_rules": _clean_requirement_list(
            item.get(
                "business_rules",
                []
            )
        ),
        "acceptance_criteria": _clean_requirement_list(
            item.get(
                "acceptance_criteria",
                []
            )
        ),
        "source_text": source_text.strip()
    }


# ============================================================
# EXTRACT SOURCE PER REQUIREMENT
# ============================================================

def _extract_source_sections(prd_context: str):
    text = prd_context or ""
    lines = text.splitlines()

    sections = {}

    current_id = None
    current_lines = []

    heading_pattern = re.compile(
        r"^###\s+((?:FR|NFR)-\d+)\s+[—-]\s+(.+?)\s*$",
        re.IGNORECASE,
    )

    for line in lines:

        heading = heading_pattern.match(
            line.strip()
        )

        if heading:

            if current_id:
                sections[current_id] = (
                    "\n".join(
                        current_lines
                    ).strip()
                )

            current_id = (
                heading.group(1)
                .upper()
            )

            current_lines = [line]

            continue

        if current_id:

            if re.match(
                r"^##\s+",
                line.strip()
            ):
                sections[current_id] = (
                    "\n".join(
                        current_lines
                    ).strip()
                )

                current_id = None
                current_lines = []

            else:
                current_lines.append(line)

    if current_id:
        sections[current_id] = (
            "\n".join(
                current_lines
            ).strip()
        )

    # Business Rule table
    br_pattern = re.compile(
        r"\|\s*(BR-\d+)\s*\|\s*(.*?)\s*\|",
        re.IGNORECASE,
    )

    for match in br_pattern.finditer(text):

        requirement_id = (
            match.group(1)
            .upper()
        )

        rule_text = (
            match.group(2)
            .strip()
        )

        sections[requirement_id] = (
            f"{requirement_id}: {rule_text}"
        )

    return sections


# ============================================================
# PROMPT
# ============================================================

def _build_batch_prompt(
    source_by_id,
    expected_ids,
):
    inventory = [
        {
            "id": requirement_id,
            "type": _expected_type(
                requirement_id
            ),
        }
        for requirement_id in expected_ids
    ]

    source_payload = [
        {
            "id": requirement_id,
            "source_text": source_by_id.get(
                requirement_id,
                "",
            ),
        }
        for requirement_id in expected_ids
    ]

    return f"""
Kamu adalah Senior Business Analyst dan QA Architect.

Tugas kamu adalah mengekstrak requirement
berdasarkan SOURCE EXCERPT yang diberikan.

PRD adalah SATU-SATUNYA source of truth.

==================================================
REQUIREMENT INVENTORY WAJIB
==================================================

HANYA ID berikut yang boleh dikembalikan:

{json.dumps(
    inventory,
    indent=2,
    ensure_ascii=False,
)}

Jangan mengembalikan ID lain.

==================================================
SOURCE EXCERPT
==================================================

{json.dumps(
    source_payload,
    indent=2,
    ensure_ascii=False,
)}

==================================================
ATURAN WAJIB
==================================================

1. Kembalikan tepat satu object untuk setiap ID.

2. Jangan menghilangkan ID.

3. Jangan menambah ID.

4. Jangan menukar isi antar requirement.

5. Untuk setiap ID gunakan HANYA source_text
   dengan ID yang sama.

6. Jangan mengambil isi dari requirement lain.

7. Jangan membuat business rule baru.

8. Jangan membuat acceptance criteria baru.

9. Jangan mengubah:
   - angka
   - boundary
   - state
   - status
   - timeout
   - expiry
   - retry
   - dependency
   - business rule

10. Actor harus berasal dari requirement yang sesuai.

11. Module harus berasal dari requirement yang sesuai.

12. Jangan membawa fitur, istilah, atau domain yang TIDAK tertulis di PRD ini (mis. dari proyek lain).

13. FR = Functional.

14. NFR = Non Functional.

15. BR = Business Rule.

16. Output hanya JSON valid.

==================================================
SCHEMA
==================================================

{{
  "requirements": [
    {{
      "id": "",
      "type": "Functional | Non Functional | Business Rule",
      "actor": [],
      "module": "",
      "title": "",
      "description": "",
      "business_rules": [],
      "acceptance_criteria": []
    }}
  ]
}}

==================================================
FINAL CHECK
==================================================

Jumlah object harus:

{len(expected_ids)}

ID yang diperbolehkan HANYA:

{json.dumps(
    expected_ids,
    ensure_ascii=False
)}
"""


# ============================================================
# BATCH LLM CALL
# ============================================================

def _parse_batch_with_retry(
    client,
    model,
    source_by_id,
    expected_ids,
    max_attempts=3,
):
    last_error = None

    for attempt in range(
        1,
        max_attempts + 1
    ):

        try:

            prompt = _build_batch_prompt(
                source_by_id,
                expected_ids,
            )

            if attempt > 1:
                prompt += f"""

RETRY #{attempt}

Respons sebelumnya gagal validasi.

Fokus hanya pada ID batch ini.

Kembalikan semua ID tepat satu kali.
Jangan mengubah schema.
"""

            response = client.chat(
                model=model,
                messages=[
                    {
                        "role": "user",
                        "content": prompt,
                    }
                ],
                format="json",
            )

            result = _parse_json_response(
                response.message.content
            )

            return _normalize_batch(
                result,
                expected_ids,
            )

        except Exception as exc:

            last_error = exc

    raise RuntimeError(
        "Requirement Parser gagal "
        "memproses batch "
        + ", ".join(expected_ids)
        + f". Reason: {last_error}"
    )


# ============================================================
# PUBLIC API
# ============================================================

def parse_requirements(
    prd_context: str,
    prd_name: str = ""
):
    prd_text = str(prd_context or "").strip()
    current_hash = hashlib.sha256(prd_text.encode("utf-8")).hexdigest()

    # Cache per-PRD supaya ganti-ganti PRD tidak saling menimpa
    if prd_name:
        slug = re.sub(r"[^A-Za-z0-9_-]+", "_", Path(str(prd_name)).stem).strip("_") or "prd"
        cache_file = CACHE_DIR / f"parsed_requirements_{slug}.json"
    else:
        cache_file = CACHE_FILE

    # 1. CEK CACHE BERDASARKAN HASH PRD (cache per-PRD, lalu cache lama sebagai fallback)
    for candidate in (cache_file, CACHE_FILE):
        if not candidate.exists():
            continue
        try:
            cache_data = json.loads(candidate.read_text(encoding="utf-8"))
            if cache_data.get("prd_hash") == current_hash:
                print(
                    "\n⚡ [CACHE HIT] Isi PRD tidak berubah. Menggunakan hasil Requirement Parser sebelumnya (Instan).\n"
                )
                return cache_data.get("data")
        except Exception:
            pass

    print("\n🔄 [CACHE MISS] PRD baru atau terdapat perubahan. Menjalankan Requirement Parser LLM...\n")

    settings = ollama_settings()

    inventory = _extract_requirement_inventory(prd_text)

    source_sections = _extract_source_sections(prd_text)

    missing_source = [
        requirement_id
        for requirement_id in inventory
        if not source_sections.get(requirement_id)
    ]

    if missing_source:
        raise RuntimeError(
            "Source requirement tidak ditemukan: " + ", ".join(missing_source)
        )

    if not inventory:
        raise RuntimeError("Tidak ditemukan requirement ID (FR/NFR/BR) pada PRD.")

    from tools import ai_source  # AI di laptop ini atau Server AI bersama
    client = ai_source.client()

    batches = _build_batches(
        inventory,
        batch_size=6,
    )

    parsed_requirements = []

    for batch_number, expected_ids in enumerate(
        batches,
        start=1,
    ):
        print(
            "Requirement Parser batch "
            f"{batch_number}/{len(batches)}: " + ", ".join(expected_ids)
        )

        parsed_requirements.extend(
            _parse_batch_with_retry(
                client=client,
                model=settings["generation_model"],
                source_by_id=source_sections,
                expected_ids=expected_ids,
            )
        )

    parsed_requirements = [
        _clean_parsed_requirement(
            item=item,
            requirement_id=item["id"],
            source_by_id=source_sections,
            prd_context=prd_text,
        )
        for item in parsed_requirements
    ]

    parsed_ids = [item["id"] for item in parsed_requirements]

    if parsed_ids != inventory:
        raise RuntimeError(
            "Requirement Parser menghasilkan inventory yang tidak sama dengan PRD source.\n"
            f"Expected: {inventory}\n"
            f"Actual: {parsed_ids}"
        )

    result = {
        "requirements": parsed_requirements
    }

    # 2. SIMPAN HASIL BATCH PARSING KE FILE CACHE
    try:
        CACHE_DIR.mkdir(parents=True, exist_ok=True)
        cache_file.write_text(
            json.dumps(
                {
                    "prd_hash": current_hash,
                    "data": result,
                },
                indent=2,
                ensure_ascii=False,
            ),
            encoding="utf-8",
        )
    except Exception as exc:
        print(f"⚠️ Gagal menyimpan cache requirements: {exc}")

    return result