#!/usr/bin/env python3
"""
Runner pipeline v2 (atomizer -> designer -> expander -> semantic verifier -> coverage/dedup -> export)
dengan tampilan terminal `rich` (otomatis fallback ke teks biasa bila rich tidak ada / output bukan terminal).

Usage:
  python run.py <PRD_PATH> [output_dir] [--plain] [--cap N] [--no-judge]
  python run.py                      # menu pilih PRD dari knowledge/prd/
  python run.py mfa                  # cocokkan potongan nama file PRD
"""
import argparse
import atexit
import os
import shutil
import subprocess
import sys
import time
from pathlib import Path

from tools import llm
from tools.ui import HAVE_RICH, ui


def parse_args():
    ap = argparse.ArgumentParser(description="Generate test case dari PRD")
    ap.add_argument("prd", nargs="?", help="path PRD .md, atau potongan nama file (kosong = menu pilih)")
    ap.add_argument("output_dir", nargs="?", default="outputs")
    ap.add_argument("--plain", action="store_true", help="matikan tampilan rich (teks biasa)")
    ap.add_argument("--cap", type=int, default=None, help="override max_obligations (0 = tanpa batas)")
    ap.add_argument("--no-judge", action="store_true", help="matikan juri LLM (lebih cepat)")
    return ap.parse_args()


def pick_prd(arg):
    """Path lengkap -> dipakai langsung. Potongan nama (mis. "mfa") -> dicocokkan. Kosong -> menu pilih."""
    files = sorted(Path("knowledge/prd").glob("*.md"))
    if arg:
        if Path(arg).exists():
            return arg
        files = [f for f in files if arg.lower() in f.stem.lower()]
        if not files:
            print(f"PRD '{arg}' tidak ditemukan (bukan path, dan tidak cocok dengan nama di knowledge/prd/).")
            sys.exit(1)
    if not files:
        print("Tidak ada PRD di knowledge/prd/. Usage: python run.py <PRD_PATH> [output_dir]")
        sys.exit(1)
    if len(files) == 1 or not sys.stdin.isatty():
        return str(files[0])

    print("\nPilih PRD:")
    for i, f in enumerate(files, 1):
        print(f"  [{i}] {f.name}")
    while True:
        ans = input(f"Nomor 1-{len(files)} (Enter = 1, q = batal): ").strip().lower()
        if ans in ("q", "quit"):
            sys.exit(0)
        if ans == "":
            return str(files[0])
        if ans.isdigit() and 1 <= int(ans) <= len(files):
            return str(files[int(ans) - 1])
        print("Pilihan tidak valid.")


def _ollama_up() -> bool:
    from tools import ai_source
    return ai_source.probe()[0] is not None


def ensure_ollama() -> None:
    """Jika server Ollama belum hidup, nyalakan otomatis (tanpa jendela) dan matikan lagi saat run selesai.
    Bila memakai Server AI bersama, tidak ada yang dinyalakan di laptop ini."""
    from tools import ai_source
    models, problem = ai_source.probe()
    if models is not None:
        return
    if ai_source.is_server():
        msg = {"login": "Belum masuk atau sesi login habis. Masuk lagi di dashboard: Pengaturan > Sumber AI.",
               "ditolak": "Server menolak laptop ini. Pastikan tersambung lewat Tailscale.",
               "versi": "Versi TƎRᗩ ini terlalu lama untuk Server AI bersama. Minta folder TƎRᗩ terbaru ke pemilik server."}.get(
            problem, "Server AI bersama tidak bisa dihubungi. Pastikan Tailscale menyala dan Server AI temanmu berjalan.")
        print(f"\n[!] {msg}")
        sys.exit(2)
    exe = shutil.which("ollama")
    if not exe:
        print("\n[!] Perintah `ollama` tidak ditemukan. Pasang Ollama dari https://ollama.com/download lalu coba lagi.")
        sys.exit(2)
    env = os.environ.copy()
    env.setdefault("OLLAMA_KEEP_ALIVE", "30m")
    env.setdefault("OLLAMA_MAX_LOADED_MODELS", "1")  # aman untuk RAM terbatas; set variabel ini sendiri untuk menimpa
    flags = getattr(subprocess, "CREATE_NO_WINDOW", 0)
    print("Ollama belum berjalan, menyalakan otomatis...", end="", flush=True)
    proc = subprocess.Popen([exe, "serve"], env=env, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                            creationflags=flags)
    atexit.register(lambda: proc.poll() is None and proc.terminate())
    for _ in range(40):
        time.sleep(0.75)
        if _ollama_up():
            print(" siap.")
            return
        if proc.poll() is not None:
            break
        print(".", end="", flush=True)
    print()


