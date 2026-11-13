import json
import re
from typing import Any, Callable, Dict, List, Optional

from tools.ai_config import ROOT_DIR, ollama_settings
from tools.ui import ui


CONFIG_PATH = ROOT_DIR / "configs" / "ai.json"
_DEFAULTS: Dict[str, Any] = {
    "batch_size": 5, "max_attempts": 2, "judge_enabled": True, "generation_model": None,
    "judge_model": None, "num_predict": 3500, "temperature": 0.2, "judge_batch": 6,
    "max_obligations": None, "output_suffix": "_v2",
    "dedup": True, "dedup_threshold": 0.95, "num_ctx": 8192, "think": False, "judge_scope": "auto", "judge_timing": "akhir", "auto_model": "", "auto_model_kinds": ["decision", "edge", "whitespace"],
    "priority_rule": {"Positive": "High", "Negative": "Medium"},
}

# Dapat di-override (test offline): fungsi dengan signature ollama.chat
CHAT_FN: Optional[Callable[..., Any]] = None
_NO_THINK: set = set()  # model yang menolak parameter think


_OVERRIDES: Dict[str, Any] = {}


def set_overrides(values: Optional[Dict[str, Any]]) -> None:
    """Pengaturan khusus satu run (dipakai run.py --cap/--no-judge dan dashboard). Tidak mengubah ai.json."""
    _OVERRIDES.clear()
    _OVERRIDES.update(values or {})


def settings() -> Dict[str, Any]:
    """Default + bagian "v2" dari configs/ai.json (kunci v2 yang tidak ada memakai default)."""
    cfg = dict(_DEFAULTS)
    try:
        data = json.loads(CONFIG_PATH.read_text(encoding="utf-8"))
        v2 = data.get("v2") if isinstance(data.get("v2"), dict) else {}
        cfg.update(v2)
    except Exception as e:
        ui.event("llm", f"gagal membaca {CONFIG_PATH.name}: {e}", "red")
    cfg.update(_OVERRIDES)
    return cfg


def generation_model() -> str:
    cfg = settings()
    o = ollama_settings()
    return cfg.get("generation_model") or o["generation_model"]


def auto_model() -> str:
    """Model untuk obligation berpolaritas TIDAK pasti (decision/edge/flow). Kosong -> sama dengan generation_model."""
    return settings().get("auto_model") or ""


def is_heavy(ob) -> bool:
    """Obligation yang hasilnya paling bergantung pada penalaran (decision/edge/whitespace berpolaritas Auto)."""
    kinds = settings().get("auto_model_kinds") or ["decision", "edge", "whitespace"]
    return bool(auto_model()) and ob.get("polarity") == "Auto" and ob.get("kind") in kinds


def model_for(batch) -> str:
    """Batch yang seluruhnya 'heavy' memakai auto_model (bila diset), selain itu generation_model."""
    if batch and all(is_heavy(o) for o in batch):
        return auto_model()
    return generation_model()


def judge_model() -> str:
    cfg = settings()
    o = ollama_settings()
    return cfg.get("judge_model") or o.get("evaluator_model") or o["generation_model"]


def _get_chat():
    if CHAT_FN is not None:
        return CHAT_FN
    from ollama import Client  # import lambat agar modul bisa dites tanpa ollama
    # batas waktu per panggilan: AI yang macet (atau koneksi putus) tidak menahan proses berjam-jam,
    # panggilan dicoba ulang. Panggilan normal di laptop CPU 1-5 menit.
    timeout = float(settings().get("call_timeout_sec") or 900)
    host = ollama_settings().get("base_url") or ollama_settings().get("host") or None
    try:
        return Client(host=host, timeout=timeout).chat
    except Exception:
        from ollama import chat
        return chat


def _content(resp: Any) -> str:
    try:
        return resp["message"]["content"]
    except Exception:
        return getattr(getattr(resp, "message", None), "content", "") or ""


def parse_json_loose(text: str) -> Optional[Any]:
    if not text:
        return None
    t = text.strip()
    t = re.sub(r"^```(?:json)?\s*|\s*```$", "", t)
    for cand in (t, t[t.find("{"): t.rfind("}") + 1] if "{" in t else ""):
        if not cand:
            continue
        for attempt in (cand, re.sub(r",\s*([}\]])", r"\1", cand)):
            try:
                return json.loads(attempt)
            except Exception:
                continue
    return None


def chat_json(model: str, system: str, prompt: str, *, temperature: Optional[float] = None,
              num_predict: Optional[int] = None, retries: int = 2, images: Optional[list] = None) -> Optional[Any]:
    cfg = settings()
    opts_base = {
        "temperature": cfg["temperature"] if temperature is None else temperature,
        "num_predict": num_predict or cfg["num_predict"], "top_p": 0.9, "repeat_penalty": 1.1,
    }
    if cfg.get("num_ctx"):
        opts_base["num_ctx"] = int(cfg["num_ctx"])  # default Ollama di mesin CPU-only = 4096 -> prompt bisa terpotong diam-diam
    chat = _get_chat()
    for i in range(retries + 1):
        opts = dict(opts_base)
        opts["temperature"] = min(0.7, opts["temperature"] + 0.15 * i)
        user = {"role": "user", "content": prompt}
        if images:  # model yang bisa melihat gambar (mis. gemma4): path file gambar
            user["images"] = [str(x) for x in images]
        kwargs = dict(model=model, messages=[{"role": "system", "content": system}, user],
                      format="json", options=opts)
        if cfg.get("think") is False and model not in _NO_THINK:
            kwargs["think"] = False  # qwen3/gemma4/gpt-oss: matikan mode berpikir (token & waktu membengkak di CPU)
        try:
            try:
                resp = chat(**kwargs)
            except Exception as e:
                if "think" in kwargs and "think" in str(e).lower():  # model/klien tidak mengenal parameter think
                    _NO_THINK.add(model)
                    kwargs.pop("think")
                    resp = chat(**kwargs)
                else:
                    raise
        except Exception as e:  # koneksi/model gagal -> coba lagi
            ui.event("llm", f"chat error: {e}", "red")
            continue
        data = parse_json_loose(_content(resp))
        if data is not None:
            return data
    return None