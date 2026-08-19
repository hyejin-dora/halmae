"""올해의 카드 그림 — visual_theme 한 칸으로 그림을 정합니다

카드 가운데에는 타로 카드처럼 그림 한 장이 들어갑니다. 그 그림이
'무엇을 그린 그림인지'를 정하는 칸이 visual_theme 입니다.

    visual_theme  = 그림의 주제. 아래 여덟 가지 중 딱 하나. (자유 문장이 아닙니다)
    image_url     = 밖에서 받아온 그림 주소. 아직 없으면 비워둡니다.

[그림은 어떻게 결정되나 — 위에서부터 순서대로]
    1. card_data["image_url"] 이 있으면      → 그 그림. (나중에 이미지 생성 API 자리)
    2. assets/year_cards/<theme>.png 이 있으면 → 그 파일. (사람이 그려 넣는 자리)
    3. 둘 다 없으면                          → 테마별 fallback 아트를 그립니다.
    visual_theme 도 없으면(옛날 카드)        → FALLBACK_VISUAL_THEME 로 봅니다.

[왜 자유 문장이 아니라 여덟 개로 못 박았나]
    Gemini 가 "황금빛 들판 위를 나는 학" 처럼 매번 다른 문장을 지어내면
    그림을 미리 그려둘 수도, 같은 카드에 같은 그림을 붙일 수도 없습니다.
    여덟 개로 좁혀두면 그림을 여덟 장만 준비해도 모든 카드가 채워집니다.

[visual_theme 은 고민과 무관합니다 — 카드 정책 그대로]
    고민 분야 · 추가 질문 · Step1~3 응답은 이 칸을 정하는 데 쓰지 않습니다.
    쓰는 것은 사주 · 점성술 · 올해 간지(세운)뿐입니다.
    그래야 "같은 사람 + 같은 해 = 같은 카드" 가 그림까지 똑같이 유지됩니다.

[실제 그림 파일을 넣는 방법 — 코드는 고치지 않습니다]
    assets/year_cards/ 아래에 아래 여덟 개 이름으로 넣으면 끝입니다.

        assets/year_cards/breakthrough.png
        assets/year_cards/expansion.png
        assets/year_cards/balance.png
        assets/year_cards/transformation.png
        assets/year_cards/grounding.png
        assets/year_cards/connection.png
        assets/year_cards/clarity.png
        assets/year_cards/renewal.png

    .png 말고 .webp / .jpg 를 넣어도 같은 이름이면 알아서 찾습니다.
    파일을 얹으면 그 테마만 사진으로 바뀌고, 없는 테마는 계속 fallback 아트가 나옵니다.
    (그림은 세로 3:4, 짧은 변 900px 이상, 가장자리에 여백을 두고 그리세요 —
     칸 비율이 달라도 찌그러지지 않게 object-fit: cover 로 채우기 때문입니다)

    어떤 그림을 그릴지는 image_prompt(theme) 가 문장으로 들고 있습니다.
    그 문장을 그대로 이미지 생성 모델에 넣으면 여기 화면과 결이 맞습니다.

    python card_visuals.py      # 여덟 테마 · 그림 설명 · 프롬프트 · 파일 유무 확인
"""

import base64
import mimetypes
from enum import Enum
from functools import lru_cache
from pathlib import Path


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
#  2. 그림 파일 자리 — 나중에 png 를 얹기만 하면 되는 곳
#
#  경로는 이 파일이 있는 폴더 기준입니다. (앱을 어디서 실행해도 같은 곳)
#  파일이 있으면 그 그림, 없으면 fallback 아트. 코드는 고칠 것이 없습니다.
# ===============================================================
ASSET_ROOT = "assets/year_cards"

THEME_IMAGE_MAP: dict[str, str] = {
    "breakthrough": f"{ASSET_ROOT}/breakthrough.png",
    "expansion": f"{ASSET_ROOT}/expansion.png",
    "balance": f"{ASSET_ROOT}/balance.png",
    "transformation": f"{ASSET_ROOT}/transformation.png",
    "grounding": f"{ASSET_ROOT}/grounding.png",
    "connection": f"{ASSET_ROOT}/connection.png",
    "clarity": f"{ASSET_ROOT}/clarity.png",
    "renewal": f"{ASSET_ROOT}/renewal.png",
}

assert set(THEME_IMAGE_MAP) == set(VISUAL_THEMES), (
    "THEME_IMAGE_MAP 에 빠진 테마가 있습니다"
)

# png 로 적어두었지만, 같은 이름의 다른 확장자도 받아줍니다.
# (사람이 webp 로 내보냈다고 코드를 고치게 만들 이유가 없습니다)
_ASSET_EXTENSIONS = (".png", ".webp", ".jpg", ".jpeg", ".svg")

# 이 파일이 있는 폴더 = 프로젝트 뿌리. Streamlit 을 어느 폴더에서 띄우든 같습니다.
_PROJECT_ROOT = Path(__file__).resolve().parent

# 그림은 HTML 안에 base64 로 박아 넣습니다. Streamlit 은 기본으로 파일을
# 서빙하지 않으므로 <img src="assets/…"> 는 404 가 됩니다.
# 대신 너무 큰 파일을 매번 문자열로 만들면 화면이 무거워지므로 상한을 둡니다.
_MAX_ASSET_BYTES = 6 * 1024 * 1024


def theme_asset_file(theme) -> Path | None:
    """이 테마의 그림 파일이 실제로 있으면 그 경로, 없으면 None."""
    mapped = _PROJECT_ROOT / THEME_IMAGE_MAP[normalize_theme(theme).value]
    if mapped.is_file():
        return mapped
    for extension in _ASSET_EXTENSIONS:
        candidate = mapped.with_suffix(extension)
        if candidate.is_file():
            return candidate
    return None


def has_theme_asset(theme) -> bool:
    """그림 파일이 이미 들어와 있는가. (진행 상황을 볼 때 씁니다)"""
    return theme_asset_file(theme) is not None


@lru_cache(maxsize=len(VISUAL_THEMES) * 2)
def _asset_data_uri(path_text: str, mtime: float, size: int) -> str | None:
    """파일을 data: 주소로 바꿔 기억해둡니다.

    mtime·size 를 열쇠에 함께 넣는 이유: 파일을 새 그림으로 바꿔 넣으면
    열쇠가 달라져 저절로 다시 읽습니다. (앱을 다시 띄울 필요가 없습니다)
    """
    if size > _MAX_ASSET_BYTES:
        return None
    path = Path(path_text)
    mime = mimetypes.guess_type(path.name)[0] or "image/png"
    try:
        encoded = base64.b64encode(path.read_bytes()).decode("ascii")
    except OSError:
        return None
    return f"data:{mime};base64,{encoded}"


