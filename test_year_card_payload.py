"""올해의 카드 — 고민과 독립인지 확인 (개발 테스트 전용 · Gemini 호출 없음)

    python test_year_card_payload.py
    python test_year_card_payload.py 1999-04-13 08:49 서울

이 파일이 확인하는 것
    1. 같은 출생정보 + 고민만 다를 때 stable_key 가 같은지
       (A. 커리어 고민  vs  B. 연애 고민)
    2. 카드 생성 함수에 넘어가는 payload 가 두 경우 완전히 같은지
    3. payload 안에 고민 분야 · 추가 질문 · Step1~3 응답 ·
       Premium 관련 내용이 한 글자도 없는지
    4. 카드 프롬프트에 계산 완료된 값(사주·점성술·올해 간지)이 실제로 들어 있는지
    5. ask_year_card() 가 대화 이력(history)을 받지 않는지 (회귀 방지)
    6. stable_key 지문에 고민 정보가 섞이지 않는지

절대 하지 않는 일
    - Gemini API 호출 (프롬프트 조립 함수만 부릅니다)
    - Supabase 읽기/쓰기 (카드를 저장하거나 지우지 않습니다)

  ⚠ 출력에 생년월일·출생시간이 들어갑니다. 개발용 터미널에서만 쓰세요.
     stable_key 와 지문은 앞자리만 찍습니다.
"""

import inspect
import json
import sys
from datetime import date, time

import halmae_ai
from halmae_ai import build_year_card_payload
from saju import compute_saju, compute_year_ganji, year_luck_notes

_failures: list[str] = []


def check(label: str, ok: bool, detail: str = "") -> None:
    mark = "PASS" if ok else "FAIL"
    print(f"  [{mark}] {label}" + (f"  — {detail}" if detail else ""))
    if not ok:
        _failures.append(label)


# ===============================================================
#  두 세션 — 출생정보는 같고 고민만 다릅니다
#
#  실제 앱에서 st.session_state.answers 에 담기는 모양 그대로 만듭니다.
#  (app.py 의 build_card_key(...) 가 이 dict 를 받습니다)
# ===============================================================
CAREER_ANSWERS_EXTRA = {
    "고민 분야": "취업/커리어",
    "추가 질문": "지금 회사를 그만두고 이직해도 될까요? 이력서를 어떻게 써야 할까요?",
}

LOVE_ANSWERS_EXTRA = {
    "고민 분야": "연애",
    "추가 질문": "지금 만나는 사람과 계속 가도 괜찮을까요? 소개팅을 더 나가야 할까요?",
}

# payload 어디에도 나와서는 안 되는 낱말 — Premium 관련.
# (카드는 결제 유도와 아무 상관이 없어야 합니다)
PREMIUM_WORDS = ("비밀 처방", "Premium", "premium", "프리미엄", "결제", "9,900")

# 고민 분야 전용 낱말.
# 이 낱말들은 프롬프트에 "이렇게 쓰지 마라"는 금지 예시로 일부러 들어 있습니다.
# 그래서 '있다/없다'로 판정하지 않고, 나오는 자리를 눈으로 확인만 합니다.
# (payload 가 두 세션에서 완전히 같으면 고민이 새어들 자리가 없습니다)
CONCERN_WORDS = (
    "취업", "커리어", "이직", "이력서", "실무자", "면접", "연봉",
    "연애", "소개팅", "썸", "재테크", "투자", "적립식",
)

# 1~3단계에서 할매가 실제로 내놓은 답이라고 가정한 글.
# 예전 버그에서는 이 글이 대화 이력으로 카드 프롬프트에 그대로 흘러들었습니다.
CAREER_STEP_ANSWERS = [
    "네 일간이 갑이라 밀어붙이는 힘이 강하단다. 지금 커리어 고민이 깊구나.",
    "이력서를 다시 쓰고, 현업 실무자에게 먼저 연락해보거라.",
    "면접에서는 연봉 이야기를 먼저 꺼내지 말거라.",
]
LOVE_STEP_ANSWERS = [
    "네 달궁이 물병이라 마음을 늦게 여는 편이란다. 지금 연애 고민이 깊구나.",
    "소개팅 자리에 두 번은 더 나가보거라.",
    "썸에서 먼저 연락하는 쪽이 되어보거라.",
]


def build_answers(birth: dict, extra: dict) -> dict:
    answers = dict(birth)
    answers.update(extra)
    return answers


