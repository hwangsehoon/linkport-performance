# -*- coding: utf-8 -*-
"""
LINKPORT 성과 분석 대시보드 (개인용, 독립 앱)

광고일지 대시보드와 같은 Supabase DB를 읽는다.
  - daily_performance : 일별 원시 카운트 (비율은 집계 후 재계산)
  - repeat_timing     : 브랜드·채널별 재구매 타이밍
  - marketing_events  : 마케팅 이벤트 (시작/중단/변경)

데이터 갱신: 광고일지 폴더에서 `python build_performance.py`
실행: streamlit run app.py   (또는 실행.bat)
"""
import os

import pandas as pd
import plotly.graph_objects as go
import psycopg2
import streamlit as st
from dotenv import load_dotenv
from plotly.subplots import make_subplots

from ui_korean_calendar import korean_calendar

load_dotenv()
st.set_page_config(page_title="성과 분석 | LINKPORT", page_icon="📈", layout="wide")


def _secret(name):
    """배포(Streamlit Cloud)는 st.secrets, 로컬은 .env(os.environ)에서 읽는다."""
    try:
        if name in st.secrets:
            return st.secrets[name]
    except Exception:
        pass
    return os.getenv(name)


def _require_password():
    """공개 URL 보호용 비밀번호 게이트. APP_PASSWORD 미설정 시(로컬) 그냥 통과."""
    pw_conf = _secret("APP_PASSWORD")
    if not pw_conf:                      # 로컬 등 비번 미설정 → 잠그지 않음
        return
    if st.session_state.get("auth_ok"):
        return
    st.markdown("### 🔒 성과 분석")
    entered = st.text_input("비밀번호", type="password")
    if entered:
        if entered == pw_conf:
            st.session_state["auth_ok"] = True
            st.rerun()
        else:
            st.error("비밀번호가 틀렸습니다.")
    st.stop()


_require_password()
korean_calendar()   # date_input 달력 월/요일 한글화

_orig_chart = st.plotly_chart
def _chart(fig, **kw):
    cfg = kw.get("config") or {}
    cfg.setdefault("displayModeBar", False)
    kw["config"] = cfg
    return _orig_chart(fig, **kw)
st.plotly_chart = _chart

# ══════════════════════════════════════════════
# 디자인 시스템 (LINKPORT 톤)
# ══════════════════════════════════════════════
st.markdown("""
<style>
    @import url('https://fonts.googleapis.com/css2?family=Noto+Sans+KR:wght@300;400;500;600;700&display=swap');
    .stApp, [data-testid="stAppViewContainer"] { background-color:#FAF9F6 !important; }
    section[data-testid="stSidebar"] > div:first-child { background:#2D2B28 !important; }
    section[data-testid="stSidebar"] * { color:#E8E4DE !important; }
    html, body, [class*="css"], [data-testid="stMarkdown"], input, button, select, textarea,
    h1,h2,h3,h4,h5,h6, p, div, label { font-family:'Noto Sans KR', sans-serif !important; }
    span:not([data-testid="stIconMaterial"]) { font-family:'Noto Sans KR', sans-serif !important; }
    h1 { color:#2D2B28 !important; font-weight:700 !important; font-size:1.8rem !important; }
    hr { border-color:#E8E4DE !important; }
    .section-title { color:#2D2B28; font-size:1.05rem; font-weight:600;
        margin:28px 0 16px; padding-bottom:8px;
        border-bottom:2px solid #D97757; display:inline-block; }
    .card { background:#FFFFFF; border:1px solid #E8E4DE; border-radius:14px;
        padding:16px 20px; box-shadow:0 1px 3px rgba(45,43,40,.06); }
    .stPlotlyChart { background:#FFFFFF; border-radius:12px; padding:8px;
        border:1px solid #E8E4DE; transition:box-shadow .2s; }
    .stPlotlyChart:hover { box-shadow:0 4px 12px rgba(45,43,40,.08); }
    [data-testid="column"] { padding:0 6px; }
    table.dt { width:100%; border-collapse:collapse; font-size:.9rem; }
    table.dt th { padding:8px; text-align:right; color:#8C8680; font-weight:500;
        font-size:.78rem; border-bottom:2px solid #E0DBD2; }
    table.dt th:first-child { text-align:left; }
    table.dt td { padding:8px; text-align:right; color:#2D2B28;
        border-bottom:1px solid #ECECEC; font-variant-numeric:tabular-nums; }
    table.dt td:first-child { text-align:left; font-weight:600; }
    div[data-baseweb="popover"] ul[role="listbox"], ul[data-baseweb="menu"] { max-height:none !important; }
</style>
""", unsafe_allow_html=True)

