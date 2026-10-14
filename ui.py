"""
ui.py — Tema "Industrial Dark / Operator Terminal" dan komponen tampilan.

Hanya urusan tampilan: CSS, top bar, langkah alur kerja, kartu KPI,
panel produksi dengan timer live. Tidak ada logika database di sini.

Cara memberi gaya pada tombol/kontainer Streamlit: pakai `key=`.
Streamlit menambahkan class `st-key-<key>` sehingga bisa ditarget CSS:
  key diawali "go_"    → tombol aksi utama hijau besar (Start, Kirim, Selesai)
  key diawali "stop_"  → tombol bergaris merah (Keluar)
  key diawali "card_"  → kontainer berbentuk kartu
"""
from __future__ import annotations

import html
import time
from datetime import datetime

import streamlit as st
import streamlit.components.v1 as components

# ------------------------------------------------------------------
# Palet (dipakai juga di iframe timer)
# ------------------------------------------------------------------
BG, SURFACE, SURFACE_2 = "#0B0F14", "#121821", "#18212C"
BORDER, BORDER_STRONG = "#263241", "#3A4859"
TEXT, MUTED = "#E6EDF3", "#8B98A9"
ACCENT, ACCENT_INK = "#FFB020", "#1A1200"
OK, OK_INK, DANGER, INFO = "#22C55E", "#03200D", "#EF4444", "#38BDF8"

FONT_IMPORT = (
    "@import url('https://fonts.googleapis.com/css2?"
    "family=Barlow:wght@400;600;700;800&family=JetBrains+Mono:wght@500;700&display=swap');"
)

