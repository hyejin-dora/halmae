"""일·커리어 — 커리어 상황 검증 (Gemini 호출 없음 · Supabase 쓰기 없음)

    python test_career.py

[무엇을 고치려고 만든 기능인가]
    고민 분야가 "취업/커리어" 하나뿐이던 시절, 할매(Gemini)는 사용자를
    취업준비생이라고 짐작하고 "이력서를 고쳐 써라", "지원해 보라" 같은
    조언을 했습니다. 이미 회사에 다니는 사람에게는 빗나간 말입니다.
    반대로 첫 취업을 준비하는 사람에게 "상사와의 갈등" 을 말하면
    없는 상황을 지어낸 말이 됩니다.

    그래서 커리어 상황을 '추측 대상'에서 '사용자가 고르는 확정 입력값'으로
    옮겼습니다. 이 파일은 그 경계가 새지 않는지 확인합니다.

확인하는 것
    1. 고민 분야가 "일·커리어" 로 바뀌었는지 (예전 이름도 알아보는지)
    2. 그 분야를 골랐을 때만 커리어 상황을 묻는지 (조건부 UI)
    3. 커리어 상황이 career_context 라는 별도 값으로 관리되는지
    4. Step1/2/3 · 올해의 흐름 프롬프트에 실려 나가는지
    5. 상황마다 해석 정책이 제대로 붙는지
    6. 상태를 뒤바꾸는 조언을 막았는지 (취준 ↔ 재직)
    7. "말하고 싶지 않아요" 일 때 아무것도 추측하지 않는지
    8. 올해의 카드 정책이 그대로인지 (열쇠·프롬프트에 커리어 상황 없음)
    9. 커리어 상황 원문이 행동 로그에 저장되지 않는지

여기 쓰는 값은 전부 개발용 예시입니다. 실제 사용자 정보가 아닙니다.
"""

import ast
import sys
from datetime import date, time

import analytics
import card_store
import halmae_ai
from halmae_ai import (
    CAREER_CONCERN,
    CAREER_CONTEXT_KEY,
    CAREER_LOCK_RULES,
    CAREER_OPTIONS,
    CAREER_POLICIES,
    CAREER_QUESTION,
    CAREER_UNKNOWN,
    LEGACY_CAREER_CONCERNS,
    build_career_block,
    build_prompt,
    build_year_card_prompt,
    build_year_flow_prompt,
    career_context,
    normalize_concern,
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
    """app.py 상수 안에 쓰인 이름을 실제 값으로 바꿉니다."""

    def visit_Name(self, node):                       # noqa: N802
        if hasattr(halmae_ai, node.id):
            return ast.Constant(value=getattr(halmae_ai, node.id))
        return node


def app_literal(name: str):
    for node in ast.walk(APP_TREE):
        if (isinstance(node, ast.Assign)
                and any(getattr(t, "id", "") == name for t in node.targets)):
            resolved = _NameResolver().visit(
                ast.parse(ast.unparse(node.value), mode="eval")
            )
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
    "추가 질문": "지금 일이 나에게 맞는지 모르겠어요",
}
SAJU = compute_saju(BASE["생년월일"], BASE["출생시간"], "양력")
ASTRO = {"latitude": 37.5665, "longitude": 126.978,
         "sun_sign": "Taurus", "moon_sign": "Leo", "rising_sign": "Cancer"}
PROMPT_ASTRO = None


def work(state: str | None, concern: str = CAREER_CONCERN) -> dict:
    """일·커리어 + 커리어 상황 조합의 입력값."""
    return {**BASE, "고민 분야": concern, CAREER_CONTEXT_KEY: state}


def other(concern: str = "돈") -> dict:
    """커리어가 아닌 다른 고민. (값이 남아 있어도 쓰이면 안 됩니다)"""
    return {**BASE, "고민 분야": concern,
            CAREER_CONTEXT_KEY: "재직 중·직장생활"}