PLOT_FONT = dict(color="#3D3B38", family="Noto Sans KR")
HOVER = dict(bgcolor="rgba(45,43,40,0.95)", font_size=12, font_color="#FAF9F6",
             bordercolor="#D97757", font_family="Noto Sans KR")
EVC = {"시작": "#2F7D4A", "중단": "#B1442F", "변경": "#8C8680"}
SUMCOLS = ["방문자", "주문", "매출", "광고비", "기타광고비", "전환매출",
           "식별주문", "재구매주문", "검색량", "블로그방문자"]


def theme(fig):
    fig.update_layout(
        plot_bgcolor="#FAF9F6", paper_bgcolor="#FFFFFF", font=PLOT_FONT,
        margin=dict(l=20, r=20, t=30, b=20), hoverlabel=HOVER,
        legend=dict(orientation="h", yanchor="bottom", y=1.02, x=0,
                    font=dict(size=11, color="#8C8680"), bgcolor="rgba(0,0,0,0)"),
        xaxis=dict(type="category", gridcolor="#E8E4DE", showline=False, color="#3D3B38"),
        yaxis=dict(gridcolor="#E8E4DE", zeroline=False, color="#3D3B38"))
    return fig


# ══════════════════════════════════════════════
# 데이터
# ══════════════════════════════════════════════
@st.cache_data(ttl=300, show_spinner="데이터 불러오는 중...")
def load():
    conn = psycopg2.connect(_secret("SUPABASE_DB_URL"), connect_timeout=10)
    dp = pd.read_sql_query("SELECT * FROM daily_performance ORDER BY 날짜", conn)
    rt = pd.read_sql_query("SELECT * FROM repeat_timing", conn)
    try:
        ev = pd.read_sql_query("SELECT 날짜,구분,채널,내용 FROM marketing_events ORDER BY 날짜", conn)
    except Exception:
        ev = pd.DataFrame(columns=["날짜", "구분", "채널", "내용"])
    conn.close()
    dp["날짜"] = pd.to_datetime(dp["날짜"])
    return dp, rt, ev


def bucket_key(ts, unit):
    if unit == "일":
        return ts.strftime("%Y-%m-%d")
    if unit == "주":
        return (ts - pd.Timedelta(days=ts.weekday())).strftime("%Y-%m-%d")
    return ts.strftime("%Y-%m")


def aggregate(dp, unit):
    """일/주/월 집계. 비율(전환율·ROAS·재구매율)은 합계로 재계산해야 정확."""
    d = dp.copy()
    d["키"] = d["날짜"].apply(lambda t: bucket_key(t, unit))
    if unit == "일":
        d["구간"] = d["날짜"].dt.strftime("%m/%d")
    elif unit == "주":
        mon = d["날짜"] - pd.to_timedelta(d["날짜"].dt.weekday, unit="D")
        d["구간"] = mon.dt.strftime("%m/%d") + "~"
    else:
        d["구간"] = d["날짜"].dt.strftime("%Y-%m")
    g = d.groupby(["키", "구간"], as_index=False)[SUMCOLS].sum().sort_values("키")
    # 분모 0은 .where로 NaN 처리 — replace(0, pd.NA)는 int 컬럼을 object dtype으로 만들어
    # 뒤따르는 .round()가 TypeError를 낸다.
    def _ratio(num, den, pct=True):
        r = g[num] / g[den].where(g[den] > 0)
        return (r * 100).round(2) if pct else r.round(1)

    g["전환율"] = _ratio("주문", "방문자").fillna(0)
    g["총마케팅비"] = g["광고비"] + g["기타광고비"]
    # 웰바이오젠은 ads.전환매출이 전 기간 0(브랜드검색/파워링크에 전환추적 미설치).
    # 전환매출÷광고비로 두면 항상 0%이므로 매출 기준 '배수'로 본다.
    # 마케팅비 0인 구간은 0배가 아니라 '정의 불가' → NaN으로 두어 선을 끊는다.
    g["roas"] = _ratio("매출", "총마케팅비", pct=False)
    g["재구매주문율"] = _ratio("재구매주문", "식별주문").fillna(0)
    return g.reset_index(drop=True)