def theme_asset_data_uri(theme) -> str | None:
    """테마 그림을 화면에 바로 박을 수 있는 주소로. 없으면 None."""
    path = theme_asset_file(theme)
    if path is None:
        return None
    try:
        stat = path.stat()
    except OSError:
        return None
    return _asset_data_uri(str(path), stat.st_mtime, stat.st_size)


# ===============================================================
#  3. 카드 아트의 결 — 그림을 새로 그릴 때도, fallback 을 볼 때도 같은 기준
#
#  이 문장은 두 곳에서 씁니다.
#      1) image_prompt(theme) → 이미지 생성 모델에 그대로 넣는 지시문
#      2) 사람이 손으로 그릴 때의 아트 디렉션 메모
#  한 곳에만 적어두어야 그림 여덟 장의 결이 서로 어긋나지 않습니다.
# ===============================================================
ART_DIRECTION = (
    "Hand-drawn pencil sketch with colored-pencil shading on textured hanji "
    "paper, visible graphite grain and paper fiber, never glossy or slick "
    "digital rendering. Korean shamanic and Joseon royal iconography — "
    "mother-of-pearl inlay, gold leaf, dancheong ornament, talismanic "
    "geometry. Deep near-black ground with deep crimson, gold leaf and jade "
    "green accents only. Mysterious, solemn, cinematic occult poster mood in "
    "the vein of Exhuma. Vertical tarot composition, single centered subject, "
    "generous margin, no text, no lettering, no cute or lighthearted styling."
)


# ===============================================================
#  4. 테마별 fallback 아트
#
#  아직 png 가 없을 때 그리는 그림입니다. 아이콘 한 개가 아니라
#  '바닥 → 후광 → 밑그림 → 채색(해칭) → 강조 → 한지 결' 여섯 겹을 쌓아
#  연필로 스케치한 카드 그림처럼 보이게 합니다.
#
#  [색을 SVG 안에 쓰지 않는 규칙]
#      shape 에는 class 만 붙입니다. 색·붓 두께·질감 필터는 전부
#      theme.py 의 CSS 가 정합니다. 나중에 색을 바꿔도 이 파일은 그대로입니다.
#      그래서 gradient·filter 를 가리키는 url(#…) 도 SVG 가 아니라 CSS 에 있습니다.
#
#  [붓 목록]  (theme.py _css_yearcard 에 같은 이름으로 정의되어 있습니다)
#      hm-line        굵은 금색 선 — 주된 형태
#      hm-line-thin   중간 금색 선 — 두 번째 획, 겹쳐 그은 스케치선
#      hm-soft        얇고 흐린 선 — 배경 · 안개 · 결
#      hm-red         대홍 선 — '하나만' 강조할 때
#      hm-jade        비취 선 — 새로 돋는 것
#      hm-hatch       금색 해칭 — 색연필 채색
#      hm-hatch-red   붉은 해칭
#      hm-hatch-jade  비취 해칭
#      hm-glow        형태 뒤에 깔리는 금빛 번짐
#      hm-fill-*      면 채우기 (gold · red · jade · dark)
#      hm-ember       아래에서 올라오는 붉은 기운
#      hm-dew         새벽빛
#      hm-pearl(-jade) 자개 티끌
#
#  [겹 이름]
#      hm-back    먼 배경 (질감 필터 없음 — 흐린 것은 흔들 필요가 없습니다)
#      hm-sketch  연필 밑그림 (손떨림 필터)
#      hm-shade   색연필 채색 (더 거친 손떨림)
#      hm-accent  마지막 강조 (필터 없음 — 여기만 선명해야 눈이 멈춥니다)
# ===============================================================

# 모든 테마가 함께 쓰는 gradient · filter. (색은 CSS 가 넣습니다)
_PLATE_DEFS = """
<defs>
  <radialGradient id="hm-night" cx="50%" cy="34%" r="84%">
    <stop class="hm-night-0" offset="0"/>
    <stop class="hm-night-1" offset="0.5"/>
    <stop class="hm-night-2" offset="1"/>
  </radialGradient>
  <radialGradient id="hm-halo" cx="50%" cy="40%" r="58%">
    <stop class="hm-halo-0" offset="0"/>
    <stop class="hm-halo-1" offset="0.55"/>
    <stop class="hm-halo-2" offset="1"/>
  </radialGradient>
  <linearGradient id="hm-ember-paint" x1="0" y1="1" x2="0" y2="0">
    <stop class="hm-ember-0" offset="0"/>
    <stop class="hm-ember-1" offset="1"/>
  </linearGradient>
  <linearGradient id="hm-dew-paint" x1="0" y1="1" x2="0" y2="0">
    <stop class="hm-dew-0" offset="0"/>
    <stop class="hm-dew-1" offset="1"/>
  </linearGradient>
  <filter id="hm-fiber" x="0" y="0" width="100%" height="100%">
    <feTurbulence type="fractalNoise" baseFrequency="0.9" numOctaves="4"
      seed="11" stitchTiles="stitch"/>
    <feColorMatrix type="saturate" values="0"/>
  </filter>
  <filter id="hm-grain" x="-16%" y="-16%" width="132%" height="132%">
    <feTurbulence type="fractalNoise" baseFrequency="0.05" numOctaves="3"
      seed="5" result="pencil"/>
    <feDisplacementMap in="SourceGraphic" in2="pencil" scale="2.4"
      xChannelSelector="R" yChannelSelector="G"/>
  </filter>
  <filter id="hm-graze" x="-16%" y="-16%" width="132%" height="132%">
    <feTurbulence type="fractalNoise" baseFrequency="0.09" numOctaves="2"
      seed="19" result="crayon"/>
    <feDisplacementMap in="SourceGraphic" in2="crayon" scale="3.4"
      xChannelSelector="R" yChannelSelector="G"/>
  </filter>
  <filter id="hm-bloom" x="-45%" y="-45%" width="190%" height="190%">
    <feGaussianBlur stdDeviation="6"/>
  </filter>
</defs>
"""

