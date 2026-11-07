import json


def _clean_rule(rule) -> str:
    """Business rule dari parser kadang berupa string JSON {"text": "..."}; ambil teksnya saja."""
    if isinstance(rule, dict):
        return str(rule.get("text", rule))
    text = str(rule)
    if text.lstrip().startswith("{"):
        try:
            return str(json.loads(text).get("text", text))
        except Exception:
            return text
    return text


def slice_context_for_submodule(
    submodule_data: dict, full_requirements: dict, full_prd_text: str
) -> tuple[str, list]:
    """Mengisolasi konteks PRD & Requirements khusus untuk satu sub-modul bisnis."""
    sub_req_ids = [
        str(rid).upper()
        for rid in submodule_data.get("requirement_ids", [])
    ]

    all_reqs = (
        (full_requirements or {}).get("requirements", [])
        if isinstance(full_requirements, dict)
        else []
    )
    sliced_reqs = []

    for req in all_reqs:
        if isinstance(req, dict) and str(req.get("id")).upper() in sub_req_ids:
            sliced_reqs.append({
                "id": req.get("id"),
                "title": req.get("title"),
                "description": req.get("description"),
                "business_rules": [_clean_rule(b) for b in req.get("business_rules", [])],
                "acceptance_criteria": req.get("acceptance_criteria", []),
            })

    sliced_prd_lines = []
    if sliced_reqs:
        sub_name = submodule_data.get("submodule_name", "General")
        sliced_prd_lines.append(f"=== SUB-MODULE: {sub_name} ===")
        for sreq in sliced_reqs:
            sliced_prd_lines.append(
                f"\n[{sreq['id']}] {sreq['title']}: {sreq['description']}"
            )
            for br in sreq.get("business_rules", []):
                sliced_prd_lines.append(f"  - Rule: {br}")
            for ac in sreq.get("acceptance_criteria", []):
                sliced_prd_lines.append(f"  - AC: {ac}")
    else:
        sliced_prd_lines.append(full_prd_text)

    return "\n".join(sliced_prd_lines), sliced_reqs