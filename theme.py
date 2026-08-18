"""할매 · 디자인 시스템 (Design System)

화면의 색·글꼴·간격을 이 파일 한 곳에 모아두었습니다.
app.py 는 build_css() 가 만들어준 CSS 를 붙이기만 하므로,
디자인을 바꾸고 싶으면 여기 토큰(TOKENS)만 고치면 됩니다.

    python theme.py           # 색 대비(가독성) 검사 결과를 출력

--------------------------------------------------------------------
 브랜드 방향 · 조선 왕실의 색을 빌린 자개장
--------------------------------------------------------------------
    오래된 자개장이 열리는 순간.
    먹빛 배경 위로 곤룡포의 대홍(大紅)과 비취, 그리고 금박이 드러난다.

    색은 조선 왕실 의복에서 가져왔다.
        대홍(大紅)   임금의 곤룡포 — 권위와 강렬함
        자적(紫赤)   왕세자·왕비의 붉은 자주 — 깊이
        비취/옥색     옥대와 노리개 — 차가운 대비
        남색(藍)     관복의 청 — 신비로움
        금박(金箔)   장식 — 화려함의 마침표
        상아/한지    바탕 — 숨 쉴 곳

    알록달록하게 늘어놓지 않는다.
    어두운 바탕을 유지한 채, 강한 색을 '적은 면적'에 놓아
    화려하되 촌스럽지 않게 만든다.

--------------------------------------------------------------------
 제1원칙 · 가독성이 분위기보다 먼저다
--------------------------------------------------------------------
    색이 화려해질수록 글씨가 묻히기 쉽다.
    그래서 이 파일의 모든 '텍스트 색 : 배경 색' 조합은
    WCAG 명도 대비 기준을 넘도록 정해두었고,
    python theme.py 로 언제든 다시 검사할 수 있다.

        본문(작은 글씨)   4.5 : 1 이상  (AA)
        큰 글씨/제목      3.0 : 1 이상  (AA Large)

--------------------------------------------------------------------
 컬러 시스템 (포트폴리오 스타일 가이드에 그대로 옮길 수 있는 단위)
--------------------------------------------------------------------
    Primary   · Royal Red    대홍 / 자적       — 타이틀, CTA, 강조
    Secondary · Jade & Indigo 비취 / 남색       — 근거 태그, 보조 포인트
    Accent    · Gold          금박             — 테두리, 라벨, 장식
    Background· Dark Wood/Ink 먹빛 목재         — 4단계 깊이
    Neutral   · Ivory         상아 / 한지       — 본문 텍스트, 입력 바탕
"""

# ===================================================================
#  1. TOKENS — 디자인 토큰
#     이름은 '쓰임새'로 짓습니다. (red_1 이 아니라 royal_red_soft)
# ===================================================================
TOKENS = {
    # ---------------------------------------------------------------
    # BACKGROUND · Dark Wood / Ink
    #   자주빛이 아주 살짝 도는 먹색. 순수한 갈색보다 색기(色氣)가 있습니다.
    # ---------------------------------------------------------------
    "bg_deep": "#0C0609",       # 가장 깊은 바닥
    "bg_base": "#170D12",       # 기본 배경
    "bg_panel": "#241419",      # 카드·패널
    "bg_raised": "#331C22",     # 카드 안에서 한 겹 올라온 면
    "bg_paper": "#F5EAD4",      # 한지 — 입력창처럼 '밝아야 하는' 곳에만

    # ---------------------------------------------------------------
    # PRIMARY · Royal Red (대홍 · 자적)
    #   임금의 곤룡포 색. 가장 강한 자리에만 씁니다.
    # ---------------------------------------------------------------
    "royal_red": "#A81D33",         # 대홍 — 면(버튼·배지) 채우기
    "royal_red_deep": "#5E0F1E",    # 자적 — 그러데이션 아래쪽
    "royal_red_soft": "#EE8496",    # 어두운 배경 위 '붉은 글씨' 전용
    "royal_red_line": "#8A2438",    # 붉은 테두리

    # ---------------------------------------------------------------
    # SECONDARY · Jade & Indigo (비취 · 남색)
    #   붉은색의 열기를 식혀주는 차가운 색. 근거 태그처럼 정보성 요소에.
    # ---------------------------------------------------------------
    "jade": "#1F7A6E",
    "jade_soft": "#7FD4C4",     # 어두운 배경 위 '옥색 글씨' 전용
    "jade_line": "#2F6E66",
    "indigo": "#243C74",
    "indigo_soft": "#8FAEE8",   # 어두운 배경 위 '남색 글씨' 전용

    # ---------------------------------------------------------------
    # ACCENT · Gold (금박)
    # ---------------------------------------------------------------
    "gold": "#D2A62E",          # 기본 금색 (테두리·라벨)
    "gold_bright": "#F3D88F",   # 밝은 금 (어두운 배경 위 강조 텍스트)
    "gold_dim": "#8C6E22",      # 어두운 금 (얇은 선)

    # ---------------------------------------------------------------
    # NEUTRAL · Ivory (상아 · 한지)
    #   본문은 순백이 아니라 상아빛. 어두운 배경에서 눈이 덜 부십니다.
    # ---------------------------------------------------------------
    "ivory": "#F8EFDC",         # 본문 (가장 많이 쓰임)
    "ivory_mid": "#D6C3A6",     # 보조 설명
    "ivory_low": "#A6927A",     # 캡션·각주

    # 밝은 면 위에 올라가는 글씨
    "text_on_paper": "#2A1B18",  # 한지 배경 위
    "text_on_gold": "#1A1006",   # 금색 버튼 위
    "text_on_red": "#FFF3F0",    # 붉은 면 위

    # ---------------------------------------------------------------
    # LINES
    # ---------------------------------------------------------------
    "line": "#3E2A2F",          # 기본 구분선
    "line_gold": "#7A6026",     # 금박 라인

    # ---------------------------------------------------------------
    # TYPOGRAPHY — 제목은 개성, 본문은 가독성
    # ---------------------------------------------------------------
    #   display : 붓글씨. 메인 타이틀 "할매" 에만 쓴다.
    #   title   : 전통 명조. 제목·소제목·카드 제목.
    #   body    : 고딕. 본문·라벨·버튼. 절대 붓글씨를 쓰지 않는다.
    #   latin   : 영문 서브타이틀 (HALMAE, THE COMPASS)
    "font_display": "'Nanum Brush Script', 'Gowun Batang', serif",
    "font_title": "'Gowun Batang', 'Nanum Myeongjo', serif",
    "font_body": "'Noto Sans KR', 'Apple SD Gothic Neo', system-ui, sans-serif",
    "font_latin": "'Cormorant Garamond', 'Gowun Batang', serif",

    # ---------------------------------------------------------------
    # RADIUS / LAYOUT
    # ---------------------------------------------------------------
    "radius_card": "4px",       # 고가구 느낌 — 모서리를 거의 굴리지 않는다
    "radius_pill": "999px",
    "content_width": "480px",   # 모바일 우선
    "cta_width": "340px",       # CTA 버튼 최대 폭 (가운데 정렬용)
}

