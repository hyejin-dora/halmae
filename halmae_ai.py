"""할매의 3단계 답변 — 캐릭터, 프롬프트, 응답 구조, Gemini 호출

화면(Streamlit) 코드와 분리해두어서, 프롬프트를 고칠 때 이 파일만 보면 됩니다.

    1단계  할매가 네 팔자부터 딱 짚어주마      → [할매, 더 듣고 싶어요]
    2단계  할매가 조금 더 깊이 들여다봤단다    → [그래서 저는 뭘 하면 좋을까요?]
    3단계  할매의 행동 지령

Gemini 의 답을 자유 글이 아니라 **정해진 구조(JSON)** 로 받습니다.
그래야 화면에서 '근거 / 행동 / 시기 / 상황 / 대사' 칸을 나눠 보여줄 수 있습니다.
구조는 아래 Pydantic 모델이 정의하고, 그대로 Gemini 에 response_schema 로 넘깁니다.

모델 전환은 아래 DEV_MODE 한 줄로 합니다.
    DEV_MODE = True   → 개발·기능 테스트    (가벼운 모델, 무료 quota 절약)
    DEV_MODE = False  → 최종 답변 품질 테스트 (좋은 모델)

터미널에서 바로 확인해보기 (실제 API 를 부릅니다)
    export GEMINI_API_KEY="발급받은_키"
    python halmae_ai.py            # 1~3단계를 차례로 호출해 결과를 출력
"""

import json
import logging
from datetime import date, time
from time import sleep

from google import genai
from google.genai import errors as genai_errors
from google.genai import types
from pydantic import BaseModel, Field, field_validator

from card_visuals import (
    FALLBACK_VISUAL_THEME,
    VisualTheme,
    normalize_theme,
    prompt_choices,
)

# ===============================================================
#  어떤 모델을 쓸지 · 진짜로 부를지 (설정은 config.py 한 곳에 있습니다)
# ===============================================================
from config import (  # noqa: E402
    DEV_MODE,
    DEV_MODEL,
    GEMINI_MODEL,
    PROD_MODEL,
    USE_MOCK_AI,
    get_secret,
)

# 지금 쓰는 모델이 개발용인지 품질용인지 한눈에 보여주기 위한 이름표.
# (환경변수로 덮어썼을 수도 있으니, DEV_MODE 가 아니라 '실제 모델 이름'으로 판단합니다.)
if USE_MOCK_AI:
    MODEL_STAGE = "Mock AI"
elif GEMINI_MODEL == DEV_MODEL:
    MODEL_STAGE = "개발용"
elif GEMINI_MODEL == PROD_MODEL:
    MODEL_STAGE = "품질 테스트"
else:
    MODEL_STAGE = "직접 지정"

if USE_MOCK_AI:
    MODEL_LABEL = "DEV MODE · Mock AI (Gemini 호출 없음)"
else:
    MODEL_LABEL = f"{MODEL_STAGE} 모델 · {GEMINI_MODEL}"

IS_DEV_MODEL = (not USE_MOCK_AI) and GEMINI_MODEL == DEV_MODEL

# 행동 로그에 남길 이름. Mock 으로 만든 줄은 나중에 걸러낼 수 있어야 합니다.
MODEL_LOG_NAME = "mock" if USE_MOCK_AI else GEMINI_MODEL

# 어떤 모델로 돌고 있는지 터미널 로그에도 한 줄 남깁니다.
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
)
logger = logging.getLogger("halmae")
if USE_MOCK_AI:
    logger.info(
        "할매 Mock AI 모드 · Gemini 를 호출하지 않습니다. "
        "실제 호출은 config.py 의 USE_MOCK_AI 를 False 로 바꾸세요"
    )
else:
    logger.info(
        "할매 모델: %s (%s)%s",
        GEMINI_MODEL,
        MODEL_STAGE,
        "  ← 품질 테스트할 때는 config.py 의 DEV_MODE 를 False 로 바꾸세요"
        if IS_DEV_MODEL else "",
    )

# 2·3단계는 A4 두 장 분량을 목표로 하므로 넉넉히 잡습니다.
MAX_OUTPUT_TOKENS = 16384


class HalmaeError(Exception):
    """사용자에게 그대로 보여줘도 되는, 이해하기 쉬운 오류 메시지."""


# ===============================================================
#  1. 할매 캐릭터 · 답변 원칙 · 안전 규칙
#     모든 단계에 공통으로 붙는 지시문입니다.
# ===============================================================
_PERSONA_TEMPLATE = """너는 "할매"다. 만 년 동안 세상사를 지켜본 것 같은, 강인하고 현실적인 할머니 상담가다.

[캐릭터]
- 무조건 다정하게 위로하는 상담가가 아니다.
- 사용자를 아끼기 때문에 핵심을 가감 없이 짚어준다.
- 위로 방식은 "괜찮아, 잘될 거야"가 아니라
  "네 상황은 이렇다. 그러니 여기서는 이렇게 움직여라"다.

[말투]
- "~란다", "~지", "~하거라", "~해보거라" 같은 할머니 말투를 쓴다.
- 이런 표현을 자연스럽게 섞어 쓴다 (과하게 반복하지 말 것):
  어허 / 오냐 / 잘 들어보거라 / 뻔한 달콤한 소리는 하지 않으마 /
  네가 지금 놓치고 있는 건 이거란다 / 할미가 딱 짚어주마 /
  여기서는 정신을 똑바로 차려야 한다 / 네 성정에는 이런 방식이 더 맞는단다 /
  그러니 이렇게 움직여보거라
- 사용자를 부를 때는 이름을 섞어 부르되, 매 문단마다 부르지는 말 것.

[절대 쓰지 말아야 할 표현]
- "너무 걱정하지 마세요"
- "당신은 충분히 잘하고 있어요"
- "천천히 해도 괜찮아요"
- "자신을 믿어보세요"
- "모든 것이 잘될 거예요"
근거 없는 감성적 위로는 최소화한다.

[가장 중요한 답변 원칙 — 근거]
모든 주요 해석에는 반드시 근거가 있어야 한다.
"너는 추진력이 강하다" 라고만 쓰지 말고 다음 순서로 쓴다.

  1) 사주/점성술 근거  →  2) 성향 또는 상황 해석  →  3) {linking_step}

예시 (아래 대괄호 자리에는 반드시 CALCULATED_SAJU 에 적힌 값을 그대로 넣는다.
      이 예시에 적힌 글자를 그대로 베껴 쓰지 마라. 자리 모양만 참고하라):
  "네 일간이 [일간]이고 [오행] 기운이 [개수]개나 되는 데다 태양궁이 [태양궁]이라,
   명리와 점성술 관점 모두에서 목표가 생기면 밀어붙이는 성향이 강하게 나타난단다."

- 어려운 명리 용어(일간, 월령, 식상, 관성 등)는 쓰자마자 바로 쉬운 말로 풀어준다.
- 사주와 점성술을 과학적 사실처럼 말하지 말 것.
  "명리학에서는 ~로 해석한다", "점성술 관점에서는 ~로 본다" 처럼
  해석 체계라는 점이 드러나게 쓴다.

[사실 관계 — 계산과 해석의 분리]
이 서비스에서 계산은 파이썬이 하고, 너는 해석만 한다. 이 경계를 넘지 마라.
- 사주 명식은 CALCULATED_SAJU 블록으로 이미 계산되어 주어진다.
  년주·월주·일주·시주·일간·오행 개수는 전부 확정값이다.
- 그 값을 다시 계산하거나, 추정하거나, 다른 글자로 바꾸어 말하지 마라.
  생년월일과 출생시간이 함께 주어지지만, 그것으로 간지를 뽑아내려 하지 마라.
- 명식 값을 문장에 적을 때는 CALCULATED_SAJU 에 적힌 글자를 그대로 옮겨 적는다.
  (예: 일주가 갑오라고 적혀 있으면 "갑오"라고만 쓴다. 무인·병자 따위로 바꾸지 않는다)
- 오행 개수도 적힌 숫자 그대로 쓴다. 직접 세어 고치지 마라.
- 입력 데이터에 없는 사실을 지어내지 마라.
{luck_rule}

[안전 규칙]
이 서비스는 엔터테인먼트와 자기성찰을 위한 것이다.
아래 주제를 사주를 근거로 확정적으로 단정하지 마라.
- 질병이나 건강 진단 / 투자 수익이나 투자 종목 / 법률적 판단
- 죽음이나 사고 / 임신 여부 / 범죄
- 특정 사람과 반드시 결혼하거나 헤어진다는 판단
- 특정 날짜에 반드시 어떤 사건이 일어난다는 예언
이런 주제가 나오면 사주 해석과 현실적인 자기성찰 수준으로만 답하고,
필요하면 전문가의 판단이 필요한 영역임을 알려준다.

[깊이]
- 짧고 뻔한 운세는 이 서비스의 실패다.
- "내 이야기를 정말 오래 들여다본 것 같다"는 느낌을 주어야 한다.
- 분량을 늘리려고 같은 내용을 다른 표현으로 되풀이하지 마라.
  사용자가 스크롤을 내릴 때마다 새로운 해석이나 새로운 정보가 나와야 한다.
- 누구에게나 적용되는 자기계발 조언은 쓰지 마라.
  {ground_rule}

[형식]
- 정해진 JSON 구조로만 답한다. 마크다운 제목이나 코드펜스는 쓰지 않는다.
- 각 항목 안에서는 줄바꿈을 써도 좋다.
- 항목 이름(예: "근거:", "행동:")을 본문 안에 다시 적지 마라. 구조가 이미 나누어져 있다."""


# 1~3단계는 "지금 이 고민"에 답하는 상담이라 고민과 연결해서 해석합니다.
STEP_LINKING_STEP = "현재 고민과의 연결"
STEP_GROUND_RULE = (
    "반드시 이 사용자의 사주 데이터, 점성술 데이터, "
    "고민 분야, 추가 질문을 서로 연결한다."
)

# 올해의 카드는 "그 사람의 그 해를 대표하는 한 장"입니다.
# 어떤 고민으로 들어와도 같은 카드가 나와야 하므로,
# 페르소나 단계에서부터 '고민과 연결하라'는 지시를 빼둡니다.
# (고민 정보가 프롬프트에 없는데 연결하라고 시키면 모델이 고민을 지어냅니다)
CARD_LINKING_STEP = "올해 한 해 전체를 관통하는 하나의 태도"
CARD_GROUND_RULE = (
    "반드시 이 사용자의 사주 데이터, 점성술 데이터, "
    "올해의 간지(세운)만을 서로 연결한다. "
    "연애·취업·돈·인간관계 같은 특정 고민 분야를 골라 답하지 마라. "
    "고민 정보는 주어지지 않았다. 있다고 가정하거나 지어내지 마라."
)

