# -*- coding: utf-8 -*-
"""
st.date_input 달력의 영어 표기를 한글로 바꾼다.

Streamlit의 date_input은 baseweb Datepicker를 쓰는데 locale을 노출하지 않아
월/요일이 영어로 나온다("April", "Su Mo Tu ..."). CSS로는 월 이름이 동적이라
바꿀 수 없어서, 부모 문서에 MutationObserver를 걸어 텍스트를 치환한다.

바꾸는 곳 (실제 DOM 확인 후 확정):
  1) 헤더 월 버튼      : [data-baseweb="calendar"] button  "April" → "4월"
  2) 요일 헤더         : 같은 서브트리의 말단 div  "Su" → "일"
  3) 이전/다음 aria-label
  4) 월 선택 드롭다운  : li[role="option"]  ※ calendar 밖 portal로 렌더됨

주의: 월 드롭다운은 calendar 서브트리 밖에 뜨므로 li[role="option"] 전역을 보되,
텍스트가 영어 월 이름과 '정확히' 일치할 때만 치환한다(앱 셀렉트박스는 전부 한글).
"""
import streamlit.components.v1 as components

_JS = """
<script>
(function () {
  const doc = window.parent && window.parent.document;
  if (!doc) return;
  if (doc.__krCalendarPatched) return;   // 리런마다 옵저버가 쌓이는 것 방지
  doc.__krCalendarPatched = true;

  const MON = {January:1, February:2, March:3, April:4, May:5, June:6,
               July:7, August:8, September:9, October:10, November:11, December:12};
  const WK  = {Su:'일', Mo:'월', Tu:'화', We:'수', Th:'목', Fr:'금', Sa:'토'};
  const ARIA = {'Previous month.':'이전 달', 'Next month.':'다음 달',
                'Select a date.':'날짜 선택'};

  let running = false;
  function translate() {
    if (running) return;               // 자기 변경으로 재귀 호출되는 것 방지
    running = true;
    try {
      doc.querySelectorAll('[data-baseweb="calendar"]').forEach(cal => {
        cal.querySelectorAll('button').forEach(b => {
          const t = b.textContent.trim();
          if (MON[t]) b.textContent = MON[t] + '월';
          const al = b.getAttribute('aria-label');
          if (ARIA[al]) b.setAttribute('aria-label', ARIA[al]);
        });
        cal.querySelectorAll('div').forEach(d => {
          if (d.children.length) return;            // 말단 노드만
          const t = d.textContent.trim();
          if (WK[t]) d.textContent = WK[t];
        });
      });
      // 월 선택 드롭다운(포털) — 영어 월 이름과 완전 일치할 때만
      doc.querySelectorAll('li[role="option"]').forEach(li => {
        const t = li.textContent.trim();
        if (MON[t]) li.textContent = MON[t] + '월';
      });
      doc.querySelectorAll('input[aria-label="Select a date."]').forEach(i => {
        i.setAttribute('aria-label', '날짜 선택');
      });
    } finally {
      running = false;
    }
  }

  new MutationObserver(translate).observe(doc.body, {childList: true, subtree: true});
  translate();
})();
</script>
"""


def korean_calendar():
    """앱 어디서든 한 번만 호출하면 된다 (st.set_page_config 이후)."""
    components.html(_JS, height=0)