# 웹폰트는 <style> 안의 @import 가 아니라 <link> 태그로 불러옵니다.
#
#   왜 바꿨나:
#   Streamlit 이 나중에 끼워 넣는 <style> 안에서 @import 를 쓰면
#   글자가 실제로 필요할 때 폰트 파일을 받아오지 못하는 경우가 있습니다.
#   실제로 붓글씨(Nanum Brush Script) 파일이 끝내 다운로드되지 않아
#   첫 화면 "할매"가 대체 서체(명조)로 보이는 문제가 있었습니다.
#   <link> 로 바꾸면 브라우저가 정상적으로 받아옵니다.
#   붓글씨(Nanum Brush Script)는 일부러 이 목록에서 뺐습니다.
#   .streamlit/config.toml 의 [[theme.fontFaces]] 에서 이미 불러오는데,
#   여기서 또 선언하면 같은 이름의 글꼴이 두 벌이 되어 브라우저가
#   어느 쪽을 쓸지 헷갈려 하다가 엉뚱한 글꼴로 그려버립니다.
FONT_URL = (
    "https://fonts.googleapis.com/css2"
    "?family=Cormorant+Garamond:wght@300;400;600"
    "&family=Gowun+Batang:wght@400;700"
    "&family=Noto+Sans+KR:wght@300;400;500;700"
    "&display=swap"
)


def font_links() -> str:
    """웹폰트를 불러오는 <link> 태그. CSS 보다 먼저 넣어야 합니다."""
    return (
        '<link rel="preconnect" href="https://fonts.googleapis.com">'
        '<link rel="preconnect" href="https://fonts.gstatic.com" crossorigin>'
        f'<link rel="stylesheet" href="{FONT_URL}">'
    )


# ===================================================================
#  2. 가독성 검사 도구 (WCAG 명도 대비)
#     '분위기보다 가독성이 먼저'라는 원칙을 숫자로 지킵니다.
# ===================================================================
def _srgb_channel(value: float) -> float:
    value /= 255
    return value / 12.92 if value <= 0.03928 else ((value + 0.055) / 1.055) ** 2.4


def relative_luminance(hex_color: str) -> float:
    """색의 밝기(0=검정, 1=흰색)."""
    raw = hex_color.lstrip("#")
    r, g, b = (int(raw[i:i + 2], 16) for i in (0, 2, 4))
    return (
        0.2126 * _srgb_channel(r)
        + 0.7152 * _srgb_channel(g)
        + 0.0722 * _srgb_channel(b)
    )


def contrast_ratio(foreground: str, background: str) -> float:
    """두 색의 명도 대비 (1 = 똑같음, 21 = 검정과 흰색)."""
    a, b = relative_luminance(foreground), relative_luminance(background)
    lighter, darker = max(a, b), min(a, b)
    return round((lighter + 0.05) / (darker + 0.05), 2)


# 실제로 화면에서 쓰이는 (글씨색, 배경색, 용도, 큰글씨인지) 조합
CONTRAST_CHECKS = [
    # 본문 — 가장 중요
    ("ivory", "bg_base", "본문 · 기본 배경", False),
    ("ivory", "bg_panel", "본문 · 카드 위", False),
    ("ivory", "bg_raised", "본문 · 카드 속 강조면", False),
    ("ivory", "bg_deep", "본문 · 가장 깊은 배경", False),
    ("ivory_mid", "bg_panel", "보조 설명 · 카드 위", False),
    ("ivory_low", "bg_base", "캡션 · 기본 배경", False),
    ("ivory_low", "bg_panel", "캡션 · 카드 위", False),
    # 금 — 제목·라벨
    ("gold_bright", "bg_base", "강조 텍스트 · 기본 배경", False),
    ("gold_bright", "bg_panel", "강조 텍스트 · 카드 위", False),
    ("gold_bright", "bg_raised", "카드 제목 · 강조면", False),
    ("gold", "bg_panel", "금색 라벨 · 카드 위", False),
    ("gold", "bg_base", "금색 선·아이콘 · 기본 배경", True),
    # 왕실 적색
    ("royal_red_soft", "bg_panel", "붉은 강조 글씨 · 카드 위", False),
    ("royal_red_soft", "bg_base", "붉은 강조 글씨 · 기본 배경", False),
    ("text_on_red", "royal_red", "글씨 · 대홍 면 위", False),
    ("gold_bright", "royal_red_deep", "금 글씨 · 자적 면 위", False),
    # 비취·남색
    ("jade_soft", "bg_panel", "비취 태그 · 카드 위", False),
    ("indigo_soft", "bg_panel", "남색 태그 · 카드 위", False),
    # 밝은 면
    ("text_on_paper", "bg_paper", "입력창 글씨 · 한지 배경", False),
    ("text_on_gold", "gold", "버튼 글씨 · 금색 버튼", False),
]


def check_contrast() -> list[dict]:
    """모든 조합을 검사해 통과 여부를 돌려줍니다."""
    results = []
    for fg, bg, label, is_large in CONTRAST_CHECKS:
        ratio = contrast_ratio(TOKENS[fg], TOKENS[bg])
        need = 3.0 if is_large else 4.5
        results.append(
            {
                "용도": label,
                "글씨": f"{fg} {TOKENS[fg]}",
                "배경": f"{bg} {TOKENS[bg]}",
                "대비": ratio,
                "기준": need,
                "통과": ratio >= need,
            }
        )
    return results


# ===================================================================
#  3. CSS 만들기
#     아래 함수들은 각각 스타일 가이드의 한 챕터에 대응합니다.
# ===================================================================
def _css_base(t: dict) -> str:
    """배경 · 레이아웃 · 기본 타이포"""
    return f"""
    /* ===== Background · 자개장 속 ===================================
       이미지 파일 없이 CSS 그러데이션만으로 색과 결을 만듭니다.
       위쪽에 대홍, 아래쪽에 남색 기운을 아주 옅게 깔아
       한 가지 갈색으로만 보이지 않게 합니다. */
    .stApp {{
        background:
            radial-gradient(85% 55% at 50% -8%,
                rgba(168, 29, 51, 0.30) 0%, transparent 62%),
            radial-gradient(70% 45% at 50% 108%,
                rgba(36, 60, 116, 0.26) 0%, transparent 60%),
            linear-gradient(180deg,
                {t['bg_panel']} 0%, {t['bg_base']} 45%, {t['bg_deep']} 100%),
            repeating-linear-gradient(90deg,
                rgba(255,255,255,0.012) 0px,
                rgba(255,255,255,0.012) 1px,
                transparent 1px, transparent 3px);
        background-attachment: fixed;
        color: {t['ivory']};
    }}

    /* 모바일 우선 — 좁은 한 칼럼 */
    .block-container {{
        max-width: {t['content_width']};
        padding: 2.5rem 1.35rem 5rem 1.35rem;
    }}
    header[data-testid="stHeader"] {{ background: transparent; }}

    /* ===== Typography · 본문은 무조건 읽기 쉬운 고딕 =============== */
    html, body, .stApp, p, li, span, div, label, input, textarea, button {{
        font-family: {t['font_body']};
    }}
    /* 본문 기본값.
       :not([class*="halmae-"]) 로 우리가 만든 요소는 빼둡니다.
       이걸 빼지 않으면 `.stApp p`(우선순위 0,1,1)가
       `.halmae-lead`, `.halmae-title-sm` 같은 우리 클래스(0,1,0)를 이겨서
       글자 크기와 색이 통째로 덮어씌워집니다.
       (실제로 두 번째 화면 타이틀이 48px 대신 15px 로 나오던 원인입니다.) */
    .stApp p:not([class*="halmae-"]),
    .stApp li:not([class*="halmae-"]) {{
        color: {t['ivory']};
        font-size: 0.95rem;
        line-height: 1.9;
    }}
    /* Streamlit 기본 마크다운 제목.
       :not(.halmae-title) 로 브랜드 타이틀은 건드리지 않게 합니다.
       (이 선택자가 .halmae-title 보다 우선순위가 높아서, 예전에는
        첫 화면 <h1> 의 붓글씨가 명조로 덮어씌워지는 문제가 있었습니다.) */
    .stApp h1:not([class*="halmae-"]),
    .stApp h2:not([class*="halmae-"]),
    .stApp h3:not([class*="halmae-"]),
    .stApp h4:not([class*="halmae-"]) {{
        font-family: {t['font_title']};
        color: {t['gold_bright']};
        letter-spacing: 0.02em;
    }}
    """


