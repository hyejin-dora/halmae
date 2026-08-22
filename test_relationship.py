"""연애·관계 — 관계 상태 검증 (Gemini 호출 없음 · Supabase 쓰기 없음)

    python test_relationship.py

[무엇을 고치려고 만든 기능인가]
    고민 분야가 "연애" 하나뿐이던 시절, 할매(Gemini)는 사용자를 솔로라고
    짐작하고 "소개팅에 나가라", "새로운 사람을 만나보라" 같은 조언을 했습니다.
    기혼인 사람에게는 쓸모없다 못해 무례한 말이 됩니다.

    그래서 관계 상태를 '추측 대상'에서 '사용자가 고르는 확정 입력값'으로
    옮겼습니다. 이 파일은 그 경계가 새지 않는지 확인합니다.

확인하는 것
    1. 고민 분야가 "연애·관계" 로 바뀌었는지
    2. 그 분야를 골랐을 때만 관계 상태를 묻는지 (조건부 UI)
    3. 관계 상태가 별도 값으로 관리되는지
    4. Step1/2/3 · 올해의 흐름 프롬프트에 관계 상태가 실려 나가는지
    5. 상태마다 해석 정책이 제대로 붙는지
    6. Gemini 가 다른 상태를 지어내지 못하게 막았는지
    7. "말하고 싶지 않아요" 일 때 아무것도 추측하지 않는지
    8. 올해의 카드 정책이 그대로인지 (열쇠·프롬프트에 관계 상태 없음)
    9. 관계 상태가 행동 로그에 저장되지 않는지

여기 쓰는 값은 전부 개발용 예시입니다. 실제 사용자 정보가 아닙니다.
"""

import ast
import sys
from datetime import date, time

import analytics
import card_store
import halmae_ai
from halmae_ai import (
    RELATIONSHIP_CONCERN,
    RELATIONSHIP_CONTEXT_KEY,
    RELATIONSHIP_LOCK_RULES,
    RELATIONSHIP_OPTIONS,
    RELATIONSHIP_POLICIES,
    RELATIONSHIP_QUESTION,
    RELATIONSHIP_UNKNOWN,
    build_prompt,
    build_relationship_block,
    build_year_card_prompt,
    build_year_flow_prompt,
    relationship_context,
)
from saju import compute_saju, compute_year_ganji

_failures: list[str] = []

APP_SOURCE = open("app.py", encoding="utf-8").read()
APP_TREE = ast.parse(APP_SOURCE)


def section(title: str) -> None:
    print()
    print(f"[{title}]")


def check(label: str, ok: bool, detail: str = "") -> None:
    print(f"  [{'PASS' if ok else 'FAIL'}] {label}"
          + (f"  — {detail}" if detail else ""))
    if not ok:
        _failures.append(label)


class _NameResolver(ast.NodeTransformer):
    """app.py 상수 안에 쓰인 이름(RELATIONSHIP_CONCERN 등)을 실제 값으로 바꿉니다.

    CONCERN_OPTIONS 처럼 다른 파일의 상수를 끼워 쓴 목록도 읽을 수 있게
    하려고 둡니다. (앱을 import 하면 Streamlit 이 통째로 도니까요)
    """

    def visit_Name(self, node):                       # noqa: N802
        if hasattr(halmae_ai, node.id):
            return ast.Constant(value=getattr(halmae_ai, node.id))
        return node


def app_literal(name: str):
    """app.py 에 적힌 상수 값을 그대로 읽어옵니다."""
    for node in ast.walk(APP_TREE):
        if (isinstance(node, ast.Assign)
                and any(getattr(target, "id", "") == name
                        for target in node.targets)):
            resolved = _NameResolver().visit(ast.parse(ast.unparse(node.value),
                                                       mode="eval"))
            return ast.literal_eval(ast.fix_missing_locations(resolved))
    return None


# ---------------------------------------------------------------
#  개발용 예시 (fixture)
# ---------------------------------------------------------------
BASE = {
    "이름": "예시",
    "생년월일": date(1990, 5, 5),
    "출생시간": time(9, 30),
    "출생시간 모름": False,
    "달력 유형": "양력",
    "평달/윤달": None,
    "출생지역": "서울",
    "성별": "여성",
    "추가 질문": "요즘 자꾸 어긋나는 것 같아요",
}
SAJU = compute_saju(BASE["생년월일"], BASE["출생시간"], "양력")
# 카드 열쇠에 필요한 값만 담은 별자리 결과 (좌표 · 세 별자리)
ASTRO = {"latitude": 37.5665, "longitude": 126.978,
         "sun_sign": "Taurus", "moon_sign": "Leo", "rising_sign": "Cancer"}