# ---------------------------------------------------------------
#  대운·세운 데이터를 쓸 수 있는지 — 단계마다 다릅니다
#
#  1~3단계와 올해의 카드에는 대운·세운을 넣지 않습니다. (예전과 같음)
#  '올해의 흐름' 한 곳에서만 파이썬이 계산한 값을 넣어주고,
#  그때도 "계산하지 말고 주어진 값만 써라" 를 못 박습니다.
# ---------------------------------------------------------------
NO_LUCK_RULE = """- 주어지지 않은 항목(예: 상승궁 없음, 대운/연운 없음)은 근거로 삼지 마라.
- 대운·연운·세운 데이터는 제공되지 않는다. 특정 연도나 월을 지어내 예언하지 마라."""

# 올해의 흐름 전용 — 대운·세운이 [CALCULATED_LUCK] 블록으로 주어집니다.
GIVEN_LUCK_RULE = """- 주어지지 않은 항목(예: 상승궁 없음)은 근거로 삼지 마라.
- 대운·세운은 [CALCULATED_LUCK] 블록으로 Python 이 계산을 마쳐 넘겨준다.
  거기 적힌 간지와 연도 구간만 쓰고, 스스로 뽑아내거나 다른 값으로 바꾸지 마라.
- 월운(月運)·일운(日運)은 주어지지 않는다.
  "몇 월에", "언제쯤" 처럼 올해 안의 시점을 짚어 예언하지 마라."""

SYSTEM_INSTRUCTION = _PERSONA_TEMPLATE.format(
    linking_step=STEP_LINKING_STEP,
    ground_rule=STEP_GROUND_RULE,
    luck_rule=NO_LUCK_RULE,
)

# 올해의 카드 전용 — 고민에서 독립된 페르소나
YEAR_CARD_SYSTEM_INSTRUCTION = _PERSONA_TEMPLATE.format(
    linking_step=CARD_LINKING_STEP,
    ground_rule=CARD_GROUND_RULE,
    luck_rule=NO_LUCK_RULE,
)

# 올해의 흐름 전용 — 고민과 연결하되, 대운·세운은 주어진 값만 쓴다
YEAR_FLOW_SYSTEM_INSTRUCTION = _PERSONA_TEMPLATE.format(
    linking_step=STEP_LINKING_STEP,
    ground_rule=STEP_GROUND_RULE,
    luck_rule=GIVEN_LUCK_RULE,
)


# ===============================================================
#  2. 답변 구조 (Gemini 가 이 모양대로 채워서 돌려줍니다)
# ===============================================================
class Evidence(BaseModel):
    """근거 하나 — '무엇을 보고' → '그래서 어떤 사람인지'."""

    source: str = Field(
        description="근거의 출처. '사주' 또는 '점성술' 중 하나만 적을 것."
    )
    fact: str = Field(
        description="근거로 삼은 계산값을 CALCULATED_SAJU / 점성술 데이터에서 "
        "글자 그대로 옮겨 적을 것. 새로 계산하거나 다른 값으로 바꾸면 안 된다. "
        "형식 예: '일간 {일간}, {오행} 기운 {개수}개' 또는 '태양궁 {태양궁}'. "
        "주어진 블록에 없는 값은 절대 쓰지 말 것."
    )
    reading: str = Field(
        description="그 값을 명리학/점성술에서 어떻게 해석하는지, 그래서 이 사람이 "
        "어떤 성향인지. 어려운 용어는 바로 쉬운 말로 풀어서. 2~4문장."
    )


class Step1Answer(BaseModel):
    """1단계 — 할매가 네 팔자부터 딱 짚어주마 (전체 800~1,200자)."""

    headline: str = Field(
        description="한 줄 총평. 이 사람의 핵심적인 특징을 강하게 한 문장으로. "
        "뻔한 칭찬이 아니라 딱 짚는 문장으로."
    )
    evidences: list[Evidence] = Field(
        description="왜 그런 사람인지에 대한 근거. 사주 근거 2개와 점성술 근거 1개, "
        "총 3개를 이 순서대로 넣을 것."
    )
    concern_reading: str = Field(
        description="현재 고민에 대한 핵심 해석. 사용자가 고른 고민 분야와 추가 질문을 "
        "직접 언급하며 답할 것. 뻔한 일반 상담 금지. "
        "타고난 성향과 지금 고민이 '어디에서 충돌하는지'를 반드시 설명할 것. "
        "300자 이상."
    )
    closing: str = Field(
        description="할매의 한마디. 가장 중요한 핵심 조언 1개. "
        "다음 이야기를 궁금하게 만들며 끝낼 것. 다음 단계 내용을 미리 다 말하지 말 것. "
        "단, 대운·연운 데이터가 없으므로 '언제 하면 되는지 시기를 알려주마' 처럼 "
        "시점을 짚어주겠다는 약속은 하지 말 것."
    )


class Insight(BaseModel):
    """강점 또는 약점 하나."""

    title: str = Field(description="이 항목을 한 줄로 요약한 제목.")
    basis: str = Field(
        description="사주 또는 점성술의 어떤 값을 근거로 이렇게 보는지. "
        "출처(명리학/점성술)를 밝히고, 어려운 용어는 바로 풀어 쓸 것."
    )
    in_real_life: str = Field(
        description="그 성향이 실제 생활에서 어떤 모습으로 나타나는지. "
        "직장, 관계, 결정 상황 같은 구체적인 장면으로. 3문장 이상."
    )


class DecisionRule(BaseModel):
    """앞으로 판단할 때 쓸 기준 하나."""

    rule: str = Field(description="기준을 한 문장으로. 실제로 적용 가능한 형태로.")
    why: str = Field(description="이 사람의 사주/점성술 근거상 왜 이 기준이 맞는지.")
    how_to_use: str = Field(
        description="실제 선택 상황에서 이 기준을 어떻게 적용하는지. 예시 상황과 함께."
    )


class Step2Answer(BaseModel):
    """2단계 — 깊은 해석 (전체 2,000~3,000자)."""

    opening: str = Field(
        description="이야기를 여는 두세 문장. 1단계에서 한 말을 되풀이하지 말 것."
    )
    strengths: list[Insight] = Field(
        description="강점 2~3개. 각각 서로 다른 사주/점성술 근거를 쓸 것."
    )
    weaknesses: list[Insight] = Field(
        description="약점 또는 반복해서 빠질 수 있는 패턴 2~3개. "
        "'이런 상황이 오면 너는 자꾸 이렇게 하더라' 식으로 패턴을 짚을 것."
    )
    blind_spot: str = Field(
        description="지금 고민에서 놓치고 있는 부분. 사용자의 추가 질문과 직접 연결할 것. "
        "1단계의 해석을 반복하지 말고 새로운 관점을 줄 것. 400자 이상."
    )
    decision_rules: list[DecisionRule] = Field(
        description="앞으로 판단할 때 쓸 기준 2~3개."
    )


class Directive(BaseModel):
    """행동 지령 하나."""

    title: str = Field(
        description="지령 제목. 할매 말투의 명령형으로. 예: '역할을 하나 직접 가져오거라'"
    )
    basis: str = Field(
        description="왜 이 지령을 내리는지. 사주 또는 점성술의 어떤 요소가 근거인지 "
        "명확히 밝힐 것. 해석 체계임이 드러나게 쓸 것."
    )
    action: str = Field(
        description="정확히 무엇을 해야 하는지. '새로운 도전을 해보세요' 같은 "
        "추상적인 말은 금지. 대상, 범위, 결과물이 분명한 행동으로."
    )
    steps: list[str] = Field(
        description="실제 실행 순서 3~5단계. 각 항목은 바로 따라 할 수 있는 한 문장으로."
    )
    timing: str = Field(
        description="언제 하면 좋은지. 근거 없이 특정 날짜나 연월을 예언하지 말 것. "
        "'이런 일이 생겼을 때', '다음 평가 면담 자리에서'처럼 상황 기준으로 쓸 것."
    )
    situation: str = Field(description="어떤 장소나 상황에서 실행할 수 있는지.")
    script: str = Field(
        description="사람에게 무언가 요청하거나 말해야 하는 행동이면, 실제로 그대로 "
        "쓸 수 있는 짧은 대사. 필요 없는 지령이면 빈 문자열."
    )
    avoid: str = Field(description="이 지령을 실행할 때 하지 말아야 할 행동.")
    expected_change: str = Field(
        description="이 행동을 했을 때 기대할 수 있는 현실적인 변화. "
        "과장하지 말고, 확정적인 미래 예언도 하지 말 것."
    )


class Step3Answer(BaseModel):
    """3단계 — 할매의 행동 지령 (전체 2,000~3,000자)."""

    intro: str = Field(
        description="지령을 내리기 전 여는 말 두세 문장. 왜 이 세 가지인지 짧게."
    )
    directives: list[Directive] = Field(
        description="행동 지령 정확히 3개. 사용자의 고민 분야와 추가 질문에 맞출 것. "
        "세 지령이 서로 다른 영역을 다루게 할 것."
    )
    closing: str = Field(description="할매가 마지막으로 남기는 한마디. 두세 문장.")


class YearFlowAnswer(BaseModel):
    """올해의 흐름 — 대운 × 세운 (전체 900~1,400자)

    [무엇이 여기 없는가]
        대운 간지 · 세운 간지 · 연도 구간은 이 구조에 넣지 않습니다.
        그 값은 파이썬(daeun.py)이 계산한 것이 원본이고, 화면에도 그 값이
        그대로 그려집니다. 할매는 '해석 글'만 채웁니다.
        (모델에게 간지 칸을 주면 결국 다른 글자를 적어 넣습니다)
    """

    opening: str = Field(
        description="여는 말 한두 문장. Step1~3 을 다 들은 사람에게 "
        "'이제 큰 흐름을 짚어주마' 하고 건네는 말."
    )
    daeun_reading: str = Field(
        default="",
        description="A. 지금 지나고 있는 대운. 주어진 대운 간지의 큰 흐름과 "
        "그것이 이 사람 원국(일간·오행·월령)과 어떤 관계인지. 250~400자. "
        "대운이 주어지지 않았으면 빈 글자로 두어라.",
    )
    sewoon_reading: str = Field(
        description="B. 올해의 세운. 올해 특히 강해지는 흐름과 그것이 원국과 "
        "어떤 식으로 만나는지. 250~400자."
    )
    push: str = Field(
        description="C-1. 올해 밀어도 되는 방향. 대운과 세운이 겹치는 자리에서 "
        "나오는 것으로 쓸 것. 100~200자."
    )
    careful: str = Field(
        description="C-2. 올해 조심해야 할 패턴. 겁주지 말고, 이 사람이 실제로 "
        "빠지기 쉬운 형태로. 100~200자."
    )
    concern_link: str = Field(
        description="C-3. 지금 이 사람의 고민 분야·추가 질문과 이 흐름이 "
        "어떻게 연결되는지. 확정적인 사건·날짜 예측은 하지 말 것. 150~250자."
    )
    closing: str = Field(
        description="할매가 남기는 한마디 한두 문장. 짧게 끊을 것."
    )


