"""
할매 - AI 조언 웹앱 (MVP: 첫 화면 + 입력 화면 + 단계형 답변 화면)

화면 흐름
    intro  (첫 화면)  →  input (입력 화면)  →  result (할매 답변 화면)

답변 화면은 세 단계로 이어집니다.
    1단계  할매가 네 팔자부터 딱 짚어주마      → [할매, 더 듣고 싶어요]
    2단계  할매가 조금 더 깊이 들여다봤단다    → [그래서 저는 뭘 하면 좋을까요?]
    3단계  할매의 행동 지령 (실행할 행동 3가지)

앞 단계의 대화를 함께 보내기 때문에 할매가 했던 이야기를 기억한 채로 이어집니다.

파일 나누기
    saju.py       사주 네 기둥과 오행 분포
    astrology.py  태양궁 / 달궁 / 상승궁
    halmae_ai.py  할매 캐릭터, 프롬프트, 답변 구조, Gemini 호출
    app.py        화면 (이 파일)

실행 전 준비
    pip install -r requirements.txt
    export GEMINI_API_KEY="발급받은_키"        # 키는 코드에 적지 않습니다
    streamlit run app.py
"""

import logging
from datetime import date, time, timedelta

import streamlit as st

import analytics
import card_store
import db
import theme
from astrology import AstrologyError, compute_astrology
from config import USE_DEV_MODE, USE_MOCK_AI
from halmae_ai import (
    GEMINI_MODEL,
    IS_DEV_MODEL,
    LOADING_MESSAGES,
    MODEL_LABEL,
    MODEL_LOG_NAME,
    MODEL_STAGE,
    NEXT_BUTTON_LABELS,
    PROD_MODEL,
    STEP_TITLES,
    YEAR_CARD_LOADING,
    HalmaeError,
    YearCard,
    answer_length,
    ask_halmae,
    ask_year_card,
    build_prompt,
    format_year_card_text,
)
from saju import (
    OHAENG_ORDER,
    CalendarError,
    compute_calendar_info,
    compute_saju,
    compute_year_ganji,
    format_saju_for_prompt,
    saju_facts,
    year_luck_notes,
)

# ---------------------------------------------------------------
# 1. 페이지 기본 설정
#    - layout="centered": 내용을 가운데 좁은 폭으로 배치 (모바일에 적합)
#    - 이 함수는 반드시 다른 st.* 명령보다 먼저 딱 한 번 호출해야 합니다.
# ---------------------------------------------------------------
st.set_page_config(
    page_title="할매 · HALMAE",
    page_icon="🕯️",
    layout="centered",
    initial_sidebar_state="collapsed",
)


# ---------------------------------------------------------------
# 2. 화면 꾸미기 (디자인 시스템은 theme.py 에 있습니다)
#    색·글꼴·카드 모양을 바꾸려면 theme.py 의 TOKENS 만 고치면 됩니다.
#    가독성(명도 대비)은 `python theme.py` 로 검사할 수 있습니다.
# ---------------------------------------------------------------
st.markdown(theme.build_css(), unsafe_allow_html=True)


# ---------------------------------------------------------------
# 2-2. 개발 로그
#     사용자에게는 짧고 이해되는 문구만 보여주고,
#     "왜 그랬는지"는 여기(터미널 · Streamlit Cloud 의 Logs)에만 남깁니다.
#     개인정보는 남기지 않습니다 — 오류 종류와 위치까지만 적습니다.
# ---------------------------------------------------------------
log = logging.getLogger("halmae.app")


# ---------------------------------------------------------------
# 2-3. 개발자용 화면을 언제 보여줄지
#
#     [Prompt · Debug 정보]  config.USE_DEV_MODE 하나로만 결정됩니다.
#         기본값 False — 배포된 앱에서는 주소를 어떻게 치든 열리지 않습니다.
#         일반 사용자 화면에 아래가 하나도 나오지 않습니다:
#             Gemini 프롬프트 / System prompt / Gemini 입력값 /
#             원본 응답 / 계산 원본 / 좌표 / 카드 열쇠 / 개발자용 문구
#         켜는 법은 config.py 의 ★ 설정 3 을 보세요.
#
#     [Funnel 지표 화면]  예전 그대로 주소 뒤 ?dev=<HALMAE_DEV_KEY>.
#         지표만 보는 화면이라 개인정보도 프롬프트도 나오지 않습니다.
# ---------------------------------------------------------------
try:
    IS_DEV_FUNNEL = analytics.dev_dashboard_allowed(st.query_params.get("dev"))
except Exception:                      # 주소를 읽지 못해도 앱은 떠야 합니다
    IS_DEV_FUNNEL = False


# ---------------------------------------------------------------
# 3. 화면 단계 관리 (Session State)
#    st.session_state = 새로고침 전까지 값을 기억해두는 사물함.
#    여기에 "지금 어느 화면인지"를 담아두고 화면을 바꿉니다.
# ---------------------------------------------------------------
if "page" not in st.session_state:
    st.session_state.page = "intro"      # 시작은 항상 첫 화면

if "answers" not in st.session_state:
    st.session_state.answers = {}        # 사용자가 입력한 값을 모아둘 곳

# --- 단계형 답변에 쓰는 사물함 ---------------------------------
#     step     : 지금까지 열린 단계 (1 → 2 → 3)
#     replies  : {단계 번호: 할매 답변 글}   ← 한 번 받으면 다시 부르지 않음
#     errors   : {단계 번호: 오류 안내 문구}
#     history  : Gemini에 함께 보낼 대화 기록 (맥락 유지용)
if "step" not in st.session_state:
    st.session_state.step = 1

if "replies" not in st.session_state:
    st.session_state.replies = {}

if "errors" not in st.session_state:
    st.session_state.errors = {}

if "history" not in st.session_state:
    st.session_state.history = []

# 생년월일로 계산한 양력·음력·간지 정보 (아직 Gemini에는 보내지 않습니다)
if "calendar_info" not in st.session_state:
    st.session_state.calendar_info = None

if "calendar_error" not in st.session_state:
    st.session_state.calendar_error = None

# 사주 네 기둥과 오행 분포 (아직 Gemini에는 보내지 않습니다)
if "saju_info" not in st.session_state:
    st.session_state.saju_info = None

if "saju_error" not in st.session_state:
    st.session_state.saju_error = None

# 태양궁·달궁·상승궁 (아직 Gemini에는 보내지 않습니다)
if "astro_info" not in st.session_state:
    st.session_state.astro_info = None

if "astro_error" not in st.session_state:
    st.session_state.astro_error = None

# --- 행동 로그 (익명) ------------------------------------------
#     session_id     : 이 브라우저 탭을 알아보는 무작위 값. 누구인지는 알 수 없습니다.
#     logged_events  : 이미 기록한 이벤트 이름들. rerun 때 같은 줄이 또 쌓이는 걸 막습니다.
if "session_id" not in st.session_state:
    st.session_state.session_id = analytics.new_session_id()

if "logged_events" not in st.session_state:
    st.session_state.logged_events = set()

# --- Premium Fake-door 테스트 ----------------------------------
#     실제 결제는 절대 하지 않습니다. "이 값이면 쓰겠는가"를 클릭으로만 재봅니다.
#     premium_open    : CTA를 눌러 안내 영역이 열렸는지
#     purchase_intent : 사용자가 고른 답 ("yes" / "no" / None)
if "premium_open" not in st.session_state:
    st.session_state.premium_open = False

if "purchase_intent" not in st.session_state:
    st.session_state.purchase_intent = None

# --- 올해의 카드 -----------------------------------------------
#     Step 1~3 이야기를 이어받아 올해를 한 장으로 압축한 결과물입니다.
if "year_card" not in st.session_state:
    st.session_state.year_card = None

if "year_card_error" not in st.session_state:
    st.session_state.year_card_error = None

if "year_ganji" not in st.session_state:
    st.session_state.year_ganji = None

# 카드를 저장소에서 꺼내 썼는지(True), 새로 만들었는지(False)
if "year_card_cached" not in st.session_state:
    st.session_state.year_card_cached = False

# 이 사람 · 이 해를 가리키는 열쇠 (개발자 화면에서 확인용)
if "year_card_key" not in st.session_state:
    st.session_state.year_card_key = None

if "year_card_fingerprint" not in st.session_state:
    st.session_state.year_card_fingerprint = None

# --- 사용자 피드백 ---------------------------------------------
#     이 세션의 최종 답: None / "positive" / "negative"
if "feedback_result" not in st.session_state:
    st.session_state.feedback_result = None


def _write_event(event_name: str) -> None:
    """이벤트 한 줄을 실제로 남깁니다. (개인정보는 넘기지 않습니다.)

    넘기는 값은 analytics.FIELDNAMES 여섯 칸뿐입니다.
    이름·생년월일·출생시간·출생지역·좌표·추가 질문은 여기까지 오지도 않습니다.
    """
    analytics.log_event(
        session_id=st.session_state.session_id,
        event_name=event_name,
        # 고민 분야는 미리 정해진 선택지라 개인정보가 아닙니다.
        concern=st.session_state.answers.get("고민 분야"),
        # Mock 모드에서는 "mock" 으로 남겨, 나중에 개발 중 기록을 걸러낼 수 있게 합니다.
        model=MODEL_LOG_NAME,
        step=st.session_state.step,
    )


def track(event_name: str) -> None:
    """[화면 노출] 이벤트 — 한 세션에 딱 한 번만 남깁니다.

    Streamlit 은 버튼 하나만 눌러도 스크립트를 처음부터 다시 실행합니다.
    그래서 render_*() 안에서 그냥 기록하면, 사용자는 가만히 있는데도
    step1_view · premium_view 같은 줄이 rerun 횟수만큼 쌓입니다.

    여기서는 st.session_state.logged_events(세션이 살아 있는 동안 유지되는 집합)에
    이미 있는 이름이면 아무것도 하지 않습니다.
        · 의도치 않은 rerun  → 두 번째부터는 기록되지 않습니다
        · 사용자가 정말로 한 행동 → track_action() 으로 따로 기록합니다

    view 계열(landing_view · step1~3_view · card_view · feedback_view ·
    premium_view)에만 씁니다.
    """
    if not analytics.should_log(st.session_state.logged_events, event_name):
        return
    _write_event(event_name)