# 프롬프트 검사에는 별자리를 넣지 않습니다.
#     format_astrology_for_prompt() 는 계산이 끝난 dict 전체를 요구하는데,
#     관계 상태는 별자리와 아무 상관이 없어서 굳이 인터넷에 나갈 이유가 없습니다.
#     (별자리 블록 자체는 test_saju_pipeline.py 가 따로 확인합니다)
PROMPT_ASTRO = None


def love(state: str | None) -> dict:
    """연애·관계 + 관계 상태 조합의 입력값."""
    return {**BASE, "고민 분야": RELATIONSHIP_CONCERN,
            RELATIONSHIP_CONTEXT_KEY: state}


def other(concern: str = "돈") -> dict:
    """연애가 아닌 다른 고민. (관계 상태 값이 남아 있어도 쓰이면 안 됩니다)"""
    return {**BASE, "고민 분야": concern,
            RELATIONSHIP_CONTEXT_KEY: "기혼·부부·가정"}


# ===============================================================
def check_options() -> None:
    section("1. 고민 분야와 선택지")

    options = app_literal("CONCERN_OPTIONS")
    check("고민 분야가 '연애·관계' 로 바뀌었다",
          RELATIONSHIP_CONCERN == "연애·관계"
          and options is not None
          and RELATIONSHIP_CONCERN in options,
          str(options))
    check("예전 '연애' 라는 이름은 선택지에 남아 있지 않다",
          options is not None and "연애" not in options)
    # "취업/커리어" → "일·커리어" 로 이름이 넓어졌습니다.
    # (취업 준비만의 칸이 아니라 재직·이직·직무 전환까지 담는 칸)
    check("나머지 고민 분야는 그대로다",
          options is not None
          and options[1:] == ["일·커리어", "돈", "인간관계", "삶의 방향", "기타"],
          str(options[1:] if options else None))

    check("관계 상태 선택지가 네 개다",
          RELATIONSHIP_OPTIONS == ["솔로·새 인연", "썸·연애중",
                                   "기혼·부부·가정", "말하고 싶지 않아요"],
          str(RELATIONSHIP_OPTIONS))
    check("질문 문구가 정해져 있다",
          RELATIONSHIP_QUESTION == "현재 관계 상태를 알려주세요.",
          RELATIONSHIP_QUESTION)
    check("선택지마다 해석 정책이 하나씩 있다",
          set(RELATIONSHIP_POLICIES) == set(RELATIONSHIP_OPTIONS))


# ===============================================================
def check_conditional_ui() -> None:
    section("2. 조건부 UI — 연애·관계를 골랐을 때만 묻는다")

    body = APP_SOURCE.split("def render_input()")[1].split("\ndef ")[0]

    concern_at = body.find('key="in_concern"')
    relationship_at = body.find('key="in_relationship"')
    check("관계 상태 질문이 고민 분야 바로 다음에 있다",
          0 < concern_at < relationship_at,
          f"고민 {concern_at} · 관계 {relationship_at}")

    check("연애·관계일 때만 질문을 그린다",
          "if concern == RELATIONSHIP_CONCERN:" in body)

    # if 문 안쪽에서만 위젯이 그려지는지 (구문 트리로 확인)
    render_input = next(
        node for node in ast.walk(APP_TREE)
        if isinstance(node, ast.FunctionDef) and node.name == "render_input"
    )
    guarded = False
    for node in ast.walk(render_input):
        if not isinstance(node, ast.If):
            continue
        if "RELATIONSHIP_CONCERN" not in ast.unparse(node.test):
            continue
        if "in_relationship" in ast.unparse(node.body):
            guarded = True
    check("관계 상태 위젯이 조건문 '안'에 있다 (다른 고민에서는 그려지지 않음)",
          guarded)

    check("미리 골라두지 않는다 (index=None)",
          "index=None," in body.split('key="in_relationship"')[0][-300:])

    note = app_literal("RELATIONSHIP_FIELD_NOTE")
    check("질문 아래 짧은 안내가 있다", bool(note), str(note))
    check("안내가 '안 골라도 된다' 는 걸 알려준다",
          note is not None and "넘겨짚지" in note)
    check("안내는 경고 상자가 아니라 halmae-fieldnote 다",
          'class="halmae-fieldnote"' in body)

    # 제출할 때 담기는 규칙
    submit = body.split("st.session_state.answers = {")[1].split("}")[0]
    check("관계 상태를 별도 칸으로 담는다",
          "RELATIONSHIP_CONTEXT_KEY:" in submit)
    check("연애·관계가 아니면 담지 않는다 (None)",
          "if concern == RELATIONSHIP_CONCERN else None" in submit)
    check("비워둔 채 제출하면 '말하고 싶지 않아요' 로 본다",
          "RELATIONSHIP_UNKNOWN" in submit)