def _css_brand(t: dict) -> str:
    """메인 화면 · 브랜드 표현 (포스터 무드)"""
    return f"""
    /* ===== 메인 타이틀 · 붓글씨 =====================================
       display 서체는 오직 여기에만 씁니다.
       선택자를 .stApp 으로 한 단계 감싸 우선순위를 높였습니다. */
    .halmae-poster {{
        position: relative;
        text-align: center;
        padding: 1.5rem 0 0.75rem 0;
    }}
    /* 타이틀 뒤에 은은한 대홍 후광 — 포스터의 조명 같은 역할 */
    .halmae-poster::before {{
        content: "";
        position: absolute;
        left: 50%; top: 46%;
        width: 260px; height: 180px;
        transform: translate(-50%, -50%);
        background: radial-gradient(closest-side,
            rgba(168, 29, 51, 0.42) 0%,
            rgba(168, 29, 51, 0.14) 45%,
            transparent 100%);
        pointer-events: none;
        z-index: 0;
    }}
    .halmae-poster > * {{ position: relative; z-index: 1; }}

    /* 워드마크(SVG) — 글자가 아니라 그림이라 폰트 로딩과 무관하게 늘 같습니다.
       currentColor 를 쓰므로 색은 아래 color 한 줄로 바뀝니다. */
    .halmae-wordmark {{
        display: block;
        width: 74%;
        max-width: 300px;
        height: auto;
        margin: 0 auto;
        color: {t['gold_bright']};
        /* 획이 배경에 묻히지 않도록: 금빛 번짐 + 붉은 잔광 */
        filter:
            drop-shadow(0 0 10px rgba(243, 216, 143, 0.55))
            drop-shadow(0 0 34px rgba(210, 166, 46, 0.40))
            drop-shadow(0 0 62px rgba(168, 29, 51, 0.55));
    }}
    /* 입력·결과 화면용 — 첫 화면보다 반드시 작고 약하게 */
    .halmae-wordmark-sm {{
        width: 40%;
        max-width: 150px;
        filter: drop-shadow(0 0 12px rgba(210, 166, 46, 0.35));
    }}

    /* 타이틀 위아래를 금선으로 잡아주는 포스터 프레임 */
    .halmae-poster-frame {{
        display: block;
        height: 1px;
        width: 150px;
        margin: 0 auto;
        background: linear-gradient(90deg,
            transparent, {t['gold']}, transparent);
    }}
    .halmae-poster-frame.top {{ margin-bottom: 0.9rem; }}
    .halmae-poster-frame.bottom {{ margin-top: 0.9rem; }}

    /* 영문 서브타이틀 — 포스터 하단 크레딧처럼 */
    .halmae-latin {{
        font-family: {t['font_latin']};
        font-size: 1rem;
        font-weight: 400;
        letter-spacing: 0.7em;
        text-indent: 0.7em;      /* 자간 때문에 오른쪽으로 밀리는 것 보정 */
        color: {t['ivory_mid']};
        margin: 0.9rem 0 0 0;
    }}
    /* 인장(도장) — 왕실 문서의 붉은 낙관에서 빌린 작은 표식 */
    .halmae-seal {{
        display: inline-block;
        margin-top: 0.9rem;
        font-family: {t['font_title']};
        font-size: 0.7rem;
        letter-spacing: 0.24em;
        text-indent: 0.24em;
        color: {t['text_on_red']};
        background: linear-gradient(180deg,
            {t['royal_red']} 0%, {t['royal_red_deep']} 100%);
        border: 1px solid {t['gold_dim']};
        border-radius: 2px;
        padding: 0.28rem 0.75rem;
    }}

    /* 작은 타이틀 (입력·결과 화면 상단) — 첫 화면보다 반드시 약하게 */
    .halmae-title-sm {{
        font-family: {t['font_display']};
        text-align: center;
        font-size: 3rem;
        line-height: 1;
        color: {t['gold_bright']};
        letter-spacing: 0.05em;
        margin: 0;
        text-shadow: 0 0 14px rgba(210, 166, 46, 0.30),
                     0 2px 0 rgba(0, 0, 0, 0.6);
    }}

    /* ===== Accent motif · 금박 라인 ================================ */
    .halmae-rule {{
        display: flex;
        align-items: center;
        justify-content: center;
        gap: 0.55rem;
        margin: 1.5rem 0 1.75rem 0;
    }}
    .halmae-rule::before, .halmae-rule::after {{
        content: "";
        height: 1px;
        width: 64px;
        background: linear-gradient(90deg,
            transparent, {t['line_gold']}, transparent);
    }}
    .halmae-rule span {{
        color: {t['royal_red_soft']};
        font-size: 0.6rem;
        line-height: 1;
    }}
    .halmae-divider {{ display: none; }}

    /* ===== 메인 카피 ============================================== */
    .halmae-lead {{
        font-family: {t['font_title']};
        text-align: center;
        font-size: 1.45rem;
        font-weight: 700;
        line-height: 1.95;
        color: {t['ivory']};
        margin: 0 0 1.5rem 0;
        white-space: pre-line;
    }}
    .halmae-desc {{
        text-align: center;
        font-size: 0.95rem;
        line-height: 2;
        color: {t['ivory_mid']};
        margin: 0 0 2.5rem 0;
        white-space: pre-line;
    }}
    .halmae-guide {{
        text-align: center;
        font-size: 0.92rem;
        line-height: 1.9;
        color: {t['ivory_mid']};
        margin: 0 0 2rem 0;
        white-space: pre-line;
    }}
    .halmae-footnote {{
        text-align: center;
        font-size: 0.75rem;
        letter-spacing: 0.12em;
        color: {t['ivory_low']};
        margin-top: 2.5rem;
    }}
    .halmae-moon {{ display: none; }}
    """


