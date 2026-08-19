"""로딩 화면 — "앱이 멈췄나?" 라는 오해를 막는 곳

    ◆  네 사주팔자를 펼쳐보는 중이란다...
       · · ·
       ▁▁▁▁▁▁▁▁▁

[왜 만들었나]
    돌아가는 스피너 하나를 10초 넘게 보여주면 사람은 멈춘 줄 압니다.
    글이 바뀌면 "지금도 뭔가 하고 있구나" 하고 기다려줍니다.

[핵심 규칙 — 연출이 처리를 늦추지 않습니다]
    문구를 보여주려고 파이썬에서 time.sleep() 하는 곳은 한 곳도 없습니다.
    문구 교체·점·금띠는 전부 **CSS 애니메이션**이라 브라우저가 혼자 돌립니다.
    그래서 Gemini 호출이 서버(파이썬)를 8초 동안 붙잡고 있어도
    화면은 1.5초마다 계속 바뀝니다.

    반대 방향도 지킵니다 — 일이 끝나면 문구를 다 보여주려고 기다리지 않고
    그 자리에서 로딩 판을 지우고 다음 화면으로 넘어갑니다.
    (최소 표시 시간 · 단계별 강제 대기 같은 것이 없습니다)

[두 가지 쓰임 — 안은 똑같습니다]
    1) 여러 단계를 차례로 도는 구간   → with steps(...) as s:
    2) 한 번에 오래 걸리는 구간       → run_staged(...)

    둘 다 같은 CSS 로딩 판을 띄웁니다. 다른 점은 run_staged 가
    걸린 시간을 perf 에 남긴다는 것뿐입니다.

[사용자에게 보이지 않는 것]
    · 처리시간(초)         — 개발용이라 perf.py 로 로그에만 남깁니다.
    · 가짜 진행률("80%")   — 몇 초 걸릴지 서버도 모르므로 숫자를 쓰지 않습니다.
                             금띠는 조각이 계속 지나가는 모양(indeterminate)입니다.

[안전장치]
    HTML 을 못 그리면 그냥 st.spinner 로 물러납니다.
    로딩 연출 때문에 답변 자체가 실패하는 일은 없어야 하니까요.
"""

import html
import logging
import time
from contextlib import contextmanager

import streamlit as st

import perf

log = logging.getLogger("halmae.progress")

# 문구 한 줄이 화면에 머무는 시간(초).
#     사람이 "화면이 변했다" 고 느끼는 간격은 1~2초입니다.
#     0.8초보다 짧으면 다 읽기 전에 사라지고, 2초를 넘으면 멈춘 것처럼 보입니다.
#     이 값은 브라우저(CSS) 쪽 시간이라, 파이썬 처리 속도와 아무 상관이 없습니다.
PHRASE_SECONDS = 1.5

# 문구가 나타날 때 · 사라질 때 겹치는 정도. (한 칸의 몇 %를 페이드에 쓸지)
_FADE_RATIO = 0.28
_FADE_MAX_PCT = 10.0


# ===============================================================
#  1. CSS 로딩 판 만들기
#     색 · 서체 · 크기는 전부 theme.py 의 _css_loading() 에 있습니다.
#     이 파일은 문구와 '몇 초에 바뀌는지' 만 정합니다.
# ===============================================================
def _phrases(stages) -> list[str]:
    """여러 모양으로 들어오는 문구 목록을 글자 목록 하나로 펴줍니다.

    받는 모양 두 가지 (예전 코드와 섞여 있어도 됩니다)
        ["펼쳐보는 중...", "정리하는 중..."]              ← 지금 쓰는 모양
        [(0.0, "펼쳐보는 중..."), (7.0, "정리하는 중...")]  ← 예전 (초, 글) 모양

    예전 모양의 '몇 초 뒤부터' 값은 일부러 버립니다.
    그 값이 7초·16초여서 한 문구가 너무 오래 머물렀던 것이 원래 문제였고,
    이제는 CSS 가 PHRASE_SECONDS 간격으로 고르게 돌립니다.
    """
    out: list[str] = []
    for item in stages or []:
        if isinstance(item, (tuple, list)):
            text = item[-1] if item else ""
        else:
            text = item
        text = str(text).strip()
        if text:
            out.append(text)
    return out or ["할매가 들여다보고 있어요..."]


