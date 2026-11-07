from typing import Any, Dict, List, TypedDict


class TCState(TypedDict, total=False):
    prd_context: str
    prd_name: str
    requirements: Dict[str, Any]
    submodule_queue: List[Dict[str, Any]]
    current_submodule: Dict[str, Any]
    generated_tc: Dict[str, List[Dict[str, Any]]]
    valid_tcs: List[Dict[str, Any]]
    invalid_tcs: List[Dict[str, Any]]
    draft_tcs: List[Dict[str, Any]]
    retry_count: int
    eval_status: str
    eval_feedback: str
    sliced_prd: str
    sliced_requirements: str


class TCStateV2(TCState, total=False):
    goal: str
    prd_path: str
    prd_structure: Dict[str, Any]
    atoms: List[Dict[str, Any]]
    hints: Dict[str, str]
    obligations: List[Dict[str, Any]]
    ob_queue: List[Dict[str, Any]]
    current_batch: List[Dict[str, Any]]
    batch_attempt: int
    batch_feedback: Dict[str, str]
    draft_map: Dict[str, Dict[str, Any]]
    accepted_tcs: List[Dict[str, Any]]
    final_tcs: List[Dict[str, Any]]
    report: Dict[str, Any]
    output_path: str
    output_dir: str
    final_v2_tcs: List[Dict[str, Any]]
    v2_report: Dict[str, Any]
    dropped_obs: List[Dict[str, Any]]
    dedup_removed: List[Dict[str, Any]]
    judge_log: List[Dict[str, Any]]