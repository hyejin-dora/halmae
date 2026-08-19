"""올해의 카드 그림 — visual_theme 한 칸으로 그림을 정합니다

카드는 지금까지 글자만 있었습니다. 앞으로는 타로 카드처럼 가운데에
그림 한 장이 들어갑니다. 그 그림이 '무엇을 그린 그림인지'를 정하는 칸이
visual_theme 입니다.

    visual_theme  = 그림의 주제. 아래 여덟 가지 중 딱 하나. (자유 문장이 아닙니다)
    image_url     = 실제 그려진 그림 파일 주소. 아직 없으면 비워둡니다.

[왜 자유 문장이 아니라 여덟 개로 못 박았나]
    Gemini 가 "황금빛 들판 위를 나는 학" 처럼 매번 다른 문장을 지어내면
    그림을 미리 그려둘 수도, 같은 카드에 같은 그림을 붙일 수도 없습니다.
    여덟 개로 좁혀두면 그림을 여덟 장만 준비해도 모든 카드가 채워집니다.

[visual_theme 은 고민과 무관합니다 — 카드 정책 그대로]
    고민 분야 · 추가 질문 · Step1~3 응답은 이 칸을 정하는 데 쓰지 않습니다.
    쓰는 것은 사주 · 점성술 · 올해 간지(세운)뿐입니다.
    그래야 "같은 사람 + 같은 해 = 같은 카드" 가 그림까지 똑같이 유지됩니다.

[그림은 어떻게 결정되나]
    image_url 이 있으면  → 그 그림을 그대로 보여줍니다.
    image_url 이 없으면  → visual_theme 에 맞는 선화(線畵) placeholder 를 그립니다.
    visual_theme 도 없으면(옛날 카드) → FALLBACK_VISUAL_THEME 로 봅니다.

[다음 단계 — 진짜 일러스트를 붙일 자리]
    1) image_prompt(theme) 가 돌려주는 문장을 이미지 생성 모델에 넣습니다.
    2) 나온 그림을 어딘가(예: Supabase Storage)에 올려 공개 주소를 얻습니다.
    3) 그 주소를 card_data["image_url"] 에 넣어 저장합니다.
       → cards 테이블에 새 칸을 만들 필요가 없습니다. card_data(jsonb) 안입니다.
    그림은 테마당 한 장이면 충분하므로, 테마 여덟 장을 미리 그려두고
    THEME_ART[theme]["image_url"] 처럼 고정 주소를 박아두어도 됩니다.

    python card_visuals.py      # 여덟 테마와 그림 설명을 확인
"""

from enum import Enum


# ===============================================================
#  1. 여덟 가지 그림 주제 (이 목록이 유일한 정답지)
# ===============================================================
class VisualTheme(str, Enum):
    """카드 그림의 주제. 이 여덟 개 중 딱 하나만 고를 것.

    새로 지어내거나, 두 개를 고르거나, 문장으로 설명하지 말 것.
    사주·점성술·올해 간지만 보고 고를 것 — 고민 분야는 주어지지 않았으니
    짐작해서 고르지 말 것.

    (이 설명글은 Gemini 에게 그대로 전달됩니다.
     google-genai 가 enum 필드를 스키마로 옮길 때, 필드 설명 대신
     이 class 의 설명글을 가져가기 때문입니다.)
    """

    BREAKTHROUGH = "breakthrough"
    EXPANSION = "expansion"
    BALANCE = "balance"
    TRANSFORMATION = "transformation"
    GROUNDING = "grounding"
    CONNECTION = "connection"
    CLARITY = "clarity"
    RENEWAL = "renewal"


VISUAL_THEMES: tuple[str, ...] = tuple(theme.value for theme in VisualTheme)

# 옛날 카드(visual_theme 이 없던 시절에 만들어진 카드)와
# 모델이 엉뚱한 값을 적어 보냈을 때 쓰는 안전한 기본값.
#
# balance 를 고른 이유: 여덟 중 가장 중립적인 그림(해와 달, 대칭된 산)이라
# 어떤 카드 글 위에 놓아도 뜻이 어긋나지 않습니다.
FALLBACK_VISUAL_THEME = VisualTheme.BALANCE

# card_data 안에서 쓰는 칸 이름. (Supabase 테이블에 새 칸을 만들지 않습니다)
VISUAL_THEME_FIELD = "visual_theme"
IMAGE_URL_FIELD = "image_url"


def normalize_theme(value) -> VisualTheme:
    """무엇이 들어와도 여덟 중 하나로 돌려줍니다. (절대 예외를 내지 않습니다)

    옛날 카드에는 이 칸이 아예 없습니다. 그래도 앱이 멈추면 안 되므로
    None · 빈 값 · 오타 · 대문자 · 앞뒤 공백을 전부 받아 기본값으로 내립니다.
    """
    if isinstance(value, VisualTheme):
        return value
    try:
        return VisualTheme(str(value).strip().lower())
    except (ValueError, TypeError, AttributeError):
        return FALLBACK_VISUAL_THEME


