"""E2E tanpa Ollama/LangGraph: LLM palsu + StateGraph mini. Menguji wiring, dedup, prioritas, juri, export."""
import re, sys, types, random, json, os
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

# --- rich dari vendor pip bila belum terpasang
try:
    import rich  # noqa
except ImportError:
    import importlib, pkgutil
    import pip._vendor.rich as _r
    for m in pkgutil.iter_modules(_r.__path__):          # muat semua submodul dulu -> tidak ada class ganda
        try: importlib.import_module("pip._vendor.rich." + m.name)
        except Exception: pass
    sys.modules["rich"] = _r
    for k in list(sys.modules):
        if k.startswith("pip._vendor.rich."):
            sys.modules["rich." + k[len("pip._vendor.rich."):]] = sys.modules[k]

# --- StateGraph mini
try:
    import langgraph  # noqa
except ImportError:
    END = "__end__"
    class StateGraph:
        def __init__(self, schema): self.nodes, self.edges, self.cond, self.entry = {}, {}, {}, None
        def add_node(self, n, f): self.nodes[n] = f
        def set_entry_point(self, n): self.entry = n
        def add_edge(self, a, b): self.edges[a] = b
        def add_conditional_edges(self, a, fn, m): self.cond[a] = (fn, m)
        def compile(self):
            g = self
            class C:
                def invoke(self, state, config=None):
                    st, cur = dict(state), g.entry
                    while cur != END:
                        st.update(g.nodes[cur](st) or {})
                        if cur in g.cond: cur = g.cond[cur][1][g.cond[cur][0](st)]
                        else: cur = g.edges[cur]
                    return st
            return C()
    m = types.ModuleType("langgraph"); mg = types.ModuleType("langgraph.graph")
    mg.StateGraph, mg.END = StateGraph, END
    sys.modules["langgraph"], sys.modules["langgraph.graph"] = m, mg

from tools import llm
from tools.ui import ui

random.seed(7)
calls = {"expand": 0, "judge": 0}
models = {}
FAULT_ONCE = set()