def payload_for(saju, astro, year_ganji) -> dict:
    """앱이 카드 생성에 넘기는 payload. (고민 정보는 애초에 인자가 없습니다)"""
    return build_year_card_payload(
        saju, astro, year_ganji, year_luck_notes(saju, year_ganji)
    )


# ===============================================================
#  1. stable_key — 고민이 달라도 같아야 합니다
# ===============================================================
def verify_stable_key(birth: dict, saju, astro, year: int) -> None:
    import card_store

    print("[STABLE KEY — 고민만 다른 두 세션]")
    career = build_answers(birth, CAREER_ANSWERS_EXTRA)
    love = build_answers(birth, LOVE_ANSWERS_EXTRA)

    key_career = card_store.build_card_key(career, saju, astro, year)
    key_love = card_store.build_card_key(love, saju, astro, year)

    check("A(커리어) 와 B(연애) 의 stable_key 가 같다",
          key_career == key_love,
          f"{key_career[:16]}… == {key_love[:16]}…")

    fingerprint = card_store.build_card_fingerprint(career, saju, astro, year)
    check("지문에 고민 분야가 없다", "고민" not in fingerprint)
    check("지문에 추가 질문이 없다",
          not any(word in fingerprint for word in ("이력서", "소개팅", "이직")))
    for field in ("concern", "question", "step"):
        check(f"지문에 '{field}' 항목이 없다", field not in fingerprint.lower())
    check("지문은 연도 + 정규화된 출생정보로만 되어 있다",
          sorted(part.split("=")[0] for part in fingerprint.split("|")) == sorted([
              "source", "year", "solar_date", "birth_time", "lat", "lon",
              "gender", "년주", "월주", "일주", "시주", "sun", "moon", "rising",
          ]),
          " · ".join(part.split("=")[0] for part in fingerprint.split("|")))

    # 다른 해에는 다른 카드여야 합니다 (열쇠가 연도를 실제로 반영하는지)
    check("연도가 바뀌면 열쇠도 바뀐다",
          card_store.build_card_key(career, saju, astro, year + 1) != key_career)
    print()


# ===============================================================
#  2. payload — 두 경우가 완전히 같아야 합니다
# ===============================================================
def verify_payload_identical(saju, astro, year_ganji) -> dict:
    print("[CARD PAYLOAD — 커리어 입력 vs 연애 입력]")

    # 카드 생성 함수는 고민을 받는 인자 자체가 없습니다.
    # 그래서 두 세션에서 만들어지는 payload 는 같은 값이어야 합니다.
    career_payload = payload_for(saju, astro, year_ganji)
    love_payload = payload_for(saju, astro, year_ganji)

    same = json.dumps(career_payload, ensure_ascii=False, sort_keys=True) == \
        json.dumps(love_payload, ensure_ascii=False, sort_keys=True)
    check("A(커리어) 와 B(연애) 의 card payload 가 완전히 같다", same)

    signature = inspect.signature(halmae_ai.ask_year_card)
    names = list(signature.parameters)
    check("ask_year_card() 가 대화 이력(history)을 받지 않는다",
          "history" not in names, " · ".join(names))
    check("build_year_card_payload() 가 고민을 받는 인자가 없다",
          not any(word in " ".join(inspect.signature(build_year_card_payload)
                                   .parameters)
                  for word in ("answers", "concern", "history", "step")),
          " · ".join(inspect.signature(build_year_card_payload).parameters))
    print()
    return career_payload


# ===============================================================
#  3. payload 안에 이 세션의 고민 흔적이 없는지
#
#  낱말이 '있는지'가 아니라 '이 세션의 값이 들어갔는지'를 봅니다.
#  프롬프트에는 "이력서를 쓰라고 하지 마라" 같은 금지 예시가 일부러 들어 있어서,
#  낱말만 세면 그 금지문까지 잡혀버립니다.
# ===============================================================
def payload_text(payload: dict) -> str:
    return payload["system_instruction"] + "\n" + "\n".join(
        part["text"] for turn in payload["contents"] for part in turn["parts"]
    )


