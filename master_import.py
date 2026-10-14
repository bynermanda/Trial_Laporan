"""
master_import.py — Ubah CSV dari Google Sheets (Master_Karyawan & MainData)
menjadi baris tabel Supabase, lalu upsert.

Dipakai oleh:
  * menu "🛠️ Admin: Import Data Master" di sidebar aplikasi (upload CSV), dan
  * import_master.py (dijalankan dari komputer).
Tidak bergantung pada Streamlit.
"""
import re

import pandas as pd

BATCH = 500


def _kunci(nama: str) -> str:
    return re.sub(r"[\s/_]", "", str(nama)).lower()


def kolom(df: pd.DataFrame, *nama: str) -> str:
    """Cari kolom tanpa peduli huruf besar/kecil, spasi, '/' atau '_'."""
    peta = {_kunci(c): c for c in df.columns}
    for n in nama:
        if _kunci(n) in peta:
            return peta[_kunci(n)]
    raise ValueError(f"Kolom {nama[0]} tidak ditemukan. Kolom yang ada: {list(df.columns)}")


def bersih(v) -> str:
    s = "" if v is None or (isinstance(v, float) and pd.isna(v)) else str(v)
    return re.sub(r"\.0$", "", s.strip().replace("'", ""))


def karyawan_rows(df: pd.DataFrame) -> list[dict]:
    c_nik, c_nama = kolom(df, "NIK"), kolom(df, "Nama")
    rows = {}
    for _, r in df.iterrows():
        nik = bersih(r[c_nik]).replace(".", "")
        if nik:
            rows[nik] = {"nik": nik, "nama": bersih(r[c_nama]) or nik}
    return list(rows.values())


def main_data_rows(df: pd.DataFrame) -> tuple[list[dict], list[dict]]:
    """Kembalikan (baris master_line, baris main_data)."""
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
            "sec_pcs":   0.0 if pd.isna(sec) or sec < 0 else round(float(sec), 2),
        }
    return [{"kode": l} for l in sorted(lines)], list(rows.values())


def upsert(client, table: str, rows: list[dict], on_conflict: str) -> int:
    for i in range(0, len(rows), BATCH):
        client.table(table).upsert(rows[i:i + BATCH], on_conflict=on_conflict).execute()
    return len(rows)


def import_karyawan(client, df: pd.DataFrame) -> int:
    return upsert(client, "master_karyawan", karyawan_rows(df), "nik")


def import_main_data(client, df: pd.DataFrame) -> tuple[int, int]:
    lines, rows = main_data_rows(df)
    n_line = upsert(client, "master_line", lines, "kode")   # line dulu (foreign key)
    n_part = upsert(client, "main_data", rows, "part_no,urutan")
    return n_line, n_part