def _keyframes(count: int, total: float) -> str:
    """문구 개수에 맞는 @keyframes 한 줄.

    문구가 N 개면 한 바퀴(total 초)를 N 칸으로 나눠, 자기 칸에서만 보입니다.
    칸 비율이 개수마다 달라서 개수별로 따로 만듭니다. (이름에 개수가 붙습니다)
    """
    slice_pct = 100.0 / count
    fade = min(slice_pct * _FADE_RATIO, _FADE_MAX_PCT)
    return (
        f"@keyframes {_keyframes_name(count)}{{"
        "0%{opacity:0;transform:translateY(5px)}"
        f"{fade:.3f}%{{opacity:1;transform:translateY(0)}}"
        f"{slice_pct - fade:.3f}%{{opacity:1;transform:translateY(0)}}"
        f"{slice_pct:.3f}%{{opacity:0;transform:translateY(-5px)}}"
        "100%{opacity:0}"
        "}"
    )


def _keyframes_name(count: int) -> str:
    return f"halmae-phrase-{count}"


def loader_html(stages, *, cadence: float = PHRASE_SECONDS) -> str:
    """로딩 판 HTML 한 덩어리. (파이썬은 이걸 한 번 뱉고 바로 일하러 갑니다)

    문구 span 을 겹쳐두고 animation-delay 만 한 칸씩 밀어둡니다.
    브라우저가 cadence 초마다 다음 span 을 보여주고, 끝나면 처음으로 돌아갑니다.
    처리가 길어지면 문구가 계속 순환하므로 화면이 멈추는 일이 없습니다.
    """
    phrases = _phrases(stages)
    count = len(phrases)

    if count == 1:
        # 한 줄뿐이면 깜빡이게 하지 않고 가만히 보여줍니다.
        spans = (
            '<p class="halmae-loading-phrase" style="opacity:1">'
            f"{html.escape(phrases[0])}</p>"
        )
        style = ""
    else:
        total = cadence * count
        name = _keyframes_name(count)
        spans = "".join(
            '<p class="halmae-loading-phrase" style="'
            f"animation-name:{name};"
            f"animation-duration:{total:.2f}s;"
            f'animation-delay:{cadence * index:.2f}s">'
            f"{html.escape(text)}</p>"
            for index, text in enumerate(phrases)
        )
        style = "<style>" + _keyframes(count, total) + "</style>"

    return (
        f"{style}"
        '<div class="halmae-loading" role="status"'
        ' aria-label="할매가 들여다보고 있단다">'
        '<div class="halmae-loading-mark" aria-hidden="true">◆</div>'
        f'<div class="halmae-loading-phrases">{spans}</div>'
        '<div class="halmae-loading-dots" aria-hidden="true">'
        '<i style="animation-delay:0s"></i>'
        '<i style="animation-delay:0.4s"></i>'
        '<i style="animation-delay:0.8s"></i>'
        "</div>"
        '<div class="halmae-loading-bar" aria-hidden="true"><span></span></div>'
        "</div>"
    )


@contextmanager
def _loader(stages):
    """로딩 판을 띄우고, 블록이 끝나면 그 자리에서 지웁니다.

    지우는 것은 finally 안에 있습니다. 일이 실패해도 로딩 판이
    화면에 남아 "아직 하는 중" 처럼 보이면 안 되니까요.

    HTML 을 못 그리는 환경이면 st.spinner 하나로 물러납니다.
    (연출 실패가 답변 실패로 번지지 않게)
    """
    phrases = _phrases(stages)
    try:
        slot = st.empty()
        slot.markdown(loader_html(phrases), unsafe_allow_html=True)
    except Exception:
        log.debug("로딩 판을 그리지 못해 spinner 로 물러납니다", exc_info=True)
        with st.spinner(phrases[0]):
            yield
        return

    try:
        yield
    finally:
        # 일이 끝나면 곧바로 치웁니다. 남은 문구를 보여주려고 기다리지 않습니다.
        try:
            slot.empty()
        except Exception:
            log.debug("로딩 판을 지우지 못했습니다", exc_info=True)