class YearCardDraft(BaseModel):
    """올해의 카드 — Gemini 가 채워 보내는 칸만 모은 모양.

    저장하거나 남에게 보여주고 싶을 만큼 간결해야 합니다.
    길게 쓰면 카드가 아니라 또 하나의 보고서가 됩니다.

    [정책] 카드는 "같은 사람 + 같은 출생정보 + 같은 해"에 하나만 존재합니다.
    연애로 들어와도, 취업으로 들어와도 같은 카드가 나와야 합니다.
    그래서 이 카드의 어느 칸도 고민 분야·추가 질문·1~3단계 답변에 기대지 않습니다.
    """

    year: int = Field(description="카드의 연도. 주어진 연도를 그대로 적을 것.")
    title: str = Field(
        description="카드 이름. 타로 카드처럼 영문 대문자로, THE 로 시작하는 "
        "두세 단어. 예: THE CROSSROAD, THE SLOW FIRE, THE OPEN GATE. "
        "이 사람의 올해를 한 장면으로 압축한 이름일 것."
    )
    keyword: str = Field(
        description="올해의 핵심 키워드. 한글 한 단어(2~4자). 예: 선택, 매듭, 확장."
    )
    message: str = Field(
        description="한 줄 메시지. 할매 말투로 40자 안팎의 한 문장. "
        "이 한 줄만 봐도 올해 무엇을 해야 하는지 알 수 있게. 따옴표는 넣지 말 것."
    )
    basis: str = Field(
        description="왜 이 카드가 나왔는지. 올해의 간지(세운)와 이 사람의 사주·점성술을 "
        "연결해서 2~3문장, 150자 안팎. 명리학/점성술의 해석임이 드러나게 쓸 것. "
        "특정 고민(연애·취업·돈 등)을 근거로 들지 말 것."
    )
    actions: list[str] = Field(
        description="올해 가장 중요한 행동 원칙 1~2개. 각각 40자 안팎의 한 문장 명령형. "
        "여러 삶의 영역(일·관계·돈·건강)에 그대로 옮겨 적용할 수 있는 원칙일 것. "
        "'이력서를 써라' · '소개팅에 나가라' · '투자를 해라' 처럼 특정 고민 분야에만 "
        "맞는 행동은 금지. 대신 '미뤄온 결정 하나를 이번 달에 매듭지어라' 처럼 "
        "구체적이면서 영역에 묶이지 않게 쓸 것. 추상적인 말 금지. 3개 이상 넣지 말 것."
    )
    caution: str = Field(
        description="올해 조심해야 할 패턴 딱 1개. 60자 안팎. "
        "'이런 상황이 오면 너는 이렇게 하더라' 식으로 구체적인 버릇을 짚을 것. "
        "특정 고민 분야가 아니라, 어느 영역에서든 되풀이되는 버릇으로 쓸 것."
    )
    visual_theme: VisualTheme = Field(
        description="이 카드에 들어갈 그림의 주제. 아래 여덟 개 중 딱 하나만 "
        "고를 것. 새로 지어내거나 문장으로 쓰지 말 것: "
        + ", ".join(item.value for item in VisualTheme)
        + ". 사주·점성술·올해 간지만 보고 고를 것. "
        "고민 분야나 질문은 주어지지 않았으니 짐작해서 고르지 말 것."
    )


class YearCard(YearCardDraft):
    """저장하고 화면에 그리는 카드 — Gemini 가 쓴 칸 + 우리가 붙이는 칸.

    [Gemini 에게 물을 때는 이 모양을 쓰지 않습니다]
        response_schema 로는 YearCardDraft 를 씁니다.
        image_url 을 스키마에 넣어두면 모델이 있지도 않은 주소를 지어냅니다.
        그림 주소는 사람이(우리가) 붙이는 값이지, 모델이 쓰는 값이 아닙니다.

    [옛날 카드도 이 모양으로 읽힙니다]
        Supabase 에 이미 저장된 카드에는 visual_theme · image_url 칸이 없습니다.
        그 카드를 지우거나 다시 만들지 않고 그대로 읽을 수 있도록,
        여기서는 visual_theme 에 기본값을 두고 이상한 값이 와도 받아냅니다.
    """

    visual_theme: VisualTheme = Field(
        default=FALLBACK_VISUAL_THEME,
        description="카드 그림의 주제. 옛날 카드에는 없을 수 있습니다.",
    )
    image_url: str | None = Field(
        default=None,
        description="그려진 카드 일러스트 주소. 아직 없으면 비워둡니다. "
        "있으면 그림을, 없으면 visual_theme placeholder 를 보여줍니다.",
    )

    @field_validator("visual_theme", mode="before")
    @classmethod
    def _accept_any_theme(cls, value):
        """옛날 카드(칸 없음)·오타·대문자를 전부 여덟 개 중 하나로 내립니다.

        여기서 예외를 내면 저장된 카드를 못 읽어 Gemini 를 다시 부르게 됩니다.
        그러면 "같은 사람 + 같은 해 = 같은 카드" 약속이 깨집니다.
        """
        if value is None or value == "":
            return FALLBACK_VISUAL_THEME
        return normalize_theme(value)


STEP_SCHEMAS = {1: Step1Answer, 2: Step2Answer, 3: Step3Answer}


# ===============================================================
#  2-2. 관계 상태 (연애·관계 고민을 고른 사람에게만 묻습니다)
#
#  [왜 만들었나]
#      "연애" 하나만 받으면 할매(Gemini)가 사용자를 솔로라고 짐작하고
#      "소개팅에 나가라", "새로운 사람을 만나보라" 같은 조언을 했습니다.
#      기혼인 사람에게는 쓸모없다 못해 무례한 말이 됩니다.
#      그래서 관계 상태를 '추측 대상'에서 '확정 입력값'으로 옮겼습니다.
#
#  [이 서비스의 원칙과 같은 결]
#      사주 명식·대운·세운과 똑같이 다룹니다.
#          사람이 고른다  →  파이썬이 그대로 넘긴다  →  Gemini 는 해석만 한다
#      Gemini 가 관계 상태를 스스로 정하는 일은 없습니다.
#
#  [올해의 카드와는 무관합니다]
#      카드는 "같은 사람 + 같은 해 = 한 장" 이라, 관계 상태를
#      stable_key 에도 카드 프롬프트에도 넣지 않습니다. (정책 변경 없음)
# ===============================================================
# 이 고민을 골랐을 때만 관계 상태를 묻습니다.
RELATIONSHIP_CONCERN = "연애·관계"

RELATIONSHIP_QUESTION = "현재 관계 상태를 알려주세요."

# 고르지 않았거나 밝히고 싶지 않은 경우에 쓰는 값.
# (라디오를 비워둔 채 제출해도 이 값으로 떨어져, 아무것도 짐작하지 않습니다)
RELATIONSHIP_UNKNOWN = "말하고 싶지 않아요"

RELATIONSHIP_OPTIONS = [
    "솔로·새 인연",
    "썸·연애중",
    "기혼·부부·가정",
    RELATIONSHIP_UNKNOWN,
]

# answers dict 에 담기는 칸 이름. 코드에서 이 이름으로 찾습니다.
RELATIONSHIP_CONTEXT_KEY = "관계 상태"

# 상태마다 '무엇을 중심으로 해석할지'와 '무엇을 하지 말지'를 못 박아둡니다.
# 화면·프롬프트·테스트가 모두 이 표 하나를 봅니다.
RELATIONSHIP_POLICIES = {
    "솔로·새 인연": (
        "새로운 관계를 만들어가는 방식으로 해석하라. "
        "사람을 만나는 방식, 관계에 들어설 때 되풀이되는 패턴, "
        "누구에게 마음이 기우는지 고르는 기준을 중심으로 본다. "
        "이미 사귀는 상대나 배우자가 있다고 전제하지 마라."
    ),
    "썸·연애중": (
        "지금 곁에 있는 상대와의 관계로 해석하라. "
        "소통 방식, 관계를 진전시키는 속도와 방법, 되풀이되는 갈등과 "
        "선택의 패턴을 중심으로 본다. "
        "'새로운 사람을 만나보라'는 조언은 하지 마라. "
        "결혼했다고 전제하지도 마라."
    ),
    "기혼·부부·가정": (
        "배우자와 가정 안의 관계로 해석하라. "
        "배우자와의 소통 방식, 가정 안에서의 균형과 역할, "
        "실제로 해볼 수 있는 행동을 중심으로 본다. "
        "새로운 인연을 찾으라는 조언은 **절대** 하지 마라. "
        "소개팅·새로운 만남·이별을 권하는 말은 어떤 형태로도 쓰지 마라."
    ),
    RELATIONSHIP_UNKNOWN: (
        "관계 상태를 알 수 없다. 솔로인지, 사귀는 중인지, 결혼했는지 "
        "**어느 쪽도 추측하지 마라.** "
        "관계 전반에서 나타나는 성향과 되풀이되는 행동 패턴만 해석하라. "
        "특정 상태를 전제로 한 행동(소개팅·고백·프러포즈·이혼 등)은 "
        "지령으로 내지 마라. "
        "'연인', '배우자', '솔로', '애인' 같은 낱말로 상태를 지어내지 말고 "
        "'가까운 사람', '상대', '곁에 있는 사람' 처럼 상태를 가리지 않는 "
        "말을 써라."
    ),
}

# 관계 상태를 바꿔 말하지 못하게 막는 규칙. 사주 명식의 잠금 규칙과 같은 방식입니다.
RELATIONSHIP_LOCK_RULES = """[관계 상태 사용 규칙 — 어기면 답변 실패로 본다]
- 위 관계 상태는 사용자가 직접 고른 확정값이다. 다른 상태를 가정하지 마라.
- 위에 적힌 상태가 아닌 상황을 전제로 한 조언을 하지 마라.
- 상태를 짐작하게 하는 표현을 쓰지 마라.
  (예: "아직 인연을 못 만났으니", "연인이 없으니", "혼자인 지금")
- 추가 질문에 관계 상황이 분명하게 적혀 있으면 그 내용을 함께 참고하라.
  다만 분명하지 않으면 특정 상태로 단정하지 말고, 위에 적힌 상태만 따르라.
- 사주·점성술 값으로 관계 상태를 역추적하려 하지 마라.
  명식에는 지금 연애 중인지 결혼했는지가 적혀 있지 않다.
- 행동 지령(3단계)을 낼 때 특히 조심하라. 지령은 실제로 하라는 말이라,
  상태와 어긋나면 그대로 무례한 말이 된다.
  (예: 기혼이라고 적혀 있는데 "소개팅에 나가라", "새로운 사람을 만나라")"""