# ===============================================================
def check_context_value() -> None:
    section("3. 관계 상태 값 다루기")

    for state in RELATIONSHIP_OPTIONS:
        check(f"'{state}' 를 그대로 돌려준다",
              relationship_context(love(state)) == state)

    check("연애·관계가 아니면 None (값이 남아 있어도 쓰지 않는다)",
          relationship_context(other()) is None)
    check("고민 분야가 없으면 None", relationship_context({}) is None)
    check("빈 값이면 '말하고 싶지 않아요' 로 본다 (솔로로 넘겨짚지 않음)",
          relationship_context(love(None)) == RELATIONSHIP_UNKNOWN
          and relationship_context(love("")) == RELATIONSHIP_UNKNOWN)
    check("모르는 값이 들어와도 추측하지 않는다",
          relationship_context(love("아무거나")) == RELATIONSHIP_UNKNOWN)


# ===============================================================
def check_prompt_carries_state() -> None:
    section("4. Step1/2/3 · 올해의 흐름 프롬프트에 실려 나가는지")

    for state in RELATIONSHIP_OPTIONS:
        answers = love(state)
        for step in (1, 2, 3):
            prompt = build_prompt(step, answers, SAJU, PROMPT_ASTRO)
            check(f"Step{step} · '{state}' 가 프롬프트에 있다",
                  "[관계 상태" in prompt and state in prompt)

    # 올해의 흐름에도 같은 값이 붙는지
    sewoon = {"year": 2026, "pillar": "병오", "pillar_hanja": "丙午",
              "stem_ohaeng": "화", "branch_ohaeng": "화", "animal": "말",
              "ganji": compute_year_ganji(date(2026, 6, 1))}
    flow = build_year_flow_prompt(love("기혼·부부·가정"), SAJU, PROMPT_ASTRO,
                                  None, sewoon)
    check("올해의 흐름에도 관계 상태가 붙는다",
          "[관계 상태" in flow and "기혼·부부·가정" in flow)

    # 다른 고민에는 붙지 않아야 합니다
    for concern in ("일·커리어", "돈", "인간관계", "삶의 방향", "기타"):
        answers = other(concern)
        blank = all("[관계 상태" not in build_prompt(step, answers, SAJU, PROMPT_ASTRO)
                    for step in (1, 2, 3))
        check(f"'{concern}' 고민에는 관계 상태가 붙지 않는다", blank)

    check("관계 상태 블록은 build_relationship_block 한 곳에서만 만든다",
          build_relationship_block(other()) == ""
          and "[관계 상태" in build_relationship_block(love("썸·연애중")))


# ===============================================================
def check_policies() -> None:
    section("5. 상태별 해석 정책")

    wanted = {
        "솔로·새 인연": ["새로운 관계", "사람을 만나는 방식", "패턴"],
        "썸·연애중": ["지금 곁에 있는 상대", "소통", "갈등"],
        "기혼·부부·가정": ["배우자", "가정", "새로운 인연을 찾으라는 조언은"],
        RELATIONSHIP_UNKNOWN: ["어느 쪽도 추측하지 마라", "성향", "행동 패턴"],
    }
    for state, words in wanted.items():
        policy = RELATIONSHIP_POLICIES[state]
        for word in words:
            check(f"'{state}' 정책에 '{word}' 가 있다", word in policy)

    # 정책 글이 실제로 프롬프트에 붙는지
    for state in RELATIONSHIP_OPTIONS:
        prompt = build_prompt(1, love(state), SAJU, PROMPT_ASTRO)
        check(f"'{state}' 정책 문장이 프롬프트에 그대로 들어간다",
              RELATIONSHIP_POLICIES[state][:24] in prompt)