# ===============================================================
#  2. 테마별 그림 — 지금은 선화(線畵) placeholder
#
#  svg 는 색을 직접 쓰지 않고 class 만 붙입니다.
#      hm-line  굵은 금색 선 (주된 형태)
#      hm-soft  얇고 흐린 선 (배경 · 안개 · 결)
#      hm-red   대홍 (붉은 실처럼 '하나만' 강조할 때)
#      hm-jade  비취 (새로 돋는 것)
#  색은 theme.py 의 CSS 가 정합니다. 나중에 색을 바꿔도 이 파일은 그대로입니다.
# ===============================================================
_ART = {
    VisualTheme.BREAKTHROUGH: {
        "scene": "갈라진 대지를 뚫고 솟는 나무",
        "image_prompt": (
            "A single young tree bursting upward through cracked earth, "
            "traditional Korean ink painting, minimal line art, "
            "gold and deep red on dark ground, vertical tarot composition"
        ),
        "svg": """
<path class="hm-line" d="M12 116 H52 l4 -7 4 7 h48"/>
<path class="hm-soft" d="M48 130 L56 116"/>
<path class="hm-soft" d="M74 132 L64 116"/>
<path class="hm-soft" d="M30 128 L38 116"/>
<path class="hm-line" d="M60 116 V40"/>
<path class="hm-line" d="M60 78 L42 60"/>
<path class="hm-line" d="M60 68 L78 52"/>
<path class="hm-line" d="M60 56 L46 44"/>
<path class="hm-jade" d="M60 46 L74 34"/>
<path class="hm-soft" d="M60 30 V20"/>
<path class="hm-soft" d="M48 34 L42 26"/>
<path class="hm-soft" d="M72 34 L78 26"/>
""",
    },
    VisualTheme.EXPANSION: {
        "scene": "넓게 뻗는 가지와 열린 문",
        "image_prompt": (
            "An open traditional Korean gate with branches spreading wide "
            "beyond its frame, minimal line art, gold on dark ground, "
            "vertical tarot composition"
        ),
        "svg": """
<path class="hm-line" d="M12 130 H108"/>
<path class="hm-line" d="M40 130 V70"/>
<path class="hm-line" d="M80 130 V70"/>
<path class="hm-line" d="M30 70 H90"/>
<path class="hm-soft" d="M24 62 H96"/>
<path class="hm-line" d="M60 70 V34"/>
<path class="hm-line" d="M60 50 C 44 46, 30 38, 20 26"/>
<path class="hm-line" d="M60 50 C 76 46, 90 38, 100 26"/>
<path class="hm-soft" d="M60 40 C 50 34, 44 26, 42 16"/>
<path class="hm-soft" d="M60 40 C 70 34, 76 26, 78 16"/>
<path class="hm-jade" d="M20 26 l-6 -4"/>
<path class="hm-jade" d="M100 26 l6 -4"/>
""",
    },
    VisualTheme.BALANCE: {
        "scene": "해와 달, 대칭으로 마주 선 산",
        "image_prompt": (
            "A sun and a crescent moon facing each other above two "
            "symmetrical mountains, traditional Korean ink painting, "
            "minimal line art, gold and deep red, vertical tarot composition"
        ),
        "svg": """
<circle class="hm-red" cx="38" cy="44" r="13"/>
<path class="hm-line" d="M88 32 a13 13 0 1 0 0 24 a10.5 10.5 0 1 1 0 -24"/>
<path class="hm-soft" d="M60 26 V62"/>
<path class="hm-line" d="M14 126 L44 82 L60 104 L76 82 L106 126"/>
<path class="hm-line" d="M12 126 H108"/>
<path class="hm-soft" d="M44 82 L60 126"/>
<path class="hm-soft" d="M76 82 L60 126"/>
<path class="hm-soft" d="M24 140 H96"/>
""",
    },
    VisualTheme.TRANSFORMATION: {
        "scene": "껍질을 벗고 새로 자라는 나무",
        "image_prompt": (
            "An old tree shedding its bark while a fresh shoot grows from "
            "the top, traditional Korean ink painting, minimal line art, "
            "gold with a single jade-green sprout, vertical tarot composition"
        ),
        "svg": """
<path class="hm-line" d="M12 132 H108"/>
<path class="hm-line" d="M54 132 V52"/>
<path class="hm-line" d="M66 132 V52"/>
<path class="hm-soft" d="M52 122 q-16 -10 -8 -28"/>
<path class="hm-soft" d="M52 100 q-14 -8 -7 -24"/>
<path class="hm-soft" d="M68 118 q16 -10 9 -28"/>
<path class="hm-line" d="M60 52 q2 -14 14 -20"/>
<path class="hm-jade" d="M74 32 q-13 1 -15 13 q13 1 15 -13"/>
<path class="hm-jade" d="M60 45 q-12 -2 -14 -13 q12 2 14 13"/>
<path class="hm-soft" d="M36 140 h18"/>
<path class="hm-soft" d="M68 140 h18"/>
""",
    },
    VisualTheme.GROUNDING: {
        "scene": "깊게 뿌리내린 고목",
        "image_prompt": (
            "An ancient tree with a wide crown and deep visible roots below "
            "the ground line, traditional Korean ink painting, minimal line "
            "art, gold on dark ground, vertical tarot composition"
        ),
        "svg": """
<path class="hm-line" d="M12 96 H108"/>
<path class="hm-line" d="M52 96 V44"/>
<path class="hm-line" d="M68 96 V44"/>
<path class="hm-line" d="M34 44 q26 -30 52 0"/>
<path class="hm-soft" d="M44 40 q16 -16 32 0"/>
<path class="hm-line" d="M60 96 V138"/>
<path class="hm-line" d="M58 104 q-20 8 -28 30"/>
<path class="hm-line" d="M62 104 q20 8 28 30"/>
<path class="hm-soft" d="M58 118 q-10 6 -12 20"/>
<path class="hm-soft" d="M62 118 q10 6 12 20"/>
<path class="hm-soft" d="M60 128 q-4 6 -4 12"/>
""",
    },
    VisualTheme.CONNECTION: {
        "scene": "서로 이어지는 붉은 실",
        "image_prompt": (
            "Two distant points joined by a single winding red thread with "
            "one knot at the center, traditional Korean ink painting, "
            "minimal line art, gold and deep red, vertical tarot composition"
        ),
        "svg": """
<circle class="hm-line" cx="34" cy="42" r="9"/>
<circle class="hm-line" cx="86" cy="120" r="9"/>
<path class="hm-red" d="M34 51 C 34 82, 92 70, 86 111"/>
<circle class="hm-red" cx="60" cy="81" r="5"/>
<path class="hm-red" d="M55 78 q10 6 10 6"/>
<path class="hm-soft" d="M34 42 h-16"/>
<path class="hm-soft" d="M86 120 h16"/>
<path class="hm-soft" d="M20 132 H60"/>
<path class="hm-soft" d="M30 26 h24"/>
""",
    },
    VisualTheme.CLARITY: {
        "scene": "안개가 걷히고 드러나는 달",
        "image_prompt": (
            "A full moon revealed as horizontal bands of fog part around it, "
            "traditional Korean ink painting, minimal line art, gold on dark "
            "ground, vertical tarot composition"
        ),
        "svg": """
<circle class="hm-line" cx="60" cy="60" r="26"/>
<path class="hm-soft" d="M14 54 H30"/>
<path class="hm-soft" d="M90 54 H106"/>
<path class="hm-soft" d="M18 68 H32"/>
<path class="hm-soft" d="M88 68 H102"/>
<path class="hm-line" d="M12 104 H46"/>
<path class="hm-line" d="M74 104 H108"/>
<path class="hm-soft" d="M22 118 H50"/>
<path class="hm-soft" d="M70 118 H98"/>
<path class="hm-soft" d="M34 132 H86"/>
<path class="hm-jade" d="M52 104 H68"/>
""",
    },
    VisualTheme.RENEWAL: {
        "scene": "새벽빛 속 새싹",
        "image_prompt": (
            "A small sprout with two leaves in front of a sun rising over the "
            "horizon at dawn, traditional Korean ink painting, minimal line "
            "art, gold with a jade-green sprout, vertical tarot composition"
        ),
        "svg": """
<path class="hm-line" d="M12 122 H108"/>
<path class="hm-line" d="M32 122 a28 28 0 0 1 56 0"/>
<path class="hm-soft" d="M60 66 V54"/>
<path class="hm-soft" d="M36 76 l-8 -8"/>
<path class="hm-soft" d="M84 76 l8 -8"/>
<path class="hm-soft" d="M24 100 l-10 -4"/>
<path class="hm-soft" d="M96 100 l10 -4"/>
<path class="hm-jade" d="M60 138 V108"/>
<path class="hm-jade" d="M60 118 q-14 -2 -16 -14 q14 2 16 14"/>
<path class="hm-jade" d="M60 112 q14 -2 16 -14 q-14 2 -16 14"/>
<path class="hm-soft" d="M40 138 H80"/>
""",
    },
}