def preflight():
    """Pastikan Ollama hidup & model yang dipakai sudah ter-pull, sebelum membakar waktu di pipeline."""
    ensure_ollama()
    needed = {llm.generation_model()}
    if llm.auto_model():
        needed.add(llm.auto_model())
    if llm.settings()["judge_enabled"]:
        needed.add(llm.judge_model())
    from tools import ai_source
    models, problem = ai_source.probe()
    have = set()
    for m in models or []:
        have.add(m["name"])
        have.add(m["name"].split(":")[0] if m["name"].endswith(":latest") else m["name"])
    if models is None:
        print("\n[!] Tidak bisa terhubung ke Ollama (127.0.0.1:11434).")
        print("    1) Pastikan `ollama serve` berjalan di jendela PowerShell LAIN dan tidak ditutup.")
        print("    2) Cek: curl http://127.0.0.1:11434   (harus menjawab: Ollama is running)")
        print('    3) Bila ada proxy:  $env:NO_PROXY = "127.0.0.1,localhost"')
        sys.exit(2)
    missing = sorted(n for n in needed if n not in have)
    if missing:
        print(f"\n[!] Model belum ter-pull: {', '.join(missing)}")
        if ai_source.is_server():
            print("    Minta pemilik Server AI bersama mengunduh model ini, atau pilih model lain di Pengaturan.")
        for n in missing:
            print(f"    ollama pull {n}")
        sys.exit(2)


def run_pipeline(prd_path, output_dir="outputs", overrides=None):
    """Jalankan pipeline untuk satu PRD. Dipakai oleh CLI (main) dan dashboard.py."""
    from tools import cancel
    cancel.CANCEL.clear()
    llm.set_overrides(overrides or {})
    from tc_workflows.tc_graph import tc_graph
    prd = Path(prd_path).read_text(encoding="utf-8")
    prd_name = Path(prd_path).stem.replace("_", " ").replace("-", " ")
    state = {"goal": "Generate test cases", "prd_context": prd, "prd_name": prd_name,
             "prd_path": str(prd_path), "output_dir": str(output_dir)}
    return tc_graph.invoke(state, config={"recursion_limit": 10000})


def main():
    args = parse_args()
    prd_path = pick_prd(args.prd)

    # override konfigurasi dari CLI (tanpa mengubah ai.json)
    overrides = {}
    if args.cap is not None:
        overrides["max_obligations"] = args.cap or None
    if args.no_judge:
        overrides["judge_enabled"] = False
    llm.set_overrides(overrides)
    prd_name = Path(prd_path).stem.replace("_", " ").replace("-", " ")

    preflight()
    ui.configure(plain=args.plain)
    ui.start(prd_name, llm.generation_model(), llm.judge_model() if llm.settings()["judge_enabled"] else "(dimatikan)",
             llm.auto_model())
    if not HAVE_RICH and not args.plain:
        print("Tip: pip install rich  -> tampilan terminal lebih informatif\n")
    try:
        with ui.live():
            final = run_pipeline(prd_path, args.output_dir, overrides)
    except KeyboardInterrupt:
        print("\nDibatalkan oleh pengguna.")
        sys.exit(130)

    report = final.get("report") or final.get("v2_report") or {}
    review = [t for t in final.get("final_tcs", []) if t.get("review_flag")][:8]
    ui.finish(report, final.get("output_path", "-"), removed=len(final.get("dedup_removed", [])),
              dropped=final.get("dropped_obs", []), review_samples=review)


if __name__ == "__main__":
    main()