def track_action(event_name: str) -> None:
    """[사용자 행동] 이벤트 — 실제로 누를 때마다 남깁니다.

    이 함수는 st.button(...) 이 True 를 돌려준 자리, 즉 사용자가 손으로
    누른 순간에만 불립니다. rerun 만으로는 절대 여기까지 오지 않습니다.
    그래서 "마음을 바꿔 👍 → 👎 → 👍" 처럼 같은 행동을 다시 한 경우를
    그대로 기록할 수 있습니다.

    Funnel 지표는 모두 '세션 수'로 세기 때문에(analytics.funnel_summary 등),
    같은 세션이 같은 행동을 두 번 남겨도 전환율이 부풀지 않습니다.
    """
    # logged_events 에도 표시해 둡니다. 나중에 이 이름이 track() 으로도
    # 불릴 일이 생기면 그쪽에서 중복으로 한 줄 더 쌓지 않도록.
    st.session_state.logged_events.add(event_name)
    _write_event(event_name)


def reset_conversation() -> None:
    """할매와 나눈 이야기를 처음부터 다시 시작합니다."""
    st.session_state.step = 1
    st.session_state.replies = {}
    st.session_state.errors = {}
    st.session_state.history = []
    # Premium 안내 영역과 올해의 카드도 비웁니다.
    # (logged_events 는 일부러 그대로 둡니다 — 한 사람이 두 번 봐도 한 명으로 세야 하니까요.)
    st.session_state.premium_open = False
    st.session_state.purchase_intent = None
    st.session_state.year_card = None
    st.session_state.year_card_error = None
    st.session_state.year_card_cached = False
    st.session_state.year_card_key = None
    # 새 답변에 대해 다시 평가할 수 있도록 피드백 버튼도 비워둡니다.
    # 피드백 버튼도 '아직 안 고른' 상태로 되돌립니다.
    # (버튼은 st.feedback 과 달리 남는 위젯 상태가 없어 이 한 줄이면 됩니다.)
    st.session_state.feedback_result = None


def compute_calendar(answers: dict) -> None:
    """입력값으로 양력·음력·간지를 계산해 Session State에 담아둡니다.

    계산이 실패해도 앱이 멈추지 않도록, 오류는 문구로만 남깁니다.
    (할매의 답변 기능은 이 결과와 상관없이 그대로 동작합니다.)
    """
    st.session_state.calendar_info = None
    st.session_state.calendar_error = None
    try:
        st.session_state.calendar_info = compute_calendar_info(
            answers.get("생년월일"),
            answers.get("달력 유형", "양력"),
            answers.get("평달/윤달"),
        )
    except CalendarError as exc:
        # 사용자에게는 이 문구만 보여주고, 원인은 개발 로그에 남깁니다.
        log.warning("달력 계산 실패 (안내함) — %s", exc)
        st.session_state.calendar_error = str(exc)
    except Exception:
        log.exception("달력 계산 중 예상 못 한 오류")
        st.session_state.calendar_error = (
            "날짜를 계산하는 중 알 수 없는 문제가 생겼어요."
        )


def compute_saju_info(answers: dict) -> None:
    """입력값으로 사주 네 기둥과 오행 분포를 계산해 Session State에 담아둡니다.

    출생시간을 모른다고 체크했으면 시간을 None으로 넘겨,
    시주를 빼고 계산하도록 합니다.
    """
    st.session_state.saju_info = None
    st.session_state.saju_error = None

    birth_time = (
        None if answers.get("출생시간 모름") else answers.get("출생시간")
    )
    try:
        st.session_state.saju_info = compute_saju(
            birth_date=answers.get("생년월일"),
            birth_time=birth_time,
            calendar_type=answers.get("달력 유형", "양력"),
            leap_month=answers.get("평달/윤달"),
            birth_place=answers.get("출생지역"),
        )
    except CalendarError as exc:
        log.warning("사주 계산 실패 (안내함) — %s", exc)
        st.session_state.saju_error = str(exc)
    except Exception:
        log.exception("사주 계산 중 예상 못 한 오류")
        st.session_state.saju_error = (
            "사주를 계산하는 중 알 수 없는 문제가 생겼어요."
        )


def compute_astro_info(answers: dict) -> None:
    """입력값으로 태양궁·달궁·상승궁을 계산해 Session State에 담아둡니다.

    출생지역을 좌표로 바꾸려면 인터넷에 한 번 다녀와야 해서 잠깐 걸립니다.
    실패해도 앱이 멈추지 않도록 오류는 문구로만 남깁니다.
    """
    st.session_state.astro_info = None
    st.session_state.astro_error = None

    birth_time = (
        None if answers.get("출생시간 모름") else answers.get("출생시간")
    )
    try:
        with st.spinner("출생지역을 찾아 별의 자리를 재고 있어요..."):
            st.session_state.astro_info = compute_astrology(
                birth_date=answers.get("생년월일"),
                birth_time=birth_time,
                birth_place=answers.get("출생지역"),
                calendar_type=answers.get("달력 유형", "양력"),
                leap_month=answers.get("평달/윤달"),
            )
    except (AstrologyError, CalendarError) as exc:
        # 출생지역을 못 찾은 경우가 여기로 옵니다.
        # 검색어(출생지역 원문)는 개인정보라 로그에 적지 않습니다.
        log.warning("점성술 계산 실패 (안내함) — %s: %s", type(exc).__name__, exc)
        st.session_state.astro_error = str(exc)
    except Exception:
        log.exception("점성술 계산 중 예상 못 한 오류")
        st.session_state.astro_error = (
            "별자리를 계산하는 중 알 수 없는 문제가 생겼어요."
        )


def go_to(page_name: str) -> None:
    """화면을 바꾸고 곧바로 다시 그립니다."""
    st.session_state.page = page_name
    st.rerun()


# 고민 분야 선택지
CONCERN_OPTIONS = ["연애", "취업/커리어", "돈", "인간관계", "삶의 방향", "기타"]


def render_model_badge() -> None:
    """지금 무엇으로 답을 만들고 있는지 화면에 보여줍니다.

    개발 중에 가짜 응답이나 가벼운 모델을 쓰고 있다는 걸 잊고
    "품질이 왜 이러지?" 하는 일이 없도록 눈에 보이게 둡니다.
    바꾸는 곳은 config.py 의 USE_MOCK_AI / DEV_MODE 두 줄입니다.

    "DEV MODE", "개발용 모델 gemini-…" 같은 개발자용 문구라서
    일반 사용자에게는 보여주지 않습니다. (config.USE_DEV_MODE)
    """
    if not USE_DEV_MODE:
        return

    if USE_MOCK_AI:
        st.markdown(
            '<div class="halmae-modelbadge halmae-mockbadge">'
            "🧪 <b>DEV MODE · Mock AI</b> — 실제 Gemini를 부르지 않은 예시 답변이에요"
            "</div>",
            unsafe_allow_html=True,
        )
        return

    hint = " · 배포 전 최종 품질 테스트는 " + PROD_MODEL + " 로" if IS_DEV_MODEL else ""
    st.markdown(
        f'<div class="halmae-modelbadge">🛠 {MODEL_STAGE} 모델 '
        f"<b>{GEMINI_MODEL}</b>{hint}</div>",
        unsafe_allow_html=True,
    )


def render_mock_footer() -> None:
    """화면 맨 아래 구석에 작게 붙는 Mock 표시.

    개발자용 문구라서 config.USE_DEV_MODE 가 켜져 있을 때만 나옵니다.
    USE_MOCK_AI = False 로 바꾸면 그때도 나오지 않습니다.
    """
    if not (USE_DEV_MODE and USE_MOCK_AI):
        return
    st.markdown(
        '<div class="halmae-mockfooter">DEV MODE · Mock AI</div>',
        unsafe_allow_html=True,
    )


# ---------------------------------------------------------------
# 4. 할매의 3단계 답변 (halmae_ai.py 가 담당합니다)
#    - 캐릭터, 프롬프트, 응답 구조, Gemini 호출은 모두 halmae_ai.py 에 있습니다.
#    - 여기서는 "언제 부르고, 어떻게 보여줄지"만 다룹니다.
#    - 1단계 → 2단계 → 3단계로 갈수록 앞의 대화를 함께 보내
#      할매가 했던 이야기를 기억한 채로 이어서 말하도록 합니다.
# ---------------------------------------------------------------


# ===============================================================
#  첫 화면
# ===============================================================
def render_intro() -> None:
    track("landing_view")            # 첫 화면을 본 순간

    # 영화 포스터 첫 장면처럼 — 붓글씨 제목 + 영문 서브타이틀 + 금박 라인
    st.markdown(theme.poster_title(), unsafe_allow_html=True)
    st.markdown(theme.rule(), unsafe_allow_html=True)
    render_model_badge()

    st.markdown(
        '<p class="halmae-lead">답이 필요한 날,\n할매에게 한번 물어보렴.</p>',
        unsafe_allow_html=True,
    )
    st.markdown(
        '<p class="halmae-desc">뻔한 달콤한 소리는 거두고,\n'
        '네 팔자를 보고 할매가 딱 짚어줄게.</p>',
        unsafe_allow_html=True,
    )

    if st.button("할매 만나러 가기", type="primary", width="stretch"):
        track_action("start_click")  # 시작 버튼을 누른 순간 (누를 때마다)
        go_to("input")

    st.markdown(
        '<p class="halmae-footnote">사주 · 별자리로 읽는 올해의 자리</p>',
        unsafe_allow_html=True,
    )