def _css_controls(t: dict) -> str:
    """Button · Input styles"""
    return f"""
    /* ===== Button · primary (금박 명패) ============================
       [가운데 정렬]
       Streamlit 은 버튼을 감싸는 칸을 왼쪽 정렬로 두기 때문에,
       감싸는 칸을 flex 로 만들어 가운데로 모으고
       버튼 안의 글자도 따로 가운데로 맞춰야 정확히 중앙에 옵니다. */
    .stButton {{
        display: flex !important;
        justify-content: center !important;
        width: 100%;
    }}
    .stButton > button {{
        width: 100%;
        max-width: {t['cta_width']};
        margin: 0 auto;
        display: flex;
        align-items: center;
        justify-content: center;
        text-align: center;
        font-family: {t['font_title']};
        font-size: 1.05rem;
        font-weight: 700;
        letter-spacing: 0.06em;
        color: {t['text_on_gold']};
        background: linear-gradient(180deg, #F0D07A 0%, {t['gold']} 52%, #A07C1C 100%);
        border: 1px solid {t['gold_bright']};
        border-radius: {t['radius_card']};
        padding: 0.9rem 1rem;
        box-shadow:
            0 0 0 1px rgba(94, 15, 30, 0.55),
            0 3px 0 rgba(0,0,0,0.5),
            inset 0 1px 0 rgba(255,255,255,0.4);
        transition: filter 0.15s ease;
    }}
    /* 버튼 안의 글자(Streamlit 이 <p> 로 감쌉니다)도 가운데로 */
    .stButton > button p, .stButton > button div {{
        width: 100%;
        text-align: center !important;
        margin: 0 !important;
        color: {t['text_on_gold']} !important;
    }}
    .stButton > button:hover {{
        filter: brightness(1.08);
        border-color: {t['gold_bright']};
    }}
    .stButton > button:active {{
        filter: brightness(0.94);
        box-shadow: inset 0 2px 5px rgba(0,0,0,0.5);
    }}
    /* 잠긴 버튼 — 눌리지 않는다는 것이 한눈에 보여야 합니다.
       (동의 체크 전의 '할매에게 물어보기' 가 여기에 해당합니다) */
    .stButton > button:disabled,
    .stButton > button:disabled:hover {{
        background: {t['bg_raised']};
        border: 1px dashed {t['line']};
        box-shadow: none;
        filter: none;
        cursor: not-allowed;
    }}
    .stButton > button:disabled p,
    .stButton > button:disabled div {{
        color: {t['ivory_low']} !important;
    }}

    /* ===== Button · secondary (자적 테두리) ======================== */
    .stButton > button[kind="secondary"] {{
        background: transparent;
        border: 1px solid {t['line']};
        box-shadow: none;
        font-family: {t['font_body']};
        font-size: 0.88rem;
        font-weight: 400;
        letter-spacing: 0;
        padding: 0.6rem;
    }}
    .stButton > button[kind="secondary"] p,
    .stButton > button[kind="secondary"] div {{
        color: {t['ivory_mid']} !important;
    }}
    .stButton > button[kind="secondary"]:hover {{
        background: rgba(168, 29, 51, 0.14);
        border-color: {t['royal_red_line']};
        filter: none;
    }}
    .stButton > button[kind="secondary"]:hover p {{
        color: {t['royal_red_soft']} !important;
    }}

    /* ===== Input · 한지 패널 =======================================
       어두운 화면에서 '적는 곳'만 밝게 → 어디에 쓰는지 한눈에 보입니다. */
    div[data-testid="stWidgetLabel"] p {{
        font-family: {t['font_title']} !important;
        font-size: 0.95rem !important;
        font-weight: 700;
        color: {t['gold_bright']} !important;
        letter-spacing: 0.02em;
    }}
    div[data-baseweb="input"], div[data-baseweb="base-input"],
    div[data-baseweb="select"] > div, .stTextArea textarea {{
        background-color: {t['bg_paper']} !important;
        border: 1px solid {t['line_gold']} !important;
        border-radius: {t['radius_card']} !important;
    }}
    div[data-baseweb="input"] input, .stTextArea textarea,
    div[data-baseweb="select"] div {{
        color: {t['text_on_paper']} !important;
        font-size: 1rem !important;
        -webkit-text-fill-color: {t['text_on_paper']};
    }}
    div[data-baseweb="input"] input::placeholder,
    .stTextArea textarea::placeholder {{
        color: #8B7A66 !important;
        opacity: 1;
    }}
    .stTextInput, .stDateInput, .stTimeInput, .stSelectbox, .stTextArea {{
        margin-bottom: 0.5rem;
    }}

    div[role="radiogroup"] label p, .stCheckbox label p {{
        color: {t['ivory']} !important;
        font-size: 0.92rem !important;
    }}
    div[role="radiogroup"] label {{ margin-right: 1rem; }}

    [data-testid="stCaptionContainer"] p {{
        color: {t['ivory_low']} !important;
        font-size: 0.78rem !important;
        line-height: 1.75;
    }}
    div[data-testid="stAlert"] {{
        background: {t['bg_raised']};
        border: 1px solid {t['line_gold']};
        border-left: 3px solid {t['royal_red_line']};
        border-radius: {t['radius_card']};
    }}
    div[data-testid="stAlert"] p {{ color: {t['ivory']} !important; }}

    details, div[data-testid="stExpander"] {{
        background: {t['bg_panel']} !important;
        border: 1px solid {t['line']} !important;
        border-radius: {t['radius_card']} !important;
    }}
    div[data-testid="stExpander"] summary p {{
        color: {t['gold_bright']} !important;
        font-family: {t['font_title']};
    }}
    """