# ===============================================================
#  2. 여러 단계를 차례로 도는 구간
# ===============================================================
class _Steps:
    """with steps(...) 안에서 쓰는 손잡이.

    [next() 는 이제 아무 일도 하지 않습니다]
        문구 교체를 브라우저(CSS)가 하기 때문에, 파이썬이 "다음 문구로" 라고
        말해줄 필요가 없어졌습니다. 부르는 쪽 코드를 건드리지 않으려고
        함수는 남겨둡니다. (부작용도, 대기시간도 없습니다)
    """

    def next(self, label: str | None = None) -> None:
        return None


@contextmanager
def steps(labels: list[str], done_label: str | None = None):
    """실제로 나뉘어 있는 여러 단계를 도는 동안 로딩 판을 띄웁니다.

        with progress.steps(progress.CALC_STAGES) as s:
            compute_saju(...)
            s.next()            # 있어도 없어도 같습니다 (CSS 가 돌립니다)
            compute_astrology(...)

    [done_label 은 화면에 띄우지 않습니다]
        "다 펼쳐놓았단다" 를 보여주려면 그만큼 다음 화면이 늦어집니다.
        계산이 끝나는 순간 로딩 판을 지우고 결과로 넘어갑니다.
        (인자는 부르는 쪽 코드를 지키려고 받아만 둡니다)

    [주의] 안쪽 일이 실패하면 오류를 그대로 위로 올려보냅니다 —
           여기서 붙잡아 다시 돌리면 같은 일을 두 번 하게 됩니다.
    """
    with _loader(labels):
        yield _Steps()


# ===============================================================
#  3. 한 번에 오래 걸리는 구간 (Gemini 호출 등)
# ===============================================================
def run_staged(
    work,
    stages,
    *,
    done_label: str | None = None,
    perf_name: str | None = None,
    perf_sink: dict | None = None,
):
    """오래 걸리는 일 하나를 돌리는 동안 로딩 판을 띄웁니다.

        answer = progress.run_staged(
            lambda: ask_halmae(...),
            stages=progress.STEP_STAGES[step],
            perf_name="gemini_step1",
        )

    돌려주는 값과 오류는 work() 가 낸 것을 그대로 전달합니다.
    (오류를 삼키면 위쪽의 안내 문구가 뜨지 않습니다)

    [딴 갈래(thread)를 쓰지 않습니다 — 예전과 달라진 곳]
        예전에는 일을 thread 로 보내고, 이쪽에서 0.15초마다 깨어나
        문구를 바꿔줬습니다. 이제 문구는 CSS 가 바꾸므로 그럴 필요가 없습니다.
        일을 이 갈래에서 그냥 돌리는 쪽이 더 빠릅니다.
            · thread pool 을 만들고 걷는 값
            · 0.15초 간격으로만 "끝났나?" 를 확인해서 생기던 지연
        둘 다 없어집니다. work() 는 예전과 똑같이 딱 한 번만 불립니다.

    [work() 안에서 st.session_state 를 보지 마세요]
        지금은 같은 갈래라 되기는 하지만, 부르는 쪽은 이미 값을 미리 꺼내
        넘기고 있습니다. 그 약속을 그대로 지켜주세요.
    """
    started = time.perf_counter()
    try:
        with _loader(stages):
            return work()
    finally:
        if perf_name:
            perf.record(perf_name, time.perf_counter() - started, perf_sink)


# ===============================================================
#  4. 이 서비스가 쓰는 로딩 문구 (한 곳에 모아둡니다)
#
#  [문구를 고를 때]
#      · 실제로 하는 일과 맞춰둡니다. 없는 일을 하는 척하지 않습니다.
#      · 목록 뒤쪽에는 "오래 걸릴 때" 문구를 둡니다. 앞쪽 문구를 다 돌고도
#        일이 안 끝나면 여기까지 내려오고, 그 뒤에는 처음으로 돌아가 순환합니다.
#      · 한 바퀴 = 문구 개수 × 1.5초. Gemini 가 8초쯤 걸리므로
#        일곱 줄(10.5초)이면 대체로 한 바퀴 안에 끝납니다.
# ===============================================================
# 입력을 제출한 직후 — 파이썬 계산 구간 (사주 · 별자리 · 대운)
#     대개 1~3초입니다. 출생지역을 처음 찾는 경우(geocoding)에만 길어집니다.
CALC_STAGES = [
    "네 사주팔자를 펼쳐보는 중이란다...",
    "태어난 날의 별자리까지 들여다보는 중...",
    "네 대운이 어디쯤 흐르는지 세어보는 중...",
    "출생지의 하늘을 찾아보는 중이란다...",
    "흐름이 하나씩 보이는구나...",
]
CALC_DONE = "다 펼쳐놓았단다."