# ---------------------------------------------------------------
#  안내 문구
#     실사용자 테스트를 위해, 어떤 값이 어디에 쓰이는지 미리 알려줍니다.
#     법률문서처럼 딱딱하게 쓰지 않되, 사실은 정확하게 적습니다.
# ---------------------------------------------------------------
def render_privacy_notice() -> None:
    """입력 화면 · '할매에게 물어보기' 바로 위에 붙는 안내 쪽지."""
    st.markdown(
        '<div class="halmae-notice">'
        '<p class="halmae-notice-title">잠깐, 이것만 알고 가거라.</p>'
        "<ul>"
        "<li>네가 적은 <b>생년월일·출생시간·출생지역</b>은 사주와 별자리를 셈하고, "
        "너에게 맞는 이야기를 짓는 데 쓰인단다.</li>"
        "<li>이야기를 지으려면 그 값과 <b>네 고민 내용</b>이 "
        "AI(Google Gemini)로 전달될 수 있단다.</li>"
        "<li><b>이름·생년월일·출생시간·출생지역, 그리고 네가 적은 질문 원문</b>은 "
        "기록으로 남기지 않으마.</li>"
        "<li>서비스를 고치는 데 쓰려고, 누구인지 알 수 없는 <b>임시 번호</b>와 "
        "어디까지 봤는지·고민 분야·👍👎 정도만 남긴단다.</li>"
        "</ul>"
        "</div>",
        unsafe_allow_html=True,
    )


def render_disclaimer() -> None:
    """결과 화면 맨 아래 · 서비스 성격 고지."""
    st.markdown(
        '<div class="halmae-disclaimer">'
        "할매의 이야기는 사주·점성술을 활용한 엔터테인먼트 및 자기성찰용 콘텐츠입니다.\n"
        "건강, 투자, 법률 등 중요한 결정은 전문적인 판단을 대신하지 않습니다."
        "</div>",
        unsafe_allow_html=True,
    )


# ===============================================================
#  입력 화면
# ===============================================================
def render_input() -> None:
    st.markdown(theme.poster_title(small=True), unsafe_allow_html=True)
    st.markdown(theme.rule(), unsafe_allow_html=True)
    render_model_badge()
    st.markdown(
        '<p class="halmae-guide">천천히 적어보렴.\n모르는 건 비워두어도 괜찮단다.</p>',
        unsafe_allow_html=True,
    )

    # --- 1. 이름 -------------------------------------------------
    name = st.text_input(
        "이름",
        placeholder="예) 김할매",
        key="in_name",
    )

    # --- 2. 달력 유형 --------------------------------------------
    # 이 값에 따라 아래 '평달/윤달' 항목이 나타나거나 사라집니다.
    calendar_type = st.radio(
        "달력 유형",
        options=["양력", "음력"],
        horizontal=True,
        key="in_calendar_type",
    )

    # --- 3. 생년월일 ---------------------------------------------
    # min_value / max_value 를 지정해야 옛날 연도까지 선택할 수 있습니다.
    birth_date = st.date_input(
        "생년월일",
        value=date(1990, 1, 1),
        min_value=date(1900, 1, 1),
        max_value=date.today(),
        format="YYYY-MM-DD",
        key="in_birth_date",
    )

    # --- 4. 평달 / 윤달 (음력을 고른 경우에만 표시) ----------------
    if calendar_type == "음력":
        leap_month = st.radio(
            "평달 / 윤달",
            options=["평달", "윤달"],
            horizontal=True,
            help="윤달은 음력에서 같은 달이 한 번 더 오는 달이에요. 모르면 '평달'로 두세요.",
            key="in_leap_month",
        )
    else:
        # 양력이면 이 항목 자체를 보여주지 않고, 값은 None으로 저장합니다.
        leap_month = None

    # --- 5. 출생시간 ---------------------------------------------
    # 체크박스를 먼저 그려야, 그 값으로 아래 시간 입력칸을 잠글 수 있습니다.
    unknown_time = st.checkbox("출생시간을 모르겠어요", key="in_unknown_time")

    birth_time_value = st.time_input(
        "출생시간",
        value=time(12, 0),
        step=timedelta(minutes=5),
        disabled=unknown_time,          # 체크하면 입력칸 비활성화
        key="in_birth_time",
    )
    # 모른다고 체크했으면 시간 값은 저장하지 않습니다.
    birth_time = None if unknown_time else birth_time_value

    # --- 6. 출생지역 ---------------------------------------------
    birth_place = st.text_input(
        "출생지역",
        placeholder="예) 서울특별시",
        key="in_birth_place",
    )

    # --- 7. 성별 -------------------------------------------------
    gender = st.radio(
        "성별",
        options=["여성", "남성", "응답하지 않음"],
        key="in_gender",
    )

    # --- 8. 고민 분야 --------------------------------------------
    # 항목이 6개라 세로로 길어지지 않도록 선택 상자를 썼습니다.
    concern = st.selectbox(
        "현재 가장 고민되는 분야",
        options=CONCERN_OPTIONS,
        key="in_concern",
    )

    # --- 9. 추가 질문 --------------------------------------------
    extra_question = st.text_area(
        "추가로 궁금한 내용",
        placeholder="예) 올해 안에 이직해도 괜찮을까요?",
        height=120,
        key="in_extra_question",
    )

    st.markdown("<div style='height: 1rem;'></div>", unsafe_allow_html=True)

    # --- 10. 데이터 사용 안내 + 동의 --------------------------------
    render_privacy_notice()
    consent = st.checkbox(
        "위 내용을 확인했고, AI 분석을 위해 입력 정보를 사용하는 것에 동의해요.",
        key="in_consent",
    )

    # --- 11. 제출 버튼 -------------------------------------------
    #     동의 전에는 눌리지 않도록 잠가둡니다. (체크는 이 하나뿐입니다)
    if not consent:
        st.caption("위 상자에 표시를 해주어야 할매가 이야기를 시작할 수 있단다.")

    if st.button(
        "할매에게 물어보기",
        type="primary",
        width="stretch",
        disabled=not consent,
    ):
        if not name.strip():
            st.warning("이름을 알려주렴. 그래야 불러줄 수 있지 않겠니.")
        else:
            # 입력값을 한 곳에 모아 Session State에 저장합니다.
            # (위젯 값은 화면이 바뀌면 사라질 수 있어서, 따로 복사해 둡니다.)
            st.session_state.answers = {
                "이름": name.strip(),
                "달력 유형": calendar_type,
                "생년월일": birth_date,
                "평달/윤달": leap_month,
                "출생시간": birth_time,
                "출생시간 모름": unknown_time,
                "출생지역": birth_place.strip(),
                "성별": gender,
                "고민 분야": concern,
                "추가 질문": extra_question.strip(),
            }
            # 입력을 마치고 제출한 순간
            # (answers 를 채운 뒤에 불러야 '고민 분야'가 함께 기록됩니다)
            track_action("input_submit")

            # 생년월일 → 양력·음력 변환, 사주 네 기둥 계산
            # (아직 Gemini에는 보내지 않습니다)
            compute_calendar(st.session_state.answers)
            compute_saju_info(st.session_state.answers)
            compute_astro_info(st.session_state.answers)

            # 새로 물어보는 것이므로 이전 대화는 비우고 1단계부터 시작합니다.
            reset_conversation()
            go_to("result")

    if st.button("← 처음으로", type="secondary", width="stretch"):
        go_to("intro")


# ===============================================================
#  결과 화면 (할매의 답변 · 3단계)
# ===============================================================
def render_calendar_check() -> None:
    """생년월일 계산 결과를 확인하는 테스트 화면.

    이번 단계에서는 값이 정확히 나오는지 눈으로 확인하는 것이 목적이라
    결과 화면 맨 위에 펼쳐진 상태로 보여줍니다.
    (아직 이 값을 Gemini에 보내지는 않습니다.)
    """
    with st.expander("🧪 계산 결과 확인 · 양력 / 음력 / 간지", expanded=True):
        if st.session_state.calendar_error:
            st.warning(st.session_state.calendar_error)
            return

        info = st.session_state.calendar_info
        if not info:
            st.caption("계산된 값이 없어요. 입력 화면에서 다시 제출해주세요.")
            return

        rows = [
            ("입력 날짜", info["입력 날짜"]),
            ("양력 날짜", info["양력 날짜 표기"]),
            ("음력 날짜", info["음력 날짜"]),
            ("윤달 여부", "윤달" if info["윤달 여부"] else "평달"),
        ]
        for label, value in rows:
            st.markdown(f"**{label}**  \n{value}")

        # 이 값은 명식이 아닙니다. 그래서 '년주/월주/일주'라고 부르지 않고
        # '음력 연간지/월간지/일간지'라고 적습니다.
        gapja = info["음력 간지(참고용)"]
        st.markdown(
            "**음력 간지 (korean_lunar_calendar · 참고용 · 명식 아님)**  \n"
            f"음력 연간지 {gapja['음력 연간지']['한글']}({gapja['음력 연간지']['한자']}) · "
            f"음력 월간지 {gapja['음력 월간지']['한글']}({gapja['음력 월간지']['한자']}) · "
            f"음력 일간지 {gapja['음력 일간지']['한글']}({gapja['음력 일간지']['한자']})"
        )

        st.caption(
            "이 간지는 korean_lunar_calendar 가 음력 기준으로 낸 값이라 "
            "사주 명식의 년주·월주와 다릅니다. (일간지는 일주와 같습니다) "
            "사주 계산에는 전혀 쓰지 않아요. 명식은 위쪽 '네 명식 (계산 결과)' 와 "
            "'사주 네 기둥' 패널의 절기 기준 값이 원본입니다."
        )

        # 원본 dict 확인 (expander 안에는 expander를 넣을 수 없어 체크박스로)
        # 원본에는 생년월일이 그대로 들어 있어서 USE_DEV_MODE 일 때만 보여줍니다.
        if USE_DEV_MODE and st.checkbox("원본 값 보기 (개발자용)", key="show_raw_calendar"):
            st.write(info)