CSS = f"""
<style>
{FONT_IMPORT}
:root {{
  --bg:{BG}; --surface:{SURFACE}; --surface-2:{SURFACE_2};
  --border:{BORDER}; --border-strong:{BORDER_STRONG};
  --text:{TEXT}; --muted:{MUTED};
  --accent:{ACCENT}; --accent-ink:{ACCENT_INK};
  --ok:{OK}; --ok-ink:{OK_INK}; --danger:{DANGER}; --info:{INFO};
  --radius:14px; --tap:60px; --tap-xl:78px;
  --mono:'JetBrains Mono', ui-monospace, Menlo, monospace;
}}

/* ---------- Dasar ---------- */
html, body, .stApp {{ background:var(--bg) !important; }}
.stApp, .stApp p, .stApp label, .stMarkdown {{ font-family:'Barlow', system-ui, sans-serif; color:var(--text); }}
header[data-testid="stHeader"], [data-testid="stSidebar"], [data-testid="stSidebarCollapsedControl"],
#MainMenu, footer, [data-testid="stDecoration"] {{ display:none !important; }}
.block-container {{ padding:0.9rem 1.2rem 3rem !important; max-width:1180px; }}
h1, h2, h3 {{ font-family:'Barlow', sans-serif; font-weight:800 !important; color:var(--text) !important; letter-spacing:.2px; }}
hr {{ border-color:var(--border) !important; margin:.8rem 0 !important; }}
[data-testid="stWidgetLabel"] p {{
  font-size:14px !important; font-weight:700 !important; color:var(--muted) !important;
  text-transform:uppercase; letter-spacing:.7px;
}}

/* ---------- Tombol: besar & ramah sentuh ---------- */
.stButton > button, [data-testid="stPopover"] > div > button, [data-testid="stPopover"] button {{
  min-height:var(--tap); border-radius:12px !important;
  background:var(--surface-2) !important; color:var(--text) !important;
  border:2px solid var(--border-strong) !important;
  font-weight:800 !important; transition:transform .06s ease, filter .15s ease;
}}
.stButton > button p, [data-testid="stPopover"] button p {{
  font-size:18px !important; font-weight:800 !important; color:inherit !important; letter-spacing:.3px;
}}
.stButton > button:hover {{ filter:brightness(1.12); }}
.stButton > button:active {{ transform:scale(.98); }}
.stButton > button:disabled {{ opacity:.4 !important; }}
.stButton > button[kind="primary"], button[data-testid="stBaseButton-primary"] {{
  background:var(--accent) !important; color:var(--accent-ink) !important; border-color:var(--accent) !important;
}}
[class*="st-key-go_"] button {{
  min-height:var(--tap-xl) !important; background:var(--ok) !important;
  color:var(--ok-ink) !important; border-color:var(--ok) !important;
  box-shadow:0 6px 20px rgba(34,197,94,.18);
}}
[class*="st-key-go_"] button p {{ font-size:22px !important; letter-spacing:.8px; }}
[class*="st-key-stop_"] button {{
  background:transparent !important; color:var(--danger) !important; border-color:var(--danger) !important;
}}

/* ---------- Pilihan berbentuk chip (radio & checkbox) ----------
   Opsi terpilih ditandai lewat :has(input:checked) → selalu terlihat jelas. */
[data-testid="stRadio"] [role="radiogroup"] {{ display:flex; flex-wrap:wrap; gap:10px; }}
[data-testid="stRadio"] label[data-baseweb="radio"],
[data-testid="stCheckbox"] label[data-baseweb="checkbox"] {{
  min-height:58px; min-width:110px; margin:0 !important; padding:0 20px !important;
  display:flex; align-items:center; justify-content:center; gap:10px;
  background:var(--surface-2); border:2px solid var(--border-strong); border-radius:12px;
  cursor:pointer; transition:background .12s, border-color .12s;
}}
[data-testid="stCheckbox"] label[data-baseweb="checkbox"] {{ width:100%; justify-content:flex-start; }}
[data-testid="stRadio"] label[data-baseweb="radio"] > div:first-child {{ display:none; }}   /* sembunyikan bulatan */
[data-testid="stRadio"] label[data-baseweb="radio"] p,
[data-testid="stCheckbox"] label[data-baseweb="checkbox"] p {{
  font-size:19px !important; font-weight:800 !important; color:var(--text) !important; text-transform:none; letter-spacing:.2px;
}}
[data-testid="stRadio"] label[data-baseweb="radio"]:has(input:checked),
[data-testid="stCheckbox"] label[data-baseweb="checkbox"]:has(input:checked) {{
  background:var(--accent); border-color:var(--accent); box-shadow:0 0 0 3px rgba(255,176,32,.25);
}}
[data-testid="stRadio"] label[data-baseweb="radio"]:has(input:checked) p,
[data-testid="stCheckbox"] label[data-baseweb="checkbox"]:has(input:checked) p {{ color:var(--accent-ink) !important; }}
[data-testid="stRadio"] label[data-baseweb="radio"]:has(input:checked) p::before,
[data-testid="stCheckbox"] label[data-baseweb="checkbox"]:has(input:checked) p::before {{ content:"✓ "; }}
[data-testid="stCheckbox"] label[data-baseweb="checkbox"]:has(input:disabled) {{ opacity:.55; }}

/* ---------- Input ---------- */
.stTextInput input, .stNumberInput input {{
  background:#05080C !important; color:var(--text) !important; -webkit-text-fill-color:var(--text) !important;
  min-height:56px; font-size:22px !important; font-family:var(--mono) !important;
}}
.stTextInput > div > div, .stNumberInput > div > div {{
  border:2px solid var(--border) !important; border-radius:10px !important; background:#05080C !important;
}}
.stTextInput > div > div:focus-within, .stNumberInput > div > div:focus-within {{ border-color:var(--accent) !important; }}
.stNumberInput button {{ min-width:52px !important; background:var(--surface-2) !important; color:var(--text) !important; }}
[data-baseweb="select"] > div {{
  background:#05080C !important; min-height:56px; border:2px solid var(--border) !important; border-radius:10px !important;
  font-size:19px !important; font-family:var(--mono);
}}
[data-baseweb="select"] input {{ font-size:19px !important; }}
[data-baseweb="popover"] li {{ min-height:48px; font-size:18px !important; }}

/* ---------- Tabs ---------- */
.stTabs [data-baseweb="tab-list"] {{ gap:8px; border-bottom:2px solid var(--border); }}
.stTabs [data-baseweb="tab"] {{
  min-height:60px; padding:0 22px; background:var(--surface); border-radius:12px 12px 0 0;
}}
.stTabs [data-baseweb="tab"] p {{ font-size:18px !important; font-weight:800 !important; color:var(--muted) !important; }}
.stTabs [aria-selected="true"] {{ background:var(--surface-2) !important; box-shadow:inset 0 -4px 0 var(--accent); }}
.stTabs [aria-selected="true"] p {{ color:var(--accent) !important; }}
.stTabs [data-baseweb="tab-highlight"], .stTabs [data-baseweb="tab-border"] {{ display:none; }}

/* ---------- Kartu, expander, alert ---------- */
[class*="st-key-card_"] {{
  background:var(--surface); border:1px solid var(--border); border-radius:var(--radius); padding:18px 18px 16px;
}}
[data-testid="stExpander"] details {{ background:var(--surface); border:1px solid var(--border) !important; border-radius:12px; }}
[data-testid="stExpander"] summary {{ min-height:56px; }}
[data-testid="stExpander"] summary p {{ font-size:17px !important; font-weight:800 !important; }}
[data-testid="stAlert"] {{ border-radius:12px; }}
[data-testid="stAlert"] p {{ font-size:17px !important; }}
[data-testid="stPopoverBody"] {{ background:var(--surface) !important; border:1px solid var(--border-strong); }}

/* ---------- Komponen HTML kustom ---------- */
.topbar {{
  display:flex; align-items:center; justify-content:space-between; gap:12px; flex-wrap:wrap;
  background:var(--surface); border:1px solid var(--border); border-radius:var(--radius);
  padding:10px 16px; margin-bottom:12px;
}}
.brand {{ display:flex; align-items:center; gap:12px; }}
.brand .mark {{ width:8px; height:34px; border-radius:3px;
  background:repeating-linear-gradient(-45deg, var(--accent) 0 6px, #111 6px 12px); }}
.brand b {{ display:block; font-size:18px; font-weight:800; letter-spacing:.6px; line-height:1.1; }}
.brand small {{ display:block; color:var(--muted); font-size:12px; font-weight:700; letter-spacing:1.2px; }}
.op {{ display:flex; align-items:center; gap:12px; }}
.op .who {{ text-align:right; line-height:1.15; }}
.op .who b {{ display:block; font-size:16px; font-weight:800; }}
.op .who span {{ font-family:var(--mono); font-size:13px; color:var(--muted); }}
.pill {{ display:inline-flex; align-items:center; gap:6px; font-weight:800; font-size:13px; letter-spacing:1.2px;
  padding:7px 12px; border-radius:999px; border:1.5px solid; white-space:nowrap; }}
.pill.idle {{ color:var(--muted); border-color:var(--border-strong); }}
.pill.info {{ color:var(--info); border-color:var(--info); }}
.pill.warn {{ color:var(--accent); border-color:var(--accent); }}
.pill.run  {{ color:var(--ok); border-color:var(--ok); }}
.pill.run::before {{ content:''; width:8px; height:8px; border-radius:50%; background:var(--ok); animation:blink 1.2s infinite; }}
@keyframes blink {{ 50% {{ opacity:.2; }} }}

.steps {{ display:flex; gap:6px; margin:0 0 14px; }}
.step {{ flex:1; padding-top:7px; border-top:4px solid var(--border); text-align:center;
  font-size:12px; font-weight:800; letter-spacing:.8px; text-transform:uppercase; color:var(--muted); }}
.step.done {{ border-color:var(--ok); color:var(--text); }}
.step.now  {{ border-color:var(--accent); color:var(--accent); }}

.sec {{ font-size:13px; font-weight:800; letter-spacing:1.3px; text-transform:uppercase; color:var(--muted); margin:2px 0 10px; }}
.hint {{ color:var(--muted); font-size:15px; margin:-4px 0 10px; }}
.bigname {{ font-size:34px; font-weight:800; line-height:1.1; margin:2px 0; }}
.mono {{ font-family:var(--mono); }}

.kpi-grid {{ display:grid; grid-template-columns:repeat(auto-fit, minmax(150px, 1fr)); gap:10px; margin:10px 0 12px; }}
.kpi {{ background:var(--surface); border:1px solid var(--border); border-radius:12px; padding:12px 14px; min-width:0; }}
.kpi .lbl {{ font-size:12px; font-weight:800; letter-spacing:.9px; text-transform:uppercase; color:var(--muted); }}
.kpi .val {{ font-family:var(--mono); font-size:26px; font-weight:700; line-height:1.25; margin-top:4px;
  color:var(--text); white-space:nowrap; overflow:hidden; text-overflow:ellipsis; }}
.kpi .sub {{ font-size:13px; color:var(--muted); margin-top:2px; }}
.kpi.accent {{ border-color:rgba(255,176,32,.45); }} .kpi.accent .val {{ color:var(--accent); }}
.kpi.ok {{ border-color:rgba(34,197,94,.45); }}      .kpi.ok .val {{ color:var(--ok); }}
.kpi.bad {{ border-color:rgba(239,68,68,.5); }}      .kpi.bad .val {{ color:var(--danger); }}
.kpi.hero .val {{ font-size:34px; }}

@media (max-width:640px) {{
  .block-container {{ padding:.5rem .6rem 3rem !important; }}
  .kpi .val {{ font-size:22px; }} .kpi.hero .val {{ font-size:28px; }}
  .bigname {{ font-size:26px; }} .step {{ font-size:10px; letter-spacing:.3px; }}
  .op .who {{ text-align:left; }}
}}
</style>
"""