def fmt_roas(v):
    """배수 표기. 2.8× / 439× / 값 없으면 —"""
    if pd.isna(v):
        return "—"
    return f"{v:,.1f}×" if v < 10 else f"{v:,.0f}×"


def mark_events(fig, ev, keys, unit):
    """집계 구간에 해당하는 이벤트를 점선으로"""
    if ev.empty:
        return fig
    kmap = dict(zip(keys["키"], keys["구간"]))
    for _, e in ev.iterrows():
        k = bucket_key(pd.Timestamp(e["날짜"]), unit)
        if k in kmap:
            fig.add_vline(x=kmap[k], line=dict(color=EVC.get(e["구분"], "#8C8680"),
                                               width=1.4, dash="dot"), opacity=.75)
    return fig


# ══════════════════════════════════════════════
with st.sidebar:
    st.markdown("<div style='text-align:center;padding:18px 0 8px;'>"
                "<div style='font-weight:700;letter-spacing:.14em;font-size:1rem;'>LINKPORT</div>"
                "<div style='letter-spacing:.2em;font-size:.6rem;color:#8C8680;margin-top:4px;'>"
                "PERFORMANCE</div></div>", unsafe_allow_html=True)
    st.divider()
    if st.button("🔄 새로고침", use_container_width=True):
        st.cache_data.clear(); st.rerun()
    st.caption("데이터 갱신: 광고일지 폴더에서\n`python build_performance.py`")

try:
    dp, rt, ev = load()
except Exception as e:
    st.error(f"DB 연결 실패: {e}"); st.stop()
if dp.empty:
    st.warning("데이터 없음. `python build_performance.py` 를 먼저 실행하세요."); st.stop()

st.markdown("<h1>성과 분석 <span style='font-size:1.1rem;color:#D97757;"
            "font-weight:600;'>웰바이오젠</span></h1>", unsafe_allow_html=True)
st.caption("방문자 · 전환율 · 재구매율 · 검색량 · 블로그 — 자동화 이후 효율 변화 "
           "· 매출/방문자/마케팅비 모두 웰바이오젠 기준 "
           "· ROAS = 매출 ÷ 총마케팅비 (배수). 웰바이오젠 SA·Meta는 전환추적이 없어 "
           "전환매출 기준 ROAS를 쓸 수 없음. 마케팅비 0인 구간은 '—'")

# ── 컨트롤: 집계 단위 + 기간 ──────────────────
_min, _max = dp["날짜"].min().date(), dp["날짜"].max().date()
c_u, c_p, c_f, c_t = st.columns([1.1, 1.4, 1.1, 1.1])
with c_u:
    unit = st.radio("집계 단위", ["일", "주", "월"], index=2, horizontal=True)
# 방문자·광고비는 2026-01부터 존재 → 기본은 그 구간(올해)으로 열어 0행 노이즈 방지
PRESET = {"최근 30일": 30, "최근 90일": 90, "최근 180일": 180, "올해": "YTD",
          "최근 1년": 365, "전체": None, "직접 설정": -1}
with c_p:
    preset = st.selectbox("기간", list(PRESET), index=3)
if preset == "직접 설정":
    with c_f:
        d_from = st.date_input("시작", max(_min, _max - pd.Timedelta(days=90)),
                               min_value=_min, max_value=_max, format="YYYY/MM/DD")
    with c_t:
        d_to = st.date_input("종료", _max, min_value=_min, max_value=_max, format="YYYY/MM/DD")
elif PRESET[preset] is None:
    d_from, d_to = _min, _max
elif PRESET[preset] == "YTD":
    d_from, d_to = max(_min, pd.Timestamp(year=_max.year, month=1, day=1).date()), _max
else:
    d_from, d_to = max(_min, _max - pd.Timedelta(days=PRESET[preset])), _max

sel = dp[(dp["날짜"].dt.date >= d_from) & (dp["날짜"].dt.date <= d_to)]
if sel.empty:
    st.info("선택 기간에 데이터가 없습니다."); st.stop()