def render_saju_check() -> None:
    """사주 네 기둥과 오행 분포를 확인하는 테스트 화면.

    이번 단계에서는 값이 정확히 나오는지 눈으로 확인하는 것이 목적이라
    결과 화면 위쪽에 펼쳐진 상태로 보여줍니다.
    (아직 이 값을 Gemini에 보내지는 않습니다.)
    """
    with st.expander("🧪 계산 결과 확인 · 사주 네 기둥 / 오행", expanded=True):
        if st.session_state.saju_error:
            st.warning(st.session_state.saju_error)
            return

        saju = st.session_state.saju_info
        if not saju:
            st.caption("계산된 값이 없어요. 입력 화면에서 다시 제출해주세요.")
            return

        # --- 1. 네 기둥 -------------------------------------------
        for name in ("년주", "월주", "일주", "시주"):
            pillar = saju["기둥"][name]
            if pillar is None:
                st.markdown(f"**{name}**  \n— {saju['시주 제외 사유']}")
                continue
            stem, branch = pillar["천간"], pillar["지지"]
            st.markdown(
                f"**{name}**  \n"
                f"{pillar['한글']} ({pillar['한자']}) · "
                f"천간 {stem['한글']}={stem['오행']} / "
                f"지지 {branch['한글']}={branch['오행']}"
            )

        st.markdown(theme.separator(), unsafe_allow_html=True)

        # --- 2. 오행 분포 -----------------------------------------
        ohaeng = saju["오행 분포"]
        st.markdown(f"**오행 분포** (총 {saju['오행 글자수']}글자)")
        st.markdown(
            "  \n".join(f"- {name}: {ohaeng[name]}" for name in OHAENG_ORDER)
        )

        # --- 3. 계산 근거 -----------------------------------------
        term = saju["적용 절기"]
        st.caption(
            f"월지 {term['월지']} · {term['현재 구간']} {term['절입 시각']} 이후 "
            f"(다음 절기 {term['다음 절기']} {term['다음 절입 시각']})  \n"
            f"입춘 {saju['입춘 시각']} 기준 · 사주상 연도 {saju['사주 기준 연도']}년"
        )
        if saju["시주 계산 근거"]:
            basis = saju["시주 계산 근거"]
            st.caption(
                f"시주 기준: {basis['기준']} · 판정 시각 {basis['판정에 쓴 시각']} "
                f"→ {basis['시지 구간']}"
            )

        # --- 4. 사람이 한 번 더 확인해야 하는 것들 ------------------
        for note in saju["주의사항"]:
            st.info(note, icon="⚠️")

        # 원본 dict / 프롬프트용 글 확인 (expander 안에는 expander를 못 넣습니다)
        # 둘 다 생년월일·출생시간이 그대로 들어 있어 USE_DEV_MODE 일 때만 보여줍니다.
        if USE_DEV_MODE:
            if st.checkbox("Gemini에 보낼 형태 보기 (개발자용)", key="show_saju_prompt"):
                st.code(format_saju_for_prompt(saju), language="text")
            if st.checkbox("원본 값 보기 (개발자용)", key="show_raw_saju"):
                st.write(saju)


def render_astrology_check() -> None:
    """태양궁·달궁·상승궁을 확인하는 개발 테스트 화면.

    아직 이 값을 Gemini에 보내지는 않습니다.
    """
    with st.expander("🧪 점성술 데이터 테스트", expanded=True):
        if st.session_state.astro_error:
            st.warning(st.session_state.astro_error)
            return

        astro = st.session_state.astro_info
        if not astro:
            st.caption("계산된 값이 없어요. 입력 화면에서 다시 제출해주세요.")
            return

        rising = astro["rising_sign"] or f"— {astro['상승궁 제외 사유']}"

        rows = [
            ("출생지역", f"{astro['출생지역 입력']}  ({astro['찾은 지역']})"),
        ]
        # 좌표는 개인정보라 화면에 띄우지 않습니다. (USE_DEV_MODE 일 때만)
        if USE_DEV_MODE:
            rows += [
                ("위도", f"{astro['latitude']}"),
                ("경도", f"{astro['longitude']}"),
            ]
        rows += [
            ("시간대", f"{astro['timezone']}  ({astro['UTC 차이']})"),
            ("Sun Sign", f"{astro['sun_sign']} · {astro['태양']['이름']}"),
            ("Moon Sign", f"{astro['moon_sign']} · {astro['달']['이름']}"),
            ("Rising Sign", rising if not astro["상승점"]
             else f"{astro['rising_sign']} · {astro['상승점']['이름']}"),
        ]
        for label, value in rows:
            st.markdown(f"**{label}**  \n{value}")

        st.caption(
            f"현지 시각 {astro['현지 시각']} → {astro['UTC 시각']}  \n"
            f"태양 황경 {astro['태양']['황경']}° · 달 황경 {astro['달']['황경']}°"
            + (
                f" · 상승점 황경 {astro['상승점']['황경']}°"
                if astro["상승점"] else ""
            )
        )

        for note in astro["주의사항"]:
            st.info(note, icon="⚠️")

        # 원본에는 좌표가 들어 있어 USE_DEV_MODE 일 때만 보여줍니다.
        if USE_DEV_MODE and st.checkbox("원본 값 보기 (개발자용)", key="show_raw_astro"):
            st.write(astro)


def render_calculation_notice() -> None:
    """계산이 실패했을 때 사용자에게 보여줄 짧은 안내.

    사주·별자리 계산 결과를 자세히 보여주던 🧪 패널은 개발자용이라
    일반 사용자에게는 열리지 않습니다(config.USE_DEV_MODE).
    다만 "왜 별자리 이야기가 없는지"는 알 수 있어야 하므로,
    실패했을 때의 짧은 안내 문구만 여기서 대신 보여줍니다.
    (자세한 원인은 화면이 아니라 개발 로그에 남습니다.)
    """
    seen = []
    for message in (
        st.session_state.saju_error,
        st.session_state.astro_error,
        st.session_state.calendar_error,
    ):
        if message and message not in seen:
            seen.append(message)
            st.warning(message)


def render_myeongsik() -> None:
    """확정 명식 — 파이썬이 계산한 값을 화면에 그대로 보여줍니다.

    이 칸에 적히는 값은 전부 saju.compute_saju() 의 결과입니다.
    할매(Gemini)의 답변에서 명식을 되읽어오지 않습니다.
    할매는 이 값을 '해석'만 하고, 값 자체는 여기 적힌 것이 원본입니다.
    """
    saju = st.session_state.saju_info
    if not saju:
        return

    facts = saju_facts(saju)

    _section("네 명식 (계산 결과)")

    pillar_cells = []
    for name in ("년주", "월주", "일주", "시주"):
        value = facts[name]
        if not value:
            value = "—"
        pillar_cells.append(
            f'<div class="halmae-myeongsik-cell">'
            f'<span class="halmae-label">{name}</span>'
            f'<span class="halmae-myeongsik-value">{_escape(value)}</span>'
            f'</div>'
        )

    ohaeng_cells = "".join(
        f'<div class="halmae-myeongsik-cell">'
        f'<span class="halmae-label">{name}</span>'
        f'<span class="halmae-myeongsik-value">{facts["오행 개수"][name]}</span>'
        f'</div>'
        for name in OHAENG_ORDER
    )

    day_master_line = (
        f'<p class="halmae-fact">일간 {_escape(facts["일간"])}</p>'
    )

    foot = f'오행은 {_escape(facts["오행 기준"])} 기준으로 셌어요.'
    if not facts["시주 계산 여부"]:
        foot += f' {_escape(facts["시주 제외 사유"])}.'

    _card(
        f'<div class="halmae-myeongsik-row">{"".join(pillar_cells)}</div>'
        f'{day_master_line}'
        f'<div class="halmae-myeongsik-row">{ohaeng_cells}</div>'
        f'<p class="halmae-card-foot">{foot}</p>'
    )


def ensure_reply(step: int, answers: dict) -> None:
    """해당 단계의 답변이 아직 없을 때만 Gemini를 부릅니다.

    한 번 받아온 답변은 Session State에 남기 때문에,
    버튼을 여러 번 누르거나 화면이 다시 그려져도 같은 요청을 반복하지 않습니다.
    """
    if step in st.session_state.replies or step in st.session_state.errors:
        return

    with st.spinner(LOADING_MESSAGES[step]):
        try:
            st.session_state.replies[step] = ask_halmae(
                step,
                answers,
                st.session_state.history,
                saju=st.session_state.saju_info,
                astro=st.session_state.astro_info,
            )
        except HalmaeError as exc:
            log.warning("%d단계 답변 실패 (안내함) — %s", step, exc)
            st.session_state.errors[step] = str(exc)
        except Exception as exc:          # 예상 못 한 문제로도 앱이 멈추지 않게
            log.exception("%d단계 답변 중 예상 못 한 오류", step)
            db.record_failure(f"step{step}", exc)
            st.session_state.errors[step] = (
                "알 수 없는 문제가 생겼어요. 잠시 뒤에 다시 시도해주세요."
            )


# ---------------------------------------------------------------
#  단계별 답변을 화면에 그리기
#     Gemini가 정해진 구조(JSON)로 답을 주기 때문에,
#     제목 / 근거 / 행동 / 시기 / 상황 / 대사 칸을 나눠서 보여줄 수 있습니다.
# ---------------------------------------------------------------
def _section(title: str) -> None:
    """섹션 소제목."""
    st.markdown(f'<p class="halmae-section">{title}</p>', unsafe_allow_html=True)


def _card(body_html: str) -> None:
    """근거·지령처럼 묶어서 보여줄 내용을 옅은 카드로 감쌉니다."""
    st.markdown(f'<div class="halmae-card">{body_html}</div>', unsafe_allow_html=True)


def _escape(text: str) -> str:
    """줄바꿈을 살리면서 HTML에 안전하게 넣습니다."""
    safe = (
        (text or "")
        .replace("&", "&amp;")
        .replace("<", "&lt;")
        .replace(">", "&gt;")
    )
    return safe.replace("\n", "<br>")