STATUS_PILL = {
    "LOGIN":             ("BELUM LOGIN", "idle"),
    "IDLE":              ("SIAP SCAN", "info"),
    "SELECTING_PROCESS": ("PILIH PROSES", "info"),
    "RUNNING":           ("PRODUKSI", "run"),
    "FINISHING":         ("LAPORAN AKHIR", "warn"),
}
LANGKAH = ["Scan ID", "Pilih Part", "Produksi", "Laporan"]
POSISI_LANGKAH = {"LOGIN": 0, "IDLE": 1, "SELECTING_PROCESS": 1, "RUNNING": 2, "FINISHING": 3}


def esc(v) -> str:
    return html.escape(str(v if v is not None else ""))


def terapkan_tema() -> None:
    st.markdown(CSS, unsafe_allow_html=True)


def topbar(tahap: str, nama: str = "", nik: str = "") -> None:
    """Bar atas: merek, operator aktif, status, dan langkah alur kerja."""
    label, cls = STATUS_PILL.get(tahap, ("—", "idle"))
    operator = (
        f'<div class="who"><b>{esc(nama)}</b><span>NIK {esc(nik)}</span></div>' if nama else ""
    )
    posisi = POSISI_LANGKAH.get(tahap, 0)
    langkah = "".join(
        f'<div class="step {"done" if i < posisi else "now" if i == posisi else ""}">{esc(s)}</div>'
        for i, s in enumerate(LANGKAH)
    )
    st.markdown(
        f"""
        <div class="topbar">
          <div class="brand"><div class="mark"></div>
            <div><b>PRESS TERMINAL</b><small>PT INDOSAFETY SENTOSA</small></div></div>
          <div class="op">{operator}<span class="pill {cls}">{label}</span></div>
        </div>
        <div class="steps">{langkah}</div>
        """,
        unsafe_allow_html=True,
    )


