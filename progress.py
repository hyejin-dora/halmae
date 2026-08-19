"""로딩 화면 — "앱이 멈췄나?" 라는 오해를 막는 곳

    ① "네 사주팔자를 펼쳐보는 중이란다..."
    ② "태어난 날의 별자리까지 맞춰보는 중..."
    ③ "네 고민과 명식을 함께 들여다보는 중..."
    ④ "할매가 할 말을 정리하고 있단다..."

[왜 만들었나]
    돌아가는 스피너 하나를 10초 넘게 보여주면 사람은 멈춘 줄 압니다.
    글이 바뀌면 "지금도 뭔가 하고 있구나" 하고 기다려줍니다.
    실제로 하는 일에 맞춰 글을 바꾸는 것이 이 파일이 하는 전부입니다.

[두 가지 쓰임]
    1) 여러 단계를 차례로 도는 구간   → with steps(...) as s:  s.next()
       사주 → 별자리처럼 실제로 나뉘어 있는 일에 씁니다.

    2) 한 번에 오래 걸리는 구간       → run_staged(...)
       Gemini 호출 한 번처럼 안이 안 보이는 일에 씁니다.
       일을 딴 갈래(thread)에서 돌리고, 기다리는 동안 글만 바꿔줍니다.
       (딴 갈래에서는 화면을 건드리지 않습니다 — 계산과 네트워크만 합니다)

[사용자에게 보이지 않는 것]
    처리시간(초)은 개발자용이라 화면에 그리지 않습니다.
    걸린 시간은 perf.py 를 통해 개발 로그에만 남습니다.

[안전장치]
    st.status 나 thread 가 말썽이면 그냥 st.spinner 로 물러납니다.
    로딩 연출 때문에 답변 자체가 실패하는 일은 없어야 하니까요.
"""

import logging
import time
from concurrent.futures import ThreadPoolExecutor
from contextlib import contextmanager

import streamlit as st

import perf

log = logging.getLogger("halmae.progress")

# 글을 바꾸기 전에 최소한 이만큼은 보여줍니다. (너무 빨리 지나가면 못 읽습니다)
MIN_LABEL_SECONDS = 1.2

# 일이 끝났는지 확인하는 간격. 짧을수록 반응이 빠르고, 길수록 CPU 를 덜 씁니다.
POLL_SECONDS = 0.15


# ===============================================================
#  1. 여러 단계를 차례로 도는 구간
# ===============================================================
class _Steps:
    """with steps(...) 안에서 단계를 넘길 때 쓰는 손잡이."""

    def __init__(self, status, labels: list[str]) -> None:
        self._status = status
        self._labels = labels
        self._index = 0

    def next(self, label: str | None = None) -> None:
        """다음 단계로 글을 바꿉니다. label 을 주면 그 글로 바꿉니다."""
        if label is None:
            self._index += 1
            if self._index >= len(self._labels):
                return
            label = self._labels[self._index]
        self._set(label)

    def _set(self, label: str) -> None:
        _quiet_update(self._status, label=label)


@contextmanager
def steps(labels: list[str], done_label: str | None = None):
    """실제로 나뉘어 있는 여러 단계를 차례로 보여줍니다.

        with progress.steps(["사주 펼치는 중...", "별자리 맞추는 중..."]) as s:
            compute_saju(...)
            s.next()
            compute_astrology(...)

    st.status 를 쓸 수 없는 환경이면 st.spinner 하나로 물러납니다.

    [주의] 상자를 '만드는 것' 이 실패했을 때만 물러납니다.
           안쪽 일이 실패한 것은 그대로 위로 올려보냅니다 —
           여기서 붙잡아 다시 돌리면 같은 일을 두 번 하게 됩니다.
    """
    if not labels:
        labels = ["할매가 준비하고 있어요..."]

    status = _open_status(labels[0])

    if status is None:                     # 상자를 못 만든 경우에만 물러납니다
        with st.spinner(labels[0]):
            yield _Steps(None, labels)
        return

    with status:
        try:
            yield _Steps(status, labels)
        except Exception:
            # 실패했다는 것만 표시하고, 오류는 부르는 쪽으로 그대로 올려보냅니다.
            _quiet_update(status, state="error")
            raise
        _quiet_update(status, label=done_label or labels[-1], state="complete")


def _open_status(label: str):
    """상태 상자를 만듭니다. 못 만들면 None. (연출 때문에 앱이 멈추면 안 됩니다)"""
    try:
        return st.status(label, expanded=False)
    except Exception:
        log.debug("st.status 를 쓰지 못해 spinner 로 물러납니다", exc_info=True)
        return None


def _quiet_update(status, **kwargs) -> None:
    """상태 상자 글을 바꿉니다. 실패해도 조용히 넘어갑니다."""
    if status is None:
        return
    try:
        status.update(**kwargs)
    except Exception:
        log.debug("상태 표시를 바꾸지 못했습니다", exc_info=True)