def render_step1(answer) -> None:
    """1단계 — 한 줄 총평 / 근거 / 고민 해석 / 할매의 한마디."""
    st.markdown(
        f'<p class="halmae-headline">"{_escape(answer.headline)}"</p>',
        unsafe_allow_html=True,
    )

    # 사주·점성술 근거는 이 서비스의 핵심이라 가장 눈에 띄게 둡니다.
    _section("할매가 이렇게 보는 이유")
    for evidence in answer.evidences:
        _card(
            f'<span class="halmae-tag">{_escape(evidence.source)}</span>'
            f'<span class="halmae-fact">{_escape(evidence.fact)}</span>'
            f'<p class="halmae-body">{_escape(evidence.reading)}</p>'
        )

    _section("지금 네 상황")
    _card(f'<p class="halmae-body">{_escape(answer.concern_reading)}</p>')

    _section("할매의 한마디")
    st.markdown(
        f'<div class="halmae-quote">{_escape(answer.closing)}</div>',
        unsafe_allow_html=True,
    )


def render_step2(answer) -> None:
    """2단계 — 강점 / 약점 / 놓치고 있는 것 / 판단 기준."""
    st.markdown(answer.opening)

    def insight_block(items, icon: str) -> None:
        for item in items:
            _card(
                f'<p class="halmae-card-title">{icon} {_escape(item.title)}</p>'
                f'<p class="halmae-label">이렇게 보는 까닭</p>'
                f'<p class="halmae-body">{_escape(item.basis)}</p>'
                f'<p class="halmae-label">실제로는 이렇게 나타난단다</p>'
                f'<p class="halmae-body">{_escape(item.in_real_life)}</p>'
            )

    _section("네가 가진 힘")
    insight_block(answer.strengths, "◆")

    _section("자꾸 되풀이하는 버릇")
    insight_block(answer.weaknesses, "◇")

    _section("네가 놓치고 있는 건 이거란다")
    _card(f'<p class="halmae-body">{_escape(answer.blind_spot)}</p>')

    _section("앞으로 고를 때 쓸 잣대")
    for index, rule in enumerate(answer.decision_rules, start=1):
        _card(
            f'<p class="halmae-card-title">기준 {index}. {_escape(rule.rule)}</p>'
            f'<p class="halmae-label">까닭</p>'
            f'<p class="halmae-body">{_escape(rule.why)}</p>'
            f'<p class="halmae-label">쓰는 법</p>'
            f'<p class="halmae-body">{_escape(rule.how_to_use)}</p>'
        )


def render_step3(answer) -> None:
    """3단계 — 행동 지령 3개를 근거/행동/순서/시기/상황/대사로 나눠 보여줍니다."""
    st.markdown(answer.intro)

    for index, directive in enumerate(answer.directives, start=1):
        steps_html = "".join(
            f'<li>{_escape(one_step)}</li>' for one_step in directive.steps
        )
        script_html = ""
        if directive.script.strip():
            script_html = (
                '<p class="halmae-label">이렇게 말해라</p>'
                f'<div class="halmae-script">{_escape(directive.script)}</div>'
            )

        _card(
            f'<p class="halmae-card-title">[지령 {index}] {_escape(directive.title)}</p>'
            f'<p class="halmae-label">근거</p>'
            f'<p class="halmae-body">{_escape(directive.basis)}</p>'
            f'<p class="halmae-label">행동</p>'
            f'<p class="halmae-body">{_escape(directive.action)}</p>'
            f'<p class="halmae-label">실행 순서</p>'
            f'<ol class="halmae-steps">{steps_html}</ol>'
            f'<p class="halmae-label">시기</p>'
            f'<p class="halmae-body">{_escape(directive.timing)}</p>'
            f'<p class="halmae-label">상황</p>'
            f'<p class="halmae-body">{_escape(directive.situation)}</p>'
            f'{script_html}'
            f'<p class="halmae-label">이건 하지 말거라</p>'
            f'<p class="halmae-body">{_escape(directive.avoid)}</p>'
            f'<p class="halmae-label">이렇게 달라진단다</p>'
            f'<p class="halmae-body">{_escape(directive.expected_change)}</p>'
        )

    st.markdown(
        f'<div class="halmae-quote">{_escape(answer.closing)}</div>',
        unsafe_allow_html=True,
    )


STEP_RENDERERS = {1: render_step1, 2: render_step2, 3: render_step3}


# ---------------------------------------------------------------
#  올해의 카드
#
#  파이썬이 계산한 사주·점성술 값 + 올해 간지(세운)만으로
#  올해를 한 장으로 압축합니다. 아직 이미지는 만들지 않고 글자로만 보여줍니다.
#
#  [정책] 카드는 "같은 사람 + 같은 출생정보 + 같은 해"에 딱 한 장입니다.
#  연애로 들어와도 취업으로 들어와도 같은 카드가 나와야 하므로,
#  고민 분야·추가 질문·Step1~3 응답은 열쇠에도, 프롬프트에도 넣지 않습니다.
# ---------------------------------------------------------------
def ensure_year_card() -> None:
    """올해의 카드를 준비합니다.

    같은 사람이 같은 해에 물으면 늘 같은 카드가 나와야 하므로,
    Gemini를 부르기 전에 먼저 저장해둔 카드가 있는지 확인합니다.

        생년월일·출생시간·출생지역·성별·사주·별자리·연도
            → SHA-256 열쇠
            → 저장소에 있으면 그대로 꺼내 쓰고 (API 호출 없음)
            → 없을 때만 Gemini를 부르고, 받은 카드를 저장해둡니다.
    """
    if st.session_state.year_card or st.session_state.year_card_error:
        return

    saju = st.session_state.saju_info
    if not saju:
        st.session_state.year_card_error = (
            "사주를 계산하지 못해서 올해의 카드를 뽑을 수 없어요."
        )
        return

    # --- 1. 이 사람 · 이 해의 열쇠를 만듭니다 --------------------
    #     올해 간지는 파이썬이 계산합니다. (Gemini가 연도를 지어내지 못하게)
    #     이 계산이나 열쇠 만들기가 실패해도 빨간 오류 화면이 뜨지 않도록
    #     통째로 감싸둡니다. 원인은 개발 로그에만 남깁니다.
    try:
        year_ganji = compute_year_ganji()
        st.session_state.year_ganji = year_ganji
        year = year_ganji["연도"]

        # Mock 카드와 진짜 카드가 섞이지 않도록 출처도 열쇠에 넣습니다.
        source = "mock" if USE_MOCK_AI else "gemini"
        key = card_store.build_card_key(
            st.session_state.answers, saju, st.session_state.astro_info,
            year, source,
        )
        st.session_state.year_card_key = key
        st.session_state.year_card_fingerprint = card_store.build_card_fingerprint(
            st.session_state.answers, saju, st.session_state.astro_info,
            year, source,
        )
    except Exception as exc:
        log.exception("올해의 카드 열쇠를 만들지 못했습니다")
        db.record_failure("year_card key", exc)
        st.session_state.year_card_error = (
            "올해의 카드를 준비하는 중 문제가 생겼어요. 잠시 뒤에 다시 눌러주세요."
        )
        return

    # --- 2. 이미 만들어둔 카드가 있으면 그대로 씁니다 -------------
    #     load_card() 는 저장소가 말썽이어도 예외를 내지 않고 None 을 돌려줍니다.
    #     (Supabase 조회 실패 → 개발 로그에만 남고, 아래에서 새로 뽑습니다)
    saved = card_store.load_card(key)
    if saved:
        try:
            st.session_state.year_card = YearCard.model_validate(saved)
            st.session_state.year_card_cached = True
            return                      # Gemini를 부르지 않습니다
        except Exception:
            # 저장된 모양이 옛날 것이라 안 맞으면 새로 뽑습니다.
            log.warning("저장된 카드 모양이 맞지 않아 새로 뽑습니다 · key=%s", key[:16])

    # --- 3. 없을 때만 Gemini를 부르고, 받은 카드를 저장합니다 -----
    with st.spinner(YEAR_CARD_LOADING):
        try:
            # 1~3단계 대화(history)는 일부러 넘기지 않습니다.
            # 그 안에는 고민 분야·추가 질문·Step1~3 응답이 들어 있어서,
            # 넘기면 카드에 "이력서를 고쳐 써라" 같은 고민 전용 행동이 박힙니다.
            # 카드는 계산이 끝난 값(사주·점성술·올해 간지)만으로 만듭니다.
            card = ask_year_card(
                saju,
                st.session_state.astro_info,
                year_ganji,
                year_luck_notes(saju, year_ganji),
            )
            # 카드 글에 이름이 섞여 들어갔으면 여기서 지웁니다.
            # 화면에 보여줄 카드와 저장할 카드에 똑같이 적용해야
            # 나중에 다시 열었을 때 같은 카드가 나옵니다.
            card = YearCard.model_validate(
                card_store.scrub_card(
                    card.model_dump(), st.session_state.answers.get("이름")
                )
            )
            st.session_state.year_card = card
            st.session_state.year_card_cached = False
            card_store.save_card(key, card.model_dump(), year, MODEL_LOG_NAME)
        except HalmaeError as exc:
            log.warning("올해의 카드 실패 (사용자 안내) — %s", exc)
            st.session_state.year_card_error = str(exc)
        except Exception as exc:
            log.exception("올해의 카드를 만들지 못했습니다")
            db.record_failure("year_card", exc)
            st.session_state.year_card_error = (
                "카드를 뽑는 중 알 수 없는 문제가 생겼어요."
            )


def redraw_year_card() -> None:
    """저장된 카드 한 장만 버리고 다시 뽑게 합니다. (개발용)

    지우는 범위는 지금 세션의 열쇠 한 줄뿐입니다.
    다른 사람의 카드나 cards 테이블 전체는 건드리지 않습니다.

    테스트하는 동안 고민 정보가 섞여 만들어진 카드가 남아 있을 때,
    Supabase 를 열지 않고 화면에서 바로 버릴 수 있게 두었습니다.
    """
    key = st.session_state.year_card_key
    if key:
        removed = card_store.delete_card(key)
        log.info("올해의 카드 다시 뽑기 · 지움=%s · key=%s", removed, key[:16])
    st.session_state.year_card = None
    st.session_state.year_card_error = None
    st.session_state.year_card_cached = False


