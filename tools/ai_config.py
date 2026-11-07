from pathlib import Path
import json


ROOT_DIR = Path(__file__).resolve().parents[1]
CONFIG_PATH = ROOT_DIR / "configs" / "ai.json"


def load_ai_config():
    if not CONFIG_PATH.exists():
        raise FileNotFoundError(
            f"AI config tidak ditemukan: {CONFIG_PATH}"
        )

    return json.loads(
        CONFIG_PATH.read_text(
            encoding="utf-8"
        )
    )


def project_path(relative_path: str) -> Path:
    return ROOT_DIR / relative_path


def ollama_settings():
    return load_ai_config()["ollama"]


def rag_settings():
    return load_ai_config()["rag"]


def learning_settings():
    return load_ai_config()["learning"]


def testcase_settings():
    return load_ai_config()["test_case"]