# 상황별로 '이 낱말이 나오면 잘못된 조언' 인 것들
FORBIDDEN = {
    "첫 취업·구직 중": ["상사", "승진", "사내 정치", "지금 회사를 그만두면"],
    "재직 중·직장생활": ["이력서", "자기소개서", "취업 지원", "취준",
                     "첫 직장을 구해라"],
    "이직·퇴사 고민": ["당장 그만두", "무조건 버텨"],
    "진로·직무 전환 고민": ["회사를 그만두고", "지금 다니는 곳에서"],
    CAREER_UNKNOWN: ["취준생", "직장인", "백수", "신입"],
}


# ===============================================================
def check_options() -> None:
    section("1. 고민 분야와 선택지")

    options = app_literal("CONCERN_OPTIONS")
    check("고민 분야가 '일·커리어' 로 바뀌었다",
          CAREER_CONCERN == "일·커리어"
          and options is not None and CAREER_CONCERN in options,
          str(options))
    check("예전 '취업/커리어' 는 선택지에 남아 있지 않다",
          options is not None and "취업/커리어" not in options)
    check("고민 분야는 여섯 개 그대로다",
          options is not None and len(options) == 6, str(options))

    check("커리어 상황 선택지가 다섯 개다",
          CAREER_OPTIONS == ["첫 취업·구직 중", "재직 중·직장생활",
                             "이직·퇴사 고민", "진로·직무 전환 고민",
                             "말하고 싶지 않아요"],
          str(CAREER_OPTIONS))
    check("질문 문구가 정해져 있다",
          CAREER_QUESTION == "현재 어떤 상황에 가까운가요?", CAREER_QUESTION)
    check("선택지마다 해석 정책이 하나씩 있다",
          set(CAREER_POLICIES) == set(CAREER_OPTIONS))


# ===============================================================
def check_legacy_compat() -> None:
    section("2. 예전 이름 호환 — 저장된 데이터가 깨지지 않는다")

    for legacy in LEGACY_CAREER_CONCERNS:
        check(f"'{legacy}' 를 '일·커리어' 로 알아본다",
              normalize_concern(legacy) == CAREER_CONCERN,
              str(normalize_concern(legacy)))
        # 예전 이름으로 저장된 답변에도 커리어 블록이 붙어야 합니다.
        answers = work("이직·퇴사 고민", concern=legacy)
        check(f"'{legacy}' 로 저장된 답변에도 커리어 상황이 붙는다",
              career_context(answers) == "이직·퇴사 고민"
              and "[일·커리어 상황" in build_career_block(answers))

    check("다른 고민 이름은 그대로 둔다",
          normalize_concern("돈") == "돈"
          and normalize_concern("연애·관계") == "연애·관계")
    check("None 은 None 으로", normalize_concern(None) is None)
    check("새 이름도 그대로 통과한다",
          normalize_concern(CAREER_CONCERN) == CAREER_CONCERN)


# ===============================================================
def check_conditional_ui() -> None:
    section("3. 조건부 UI — 일·커리어를 골랐을 때만 묻는다")

    body = APP_SOURCE.split("def render_input()")[1].split("\ndef ")[0]

    concern_at = body.find('key="in_concern"')
    career_at = body.find('key="in_career"')
    check("커리어 질문이 고민 분야 다음에 있다",
          0 < concern_at < career_at, f"고민 {concern_at} · 커리어 {career_at}")
    check("일·커리어일 때만 질문을 그린다",
          "if concern == CAREER_CONCERN:" in body)

    render_input = next(
        node for node in ast.walk(APP_TREE)
        if isinstance(node, ast.FunctionDef) and node.name == "render_input"
    )
    guarded = False
    for node in ast.walk(render_input):
        if not isinstance(node, ast.If):
            continue
        if "CAREER_CONCERN" not in ast.unparse(node.test):
            continue
        if "in_career" in ast.unparse(node.body):
            guarded = True
    check("커리어 위젯이 조건문 '안'에 있다 (다른 고민에서는 안 그려짐)",
          guarded)

    check("미리 골라두지 않는다 (index=None)",
          "index=None," in body.split('key="in_career"')[0][-300:])

    note = app_literal("CAREER_FIELD_NOTE")
    check("질문 아래 짧은 안내가 있다", bool(note), str(note))
    check("안내가 '안 골라도 된다' 는 걸 알려준다",
          note is not None and "넘겨짚지" in note)

    submit = body.split("st.session_state.answers = {")[1].split("}")[0]
    check("커리어 상황을 별도 칸으로 담는다",
          "CAREER_CONTEXT_KEY:" in submit)
    check("일·커리어가 아니면 담지 않는다 (None)",
          "if concern == CAREER_CONCERN else None" in submit)
    check("비워둔 채 제출하면 '말하고 싶지 않아요' 로 본다",
          "CAREER_UNKNOWN" in submit)

    # 관계 상태 질문과 섞이지 않아야 합니다.
    check("연애·관계 질문과 서로 다른 위젯이다",
          'key="in_relationship"' in body and 'key="in_career"' in body)


