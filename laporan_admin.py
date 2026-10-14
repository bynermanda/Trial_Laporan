"""
laporan_admin.py — Halaman Admin "Data Laporan": seluruh hasil proses & abnormal.

Fitur:
  * Filter tanggal, status, kondisi, operator, part
  * Ringkasan angka (jumlah laporan, ACT, NG, rasio NG, rata-rata %Prod, jam kerja)
  * Tab: Hasil Proses · Abnormal · Rekap Operator · Rekap Part
  * Download CSV (bisa dibuka langsung di Excel)
Hanya membaca data; tidak ada yang diubah atau dihapus.
"""
from __future__ import annotations

from datetime import timedelta

import pandas as pd
import streamlit as st

import db
import ui
from db import DBError, now_wib

TZ = "Asia/Jakarta"


def _jam(series: pd.Series) -> pd.Series:
    t = pd.to_datetime(series, utc=True, errors="coerce").dt.tz_convert(TZ)
    return t.dt.strftime("%H:%M").fillna("")


def _angka(df: pd.DataFrame, kolom: list[str]) -> pd.DataFrame:
    for k in kolom:
        if k in df.columns:
            df[k] = pd.to_numeric(df[k], errors="coerce")
    return df


def _csv(df: pd.DataFrame) -> bytes:
    return df.to_csv(index=False).encode("utf-8-sig")   # utf-8-sig agar Excel membaca karakter dengan benar


def _cocok(df: pd.DataFrame, kolom: list[str], kata: str) -> pd.Series:
    kata = kata.strip().upper()
    if not kata:
        return pd.Series(True, index=df.index)
    hasil = pd.Series(False, index=df.index)
    for k in kolom:
        if k in df.columns:
            hasil |= df[k].astype(str).str.upper().str.contains(kata, regex=False, na=False)
    return hasil