def _css_cards(t: dict) -> str:
    """Card styles — 자개장 문짝에서 영감을 받은 패널"""
    return f"""
    /* ===== Card · 기본 패널 ========================================
       왼쪽 세로선을 금 → 대홍 그러데이션으로 두어 색기를 넣습니다. */
    .halmae-card {{
        position: relative;
        background: linear-gradient(180deg, {t['bg_panel']} 0%, {t['bg_raised']} 100%);
        border: 1px solid {t['line']};
        border-radius: {t['radius_card']};
        padding: 1.15rem 1.2rem 1.15rem 1.3rem;
        margin-bottom: 0.9rem;
        overflow: hidden;
    }}
    .halmae-card::before {{
        content: "";
        position: absolute;
        left: 0; top: 0; bottom: 0;
        width: 3px;
        background: linear-gradient(180deg,
            {t['gold']} 0%, {t['royal_red']} 60%, {t['royal_red_deep']} 100%);
    }}
    .halmae-card-title {{
        font-family: {t['font_title']};
        font-size: 1.05rem;
        font-weight: 700;
        color: {t['gold_bright']};
        line-height: 1.6;
        margin: 0 0 0.85rem 0;
    }}

    /* 항목 이름 (근거 / 행동 / 시기 …) — 금색 작은 라벨 */
    .halmae-label {{
        font-family: {t['font_body']};
        font-size: 0.72rem;
        font-weight: 700;
        letter-spacing: 0.14em;
        color: {t['gold']};
        margin: 1rem 0 0.3rem 0;
    }}
    .halmae-body {{
        font-size: 0.95rem;
        line-height: 1.95;
        color: {t['ivory']};
        margin: 0;
    }}
    .halmae-steps {{
        font-size: 0.95rem;
        line-height: 1.95;
        color: {t['ivory']};
        margin: 0;
        padding-left: 1.15rem;
    }}
    .halmae-steps li::marker {{ color: {t['royal_red_soft']}; }}

    /* ===== 근거 카드 · 사주/점성술 태그 ============================
       "할매가 이렇게 보는 이유"의 핵심.
       붉은 화면에서 눈에 띄도록 차가운 비취색을 씁니다. */
    .halmae-tag {{
        display: inline-block;
        vertical-align: middle;
        background: rgba(31, 122, 110, 0.18);
        border: 1px solid {t['jade_line']};
        color: {t['jade_soft']};
        font-size: 0.7rem;
        letter-spacing: 0.06em;
        border-radius: {t['radius_pill']};
        padding: 0.15rem 0.6rem;
        margin-right: 0.45rem;
    }}
    .halmae-fact {{
        font-family: {t['font_title']};
        font-size: 0.95rem;
        font-weight: 700;
        color: {t['gold_bright']};
    }}

    /* ===== 명식 칸 · 파이썬이 계산한 확정값 =========================
       할매의 글이 아니라 계산 결과를 그대로 보여주는 자리입니다. */
    .halmae-myeongsik-row {{
        display: flex;
        flex-wrap: wrap;
        gap: 0.5rem;
        margin: 0.2rem 0 0.6rem 0;
    }}
    .halmae-myeongsik-cell {{
        flex: 1 1 4.5rem;
        min-width: 4.5rem;
        display: flex;
        flex-direction: column;
        align-items: center;
        gap: 0.15rem;
        background: {t['bg_deep']};
        border: 1px solid {t['line_gold']};
        border-radius: {t['radius_card']};
        padding: 0.55rem 0.35rem;
    }}
    .halmae-myeongsik-cell .halmae-label {{
        margin: 0;
    }}
    .halmae-myeongsik-value {{
        font-family: {t['font_title']};
        font-size: 1.05rem;
        font-weight: 700;
        color: {t['gold_bright']};
        line-height: 1.4;
        white-space: nowrap;
    }}

    /* ===== 대사 상자 · 그대로 읽어도 되는 문장 ===================== */
    .halmae-script {{
        background: {t['bg_deep']};
        border: 1px solid {t['line_gold']};
        border-left: 3px solid {t['gold']};
        border-radius: {t['radius_card']};
        padding: 0.8rem 0.95rem;
        font-family: {t['font_title']};
        font-size: 0.95rem;
        line-height: 1.9;
        color: {t['ivory']};
    }}

    /* ===== 할매의 한마디 · 인용 패널 =============================== */
    .halmae-quote {{
        font-family: {t['font_title']};
        font-size: 1.05rem;
        line-height: 2;
        color: {t['gold_bright']};
        background:
            linear-gradient(180deg,
                rgba(168, 29, 51, 0.16) 0%, rgba(94, 15, 30, 0.10) 100%);
        border-top: 1px solid {t['line_gold']};
        border-bottom: 1px solid {t['line_gold']};
        padding: 1.1rem 1.15rem;
        margin: 0.6rem 0;
        text-align: center;
    }}
    """


def _css_result(t: dict) -> str:
    """Step 1~3 결과 화면 · 읽기 좋은 덩어리 나누기"""
    return f"""
    .halmae-step-badge {{
        text-align: center;
        font-family: {t['font_latin']};
        font-size: 0.8rem;
        letter-spacing: 0.35em;
        text-indent: 0.35em;
        color: {t['royal_red_soft']};
        margin: 2rem 0 0.4rem 0;
    }}
    .halmae-step-title {{
        font-family: {t['font_title']};
        text-align: center;
        font-size: 1.3rem;
        font-weight: 700;
        line-height: 1.6;
        color: {t['ivory']};
        margin: 0 0 1.4rem 0;
    }}
    /* 1단계 한 줄 총평 — 포스터 카피처럼 */
    .halmae-headline {{
        font-family: {t['font_title']};
        font-size: 1.25rem;
        font-weight: 700;
        line-height: 1.85;
        color: {t['gold_bright']};
        text-align: center;
        padding: 1.2rem 0.8rem;
        background: radial-gradient(80% 100% at 50% 50%,
            rgba(168, 29, 51, 0.16) 0%, transparent 75%);
        border-top: 1px solid {t['line_gold']};
        border-bottom: 1px solid {t['line_gold']};
        margin: 0.4rem 0 1.75rem 0;
    }}
    /* 섹션 소제목 — 앞에 작은 대홍 마름모 */
    .halmae-section {{
        font-family: {t['font_title']};
        font-size: 1.08rem;
        font-weight: 700;
        color: {t['gold_bright']};
        letter-spacing: 0.02em;
        margin: 2.1rem 0 0.85rem 0;
    }}
    .halmae-section::before {{
        content: "◆ ";
        color: {t['royal_red_soft']};
        font-size: 0.7rem;
        vertical-align: middle;
    }}
    .halmae-sep {{
        height: 1px;
        background: linear-gradient(90deg,
            transparent, {t['line_gold']} 35%,
            {t['royal_red_line']} 50%, {t['line_gold']} 65%, transparent);
        margin: 2rem 0;
    }}
    """


def _css_yearcard(t: dict) -> str:
    """올해의 카드 — 자개장 비밀 서랍에서 꺼낸 부적"""
    return f"""
    /* 이중 테두리(바깥 금선 + 안쪽 얇은 선)로 부적 느낌.
       바탕에 자적(紫赤)을 깔아 왕실 문서 같은 무게를 줍니다. */
    .halmae-yearcard {{
        position: relative;
        background:
            radial-gradient(95% 70% at 50% 0%,
                rgba(210, 166, 46, 0.16) 0%, transparent 62%),
            linear-gradient(180deg,
                {t['royal_red_deep']} 0%, {t['bg_panel']} 55%, {t['bg_deep']} 100%);
        border: 1px solid {t['gold_dim']};
        border-radius: {t['radius_card']};
        padding: 2.2rem 1.3rem 1.9rem 1.3rem;
        margin: 1rem 0;
        text-align: center;
    }}
    .halmae-yearcard::before {{
        content: "";
        position: absolute;
        inset: 7px;
        border: 1px solid rgba(243, 216, 143, 0.32);
        border-radius: 2px;
        pointer-events: none;
    }}
    .halmae-yearcard-year {{
        font-family: {t['font_latin']};
        font-size: 0.78rem;
        letter-spacing: 0.3em;
        text-indent: 0.3em;
        color: {t['gold_bright']};
        margin: 0 0 1rem 0;
    }}
    .halmae-yearcard-title {{
        font-family: {t['font_latin']};
        font-size: 2.15rem;
        font-weight: 600;
        letter-spacing: 0.1em;
        line-height: 1.25;
        color: {t['gold_bright']};
        margin: 0 0 0.85rem 0;
        text-shadow: 0 0 20px rgba(243, 216, 143, 0.35);
    }}
    .halmae-yearcard-keyword {{
        display: inline-block;
        font-family: {t['font_title']};
        font-size: 0.85rem;
        letter-spacing: 0.14em;
        color: {t['text_on_gold']};
        background: linear-gradient(180deg, #F0D07A, {t['gold']});
        border: 1px solid {t['gold_bright']};
        border-radius: {t['radius_pill']};
        padding: 0.25rem 0.95rem;
        margin: 0 0 1.2rem 0;
    }}
    .halmae-yearcard-message {{
        font-family: {t['font_title']};
        font-size: 1.12rem;
        font-weight: 700;
        line-height: 2;
        color: {t['ivory']};
        margin: 0;
    }}
    .halmae-card-foot {{
        font-family: {t['font_latin']};
        font-size: 0.75rem;
        letter-spacing: 0.2em;
        color: {t['ivory_low']};
        margin: 1.3rem 0 0 0;
    }}
    """