# 1~3단계 답변 — Gemini 한 번 호출.
STEP_STAGES = {
    1: [
        "네 고민과 명식을 맞춰보는 중...",
        "네 사주팔자를 한 번 더 짚어보는 중...",
        "올해의 흐름까지 훑어보는 중...",
        "할매가 할 말을 정리하고 있단다...",
        "조금만 기다려라, 중요한 대목을 보고 있단다...",
        "흐름이 하나씩 보이는구나...",
        "마지막으로 말을 다듬고 있단다...",
    ],
    2: [
        "네 명식을 한 겹 더 들춰보는 중...",
        "타고난 기운이 어디로 뻗는지 보는 중...",
        "네 고민의 뿌리를 짚어보는 중...",
        "할매가 더 깊은 이야기를 고르고 있단다...",
        "조금만 기다려라, 중요한 대목을 보고 있단다...",
        "흐름이 하나씩 보이는구나...",
        "마지막으로 말을 다듬고 있단다...",
    ],
    3: [
        "네가 실제로 해볼 만한 일을 꼽아보는 중...",
        "언제 움직이면 좋을지 시기를 맞춰보는 중...",
        "할매가 지령을 다듬고 있단다...",
        "조금만 기다려라, 중요한 대목을 보고 있단다...",
        "흐름이 하나씩 보이는구나...",
        "마지막으로 말을 다듬고 있단다...",
    ],
}
STEP_DONE = "다 골랐단다."

# 올해의 흐름 (대운 × 세운)
YEAR_FLOW_STAGES = [
    "네 대운과 올해 세운을 나란히 놓아보는 중...",
    "두 흐름이 어디서 맞물리는지 짚어보는 중...",
    "올해의 흐름까지 훑어보는 중...",
    "할매가 올해 이야기를 정리하고 있단다...",
    "조금만 기다려라, 중요한 대목을 보고 있단다...",
    "흐름이 하나씩 보이는구나...",
    "마지막으로 말을 다듬고 있단다...",
]
YEAR_FLOW_DONE = "올해 흐름을 다 짚었단다."

# 올해의 카드
YEAR_CARD_STAGES = [
    "올해 네 카드를 고르는 중...",
    "카드에 들어갈 그림까지 고르고 있단다...",
    "카드에 새길 한 마디를 벼르는 중...",
    "조금만 기다려라, 중요한 대목을 보고 있단다...",
    "흐름이 하나씩 보이는구나...",
    "마지막으로 말을 다듬고 있단다...",
]
YEAR_CARD_DONE = "카드를 다 골랐단다."


# ---------------------------------------------------------------
#  이 파일이 제대로 도는지 눈으로 확인
#      streamlit run progress.py
#
#  아래 sleep 은 '오래 걸리는 일' 을 흉내내는 것뿐입니다.
#  이 블록은 streamlit run progress.py 로 직접 열었을 때만 돕니다 —
#  app.py 가 import 할 때는 실행되지 않습니다.
# ---------------------------------------------------------------
if __name__ == "__main__":
    import theme

    st.markdown(theme.build_css(), unsafe_allow_html=True)
    st.title("로딩 화면 시연")
    st.caption(f"문구는 {PHRASE_SECONDS}초마다 바뀝니다 (CSS 애니메이션)")

    if st.button("계산 구간 흉내 (3초)"):
        with steps(CALC_STAGES) as s:
            time.sleep(1.5)
            s.next()
            time.sleep(1.5)
        st.success("끝났습니다")

    if st.button("Gemini 흉내 (18초 — 문구가 한 바퀴 돌고 다시 시작)"):
        value = run_staged(
            lambda: (time.sleep(18), "다 되었다")[1],
            stages=STEP_STAGES[1],
            perf_name="gemini_step1",
        )
        st.success(value)
