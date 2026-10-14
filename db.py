"""
db.py — Lapisan akses data Supabase untuk aplikasi Laporan Produksi Press.

Semua komunikasi ke database lewat file ini. Trial.py (UI) tidak pernah
menyentuh client Supabase secara langsung, sehingga:
  * retry & penanganan error ada di satu tempat,
  * setiap operasi hanya membaca/menulis BARIS yang perlu (bukan seluruh sheet),
  * aturan anti-dobel dijaga oleh unique index di database (lihat supabase_schema.sql).
"""
from __future__ import annotations

import logging
import random
import re
import time
import uuid
from datetime import date, datetime, time as dt_time, timedelta
from typing import Any, Callable
from zoneinfo import ZoneInfo

import httpx
import pandas as pd
import streamlit as st
from postgrest.exceptions import APIError
from supabase import Client, create_client

TZ_WIB = ZoneInfo("Asia/Jakarta")
log = logging.getLogger("laporan_press.db")


# =====================================================================
# ERROR
# =====================================================================
class DBError(Exception):
    """Gagal akses database. Pesannya aman ditampilkan ke operator."""


class DuplicateError(DBError):
    """Melanggar unique constraint (dobel check-in / dobel START / dobel kirim)."""


# =====================================================================
# UTILITAS WAKTU & NORMALISASI
# =====================================================================
def now_wib() -> datetime:
    """Waktu sekarang WIB, timezone-aware (tidak tergantung zona server)."""
    return datetime.now(TZ_WIB)


def combine_wib(tgl: date, jam: dt_time) -> datetime:
    """Gabungkan tanggal + jam menjadi datetime WIB yang timezone-aware."""
    return datetime.combine(tgl, jam.replace(tzinfo=None)).replace(tzinfo=TZ_WIB)


def parse_ts(value: Any) -> datetime | None:
    """Ubah string timestamptz dari Supabase menjadi datetime WIB."""
    if value in (None, ""):
        return None
    ts = pd.Timestamp(value)
    if ts.tzinfo is None:
        ts = ts.tz_localize("UTC")
    return ts.tz_convert(TZ_WIB).to_pydatetime()


def normalize_nik(raw: Any) -> str:
    """'12.345 / '12345 / 12345.0 → '12345' (format yang disimpan di DB)."""
    s = str(raw or "").strip().replace("'", "")
    s = re.sub(r"\.0$", "", s)
    return s.replace(".", "").strip()


def normalize_part_no(raw: Any) -> str:
    return re.sub(r"\.0$", "", str(raw or "").strip()).strip()


def _serialize(data: dict) -> dict:
    """datetime/date/time → ISO string agar bisa dikirim sebagai JSON."""
    out = {}
    for k, v in data.items():
        if isinstance(v, (datetime, date, dt_time)):
            v = v.isoformat()
        elif isinstance(v, uuid.UUID):
            v = str(v)
        out[k] = v
    return out


# =====================================================================
# KONEKSI
# =====================================================================
@st.cache_resource(show_spinner=False)
def get_client() -> Client:
    """
    Satu client Supabase per proses server (dipakai bersama semua sesi).
    Kredensial dibaca dari .streamlit/secrets.toml:
        [supabase]
        url = "https://xxxx.supabase.co"
        key = "sb_secret_...."   # atau service_role key (legacy)
    """
    try:
        cfg = st.secrets["supabase"]
        url, key = cfg["url"], cfg["key"]
    except (KeyError, FileNotFoundError) as e:
        raise DBError("Konfigurasi [supabase] url/key belum ada di secrets.toml.") from e
    return create_client(url, key)


# Error PostgREST/Postgres yang sifatnya sementara → aman dicoba ulang.
_TRANSIENT_CODES = {
    "PGRST000", "PGRST001", "PGRST002", "PGRST003",  # koneksi/pool PostgREST
    "40001", "40P01",                                # serialization failure, deadlock
    "57014",                                         # statement timeout
}
_TRANSIENT_NET = (httpx.TransportError, ConnectionError, TimeoutError)


def _backoff(attempt: int, op: str) -> None:
    wait = min(0.5 * (2 ** (attempt - 1)), 4.0) + random.uniform(0, 0.3)
    log.warning("Retry %s (percobaan %s) dalam %.1fs", op, attempt, wait)
    time.sleep(wait)