def render_year_card() -> None:
    """Step 3 아래에 붙는 '올해의 카드' 영역."""
    # --- 아직 안 뽑았으면 버튼만 보여줍니다 ----------------------
    if not st.session_state.year_card and not st.session_state.year_card_error:
        st.markdown(
            '<p class="halmae-section">올해의 카드</p>'
            '<p class="halmae-body">여기까지 들은 이야기를 할매가 한 장으로 '
            "묶어주마. 올해 네가 붙들고 갈 딱 한 가지란다.</p>",
            unsafe_allow_html=True,
        )
        if st.button("올해의 카드 받기", type="primary", key="year_card_cta", width="stretch"):
            track_action("card_click")
            ensure_year_card()
            st.rerun()
        return

    if st.session_state.year_card_error:
        st.warning(st.session_state.year_card_error)
        if st.button("카드 다시 뽑기", type="secondary", key="year_card_retry", width="stretch"):
            st.session_state.year_card_error = None
            st.rerun()
        return

    # --- 카드 보여주기 ------------------------------------------
    card = st.session_state.year_card
    ganji = st.session_state.year_ganji
    track("card_view")

    actions_html = "".join(
        f'<li>{_escape(action)}</li>' for action in card.actions
    )
    ganji_html = ""
    if ganji:
        ganji_html = (
            f'<p class="halmae-card-foot">{_escape(ganji["한글"])}년 · '
            f'{_escape(ganji["띠"])}띠</p>'
        )

    st.markdown(
        '<div class="halmae-yearcard">'
        f'<p class="halmae-yearcard-year">{card.year} 올해의 카드</p>'
        f'<p class="halmae-yearcard-title">{_escape(card.title)}</p>'
        f'<p class="halmae-yearcard-keyword">키워드 · {_escape(card.keyword)}</p>'
        f'<p class="halmae-yearcard-message">"{_escape(card.message)}"</p>'
        f"{ganji_html}"
        "</div>",
        unsafe_allow_html=True,
    )

    _card(
        '<p class="halmae-label">왜 이 카드가 나왔나</p>'
        f'<p class="halmae-body">{_escape(card.basis)}</p>'
        '<p class="halmae-label">올해 가장 중요한 것</p>'
        f'<ol class="halmae-steps">{actions_html}</ol>'
        '<p class="halmae-label">이것만은 조심하거라</p>'
        f'<p class="halmae-body">{_escape(card.caution)}</p>'
    )

    st.caption(
        "이 카드는 네 출생정보와 올해 기운으로 정해진 것이라, "
        "다시 열어도 같은 카드가 나온단다."
    )
    st.caption("카드를 저장하거나 나눠보고 싶으면 아래 글을 복사하세요.")
    st.code(format_year_card_text(card, ganji), language="text")

    # 개발자 확인용 -----------------------------------------------
    #  · 저장된 걸 꺼내 썼는지 / 새로 만들었는지는 늘 보여줍니다.
    #  · 열쇠와 지문에는 생년월일·좌표가 들어 있어 따로 눌러야 보입니다.
    #  · '이 카드만 다시 뽑기' 는 지금 이 열쇠 한 줄만 지웁니다.
    #    (테스트 중 고민이 섞여 만들어진 카드를 버릴 때 씁니다)
    if USE_DEV_MODE:
        st.caption(
            ("저장된 카드를 그대로 꺼내 썼어요 (Gemini 호출 없음)"
             if st.session_state.year_card_cached
             else "새로 만들어 저장했어요 (Gemini 1회 호출)")
        )
        if st.button("이 카드만 다시 뽑기 (개발자용)",
                     type="secondary", key="year_card_redraw", width="stretch"):
            redraw_year_card()
            st.rerun()
        if st.checkbox("카드 열쇠 보기 (개발자용)", key="show_card_key"):
            st.caption(
                "아래 지문에는 생년월일·좌표가 들어 있어요. "
                "화면을 캡처해 공유하지 마세요."
            )
            st.code(
                f"key         : {st.session_state.year_card_key}\n"
                f"fingerprint : {st.session_state.year_card_fingerprint}",
                language="text",
            )


# ---------------------------------------------------------------
#  사용자 피드백 — 클릭 한 번으로 끝
#
#  추가 설문 없이 👍 / 👎 만 받습니다.
#  마음이 바뀌어 다시 눌러도 새 줄을 쌓지 않고 마지막 답만 남깁니다.
# ---------------------------------------------------------------
FEEDBACK_MESSAGES = {
    "positive": "오냐, 할매가 제대로 짚었구나.",
    "negative": "어허, 다음엔 더 제대로 들여다보마.",
}

# 지금 무엇을 골랐는지 글로 보여줄 때 쓰는 이름표
FEEDBACK_LABELS = {"positive": "👍 맞아요", "negative": "👎 아니에요"}


def render_feedback() -> None:
    """Step 3 · 올해의 카드를 본 뒤, Premium 바로 위에 붙는 피드백 영역.

    화면에 보이는 것은 제목 한 줄과 버튼 두 개가 전부입니다.

        할매 말, 잘 맞았나요?
        [ 👍 맞아요 ]   [ 👎 아니에요 ]

    지금 고른 쪽은 primary(금색 채움), 고르지 않은 쪽은 secondary(테두리만)로
    그려서 무엇을 골랐는지 버튼 자체로 알 수 있게 했습니다.
    이모지만 따로 뜨는 위젯과 안내 문구를 함께 두면 같은 말이 두 번 보여서,
    버튼 하나로 합치고 나머지는 없앴습니다.

    저장 방식은 그대로입니다 — analytics.save_feedback() 이 session_id 당
    한 줄만 두고, 마음이 바뀌면 새 줄을 쌓지 않고 그 줄을 고쳐 씁니다.
    """
    track("feedback_view")           # 피드백 영역이 눈에 보인 순간

    st.markdown(
        '<p class="halmae-feedback-title">할매 말, 잘 맞았나요?</p>',
        unsafe_allow_html=True,
    )

    current = st.session_state.feedback_result      # None / positive / negative

    # 지금 고른 쪽만 primary 로 그려서 선택 상태를 눈에 보이게 합니다.
    def _button_type(name: str) -> str:
        return "primary" if current == name else "secondary"

    good_col, bad_col = st.columns(2)
    chosen = None
    if good_col.button(
        FEEDBACK_LABELS["positive"],
        key="feedback_yes",
        type=_button_type("positive"),
        width="stretch",
    ):
        chosen = "positive"
    if bad_col.button(
        FEEDBACK_LABELS["negative"],
        key="feedback_no",
        type=_button_type("negative"),
        width="stretch",
    ):
        chosen = "negative"

    # 답이 '바뀌었을 때만' 저장합니다.
    # (버튼은 누른 순간에만 True 라서 rerun 으로는 여기까지 오지 않습니다.
    #  같은 쪽을 또 눌러도 값이 그대로면 아무것도 하지 않습니다.)
    if chosen and chosen != current:
        st.session_state.feedback_result = chosen
        # 최종 답 저장 (같은 세션이면 새 줄을 쌓지 않고 덮어씁니다)
        analytics.save_feedback(
            session_id=st.session_state.session_id,
            feedback_result=chosen,
            concern=st.session_state.answers.get("고민 분야"),
            model=MODEL_LOG_NAME,
        )
        # 행동 로그 — 👍 → 👎 로 바꾼 것은 사용자가 실제로 한 행동이라
        # 그때마다 한 줄 남깁니다.
        track_action(f"feedback_{chosen}")
        # 버튼 모양(primary/secondary)은 위에서 이미 그려졌으므로,
        # 방금 누른 쪽이 곧바로 강조되도록 화면을 다시 그립니다.
        st.rerun()

    if current is None:
        return

    st.markdown(
        f'<div class="halmae-quote">{_escape(FEEDBACK_MESSAGES[current])}</div>',
        unsafe_allow_html=True,
    )
    st.caption("마음이 바뀌면 다른 쪽을 눌러 바꿀 수 있어요. (마지막 답 하나만 남습니다)")


# ---------------------------------------------------------------
#  Premium Fake-door 테스트
#
#  ※ 실제 결제는 어디에서도 일어나지 않습니다.
#     카드 정보도, 회원가입도, 이메일도 받지 않습니다.
#     "3,900원이면 써보겠다"는 마음이 있는지 클릭으로만 재보는 것이 전부입니다.
#     버튼을 누르면 곧바로 베타 테스트라는 사실을 알려줍니다.
# ---------------------------------------------------------------
PREMIUM_PRICE = "3,900원"


def render_premium() -> None:
    """Step 3 아래에 붙는 Premium 영역."""
    track("premium_view")            # Premium 영역을 본 순간

    st.markdown(
        '<div class="halmae-premium">'
        '<p class="halmae-premium-title">🔮 할매의 비밀 처방</p>'
        '<p class="halmae-premium-desc">할매가 네 고민을 한 단계 더 깊게 들여다보고,<br>'
        '더 구체적인 행동 방향을 짚어줄게.</p>'
        f'<p class="halmae-premium-price">{PREMIUM_PRICE}'
        '<span class="halmae-beta-tag">베타 테스트</span></p>'
        "</div>",
        unsafe_allow_html=True,
    )

    # 누르기 '전'에도 결제가 없다는 걸 분명히 알려줍니다.
    # (Fake-door 테스트라도 사용자가 결제되는 줄 알고 누르게 두면 안 됩니다.)
    st.caption(
        "※ 베타 테스트로 실제 결제는 진행되지 않습니다. "
        "카드 정보·회원가입·이메일을 받지 않고, 눌러도 돈이 빠져나가지 않아요."
    )

    # --- 아직 CTA를 누르지 않은 상태 ---------------------------
    if not st.session_state.premium_open:
        if st.button("더 깊은 처방 받아보기", type="primary", key="premium_cta", width="stretch"):
            track_action("premium_click")   # CTA를 누른 순간
            st.session_state.premium_open = True
            st.rerun()
        return

    # --- CTA를 누른 뒤: 결제 대신 베타 안내를 보여줍니다 ---------
    st.markdown(
        '<div class="halmae-fakedoor">'
        '<p class="halmae-fakedoor-title">아직 할매가 준비 중이란다</p>'
        '<p class="halmae-fakedoor-body">'
        "현재 베타 테스트 중이라 <b>실제 결제는 진행되지 않아요.</b><br>"
        "정식 출시된다면 이 가격에 이용해보고 싶으신가요?"
        "</p>"
        "</div>",
        unsafe_allow_html=True,
    )

    # --- 아직 답을 고르지 않았으면 두 버튼을 보여줍니다 ----------
    if st.session_state.purchase_intent is None:
        yes_col, no_col = st.columns(2)
        if yes_col.button("네, 이용해보고 싶어요", type="primary", key="intent_yes", width="stretch"):
            track_action("purchase_intent_yes")
            st.session_state.purchase_intent = "yes"
            st.rerun()
        if no_col.button("조금 더 고민해볼게요", type="secondary", key="intent_no", width="stretch"):
            track_action("purchase_intent_no")
            st.session_state.purchase_intent = "no"
            st.rerun()
        return

    # --- 답을 고른 뒤 인사말 (버튼은 사라집니다) -----------------
    if st.session_state.purchase_intent == "yes":
        message = (
            "오냐, 잘 새겨두마. 할미가 처방을 다 갈무리하면 그때 다시 들르거라."
        )
    else:
        message = (
            "그래, 천천히 생각해보거라. 서두른다고 답이 빨리 나오는 건 아니란다."
        )
    st.markdown(
        f'<div class="halmae-quote">{_escape(message)}</div>',
        unsafe_allow_html=True,
    )
    st.caption("※ 결제는 이루어지지 않았습니다. 베타 테스트 응답만 기록됐어요.")


