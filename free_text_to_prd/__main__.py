"""python -m free_text_to_prd --input catatan.txt --name "Nama Modul"
python -m free_text_to_prd --text "isi catatan ..." --name "Nama Modul"
Hasil: knowledge/prd/<nama>_dari_catatan.md (langsung muncul di dashboard) + outputs/free_text_to_prd/<nama>/"""
import argparse
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))


def main(argv=None):
    ap = argparse.ArgumentParser(prog="free_text_to_prd", description="Susun catatan QA menjadi PRD.")
    src = ap.add_mutually_exclusive_group(required=True)
    src.add_argument("--input", help="file catatan (.txt / .md)")
    src.add_argument("--text", help="isi catatan langsung")
    ap.add_argument("--name", default="", help="nama modul, mis. \"Berita Acara\"")
    a = ap.parse_args(argv)
    if a.input:
        p = Path(a.input)
        text, source = p.read_text(encoding="utf-8"), p.name
    else:
        text, source = a.text, "teks langsung"
    from free_text_to_prd.pipeline import run
    res = run(text, name=a.name, source_name=source)
    print(f"\nPRD: {res['prd_path']}\nCatatan review (hal yang belum jelas, terpisah dari PRD): {res['review_path']}")
    print("PRD ini sudah ada di daftar PRD dashboard. Baca catatan review dulu sebelum membuat test case.")


if __name__ == "__main__":
    main()