def run_query(build: Callable[[Client], Any], op: str, retries: int = 3):
    """
    Jalankan query Supabase dengan retry otomatis untuk gangguan jaringan.

    `build` menerima client dan mengembalikan query builder (tanpa .execute()).
    Contoh:
        run_query(lambda c: c.table("proses").select("*").eq("nik", nik), "baca proses")

    Melempar:
        DuplicateError  → unique constraint dilanggar (kode 23505)
        DBError         → error lain, pesan sudah ramah operator
    """
    for attempt in range(1, retries + 1):
        try:
            return build(get_client()).execute()
        except APIError as e:
            code = str(getattr(e, "code", "") or "")
            msg = getattr(e, "message", None) or str(e)
            if code == "23505":
                raise DuplicateError(msg) from e
            # Tanpa kode = biasanya error gateway (502/503/504) non-JSON → sementara
            if (code in _TRANSIENT_CODES or not code) and attempt < retries:
                _backoff(attempt, op)
                continue
            log.error("%s gagal: [%s] %s", op, code, msg)
            raise DBError(f"{op} ditolak database: {msg} [{code or 'no-code'}]") from e
        except _TRANSIENT_NET as e:
            if attempt < retries:
                _backoff(attempt, op)
                continue
            log.error("%s gagal karena jaringan: %s", op, e)
            raise DBError(
                f"Koneksi ke database terputus saat {op}. Cek jaringan/WiFi lalu coba lagi."
            ) from e
    raise DBError(f"{op} gagal setelah {retries} percobaan.")


def ping() -> int:
    """Cek koneksi; mengembalikan jumlah karyawan terdaftar."""
    res = run_query(
        lambda c: c.table("master_karyawan").select("nik", count="exact").limit(1),
        "cek koneksi",
    )
    return res.count or 0


# =====================================================================
# MASTER DATA (di-cache singkat karena jarang berubah)
# Tombol "Update Data Master" di sidebar memanggil st.cache_data.clear().
# =====================================================================
@st.cache_data(ttl=300, show_spinner=False)
def get_karyawan(nik: str) -> dict | None:
    res = run_query(
        lambda c: c.table("master_karyawan").select("nik,nama,aktif").eq("nik", nik).limit(1),
        "verifikasi NIK",
    )
    return res.data[0] if res.data else None


@st.cache_data(ttl=300, show_spinner=False)
def get_part_processes(part_no: str) -> list[dict]:
    """Semua urutan proses untuk 1 Part No (pengganti filter MainData)."""
    res = run_query(
        lambda c: c.table("main_data")
        .select("part_no,part_name,model,line,urutan,sec_pcs")
        .eq("part_no", part_no)
        .eq("aktif", True)
        .order("urutan"),
        "baca MainData",
    )
    return res.data or []


@st.cache_data(ttl=3600, show_spinner=False)
def get_lines() -> list[str]:
    res = run_query(
        lambda c: c.table("master_line").select("kode").eq("aktif", True).order("kode"),
        "baca daftar line",
    )
    return [r["kode"] for r in res.data or []]


@st.cache_data(ttl=3600, show_spinner=False)
def get_kode_abnormal() -> list[dict]:
    res = run_query(
        lambda c: c.table("master_kode_abnormal")
        .select("kode,uraian")
        .eq("aktif", True)
        .order("urutan_tampil"),
        "baca kode abnormal",
    )
    return res.data or []


# =====================================================================
# WAKTU KERJA (check-in / check-out) — TIDAK di-cache, selalu real-time
# =====================================================================
def get_active_shift(nik: str) -> dict | None:
    res = run_query(
        lambda c: c.table("waktu_kerja")
        .select("*")
        .eq("nik", nik)
        .is_("check_out", "null")
        .order("check_in", desc=True)
        .limit(1),
        "cek status check-in",
    )
    return res.data[0] if res.data else None


def check_in(nik: str, nama: str) -> dict:
    """INSERT 1 baris. Jika sudah ada shift aktif, kembalikan shift tersebut."""
    now = now_wib()
    row = _serialize({
        "tanggal": now.date(),
        "nik": nik,
        "nama": nama,
        "check_in": now,
        "aktivitas": "Mulai Shift",
    })
    try:
        return run_query(lambda c: c.table("waktu_kerja").insert(row), "check-in").data[0]
    except DuplicateError:
        existing = get_active_shift(nik)
        if existing:
            return existing
        raise