def render_result() -> None:
    answers = st.session_state.answers

    # 입력값 없이 이 화면에 들어온 경우(새로고침 등)에는 입력 화면으로 돌려보냅니다.
    if not answers:
        go_to("input")

    st.markdown(theme.poster_title(small=True), unsafe_allow_html=True)
    st.markdown(theme.rule(), unsafe_allow_html=True)
    render_model_badge()

    # --- 0. 계산 결과 확인 ------------------------------------------
    #     🧪 패널 세 개는 사주·별자리 계산이 맞는지 눈으로 확인하려고 만든
    #     개발자용 화면입니다. (원본 값 · 절기 계산 근거 · 좌표 · 프롬프트 형태)
    #     일반 사용자에게는 열지 않고, 계산이 실패했을 때의 안내만 보여줍니다.
    if USE_DEV_MODE:
        render_saju_check()
        render_astrology_check()
        render_calendar_check()
    else:
        render_calculation_notice()

    # --- 0-1. 확정 명식 (모든 사용자에게 보여줍니다) ------------------
    #     여기 적히는 값은 전부 파이썬 계산 결과입니다.
    #     할매의 답변 글에서 명식을 되읽어오지 않습니다. (계산 ≠ 해석)
    render_myeongsik()

    # --- 1. 열려 있는 단계를 위에서부터 차례로 보여줍니다 -----------
    #     이미 받아둔 답변은 st.session_state.replies에 남아 있어서,
    #     다음 단계로 넘어가도 앞의 이야기가 그대로 보입니다.
    for step in range(1, st.session_state.step + 1):
        ensure_reply(step, answers)

        st.markdown(
            f'<p class="halmae-step-badge">{step} / 3</p>'
            f'<p class="halmae-step-title">{STEP_TITLES[step]}</p>',
            unsafe_allow_html=True,
        )

        # 이 단계가 실패했다면 안내 문구와 다시 시도 버튼만 보여주고 멈춥니다.
        if step in st.session_state.errors:
            st.error(st.session_state.errors[step])
            if st.button("다시 물어보기", type="primary", key=f"retry_{step}", width="stretch"):
                st.session_state.errors.pop(step, None)
                st.rerun()
            break

        # 답변이 실제로 화면에 그려지는 순간에만 기록합니다.
        # (오류가 났으면 위에서 break 되므로 여기까지 오지 않습니다.)
        track(f"step{step}_view")

        STEP_RENDERERS[step](st.session_state.replies[step])
        st.markdown(theme.separator(), unsafe_allow_html=True)

        # 마지막으로 열린 단계 아래에만 "다음 이야기" 버튼을 답니다.
        # (버튼을 여러 번 눌러도 이미 받아둔 답변이 있으면 다시 호출하지 않습니다.)
        is_last_shown = step == st.session_state.step
        if is_last_shown and step < 3:
            if st.button(
                NEXT_BUTTON_LABELS[step + 1],
                type="primary",
                key=f"next_{step + 1}",
                width="stretch",
            ):
                # 2단계로 갈 때는 more_click, 3단계로 갈 때는 action_click
                track_action("more_click" if step == 1 else "action_click")
                st.session_state.step = step + 1
                st.rerun()

        # 3단계(행동 지령)를 끝까지 보여준 뒤에만
        # 올해의 카드 → Premium 순서로 답니다.
        if step == 3:
            render_year_card()
            st.markdown(theme.separator(), unsafe_allow_html=True)
            render_feedback()
            st.markdown(theme.separator(), unsafe_allow_html=True)
            render_premium()

    # --- 2. 개발자용: 보낸 값과 프롬프트 확인 -----------------------
    #     여기에는 이름·생년월일·출생시간·출생지역·추가 질문 원문과
    #     Gemini 프롬프트·응답 전문이 그대로 나옵니다.
    #     일반 사용자에게는 절대 보이면 안 되므로 USE_DEV_MODE 일 때만 엽니다.
    #     (저장은 원래부터 하지 않습니다 — 화면 노출만 막는 것입니다.)
    if USE_DEV_MODE:
        with st.expander("개발자용 · 입력값과 프롬프트 보기"):
            st.caption(
                f"{MODEL_LABEL} · 대화 기록 {len(st.session_state.history)}개"
            )
            if IS_DEV_MODEL:
                st.caption(
                    "지금은 무료 quota 를 아끼려고 가벼운 개발용 모델을 쓰고 있어요. "
                    "최종 답변 품질 테스트는 halmae_ai.py 의 DEV_MODE 를 False 로 "
                    f"바꾼 뒤에 하세요. ({PROD_MODEL} 로 전환됩니다)"
                )
            st.write(answers)

            st.caption("Gemini에 실제로 보낸 질문 (사주·점성술 값이 함께 들어갑니다)")
            for step in range(1, st.session_state.step + 1):
                st.code(
                    build_prompt(
                        step,
                        answers,
                        st.session_state.saju_info,
                        st.session_state.astro_info,
                    ),
                    language="text",
                )

            st.caption("Gemini가 돌려준 구조화 데이터")
            for step in range(1, st.session_state.step + 1):
                reply = st.session_state.replies.get(step)
                if reply is None:
                    continue
                st.caption(f"{step}단계 · {answer_length(reply)}자")
                st.json(reply.model_dump())

    st.markdown("<div style='height: 1rem;'></div>", unsafe_allow_html=True)

    if st.button("다시 입력하기", type="primary", key="result_again", width="stretch"):
        reset_conversation()
        go_to("input")

    if st.button("← 처음으로", type="secondary", key="result_home", width="stretch"):
        reset_conversation()
        go_to("intro")

    # 화면 맨 아래 · 이 서비스가 어떤 성격인지 조용히 밝혀둡니다.
    render_disclaimer()


# ===============================================================
#  개발자 전용 · Funnel 분석 화면
#
#  일반 사용자에게는 보이지 않습니다.
#  주소 뒤에 ?dev=1 을 붙였을 때만 이 화면이 열립니다.
#      내 컴퓨터   http://localhost:8501/?dev=1
#
#  배포한 뒤에는 반드시 암호를 정해두세요. 주소만 알면 누구나 지표를 보게 됩니다.
#      내 컴퓨터   export HALMAE_DEV_KEY="아무거나정한암호"
#      Cloud      Settings → Secrets 에  HALMAE_DEV_KEY = "아무거나정한암호"
#      → https://<내앱>.streamlit.app/?dev=아무거나정한암호
# ===============================================================
def render_storage_status() -> None:
    """지금 로그가 어디에 저장되고 있는지, 실패한 건 없는지 한눈에 보여줍니다.

    Supabase 저장이 실패하면 사용자 화면은 그대로 흘러가지만
    데이터는 조용히 사라집니다. 그런 일이 있었는지 여기서 확인할 수 있습니다.
    """
    connected = db.is_available()
    using_supabase = db.use_supabase()
    failures = db.failure_count()

    if using_supabase and connected and failures == 0:
        st.success(f"저장소: {analytics.storage_label()}", icon="✅")
    elif using_supabase and connected:
        st.warning(
            f"저장소: {analytics.storage_label()}  \n"
            f"Supabase 저장 실패 {failures}건 — 실패한 줄은 로컬 파일에 대신 적어두었습니다.",
            icon="⚠️",
        )
    elif using_supabase:
        st.error(
            f"Supabase 에 연결하지 못했습니다 — {db.last_error()}  \n"
            f"지금은 로컬 파일({analytics.DEFAULT_CSV_PATH})에 저장하고 있습니다.",
            icon="🚨",
        )
    else:
        st.info(
            f"저장소: {analytics.storage_label()}  \n"
            "환경변수 SUPABASE_URL · SUPABASE_SECRET_KEY 를 넣으면 Supabase 로 저장됩니다.",
            icon="🗂️",
        )

    with st.expander(f"저장소 자세히 보기 (실패 {failures}건)"):
        st.write(
            {
                **db.status(),
                "저장 모드(HALMAE_STORAGE)": db.storage_mode(),
                "이벤트·피드백": analytics.storage_label(),
                "올해의 카드": card_store.storage_label(),
            }
        )
        if failures:
            st.markdown("**Supabase 저장 실패 기록**")
            st.dataframe(db.failures(), hide_index=True, width="stretch")
        st.caption(
            "SECRET_KEY 는 가운데를 가려서 보여줍니다. 열쇠 전체는 화면에 찍지 않습니다."
        )