# ===============================================================
def check_context_value() -> None:
    section("4. career_context 값 다루기")

    for state in CAREER_OPTIONS:
        check(f"'{state}' 를 그대로 돌려준다",
              career_context(work(state)) == state)

    check("일·커리어가 아니면 None (값이 남아 있어도 쓰지 않는다)",
          career_context(other()) is None)
    check("고민 분야가 없으면 None", career_context({}) is None)
    check("빈 값이면 '말하고 싶지 않아요' 로 본다 (취준생으로 넘겨짚지 않음)",
          career_context(work(None)) == CAREER_UNKNOWN
          and career_context(work("")) == CAREER_UNKNOWN)
    check("모르는 값이 들어와도 추측하지 않는다",
          career_context(work("아무거나")) == CAREER_UNKNOWN)
    check("연애·관계 고민에는 붙지 않는다",
          career_context(other("연애·관계")) is None)


# ===============================================================
def check_prompt_payload() -> None:
    section("5. 프롬프트 payload — Step1/2/3 · 올해의 흐름")

    # 세운은 daeun.format_year_flow_for_prompt 가 받는 모양으로 만듭니다.
    sewoon = {"year": 2026, "pillar": "병오", "pillar_hanja": "丙午",
              "stem_ohaeng": "화", "branch_ohaeng": "화", "animal": "말",
              "ganji": compute_year_ganji(date(2026, 6, 1))}

    for state in CAREER_OPTIONS:
        answers = work(state)
        for step in (1, 2, 3):
            prompt = build_prompt(step, answers, SAJU, PROMPT_ASTRO)
            ok = (
                "[일·커리어 상황" in prompt
                and state in prompt
                and CAREER_POLICIES[state][:24] in prompt
                and "커리어 상황 사용 규칙" in prompt
            )
            check(f"'{state}' · Step{step} 에 상황과 정책이 실린다", ok)

        flow = build_year_flow_prompt(answers, SAJU, PROMPT_ASTRO,
                                      None, sewoon)
        check(f"'{state}' · 올해의 흐름에도 실린다",
              "[일·커리어 상황" in flow and state in flow)

    # 다른 고민에는 붙지 않아야 합니다
    for concern in ("연애·관계", "돈", "인간관계", "삶의 방향", "기타"):
        answers = other(concern)
        blank = all(
            "[일·커리어 상황" not in build_prompt(step, answers, SAJU,
                                             PROMPT_ASTRO)
            for step in (1, 2, 3)
        )
        check(f"'{concern}' 고민에는 커리어 상황이 붙지 않는다", blank)

    check("커리어 블록은 build_career_block 한 곳에서만 만든다",
          build_career_block(other()) == ""
          and build_career_block({}) == ""
          and build_career_block(None) == "")

    # 커리어 상황 칸이 아예 없는 예전 사용자도 프롬프트가 만들어져야 합니다.
    old = {k: v for k, v in BASE.items()}
    old["고민 분야"] = "돈"
    for step in (1, 2, 3):
        prompt = build_prompt(step, old, SAJU, PROMPT_ASTRO)
        check(f"커리어 칸이 없어도 Step{step} 프롬프트가 만들어진다",
              len(prompt) > 100 and "[일·커리어 상황" not in prompt)


