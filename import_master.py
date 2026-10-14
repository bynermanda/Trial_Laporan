"""
import_master.py — Pindahkan data master dari Google Sheets (CSV) ke Supabase.

Langkah:
  1. Di Google Sheets: File → Download → CSV untuk sheet
       - Master_Karyawan  → simpan sebagai Master_Karyawan.csv
       - MainData         → simpan sebagai MainData.csv
  2. Taruh kedua CSV di folder yang sama dengan file ini.
  3. Jalankan:  python import_master.py
     (kredensial dibaca dari .streamlit/secrets.toml)

Aman dijalankan berulang: memakai UPSERT, jadi data yang sama akan di-update,
bukan diduplikasi.
"""
import re
import sys
import tomllib
from pathlib import Path

import pandas as pd
from supabase import create_client

BATCH = 500


def load_client():
    path = Path(".streamlit/secrets.toml")
    if not path.exists():
        sys.exit("❌ .streamlit/secrets.toml tidak ditemukan.")
    cfg = tomllib.loads(path.read_text(encoding="utf-8"))["supabase"]
    return create_client(cfg["url"], cfg["key"])


def kolom(df: pd.DataFrame, *nama: str) -> str:
    """Cari kolom tanpa peduli huruf besar/kecil, spasi, '/' atau '_'."""
    norm = {re.sub(r"[\s/_]", "", c).lower(): c for c in df.columns}
    for n in nama:
        key = re.sub(r"[\s/_]", "", n).lower()
        if key in norm:
            return norm[key]
    sys.exit(f"❌ Kolom {nama} tidak ditemukan. Kolom yang ada: {list(df.columns)}")


def bersih(v) -> str:
    return re.sub(r"\.0$", "", str(v if pd.notna(v) else "").strip().replace("'", ""))


def upsert(client, table: str, rows: list[dict], on_conflict: str) -> None:
    for i in range(0, len(rows), BATCH):
        client.table(table).upsert(rows[i:i + BATCH], on_conflict=on_conflict).execute()
    print(f"  ✅ {table}: {len(rows)} baris di-upsert")


def import_karyawan(client) -> None:
    df = pd.read_csv("Master_Karyawan.csv", dtype=str)
    c_nik, c_nama = kolom(df, "NIK"), kolom(df, "Nama")
    rows = {}
    for _, r in df.iterrows():
        nik = bersih(r[c_nik]).replace(".", "")
        if nik:
            rows[nik] = {"nik": nik, "nama": bersih(r[c_nama]) or nik}
    upsert(client, "master_karyawan", list(rows.values()), "nik")


def import_main_data(client) -> None:
    df = pd.read_csv("MainData.csv", dtype=str)
    c = {
        "part_no":   kolom(df, "Part_No"),
        "part_name": kolom(df, "Part_Name"),
        "model":     kolom(df, "MODEL"),
        "line":      kolom(df, "LINE"),
        "urutan":    kolom(df, "URUTAN"),
        "sec_pcs":   kolom(df, "SEC /PCS", "Sec_Pcs"),
    }
    rows, lines = {}, set()
    for _, r in df.iterrows():
        part_no, urutan = bersih(r[c["part_no"]]), bersih(r[c["urutan"]])
        if not part_no or not urutan:
            continue
        line = bersih(r[c["line"]]) or None
        if line:
            lines.add(line)
        sec = pd.to_numeric(bersih(r[c["sec_pcs"]]).replace(",", "."), errors="coerce")
        rows[(part_no, urutan)] = {          # duplikat part+urutan: baris terakhir menang
            "part_no":   part_no,
            "part_name": bersih(r[c["part_name"]]),
            "model":     bersih(r[c["model"]]) or None,
            "line":      line,
            "urutan":    urutan,
            "sec_pcs":   0 if pd.isna(sec) else float(sec),
        }
    # Line harus ada dulu (foreign key)
    upsert(client, "master_line", [{"kode": l} for l in sorted(lines)], "kode")
    upsert(client, "main_data", list(rows.values()), "part_no,urutan")


if __name__ == "__main__":
    client = load_client()
    print("Import Master_Karyawan...")
    import_karyawan(client)
    print("Import MainData...")
    import_main_data(client)
    print("🎉 Selesai.")