def _css_feedback_premium(t: dict) -> str:
    """피드백 · Premium"""
    return f"""
    /* ===== 피드백 ================================================= */
    .halmae-feedback-title {{
        font-family: {t['font_title']};
        text-align: center;
        font-size: 1.12rem;
        font-weight: 700;
        color: {t['gold_bright']};
        margin: 1.4rem 0 0.35rem 0;
    }}
    .halmae-feedback-hint {{
        text-align: center;
        font-size: 0.78rem;
        letter-spacing: 0.05em;
        color: {t['ivory_low']};
        margin: 0 0 0.7rem 0;
    }}
    div[data-testid="stFeedback"] {{
        display: flex; justify-content: center; gap: 0.8rem;
    }}
    div[data-testid="stFeedback"] button {{
        width: 62px !important; height: 54px !important;
        border-radius: {t['radius_card']} !important;
        border: 1px solid {t['line_gold']} !important;
        background: {t['bg_panel']} !important;
    }}
    div[data-testid="stFeedback"] button span {{ font-size: 1.5rem !important; }}
    div[data-testid="stFeedback"] button:hover {{
        background: {t['bg_raised']} !important;
        border-color: {t['royal_red_line']} !important;
    }}

    /* ===== Premium · 비밀 서랍 ====================================
       왕실 문서함처럼 자적 바탕 + 금 이중선. */
    .halmae-premium {{
        position: relative;
        background:
            radial-gradient(80% 60% at 50% 0%,
                rgba(210, 166, 46, 0.18) 0%, transparent 62%),
            linear-gradient(180deg,
                {t['royal_red_deep']} 0%, {t['bg_panel']} 60%, {t['bg_deep']} 100%);
        border: 1px solid {t['gold_dim']};
        border-radius: {t['radius_card']};
        padding: 1.9rem 1.25rem;
        margin: 1.25rem 0 1rem 0;
        text-align: center;
    }}
    .halmae-premium::before {{
        content: "";
        position: absolute; inset: 7px;
        border: 1px solid rgba(243, 216, 143, 0.26);
        border-radius: 2px; pointer-events: none;
    }}
    .halmae-premium-title {{
        font-family: {t['font_title']};
        font-size: 1.3rem; font-weight: 700;
        color: {t['gold_bright']};
        margin: 0 0 0.9rem 0;
    }}
    .halmae-premium-desc {{
        font-size: 0.92rem; line-height: 2;
        color: {t['ivory_mid']};
        margin: 0 0 1.2rem 0;
    }}
    .halmae-premium-price {{
        font-family: {t['font_title']};
        font-size: 1.5rem; font-weight: 700;
        color: {t['ivory']};
        margin: 0;
    }}
    .halmae-beta-tag {{
        display: inline-block; vertical-align: middle;
        margin-left: 0.5rem;
        background: transparent;
        border: 1px solid {t['gold_dim']};
        color: {t['gold']};
        font-size: 0.66rem; font-weight: 400;
        letter-spacing: 0.08em;
        border-radius: {t['radius_pill']};
        padding: 0.2rem 0.55rem;
    }}
    .halmae-fakedoor {{
        background: {t['bg_panel']};
        border: 1px solid {t['line']};
        border-top: 2px solid {t['royal_red_line']};
        border-radius: {t['radius_card']};
        padding: 1.3rem 1.2rem;
        margin: 0.5rem 0 1rem 0;
        text-align: center;
    }}
    .halmae-fakedoor-title {{
        font-family: {t['font_title']};
        font-size: 1.12rem; font-weight: 700;
        color: {t['gold_bright']};
        margin: 0 0 0.8rem 0;
    }}
    .halmae-fakedoor-body {{
        font-size: 0.93rem; line-height: 2;
        color: {t['ivory']};
        margin: 0;
    }}
    .halmae-fakedoor-body b {{ color: {t['royal_red_soft']}; }}
    """


def _css_notice(t: dict) -> str:
    """안내 쪽지 · 서비스 성격 고지

    낡은 한지 쪽지처럼 보이되, 본문 가독성이 먼저입니다.
    (어두운 바탕에 상아빛 글씨 — 대비 15:1)
    """
    return f"""
    /* ===== 입력 화면 · 데이터 사용 안내 쪽지 ======================= */
    .halmae-notice {{
        position: relative;
        background:
            repeating-linear-gradient(102deg,
                rgba(248, 239, 220, 0.022) 0px,
                rgba(248, 239, 220, 0.022) 1px,
                transparent 1px, transparent 4px),
            linear-gradient(180deg, {t['bg_panel']} 0%, {t['bg_deep']} 100%);
        border: 1px solid {t['line']};
        border-top: 2px solid {t['line_gold']};
        border-radius: {t['radius_card']};
        padding: 1rem 1.1rem 0.9rem 1.1rem;
        margin: 0.5rem 0 0.75rem 0;
    }}
    .halmae-notice-title {{
        font-family: {t['font_title']};
        font-size: 0.98rem;
        font-weight: 700;
        color: {t['gold_bright']};
        margin: 0 0 0.6rem 0;
    }}
    .halmae-notice-title::before {{
        content: "◆ ";
        color: {t['royal_red_soft']};
        font-size: 0.62rem;
        vertical-align: middle;
    }}
    .halmae-notice ul {{
        margin: 0;
        padding-left: 1.05rem;
        list-style: none;
    }}
    .halmae-notice li {{
        position: relative;
        font-size: 0.82rem !important;
        line-height: 1.75 !important;
        color: {t['ivory']} !important;
        margin-bottom: 0.45rem;
    }}
    .halmae-notice li:last-child {{ margin-bottom: 0; }}
    .halmae-notice li::before {{
        content: "·";
        position: absolute;
        left: -0.75rem;
        color: {t['gold']};
        font-weight: 700;
    }}
    /* 안내 안에서 특히 짚어줄 부분 */
    .halmae-notice b {{ color: {t['gold_bright']}; font-weight: 700; }}

    /* ===== 결과 화면 맨 아래 · 서비스 성격 고지 ==================== */
    .halmae-disclaimer {{
        text-align: center;
        font-size: 0.72rem;
        line-height: 1.85;
        color: {t['ivory_low']};
        border-top: 1px solid {t['line']};
        padding-top: 1rem;
        margin-top: 2.5rem;
        white-space: pre-line;
    }}
    """