d = aggregate(sel, unit)
first, last = d.iloc[0], d.iloc[-1]


def delta(cur, base, invert=False):
    if not base:
        return "<span style='color:#8C8680;'>—</span>"
    p = (cur - base) / base * 100
    good = (p < 0) if invert else (p > 0)
    return f"<span style='color:{'#2F7D4A' if good else '#B1442F'};font-weight:600;'>{p:+.0f}%</span>"


# ── 헤드라인 ──────────────────────────────────
cells = [
    ("광고비 (유료)", f"₩{int(last['광고비']):,}", delta(last["광고비"], first["광고비"], invert=True)),
    ("총 마케팅비", f"₩{int(last['총마케팅비']):,}",
     delta(last["총마케팅비"], first["총마케팅비"], invert=True)),
    ("전환율", f"{last['전환율']:.2f}%", delta(last["전환율"], first["전환율"])),
    ("재구매율", f"{last['재구매주문율']:.2f}%", delta(last["재구매주문율"], first["재구매주문율"])),
    ("검색량 (활신경제)", f"{int(last['검색량']):,}", delta(last["검색량"], first["검색량"])),
    ("블로그 방문자", f"{int(last['블로그방문자']):,}", delta(last["블로그방문자"], first["블로그방문자"])),
]
inner = "".join(f"<div><div style='color:#8C8680;font-size:.76rem;'>{k}</div>"
                f"<div style='font-size:1.25rem;font-weight:700;color:#2D2B28;'>{v}</div>"
                f"<div style='font-size:.78rem;'>{dd}</div></div>" for k, v, dd in cells)
st.markdown(f"<div class='card' style='margin:10px 0 20px;'>"
            f"<div style='color:#8C8680;font-size:.8rem;letter-spacing:.04em;'>"
            f"{first['구간']} → {last['구간']} 변화 · {unit} 단위 · "
            f"{d_from} ~ {d_to}</div>"
            f"<div style='display:flex;gap:30px;flex-wrap:wrap;margin-top:12px;'>{inner}</div></div>",
            unsafe_allow_html=True)

# ── 마케팅 이벤트 ─────────────────────────────
evs = ev[(pd.to_datetime(ev["날짜"]).dt.date >= d_from) &
         (pd.to_datetime(ev["날짜"]).dt.date <= d_to)] if not ev.empty else ev
if not evs.empty:
    st.markdown('<div class="section-title">마케팅 이벤트</div>', unsafe_allow_html=True)
    chips = ""
    for _, e in evs.iterrows():
        col = EVC.get(e["구분"], "#8C8680")
        chips += (f"<div style='display:flex;align-items:center;gap:10px;padding:7px 0;"
                  f"border-bottom:1px solid #ECECEC;'>"
                  f"<span style='color:{col};font-size:1rem;'>●</span>"
                  f"<span style='font-variant-numeric:tabular-nums;color:#8C8680;font-size:.84rem;"
                  f"min-width:92px;'>{e['날짜']}</span>"
                  f"<span style='background:{col}1A;color:{col};padding:1px 9px;border-radius:999px;"
                  f"font-size:.74rem;font-weight:600;min-width:44px;text-align:center;'>{e['구분']}</span>"
                  f"<span style='font-weight:600;color:#2D2B28;min-width:64px;'>{e['채널']}</span>"
                  f"<span style='color:#3D3B38;font-size:.9rem;'>{e['내용']}</span></div>")
    st.markdown(f"<div class='card'>{chips}</div>", unsafe_allow_html=True)
    st.caption("아래 차트의 점선 = 해당 이벤트가 있던 구간 (초록=시작 · 빨강=중단)")