# 테마마다 그림 설명이 반드시 하나씩 있어야 합니다. (하나라도 빠지면 바로 알도록)
assert set(_ART) == set(VisualTheme), "visual_theme 여덟 개 중 그림이 빠진 것이 있습니다"


# ===============================================================
#  3. 화면에 그리기
# ===============================================================
def scene_of(theme) -> str:
    """이 테마에 어떤 그림이 들어가는지 한 줄. (placeholder 아래 설명)"""
    return _ART[normalize_theme(theme)]["scene"]


def image_prompt(theme) -> str:
    """다음 단계에서 이미지 생성 모델에 그대로 넣을 문장.

    여기서 만들지 않고 밖에서 지어내면, 같은 테마에 매번 다른 그림이 나옵니다.
    그림은 테마당 한 장이어야 하므로 문장도 테마당 하나로 고정해둡니다.
    """
    return _ART[normalize_theme(theme)]["image_prompt"]


def _escape_attr(value: str) -> str:
    """따옴표까지 막아, 주소가 HTML 속성을 빠져나가지 못하게 합니다."""
    return (
        str(value)
        .replace("&", "&amp;")
        .replace("<", "&lt;")
        .replace(">", "&gt;")
        .replace('"', "&quot;")
    )


# 그림 주소로 허용하는 것 — 평범한 이미지 주소만.
# javascript: 나 data: 로 시작하는 주소가 카드에 박히면
# 화면에 그대로 심어지는 코드가 되므로 처음부터 받지 않습니다.
_ALLOWED_IMAGE_PREFIXES = ("https://", "http://", "/", "./", "assets/", "static/")