def check_out(shift: dict) -> float:
    """UPDATE baris shift ini saja. Mengembalikan total jam shift."""
    now = now_wib()
    check_in_dt = parse_ts(shift["check_in"]) or now
    total_jam = round((now - check_in_dt).total_seconds() / 3600, 2)
    payload = _serialize({"check_out": now, "total_jam": total_jam, "aktivitas": "Shift Complete"})
    res = run_query(
        lambda c: c.table("waktu_kerja")
        .update(payload)
        .eq("id", shift["id"])
        .is_("check_out", "null"),       # guard: hanya jika belum check-out
        "check-out",
    )
    if not res.data:
        raise DBError("Shift ini sudah check-out sebelumnya (mungkin dari perangkat lain).")
    return total_jam


# =====================================================================
# PROSES PRODUKSI
# =====================================================================
def get_active_proses(nik: str) -> dict | None:
    res = run_query(
        lambda c: c.table("proses")
        .select("*")
        .eq("nik", nik)
        .eq("status", "START")
        .order("actual_time_start", desc=True)
        .limit(1),
        "cek proses aktif",
    )
    return res.data[0] if res.data else None


def ringkasan_hari_ini(nik: str) -> dict:
    """Jumlah SPH terkirim & total ACT operator ini untuk tanggal WIB hari ini."""
    res = run_query(
        lambda c: c.table("proses")
        .select("act")
        .eq("nik", nik)
        .eq("status", "FINISH")
        .eq("tanggal", now_wib().date().isoformat()),
        "rekap hari ini",
    )
    rows = res.data or []
    return {"jumlah": len(rows), "act": sum(int(r.get("act") or 0) for r in rows)}


def start_proses(data: dict) -> dict:
    """
    INSERT baris START. Unique index `uq_proses_aktif_per_operator` menjamin
    1 operator hanya punya 1 START, walau tombol diklik dua kali.
    """
    payload = _serialize(data)
    try:
        return run_query(lambda c: c.table("proses").insert(payload), "simpan START").data[0]
    except DuplicateError:
        # Kasus retry: request pertama ternyata sudah masuk sebelum koneksi putus.
        aktif = get_active_proses(data["nik"])
        if (
            aktif
            and aktif["part_no"] == data["part_no"]
            and parse_ts(aktif["actual_time_start"]) == data["actual_time_start"]
        ):
            return aktif
        raise DuplicateError("Masih ada proses START aktif untuk operator ini.")


def finish_proses(proses_id: int, data: dict) -> dict:
    """UPDATE baris START menjadi FINISH (hanya baris dengan id ini)."""
    payload = _serialize({**data, "status": "FINISH"})
    res = run_query(
        lambda c: c.table("proses")
        .update(payload)
        .eq("id", proses_id)
        .eq("status", "START"),          # guard: tidak menimpa data yang sudah FINISH
        "simpan FINISH",
    )
    if res.data:
        return res.data[0]

    # Tidak ada baris ter-update: cek apakah ternyata sudah tersimpan (retry).
    cek = run_query(
        lambda c: c.table("proses").select("*").eq("id", proses_id).limit(1),
        "verifikasi FINISH",
    )
    if cek.data and cek.data[0]["status"] == "FINISH" and cek.data[0]["act"] == data.get("act"):
        return cek.data[0]
    raise DBError("Data START untuk proses ini tidak ditemukan atau sudah FINISH.")


# =====================================================================
# ABNORMAL
# =====================================================================
def insert_abnormal(data: dict) -> None:
    """
    INSERT 1 baris abnormal. `client_ref` (UUID) dibuat sekali per form,
    jadi klik dobel / retry tidak menghasilkan baris ganda.
    """
    payload = _serialize({**data, "client_ref": data.get("client_ref") or uuid.uuid4()})
    try:
        run_query(lambda c: c.table("abnormal").insert(payload), "simpan ABNORMAL")
    except DuplicateError:
        return  # client_ref sama → data ini sudah tersimpan sebelumnya
