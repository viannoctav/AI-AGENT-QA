import json
from pathlib import Path

CONFIG_PATH = Path("configs/environments.json")


def load_environment(env_name=None):
    with open(CONFIG_PATH, "r", encoding="utf-8") as f:
        config = json.load(f)

    if env_name is None:
        env_name = config["default_environment"]

    return config["environments"][env_name]