# 바닥 · 후광 · 귀퉁이 당초문 — 그림 뒤에 먼저 깔립니다.
# 당초문을 여기 둔 이유: 여덟 장이 공통으로 쓰는 장식이라
# 테마마다 베껴 두면 한 곳을 고칠 때 여덟 곳을 고쳐야 합니다.
_PLATE_BASE = """
<rect class="hm-ground" x="0" y="0" width="240" height="320"/>
<ellipse class="hm-halo" cx="120" cy="126" rx="116" ry="130"/>
<g class="hm-ornament">
  <path d="M12 50 C 12 28, 28 12, 50 12"/>
  <path d="M21 37 C 25 24, 35 17, 48 19 C 39 30, 31 35, 21 37"/>
  <path d="M228 50 C 228 28, 212 12, 190 12"/>
  <path d="M219 37 C 215 24, 205 17, 192 19 C 201 30, 209 35, 219 37"/>
  <path d="M12 270 C 12 292, 28 308, 50 308"/>
  <path d="M21 283 C 25 296, 35 303, 48 301 C 39 290, 31 285, 21 283"/>
  <path d="M228 270 C 228 292, 212 308, 190 308"/>
  <path d="M219 283 C 215 296, 205 303, 192 301 C 201 290, 209 285, 219 283"/>
</g>
"""

# 한지 결 — 마지막에 그림 위를 덮어, 전체가 종이 위 그림처럼 보이게 합니다.
_PLATE_TEXTURE = """
<rect class="hm-hanji" x="0" y="0" width="240" height="320"/>
"""