def relationship_context(answers: dict | None) -> str | None:
    """이 사람의 관계 상태. 물어보지 않은 고민이면 None.

    '연애·관계' 를 고른 사람에게만 값이 있습니다.
    고르지 않은 채 제출했으면 '말하고 싶지 않아요' 로 봅니다 —
    비어 있다고 솔로로 넘겨짚으면 안 되니까요.
    """
    if not answers:
        return None
    if answers.get("고민 분야") != RELATIONSHIP_CONCERN:
        return None
    value = (answers.get(RELATIONSHIP_CONTEXT_KEY) or "").strip()
    return value if value in RELATIONSHIP_POLICIES else RELATIONSHIP_UNKNOWN


def build_relationship_block(answers: dict | None) -> str:
    """관계 상태를 프롬프트에 붙일 수 있는 글자로. 해당 없으면 빈 글자.

    이 함수가 관계 상태가 프롬프트로 나가는 유일한 통로입니다.
    """
    state = relationship_context(answers)
    if state is None:
        return ""

    return "\n".join([
        "[관계 상태 — 사용자가 직접 고른 확정 입력값]",
        f"- 현재 관계 상태: {state}",
        f"- 이 상태를 기준으로만 해석한다: {RELATIONSHIP_POLICIES[state]}",
        "",
        RELATIONSHIP_LOCK_RULES,
    ])


# ===============================================================
#  3. 사용자 정보 블록 만들기
# ===============================================================
def _as_text(value) -> str:
    """저장된 입력값을 프롬프트에 넣기 좋은 글자로 바꿉니다."""
    if value is None or value == "":
        return "모름"
    if isinstance(value, bool):
        return "예" if value else "아니오"
    if isinstance(value, date):
        return value.strftime("%Y년 %m월 %d일")
    if isinstance(value, time):
        return value.strftime("%H시 %M분")
    return str(value)


def build_profile_block(
    answers: dict,
    saju: dict | None = None,
    astro: dict | None = None,
) -> str:
    """사용자 입력 + 사주 + 점성술을 하나의 사실 블록으로 묶습니다.

    saju 나 astro 가 없으면(계산 실패 등) 그 사실을 분명히 적어서,
    할매가 없는 근거를 지어내지 않도록 합니다.
    """
    # 순환 import 를 피하려고 여기서 불러옵니다.
    from astrology import format_astrology_for_prompt
    from saju import format_saju_for_prompt

    birth_date = _as_text(answers.get("생년월일"))
    calendar_type = _as_text(answers.get("달력 유형"))
    leap_month = answers.get("평달/윤달")
    if leap_month:
        birth_date = f"{birth_date} ({calendar_type}, {leap_month})"
    else:
        birth_date = f"{birth_date} ({calendar_type})"

    if answers.get("출생시간 모름"):
        birth_time = "모름"
    else:
        birth_time = _as_text(answers.get("출생시간"))

    blocks = [
        "[사용자 정보]\n"
        f"- 이름: {_as_text(answers.get('이름'))}\n"
        f"- 생년월일: {birth_date}\n"
        f"- 출생시간: {birth_time}\n"
        f"- 출생지역: {_as_text(answers.get('출생지역'))}\n"
        f"- 성별: {_as_text(answers.get('성별'))}\n"
        f"- 고민 분야: {_as_text(answers.get('고민 분야'))}\n"
        f"- 추가 질문: {_as_text(answers.get('추가 질문'))}"
    ]

    # 관계 상태는 '연애·관계' 를 고른 사람에게만 있습니다.
    # 없는 사람에게는 이 블록 자체가 붙지 않습니다.
    relationship = build_relationship_block(answers)
    if relationship:
        blocks.append(relationship)

    if saju:
        blocks.append(format_saju_for_prompt(saju))
    else:
        blocks.append(
            "[사주 명식]\n계산하지 못했다. 사주를 근거로 든 해석은 하지 말 것."
        )

    if astro:
        blocks.append(format_astrology_for_prompt(astro))
    else:
        blocks.append(
            "[점성술 데이터]\n계산하지 못했다. 점성술을 근거로 든 해석은 하지 말 것."
        )

    return "\n\n".join(blocks)


# ===============================================================
#  4. 단계별 질문
# ===============================================================
STEP_TITLES = {
    1: "할매가 네 팔자부터 딱 짚어주마",
    2: "할매가 조금 더 깊이 들여다봤단다",
    3: "할매의 행동 지령",
}

NEXT_BUTTON_LABELS = {
    2: "할매, 더 듣고 싶어요",
    3: "그래서 저는 뭘 하면 좋을까요?",
}

# 로딩 문구는 progress.py 한 곳으로 옮겼습니다.
#     예전에는 단계마다 문구 하나를 스피너에 걸어두었는데,
#     Gemini 한 번 호출이 10초 가까이 걸리다 보니 같은 글이 계속 떠 있어
#     "앱이 멈췄나?" 하는 오해가 생겼습니다.
#     지금은 기다리는 동안 문구가 바뀝니다 — progress.STEP_STAGES 참고.

# 1단계 맨 끝에 붙는 예고 한 문장 — 뒤에 '올해의 흐름'이 있다는 걸 알려줍니다.
#
# [왜 Gemini 에게 맡기지 않았나]
#     이 문장은 "뒤에 무엇이 더 있다" 는 서비스 안내라서, 있다 없다 하면
#     사용자가 흐름을 놓칩니다. 매번 똑같이 나와야 하므로 파이썬 고정 문구로 둡니다.
#     (Step2·3 에서는 이 예고를 되풀이하지 않습니다 — 중복 안내는 지저분합니다)
STEP1_YEAR_FLOW_TEASER = (
    "마지막엔 네 대운과 올해 세운이 어디서 맞물리는지까지 짚어주마. "
    "올해 무엇을 밀고 무엇을 조심해야 하는지 그때 확실히 일러줄 테니 "
    "끝까지 잘 따라오너라."
)

STEP1_TASK = """[이번에 할 일 — 첫 번째 이야기]
위 사람의 사주와 점성술 데이터를 근거로 첫 번째 이야기를 들려주거라.

A. headline — 한 줄 총평
B. evidences — 왜 그런 사람인지 (사주 근거 2개 + 점성술 근거 1개, 이 순서로)
C. concern_reading — 현재 고민에 대한 핵심 해석
D. closing — 할매의 한마디

[분량] 전체 합쳐 한글 800~1,200자. 모바일에서 한 번에 읽을 만한 길이.
[주의] 2단계에서 할 깊은 분석과 3단계 행동 지령은 여기서 미리 다 말하지 말 것.
       지금은 "더 듣고 싶다"는 마음이 들게 하는 것이 목적이다."""

STEP2_TASK = """할매, 더 듣고 싶어요.

[이번에 할 일 — 깊은 해석]
앞에서 한 말을 되풀이하지 말고, 한 걸음 더 들어가거라.

A. strengths — 강점 2~3개 (근거 + 현실에서 어떻게 나타나는지)
B. weaknesses — 약점 또는 반복해서 빠질 수 있는 패턴 2~3개
C. blind_spot — 지금 고민에서 놓치고 있는 부분 (추가 질문과 직접 연결)
D. decision_rules — 앞으로 판단할 때 쓸 기준 2~3개

[분량] 전체 합쳐 한글 2,000~3,000자. A4 두 장을 읽는 정도의 깊이.
[반드시 지킬 것]
- 1단계에서 쓴 근거를 그대로 다시 쓰지 말고, 아직 안 쓴 사주/점성술 요소를 꺼내 쓸 것
  (예: 1단계에서 일간을 썼다면 여기서는 월지·오행 편중·달궁 같은 다른 값을 활용)
- 해석마다 "왜 그렇게 보는지" 근거를 함께 적을 것
- 인간관계 방식과 의사결정 방식까지 다룰 것
- 문장만 늘려 분량을 채우지 말 것. 새로운 정보가 계속 나와야 한다.
- 아직 구체적인 행동 지령은 내리지 말 것. 그건 다음 단계다."""

STEP3_TASK = """그래서 저는 뭘 하면 좋을까요?

[이번에 할 일 — 행동 지령]
이번에는 추상적인 조언 말고, 이 사람이 실제로 해볼 수 있는 행동 지령 3개를 내리거라.
이 단계가 이 서비스의 핵심이다.

각 지령마다 반드시 아래를 모두 채운다.
1. basis          — 왜 이 지령을 내리는지 / 어떤 사주·점성술 요소가 근거인지
2. action         — 정확히 무엇을 해야 하는지
3. steps          — 실제 실행 순서 3~5단계
4. timing         — 언제 또는 어떤 상황에서
5. situation      — 어떤 장소나 상황에서
6. script         — 사람과 대화가 필요하면 그대로 쓸 수 있는 대사
7. avoid          — 하지 말아야 할 행동
8. expected_change — 기대할 수 있는 현실적인 변화

[분량] 전체 합쳐 한글 2,000~3,000자. 지령 하나를 한두 문장으로 끝내지 말 것.

[금지]
- "새로운 도전을 해보세요", "사람들을 많이 만나보세요" 같은 누구에게나 되는 말
- 대운·연운 데이터가 없으므로 "2027년에는", "올해 하반기에는" 같은 시점 예언
  → 시기는 반드시 상황 기준으로 쓸 것
- 세 지령이 사실상 같은 이야기인 것 (서로 다른 영역을 다룰 것)"""

STEP_TASKS = {1: STEP1_TASK, 2: STEP2_TASK, 3: STEP3_TASK}


def build_prompt(
    step: int,
    answers: dict,
    saju: dict | None = None,
    astro: dict | None = None,
) -> str:
    """단계 번호에 맞는 질문 글을 돌려줍니다.

    1단계에는 사용자 정보 블록을 통째로 붙입니다.
    2·3단계는 앞선 대화가 함께 전달되지만, 대화가 길어질수록 모델이 명식을
    슬금슬금 바꿔 말하는 일이 생깁니다. 그래서 확정 명식(CALCULATED_SAJU)과
    관계 상태만 단계마다 다시 붙여 못을 박습니다.
    (이름·생년월일 같은 나머지 사용자 정보는 다시 붙이지 않습니다)
    """
    if step == 1:
        return build_profile_block(answers, saju, astro) + "\n\n" + STEP1_TASK

    return _reanchor_block(saju, astro, answers) + STEP_TASKS[step]