# ===============================================================
def check_no_assumption() -> None:
    section("6. 상태 오가정 금지 — 취준 ↔ 재직을 뒤바꾸지 않는다")

    # 각 정책이 '하지 말 것' 을 실제로 적어두었는지
    for state, banned_words in FORBIDDEN.items():
        policy = CAREER_POLICIES[state]
        found = [w for w in banned_words if w in policy]
        check(f"'{state}' 정책이 금지 표현을 직접 적어둔다 ({len(found)}개)",
              len(found) >= 2, str(found))

    # 가장 흔한 실수 두 가지를 정책이 못 박아두었는지
    employed = CAREER_POLICIES["재직 중·직장생활"]
    check("재직자에게 '이력서' 를 금지한다", "이력서" in employed)
    check("재직자에게 '취업 지원' 을 금지한다", "취업 지원" in employed)
    check("재직자에게 '취준' 을 금지한다", "취준" in employed)
    check("재직자를 이직 고민으로 단정하지 않는다",
          "이직을 고민한다고 전제하지도 마라" in employed)

    seeker = CAREER_POLICIES["첫 취업·구직 중"]
    check("구직자에게 조직 내 갈등을 전제하지 않는다",
          "상사" in seeker and "승진" in seeker)
    check("구직자에게 경력·직급을 가정하지 않는다",
          "경력·연차·직급이 있다고 가정하지 마라" in seeker)

    quitting = CAREER_POLICIES["이직·퇴사 고민"]
    check("감정적 즉시 퇴사를 단정하지 않는다",
          "감정이 상한 상태에서 즉시 퇴사하라는 말은" in quitting)
    check("반대로 무조건 버티라고도 하지 않는다",
          "무조건 버텨라" in quitting)

    switching = CAREER_POLICIES["진로·직무 전환 고민"]
    check("전환 고민은 장기 방향과 강점 연결을 본다",
          "길게 보았을 때" in switching and "강점" in switching)
    check("재직 여부를 어느 쪽도 전제하지 않는다",
          "어느 쪽도 전제하지 마라" in switching)

    unknown = CAREER_POLICIES[CAREER_UNKNOWN]
    for word in ("취업준비생", "재직자", "무직", "이직"):
        check(f"'말하고 싶지 않아요' 는 '{word}' 를 추측하지 않는다",
              word in unknown)
    check("성향·판단 패턴만 해석하라고 적어둔다",
          "성향" in unknown and "패턴" in unknown)

    # 잠금 규칙이 프롬프트에 실제로 실려 나가는지
    prompt = build_prompt(1, work("재직 중·직장생활"), SAJU, PROMPT_ASTRO)
    for line in ("다른 상태를 가정하지 마라",
                 "이 두 가지를 뒤바꾸는 것이 가장 흔한 실수다",
                 "사주·점성술 값으로 취업 상태를 역추적하려 하지 마라"):
        check(f"잠금 규칙이 프롬프트에 있다: '{line[:24]}...'", line in prompt)

    check("추가 질문에 적힌 내용은 반영할 수 있다고 적어둔다",
          "추가 질문에 커리어 상황이 분명하게 적혀 있으면" in CAREER_LOCK_RULES)


# ===============================================================
def check_year_card_independent() -> None:
    section("7. 올해의 카드는 커리어 상황과 무관하다")

    ganji = compute_year_ganji(date(2026, 6, 1))

    # 카드 프롬프트는 answers 를 아예 받지 않습니다 (구조적 차단)
    import inspect
    params = list(inspect.signature(build_year_card_prompt).parameters)
    check("카드 프롬프트는 answers 를 받지 않는다 (구조적으로 못 들어간다)",
          "answers" not in params, str(params))

    card_prompt = build_year_card_prompt(SAJU, PROMPT_ASTRO, ganji,
                                        ["올해는 토가 세다"])
    for state in CAREER_OPTIONS:
        check(f"카드 프롬프트에 '{state}' 가 없다", state not in card_prompt)
    check("카드 프롬프트에 커리어 블록이 없다",
          "[일·커리어 상황" not in card_prompt
          and "커리어 상황 사용 규칙" not in card_prompt)

    # stable_key 는 커리어 상황과 무관해야 합니다.
    keys = {
        card_store.build_card_key(work(state), SAJU, ASTRO, 2026)
        for state in CAREER_OPTIONS
    }
    check("커리어 상황이 달라도 카드 열쇠는 하나다", len(keys) == 1, str(keys))
    check("다른 고민으로 들어와도 같은 열쇠다",
          card_store.build_card_key(other("돈"), SAJU, ASTRO, 2026) in keys)

    fingerprint = card_store.build_card_fingerprint(
        work("재직 중·직장생활"), SAJU, ASTRO, 2026
    )
    for word in ("재직", "취업", "이직", "커리어", "구직", "전환"):
        check(f"카드 지문에 '{word}' 가 없다", word not in fingerprint)