_ART = {
    VisualTheme.BREAKTHROUGH: {
        "scene": "갈라진 대지를 뚫고 솟는 나무",
        "mood": "쪼개진 땅 · 치솟는 붉은 기운 · 옥빛 새순",
        "subject": (
            "A young tree bursting upward through cracked, split earth, "
            "red heat rising from the fissure, a single jade-green shoot at "
            "the highest branch"
        ),
        "svg": """
<g class="hm-back">
  <path class="hm-soft" d="M120 44 V8"/>
  <path class="hm-soft" d="M94 52 L76 16"/>
  <path class="hm-soft" d="M146 52 L164 16"/>
  <path class="hm-soft" d="M66 78 L36 54"/>
  <path class="hm-soft" d="M174 78 L204 54"/>
  <ellipse class="hm-fill-red" cx="120" cy="238" rx="88" ry="22"/>
  <path class="hm-ember" d="M120 240 C 152 216, 158 186, 148 156
    C 172 190, 176 218, 162 244 Z"/>
  <path class="hm-ember" d="M120 240 C 88 216, 82 186, 92 156
    C 68 190, 64 218, 78 244 Z"/>
</g>
<g class="hm-sketch">
  <path class="hm-glow" d="M120 234 V72"/>
  <path class="hm-line" d="M12 238 H84 l10 -15 8 13 10 -19 9 21 h107"/>
  <path class="hm-line" d="M120 234 V74"/>
  <path class="hm-line-thin" d="M113 232 C 111 188, 116 136, 121 92"/>
  <path class="hm-line" d="M120 170 C 100 158, 86 138, 78 112"/>
  <path class="hm-line" d="M120 148 C 143 138, 159 118, 167 94"/>
  <path class="hm-line" d="M120 122 C 106 110, 98 96, 95 78"/>
  <path class="hm-line-thin" d="M120 104 C 133 94, 141 82, 145 66"/>
  <path class="hm-line-thin" d="M120 190 C 138 182, 150 170, 157 154"/>
  <path class="hm-soft" d="M78 112 l-13 -7"/>
  <path class="hm-soft" d="M167 94 l14 -6"/>
</g>
<g class="hm-shade">
  <path class="hm-hatch-red" d="M46 252 L58 238"/>
  <path class="hm-hatch-red" d="M62 256 L74 240"/>
  <path class="hm-hatch-red" d="M80 258 L92 242"/>
  <path class="hm-hatch-red" d="M150 258 L162 242"/>
  <path class="hm-hatch-red" d="M168 256 L180 240"/>
  <path class="hm-hatch-red" d="M184 252 L196 238"/>
  <path class="hm-hatch" d="M111 216 L131 202"/>
  <path class="hm-hatch" d="M111 198 L130 185"/>
  <path class="hm-hatch" d="M112 180 L129 168"/>
  <path class="hm-hatch" d="M112 162 L128 151"/>
  <path class="hm-hatch" d="M113 144 L128 134"/>
  <path class="hm-hatch" d="M114 126 L127 117"/>
</g>
<g class="hm-accent">
  <path class="hm-jade" d="M145 66 q-14 2 -16 15 q15 -1 16 -15"/>
  <path class="hm-jade" d="M95 78 q13 4 14 16 q-14 -3 -14 -16"/>
  <path class="hm-red-glow" d="M84 238 l10 -15 9 13 10 -19 9 21 h10"/>
  <path class="hm-red" d="M84 238 l10 -15 9 13 10 -19 9 21 h10"/>
  <circle class="hm-pearl" cx="68" cy="96" r="2.6"/>
  <circle class="hm-pearl" cx="184" cy="128" r="2.1"/>
  <circle class="hm-pearl-jade" cx="56" cy="152" r="1.9"/>
  <circle class="hm-pearl" cx="196" cy="196" r="1.7"/>
  <circle class="hm-pearl-jade" cx="150" cy="52" r="1.6"/>
</g>
""",
    },
    VisualTheme.EXPANSION: {
        "scene": "빛이 새는 열린 문과 넓게 뻗은 가지",
        "mood": "단청 문틀 · 문틈의 금빛 · 틀을 넘는 가지",
        "subject": (
            "An open traditional Korean gate with light spilling through the "
            "doorway, bare branches spreading wide past the edges of the "
            "frame, jade buds at the branch tips"
        ),
        "svg": """
<g class="hm-back">
  <path class="hm-fill-gold" d="M94 248 H146 L170 306 H70 Z"/>
  <ellipse class="hm-fill-gold" cx="120" cy="200" rx="27" ry="48"/>
  <path class="hm-soft" d="M120 166 V128"/>
  <path class="hm-soft" d="M36 264 H204"/>
  <path class="hm-soft" d="M24 280 H216"/>
  <path class="hm-soft" d="M40 296 H200"/>
</g>
<g class="hm-sketch">
  <path class="hm-glow" d="M120 248 V140"/>
  <path class="hm-line" d="M10 248 H230"/>
  <path class="hm-line" d="M86 248 V172"/>
  <path class="hm-line" d="M154 248 V172"/>
  <path class="hm-line-thin" d="M97 248 V177"/>
  <path class="hm-line-thin" d="M143 248 V177"/>
  <path class="hm-line" d="M50 172 C 84 156, 156 156, 190 172"/>
  <path class="hm-line-thin" d="M60 161 C 88 149, 152 149, 180 161"/>
  <path class="hm-soft" d="M50 172 q-11 -7 -13 -16"/>
  <path class="hm-soft" d="M190 172 q11 -7 13 -16"/>
  <path class="hm-line" d="M120 154 C 96 138, 66 118, 38 94"/>
  <path class="hm-line" d="M120 154 C 144 138, 174 118, 202 94"/>
  <path class="hm-line-thin" d="M120 142 C 105 120, 97 94, 95 62"/>
  <path class="hm-line-thin" d="M120 142 C 135 120, 143 94, 145 62"/>
  <path class="hm-soft" d="M74 122 C 58 114, 42 112, 24 116"/>
  <path class="hm-soft" d="M166 122 C 182 114, 198 112, 216 116"/>
  <path class="hm-soft" d="M104 100 C 96 84, 92 66, 94 46"/>
  <path class="hm-soft" d="M136 100 C 144 84, 148 66, 146 46"/>
</g>
<g class="hm-shade">
  <path class="hm-hatch" d="M88 240 L96 228"/>
  <path class="hm-hatch" d="M88 222 L96 210"/>
  <path class="hm-hatch" d="M88 204 L96 192"/>
  <path class="hm-hatch" d="M88 186 L96 176"/>
  <path class="hm-hatch" d="M145 240 L153 228"/>
  <path class="hm-hatch" d="M145 222 L153 210"/>
  <path class="hm-hatch" d="M145 204 L153 192"/>
  <path class="hm-hatch" d="M145 186 L153 176"/>
  <path class="hm-hatch-red" d="M66 168 L74 160"/>
  <path class="hm-hatch-red" d="M84 164 L92 157"/>
  <path class="hm-hatch-red" d="M148 164 L156 157"/>
  <path class="hm-hatch-red" d="M166 168 L174 160"/>
</g>
<g class="hm-accent">
  <path class="hm-red" d="M86 172 H154"/>
  <path class="hm-jade" d="M38 94 q-15 -5 -17 -18 q15 4 17 18"/>
  <path class="hm-jade" d="M202 94 q15 -5 17 -18 q-15 4 -17 18"/>
  <path class="hm-jade" d="M95 62 q-13 -8 -11 -21 q13 8 11 21"/>
  <circle class="hm-pearl" cx="120" cy="150" r="3"/>
  <circle class="hm-pearl" cx="52" cy="70" r="2.2"/>
  <circle class="hm-pearl-jade" cx="190" cy="60" r="1.9"/>
  <circle class="hm-pearl" cx="212" cy="150" r="1.7"/>
  <circle class="hm-pearl-jade" cx="30" cy="146" r="1.6"/>
</g>
""",
    },
    VisualTheme.BALANCE: {
        "scene": "해와 달이 마주 선 대칭의 산",
        "mood": "붉은 해 · 금빛 달 · 물에 비친 대칭",
        "subject": (
            "A deep red sun and a gold crescent moon facing each other above "
            "two symmetrical mountain peaks mirrored in still water, a small "
            "taegeuk swirl on the central axis"
        ),
        "svg": """
<g class="hm-back">
  <circle class="hm-fill-red" cx="72" cy="90" r="32"/>
  <circle class="hm-fill-gold" cx="168" cy="90" r="30"/>
  <path class="hm-soft" d="M120 44 V150"/>
  <path class="hm-soft" d="M14 268 H226"/>
  <path class="hm-soft" d="M28 284 H212"/>
  <path class="hm-soft" d="M44 300 H196"/>
  <path class="hm-fill-dark" d="M0 252 H240 V320 H0 Z"/>
</g>
<g class="hm-sketch">
  <circle class="hm-line" cx="72" cy="90" r="27"/>
  <path class="hm-line" d="M177 71 a27 27 0 1 0 0 40 a22 22 0 1 1 0 -40"/>
  <path class="hm-line" d="M14 252 C 34 240, 50 214, 68 176
    C 84 206, 100 228, 120 240
    C 140 228, 156 206, 172 176
    C 190 214, 206 240, 226 252"/>
  <path class="hm-line" d="M10 252 H230"/>
  <path class="hm-line-thin" d="M68 176 C 74 200, 82 226, 96 252"/>
  <path class="hm-line-thin" d="M172 176 C 166 200, 158 226, 144 252"/>
  <path class="hm-soft" d="M30 250 C 44 234, 54 216, 62 196"/>
  <path class="hm-soft" d="M210 250 C 196 234, 186 216, 178 196"/>
  <path class="hm-soft" d="M40 258 C 50 272, 58 284, 64 292"/>
  <path class="hm-soft" d="M200 258 C 190 272, 182 284, 176 292"/>
</g>
<g class="hm-shade">
  <path class="hm-hatch-red" d="M52 96 L64 84"/>
  <path class="hm-hatch-red" d="M56 106 L72 90"/>
  <path class="hm-hatch-red" d="M64 112 L80 96"/>
  <path class="hm-hatch" d="M162 96 L174 84"/>
  <path class="hm-hatch" d="M166 106 L180 92"/>
  <path class="hm-hatch" d="M40 244 L60 214"/>
  <path class="hm-hatch" d="M52 246 L72 216"/>
  <path class="hm-hatch" d="M64 248 L82 222"/>
  <path class="hm-hatch" d="M200 244 L180 214"/>
  <path class="hm-hatch" d="M188 246 L168 216"/>
  <path class="hm-hatch" d="M176 248 L158 222"/>
  <path class="hm-hatch" d="M106 244 L120 230"/>
  <path class="hm-hatch" d="M134 244 L120 230"/>
  <path class="hm-hatch" d="M96 248 L110 234"/>
  <path class="hm-hatch" d="M144 248 L130 234"/>
</g>
<g class="hm-accent">
  <path class="hm-red" d="M72 56 V44"/>
  <path class="hm-red" d="M46 66 L37 56"/>
  <path class="hm-red" d="M98 66 L107 56"/>
  <path class="hm-jade" d="M120 244 V254"/>
  <circle class="hm-pearl" cx="120" cy="152" r="3.2"/>
  <circle class="hm-pearl" cx="120" cy="166" r="1.8"/>
  <circle class="hm-pearl" cx="120" cy="138" r="1.8"/>
  <circle class="hm-pearl" cx="120" cy="30" r="2.2"/>
  <circle class="hm-pearl-jade" cx="34" cy="140" r="1.9"/>
  <circle class="hm-pearl" cx="208" cy="140" r="1.9"/>
  <circle class="hm-pearl-jade" cx="120" cy="278" r="1.7"/>
</g>
""",
    },
    VisualTheme.TRANSFORMATION: {
        "scene": "껍질을 벗고 새로 자라는 나무",
        "mood": "벗겨지는 껍질 · 드러난 붉은 속살 · 옥빛 순",
        "subject": (
            "An old tree shedding curling strips of bark to reveal deep red "
            "inner wood, a single fresh jade-green shoot rising from the "
            "crown, fallen bark on the ground"
        ),
        "svg": """
<g class="hm-back">
  <path class="hm-soft" d="M120 40 V10"/>
  <path class="hm-soft" d="M84 58 L64 30"/>
  <path class="hm-soft" d="M156 58 L176 30"/>
  <ellipse class="hm-fill-red" cx="120" cy="256" rx="76" ry="18"/>
  <path class="hm-ember" d="M120 256 C 136 226, 138 196, 130 168
    C 148 198, 150 228, 140 258 Z"/>
  <path class="hm-soft" d="M24 272 H216"/>
  <path class="hm-soft" d="M40 288 H200"/>
</g>
<g class="hm-sketch">
  <path class="hm-glow" d="M120 254 V96"/>
  <path class="hm-line" d="M10 256 H230"/>
  <path class="hm-line" d="M108 256 C 106 200, 109 148, 113 100"/>
  <path class="hm-line" d="M132 256 C 134 200, 131 148, 127 100"/>
  <path class="hm-line-thin" d="M112 100 C 114 82, 122 68, 138 58"/>
  <path class="hm-line" d="M109 232 C 84 224, 72 200, 84 174
    C 76 180, 70 188, 68 198"/>
  <path class="hm-line" d="M110 194 C 86 186, 76 164, 86 144"/>
  <path class="hm-line" d="M131 222 C 158 214, 170 190, 158 166
    C 166 170, 172 178, 174 188"/>
  <path class="hm-line-thin" d="M110 210 C 94 206, 86 194, 88 182"/>
  <path class="hm-line-thin" d="M131 200 C 148 196, 156 184, 154 172"/>
  <path class="hm-soft" d="M60 256 C 64 244, 76 238, 88 240"/>
  <path class="hm-soft" d="M180 256 C 176 246, 166 240, 154 242"/>
</g>
<g class="hm-shade">
  <path class="hm-hatch-red" d="M115 208 L124 199"/>
  <path class="hm-hatch-red" d="M115 194 L124 185"/>
  <path class="hm-hatch-red" d="M116 180 L125 171"/>
  <path class="hm-hatch-red" d="M116 166 L125 158"/>
  <path class="hm-hatch" d="M110 240 L119 231"/>
  <path class="hm-hatch" d="M110 226 L119 217"/>
  <path class="hm-hatch" d="M122 132 L131 124"/>
  <path class="hm-hatch" d="M122 118 L131 110"/>
  <path class="hm-hatch" d="M86 220 L96 208"/>
  <path class="hm-hatch" d="M84 200 L94 188"/>
  <path class="hm-hatch" d="M150 210 L160 198"/>
  <path class="hm-hatch" d="M152 190 L162 178"/>
  <path class="hm-hatch-jade" d="M132 78 L142 68"/>
  <path class="hm-hatch-jade" d="M128 92 L138 82"/>
</g>
<g class="hm-accent">
  <path class="hm-red" d="M117 212 C 115 194, 117 174, 121 156"/>
  <path class="hm-red" d="M113 206 C 118 200, 124 200, 128 206"/>
  <path class="hm-red" d="M114 178 C 119 172, 125 172, 129 178"/>
  <path class="hm-jade" d="M138 58 q-20 2 -23 21 q21 -2 23 -21"/>
  <path class="hm-jade" d="M115 74 q-19 -4 -21 -22 q20 4 21 22"/>
  <path class="hm-jade" d="M138 58 V38"/>
  <circle class="hm-pearl" cx="56" cy="118" r="2.4"/>
  <circle class="hm-pearl-jade" cx="188" cy="106" r="2.1"/>
  <circle class="hm-pearl" cx="204" cy="164" r="1.8"/>
  <circle class="hm-pearl-jade" cx="38" cy="182" r="1.7"/>
  <circle class="hm-pearl" cx="164" cy="44" r="1.6"/>
</g>
""",
    },
    VisualTheme.GROUNDING: {
        "scene": "돌 위에 깊게 뿌리내린 고목",
        "mood": "겹겹의 지층 · 굳은 기단석 · 흔들리지 않는 뿌리",
        "subject": (
            "An ancient wide-crowned tree on a stone terrace, its deep roots "
            "visible below the ground line through layered strata of earth, "
            "old foundation stones at the base"
        ),
        "svg": """
<g class="hm-back">
  <path class="hm-soft" d="M120 36 V12"/>
  <path class="hm-soft" d="M70 52 L48 32"/>
  <path class="hm-soft" d="M170 52 L192 32"/>
  <path class="hm-fill-dark" d="M0 196 H240 V320 H0 Z"/>
  <path class="hm-soft" d="M8 220 H232"/>
  <path class="hm-soft" d="M8 250 H232"/>
  <path class="hm-soft" d="M8 280 H232"/>
  <ellipse class="hm-fill-gold" cx="120" cy="120" rx="76" ry="46"/>
</g>
<g class="hm-sketch">
  <path class="hm-glow" d="M120 196 V96"/>
  <path class="hm-line" d="M10 196 H230"/>
  <path class="hm-line" d="M102 196 C 100 168, 102 130, 106 100"/>
  <path class="hm-line" d="M138 196 C 140 168, 138 130, 134 100"/>
  <path class="hm-line-thin" d="M106 104 C 92 100, 74 94, 58 86"/>
  <path class="hm-line-thin" d="M134 104 C 148 100, 166 94, 182 86"/>
  <path class="hm-line-thin" d="M120 104 V72"/>
  <path class="hm-line" d="M24 92 C 22 72, 40 60, 58 64
    C 66 44, 96 36, 116 46 C 134 34, 168 40, 176 62
    C 202 62, 218 76, 214 94"/>
  <path class="hm-line-thin" d="M46 88 C 44 72, 58 62, 74 66
    C 84 52, 110 48, 124 58 C 142 50, 164 58, 168 76"/>
  <path class="hm-soft" d="M72 80 C 78 66, 100 60, 114 66"/>
  <path class="hm-soft" d="M128 60 C 144 56, 160 64, 164 76"/>
  <path class="hm-soft" d="M40 100 C 76 88, 164 88, 200 100"/>
  <path class="hm-line" d="M120 196 V308"/>
  <path class="hm-line" d="M114 210 C 86 222, 62 250, 50 292"/>
  <path class="hm-line" d="M126 210 C 154 222, 178 250, 190 292"/>
  <path class="hm-line-thin" d="M114 240 C 96 250, 84 268, 80 296"/>
  <path class="hm-line-thin" d="M126 240 C 144 250, 156 268, 160 296"/>
  <path class="hm-soft" d="M120 264 C 112 278, 110 292, 112 306"/>
  <path class="hm-soft" d="M120 264 C 128 278, 130 292, 128 306"/>
  <path class="hm-line-thin" d="M64 196 q16 -14 32 0"/>
  <path class="hm-line-thin" d="M144 196 q16 -14 32 0"/>
</g>
<g class="hm-shade">
  <path class="hm-hatch" d="M106 188 L124 174"/>
  <path class="hm-hatch" d="M106 168 L124 154"/>
  <path class="hm-hatch" d="M107 148 L125 135"/>
  <path class="hm-hatch" d="M108 128 L126 116"/>
  <path class="hm-hatch" d="M110 110 L127 99"/>
  <path class="hm-hatch" d="M70 92 L86 70"/>
  <path class="hm-hatch" d="M86 90 L102 66"/>
  <path class="hm-hatch" d="M154 90 L138 66"/>
  <path class="hm-hatch" d="M170 92 L154 70"/>
  <path class="hm-hatch-red" d="M96 216 L108 204"/>
  <path class="hm-hatch-red" d="M132 216 L144 204"/>
  <path class="hm-hatch-red" d="M74 258 L86 246"/>
  <path class="hm-hatch-red" d="M154 258 L166 246"/>
</g>
<g class="hm-accent">
  <path class="hm-red-glow" d="M104 200 C 112 208, 128 208, 136 200"/>
  <path class="hm-red" d="M104 200 C 112 208, 128 208, 136 200"/>
  <path class="hm-jade" d="M158 196 V176"/>
  <path class="hm-jade" d="M158 184 C 148 183, 145 175, 146 170
    C 155 172, 158 179, 158 184"/>
  <path class="hm-jade" d="M158 180 C 167 178, 170 171, 169 166
    C 161 168, 158 175, 158 180"/>
  <circle class="hm-pearl" cx="120" cy="56" r="2.8"/>
  <circle class="hm-pearl" cx="46" cy="150" r="2.2"/>
  <circle class="hm-pearl-jade" cx="196" cy="140" r="2"/>
  <circle class="hm-pearl" cx="208" cy="222" r="1.7"/>
  <circle class="hm-pearl-jade" cx="34" cy="238" r="1.6"/>
</g>
""",
    },
    VisualTheme.CONNECTION: {
        "scene": "두 존재를 잇는 한 줄기 붉은 실",
        "mood": "청동 거울 둘 · 가운데 매듭 · 끊기지 않는 붉은 실",
        "subject": (
            "Two bronze mirrors at opposite corners joined by one continuous "
            "winding red thread with a traditional Korean knot tied at the "
            "center, faint radiating lines behind"
        ),
        "svg": """
<g class="hm-back">
  <path class="hm-soft" d="M70 84 L18 40"/>
  <path class="hm-soft" d="M70 84 L26 108"/>
  <path class="hm-soft" d="M172 236 L222 280"/>
  <path class="hm-soft" d="M172 236 L216 212"/>
  <ellipse class="hm-fill-red" cx="120" cy="160" rx="54" ry="54"/>
  <path class="hm-soft" d="M16 160 H60"/>
  <path class="hm-soft" d="M180 160 H224"/>
  <path class="hm-soft" d="M120 40 V70"/>
  <path class="hm-soft" d="M120 250 V284"/>
</g>
<g class="hm-sketch">
  <circle class="hm-line" cx="70" cy="84" r="30"/>
  <circle class="hm-line-thin" cx="70" cy="84" r="22"/>
  <circle class="hm-soft" cx="70" cy="84" r="13"/>
  <circle class="hm-line" cx="172" cy="236" r="30"/>
  <circle class="hm-line-thin" cx="172" cy="236" r="22"/>
  <circle class="hm-soft" cx="172" cy="236" r="13"/>
  <path class="hm-line-thin" d="M70 54 V40"/>
  <path class="hm-line-thin" d="M172 266 V280"/>
  <path class="hm-soft" d="M48 62 L36 50"/>
  <path class="hm-soft" d="M92 62 L104 50"/>
  <path class="hm-soft" d="M150 258 L138 270"/>
  <path class="hm-soft" d="M194 258 L206 270"/>
</g>
<g class="hm-shade">
  <path class="hm-hatch" d="M50 96 L64 82"/>
  <path class="hm-hatch" d="M56 104 L72 88"/>
  <path class="hm-hatch" d="M64 108 L80 92"/>
  <path class="hm-hatch" d="M152 248 L166 234"/>
  <path class="hm-hatch" d="M158 256 L174 240"/>
  <path class="hm-hatch" d="M166 260 L182 244"/>
  <path class="hm-hatch-red" d="M96 150 L110 140"/>
  <path class="hm-hatch-red" d="M100 176 L114 166"/>
  <path class="hm-hatch-red" d="M130 148 L144 138"/>
  <path class="hm-hatch-red" d="M134 174 L148 164"/>
</g>
<g class="hm-accent">
  <path class="hm-red-glow" d="M70 114 C 66 152, 104 132, 110 146"/>
  <path class="hm-red-glow" d="M130 174 C 138 190, 176 192, 172 206"/>
  <path class="hm-red" d="M70 114 C 66 152, 104 132, 110 146"/>
  <path class="hm-red" d="M130 174 C 138 190, 176 192, 172 206"/>
  <path class="hm-red" d="M110 146 C 96 146, 96 164, 110 164
    C 124 164, 124 146, 138 146 C 152 146, 152 164, 138 164
    C 124 164, 124 176, 130 174"/>
  <path class="hm-red" d="M112 158 C 120 152, 130 152, 136 158"/>
  <circle class="hm-pearl" cx="70" cy="84" r="2.6"/>
  <circle class="hm-pearl" cx="172" cy="236" r="2.6"/>
  <circle class="hm-pearl-jade" cx="36" cy="196" r="2"/>
  <circle class="hm-pearl" cx="206" cy="120" r="1.9"/>
  <circle class="hm-pearl-jade" cx="120" cy="292" r="1.6"/>
</g>
""",
    },
    VisualTheme.CLARITY: {
        "scene": "안개가 걷히자 드러나는 달과 길",
        "mood": "갈라지는 안개 · 창백한 달 · 열리는 옥빛 길",
        "subject": "A full moon revealed as horizontal bands of fog part around it, a stone path opening below and receding to the horizon, a single jade marker stone on the path",
        "svg": """
<g class="hm-back">
  <circle class="hm-fill-gold" cx="120" cy="104" r="52"/>
  <path class="hm-fill-dark" d="M0 224 H240 V320 H0 Z"/>
  <path class="hm-soft" d="M10 60 H58"/>
  <path class="hm-soft" d="M182 60 H230"/>
  <path class="hm-soft" d="M16 84 H54"/>
  <path class="hm-soft" d="M186 84 H224"/>
  <path class="hm-soft" d="M8 128 H50"/>
  <path class="hm-soft" d="M190 128 H232"/>
  <path class="hm-soft" d="M20 152 H62"/>
  <path class="hm-soft" d="M178 152 H220"/>
</g>
<g class="hm-sketch">
  <circle class="hm-glow" cx="120" cy="104" r="42"/>
  <circle class="hm-line" cx="120" cy="104" r="42"/>
  <circle class="hm-line-thin" cx="120" cy="104" r="34"/>
  <path class="hm-line" d="M10 184 H84"/>
  <path class="hm-line" d="M156 184 H230"/>
  <path class="hm-line" d="M10 224 H230"/>
  <path class="hm-line" d="M104 224 L48 318"/>
  <path class="hm-line" d="M136 224 L192 318"/>
  <path class="hm-line-thin" d="M96 246 H144"/>
  <path class="hm-line-thin" d="M84 274 H156"/>
  <path class="hm-line-thin" d="M70 302 H170"/>
  <path class="hm-soft" d="M26 206 H90"/>
  <path class="hm-soft" d="M150 206 H214"/>
</g>
<g class="hm-shade">
  <path class="hm-hatch" d="M92 124 L108 108"/>
  <path class="hm-hatch" d="M96 136 L116 116"/>
  <path class="hm-hatch" d="M106 142 L126 122"/>
  <path class="hm-hatch" d="M118 144 L136 126"/>
  <path class="hm-hatch" d="M130 142 L144 128"/>
  <path class="hm-hatch-red" d="M62 200 L74 192"/>
  <path class="hm-hatch-red" d="M166 200 L178 192"/>
  <path class="hm-hatch" d="M100 262 L112 250"/>
  <path class="hm-hatch" d="M128 262 L140 250"/>
  <path class="hm-hatch" d="M86 290 L98 278"/>
  <path class="hm-hatch" d="M142 290 L154 278"/>
</g>
<g class="hm-accent">
  <path class="hm-red-glow" d="M120 62 a42 42 0 0 1 34 26"/>
  <path class="hm-red" d="M120 62 a42 42 0 0 1 34 26"/>
  <path class="hm-jade" d="M111 242 C 111 232, 129 232, 129 242
    C 129 250, 111 250, 111 242"/>
  <path class="hm-jade" d="M113 250 V262"/>
  <path class="hm-jade" d="M127 250 V262"/>
  <circle class="hm-pearl" cx="120" cy="104" r="3"/>
  <circle class="hm-pearl" cx="42" cy="40" r="2.2"/>
  <circle class="hm-pearl-jade" cx="200" cy="34" r="1.9"/>
  <circle class="hm-pearl" cx="212" cy="176" r="1.8"/>
  <circle class="hm-pearl-jade" cx="30" cy="172" r="1.6"/>
</g>
""",
    },
    VisualTheme.RENEWAL: {
        "scene": "새벽빛을 받고 올라오는 새싹",
        "mood": "트는 새벽 · 번지는 금빛 · 갓 나온 옥빛 잎",
        "subject": (
            "A small two-leaf sprout in the foreground against a sun just "
            "breaking the horizon at dawn, soft radiating light, dew on the "
            "ground, faint water ripples"
        ),
        "svg": """
<g class="hm-back">
  <path class="hm-dew" d="M0 0 H240 V320 H0 Z"/>
  <path class="hm-soft" d="M120 78 V34"/>
  <path class="hm-soft" d="M88 88 L66 50"/>
  <path class="hm-soft" d="M152 88 L174 50"/>
  <path class="hm-soft" d="M60 118 L26 92"/>
  <path class="hm-soft" d="M180 118 L214 92"/>
  <path class="hm-soft" d="M44 156 L10 146"/>
  <path class="hm-soft" d="M196 156 L230 146"/>
  <ellipse class="hm-fill-gold" cx="120" cy="234" rx="90" ry="26"/>
</g>
<g class="hm-sketch">
  <path class="hm-glow" d="M64 234 a56 56 0 0 1 112 0"/>
  <path class="hm-line" d="M64 234 a56 56 0 0 1 112 0"/>
  <path class="hm-line-thin" d="M78 234 a42 42 0 0 1 84 0"/>
  <path class="hm-line" d="M8 234 H232"/>
  <path class="hm-soft" d="M20 258 H104"/>
  <path class="hm-soft" d="M136 258 H220"/>
  <path class="hm-soft" d="M34 280 H98"/>
  <path class="hm-soft" d="M142 280 H206"/>
  <path class="hm-soft" d="M52 302 H188"/>
</g>
<g class="hm-shade">
  <path class="hm-hatch" d="M84 226 L100 210"/>
  <path class="hm-hatch" d="M94 230 L112 212"/>
  <path class="hm-hatch" d="M128 230 L146 212"/>
  <path class="hm-hatch" d="M140 226 L156 210"/>
  <path class="hm-hatch-red" d="M100 200 L114 188"/>
  <path class="hm-hatch-red" d="M126 200 L140 188"/>
  <path class="hm-hatch-jade" d="M104 288 L116 276"/>
  <path class="hm-hatch-jade" d="M124 288 L136 276"/>
  <path class="hm-hatch-jade" d="M108 268 L120 256"/>
</g>
<g class="hm-accent">
  <path class="hm-jade" d="M120 306 V244"/>
  <path class="hm-jade" d="M120 268 q-26 -3 -30 -26 q27 3 30 26"/>
  <path class="hm-jade" d="M120 256 q26 -4 30 -27 q-27 4 -30 27"/>
  <path class="hm-red" d="M120 234 V212"/>
  <circle class="hm-pearl" cx="120" cy="188" r="3"/>
  <circle class="hm-pearl" cx="50" cy="70" r="2.3"/>
  <circle class="hm-pearl-jade" cx="192" cy="64" r="2"/>
  <circle class="hm-pearl" cx="214" cy="188" r="1.8"/>
  <circle class="hm-pearl-jade" cx="28" cy="196" r="1.6"/>
</g>
""",
    },
}