def render_dev_funnel() -> None:
    st.markdown('<h2 class="halmae-title-sm">할매 · Funnel</h2>', unsafe_allow_html=True)
    st.markdown(theme.rule(), unsafe_allow_html=True)
    st.caption("개발자 전용 화면입니다. 일반 사용자에게는 보이지 않습니다.")

    render_storage_status()

    # 이벤트는 여기서 딱 한 번만 읽어옵니다.
    # (아래 네 개의 요약이 저마다 Supabase 를 다녀오면 화면이 느려집니다.)
    events = analytics.snapshot_store()

    summary = analytics.funnel_summary(events)
    total = summary["총 세션"]

    left, right = st.columns(2)
    left.metric("총 세션", total)
    right.metric("기록된 이벤트", summary["총 이벤트"])

    if total == 0:
        st.info(
            "아직 기록된 로그가 없어요. 앱을 한 바퀴 돌아본 뒤 이 화면을 새로고침해보세요.",
            icon="🗒️",
        )
    else:
        st.markdown("**단계별 도달 세션과 전환율**")
        st.dataframe(
            [
                {
                    "단계": step["label"],
                    "이벤트": step["event"],
                    "세션 수": step["세션 수"],
                    "직전 대비": (
                        "-" if step["직전 대비"] is None
                        else f"{step['직전 대비']}%"
                    ),
                    "전체 대비": (
                        "-" if step["전체 대비"] is None
                        else f"{step['전체 대비']}%"
                    ),
                }
                for step in summary["단계"]
            ],
            hide_index=True,
            width="stretch",
        )

        st.markdown("**터미널에서 보던 그대로**")
        st.code(analytics.format_funnel_text(summary), language="text")

    # --- 올해의 카드 지표 ---------------------------------------
    st.markdown(theme.rule(), unsafe_allow_html=True)
    st.markdown("### 🃏 올해의 카드")
    st.caption(
        "Step 3 화면에서 Premium 과 나란히 보이는 곁가지라, 위 깔때기와 따로 셉니다."
    )

    card_stats = analytics.card_summary(events)
    card_counts = card_stats["counts"]
    card_cols = st.columns(4)
    card_cols[0].metric("Step 3 조회자", card_counts["step3_view"])
    card_cols[1].metric("카드 받기 클릭", card_counts["card_click"])
    card_cols[2].metric(
        "카드 클릭률",
        "-" if card_stats["카드 클릭률"] is None else f"{card_stats['카드 클릭률']}%",
        help="card_click ÷ step3_view",
    )
    card_cols[3].metric(
        "카드 완료율",
        "-" if card_stats["카드 완료율"] is None else f"{card_stats['카드 완료율']}%",
        help="card_view ÷ card_click · 낮으면 카드 생성이 실패하고 있다는 뜻",
    )

    # --- 사용자 피드백 지표 -------------------------------------
    st.markdown(theme.rule(), unsafe_allow_html=True)
    st.markdown("### 👍 사용자 피드백")
    st.caption(
        "👍/👎 개수는 이벤트 일지가 아니라 '최종 답 파일'에서 셉니다. "
        "마음을 바꾼 사람이 양쪽에 두 번 세어지지 않도록요."
    )

    fb = analytics.feedback_summary(events)
    fb_top = st.columns(3)
    fb_top[0].metric("전체 피드백", fb["전체 피드백"])
    fb_top[1].metric(
        "👍 맞아요",
        f"{fb['긍정']}"
        + ("" if fb["긍정 비율"] is None else f" ({fb['긍정 비율']}%)"),
    )
    fb_top[2].metric(
        "👎 아니에요",
        f"{fb['부정']}"
        + ("" if fb["부정 비율"] is None else f" ({fb['부정 비율']}%)"),
    )

    fb_bottom = st.columns(3)
    fb_bottom[0].metric(
        "응답률",
        "-" if fb["응답률"] is None else f"{fb['응답률']}%",
        help="피드백을 남긴 사람 ÷ 피드백 영역을 본 사람",
    )
    fb_bottom[1].metric(
        "긍정 → CTA 클릭률",
        "-" if fb["긍정→CTA 클릭률"] is None else f"{fb['긍정→CTA 클릭률']}%",
        help="👍 를 준 사람 중 Premium CTA 를 누른 비율",
    )
    fb_bottom[2].metric(
        "부정 → CTA 클릭률",
        "-" if fb["부정→CTA 클릭률"] is None else f"{fb['부정→CTA 클릭률']}%",
        help="👎 를 준 사람 중 Premium CTA 를 누른 비율",
    )

    if fb["전체 피드백"] == 0:
        st.info(
            "아직 피드백이 없어요. Step 3까지 진행한 뒤 👍 나 👎 를 눌러보세요.",
            icon="👍",
        )
    else:
        st.code(analytics.format_feedback_text(fb), language="text")

    # --- Premium Fake-door 지표 ---------------------------------
    st.markdown(theme.rule(), unsafe_allow_html=True)
    st.markdown("### 🔮 Premium Fake-door")
    st.caption("실제 결제는 일어나지 않습니다. 클릭으로만 유료 의향을 재는 테스트예요.")

    premium = analytics.premium_summary(events)
    counts = premium["counts"]

    top = st.columns(3)
    top[0].metric("Step 3 조회자", counts["step3_view"])
    top[1].metric("Premium 조회자", counts["premium_view"])
    top[2].metric("CTA 클릭자", counts["premium_click"])

    bottom = st.columns(3)
    bottom[0].metric("구매 의향 Yes", counts["purchase_intent_yes"])
    bottom[1].metric("구매 의향 No", counts["purchase_intent_no"])
    bottom[2].metric(
        "CTA 클릭률",
        "-" if premium["CTA 클릭률"] is None else f"{premium['CTA 클릭률']}%",
        help="premium_click ÷ premium_view",
    )

    rate_cols = st.columns(3)
    rate_cols[0].metric(
        "구매 의향률",
        "-" if premium["구매 의향률"] is None else f"{premium['구매 의향률']}%",
        help="purchase_intent_yes ÷ premium_click",
    )
    rate_cols[1].metric(
        "의향 응답률",
        "-" if premium["의향 응답률"] is None else f"{premium['의향 응답률']}%",
        help="(Yes + No) ÷ premium_click · 누르고 답 없이 나간 비율을 보는 참고값",
    )
    rate_cols[2].metric(
        "Premium 도달률",
        "-" if premium["Premium 도달률"] is None else f"{premium['Premium 도달률']}%",
        help="premium_view ÷ step3_view",
    )

    if counts["premium_view"] == 0:
        st.info(
            "아직 Premium 영역까지 온 사람이 없어요. "
            "Step 3까지 진행해보면 지표가 쌓입니다.",
            icon="🔮",
        )
    else:
        st.code(analytics.format_premium_text(premium), language="text")

    st.caption(
        f"저장 위치: {analytics.storage_label()}  \n"
        "개인정보(이름·생년월일·출생시간·출생지역·좌표·추가 질문·"
        "Gemini 프롬프트와 답변 원문)는 어디에도 기록하지 않습니다."
    )

    if st.checkbox("원본 이벤트 보기", key="show_raw_events"):
        rows = events.read_all()
        st.caption(f"{len(rows)}건")
        st.dataframe(rows[-200:], hide_index=True, width="stretch")


# ===============================================================
#  현재 단계에 맞는 화면을 그립니다.
#
#  [마지막 안전망]
#  화면을 그리다 예상 못 한 오류가 나면 Streamlit 은 빨간 traceback 을
#  통째로 띄웁니다. 실사용자 테스트에서는 그 화면 자체가 사고입니다.
#  (코드 경로 · 변수 이름이 그대로 노출되고, 사용자는 무엇을 해야 할지 모릅니다.)
#
#  그래서 여기서 한 번 더 받아냅니다.
#      사용자에게  → 짧고 이해되는 문구 + 처음으로 돌아가는 버튼
#      개발 로그에  → traceback 전문 (터미널 · Streamlit Cloud 의 Logs)
#
#  st.rerun() · st.stop() 도 '예외'로 흐름을 바꾸기 때문에,
#  그 둘은 붙잡지 않고 그대로 통과시켜야 화면 전환이 정상 동작합니다.
# ===============================================================
try:
    from streamlit.runtime.scriptrunner_utils.exceptions import (
        ScriptControlException,
    )
    CONTROL_FLOW_EXCEPTIONS: tuple = (ScriptControlException,)
except Exception:                      # Streamlit 버전이 달라 경로가 바뀐 경우
    CONTROL_FLOW_EXCEPTIONS = ()


def render_current_page() -> None:
    if IS_DEV_FUNNEL:
        render_dev_funnel()
    elif st.session_state.page == "intro":
        render_intro()
    elif st.session_state.page == "input":
        render_input()
    else:
        render_result()


try:
    render_current_page()
except CONTROL_FLOW_EXCEPTIONS:
    # st.rerun() / st.stop() — 오류가 아니라 화면 전환 신호입니다. 그대로 넘깁니다.
    raise
except Exception as unexpected:
    # Streamlit 버전이 올라가 위 import 경로가 바뀌었더라도
    # 화면 전환 신호(rerun/stop)를 오류로 삼키지 않도록 이름으로 한 번 더 확인합니다.
    if type(unexpected).__name__ in (
        "RerunException", "StopException", "ScriptControlException",
    ):
        raise

    # 원인은 개발 로그에만 (개인정보는 애초에 담기지 않는 값들입니다)
    log.exception("화면을 그리는 중 예상 못 한 오류 · page=%s",
                  st.session_state.get("page"))
    db.record_failure("render", unexpected, str(st.session_state.get("page")))

    st.error(
        "화면을 그리는 중 문제가 생겼어요.  \n"
        "잠시 뒤에 다시 시도해주시고, 계속 그러면 처음부터 다시 시작해주세요.",
        icon="🕯️",
    )
    if st.button("처음부터 다시 시작하기", type="primary", key="fatal_restart"):
        reset_conversation()
        st.session_state.page = "intro"
        st.rerun()

# 어느 화면이든 맨 아래 구석에 Mock 표시를 붙입니다. (실제 모드에서는 안 나옵니다)
render_mock_footer()
