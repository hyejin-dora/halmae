"""단계별 처리시간 재기 — "앱이 멈췄나?" 를 개발자가 숫자로 확인하는 곳

    [PERF] saju_calculation: 0.02s
    [PERF] astrology_calculation: 1.14s
    [PERF] gemini_step1: 8.31s

이 파일이 하는 일은 두 가지뿐입니다.

    1) with perf.stage("이름"): ...   으로 감싼 구간의 시간을 잽니다.
    2) 잰 값을 개발 로그(터미널 · Streamlit Cloud Logs)에 한 줄로 남깁니다.

[개인정보를 남기지 않습니다]
    남기는 것은 '구간 이름'과 '초' 두 가지뿐입니다.
    생년월일·출생시간·출생지역·이름·추가 질문·프롬프트·응답은
    이 파일까지 들어오지도 않습니다. (구간 이름은 코드에 적힌 고정값입니다)

[사용자에게는 보이지 않습니다]
    처리시간은 개발자용 정보라 화면에 그리지 않습니다.
    개발자 모드(config.USE_DEV_MODE)에서만 요약을 볼 수 있습니다.

터미널에서 확인:
    python perf.py            # 이 파일이 제대로 도는지 (가짜 구간으로 시연)
"""

import logging
import time
from contextlib import contextmanager

logger = logging.getLogger("halmae.perf")

# 로그 앞에 붙는 표시. 로그를 grep 할 때 쓰라고 한 곳에 모아둡니다.
#     streamlit run app.py 2>&1 | grep PERF
PERF_TAG = "[PERF]"

# 이 서비스에서 재는 구간 이름 — 여기 없는 이름을 쓰면 오타입니다.
# (이름을 한 곳에 모아두면 나중에 지표를 볼 때 이름이 어긋나지 않습니다)
STAGE_NAMES = (
    "saju_calculation",        # 사주 네 기둥 · 오행
    "calendar_conversion",     # 양력 ↔ 음력 변환
    "geocoding",               # 출생지 → 좌표 (인터넷)
    "timezone",                # 좌표 → 시간대
    "astrology_calculation",   # 태양궁 · 달궁 · 상승궁 (좌표·시간대 포함)
    "daeun_calculation",       # 대운 (파이썬 계산)
    "sewoon_calculation",      # 세운 (파이썬 계산)
    "gemini_step1",
    "gemini_step2",
    "gemini_step3",
    "gemini_year_flow",        # 올해의 흐름 해석
    "year_card_lookup",        # 올해의 카드 저장소 조회
    "gemini_year_card",        # 올해의 카드 생성
    "supabase_read",
    "supabase_write",
)


def _log(name: str, seconds: float) -> None:
    """[PERF] 한 줄. 이 파일에서 로그를 남기는 유일한 곳입니다."""
    logger.info("%s %s: %.2fs", PERF_TAG, name, seconds)


@contextmanager
def stage(name: str, sink: dict | None = None):
    """이 구간이 몇 초 걸렸는지 재서 개발 로그에 남깁니다.

        with perf.stage("saju_calculation"):
            saju = compute_saju(...)

    sink 를 주면 그 dict 에도 {"saju_calculation": 0.02} 로 담아둡니다.
    (화면에서 개발자용 요약을 보여줄 때 씁니다 — 사용자에게는 보여주지 않습니다)

    구간 안에서 오류가 나도 시간은 남깁니다. 그래야 "느려서 죽었는지,
    바로 죽었는지" 를 구별할 수 있습니다. 오류는 그대로 위로 올려보냅니다.
    """
    started = time.perf_counter()
    try:
        yield
    finally:
        elapsed = time.perf_counter() - started
        _log(name, elapsed)
        if sink is not None:
            # 같은 구간이 두 번 돌면 합칩니다. (예: 카드 조회 → 생성)
            sink[name] = round(sink.get(name, 0.0) + elapsed, 3)


def record(name: str, seconds: float, sink: dict | None = None) -> None:
    """이미 잰 시간을 그대로 남깁니다. (with 로 감싸기 어려운 자리용)"""
    _log(name, seconds)
    if sink is not None:
        sink[name] = round(sink.get(name, 0.0) + seconds, 3)


def slowest(sink: dict, top: int = 3) -> list[tuple[str, float]]:
    """가장 오래 걸린 구간 위쪽 몇 개. (개발자 화면·완료 보고용)"""
    return sorted(sink.items(), key=lambda row: row[1], reverse=True)[:top]


def format_summary(sink: dict, top: int = 3) -> str:
    """개발자용 한 덩어리 글. 사용자 화면에는 쓰지 않습니다."""
    if not sink:
        return "아직 잰 구간이 없습니다."
    lines = [f"{name:<24} {seconds:>6.2f}s"
             for name, seconds in sorted(sink.items(),
                                         key=lambda row: row[1], reverse=True)]
    total = sum(sink.values())
    lines.append("-" * 32)
    lines.append(f"{'합계':<24} {total:>6.2f}s")
    slow = slowest(sink, top)
    if slow:
        lines.append("")
        lines.append("가장 오래 걸린 구간 " + str(top) + "개")
        for rank, (name, seconds) in enumerate(slow, start=1):
            lines.append(f"  {rank}. {name} — {seconds:.2f}s")
    return "\n".join(lines)


# ---------------------------------------------------------------
#  이 파일이 제대로 도는지 눈으로 확인
#      python perf.py
# ---------------------------------------------------------------
if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format="%(message)s")

    measured: dict = {}
    with stage("saju_calculation", measured):
        time.sleep(0.02)
    with stage("astrology_calculation", measured):
        time.sleep(0.12)
    with stage("gemini_step1", measured):
        time.sleep(0.3)

    print()
    print(format_summary(measured))