# 테마마다 그림이 반드시 하나씩 있어야 합니다. (하나라도 빠지면 바로 알도록)
assert set(_ART) == set(VisualTheme), "visual_theme 여덟 개 중 그림이 빠진 것이 있습니다"


# ===============================================================
#  5. 화면에 그리기
# ===============================================================
def scene_of(theme) -> str:
    """이 테마에 어떤 그림이 들어가는지 한 줄. (그림 아래 첫째 줄)"""
    return _ART[normalize_theme(theme)]["scene"]


def mood_of(theme) -> str:
    """그림의 결을 짚어주는 낱말 셋. (그림 아래 둘째 줄)

    fallback 아트가 '덜 그려진 그림'이 아니라 '이런 결의 그림'으로
    읽히게 하는 줄입니다.
    """
    return _ART[normalize_theme(theme)]["mood"]


def image_prompt(theme) -> str:
    """이미지 생성 모델에 그대로 넣을 문장. (테마당 하나로 고정)

    밖에서 그때그때 지어내면 같은 테마에 매번 다른 그림이 나옵니다.
    그림은 테마당 한 장이어야 하므로 문장도 테마당 하나로 박아둡니다.
    """
    return f"{_ART[normalize_theme(theme)]['subject']}. {ART_DIRECTION}"


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
#
# (우리가 직접 읽은 로컬 파일은 이 검사를 거치지 않습니다. 그 경로는
#  Gemini 나 사용자가 값을 넣을 수 없는, 우리 디스크의 파일뿐입니다)
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
    """아직 그림 파일이 없을 때 그리는 카드 아트.

    여섯 겹을 쌓습니다.
        바닥(hm-ground) → 후광(hm-halo) → 먼 배경(hm-back)
        → 연필 밑그림(hm-sketch) → 색연필 채색(hm-shade)
        → 강조(hm-accent) → 한지 결(hm-hanji)
    """
    resolved = normalize_theme(theme)
    return (
        '<svg class="halmae-yearcard-svg halmae-yearcard-svg--'
        f'{resolved.value}" viewBox="0 0 240 320" role="img" aria-hidden="true" '
        'preserveAspectRatio="xMidYMid slice">'
        f"{_PLATE_DEFS.strip()}"
        f"{_PLATE_BASE.strip()}"
        f'{_ART[resolved]["svg"].strip()}'
        f"{_PLATE_TEXTURE.strip()}"
        "</svg>"
    )


