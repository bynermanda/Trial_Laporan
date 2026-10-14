"""
import_master.py — Import data master dari CSV Google Sheets ke Supabase (via komputer).

Alternatif tanpa Python: pakai menu "🛠️ Admin: Import Data Master" di sidebar aplikasi.

Langkah:
  1. Google Sheets → File → Download → CSV untuk sheet Master_Karyawan dan MainData,
     simpan sebagai Master_Karyawan.csv dan MainData.csv di folder ini.
  2. python import_master.py   (kredensial dari .streamlit/secrets.toml)
Aman dijalankan berulang (UPSERT).
"""
import sys
import tomllib
from pathlib import Path

import pandas as pd
from supabase import create_client

import master_import as mi


def main():
    path = Path(".streamlit/secrets.toml")
    if not path.exists():
        sys.exit("❌ .streamlit/secrets.toml tidak ditemukan.")
    cfg = tomllib.loads(path.read_text(encoding="utf-8"))["supabase"]
    client = create_client(cfg["url"], cfg["key"])

    n = mi.import_karyawan(client, pd.read_csv("Master_Karyawan.csv", dtype=str))
    print(f"✅ master_karyawan: {n} baris")
    n_line, n_part = mi.import_main_data(client, pd.read_csv("MainData.csv", dtype=str))
    print(f"✅ master_line: {n_line} baris, main_data: {n_part} baris")


if __name__ == "__main__":
    main()