def safe_image_url(card) -> str | None:
    """카드에서 쓸 수 있는 그림 주소만 꺼냅니다. 없거나 수상하면 None."""
    if isinstance(card, dict):
        url = card.get(IMAGE_URL_FIELD)
    else:
        url = getattr(card, IMAGE_URL_FIELD, None)
    url = str(url or "").strip()
    if not url:
        return None
    # 따옴표·꺾쇠·빈칸이 섞인 주소는 주소가 아니라 '속성을 빠져나가려는 글'입니다.
    # (예: https://a.png" onerror="… — 그림 태그를 깨고 코드를 심으려는 모양)
    if any(bad in url for bad in ('"', "'", "<", ">", " ", "\t", "\n")):
        return None
    if not url.startswith(_ALLOWED_IMAGE_PREFIXES):
        return None
    return url


def theme_of(card) -> VisualTheme:
    """카드에서 그림 주제를 꺼냅니다. 없으면(옛날 카드) 기본값."""
    if isinstance(card, dict):
        return normalize_theme(card.get(VISUAL_THEME_FIELD))
    return normalize_theme(getattr(card, VISUAL_THEME_FIELD, None))


def placeholder_svg(theme) -> str:
    """아직 그림이 없을 때 그리는 선화(線畵)."""
    resolved = normalize_theme(theme)
    return (
        '<svg class="halmae-yearcard-svg" viewBox="0 0 120 160" '
        'role="img" aria-hidden="true" preserveAspectRatio="xMidYMid meet">'
        f'{_ART[resolved]["svg"].strip()}'
        "</svg>"
    )


def art_html(card) -> str:
    """카드 가운데 그림 칸의 속 내용.

        image_url 이 있으면  → 그 그림
        없으면               → visual_theme 에 맞는 선화 placeholder
    """
    resolved = theme_of(card)
    url = safe_image_url(card)
    if url:
        return (
            f'<img class="halmae-yearcard-image" src="{_escape_attr(url)}" '
            f'alt="{_escape_attr(scene_of(resolved))}" loading="lazy">'
        )
    return (
        f"{placeholder_svg(resolved)}"
        f'<p class="halmae-yearcard-scene">{_escape_attr(scene_of(resolved))}</p>'
    )


# ===============================================================
#  4. 프롬프트에 넣을 목록
#     여기서 만들어 쓰면, 테마를 하나 더할 때 프롬프트가 저절로 따라옵니다.
#     (목록을 프롬프트에 손으로 또 적어두면 언젠가 반드시 어긋납니다)
# ===============================================================
def prompt_choices() -> str:
    """Gemini 에게 보여줄 '고를 수 있는 여덟 가지' 목록."""
    return "\n".join(
        f"  {theme.value:<15} {_ART[theme]['scene']}" for theme in VisualTheme
    )


if __name__ == "__main__":
    print("=" * 64)
    print(" 올해의 카드 · 그림 주제 여덟 가지")
    print("=" * 64)
    for item in VisualTheme:
        print(f"\n[{item.value}]  {scene_of(item)}")
        print(f"  이미지 프롬프트: {image_prompt(item)}")
    print()
    print(f"기본값(옛날 카드용): {FALLBACK_VISUAL_THEME.value}")