# ===============================================================
def check_no_assumption() -> None:
    section("6. 다른 상태를 지어내지 못하게 막았는지")

    for rule in ("사용자가 직접 고른 확정값이다",
                 "다른 상태를 가정하지 마라",
                 "상태를 짐작하게 하는 표현을 쓰지 마라",
                 "사주·점성술 값으로 관계 상태를 역추적하려 하지 마라"):
        check(f"잠금 규칙에 '{rule}' 이 있다", rule in RELATIONSHIP_LOCK_RULES)

    check("3단계 행동 지령을 특히 조심하라고 못 박는다",
          "행동 지령(3단계)" in RELATIONSHIP_LOCK_RULES
          and "소개팅에 나가라" in RELATIONSHIP_LOCK_RULES)

    # 추가 질문과 어긋날 때의 규칙 (요구사항 6)
    check("추가 질문에 상황이 분명하면 참고하라고 적혀 있다",
          "추가 질문에 관계 상황이 분명하게 적혀 있으면" in RELATIONSHIP_LOCK_RULES)
    check("분명하지 않으면 단정하지 말라고 적혀 있다",
          "분명하지 않으면 특정 상태로 단정하지 말고" in RELATIONSHIP_LOCK_RULES)

    # 기혼에게 금지되는 말이 정책에 분명히 적혀 있는지
    married = RELATIONSHIP_POLICIES["기혼·부부·가정"]
    for banned in ("소개팅", "새로운 만남", "이별"):
        check(f"기혼 정책이 '{banned}' 을 금지한다", banned in married)

    # 모든 단계에서 잠금 규칙이 함께 나가는지 (2·3단계에서 흐려지지 않게)
    for step in (1, 2, 3):
        prompt = build_prompt(step, love("기혼·부부·가정"), SAJU, PROMPT_ASTRO)
        check(f"Step{step} 에 잠금 규칙이 함께 나간다",
              "다른 상태를 가정하지 마라" in prompt)


# ===============================================================
def check_unknown_state() -> None:
    section("7. '말하고 싶지 않아요' — 아무것도 추측하지 않기")

    policy = RELATIONSHIP_POLICIES[RELATIONSHIP_UNKNOWN]
    prompt = build_prompt(1, love(RELATIONSHIP_UNKNOWN), SAJU, PROMPT_ASTRO)

    check("솔로·연애중·기혼 어느 쪽도 추측하지 말라고 적혀 있다",
          "솔로인지" in policy and "사귀는 중인지" in policy
          and "결혼했는지" in policy and "어느 쪽도 추측하지 마라" in policy)
    check("관계 전반의 성향·행동 패턴만 보라고 적혀 있다",
          "관계 전반에서 나타나는 성향" in policy
          and "되풀이되는 행동 패턴만 해석하라" in policy)
    check("상태를 전제로 한 행동을 지령으로 내지 말라고 적혀 있다",
          "소개팅·고백·프러포즈·이혼" in policy)
    check("상태를 드러내는 낱말 대신 중립적인 말을 쓰라고 알려준다",
          "'연인', '배우자', '솔로', '애인'" in policy
          and "가까운 사람" in policy)
    check("이 정책이 실제 프롬프트에 들어간다",
          "어느 쪽도 추측하지 마라" in prompt)

    # 프롬프트 어디에도 특정 상태를 단정하는 말이 없어야 합니다
    context_block = prompt.split("[관계 상태")[1].split("[사주 명식")[0]
    for word in ("솔로다", "연애 중이다", "기혼이다"):
        check(f"프롬프트가 '{word}' 라고 단정하지 않는다", word not in context_block)


# ===============================================================
def check_year_card_untouched() -> None:
    section("8. 올해의 카드 정책 — 관계 상태와 무관")

    year_ganji = compute_year_ganji(date(2026, 6, 1))

    keys = {
        state: card_store.build_card_key(love(state), SAJU, ASTRO, 2026)
        for state in RELATIONSHIP_OPTIONS
    }
    keys["다른 고민"] = card_store.build_card_key(other(), SAJU, ASTRO, 2026)

    unique = set(keys.values())
    check("관계 상태가 달라도 카드 열쇠가 같다", len(unique) == 1,
          " / ".join(f"{k}={v[:8]}" for k, v in keys.items()))

    fingerprint = card_store.build_card_fingerprint(
        love("기혼·부부·가정"), SAJU, ASTRO, 2026
    )
    for word in ("기혼", "솔로", "관계", "연애"):
        check(f"카드 지문에 '{word}' 가 없다", word not in fingerprint)

    # 카드 프롬프트에는 원래부터 "연애 전용 조언을 쓰지 마라" 같은 문장이
    # 들어 있습니다. 그건 금지 규칙이라 그대로 두고, 이 사람의 '관계 상태'가
    # 새어 들어가지 않았는지만 봅니다.
    card_prompt = build_year_card_prompt(SAJU, PROMPT_ASTRO, year_ganji, [])
    for word in ["관계 상태", "배우자"] + RELATIONSHIP_OPTIONS:
        check(f"카드 프롬프트에 '{word}' 가 없다", word not in card_prompt)

    # 카드 준비 코드가 관계 상태를 읽지 않는지
    card_body = APP_SOURCE.split("def ensure_year_card()")[1].split("\ndef ")[0]
    code = "\n".join(line for line in card_body.splitlines()
                     if not line.strip().startswith("#"))
    for word in ("RELATIONSHIP", "관계 상태"):
        check(f"카드 준비 코드가 '{word}' 를 읽지 않는다", word not in code)


