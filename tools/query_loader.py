import json
from pathlib import Path

QUERY_PATH = Path("queries/user_queries.json")

def load_query(query_name):
    with open(QUERY_PATH, "r", encoding="utf-8") as f:
        queries = json.load(f)

    return queries[query_name]