def _reanchor_block(
    saju: dict | None,
    astro: dict | None,
    answers: dict | None = None,
) -> str:
    """2·3단계 맨 앞에 다시 붙이는 확정값 블록.

    개인정보(이름·생년월일 등)는 넣지 않습니다. 계산 결과만 다시 못 박습니다.

    관계 상태도 여기서 다시 붙입니다. 3단계 행동 지령까지 가는 동안
    모델이 "그러고 보니 새 사람을 만나보라" 로 흘러가는 일이 실제로 있어서,
    단계마다 같은 값을 다시 보여줍니다.
    """
    from astrology import format_astrology_for_prompt
    from saju import format_saju_for_prompt

    parts = ["[다시 확인 — 아래 값은 1단계와 똑같은 확정값이다. 바뀌지 않았다]"]
    if saju:
        parts.append(format_saju_for_prompt(saju))
    else:
        parts.append("[사주 명식]\n계산하지 못했다. 사주를 근거로 든 해석은 하지 말 것.")
    if astro:
        parts.append(format_astrology_for_prompt(astro))

    relationship = build_relationship_block(answers)
    if relationship:
        parts.append(relationship)

    return "\n\n".join(parts) + "\n\n"


# ===============================================================
#  4-2. 할매가 계산값을 바꿔 말했는지 확인
#
#  화면에 뜨는 명식은 파이썬 계산값이라(app.render_myeongsik) 잘못 보이는 일은
#  없습니다. 다만 해석 글 안에서 다른 간지를 말하면 앞뒤가 안 맞으므로,
#  개발 로그에 남겨 프롬프트를 손볼 수 있게 합니다.
#
#  로그에는 '어느 칸에서 어긋났는지'와 '맞는 값'만 남깁니다.
#  생년월일·이름 같은 개인정보는 넣지 않습니다.
# ===============================================================
def _text_fields(answer) -> list[tuple[str, str]]:
    """응답 안의 글자 칸을 (칸 이름, 내용)으로 모두 펼칩니다."""
    found: list[tuple[str, str]] = []

    def walk(value, path: str) -> None:
        if isinstance(value, str):
            found.append((path, value))
        elif isinstance(value, dict):
            for key, item in value.items():
                walk(item, f"{path}.{key}" if path else key)
        elif isinstance(value, list):
            for index, item in enumerate(value):
                walk(item, f"{path}[{index}]")

    walk(answer.model_dump(), "")
    return found


def find_saju_contradictions(
    answer, saju: dict | None, extra_allowed: set[str] | None = None
) -> list[str]:
    """할매 답변이 확정 명식과 어긋나는 곳을 찾아 문장으로 돌려줍니다.

    extra_allowed 에는 '이 단계에서는 써도 되는 간지' 를 넣습니다.
    올해의 흐름에서는 대운·세운 간지가 여기에 들어갑니다 —
    파이썬이 계산해 넘겨준 값이라 명식에 없어도 어긋난 것이 아닙니다.
    """
    if not saju:
        return []

    from saju import CHEONGAN, JIJI, saju_facts

    facts = saju_facts(saju)
    allowed = {
        pillar[:2] for pillar in
        (facts["년주"], facts["월주"], facts["일주"], facts["시주"])
        if pillar
    }
    allowed |= (extra_allowed or set())
    every_ganji = {stem + branch
                   for index, stem in enumerate(CHEONGAN)
                   for offset, branch in enumerate(JIJI)
                   if (index - offset) % 2 == 0}      # 실제로 존재하는 60갑자만

    warnings: list[str] = []
    seen: set[str] = set()
    for field, text in _text_fields(answer):
        for position in range(len(text) - 1):
            pair = text[position:position + 2]
            if pair in every_ganji and pair not in allowed and pair not in seen:
                seen.add(pair)
                warnings.append(
                    f"할매가 명식에 없는 간지 '{pair}' 를 말했습니다 "
                    f"({field}). 확정 명식은 {' · '.join(sorted(allowed))} 입니다."
                )

    return warnings


# ===============================================================
#  5. Gemini 호출
# ===============================================================
def get_client(api_key: str | None = None) -> genai.Client:
    """Gemini 클라이언트를 만듭니다. 키는 코드에 적지 않습니다.

    config.get_secret() 이 환경변수(내 컴퓨터·Codespaces)를 먼저 보고,
    없으면 st.secrets(Streamlit Community Cloud)를 봅니다.
    """
    # api_key 는 문자열이어야 합니다. 문자열이 아닌 값이 들어오면
    # .strip() 에서 엉뚱한 AttributeError 가 나서 원인을 찾기 어려워집니다.
    # (예전 사고: 호출부의 year_notes(list) 가 이 자리로 밀려들어왔습니다)
    # 그래서 조용히 str() 로 바꾸지 않고, 무엇이 잘못 왔는지 밝히고 멈춥니다.
    if api_key is not None and not isinstance(api_key, str):
        raise TypeError(
            "get_client(api_key=...) 는 문자열만 받습니다. "
            f"받은 값의 타입: {type(api_key).__name__}. "
            "카드 인자(year_notes 등)가 api_key 자리로 밀려 들어왔는지 "
            "호출부의 인자 순서를 확인하세요."
        )

    key = (api_key or get_secret("GEMINI_API_KEY")).strip()
    if not key:
        # 사용자에게는 무엇을 하면 되는지만 알려줍니다.
        # (환경변수 이름과 설정 위치는 개발자가 볼 로그에만 적습니다)
        logger.error(
            "GEMINI_API_KEY 가 없습니다 — 내 컴퓨터는 환경변수로, "
            "Streamlit Cloud 는 Settings → Secrets 에 넣어주세요."
        )
        raise HalmaeError(
            "할매가 지금은 답을 할 수 없는 상태예요. "
            "잠시 뒤에 다시 시도해주세요."
        )
    return genai.Client(api_key=key)


def _generate_with_retry(client: genai.Client, contents: list, config):
    """Gemini를 호출합니다. 서버가 붐빌 때(5xx)는 잠깐 쉬었다 몇 번 더 시도합니다.

    Gemini 로 나가는 길목은 이 함수 하나뿐입니다.
    그래서 Mock 모드에서 여기까지 들어왔다는 건 어딘가 빠뜨린 길이 있다는 뜻이라,
    조용히 넘어가지 않고 일부러 큰 소리로 멈춥니다. (요구사항: API 보호)
    """
    if USE_MOCK_AI:
        raise RuntimeError(
            "Mock AI 모드인데 Gemini 를 호출하려 했습니다. "
            "이건 버그입니다 — 어딘가 Mock 처리를 빠뜨린 길이 있습니다. "
            "(config.USE_MOCK_AI = True)"
        )

    last_error = None
    for attempt in range(3):
        try:
            logger.info(
                "Gemini 호출 · 모델 %s (%s) · %d번째 시도",
                GEMINI_MODEL, MODEL_STAGE, attempt + 1,
            )
            return client.models.generate_content(
                model=GEMINI_MODEL,
                contents=contents,
                config=config,
            )
        except genai_errors.ServerError as exc:
            last_error = exc
            if attempt < 2:
                sleep(1.5 * (attempt + 1))     # 1.5초 → 3초 쉬고 재시도
    raise last_error


def _parse_answer(response, schema) -> BaseModel:
    """Gemini 응답을 정해진 구조로 바꿉니다.

    보통은 SDK 가 이미 파싱해 둔 response.parsed 를 그대로 쓰면 됩니다.
    혹시 비어 있으면 본문 글자를 직접 JSON 으로 읽어봅니다.
    """
    parsed = getattr(response, "parsed", None)
    if isinstance(parsed, schema):
        return parsed

    try:
        raw = (response.text or "").strip()
    except Exception as exc:
        raise HalmaeError(
            "할매의 답을 읽어오지 못했어요. 한 번만 다시 물어봐주세요."
        ) from exc

    if not raw:
        raise HalmaeError(
            "할매가 이번에는 답을 내놓지 못했어요. 한 번만 다시 물어봐주세요."
        )

    # 혹시 ```json 코드펜스가 붙어 왔으면 벗겨냅니다.
    if raw.startswith("```"):
        raw = raw.split("\n", 1)[-1]
        if raw.endswith("```"):
            raw = raw[:-3]

    try:
        return schema.model_validate(json.loads(raw))
    except Exception as exc:
        raise HalmaeError(
            "할매의 이야기가 도중에 끊겼어요. 한 번만 다시 물어봐주세요."
        ) from exc