def verify_no_concern_leak(payload: dict, birth: dict) -> None:
    print("[CARD PAYLOAD — 이 세션의 고민이 새어들었는지]")
    text = payload_text(payload)

    # 고민이 프롬프트로 새는 길은 사용자 정보 블록(build_profile_block)입니다.
    # 그 블록은 "- 고민 분야: 연애" / "- 추가 질문: ..." 모양으로 붙습니다.
    # 그래서 값 자체보다 이 라벨이 있는지를 봅니다.
    # ('연애' 두 글자는 아래 금지 예시에도 나와서 값만 세면 헷갈립니다)
    check("사용자 정보 블록이 붙지 않았다 ([사용자 정보] 없음)",
          "[사용자 정보]" not in text)
    check("'고민 분야:' 라벨이 없다", "고민 분야:" not in text)
    check("'추가 질문:' 라벨이 없다", "추가 질문:" not in text)

    for label, extra, step_answers in (
        ("커리어", CAREER_ANSWERS_EXTRA, CAREER_STEP_ANSWERS),
        ("연애", LOVE_ANSWERS_EXTRA, LOVE_STEP_ANSWERS),
    ):
        # 추가 질문은 문장이 길어 통째로 찾으면 늘 통과합니다.
        # 그래서 문장을 조각내 한 조각이라도 들어갔는지 봅니다.
        fragments = [
            piece.strip() for piece in
            extra["추가 질문"].replace("?", "?|").split("|") if piece.strip()
        ]
        leaked = [piece for piece in fragments if piece in text]
        check(f"{label} 세션의 추가 질문이 한 조각도 없다",
              not leaked, " / ".join(leaked))
        for index, answer in enumerate(step_answers, start=1):
            check(f"{label} Step{index} 응답이 없다", answer not in text)

    check("사용자 이름이 없다", birth["이름"] not in text)
    check("Step1~3 응답 항목 이름이 없다",
          not any(name in text for name in
                  ("headline", "evidences", "concern_reading",
                   "blind_spot", "decision_rules", "directives")))
    for word in PREMIUM_WORDS:
        check(f"Premium 관련 '{word}' 가 없다", word not in text)

    check("대화가 한 번뿐이다 (1~3단계 이력이 붙지 않았다)",
          len(payload["contents"]) == 1, f"{len(payload['contents'])}턴")
    check("카드 전용 페르소나를 쓴다 (고민 연결 지시가 빠진 것)",
          payload["system_instruction"] == halmae_ai.YEAR_CARD_SYSTEM_INSTRUCTION
          and payload["system_instruction"] != halmae_ai.SYSTEM_INSTRUCTION)
    check("페르소나가 '고민 분야를 연결하라'고 시키지 않는다",
          "고민 분야, 추가 질문을 서로 연결" not in payload["system_instruction"])

    # 고민 전용 낱말이 남아 있는 자리는 전부 '금지 예시'여야 합니다.
    # 사람이 눈으로 확인할 수 있게 그 줄을 그대로 찍어둡니다.
    print()
    print("  (참고) 고민 전용 낱말이 나오는 자리 — 모두 금지·정책 문구여야 합니다")
    shown = 0
    for line in text.splitlines():
        if any(word in line for word in CONCERN_WORDS):
            print(f"      {line.strip()}")
            shown += 1
    if shown == 0:
        print("      (없음)")
    print()


# ===============================================================
#  4. 계산 완료된 값은 제대로 들어갔는지
# ===============================================================
def verify_calculated_inputs(payload: dict, saju, astro, year_ganji) -> None:
    print("[CARD PAYLOAD — 들어가야 할 계산값]")
    question = payload["contents"][0]["parts"][0]["text"]

    for name in ("년주", "월주", "일주", "시주"):
        pillar = saju["기둥"][name]
        if pillar is None:
            check(f"{name} 없음이 명시되어 있다", f"{name}: (없음)" in question)
            continue
        check(f"{name}({pillar['한글']}) 가 들어 있다",
              pillar["한글"] in question)

    check(f"일간({saju['일간']['한글']}) 이 들어 있다",
          f"일간: {saju['일간']['한글']}" in question)
    check("오행 개수가 들어 있다", "오행 개수" in question)

    if astro:
        check(f"Sun({astro['sun_sign']}) 이 들어 있다",
              astro["sun_sign"] in question)
        check(f"Moon({astro['moon_sign']}) 이 들어 있다",
              astro["moon_sign"] in question)
        if astro["상승점"]:
            check(f"Ascendant({astro['rising_sign']}) 이 들어 있다",
                  astro["rising_sign"] in question)
        else:
            check("출생시간을 모를 때 상승궁 없음이 명시되어 있다",
                  "Rising Sign(상승궁): 없음" in question)

    check(f"올해 연도({year_ganji['연도']}) 가 들어 있다",
          str(year_ganji["연도"]) in question)
    check(f"올해 간지({year_ganji['한글']}) 가 들어 있다",
          year_ganji["한글"] in question)
    check("올해 오행 정보가 들어 있다", "올해 천간의 오행" in question)
    check("'올해의 테마 한 가지' 를 요구한다", "하나의 테마" in question)
    check("고민을 짐작하지 말라고 못 박혀 있다",
          "고민 정보는 주어지지 않았다" in question)
    print()