# ── 표 ────────────────────────────────────────
st.markdown(f'<div class="section-title">{unit}별 지표</div>', unsafe_allow_html=True)
rows = ""
for _, r in d.iloc[::-1].iterrows():          # 최근이 위로
    rr = float(r["재구매주문율"])
    rc = "#2F7D4A" if rr >= 10 else "#2D2B28"
    rows += (f"<tr><td>{r['구간']}</td>"
             f"<td>{int(r['방문자']):,}</td><td>{int(r['주문']):,}</td>"
             f"<td style='font-weight:600;'>{r['전환율']:.2f}%</td>"
             f"<td>₩{int(r['매출']):,}</td><td>₩{int(r['광고비']):,}</td>"
             f"<td>₩{int(r['기타광고비']):,}</td><td>₩{int(r['총마케팅비']):,}</td>"
             f"<td>{fmt_roas(r['roas'])}</td>"
             f"<td style='font-weight:700;color:{rc};'>{rr:.2f}%</td>"
             f"<td>{int(r['검색량']):,}</td><td>{int(r['블로그방문자']):,}</td></tr>")
head = "".join(f"<th>{h}</th>" for h in
               ["방문자", "주문", "전환율", "매출", "광고비", "기타광고비", "총마케팅비",
                "ROAS(배수)", "재구매율", "검색량", "블로그"])
st.markdown(f"<div style='overflow-x:auto;max-height:460px;'>"
            f"<table class='dt'><thead><tr><th>{unit}</th>{head}</tr></thead>"
            f"<tbody>{rows}</tbody></table></div>", unsafe_allow_html=True)

# ── 차트 ──────────────────────────────────────
st.markdown('<div class="section-title">추이</div>', unsafe_allow_html=True)
x = d["구간"]

# 구간이 많으면(일 단위 등) 라벨이 서로 겹쳐 못 읽는다 → 적을 때만 수치를 찍는다
SHOW_LABELS = len(d) <= 14


def bar_text(series):
    """막대 위 수치. 0은 라벨을 비운다(막대 없음이 이미 0을 말해줌)."""
    if not SHOW_LABELS:
        return None
    return [f"{int(v):,}" if v else "" for v in series]


def headroom(series, pad=1.18):
    """라벨이 위쪽 테두리에 잘리지 않도록 y축 상단 여유."""
    top = float(max(series)) if len(series) else 0
    return [0, top * pad] if top > 0 else None


c1, c2 = st.columns(2)
with c1:
    f = make_subplots(specs=[[{"secondary_y": True}]])
    f.add_trace(go.Bar(x=x, y=d["광고비"], name="광고비(유료)", marker_color="#B8B2AA", opacity=.85,
                       hovertemplate="%{x}<br>광고비 ₩%{y:,.0f}<extra></extra>"), secondary_y=False)
    f.add_trace(go.Bar(x=x, y=d["기타광고비"], name="기타 광고비", marker_color="#D4C09A", opacity=.85,
                       hovertemplate="%{x}<br>기타 광고비 ₩%{y:,.0f}<extra></extra>"), secondary_y=False)
    _r = go.Scatter(x=x, y=d["roas"], name="ROAS",
                    mode="lines+text" if SHOW_LABELS else "lines",
                    line=dict(color="#D97757", width=2.5),
                    connectgaps=False,          # 마케팅비 0 구간은 선을 끊는다
                    hovertemplate="%{x}<br>ROAS %{y:,.1f}배<extra></extra>")
    if SHOW_LABELS:
        _r.update(text=[fmt_roas(v) for v in d["roas"]], textposition="top center",
                  textfont=dict(size=10, color="#B1442F", family="Noto Sans KR"))
    f.add_trace(_r, secondary_y=True)
    f.update_yaxes(title_text="마케팅비", secondary_y=False)
    # 2.8배 ~ 574배까지 두 자릿수 차이 → 로그축이 아니면 앞쪽 달이 바닥에 붙는다
    f.update_yaxes(title_text="ROAS (배수, 로그축)", type="log", secondary_y=True)
    f = theme(f); f.update_layout(height=310, barmode="stack")
    st.plotly_chart(mark_events(f, ev, d, unit), use_container_width=True)