def _css_dev(t: dict) -> str:
    """개발용 표시 (Mock 배지 등) — 무드와 섞이지 않게 일부러 다른 색"""
    return f"""
    .halmae-modelbadge {{
        text-align: center;
        font-size: 0.7rem;
        letter-spacing: 0.05em;
        color: {t['ivory_low']};
        background: rgba(255,255,255,0.03);
        border: 1px dashed {t['line']};
        border-radius: {t['radius_pill']};
        padding: 0.3rem 0.7rem;
        margin: 0 auto 1.25rem auto;
        max-width: 360px;
    }}
    .halmae-modelbadge b {{ color: {t['ivory_mid']}; }}
    .halmae-mockbadge {{
        border-color: {t['jade_line']};
        color: {t['jade_soft']};
        max-width: 420px;
    }}
    .halmae-mockbadge b {{ color: {t['jade_soft']}; }}
    .halmae-mockfooter {{
        position: fixed; right: 10px; bottom: 8px; z-index: 1000;
        font-size: 0.66rem; letter-spacing: 0.08em;
        color: {t['jade_soft']};
        background: rgba(31, 122, 110, 0.20);
        border: 1px dashed {t['jade_line']};
        border-radius: {t['radius_pill']};
        padding: 0.2rem 0.6rem;
        pointer-events: none;
    }}
    div[data-testid="stMetricValue"] {{ color: {t['gold_bright']} !important; }}
    div[data-testid="stMetricLabel"] p {{ color: {t['ivory_mid']} !important; }}
    .stCode, pre, code {{
        background: {t['bg_deep']} !important;
        color: {t['ivory']} !important;
        border: 1px solid {t['line']};
        border-radius: {t['radius_card']};
    }}
    """


def build_css() -> str:
    """모든 조각을 합쳐 <style> 한 덩어리로."""
    t = TOKENS
    blocks = [
        _css_base(t),
        _css_brand(t),
        _css_controls(t),
        _css_cards(t),
        _css_result(t),
        _css_yearcard(t),
        _css_feedback_premium(t),
        _css_notice(t),
        _css_dev(t),
    ]
    # 웹폰트 <link> + 스타일을 한 덩어리로 돌려줍니다.
    return font_links() + "<style>\n" + "\n".join(blocks) + "\n</style>"


# ===================================================================
#  4. 화면 조각 (여러 곳에서 되풀이되는 마크업)
# ===================================================================
def rule() -> str:
    """금박 구분선 — 가운데 대홍 마름모."""
    return '<div class="halmae-rule"><span>◆</span></div>'


def separator() -> str:
    """단계 사이의 얇은 금선."""
    return '<div class="halmae-sep"></div>'


# ===================================================================
#  4-1. 워드마크 "할매" — 붓글씨를 그림(벡터)으로 굳혀둔 것
#
#  왜 글자가 아니라 그림인가:
#    웹폰트는 '내려받는 데 시간이 걸리는' 자원이라, 첫 화면처럼 빨리 그려지는
#    자리에서는 폰트가 도착하기 전에 대체 글꼴로 먼저 그려질 수 있습니다.
#    브라우저가 한 번 그렇게 정하면 폰트가 늦게 도착해도 다시 그리지 않습니다.
#    (실제로 첫 화면 "할매"만 계속 다른 글꼴로 나오던 원인이 이것이었습니다.)
#
#    로고는 어떤 환경에서도 똑같이 보여야 하므로,
#    붓글씨 글자의 외곽선을 그대로 떠서 SVG 그림으로 박아두었습니다.
#    이제 폰트를 못 받아와도, 인터넷이 느려도 늘 같은 모양으로 나옵니다.
#
#  출처: Nanum Brush Script (SIL Open Font License 1.1) 의 '할','매' 글리프 외곽선.
#  글자를 바꾸려면 fontTools 로 다시 떠야 합니다.
WORDMARK_VIEWBOX = "-1 -632 1412 984"
WORDMARK_PATH = (
    "M589 -112Q584 -90 566.0 -63.5Q548 -37 527 -13Q542 -15 558.0 -15.0Q574 -15 587 -11Q597 -3 607.0 0.5Q617 4 625 10Q629 13 634.5 14.0Q640 15 642 19Q647 27 644.0 35.5Q641 44 636 54Q615 102 593.5 148.0Q572 194 558 239Q555 247 561.0 247.0Q567 247 586 239Q660 205 708.5 171.5Q757 138 797 108Q792 116 790.0 119.5Q788 123 783 131Q774 145 772.0 156.0Q770 167 757 180Q722 217 670.0 254.5Q618 292 548 330Q535 334 529.5 327.5Q524 321 516 317Q508 313 505.5 304.0Q503 295 501 284Q500 279 496.5 274.5Q493 270 493 264Q501 210 525.5 162.5Q550 115 574 75L583 60Q568 60 550.5 62.5Q533 65 515.0 68.5Q497 72 481.0 76.5Q465 81 453 85Q447 83 446.0 72.5Q445 62 445 52Q445 43 448.0 35.5Q451 28 453 20Q455 13 456.0 7.0Q457 1 460 -2Q518 -45 538 -102Q539 -107 526.0 -110.5Q513 -114 492.0 -116.0Q471 -118 445.0 -119.0Q419 -120 394 -120Q391 -120 390.0 -122.5Q389 -125 387 -127Q384 -128 385 -136Q386 -141 386.5 -145.0Q387 -149 389 -151Q404 -164 425.5 -172.0Q447 -180 470.5 -183.5Q494 -187 516.0 -186.0Q538 -185 553 -180Q560 -178 567.0 -175.5Q574 -173 578 -170Q585 -165 585.0 -156.0Q585 -147 587 -140Q589 -132 590.0 -126.0Q591 -120 589 -112ZM320 -84Q319 -70 319.0 -57.0Q319 -44 321 -30Q323 -15 323.0 -7.0Q323 1 319 16Q292 104 234 141Q227 146 215.0 150.5Q203 155 195 156Q184 153 181.5 139.5Q179 126 174 116Q170 108 168.5 105.0Q167 102 166 91Q164 54 176.0 4.0Q188 -46 204.5 -97.5Q221 -149 239.0 -195.5Q257 -242 267 -272Q267 -274 268.5 -275.5Q270 -277 269 -278Q267 -280 263.5 -280.5Q260 -281 257 -281Q233 -279 206.0 -275.0Q179 -271 152.5 -265.0Q126 -259 101.0 -251.5Q76 -244 55 -237Q51 -235 44.5 -239.5Q38 -244 33 -243L26 -249Q22 -253 21.0 -257.0Q20 -261 20 -264Q20 -266 19.0 -270.5Q18 -275 20 -278Q33 -293 65.0 -306.0Q97 -319 135.0 -326.5Q173 -334 210.5 -335.0Q248 -336 272 -326Q277 -324 279.5 -320.5Q282 -317 285 -315Q287 -313 288.5 -311.0Q290 -309 292 -306Q296 -301 299.0 -300.0Q302 -299 304 -294Q306 -288 305.5 -278.0Q305 -268 303 -261Q296 -241 288.0 -218.5Q280 -196 271 -171Q276 -170 280.0 -169.0Q284 -168 287 -167Q301 -161 308 -151Q317 -138 319.0 -120.5Q321 -103 320 -84ZM580 -246Q577 -242 573.5 -247.5Q570 -253 561 -270Q556 -281 546.5 -294.5Q537 -308 533 -330Q528 -360 526.5 -395.5Q525 -431 527.0 -465.5Q529 -500 535.5 -531.0Q542 -562 553 -584L567 -610Q574 -615 579.5 -610.0Q585 -605 595 -604Q599 -600 598.5 -590.5Q598 -581 599 -574Q601 -564 602.5 -557.0Q604 -550 602 -542Q594 -504 588.5 -466.5Q583 -429 580 -394Q597 -399 612.0 -404.0Q627 -409 643.0 -415.0Q659 -421 677.0 -427.0Q695 -433 717 -441Q722 -443 722.5 -441.0Q723 -439 724 -437Q725 -435 720.0 -432.5Q715 -430 713 -424Q711 -414 705.0 -408.0Q699 -402 693 -399Q664 -385 635.5 -373.5Q607 -362 578 -352Q577 -324 577.5 -298.0Q578 -272 580 -246ZM262 -394Q246 -416 224.5 -441.5Q203 -467 180.5 -492.0Q158 -517 135.5 -538.5Q113 -560 95 -574Q95 -577 92.5 -578.0Q90 -579 92 -582Q96 -590 104.5 -592.0Q113 -594 118 -595Q124 -597 135.0 -595.0Q146 -593 154 -594Q157 -593 160.5 -594.5Q164 -596 168 -594Q185 -583 202.5 -565.5Q220 -548 236.0 -528.0Q252 -508 264.0 -486.0Q276 -464 282 -445Q285 -437 282 -429Q278 -415 277.0 -402.0Q276 -389 276 -377ZM205 73Q214 67 226.0 48.5Q238 30 249.0 5.0Q260 -20 266.5 -47.0Q273 -74 270 -95Q267 -118 258 -136Q240 -82 224.5 -28.5Q209 25 205 73Z M1360 -406Q1366 -409 1371.5 -415.0Q1377 -421 1381 -419Q1388 -414 1389.5 -402.0Q1391 -390 1391 -376V-360Q1386 -273 1375.0 -190.0Q1364 -107 1343 -28Q1338 -17 1329.5 -1.0Q1321 15 1313 22Q1309 25 1307.5 20.5Q1306 16 1304 15Q1296 10 1296.0 4.5Q1296 -1 1294 -7Q1292 -17 1288.5 -28.5Q1285 -40 1287 -51Q1293 -99 1298.5 -147.0Q1304 -195 1309 -243Q1302 -235 1292.5 -228.5Q1283 -222 1272 -217Q1243 -203 1210.5 -188.5Q1178 -174 1155 -166L1152 -108Q1151 -98 1150.0 -91.5Q1149 -85 1148 -77Q1147 -67 1144.0 -57.0Q1141 -47 1139 -42Q1134 -35 1129.5 -25.5Q1125 -16 1117 -11Q1114 -9 1111.5 -14.5Q1109 -20 1107 -19Q1101 -40 1097.5 -77.5Q1094 -115 1092.5 -156.5Q1091 -198 1091.5 -237.5Q1092 -277 1094 -303Q1096 -311 1102.0 -315.5Q1108 -320 1116 -327Q1123 -333 1128.5 -339.5Q1134 -346 1137 -346Q1139 -346 1145 -344Q1146 -344 1149.0 -345.0Q1152 -346 1155.0 -347.5Q1158 -349 1161.0 -349.5Q1164 -350 1164 -349L1156 -197Q1165 -207 1172.5 -211.0Q1180 -215 1188 -218Q1233 -234 1259.5 -247.5Q1286 -261 1312 -275Q1314 -293 1315.5 -311.5Q1317 -330 1319 -349Q1319 -354 1323.0 -358.0Q1327 -362 1332 -369Q1340 -381 1344.5 -389.5Q1349 -398 1360 -406ZM785 -37Q771 -63 767.5 -98.0Q764 -133 768.0 -170.5Q772 -208 783.0 -246.5Q794 -285 810 -318L817 -315Q820 -313 822.0 -310.0Q824 -307 826 -305Q829 -303 831.0 -302.5Q833 -302 834 -297V-268Q834 -260 834.0 -252.5Q834 -245 833 -237Q851 -248 878.5 -262.5Q906 -277 932 -283Q950 -288 964 -283Q970 -281 970.0 -270.0Q970 -259 971 -254Q972 -249 976.5 -246.0Q981 -243 979 -236Q964 -187 938.5 -132.5Q913 -78 892 -33Q920 -47 954.0 -65.5Q988 -84 1017 -95Q1025 -98 1033.0 -99.0Q1041 -100 1048 -102Q1057 -104 1063.5 -107.5Q1070 -111 1074 -109Q1055 -95 1032.0 -79.0Q1009 -63 984.0 -46.5Q959 -30 934.0 -14.0Q909 2 887 15L867 28Q862 29 860.5 23.0Q859 17 857 14Q852 9 852 -2Q852 -7 851.5 -10.5Q851 -14 853 -19L928 -234Q909 -229 882.0 -218.5Q855 -208 830 -194Q827 -158 822.0 -124.0Q817 -90 811 -67Q810 -62 814 -62H817Q819 -62 817 -60Q814 -57 811.5 -54.0Q809 -51 807 -49Q805 -47 802.0 -46.5Q799 -46 797 -44Q792 -41 789.5 -39.0Q787 -37 785 -37Z"
)