def ask_halmae(
    step: int,
    answers: dict,
    history: list,
    saju: dict | None = None,
    astro: dict | None = None,
    api_key: str | None = None,
) -> BaseModel:
    """이전 대화(history)에 이번 질문을 붙여 Gemini에 물어봅니다.

    돌려주는 값: Step1Answer / Step2Answer / Step3Answer 중 하나.
    실패하면 HalmaeError를 냅니다. 부르는 쪽에서 try/except로 받아
    화면에 안내 문구만 보여주면 앱이 멈추지 않습니다.
    """
    schema = STEP_SCHEMAS[step]
    question = build_prompt(step, answers, saju, astro)

    # --- Mock 모드: Gemini 를 부르지 않고 미리 만들어둔 답을 씁니다 ---
    #     대화 기록(history)은 실제와 똑같이 쌓아서, 단계 이동이 그대로 동작합니다.
    if USE_MOCK_AI:
        from mock_ai import MOCK_DELAY_SECONDS, mock_step_answer

        sleep(MOCK_DELAY_SECONDS)          # 로딩 화면이 보이는지 확인용
        answer = mock_step_answer(step, answers, saju, astro)
        history.append({"role": "user", "text": question})
        history.append(
            {
                "role": "model",
                "text": json.dumps(answer.model_dump(), ensure_ascii=False),
            }
        )
        logger.info("%d단계 Mock 응답 사용 · Gemini 호출 없음", step)
        return answer

    client = get_client(api_key)

    # 앞선 대화 + 이번 질문을 통째로 보내 맥락을 유지합니다.
    contents = [
        {"role": turn["role"], "parts": [{"text": turn["text"]}]}
        for turn in history
    ]
    contents.append({"role": "user", "parts": [{"text": question}]})

    config = types.GenerateContentConfig(
        system_instruction=SYSTEM_INSTRUCTION,
        response_mime_type="application/json",
        response_schema=schema,
        max_output_tokens=MAX_OUTPUT_TOKENS,
        temperature=1.0,
    )

    try:
        response = _generate_with_retry(client, contents, config)
    except genai_errors.ClientError as exc:          # 키·요청·사용량 문제 (4xx)
        if exc.code == 429:
            raise HalmaeError(
                "지금은 요청이 너무 많아 할매가 잠시 쉬고 있어요. "
                "1~2분 뒤에 다시 시도해주세요."
            ) from exc
        # 키가 틀리면 보통 400(API key not valid) 또는 401/403으로 옵니다.
        if exc.code in (401, 403) or "api key" in str(exc).lower():
            # 사용자는 API 키를 모릅니다. 원인은 개발 로그에만 남깁니다.
            logger.error(
                "Gemini 인증 실패 (코드 %s) — GEMINI_API_KEY 값과 권한을 확인하세요.",
                exc.code,
            )
            raise HalmaeError(
                "할매가 지금은 답을 할 수 없는 상태예요. "
                "잠시 뒤에 다시 시도해주세요."
            ) from exc
        raise HalmaeError(
            f"요청을 보내는 중 문제가 생겼어요. (오류 코드 {exc.code})"
        ) from exc
    except genai_errors.ServerError as exc:          # 구글 서버 쪽 문제 (5xx)
        raise HalmaeError(
            "할매가 잠시 자리를 비웠어요. 잠시 뒤에 다시 시도해주세요."
        ) from exc
    except HalmaeError:
        raise
    except Exception as exc:                         # 네트워크 끊김 등 나머지
        raise HalmaeError(
            "답변을 받아오지 못했어요. 인터넷 연결을 확인한 뒤 다시 시도해주세요."
        ) from exc

    answer = _parse_answer(response, schema)

    # 할매가 명식을 바꿔 말했는지 확인합니다. (화면에 뜨는 명식은 파이썬 값이라
    # 사용자에게 잘못 보이지는 않지만, 해석 글 안에서 어긋나면 알아야 합니다)
    contradictions = find_saju_contradictions(answer, saju)
    if contradictions:
        # 운영 로그에는 개인정보가 남으면 안 되므로 '몇 군데가 어긋났는지'만
        # 남깁니다. 실제 값은 개발용 테스트(test_saju_pipeline.py)에서 봅니다.
        logger.warning(
            "%d단계 — 할매가 확정 명식에 없는 간지를 %d군데에서 말했습니다. "
            "화면에 뜨는 명식은 파이썬 계산값이라 영향은 없지만 프롬프트 점검 필요.",
            step, len(contradictions),
        )

    usage = getattr(response, "usage_metadata", None)
    if usage is not None:
        logger.info(
            "%d단계 답변 완료 · 모델 %s · 입력 %s토큰 / 출력 %s토큰",
            step, GEMINI_MODEL,
            getattr(usage, "prompt_token_count", "?"),
            getattr(usage, "candidates_token_count", "?"),
        )

    # 다음 단계에서도 맥락이 이어지도록 이번에 주고받은 내용을 기록해 둡니다.
    history.append({"role": "user", "text": question})
    history.append(
        {
            "role": "model",
            "text": json.dumps(answer.model_dump(), ensure_ascii=False),
        }
    )
    return answer


# ===============================================================
#  5-2. 올해의 흐름 — 대운 × 세운
#
#  [자리]  Step1 → Step2 → Step3 → **올해의 흐름** → 올해의 카드
#          Step 번호를 붙이지 않습니다. 1/3·2/3·3/3 구조는 그대로 두고,
#          그 뒤에 붙는 별도의 다리(bridge) 구간입니다.
#
#  [원칙] 대운·세운은 파이썬(daeun.py)이 계산합니다.
#         여기서 하는 일은 계산이 끝난 값을 프롬프트에 '그대로' 실어보내는 것뿐입니다.
#         Gemini 에게 간지를 뽑게 하거나 연도를 정하게 하지 않습니다.
#
#  [올해의 카드와의 관계]  이 답변은 카드 프롬프트에 넣지 않습니다.
#         카드는 예전 그대로 "계산값만"으로 만들어집니다. (정책 변경 없음)
# ===============================================================
YEAR_FLOW_TITLE = "할매가 올해의 큰 흐름까지 짚어주마"
YEAR_FLOW_SUBTITLE = "대운 × 세운"
# 성별을 고르지 않아 대운이 빠진 경우 — 제목에 없는 것을 적어두지 않습니다.
YEAR_FLOW_SUBTITLE_SEWOON = "올해의 세운"
YEAR_FLOW_BUTTON = "할매, 올해 흐름도 봐줘"
YEAR_FLOW_ERROR = "올해의 흐름을 계산하는 데 잠시 문제가 생겼단다."

# 흐름은 이야기라기보다 '정리'라, 1~3단계보다 조금 낮게 잡습니다.
YEAR_FLOW_TEMPERATURE = 0.7

YEAR_FLOW_TASK = """할매, 올해 흐름도 봐줘.

[이번에 할 일 — 올해의 흐름 (대운 × 세운)]
위 [CALCULATED_LUCK] 에 파이썬이 계산해둔 대운과 세운이 있다.
그 값을 해석해서, 이 사람의 올해를 큰 흐름으로 정리해주거라.

A. daeun_reading — 지금 지나고 있는 대운
   주어진 대운 간지의 큰 흐름 + 이 사람 원국(일간·오행·월령)과의 관계
B. sewoon_reading — 올해의 세운
   올해 특히 강해지는 흐름 + 그것이 원국과 만나는 방식
C. push / careful / concern_link — 대운과 세운이 만나는 지점
   밀어도 되는 방향 / 조심할 패턴 / 지금 고민과 연결되는 의미

[분량] 전체 합쳐 한글 900~1,400자.
   이 사람은 이미 1~3단계의 긴 글을 다 읽은 뒤다. 핵심만 정리해라.
   대운·세운이 무엇인지 설명하느라 분량을 늘리지 마라.
   앞 단계에서 이미 한 말을 다시 풀어 쓰지 마라.

[반드시 지킬 것]
- 간지와 연도 구간은 [CALCULATED_LUCK] 에 적힌 글자·숫자를 그대로 옮겨 적어라.
- 시기는 **나이가 아니라 연도**로 말하라. ("2017년부터 2026년까지" 처럼)
  나이는 만세력마다 한 해쯤 다를 수 있으니 "만 O세부터" 라고 단정하지 마라.
- 명리학적 해석이라는 점이 드러나게 써라.
  ("명리에서는 ~로 본다", "대운이 ~하면 ~로 해석한다")
- 어려운 말(대운·세운·비겁·관성 등)은 쓰자마자 바로 쉬운 말로 풀어줘라.

[금지]
- 대운·세운을 스스로 계산하거나, 주어진 것과 다른 간지·연도를 적는 것
- "올해 반드시 결혼한다", "몇 월에 취업한다" 같은 확정적인 사건·날짜 예측
- 올해 안의 특정 월·계절을 짚는 것 (월운 데이터는 주어지지 않았다)
- 질병·투자 종목·법률 판단을 단정하는 것
- 1~3단계에서 한 말을 표현만 바꿔 되풀이하는 것"""


def allowed_luck_pillars(daeun: dict | None, sewoon: dict) -> set[str]:
    """이 단계에서 할매가 적어도 되는 간지 — 파이썬이 계산해 넘겨준 것들.

    현재 대운과 올해 세운, 그리고 참고로 함께 넘긴 앞뒤 대운까지입니다.
    (프롬프트에 적어 보낸 값과 정확히 같은 목록이어야 합니다)
    """
    allowed = {sewoon["pillar"]}
    if daeun:
        current = daeun.get("current")
        allowed |= {
            period["pillar"] for period in daeun.get("periods", [])
            if current is None
            or abs(period["order"] - current["order"]) <= 1
        }
        allowed.add(daeun["month_pillar"])
    return allowed


# 대운이 없을 때(성별 미선택) — A 파트를 빼고 세운만 다룹니다.
# 없는 대운을 설명하려 들거나 "성별을 알려달라" 고 조르지 않게 못 박아둡니다.
YEAR_FLOW_TASK_SEWOON_ONLY = """할매, 올해 흐름도 봐줘.

[이번에 할 일 — 올해의 흐름 (세운)]
위 [CALCULATED_LUCK] 에 파이썬이 계산해둔 세운이 있다.
이번에는 대운이 주어지지 않았다. 세운만 가지고 이 사람의 올해를 정리해주거라.

A. daeun_reading — **빈 글자로 두어라.** (대운이 없으므로 아무것도 쓰지 마라)
B. sewoon_reading — 올해의 세운
   올해 특히 강해지는 흐름 + 그것이 원국(일간·오행·월령)과 만나는 방식
C. push / careful / concern_link — 올해 세운이 원국과 만나는 지점
   밀어도 되는 방향 / 조심할 패턴 / 지금 고민과 연결되는 의미

[분량] 전체 합쳐 한글 600~900자.
   이 사람은 이미 1~3단계의 긴 글을 다 읽은 뒤다. 핵심만 정리해라.
   대운이 빠진 만큼 세운 이야기를 억지로 늘리지 마라.

[반드시 지킬 것]
- 간지와 연도는 [CALCULATED_LUCK] 에 적힌 글자·숫자를 그대로 옮겨 적어라.
- 명리학적 해석이라는 점이 드러나게 써라.
- 어려운 말(세운·비겁·관성 등)은 쓰자마자 바로 쉬운 말로 풀어줘라.

[금지]
- 대운을 언급하는 것. 있다고 가정하거나 지어내는 것.
- 성별을 알려달라고 요구하거나, 성별이 없어 아쉽다고 말하는 것
  (그 안내는 화면이 이미 따로 하고 있다. 답변에서 되풀이하지 마라.)
- "올해 반드시 결혼한다", "몇 월에 취업한다" 같은 확정적인 사건·날짜 예측
- 올해 안의 특정 월·계절을 짚는 것 (월운 데이터는 주어지지 않았다)
- 질병·투자 종목·법률 판단을 단정하는 것
- 1~3단계에서 한 말을 표현만 바꿔 되풀이하는 것"""