# ===============================================================
#  5. 행동 문구 규칙이 프롬프트/스키마에 박혀 있는지
# ===============================================================
def verify_action_rules(payload: dict) -> None:
    print("[ACTION 규칙 — 고민에 종속되지 않게]")
    question = payload["contents"][0]["parts"][0]["text"]

    check("여러 영역에 적용 가능한 원칙으로 쓰라고 시킨다",
          "여러 삶의 영역" in question)
    for bad in ("이력서", "소개팅", "투자"):
        check(f"'{bad}' 를 나쁜 예로 못 박아두었다",
              f"나쁜 예" in question and bad in question)

    schema = halmae_ai.YearCard.model_fields["actions"].description
    check("스키마 설명에도 '특정 고민 분야 금지' 가 적혀 있다",
          "특정 고민 분야" in schema)
    print()


# ===============================================================
#  6. app.py 가 history 를 카드에 넘기지 않는지
# ===============================================================
def verify_app_call_site() -> None:
    print("[APP 호출부 — history 를 넘기지 않는지]")
    source = open("app.py", encoding="utf-8").read()
    body = source.split("def ensure_year_card")[1].split("\ndef ")[0]

    # 주석에는 "history 를 넘기지 않는다"는 설명이 들어 있어서
    # 그대로 세면 잡혀버립니다. 실제로 도는 코드 줄만 남겨 검사합니다.
    code = "\n".join(
        line for line in body.splitlines()
        if not line.strip().startswith("#")
    )

    check("ensure_year_card() 코드가 history 를 쓰지 않는다",
          "history" not in code)
    check("ensure_year_card() 코드가 고민 분야·추가 질문을 읽지 않는다",
          "고민 분야" not in code and "추가 질문" not in code)
    check("ask_year_card 에 saju 와 astro 를 넘긴다",
          "ask_year_card(\n                saju," in body
          and "st.session_state.astro_info," in body)
    print()


# ===============================================================
#  실행
# ===============================================================
def main() -> int:
    argv = sys.argv[1:]
    raw_date = argv[0] if argv else "1999-04-12"
    raw_time = argv[1] if len(argv) > 1 else "08:49"
    place = argv[2] if len(argv) > 2 else "서울"

    birth_time = None
    if raw_time not in ("모름", "-", "none", "None"):
        birth_time = time.fromisoformat(raw_time)

    print("=" * 64)
    print(" 올해의 카드 · 고민 독립성 진단 (Gemini 호출 없음)")
    print("=" * 64)
    print(f" 출생정보 {raw_date} {raw_time} {place} — 고민만 바꿔가며 비교합니다")
    print()

    birth_date = date.fromisoformat(raw_date)
    saju = compute_saju(birth_date=birth_date, birth_time=birth_time)
    year_ganji = compute_year_ganji()

    # 점성술은 좌표를 찾아야 해서 실패할 수 있습니다. 없으면 없는 채로 검사합니다.
    astro = None
    try:
        from astrology import compute_astrology

        astro = compute_astrology(
            birth_date=birth_date, birth_time=birth_time, birth_place=place
        )
    except Exception as exc:                        # 좌표 조회 실패 등
        print(f" (점성술 계산을 건너뜁니다: {type(exc).__name__})")
        print()

    birth = {
        "생년월일": birth_date,
        "출생시간": birth_time,
        "출생시간 모름": birth_time is None,
        "출생지역": place,
        "성별": "여성",
        "달력 유형": "양력",
        "이름": "테스트",
    }

    verify_stable_key(birth, saju, astro, year_ganji["연도"])
    payload = verify_payload_identical(saju, astro, year_ganji)
    verify_no_concern_leak(payload, birth)
    verify_calculated_inputs(payload, saju, astro, year_ganji)
    verify_action_rules(payload)
    verify_app_call_site()

    print("=" * 64)
    if _failures:
        print(f" 실패 {len(_failures)}건")
        for name in _failures:
            print(f"   - {name}")
        return 1
    print(" 전부 통과 — 카드는 고민과 독립입니다")
    return 0


if __name__ == "__main__":
    sys.exit(main())