def _frame_html() -> str:
    """그림 위에 얹는 금색 이중 프레임 + 귀퉁이 문양.

    실제 그림이든 fallback 아트든 똑같이 씌웁니다. 그래야 나중에 png 를
    넣어도 카드 틀이 달라 보이지 않습니다. 무늬는 CSS 가 그립니다.
    """
    return '<span class="halmae-yearcard-frame" aria-hidden="true"></span>'


def _plate_label_html(theme) -> str:
    """fallback 아트 아래 두 줄 — 무슨 그림이고, 어떤 결인지."""
    return (
        '<span class="halmae-yearcard-plate">'
        f'<span class="halmae-yearcard-scene">{_escape_attr(scene_of(theme))}</span>'
        f'<span class="halmae-yearcard-mood">{_escape_attr(mood_of(theme))}</span>'
        "</span>"
    )


def _image_html(src: str, theme) -> str:
    return (
        f'<img class="halmae-yearcard-image" src="{_escape_attr(src)}" '
        f'alt="{_escape_attr(scene_of(theme))}" loading="lazy">'
    )


def art_html(card) -> str:
    """카드 가운데 그림 칸의 속 내용.

        1. image_url 이 있으면              → 그 그림
        2. assets/year_cards/<theme>.* 이 있으면 → 그 파일
        3. 둘 다 없으면                     → 테마별 fallback 아트
    """
    resolved = theme_of(card)

    url = safe_image_url(card)
    if url:
        return _image_html(url, resolved) + _frame_html()

    asset = theme_asset_data_uri(resolved)
    if asset:
        return _image_html(asset, resolved) + _frame_html()

    return placeholder_svg(resolved) + _frame_html() + _plate_label_html(resolved)