def build_year_flow_prompt(
    answers: dict,
    saju: dict | None,
    astro: dict | None,
    daeun: dict | None,
    sewoon: dict,
    no_daeun_reason: str | None = None,
) -> str:
    """올해의 흐름 프롬프트.

    [들어가는 것]
        확정 명식(다시 못 박기) · 파이썬이 계산한 대운/세운 ·
        고민 분야 · 추가 질문 (이 둘은 '고민과 연결하라'는 요구사항 때문)
    [들어가지 않는 것]
        이름 · 생년월일 · 출생시간 · 출생지역
        (대운·세운은 이미 계산이 끝났으므로 원본 출생정보가 필요 없습니다)
    """
    from daeun import format_year_flow_for_prompt

    blocks = [
        _reanchor_block(saju, astro, answers).rstrip(),
        format_year_flow_for_prompt(daeun, sewoon, saju, no_daeun_reason),
        "[지금 이 사람의 고민]\n"
        f"- 고민 분야: {_as_text(answers.get('고민 분야'))}\n"
        f"- 추가 질문: {_as_text(answers.get('추가 질문'))}",
        YEAR_FLOW_TASK if daeun else YEAR_FLOW_TASK_SEWOON_ONLY,
    ]
    return "\n\n".join(blocks)


def build_year_flow_payload(
    answers: dict,
    saju: dict | None,
    astro: dict | None,
    daeun: dict | None,
    sewoon: dict,
    history: list | None = None,
    no_daeun_reason: str | None = None,
) -> dict:
    """Gemini 로 나가는 '올해의 흐름' 요청을 그대로 담은 dict.

    테스트는 Gemini 를 부르지 않고 이 dict 만 들여다보면 됩니다 —
    "대운/세운 값이 파이썬 계산값 그대로인가",
    "모델에게 계산을 시키는 문장이 없는가" 를 API 호출 없이 확인할 수 있습니다.
    """
    question = build_year_flow_prompt(
        answers, saju, astro, daeun, sewoon, no_daeun_reason
    )
    contents = [
        {"role": turn["role"], "parts": [{"text": turn["text"]}]}
        for turn in (history or [])
    ]
    contents.append({"role": "user", "parts": [{"text": question}]})
    return {
        "system_instruction": YEAR_FLOW_SYSTEM_INSTRUCTION,
        "contents": contents,
        "temperature": YEAR_FLOW_TEMPERATURE,
        "question": question,
    }


def ask_year_flow(
    answers: dict,
    saju: dict | None,
    astro: dict | None,
    daeun: dict | None,
    sewoon: dict,
    history: list | None = None,
    *,
    no_daeun_reason: str | None = None,
    api_key: str | None = None,
) -> YearFlowAnswer:
    """올해의 흐름 한 덩어리를 받아옵니다.

    대운·세운은 이미 계산이 끝난 값으로 넘어갑니다.
    Gemini 는 그 값을 해석만 하고, 간지나 시기를 새로 만들지 않습니다.

    앞선 1~3단계 대화(history)를 함께 보내는 이유는 딱 하나 —
    앞에서 한 말을 되풀이하지 않게 하기 위해서입니다.
    (올해의 카드는 반대로 대화를 절대 넘기지 않습니다. 정책이 다릅니다)
    """
    # --- Mock 모드: Gemini 를 부르지 않고 미리 만들어둔 답을 씁니다 ---
    if USE_MOCK_AI:
        from mock_ai import MOCK_DELAY_SECONDS, mock_year_flow

        sleep(MOCK_DELAY_SECONDS)
        logger.info("올해의 흐름 Mock 응답 사용 · Gemini 호출 없음")
        return mock_year_flow(answers, saju, daeun, sewoon)

    client = get_client(api_key)
    payload = build_year_flow_payload(
        answers, saju, astro, daeun, sewoon, history, no_daeun_reason
    )

    config = types.GenerateContentConfig(
        system_instruction=payload["system_instruction"],
        response_mime_type="application/json",
        response_schema=YearFlowAnswer,
        max_output_tokens=MAX_OUTPUT_TOKENS,
        temperature=payload["temperature"],
    )

    try:
        response = _generate_with_retry(client, payload["contents"], config)
    except genai_errors.ClientError as exc:
        if exc.code == 429:
            raise HalmaeError(
                "지금은 요청이 너무 많아 할매가 잠시 쉬고 있어요. "
                "1~2분 뒤에 다시 시도해주세요."
            ) from exc
        if exc.code in (401, 403) or "api key" in str(exc).lower():
            logger.error(
                "Gemini 인증 실패 (코드 %s) — GEMINI_API_KEY 값과 권한을 확인하세요.",
                exc.code,
            )
            raise HalmaeError(
                "할매가 지금은 답을 할 수 없는 상태예요. "
                "잠시 뒤에 다시 시도해주세요."
            ) from exc
        raise HalmaeError(
            f"요청을 보내는 중 문제가 생겼어요. (오류 코드 {exc.code})"
        ) from exc
    except genai_errors.ServerError as exc:
        raise HalmaeError(
            "할매가 잠시 자리를 비웠어요. 잠시 뒤에 다시 시도해주세요."
        ) from exc
    except HalmaeError:
        raise
    except Exception as exc:
        raise HalmaeError(
            "올해의 흐름을 받아오지 못했어요. "
            "인터넷 연결을 확인한 뒤 다시 시도해주세요."
        ) from exc

    answer = _parse_answer(response, YearFlowAnswer)

    # 대운이 없으면 A 파트는 무조건 비웁니다.
    # 프롬프트로도 막아두었지만, 모델이 굳이 써넣었을 때 화면에
    # 계산하지 않은 대운 이야기가 뜨는 일만은 없어야 합니다.
    if not daeun:
        answer.daeun_reading = ""

    # 할매가 확정값을 바꿔 말했는지 (1~3단계와 같은 검사).
    # 이 단계에서는 대운·세운 간지도 '확정값' 이라 어긋난 것으로 세지 않습니다.
    contradictions = find_saju_contradictions(
        answer, saju, allowed_luck_pillars(daeun, sewoon)
    )
    if contradictions:
        logger.warning(
            "올해의 흐름 — 확정 명식에 없는 간지를 %d군데에서 말했습니다. "
            "화면 값은 파이썬 계산값이라 영향은 없지만 프롬프트 점검 필요.",
            len(contradictions),
        )

    # 운영 로그에는 글 내용을 남기지 않습니다. 길이와 토큰 수만 남깁니다.
    usage = getattr(response, "usage_metadata", None)
    if usage is not None:
        logger.info(
            "올해의 흐름 완료 · 모델 %s · 입력 %s토큰 / 출력 %s토큰 · %d자",
            GEMINI_MODEL,
            getattr(usage, "prompt_token_count", "?"),
            getattr(usage, "candidates_token_count", "?"),
            answer_length(answer),
        )
    return answer


# ===============================================================
#  6. 올해의 카드
#
#  [정책] 카드는 "같은 사람 + 같은 출생정보 + 같은 해"에 딱 한 장입니다.
#  어떤 고민(연애·취업·돈·인간관계·삶의 방향)으로 들어와도 같은 카드입니다.
#
#  그래서 이 구역의 프롬프트에는 아래가 들어가지 않습니다.
#      고민 분야 · 추가 질문 · Step1/2/3 응답 · 고민 해석 텍스트 ·
#      Premium 관련 내용 · 1~3단계 대화 이력
#  들어가는 것은 계산이 끝난 값뿐입니다.
#      사주(년·월·일·시주 · 일간 · 오행) · 점성술(Sun · Moon · Ascendant) ·
#      올해 연도와 그 해의 간지
# ===============================================================
# 카드는 "같은 사람이면 늘 같은 카드"여야 하므로 온도를 낮춥니다.
# (1~3단계는 이야기라 다양해도 좋지만, 카드는 흔들리면 믿음이 가지 않습니다.)
YEAR_CARD_TEMPERATURE = 0.3


def build_year_card_task() -> str:
    """올해의 카드를 뽑아달라는 지시문. (사람마다 달라지지 않는 고정 글)"""
    return """[이번에 할 일 — 올해의 카드 한 장]
위 확정 명식·점성술 값과 올해 기운만 가지고,
이 사람의 올해를 카드 한 장으로 압축해주거라.

[이 카드가 무엇인지]
이 카드는 "지금 무엇을 물었는가"에 대한 답이 아니다.
이 사람이 올해 한 해 전반에 걸쳐 가져가야 할 '하나의 테마'다.
연애로 물어도, 취업으로 물어도, 돈으로 물어도 같은 카드가 나와야 한다.

[가장 중요한 규칙]
카드는 짧아야 한다. 저장해두거나 남에게 보여주고 싶을 만큼 간결해야 한다.
길게 쓰면 카드가 아니라 또 하나의 보고서가 된다. 딱 한 가지로 좁혀라.

- title    : 영문 대문자 두세 단어 (THE ~). 이 사람의 올해를 한 장면으로.
- keyword  : 한글 한 단어
- message  : 할매 말투 한 문장, 40자 안팎
- basis    : 왜 이 카드인지. 올해 간지와 이 사람 사주/점성술을 연결해 150자 안팎
- actions  : 올해 가장 중요한 행동 원칙 1~2개 (3개 이상 금지)
- caution  : 조심할 패턴 딱 1개
- visual_theme : 이 카드에 들어갈 그림의 주제. 아래 여덟 개 중 딱 하나

[그림 주제(visual_theme) 고르는 법 — 반드시 지킬 것]
이 카드는 타로 카드처럼 가운데에 그림이 한 장 들어간다.
아래 여덟 개 중, 위에서 정한 카드의 핵심 테마와 가장 잘 맞는 것 하나만 골라라.
""" + prompt_choices() + """
- 반드시 왼쪽에 적힌 영문 낱말 그대로 적어라. (예: breakthrough)
- 새로 지어내거나 두 개를 고르거나 문장으로 설명하지 마라.
- 사주·점성술·올해 간지만 보고 골라라.
  고민 분야는 주어지지 않았다. 짐작해서 고르지 마라.

[행동 원칙(actions) 쓰는 법 — 반드시 지킬 것]
여러 삶의 영역에 그대로 옮겨 쓸 수 있는 수준의 원칙으로 쓴다.
  좋은 예: 판단을 오래 미루고 있다면 가장 작은 행동 하나부터 실행하거라
  좋은 예: 새로운 환경이나 사람에 노출되는 횟수를 지금보다 늘리거라
  좋은 예: 반복해서 미뤄온 결정 하나를 이번 달에 매듭지어라
  나쁜 예: 이력서를 고쳐 써라 / 현업 실무자에게 연락해라 (취업 전용)
  나쁜 예: 소개팅에 나가라 / 먼저 연락해라 (연애 전용)
  나쁜 예: 적립식으로 투자를 시작해라 (돈 전용)
구체적이어야 하지만, 특정 고민 분야에만 맞는 행동이면 안 된다.

[금지]
- 이 사람의 고민 분야·질문을 짐작해서 답하는 것
  (고민 정보는 주어지지 않았다. 없는 것을 있다고 여기고 쓰지 마라.)
- 취업 · 연애 · 재테크 · 이직 · 결혼 같은 특정 영역 전용 조언
- 올해 안의 특정 월이나 날짜를 짚어 예언하는 것
  (월별 운세 데이터는 주어지지 않았다. 위 간지 말고 다른 시점 정보를 지어내지 마라.)
- "새로운 도전을 하라" 같은 누구에게나 되는 말
- 사용자의 이름을 카드 안에 적는 것
  (카드는 저장해두고 남에게 보여주는 것이라 이름이 들어가면 안 된다.
   부를 일이 있으면 "너"라고만 하거라.)"""