def fake_chat(model, messages, format=None, options=None):
    system, prompt = messages[0]["content"], messages[1]["content"]
    models[(model, "judge" if "auditor" in system else "expand")] = models.get((model, "judge" if "auditor" in system else "expand"), 0) + 1
    if "Kondisi decision table:" in prompt:  # analisis decision table (nilai, nilai normal, nilai yang pasti ditolak)
        out = []
        found = re.findall(r"^- \[([^\]]*)\] ([^:\n]+): (.+)$", prompt, re.M)
        if len({t for t, _, _ in found}) > 1:  # jawaban sebagian (seperti AI asli): tabel pertama terlewat
            found = [f for f in found if f[0] != found[0][0]]
        for table, name, vals in found:
            name = name.replace("(", "").replace(")", "") if "(" in name else name  # nama sedikit berbeda
            v = [f"{name} normal", f"{name} gagal"] if "belum ada" in vals else [x.strip() for x in vals.split(" / ")]
            rej = [x for x in v if re.match(r"(?i)^(invalid|expired|revoked|locked|already used)", x)]
            prev = next((o for o in reversed(out) if o["table"] == table), None)
            dep = {"name": prev["name"], "values": [prev["values"][0]]} if prev and len(prev["values"]) > 1 else None
            out.append({"table": table, "name": name, "values": v, "normal": v[0], "reject": rej, "berlaku_jika": dep})
        return {"message": {"content": json.dumps({"conditions": out})}}
    if "Cocokkan label" in system:  # penyeragaman nama field Test Data
        return {"message": {"content": json.dumps({"map": {}})}}
    if "Satu baris decision table" in prompt:  # hasil satu baris decision table
        combo = prompt.split("Satu baris decision table", 1)[1]
        bad = re.search(r"(?i)gagal|expired|invalid|FAILED", combo)
        r = random.random()
        if r < 0.1:
            return {"message": {"content": json.dumps({"langkah": [], "keputusan": "DIPROSES", "expected": "Express shipping is always chargeable"})}}
        if r < 0.15:
            return {"message": {"content": "bukan json"}}
        return {"message": {"content": json.dumps({"langkah": ["aturan berlaku"], "keputusan": "DITOLAK" if bad else "DIPROSES",
                                                    "expected": "Sistem memproses sesuai kombinasi kondisi pada baris ini"})}}
    if "auditor" in system:
        calls["judge"] += 1
        exp = re.search(r"^TC expected: (.*)$", prompt, re.M).group(1)
        r = random.random()
        if r < 0.08: res = {"keputusan_sistem": "TIDAK JELAS", "relevan": True, "salah_fakta": "", "aturan": "", "reason": "informasi PRD kurang jelas"}
        elif r < 0.15: res = {"keputusan_sistem": "DIPROSES", "relevan": True, "salah_fakta": "", "aturan": "x", "reason": "TC允许第4次尝试 与PRD矛盾"}
        elif r < 0.22: res = {"keputusan_sistem": "DITOLAK", "relevan": True, "salah_fakta": exp[:30], "aturan": "aturan PRD", "reason": "nilai salah"}
        elif r < 0.28: res = {"keputusan_sistem": "DITOLAK", "relevan": True, "salah_fakta": "tidak menyebut pesan error", "aturan": "", "reason": "kurang detail"}
        elif r < 0.32: res = {"keputusan_sistem": "DIPROSES", "relevan": False, "salah_fakta": "", "aturan": "", "reason": "menguji hal lain"}
        else: res = {"keputusan_sistem": "DIPROSES" if exp.lower().startswith("berhasil") else "DITOLAK", "relevan": True,
                     "salah_fakta": "", "aturan": "aturan PRD", "reason": "sesuai"}
        return {"message": {"content": json.dumps(res)}}
    calls["expand"] += 1
    out = []
    for blk in re.split(r"(?m)^### ", prompt)[1:]:
        oid = blk.split("\n")[0].strip()
        if not re.match(r"OB-\d+$", oid): continue
        sc = re.search(r"Skenario: (.*)", blk).group(1)
        pol = re.search(r"Polaritas: (\w+)", blk).group(1)
        fb = "PERBAIKI" in blk
        data = re.search(r"Nilai uji.*?:\n(.*?)(?:\nPrekondisi|\nHasil|\nPERBAIKI|\Z)", blk, re.S)
        n = int(oid.split("-")[1])
        hint = re.search(r"Langkah wajib.*?: (.*)", blk)
        generic = (n % 7 == 0 and not fb)           # gagal lunak pada attempt-1, ok setelah feedback
        stubborn = (n % 23 == 0)                     # selalu generik -> harus ditandai review
        wrongpol = (n % 31 == 0)                     # polaritas selalu salah -> template/dropped
        okpol = "Berhasil" if pol != "Negative" else "Gagal"
        if wrongpol: okpol = "Gagal" if okpol == "Berhasil" else "Berhasil"
        exp = f"{okpol}. Sistem {'menerima' if okpol=='Berhasil' else 'menolak'} input dan menampilkan hasil sesuai skenario ({sc[:40]})."
        if generic or stubborn: exp = "Berhasil. Alur berhasil sesuai deskripsi requirement."
        ttl = f"Verifikasi {sc[:60]}"
        if n % 11 == 0: ttl += " | Expected: Berhasil sesuatu"
        elif n % 13 == 0: ttl += f" {n % 5 + 1}"
        tdata = "" if data else ("contoh" if n % 17 else {"email": "x@y.z", "phone_number": "628123456789"})
        out.append({"ob_id": oid, "title": ttl,
                    "preconditions": "Kondisi awal sistem sesuai skenario pengujian" if generic or stubborn else "Pengguna terdaftar dan berada di halaman terkait",
                    "steps": (["Isi field sesuai Test Data", "Klik tombol Kirim"] if n % 19 or fb else ["Kirim"])
                             + ([hint.group(1)] if hint else []), "expected_result": exp,
                    "test_data": tdata})
    return {"message": {"content": json.dumps({"test_cases": out})}}

llm.CHAT_FN = fake_chat

if __name__ == "__main__":
    plain = "--plain" in sys.argv
    from pathlib import Path
    from tc_workflows.tc_graph import tc_graph
    prd_path = "knowledge/prd/prd_user_authentication_mfa_management.md"
    prd = Path(prd_path).read_text(encoding="utf-8")
    ui.configure(plain=plain)
    ui.start("prd user authentication mfa management", llm.generation_model(), llm.judge_model())
    with ui.live():
        final = tc_graph.invoke({"goal": "x", "prd_context": prd, "prd_name": "prd user authentication mfa management",
                                 "prd_path": prd_path, "output_dir": "/tmp/out_test"})
    rep = final["report"]
    ui.finish(rep, final["output_path"], removed=len(final["dedup_removed"]), dropped=final["dropped_obs"],
              review_samples=[t for t in final["final_tcs"] if t.get("review_flag")][:5])
    print("calls", calls); print("models", models)