def judul(teks: str, hint: str = "") -> None:
    st.markdown(f'<div class="sec">{esc(teks)}</div>' + (f'<div class="hint">{esc(hint)}</div>' if hint else ""),
                unsafe_allow_html=True)


def kpi_grid(items: list[tuple]) -> None:
    """items: (label, nilai, varian='', sub='') — varian: accent | ok | bad | hero."""
    cards = []
    for item in items:
        label, nilai, varian, sub = (list(item) + ["", ""])[:4]
        cards.append(
            f'<div class="kpi {esc(varian)}"><div class="lbl">{esc(label)}</div>'
            f'<div class="val">{esc(nilai)}</div>'
            + (f'<div class="sub">{esc(sub)}</div>' if sub else "")
            + "</div>"
        )
    st.markdown(f'<div class="kpi-grid">{"".join(cards)}</div>', unsafe_allow_html=True)


def panel_produksi(dp: dict, waktu_start: datetime, sudah_start: bool) -> None:
    """
    Panel utama saat RUNNING: nama part besar + timer live.
    Timer berjalan di browser (tanpa rerun) dan dikoreksi ke jam server.
    """
    overtime = dp.get("condition") == "Overtime"
    start_ms = int(waktu_start.timestamp() * 1000)
    server_ms = int(time.time() * 1000)
    label_timer = "WAKTU BERJALAN" if sudah_start else "MENUNGGU START"
    warna_timer = OK if sudah_start else MUTED

    doc = f"""
<style>
{FONT_IMPORT}
* {{ box-sizing:border-box; margin:0; padding:0; }}
body {{ background:transparent; font-family:'Barlow', system-ui, sans-serif; color:{TEXT}; }}
.wrap {{ display:flex; gap:14px; align-items:stretch; background:{SURFACE};
  border:1px solid {BORDER}; border-left:6px solid {ACCENT if overtime else OK};
  border-radius:14px; padding:14px 16px; height:146px; }}
.l {{ flex:1; min-width:0; display:flex; flex-direction:column; justify-content:center; gap:6px; }}
.lbl {{ font-size:12px; font-weight:800; letter-spacing:1.2px; color:{MUTED}; text-transform:uppercase; }}
.name {{ font-size:clamp(18px, 3.4vw, 30px); font-weight:800; line-height:1.1;
  display:-webkit-box; -webkit-line-clamp:2; -webkit-box-orient:vertical; overflow:hidden; }}
.meta {{ font-family:'JetBrains Mono', monospace; font-size:clamp(12px, 2vw, 15px); color:{MUTED};
  white-space:nowrap; overflow:hidden; text-overflow:ellipsis; }}
.badges {{ display:flex; gap:6px; flex-wrap:wrap; }}
.b {{ font-size:12px; font-weight:800; letter-spacing:1px; padding:4px 9px; border-radius:999px;
  border:1.5px solid {BORDER_STRONG}; color:{TEXT}; }}
.b.ot {{ background:{ACCENT}; color:{ACCENT_INK}; border-color:{ACCENT}; }}
.b.nm {{ border-color:{OK}; color:{OK}; }}
.r {{ display:flex; flex-direction:column; justify-content:center; align-items:flex-end; text-align:right; }}
.timer {{ font-family:'JetBrains Mono', monospace; font-weight:700; color:{warna_timer};
  font-size:clamp(30px, 7vw, 58px); line-height:1; letter-spacing:1px; font-variant-numeric:tabular-nums; }}
.since {{ font-size:13px; color:{MUTED}; margin-top:6px; font-family:'JetBrains Mono', monospace; }}
</style>
<div class="wrap">
  <div class="l">
    <div class="lbl">Part aktif · Urutan {esc(dp.get('urutan_proses'))}</div>
    <div class="name">{esc(dp.get('part_name'))}</div>
    <div class="meta">{esc(dp.get('part_no'))} · {esc(dp.get('model'))}</div>
    <div class="badges">
      <span class="b {'ot' if overtime else 'nm'}">{'OVERTIME' if overtime else 'NORMAL'}</span>
      <span class="b">LINE {esc(dp.get('Actual_Line') or '-')}</span>
    </div>
  </div>
  <div class="r">
    <div class="lbl">{label_timer}</div>
    <div class="timer" id="t">{'00:00:00' if sudah_start else '--:--:--'}</div>
    <div class="since">{'Mulai ' + waktu_start.strftime('%H:%M') if sudah_start else 'Tekan START di bawah'}</div>
  </div>
</div>
<script>
  const START = {start_ms}, OFFSET = {server_ms} - Date.now(), JALAN = {'true' if sudah_start else 'false'};
  const p = n => String(n).padStart(2, '0');
  function tick() {{
    if (!JALAN) return;
    const s = Math.max(0, Math.floor((Date.now() + OFFSET - START) / 1000));
    document.getElementById('t').textContent = p(Math.floor(s / 3600)) + ':' + p(Math.floor(s % 3600 / 60)) + ':' + p(s % 60);
  }}
  tick(); setInterval(tick, 1000);
</script>
"""
    components.html(doc, height=152)