def wordmark(class_name: str = "halmae-wordmark") -> str:
    """붓글씨 '할매' 워드마크 SVG."""
    return (
        f'<svg class="{class_name}" viewBox="{WORDMARK_VIEWBOX}" '
        'role="img" aria-label="할매" xmlns="http://www.w3.org/2000/svg">'
        f'<path d="{WORDMARK_PATH}" fill="currentColor"/>'
        "</svg>"
    )


def poster_title(small: bool = False) -> str:
    """붓글씨 '할매' + 영문 서브타이틀.

    small=False (첫 화면) : 금선 프레임 + 큰 붓글씨 + HALMAE + 붉은 인장
    small=True  (그 외)   : 작은 붓글씨 + HALMAE 만
    """
    if small:
        return (
            '<div class="halmae-poster">'
            + wordmark("halmae-wordmark halmae-wordmark-sm")
            + '<p class="halmae-latin">HALMAE</p>'
            "</div>"
        )
    return (
        '<div class="halmae-poster">'
        '<span class="halmae-poster-frame top"></span>'
        + wordmark("halmae-wordmark")
        + '<span class="halmae-poster-frame bottom"></span>'
        '<p class="halmae-latin">HALMAE</p>'
        '<br><span class="halmae-seal">사주 · 별자리</span>'
        "</div>"
    )


# ---------------------------------------------------------------
#  가독성 검사
#      python theme.py
# ---------------------------------------------------------------
if __name__ == "__main__":
    print("할매 디자인 시스템 · 명도 대비 검사 (WCAG)")
    print("조선 왕실 의복의 색감을 차용한 컬러 시스템")
    print("=" * 70)
    rows = check_contrast()
    for row in rows:
        mark = "통과" if row["통과"] else "미달 ***"
        print(
            f"  {row['용도']:<28} {row['대비']:>5.2f} : 1   "
            f"(기준 {row['기준']})  {mark}"
        )
    failed = [r for r in rows if not r["통과"]]
    print("=" * 70)
    if failed:
        print(f"미달 {len(failed)}건 — 색을 다시 잡아야 합니다.")
        for row in failed:
            print(f"    {row['용도']}: {row['글씨']} on {row['배경']}")
    else:
        print(f"전체 {len(rows)}건 통과. 본문 4.5:1, 큰 글씨 3:1 기준을 모두 넘겼습니다.")
