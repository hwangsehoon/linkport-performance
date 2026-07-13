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
    # 반품·취소 (웰바이오젠 카페24만) — 이 대시보드는 웰바이오젠 전용
    try:
        rr = pd.read_sql_query(
            "SELECT 년,월,구매건수,반품건수,COALESCE(취소건수,0) AS 취소건수 "
            "FROM monthly_returns WHERE 채널='카페24' AND 브랜드='웰바이오젠' "
            "ORDER BY 년,월", conn)
    except Exception:
        rr = pd.DataFrame(columns=["년", "월", "구매건수", "반품건수", "취소건수"])
    conn.close()
    dp["날짜"] = pd.to_datetime(dp["날짜"])
    return dp, rt, ev, rr


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
    dp, rt, ev, rr = load()
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

# ── 자동 점검 · 피드백 ────────────────────────
def _pc(cur, prev):
    if prev is None or pd.isna(prev) or prev == 0:
        return None
    return (cur - prev) / prev * 100


def _sig(p):
    return "—" if p is None else f"{p:+.0f}%"


def build_insights(d, unit, last_date, today):
    """집계된 d에서 실제 수치로 점검·피드백 문장을 생성한다(계산 기반이라 항상 정확).
    반환: [(아이콘, 색, HTML문장)]"""
    import calendar
    from datetime import timedelta
    if len(d) < 2:
        return [("ℹ️", "#8C8680", "비교할 이전 구간이 없어 점검을 생략합니다. 기간을 넓혀 보세요.")]

    # 마지막 구간이 '진행 중'(일=오늘 / 주=이번주 / 월=이번달)이면 총량 비교에서 제외.
    # last_date=데이터 최종일, today=실제 오늘 → 마지막 구간의 기간 끝이 오늘 이후면 진행 중.
    if unit == "일":
        period_end = last_date
    elif unit == "주":
        period_end = last_date + timedelta(days=6 - last_date.weekday())   # 그 주 일요일
    else:
        period_end = last_date.replace(
            day=calendar.monthrange(last_date.year, last_date.month)[1])
    partial = d.iloc[-1] if today <= period_end else None
    idx = -2 if partial is not None else -1
    if len(d) + idx < 1:
        return [("ℹ️", "#8C8680", "진행 중 구간을 빼면 비교할 완료 구간이 부족합니다. 기간을 넓혀 보세요.")]
    cur, prev = d.iloc[idx], d.iloc[idx - 1]
    _uw_neun = {"일": "이 날은", "주": "이번 주는", "월": "이번 달은"}.get(unit, "이 구간은")
    _uw_ga = {"일": "이 날이", "주": "이번 주가", "월": "이번 달이"}.get(unit, "이 구간이")
    out = []

    # 1) 매출 요인 분해 — 끌어내린 요인 vs 밀어올린 요인 (방향까지 설명)
    rev_p = _pc(cur["매출"], prev["매출"])
    vis_p = _pc(cur["방문자"], prev["방문자"])
    cr_p = _pc(cur["전환율"], prev["전환율"])
    aov_c = cur["매출"] / cur["주문"] if cur["주문"] else 0
    aov_p = prev["매출"] / prev["주문"] if prev["주문"] else 0
    aovp = _pc(aov_c, aov_p)
    # 매출 = 방문수 × 전환율 × 객단가. 상대%로 순위(요인 기여)를 매기되,
    # 전환율은 그 자체가 %라 '-9%'가 오해되므로 실제값(13.2%→12.0%)으로 표시한다.
    facs = []
    if vis_p is not None:
        facs.append(("방문", vis_p, _sig(vis_p)))
    if cr_p is not None:
        facs.append(("전환율", cr_p, f"{prev['전환율']:.1f}%→{cur['전환율']:.1f}%"))
    if aovp is not None:
        facs.append(("객단가", aovp, _sig(aovp)))
    if rev_p is not None and facs:
        ups = sorted([f for f in facs if f[1] > 0], key=lambda x: -x[1])
        downs = sorted([f for f in facs if f[1] < 0], key=lambda x: x[1])
        col = "#2F7D4A" if rev_p >= 0 else "#B1442F"
        if rev_p >= 0:
            lead = f"<b>{ups[0][0]} {ups[0][2]}</b> 덕분에 매출이 올랐습니다" if ups else "요인 혼조"
            tail = f" ({downs[0][0]} {downs[0][2]} 부진에도)" if downs else ""
        else:
            lead = f"<b>{downs[0][0]} {downs[0][2]}</b> 때문에 매출이 빠졌습니다" if downs else "요인 혼조"
            tail = f" ({ups[0][0]} {ups[0][2]}로 낙폭 일부 방어)" if ups else ""
        out.append(("💰", col,
            f"<b>매출 {_sig(rev_p)}</b> ({int(prev['매출']):,}→{int(cur['매출']):,}): {lead}{tail}."))

    # 2) 블로그 유입 → 성과 연결 (초기 구간은 %가 과장되므로 절대값)
    bc, bp = cur["블로그방문자"], prev["블로그방문자"]
    if bc >= 3000 or bp >= 3000:
        if bp >= 3000:                       # 비교 가능한 규모 → % 사용
            blog_p = _pc(bc, bp)
            if blog_p is not None and blog_p > 10 and (cr_p is None or cr_p <= 2):
                out.append(("🔎", "#B8860B",
                    f"블로그 방문자는 {_sig(blog_p)} 늘었지만 전환율은 "
                    f"{prev['전환율']:.1f}%→{cur['전환율']:.1f}%로 나아지지 않았습니다 — "
                    f"<b>유입이 아직 매출로 뚜렷이 이어지진 않았습니다</b>. 유입→구매 경로 점검."))
            elif blog_p is not None and abs(blog_p) >= 10:
                out.append(("🔎", "#3D3B38",
                    f"블로그 방문자 {int(bp):,}→{int(bc):,}명({_sig(blog_p)})."))
        else:                                # 직전이 초기 시작 구간
            out.append(("🔎", "#3D3B38",
                f"블로그 방문자 {int(bp):,}→{int(bc):,}명으로 확대(직전은 시작 초기라 %는 생략)."))

    # 3) 재구매율 점검 — 분모(식별주문)와 분자(재구매 건수)를 함께 본다 ★사용자 요청
    rr_p = _pc(cur["재구매주문율"], prev["재구매주문율"])
    id_p = _pc(cur["식별주문"], prev["식별주문"])
    rc_p = _pc(cur["재구매주문"], prev["재구매주문"])
    if rr_p is not None and rr_p >= 5:
        denom_shrink = id_p is not None and id_p < -5
        numer_grow = rc_p is not None and rc_p >= 10
        if denom_shrink and numer_grow:
            out.append(("🔁", "#B8860B",
                f"재구매율 {prev['재구매주문율']:.1f}%→{cur['재구매주문율']:.1f}% 상승엔 두 가지가 겹칩니다: "
                f"실제 재구매 건수 증가({int(prev['재구매주문'])}→{int(cur['재구매주문'])}건, {_sig(rc_p)})와 "
                f"전체 식별주문 감소({int(prev['식별주문'])}→{int(cur['식별주문'])}건, {_sig(id_p)}). "
                f"<b>순수 충성도 개선 + 신규 감소 착시가 섞인</b> 수치입니다."))
        elif denom_shrink:
            out.append(("⚠️", "#B1442F",
                f"재구매율이 {prev['재구매주문율']:.1f}%→{cur['재구매주문율']:.1f}%로 올랐지만 재구매 건수는 "
                f"거의 그대로({int(prev['재구매주문'])}→{int(cur['재구매주문'])}건)인데 식별주문이 {_sig(id_p)} 줄었습니다. "
                f"<b>분모 축소 착시</b>일 가능성이 큽니다."))
        else:
            out.append(("🔁", "#2F7D4A",
                f"재구매율 {prev['재구매주문율']:.1f}%→{cur['재구매주문율']:.1f}% 상승. "
                f"식별주문도 유지·증가({_sig(id_p)})라 <b>실질적인 충성도 개선</b>으로 볼 수 있습니다."))

    # 4) ROAS 안정성 (마케팅비 극소면 배수 불안정)
    if pd.notna(cur["roas"]) and cur["총마케팅비"] and cur["총마케팅비"] < 300000:
        out.append(("🧮", "#B8860B",
            f"{_uw_neun} 총마케팅비가 {int(cur['총마케팅비']):,}원으로 매우 작아 "
            f"ROAS({cur['roas']:.0f}배)는 소액 변동에도 크게 흔들립니다. "
            f"'배수'보다 <b>마케팅비를 거의 안 쓰고 매출 {int(cur['매출']):,}원을 유지</b>로 해석하는 편이 안전."))

    # 5) 진행 중 구간 안내
    if partial is not None:
        out.append(("🗓️", "#8C8680",
            f"가장 최근 <b>{partial['구간']}</b>은 아직 진행 중이라 위 비교에서 제외했습니다"
            f"(현재까지 매출 {int(partial['매출']):,}원). {_uw_ga} 끝나면 반영됩니다."))
    return out