def build_year_luck_block(year_ganji: dict, notes: list[str]) -> str:
    """파이썬이 계산한 올해 간지를 프롬프트용 글로 만듭니다."""
    lines = [
        "[올해의 기운 — Python에서 계산 완료. 다시 계산하지 말 것]",
        f"- 올해(사주 기준, 입춘 이후): {year_ganji['연도']}년 "
        f"{year_ganji['한글']}({year_ganji['한자']}) · {year_ganji['띠']}띠",
        f"- 올해 천간의 오행: {year_ganji['천간 오행']} / "
        f"지지의 오행: {year_ganji['지지 오행']}",
        "- 이 사람 사주와 견주어 눈에 띄는 점:",
    ]
    lines.extend(f"    · {note}" for note in notes)
    return "\n".join(lines)


def build_year_card_prompt(
    saju: dict | None,
    astro: dict | None,
    year_ganji: dict,
    year_notes: list[str],
) -> str:
    """올해의 카드 프롬프트 — 이 한 덩이로 완결됩니다.

    [왜 1~3단계 대화를 이어받지 않는가]
        예전에는 1~3단계 대화(history)를 통째로 함께 보냈습니다.
        그 대화 안에는 고민 분야 · 추가 질문 · Step1~3 답변이 들어 있어서,
        커리어 고민으로 만든 카드에 "이력서" 같은 취업 전용 행동이 박혔습니다.
        stable_key 는 고민과 무관하므로, 그 카드가 나중에 연애로 들어온
        같은 사람에게 그대로 재사용되었습니다.

        그래서 카드는 대화를 이어받지 않고, 계산 결과만으로 새로 묻습니다.
        같은 사람·같은 해라면 프롬프트가 한 글자도 다르지 않습니다.

    [들어가는 것]  확정 사주 명식 · 점성술 값 · 올해 간지와 연간 정보
    [들어가지 않는 것]
        고민 분야 · 추가 질문 · Step1/2/3 응답 · 고민 해석 텍스트 ·
        Premium 관련 내용 · 이름
    """
    from astrology import format_astrology_for_prompt
    from saju import format_saju_for_prompt

    blocks = ["할매, 올해 제 카드는 뭔가요?"]

    if saju:
        blocks.append(format_saju_for_prompt(saju))
    else:
        blocks.append(
            "[사주 명식]\n계산하지 못했다. 사주를 근거로 든 해석은 하지 말 것."
        )

    if astro:
        blocks.append(format_astrology_for_prompt(astro))
    else:
        blocks.append(
            "[점성술 데이터]\n계산하지 못했다. 점성술을 근거로 든 해석은 하지 말 것."
        )

    blocks.append(build_year_luck_block(year_ganji, year_notes))
    blocks.append(build_year_card_task())

    return "\n\n".join(blocks)


def build_year_card_payload(
    saju: dict | None,
    astro: dict | None,
    year_ganji: dict,
    year_notes: list[str],
) -> dict:
    """Gemini 로 나가는 카드 요청을 그대로 담은 dict.

    ask_year_card() 는 이 dict 를 그대로 보냅니다.
    테스트는 Gemini 를 부르지 않고 이 dict 만 비교하면 됩니다 —
    "커리어로 들어온 사람과 연애로 들어온 사람의 요청이 같은가"를
    API 호출 없이 확인할 수 있습니다. (test_year_card_payload.py)
    """
    question = build_year_card_prompt(saju, astro, year_ganji, year_notes)
    return {
        "system_instruction": YEAR_CARD_SYSTEM_INSTRUCTION,
        "contents": [{"role": "user", "parts": [{"text": question}]}],
        "temperature": YEAR_CARD_TEMPERATURE,
    }


def ask_year_card(
    saju: dict | None,
    astro: dict | None,
    year_ganji: dict,
    year_notes: list[str],
    *,
    api_key: str | None = None,
) -> YearCard:
    """올해의 카드 한 장을 받아옵니다.

    1~3단계 대화는 일부러 넘기지 않습니다. (build_year_card_prompt 의 설명 참고)
    같은 사람·같은 해라면 어떤 고민으로 들어와도 똑같은 요청이 나갑니다.

    연도는 Gemini 가 지어내지 못하도록, 받아온 뒤 파이썬 계산값으로 덮어씁니다.
    """
    # --- Mock 모드: Gemini 를 부르지 않고 미리 만들어둔 카드를 씁니다 ---
    if USE_MOCK_AI:
        from mock_ai import MOCK_DELAY_SECONDS, mock_year_card

        sleep(MOCK_DELAY_SECONDS)
        card = mock_year_card(year_ganji["연도"], year_ganji)
        logger.info("올해의 카드 Mock 응답 사용 · Gemini 호출 없음")
        return card

    client = get_client(api_key)
    payload = build_year_card_payload(saju, astro, year_ganji, year_notes)

    config = types.GenerateContentConfig(
        system_instruction=payload["system_instruction"],
        response_mime_type="application/json",
        # image_url 은 스키마에 넣지 않습니다 — 넣으면 모델이 주소를 지어냅니다.
        response_schema=YearCardDraft,
        max_output_tokens=MAX_OUTPUT_TOKENS,
        temperature=payload["temperature"],
    )

    try:
        response = _generate_with_retry(client, payload["contents"], config)
    except genai_errors.ClientError as exc:
        if exc.code == 429:
            raise HalmaeError(
                "지금은 요청이 너무 많아 할매가 잠시 쉬고 있어요. "
                "1~2분 뒤에 다시 시도해주세요."
            ) from exc
        if exc.code in (401, 403) or "api key" in str(exc).lower():
            # 사용자는 API 키를 모릅니다. 원인은 개발 로그에만 남깁니다.
            logger.error(
                "Gemini 인증 실패 (코드 %s) — GEMINI_API_KEY 값과 권한을 확인하세요.",
                exc.code,
            )
            raise HalmaeError(
                "할매가 지금은 답을 할 수 없는 상태예요. "
                "잠시 뒤에 다시 시도해주세요."
            ) from exc
        raise HalmaeError(
            f"요청을 보내는 중 문제가 생겼어요. (오류 코드 {exc.code})"
        ) from exc
    except genai_errors.ServerError as exc:
        raise HalmaeError(
            "할매가 잠시 자리를 비웠어요. 잠시 뒤에 다시 시도해주세요."
        ) from exc
    except HalmaeError:
        raise
    except Exception as exc:
        raise HalmaeError(
            "카드를 받아오지 못했어요. 인터넷 연결을 확인한 뒤 다시 시도해주세요."
        ) from exc

    draft = _parse_answer(response, YearCardDraft)
    # 그림 주소는 아직 없습니다. (다음 단계에서 image_url 을 채워 넣습니다)
    card = YearCard.model_validate(draft.model_dump())

    # 연도는 파이썬이 계산한 값이 정답입니다. (모델이 다른 해를 적었어도 바로잡습니다)
    card.year = year_ganji["연도"]
    # 행동은 최대 2개까지만 (카드가 길어지지 않게)
    card.actions = [a for a in card.actions if a.strip()][:2]

    # 운영 로그에는 카드 '글'을 남기지 않습니다.
    # 제목·키워드는 그 사람의 사주로 지어진 문구라 Gemini 응답 본문에 해당합니다.
    # (내용을 봐야 할 때는 개발자 모드 화면이나 test_year_card_payload.py 를 씁니다)
    logger.info(
        "올해의 카드 완료 · 모델 %s · %d년 카드 · 행동 %d개 · 그림 %s",
        GEMINI_MODEL, card.year, len(card.actions), card.visual_theme.value,
    )
    return card


def format_year_card_text(card: YearCard, year_ganji: dict | None = None) -> str:
    """카드를 복사해서 공유할 수 있는 짧은 글로 만듭니다."""
    lines = [
        f"{card.year} 올해의 카드",
        card.title,
        f"키워드: {card.keyword}",
        "",
        f'"{card.message}"',
    ]
    if year_ganji:
        lines.append("")
        lines.append(f"— 할매 · {year_ganji['한글']}년 {year_ganji['띠']}띠")
    return "\n".join(lines)


def answer_length(answer: BaseModel) -> int:
    """답변에 들어있는 글자 수 (분량 확인용)."""

    def walk(value) -> int:
        if isinstance(value, str):
            return len(value)
        if isinstance(value, dict):
            return sum(walk(v) for v in value.values())
        if isinstance(value, list):
            return sum(walk(v) for v in value)
        return 0

    return walk(answer.model_dump())


# ---------------------------------------------------------------
#  터미널에서 1~3단계를 실제로 불러보기 (API 를 씁니다)
#      python halmae_ai.py
# ---------------------------------------------------------------
if __name__ == "__main__":
    from datetime import date as _date
    from datetime import time as _time

    from astrology import compute_astrology
    from saju import compute_saju

    demo_answers = {
        "이름": "안혜진",
        "달력 유형": "양력",
        "생년월일": _date(1999, 4, 13),
        "평달/윤달": None,
        "출생시간": _time(8, 49),
        "출생시간 모름": False,
        "출생지역": "서울",
        "성별": "여성",
        "고민 분야": "취업/커리어",
        "추가 질문": "지금 회사에서 3년째인데, 올해 안에 이직해도 괜찮을까요?",
    }

    demo_saju = compute_saju(
        demo_answers["생년월일"], demo_answers["출생시간"], "양력",
        birth_place=demo_answers["출생지역"],
    )
    demo_astro = compute_astrology(
        demo_answers["생년월일"], demo_answers["출생시간"],
        demo_answers["출생지역"], "양력",
    )

    demo_history: list = []
    for demo_step in (1, 2, 3):
        print("=" * 60)
        print(f"[{demo_step}단계] {STEP_TITLES[demo_step]}")
        print("=" * 60)
        demo_answer = ask_halmae(
            demo_step, demo_answers, demo_history, demo_saju, demo_astro
        )
        print(json.dumps(demo_answer.model_dump(), ensure_ascii=False, indent=2))
        print(f"\n>>> 글자 수: {answer_length(demo_answer)}자\n")