# ===============================================================
#  2. 한 번에 오래 걸리는 구간 (Gemini 호출 등)
# ===============================================================
def run_staged(
    work,
    stages: list[tuple[float, str]],
    *,
    done_label: str | None = None,
    perf_name: str | None = None,
    perf_sink: dict | None = None,
):
    """오래 걸리는 일 하나를 돌리면서, 기다리는 동안 글을 바꿔 보여줍니다.

        answer = progress.run_staged(
            lambda: ask_halmae(...),
            stages=[(0, "명식을 펼치는 중..."), (6, "할 말을 정리하는 중...")],
            perf_name="gemini_step1",
        )

    stages 는 (몇 초 뒤부터, 보여줄 글) 목록입니다. 첫 칸은 0초여야 합니다.
    돌려주는 값과 오류는 work() 가 낸 것을 그대로 전달합니다.
    (오류를 삼키면 위쪽의 안내 문구가 뜨지 않습니다)

    [왜 딴 갈래(thread)를 쓰나]
        Gemini 호출은 한 번 들어가면 끝날 때까지 돌아오지 않습니다.
        그 사이 화면을 못 건드리면 글을 바꿀 수 없어서, 일만 딴 갈래로 보내고
        화면은 원래 갈래가 지킵니다. 딴 갈래는 st.* 를 부르지 않습니다.

    [일은 딱 한 번만 돕니다]
        상태 상자를 못 만들면 스피너로 물러나지만, 그때도 work() 는 한 번만
        불립니다. 같은 Gemini 요청이 두 번 나가면 안 되니까요.
    """
    if not stages:
        stages = [(0.0, "할매가 들여다보고 있어요...")]
    labels = [label for _, label in stages]

    started = time.perf_counter()
    try:
        status = _open_status(labels[0])
        if status is None:
            with st.spinner(labels[0]):
                return work()

        with status:
            with ThreadPoolExecutor(max_workers=1) as pool:
                future = pool.submit(work)
                shown = 0
                while not future.done():
                    time.sleep(POLL_SECONDS)
                    elapsed = time.perf_counter() - started
                    while (
                        shown + 1 < len(stages)
                        and elapsed >= max(stages[shown + 1][0],
                                           MIN_LABEL_SECONDS)
                    ):
                        shown += 1
                        _quiet_update(status, label=labels[shown])
                try:
                    result = future.result()
                except Exception:
                    _quiet_update(status, state="error")
                    raise
            _quiet_update(status, label=done_label or labels[-1],
                          state="complete")
        return result
    finally:
        if perf_name:
            perf.record(perf_name, time.perf_counter() - started, perf_sink)


# ===============================================================
#  3. 이 서비스가 쓰는 로딩 문구 (한 곳에 모아둡니다)
#
#  실제 처리 단계와 최대한 맞춰둡니다. 없는 일을 하는 척하지 않습니다.
# ===============================================================
# 입력을 제출한 직후 — 파이썬 계산 구간 (실제로 나뉘어 있는 단계)
CALC_STAGES = [
    "네 사주팔자를 펼쳐보는 중이란다...",
    "태어난 날의 별자리까지 맞춰보는 중...",
    "네 대운이 어디쯤 흐르는지 세어보는 중...",
]
CALC_DONE = "다 펼쳐놓았단다."

# 1~3단계 답변 — Gemini 한 번 호출. 기다리는 동안 글만 바뀝니다.
STEP_STAGES = {
    1: [
        (0.0, "네 고민과 명식을 함께 들여다보는 중..."),
        (7.0, "할매가 할 말을 정리하고 있단다..."),
        (16.0, "거의 다 되었다. 조금만 더 기다려보거라..."),
    ],
    2: [
        (0.0, "네 명식을 한 겹 더 들춰보는 중..."),
        (8.0, "할매가 더 깊은 이야기를 고르고 있단다..."),
        (18.0, "긴 이야기라 조금 더 걸리는구나. 기다려보거라..."),
    ],
    3: [
        (0.0, "네가 실제로 해볼 만한 일을 꼽아보는 중..."),
        (8.0, "할매가 지령을 다듬고 있단다..."),
        (18.0, "거의 다 되었다. 조금만 더 기다려보거라..."),
    ],
}
STEP_DONE = "다 골랐단다."

# 올해의 흐름 (대운 × 세운)
YEAR_FLOW_STAGES = [
    (0.0, "네 대운과 올해 세운을 나란히 놓아보는 중..."),
    (7.0, "두 흐름이 어디서 맞물리는지 짚어보는 중..."),
    (15.0, "할매가 올해 이야기를 정리하고 있단다..."),
]
YEAR_FLOW_DONE = "올해 흐름을 다 짚었단다."

# 올해의 카드
YEAR_CARD_STAGES = [
    (0.0, "올해 네 카드를 고르는 중..."),
    (7.0, "카드에 들어갈 그림까지 고르고 있단다..."),
    (15.0, "거의 다 되었다. 조금만 더 기다려보거라..."),
]
YEAR_CARD_DONE = "카드를 다 골랐단다."


# ---------------------------------------------------------------
#  이 파일이 제대로 도는지 눈으로 확인
#      streamlit run progress.py
# ---------------------------------------------------------------
if __name__ == "__main__":
    st.title("로딩 화면 시연")

    if st.button("여러 단계 (계산 구간)"):
        with steps(CALC_STAGES, CALC_DONE) as s:
            time.sleep(1.5)
            s.next()
            time.sleep(1.5)
            s.next()
            time.sleep(1.0)
        st.success("끝났습니다")

    if st.button("오래 걸리는 한 번 (Gemini 흉내)"):
        value = run_staged(
            lambda: (time.sleep(9), "다 되었다")[1],
            stages=STEP_STAGES[1],
            done_label=STEP_DONE,
            perf_name="gemini_step1",
        )
        st.success(value)