# ===============================================================
#  6. 프롬프트에 넣을 목록
#     여기서 만들어 쓰면, 테마를 하나 더할 때 프롬프트가 저절로 따라옵니다.
#     (목록을 프롬프트에 손으로 또 적어두면 언젠가 반드시 어긋납니다)
# ===============================================================
def prompt_choices() -> str:
    """Gemini 에게 보여줄 '고를 수 있는 여덟 가지' 목록."""
    return "\n".join(
        f"  {theme.value:<15} {_ART[theme]['scene']}" for theme in VisualTheme
    )


if __name__ == "__main__":
    print("=" * 68)
    print(" 올해의 카드 · 그림 주제 여덟 가지")
    print("=" * 68)
    print(f" 그림 파일을 넣는 곳: {ASSET_ROOT}/<theme>.png")
    print(f" ({_PROJECT_ROOT / ASSET_ROOT})")
    for item in VisualTheme:
        found = theme_asset_file(item)
        mark = f"파일 있음 → {found.name}" if found else "파일 없음 → fallback 아트"
        print()
        print(f"[{item.value}]  {scene_of(item)}")
        print(f"  결      : {mood_of(item)}")
        print(f"  자리    : {THEME_IMAGE_MAP[item.value]}  ({mark})")
        print(f"  프롬프트: {image_prompt(item)}")
    print()
    print(f"기본값(옛날 카드용): {FALLBACK_VISUAL_THEME.value}")