# ===============================================================
def check_privacy() -> None:
    section("8. 개인정보 — 추가 질문 원문과 상황 원문이 저장되지 않는다")

    check("analytics 저장 칸이 여섯 개 그대로다",
          analytics.FIELDNAMES == ["session_id", "timestamp", "event_name",
                                   "concern", "model", "step"],
          str(analytics.FIELDNAMES))
    check("커리어 상황 전용 칸을 새로 만들지 않았다",
          not any("career" in f or "커리어" in f
                  for f in analytics.FIELDNAMES))

    row = analytics._clean_row("sid", "input_submit", CAREER_CONCERN,
                               "gemini", 1)
    check("이벤트 한 줄에는 고민 분야까지만 들어간다",
          row["concern"] == CAREER_CONCERN and len(row) == 6, str(row))
    for banned in ("재직 중·직장생활", "지금 일이 나에게 맞는지 모르겠어요",
                   "예시"):
        check(f"이벤트 한 줄에 '{banned[:12]}' 가 없다",
              banned not in " ".join(str(v) for v in row.values()))

    # app.py 가 커리어 상황을 로그로 넘기지 않는지
    write_event = next(node for node in ast.walk(APP_TREE)
                       if isinstance(node, ast.FunctionDef)
                       and node.name == "_write_event")
    # docstring 은 설명일 뿐이라 실제로 넘기는 코드만 봅니다.
    # ("추가 질문은 여기까지 오지도 않습니다" 같은 문장이 들어 있어서요)
    statements = [
        node for node in write_event.body
        if not (isinstance(node, ast.Expr)
                and isinstance(node.value, ast.Constant)
                and isinstance(node.value.value, str))
    ]
    code = "\n".join(ast.unparse(node) for node in statements)
    check("_write_event 는 커리어 상황을 넘기지 않는다",
          "CAREER_CONTEXT_KEY" not in code and "커리어 상황" not in code, code)
    check("_write_event 는 추가 질문을 넘기지 않는다",
          "추가 질문" not in code, code)
    check("_write_event 가 넘기는 것은 고민 분야뿐이다",
          "고민 분야" in code
          and not any(word in code for word in
                      ("이름", "생년월일", "출생시간", "출생지역")),
          code)


# ===============================================================
def check_mock() -> None:
    section("9. Mock 도 커리어 상황을 쓴다 (개발 화면이 실제와 달라지지 않게)")

    import mock_ai
    answers = work("재직 중·직장생활")
    reply = mock_ai.mock_step1(answers, SAJU, None)
    check("Mock 1단계가 커리어 상황을 반영한다",
          "재직 중·직장생활" in str(reply.model_dump()))
    plain = mock_ai.mock_step1(other("돈"), SAJU, None)
    check("다른 고민에서는 반영하지 않는다",
          "재직 중·직장생활" not in str(plain.model_dump()))


# ===============================================================
def main() -> int:
    print("=" * 64)
    print(" 할매 · 일·커리어 상황 검증 (Gemini 호출 없음 · Supabase 쓰기 없음)")
    print("=" * 64)

    check_options()
    check_legacy_compat()
    check_conditional_ui()
    check_context_value()
    check_prompt_payload()
    check_no_assumption()
    check_year_card_independent()
    check_privacy()
    check_mock()

    print()
    print("=" * 64)
    if _failures:
        print(f" 실패 {len(_failures)}건")
        for name in _failures:
            print(f"   - {name}")
        return 1
    print(" 전부 통과 — 할매가 취업 상태를 넘겨짚지 않습니다")
    return 0


if __name__ == "__main__":
    sys.exit(main())