st.markdown('<div class="section-title">자동 점검 · 피드백</div>', unsafe_allow_html=True)
_today_kst = pd.Timestamp.now(tz="Asia/Seoul").date()   # 배포(UTC) 서버에서도 한국 날짜 기준
_ins = build_insights(d, unit, _max, _today_kst)
_items = "".join(
    f"<div style='display:flex;gap:10px;padding:9px 0;border-bottom:1px solid #EFEDE9;'>"
    f"<span style='font-size:1rem;'>{ic}</span>"
    f"<span style='color:{co};font-size:.92rem;line-height:1.5;'>{tx}</span></div>"
    for ic, co, tx in _ins)
st.markdown(f"<div class='card' style='margin:2px 0 20px;'>{_items}"
            f"<div style='color:#A8A29E;font-size:.72rem;margin-top:8px;'>"
            f"※ 실제 집계값에서 자동 계산된 점검입니다(추정·생성 아님). "
            f"바로 앞의 완료된 구간과 그 이전 구간을 비교합니다.</div></div>",
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
    _rpr = float(r["재구매주문율"])
    rc = "#2F7D4A" if _rpr >= 10 else "#2D2B28"
    rows += (f"<tr><td>{r['구간']}</td>"
             f"<td>{int(r['방문자']):,}</td><td>{int(r['주문']):,}</td>"
             f"<td style='font-weight:600;'>{r['전환율']:.2f}%</td>"
             f"<td>₩{int(r['매출']):,}</td><td>₩{int(r['광고비']):,}</td>"
             f"<td>₩{int(r['기타광고비']):,}</td><td>₩{int(r['총마케팅비']):,}</td>"
             f"<td>{fmt_roas(r['roas'])}</td>"
             f"<td style='font-weight:700;color:{rc};'>{_rpr:.2f}%</td>"
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

# ── 반품 · 취소 (웰바이오젠) ───────────────────
st.markdown('<div class="section-title">반품 · 취소 (웰바이오젠 카페24)</div>',
            unsafe_allow_html=True)
if rr is None or rr.empty:
    st.caption("반품 데이터가 아직 없습니다. (광고일지 폴더의 로컬 동기화에서 수집됩니다)")
else:
    _rr = rr.copy()
    _rr["ym"] = (_rr["년"].astype(int).astype(str) + "-"
                 + _rr["월"].astype(int).map(lambda m: f"{m:02d}"))
    _lo, _hi = f"{d_from:%Y-%m}", f"{d_to:%Y-%m}"     # 선택 기간에 걸치는 달만
    _rr = _rr[(_rr["ym"] >= _lo) & (_rr["ym"] <= _hi)].sort_values("ym")
    if _rr.empty:
        st.caption("선택 기간에 반품 데이터가 없습니다.")
    else:
        _rr["반품률"] = (_rr["반품건수"] / _rr["구매건수"].where(_rr["구매건수"] > 0) * 100)
        _rows = ""
        for _, r in _rr[::-1].iterrows():
            _rt = r["반품률"]
            _rc = "#B1442F" if (pd.notna(_rt) and _rt >= 5) else "#2D2B28"
            _rows += (f"<tr><td>{r['ym']}</td>"
                      f"<td>{int(r['구매건수']):,}</td>"
                      f"<td>{int(r['반품건수']):,}</td>"
                      f"<td style='font-weight:700;color:{_rc};'>"
                      f"{'—' if pd.isna(_rt) else f'{_rt:.1f}%'}</td>"
                      f"<td style='color:#8C8680;'>{int(r['취소건수']):,}</td></tr>")
        _tb = int(_rr["반품건수"].sum()); _tt = int(_rr["구매건수"].sum())
        _tc = int(_rr["취소건수"].sum())
        _trate = _tb / _tt * 100 if _tt else 0
        _head = "".join(f"<th>{h}</th>" for h in ["구매", "반품", "반품률", "취소"])
        _ct, _cc = st.columns([1, 1])
        with _ct:
            st.markdown(
                f"<div style='overflow-x:auto;'><table class='dt'>"
                f"<thead><tr><th>월</th>{_head}</tr></thead><tbody>{_rows}"
                f"<tr style='border-top:2px solid #E0DBD2;font-weight:700;'>"
                f"<td>합계</td><td>{_tt:,}</td><td>{_tb:,}</td><td>{_trate:.1f}%</td>"
                f"<td style='color:#8C8680;'>{_tc:,}</td></tr>"
                f"</tbody></table></div>", unsafe_allow_html=True)
        with _cc:
            _f = go.Figure(go.Bar(x=_rr["ym"], y=_rr["반품률"].round(1), marker_color="#D97757",
                                  hovertemplate="%{x}<br>반품률 %{y:.1f}%<extra></extra>"))
            _f = theme(_f)
            _f.update_layout(height=280, margin=dict(l=10, r=10, t=20, b=10),
                             yaxis=dict(title="반품률 (%)", ticksuffix="%", gridcolor="#E8E4DE"))
            st.plotly_chart(_f, use_container_width=True)
        st.caption("반품 = 배송 후 실제 반품(반품완료) · 취소 = 결제 후 배송 전 취소. "
                   "입금전취소(미결제)는 구매·반품·취소 모두 제외. 반품률 = 반품 ÷ 구매.")