# ===============================================================
def check_privacy() -> None:
    section("9. 개인정보 — 관계 상태는 로그에 남기지 않는다")

    check("저장하는 칸은 예전 여섯 개 그대로다",
          analytics.FIELDNAMES
          == ["session_id", "timestamp", "event_name", "concern",
              "model", "step"],
          str(analytics.FIELDNAMES))

    write_event = next(
        node for node in ast.walk(APP_TREE)
        if isinstance(node, ast.FunctionDef) and node.name == "_write_event"
    )
    statements = write_event.body
    if ast.get_docstring(write_event):
        statements = statements[1:]
    code = "\n".join(ast.unparse(node) for node in statements)
    for word in ("RELATIONSHIP", "관계 상태", "추가 질문"):
        check(f"이벤트 한 줄에 '{word}' 가 들어가지 않는다", word not in code)

    # 피드백 저장에도 들어가지 않는지
    check("피드백 저장 칸도 그대로다",
          analytics.FEEDBACK_FIELDNAMES
          == ["session_id", "timestamp", "feedback_result", "concern", "model"],
          str(analytics.FEEDBACK_FIELDNAMES))

    # 관계 상태는 미리 정해진 선택지라 자유서술이 아닙니다 — 그래도 저장하지 않습니다.
    check("관계 상태는 미리 정해진 선택지뿐이다 (자유서술 아님)",
          all(isinstance(option, str) for option in RELATIONSHIP_OPTIONS))
    check("추가 질문 원문은 예전처럼 저장하지 않는다",
          "추가 질문" not in code)


# ===============================================================
def check_no_regression() -> None:
    section("10. 기존 기능이 그대로인지")

    import daeun

    check("Step1~3 과제문은 그대로다",
          "행동 지령" in halmae_ai.STEP3_TASK
          and "깊은 해석" in halmae_ai.STEP2_TASK)
    check("Step1 예고 문장은 그대로다",
          "대운" in halmae_ai.STEP1_YEAR_FLOW_TEASER)
    check("대운·세운 계산은 관계 상태를 모른다",
          "관계" not in open("daeun.py", encoding="utf-8").read())
    check("대운 계산 규칙이 그대로다",
          daeun.DIRECTION_RULE.startswith("양간년 남자"))

    # 관계 상태가 없어도 프롬프트가 정상적으로 만들어지는지 (예전 사용자)
    old_answers = {k: v for k, v in BASE.items()}
    old_answers["고민 분야"] = "취업/커리어"
    for step in (1, 2, 3):
        prompt = build_prompt(step, old_answers, SAJU, PROMPT_ASTRO)
        check(f"관계 상태 칸이 아예 없어도 Step{step} 프롬프트가 만들어진다",
              len(prompt) > 100 and "[관계 상태" not in prompt)

    check("Mock 도 관계 상태를 쓴다 (화면이 실제와 달라지지 않게)",
          "relationship" in open("mock_ai.py", encoding="utf-8").read())


# ===============================================================
def main() -> int:
    print("=" * 64)
    print(" 할매 · 연애·관계 상태 검증 (Gemini 호출 없음)")
    print("=" * 64)
    print(f" 고민 분야   {RELATIONSHIP_CONCERN}")
    print(f" 관계 상태   {' / '.join(RELATIONSHIP_OPTIONS)}")

    check_options()
    check_conditional_ui()
    check_context_value()
    check_prompt_carries_state()
    check_policies()
    check_no_assumption()
    check_unknown_state()
    check_year_card_untouched()
    check_privacy()
    check_no_regression()

    print()
    print("=" * 64)
    if _failures:
        print(f" 실패 {len(_failures)}건")
        for name in _failures:
            print(f"   - {name}")
        return 1
    print(" 전부 통과 — 할매가 관계 상태를 넘겨짚지 않습니다")
    return 0


if __name__ == "__main__":
    sys.exit(main())