with c2:
    f = go.Figure()
    _c = go.Scatter(x=x, y=d["전환율"], name="전환율",
                    mode="lines+text" if SHOW_LABELS else "lines",
                    line=dict(color="#7B8DBF", width=2.5),
                    hovertemplate="%{x}<br>전환율 %{y:.2f}%<extra></extra>")
    _p = go.Scatter(x=x, y=d["재구매주문율"], name="재구매율",
                    mode="lines+text" if SHOW_LABELS else "lines",
                    line=dict(color="#4A8C5F", width=2.5),
                    hovertemplate="%{x}<br>재구매율 %{y:.2f}%<extra></extra>")
    if SHOW_LABELS:
        # 두 선이 교차하므로 위/아래로 갈라 붙인다
        _c.update(text=[f"{v:.2f}%" for v in d["전환율"]], textposition="bottom center",
                  textfont=dict(size=10, color="#5A6B99", family="Noto Sans KR"))
        _p.update(text=[f"{v:.2f}%" for v in d["재구매주문율"]], textposition="top center",
                  textfont=dict(size=10, color="#2F7D4A", family="Noto Sans KR"))
    f.add_trace(_c); f.add_trace(_p)
    f = theme(f)
    _hi = max(d["전환율"].max(), d["재구매주문율"].max())
    f.update_layout(height=310, yaxis=dict(title="비율 (%)", ticksuffix="%",
                                           gridcolor="#E8E4DE", zeroline=False,
                                           range=[0, _hi * 1.18] if SHOW_LABELS else None))
    st.plotly_chart(mark_events(f, ev, d, unit), use_container_width=True)

c3, c4 = st.columns(2)
with c3:
    f = go.Figure(go.Bar(x=x, y=d["검색량"], marker_color="#D97757",
                         text=bar_text(d["검색량"]),
                         textposition="outside" if SHOW_LABELS else "none",
                         textfont=dict(size=10, color="#3D3B38", family="Noto Sans KR"),
                         cliponaxis=False,
                         hovertemplate="%{x}<br>검색량 %{y:,.0f}<extra></extra>"))
    f = theme(f)
    f.update_layout(height=290, yaxis=dict(title="검색량 (활신경제)",
                                           gridcolor="#E8E4DE", zeroline=False,
                                           range=headroom(d["검색량"]) if SHOW_LABELS else None))
    st.plotly_chart(mark_events(f, ev, d, unit), use_container_width=True)
with c4:
    f = go.Figure(go.Bar(x=x, y=d["블로그방문자"], marker_color="#6B9B7A",
                         text=bar_text(d["블로그방문자"]),
                         textposition="outside" if SHOW_LABELS else "none",
                         textfont=dict(size=10, color="#3D3B38", family="Noto Sans KR"),
                         cliponaxis=False,
                         hovertemplate="%{x}<br>블로그 방문자 %{y:,.0f}명<extra></extra>"))
    f = theme(f)
    f.update_layout(height=290, yaxis=dict(title="블로그 방문자",
                                           gridcolor="#E8E4DE", zeroline=False,
                                           range=headroom(d["블로그방문자"]) if SHOW_LABELS else None))
    st.plotly_chart(mark_events(f, ev, d, unit), use_container_width=True)

# ── 재구매 타이밍 ─────────────────────────────
if not rt.empty:
    st.markdown('<div class="section-title">재구매 타이밍 (첫 구매 → 두 번째 구매)</div>',
                unsafe_allow_html=True)
    tr = ""
    for _, r in rt.sort_values("재구매율", ascending=False).iterrows():
        tr += (f"<tr><td>{r['구분']}</td><td>{int(r['고객']):,}</td><td>{int(r['재구매']):,}</td>"
               f"<td style='font-weight:700;color:#2F7D4A;'>{r['재구매율']:.2f}%</td>"
               f"<td>{r['평균일']:.0f}일</td>"
               f"<td style='font-weight:600;'>{int(r['중앙값일'])}일</td>"
               f"<td>{r['d30']:.0f}%</td><td>{r['d90']:.0f}%</td><td>{r['d180']:.0f}%</td></tr>")
    th = "".join(f"<th>{h}</th>" for h in
                 ["고객", "재구매", "재구매율", "평균", "중앙값", "30일내", "90일내", "180일내"])
    st.markdown(f"<div style='overflow-x:auto;'><table class='dt'>"
                f"<thead><tr><th>구분</th>{th}</tr></thead><tbody>{tr}</tbody></table></div>",
                unsafe_allow_html=True)
    st.caption("※ 웰바이오젠(카페24) 주문만. 고객 식별은 주문자 휴대폰 기준(수령자 아님). "
               "위 월별 재구매율은 해당 기간 주문 기준이고, 이 표는 전체 주문 이력 기준이라 값이 다르다.")