def tampilkan() -> None:
    hari_ini = now_wib().date()

    # ---------------- Header ----------------
    c_judul, c_aksi = st.columns([3, 2], vertical_alignment="center")
    with c_judul:
        st.markdown('<div class="sec">Admin</div><div class="bigname">📊 Data Laporan Produksi</div>',
                    unsafe_allow_html=True)
    with c_aksi:
        b1, b2 = st.columns(2)
        if b1.button("↻ Muat Ulang", width="stretch"):
            db.get_laporan_proses.clear()
            db.get_laporan_abnormal.clear()
            st.rerun()
        if b2.button("← Kembali", width="stretch"):
            st.session_state.pop("halaman", None)
            st.rerun()

    # ---------------- Filter ----------------
    with st.container(key="card_filter"):
        f1, f2 = st.columns([2, 3], gap="medium")
        with f1:
            rentang = st.date_input("Rentang tanggal", value=(hari_ini - timedelta(days=6), hari_ini),
                                    max_value=hari_ini, format="DD/MM/YYYY", key="adm_rentang")
            status = st.radio("Status", ["Semua", "FINISH", "START"], horizontal=True, key="adm_status")
        with f2:
            g1, g2 = st.columns(2)
            cari_op = g1.text_input("Operator / NIK", key="adm_op")
            cari_part = g2.text_input("Part No / Nama Part", key="adm_part")
            kondisi = st.radio("Kondisi", ["Semua", "Normal", "Overtime"], horizontal=True, key="adm_kondisi")

    if not isinstance(rentang, (list, tuple)) or len(rentang) != 2:
        st.info("Pilih tanggal awal dan akhir.")
        return
    tgl_awal, tgl_akhir = rentang

    try:
        with st.spinner("Mengambil data..."):
            proses = pd.DataFrame(db.get_laporan_proses(tgl_awal, tgl_akhir))
            abnormal = pd.DataFrame(db.get_laporan_abnormal(tgl_awal, tgl_akhir))
    except DBError as e:
        st.error(f"❌ {e}")
        return

    # ---------------- Olah data proses ----------------
    if not proses.empty:
        proses = _angka(proses, ["act", "ng", "persen_prod", "rasio_ng", "total_jam", "total_istirahat", "sec_pcs"])
        mask = _cocok(proses, ["nama", "nik"], cari_op) & _cocok(proses, ["part_no", "part_name"], cari_part)
        if status != "Semua":
            mask &= proses["status"] == status
        if kondisi != "Semua":
            mask &= proses["condition"] == kondisi
        proses = proses[mask]

    if not abnormal.empty:
        abnormal = _angka(abnormal, ["total_waktu"])
        abnormal = abnormal[_cocok(abnormal, ["operator", "nik"], cari_op)
                            & _cocok(abnormal, ["part_no", "part_name"], cari_part)]

    # ---------------- Ringkasan ----------------
    selesai = proses[proses["status"] == "FINISH"] if not proses.empty else proses
    total_act = int(selesai["act"].sum()) if not selesai.empty else 0
    total_ng = int(selesai["ng"].sum()) if not selesai.empty else 0
    rata_prod = selesai["persen_prod"].dropna().mean() if not selesai.empty else float("nan")
    berjalan = int((proses["status"] == "START").sum()) if not proses.empty else 0

    ui.kpi_grid([
        ("Laporan Selesai", f"{len(selesai)}", "", f"{tgl_awal:%d/%m} – {tgl_akhir:%d/%m/%Y}"),
        ("Sedang Berjalan", f"{berjalan}", "accent" if berjalan else ""),
        ("Total ACT", f"{total_act:,}".replace(",", "."), "ok"),
        ("Total NG", f"{total_ng:,}".replace(",", "."), "bad" if total_ng else ""),
        ("Rasio NG", f"{total_ng / total_act * 100:.2f}%" if total_act else "—", ""),
        ("Rata-rata %Prod", f"{rata_prod:.1f}%" if pd.notna(rata_prod) else "—", "accent"),
        ("Total Jam Kerja", f"{selesai['total_jam'].sum():.1f} j" if not selesai.empty else "—", ""),
        ("Total Abnormal", f"{int(abnormal['total_waktu'].sum()) if not abnormal.empty else 0} m",
         "bad" if not abnormal.empty else "", f"{len(abnormal)} catatan"),
    ])

    tab_p, tab_a, tab_o, tab_part = st.tabs(["📋 Hasil Proses", "⚠️ Abnormal", "👷 Rekap Operator", "🔩 Rekap Part"])

    # ---------------- Tab: hasil proses ----------------
    with tab_p:
        if proses.empty:
            st.info("Belum ada data proses untuk filter ini.")
        else:
            tabel = pd.DataFrame({
                "Tanggal":       proses["tanggal"],
                "Start":         _jam(proses["actual_time_start"]),
                "Finish":        _jam(proses["actual_time_finish"]),
                "Operator":      proses["nama"],
                "NIK":           proses["nik"],
                "Part No":       proses["part_no"],
                "Part Name":     proses["part_name"],
                "Model":         proses["model"],
                "Urutan":        proses["urutan_proses"],
                "Line":          proses["actual_line"],
                "Kondisi":       proses["condition"],
                "Sec/Pcs":       proses["sec_pcs"],
                "ACT":           proses["act"],
                "NG":            proses["ng"],
                "% Prod":        proses["persen_prod"],
                "Rasio NG %":    proses["rasio_ng"],
                "Istirahat (m)": proses["total_istirahat"],
                "Total Jam":     proses["total_jam"],
                "Status":        proses["status"],
            })
            st.dataframe(
                tabel, hide_index=True, width="stretch", height=520,
                column_config={
                    "% Prod":     st.column_config.NumberColumn(format="%.2f%%"),
                    "Rasio NG %": st.column_config.NumberColumn(format="%.2f%%"),
                    "Total Jam":  st.column_config.NumberColumn(format="%.2f"),
                    "Sec/Pcs":    st.column_config.NumberColumn(format="%.2f"),
                },
            )
            st.download_button("⬇️ Download CSV Hasil Proses", data=_csv(tabel),
                               file_name=f"laporan_proses_{tgl_awal}_{tgl_akhir}.csv",
                               mime="text/csv", width="stretch")

    # ---------------- Tab: abnormal ----------------
    with tab_a:
        if abnormal.empty:
            st.info("Belum ada data abnormal untuk filter ini.")
        else:
            rekap_kode = (abnormal.groupby(["kode_abnormal", "uraian_abnormal"], dropna=False)["total_waktu"]
                          .agg(["count", "sum"]).reset_index()
                          .rename(columns={"kode_abnormal": "Kode", "uraian_abnormal": "Uraian",
                                           "count": "Kejadian", "sum": "Total Menit"})
                          .sort_values("Total Menit", ascending=False))
            c_grafik, c_rekap = st.columns([3, 2], gap="medium")
            with c_grafik:
                st.bar_chart(rekap_kode, x="Kode", y="Total Menit", color=ui.ACCENT, height=280)
            with c_rekap:
                st.dataframe(rekap_kode, hide_index=True, width="stretch", height=280)

            tabel_ab = pd.DataFrame({
                "Tanggal":    abnormal["tanggal"],
                "Jam":        abnormal["jam_input"].astype(str).str[:5],
                "Operator":   abnormal["operator"],
                "Mesin":      abnormal["mesin"],
                "Part No":    abnormal["part_no"],
                "Part Name":  abnormal["part_name"],
                "Urutan":     abnormal["urutan_proses"],
                "Kode":       abnormal["kode_abnormal"],
                "Uraian":     abnormal["uraian_abnormal"],
                "Menit":      abnormal["total_waktu"],
                "Keterangan": abnormal["keterangan"],
            })
            st.dataframe(tabel_ab, hide_index=True, width="stretch", height=420)
            st.download_button("⬇️ Download CSV Abnormal", data=_csv(tabel_ab),
                               file_name=f"laporan_abnormal_{tgl_awal}_{tgl_akhir}.csv",
                               mime="text/csv", width="stretch")

    # ---------------- Tab: rekap operator ----------------
    with tab_o:
        if selesai.empty:
            st.info("Belum ada laporan FINISH untuk filter ini.")
        else:
            rekap_op = (selesai.groupby(["nama", "nik"])
                        .agg(Laporan=("id", "count"), ACT=("act", "sum"), NG=("ng", "sum"),
                             Rata_Prod=("persen_prod", "mean"), Total_Jam=("total_jam", "sum"))
                        .reset_index())
            rekap_op["Rasio NG %"] = (rekap_op["NG"] / rekap_op["ACT"].where(rekap_op["ACT"] > 0) * 100).round(2)
            rekap_op = rekap_op.rename(columns={"nama": "Operator", "nik": "NIK", "Rata_Prod": "Rata-rata % Prod",
                                                "Total_Jam": "Total Jam"}).sort_values("ACT", ascending=False)
            st.dataframe(
                rekap_op, hide_index=True, width="stretch",
                column_config={
                    "Rata-rata % Prod": st.column_config.NumberColumn(format="%.1f%%"),
                    "Rasio NG %":       st.column_config.NumberColumn(format="%.2f%%"),
                    "Total Jam":        st.column_config.NumberColumn(format="%.2f"),
                },
            )
            st.download_button("⬇️ Download CSV Rekap Operator", data=_csv(rekap_op),
                               file_name=f"rekap_operator_{tgl_awal}_{tgl_akhir}.csv",
                               mime="text/csv", width="stretch")

    # ---------------- Tab: rekap part ----------------
    with tab_part:
        if selesai.empty:
            st.info("Belum ada laporan FINISH untuk filter ini.")
        else:
            rekap_part = (selesai.groupby(["part_no", "part_name", "urutan_proses"], dropna=False)
                          .agg(Laporan=("id", "count"), ACT=("act", "sum"), NG=("ng", "sum"),
                               Rata_Prod=("persen_prod", "mean"), Total_Jam=("total_jam", "sum"))
                          .reset_index())
            rekap_part["Rasio NG %"] = (rekap_part["NG"] / rekap_part["ACT"].where(rekap_part["ACT"] > 0) * 100).round(2)
            rekap_part = rekap_part.rename(columns={"part_no": "Part No", "part_name": "Part Name",
                                                    "urutan_proses": "Urutan", "Rata_Prod": "Rata-rata % Prod",
                                                    "Total_Jam": "Total Jam"}).sort_values("ACT", ascending=False)
            st.dataframe(
                rekap_part, hide_index=True, width="stretch",
                column_config={
                    "Rata-rata % Prod": st.column_config.NumberColumn(format="%.1f%%"),
                    "Rasio NG %":       st.column_config.NumberColumn(format="%.2f%%"),
                    "Total Jam":        st.column_config.NumberColumn(format="%.2f"),
                },
            )
            st.download_button("⬇️ Download CSV Rekap Part", data=_csv(rekap_part),
                               file_name=f"rekap_part_{tgl_awal}_{tgl_akhir}.csv",
                               mime="text/csv", width="stretch")
