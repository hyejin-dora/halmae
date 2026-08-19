"""대운 · 세운 계산 검증 (Gemini 호출 없음 · Supabase 쓰기 없음)

    python test_daeun.py

이번에 처음 들어오는 계산이라, 할매(Gemini)에 연결하기 전에
계산 자체가 맞는지부터 확인합니다.

확인하는 것
    1. 순행 / 역행 규칙이 네 경우(양남·음남·양녀·음녀) 모두 맞는지
    2. 대운수(교운 시점)가 절기까지의 거리 ÷ 3 규칙대로 나오는지
    3. 대운 구간이 시간 순서대로 끊김 없이 이어지는지
    4. 대운 간지가 60갑자를 한 칸씩 제대로 옮겨가는지
    5. '지금 어느 대운인지' 고르는 규칙이 맞는지
    6. 세운이 코드에서 연도를 가져오는지 (2026 하드코딩이 아닌지)
    7. Gemini 로 나가는 글에 '다시 계산하지 말라' 는 규칙이 붙어 있는지
    8. 사주 계산에 회귀(regression)가 없는지

여기 쓰는 생년월일은 전부 개발용 예시(fixture)입니다. 실제 사용자 정보가 아닙니다.
"""

import sys
from datetime import date, time

import daeun as daeun_module
from daeun import (
    DIRECTION_BACKWARD,
    DIRECTION_FORWARD,
    DaeunError,
    compute_daeun,
    compute_sewoon,
    daeun_direction,
    describe,
    format_year_flow_for_prompt,
    gapja_index,
    normalize_gender,
)
from saju import CHEONGAN, JIJI, compute_saju

_failures: list[str] = []


def section(title: str) -> None:
    print()
    print(f"[{title}]")


def check(label: str, ok: bool, detail: str = "") -> None:
    print(f"  [{'PASS' if ok else 'FAIL'}] {label}" + (f"  — {detail}" if detail else ""))
    if not ok:
        _failures.append(label)


# ---------------------------------------------------------------
#  개발용 예시 (fixture) — 실제 사용자 정보가 아닙니다
# ---------------------------------------------------------------
FIXTURES = [
    # (이름표, 생년월일, 출생시간, 성별, 기대 방향)
    ("음간년 여자", date(1999, 4, 12), time(8, 49), "여성", DIRECTION_FORWARD),
    ("음간년 남자", date(1999, 4, 12), time(8, 49), "남성", DIRECTION_BACKWARD),
    ("양간년 남자", date(1984, 9, 3), time(14, 20), "남성", DIRECTION_FORWARD),
    ("양간년 여자", date(1984, 9, 3), time(14, 20), "여성", DIRECTION_BACKWARD),
    ("출생시간 모름", date(1970, 1, 30), None, "여성", None),
    ("절입 직후 출생", date(2000, 2, 5), time(3, 0), "남성", None),
    ("절입 직전 출생", date(2000, 2, 3), time(23, 30), "여성", None),
]


def build(fixture) -> tuple[dict, dict]:
    """예시 하나로 사주와 대운을 계산합니다."""
    _, birth_date, birth_time, gender, _ = fixture
    saju = compute_saju(birth_date, birth_time, "양력")
    return saju, compute_daeun(saju, gender)


# ===============================================================
def check_direction() -> None:
    section("1. 순행 / 역행 — 년간 음양 × 성별")

    for fixture in FIXTURES:
        label, birth_date, birth_time, gender, expected = fixture
        if expected is None:
            continue
        saju = compute_saju(birth_date, birth_time, "양력")
        year_stem = saju["년주"]["천간"]["한글"]
        got = daeun_direction(saju, gender)
        check(f"{label} ({year_stem}년 · {gender}) → {expected}",
              got == expected, got)

    # 성별을 모르면 계산하지 않습니다 (임의로 정하면 절반이 틀립니다)
    saju = compute_saju(date(1999, 4, 12), time(8, 49), "양력")
    try:
        compute_daeun(saju, "응답하지 않음")
        check("성별 미응답이면 대운을 계산하지 않는다", False, "예외가 나지 않았습니다")
    except DaeunError as exc:
        check("성별 미응답이면 대운을 계산하지 않는다", True, str(exc)[:30] + "...")

    check("normalize_gender 가 표기 흔들림을 받아준다",
          normalize_gender("남자") == "male"
          and normalize_gender("여성") == "female"
          and normalize_gender("응답하지 않음") is None)


# ===============================================================
def check_start_age() -> None:
    section("2. 대운수 — 절입까지의 거리 ÷ 3 (3일 = 1년)")

    for fixture in FIXTURES:
        label = fixture[0]
        gender = fixture[3]
        if normalize_gender(gender) is None:
            continue
        saju, result = build(fixture)
        basis = result["basis"]
        expected = max(1, int(basis["exact_years"] + 0.5))
        check(f"{label} · 대운수 {result['start_age']} = round({basis['exact_years']})",
              result["start_age"] == expected,
              f"{basis['gap_days']}일 → {basis['boundary_term']} 기준")

        # 절입까지의 거리는 한 절기 구간(약 30일)을 넘을 수 없습니다.
        check(f"{label} · 절입까지 거리가 한 절기 안이다",
              0 <= basis["gap_days"] <= 32, f"{basis['gap_days']}일")

    check("대운수는 최소 1 이상이다",
          all(build(f)[1]["start_age"] >= 1
              for f in FIXTURES if normalize_gender(f[3])))


# ===============================================================
def check_periods_continuous() -> None:
    section("3. 대운 구간 — 시간 순서대로 끊김 없이 이어지는지")

    for fixture in FIXTURES:
        label = fixture[0]
        if normalize_gender(fixture[3]) is None:
            continue
        _, result = build(fixture)
        periods = result["periods"]

        check(f"{label} · 대운을 {len(periods)}개 만들었다", len(periods) >= 8)

        gaps = [
            (periods[i + 1]["start_year"] - periods[i]["end_year"])
            for i in range(len(periods) - 1)
        ]
        check(f"{label} · 구간 사이에 빈 해가 없다 (끝난 다음 해에 바로 시작)",
              all(gap == 1 for gap in gaps), str(sorted(set(gaps))))

        ages = [
            (periods[i + 1]["start_age"] - periods[i]["start_age"])
            for i in range(len(periods) - 1)
        ]
        check(f"{label} · 한 대운은 10년씩이다",
              all(step == 10 for step in ages)
              and all(p["end_age"] - p["start_age"] == 9 for p in periods))

        check(f"{label} · 연도가 계속 커진다 (역행이어도 시간은 앞으로)",
              all(periods[i]["start_year"] < periods[i + 1]["start_year"]
                  for i in range(len(periods) - 1)))

        check(f"{label} · 나이와 연도가 서로 맞는다",
              all(p["start_year"] - p["start_age"] == result["birth_year"]
                  for p in periods))


# ===============================================================
def check_pillar_progression() -> None:
    section("4. 대운 간지 — 월주에서 60갑자를 한 칸씩")

    for fixture in FIXTURES:
        label = fixture[0]
        if normalize_gender(fixture[3]) is None:
            continue
        saju, result = build(fixture)
        month = saju["월주"]
        month_index = gapja_index(month["천간"]["한글"], month["지지"]["한글"])
        step = 1 if result["forward"] else -1

        expected = []
        for order in range(len(result["periods"])):
            index = (month_index + step * (order + 1)) % 60
            expected.append(CHEONGAN[index % 10] + JIJI[index % 12])

        got = [p["pillar"] for p in result["periods"]]
        check(f"{label} · 월주 {month['한글']} 다음부터 {result['direction']}",
              got == expected, " ".join(got[:4]) + " ...")

        check(f"{label} · 대운 간지가 서로 다르다 (10개 안에서 겹치지 않음)",
              len(set(got)) == len(got))


# ===============================================================
def check_current_period() -> None:
    section("5. 지금 어느 대운인지 — 파이썬 결과만으로 알 수 있는지")

    for fixture in FIXTURES:
        label = fixture[0]
        if normalize_gender(fixture[3]) is None:
            continue
        _, result = build(fixture)
        current = result["current"]
        year = result["current_year"]

        if current is None:
            check(f"{label} · 대운 밖이면 이유를 밝힌다",
                  result["current_status"] in ("대운 시작 전", "계산 구간 밖"),
                  result["current_status"])
            continue

        check(f"{label} · 지금 대운은 {current['pillar']} "
              f"({current['start_year']}~{current['end_year']})",
              current["start_year"] <= year <= current["end_year"],
              f"올해 {year}년")
        check(f"{label} · 지금 대운은 딱 하나다",
              sum(1 for p in result["periods"]
                  if p["start_year"] <= year <= p["end_year"]) == 1)

    # 옛날 사람 · 미래 사람으로 경계를 밀어봅니다.
    saju = compute_saju(date(2024, 6, 1), time(9, 0), "양력")
    result = compute_daeun(saju, "여성")
    check("아직 대운에 들어서지 않은 사람은 그렇다고 알려준다",
          result["current"] is None and result["current_status"] == "대운 시작 전",
          result["current_status"])

    saju = compute_saju(date(1940, 3, 3), time(9, 0), "양력")
    result = compute_daeun(saju, "남성")
    check("오래 사신 분도 현재 대운을 찾는다",
          result["current"] is not None,
          result["current"]["pillar"] if result["current"] else "-")


# ===============================================================
def check_sewoon() -> None:
    section("6. 세운 — 연도를 코드에서 가져오는지")

    now = compute_sewoon()
    check("세운에 연도와 간지가 들어 있다",
          isinstance(now["year"], int) and len(now["pillar"]) == 2,
          f"{now['year']} {now['pillar']}")

    check("올해 연도는 오늘 날짜에서 나온다 (하드코딩 아님)",
          now["year"] in (date.today().year, date.today().year - 1),
          f"오늘 {date.today()} → 사주 기준 {now['year']}년")

    # 60년 주기가 맞는지 (같은 간지가 60년마다 돌아옵니다)
    a = compute_sewoon(date(2026, 6, 1))
    b = compute_sewoon(date(2086, 6, 1))
    check("60년 뒤 같은 간지가 돌아온다", a["pillar"] == b["pillar"],
          f"{a['year']} {a['pillar']} / {b['year']} {b['pillar']}")

    # 입춘 전은 지난해로 봅니다
    before = compute_sewoon(date(2026, 1, 20))
    after = compute_sewoon(date(2026, 3, 20))
    check("입춘 전은 아직 지난해 세운이다",
          before["year"] == after["year"] - 1,
          f"1월 → {before['year']}년 / 3월 → {after['year']}년")

    # 연도를 코드에 박아두면 해가 바뀌었을 때 조용히 틀린 값이 나갑니다.
    # (설명용 주석·docstring 의 예시는 실행되지 않으므로 세지 않습니다)
    import ast

    tree = ast.parse(open("daeun.py", encoding="utf-8").read())
    hardcoded = [
        node.value for node in ast.walk(tree)
        if isinstance(node, ast.Constant)
        and isinstance(node.value, int)
        and not isinstance(node.value, bool)
        and 1900 <= node.value <= 2200
    ]
    check("실행되는 코드에 연도가 박혀 있지 않다", not hardcoded, str(hardcoded))


# ===============================================================
def check_prompt_lock() -> None:
    section("7. Gemini 로 나가는 글 — 계산은 파이썬, 해석만 Gemini")

    saju, result = build(FIXTURES[0])
    sewoon = compute_sewoon()
    text = format_year_flow_for_prompt(result, sewoon, saju)

    check("대운 간지가 계산값 그대로 들어간다",
          result["current"]["pillar"] in text, result["current"]["pillar"])
    check("대운 기간(연도)이 들어간다",
          str(result["current"]["start_year"]) in text)
    check("세운 간지와 연도가 들어간다",
          sewoon["pillar"] in text and str(sewoon["year"]) in text)

    for rule in ("다시 계산하지 말고", "스스로 뽑아내려 하지 마라",
                 "만들어내지 마라", "월운"):
        check(f"'{rule}' 규칙이 붙어 있다", rule in text)

    check("생년월일·이름 같은 개인정보가 이 글에 없다",
          "1999" not in text and "04-12" not in text)

    # 성별을 모르면 대운 없이도 글이 만들어져야 합니다 (앱이 죽지 않게)
    only_sewoon = format_year_flow_for_prompt(None, sewoon, saju)
    check("대운이 없어도 글이 만들어진다",
          "대운을 근거로 든 해석은 하지 말 것" in only_sewoon)

    # 개발용 요약 (CLI 출력 모양)
    text = describe(result, sewoon)
    for line in ("[DAEUN CALCULATION]", "direction", "start_age",
                 "current_pillar", "current_period",
                 "[SEWOON CALCULATION]", "year", "pillar"):
        check(f"개발용 요약에 '{line}' 이 있다", line in text)


# ===============================================================
def check_no_regression() -> None:
    section("8. 기존 사주 계산에 회귀가 없는지")

    saju = compute_saju(date(1999, 4, 12), time(8, 49), "양력")
    check("년주·월주·일주·시주가 그대로다",
          (saju["년주"]["한글"], saju["월주"]["한글"],
           saju["일주"]["한글"], saju["시주"]["한글"])
          == ("기묘", "무진", "갑오", "무진"),
          " ".join(saju["기둥"][n]["한글"] for n in
                   ("년주", "월주", "일주", "시주")))

    check("오행 합계가 8이다 (표면 8자)", sum(saju["오행 분포"].values()) == 8)
    check("일간이 그대로다", saju["일간"]["한글"] == "갑")

    check("대운이 쓰는 기준 시각이 사주에서 나온다",
          saju.get("기준 시각(UTC)") is not None
          and saju.get("기준 율리우스일") is not None)

    # 대운 계산이 사주 dict 를 건드리지 않아야 합니다.
    before = dict(saju)
    compute_daeun(saju, "여성")
    check("대운 계산이 사주 값을 바꾸지 않는다",
          all(saju[key] is before[key] for key in before))

    # daeun 모듈이 Gemini 를 부르지 않는지 (계산 전용 모듈)
    source = open("daeun.py", encoding="utf-8").read()
    check("daeun.py 는 Gemini 를 부르지 않는다",
          "genai" not in source and "ask_" not in source)
    check("daeun.py 는 화면(streamlit)을 모른다",
          "import streamlit" not in source)


# ===============================================================
def check_service_wiring() -> None:
    section("9. 서비스 연결 — 계산값이 그대로 할매에게 가는지")

    import ast

    import halmae_ai

    app_source = open("app.py", encoding="utf-8").read()
    app_tree = ast.parse(app_source)

    saju, daeun_result = build(FIXTURES[0])
    sewoon = compute_sewoon()
    answers = {"고민 분야": "취업/커리어", "추가 질문": "이직해도 될까요",
               "이름": "예시", "성별": "여성"}

    payload = halmae_ai.build_year_flow_payload(
        answers, saju, None, daeun_result, sewoon
    )
    sent = payload["question"]

    # (5) Gemini 로 나가는 대운·세운 값이 파이썬 계산값 그대로인지
    current = daeun_result["current"]
    check("나가는 대운 간지가 파이썬 계산값 그대로다",
          current["pillar"] in sent, current["pillar"])
    check("나가는 대운 기간이 파이썬 계산값 그대로다",
          f"{current['start_year']}년 ~ {current['end_year']}년" in sent)
    check("나가는 세운 간지·연도가 파이썬 계산값 그대로다",
          sewoon["pillar"] in sent and str(sewoon["year"]) in sent)
    check("대운 방향과 대운수도 함께 넘어간다",
          daeun_result["direction"] in sent
          and f"대운수 {daeun_result['start_age']}" in sent)

    # (6) 모델에게 계산을 시키는 문장이 없는지
    lowered = sent
    for banned in ("계산해줘", "계산해 보거라", "산출해", "뽑아보거라", "구해라"):
        check(f"'{banned}' 같은 계산 지시가 없다", banned not in lowered)
    check("'다시 계산하지 말고' 가 프롬프트에 있다", "다시 계산하지 말고" in sent)
    check("페르소나도 '스스로 뽑아내지 마라' 를 말한다",
          "스스로 뽑아내거나" in payload["system_instruction"]
          or "스스로 뽑아내려" in payload["system_instruction"])
    check("1~3단계 페르소나는 예전 그대로 대운을 안 쓴다",
          "대운·연운·세운 데이터는 제공되지 않는다"
          in halmae_ai.SYSTEM_INSTRUCTION)
    check("올해의 카드 페르소나도 예전 그대로다",
          "대운·연운·세운 데이터는 제공되지 않는다"
          in halmae_ai.YEAR_CARD_SYSTEM_INSTRUCTION)

    # (7) Step1 마지막 예고 문장
    teaser = halmae_ai.STEP1_YEAR_FLOW_TEASER
    check("Step1 예고 문장에 대운·세운이 들어 있다",
          "대운" in teaser and "세운" in teaser)
    check("Step1 화면이 예고 문장을 그린다",
          "STEP1_YEAR_FLOW_TEASER" in app_source.split("def render_step1")[1]
          .split("\ndef ")[0])
    for step_name in ("render_step2", "render_step3"):
        body = app_source.split(f"def {step_name}")[1].split("\ndef ")[0]
        check(f"{step_name} 은 같은 예고를 되풀이하지 않는다",
              "STEP1_YEAR_FLOW_TEASER" not in body)

    # (8) Step3 → 올해의 흐름 → 올해의 카드 순서
    result_body = app_source.split("def render_result()")[1].split("\ndef ")[0]
    flow_at = result_body.find("render_year_flow()")
    card_at = result_body.find("render_year_card()")
    check("결과 화면이 흐름을 먼저, 카드를 나중에 그린다",
          0 < flow_at < card_at, f"흐름 {flow_at} · 카드 {card_at}")
    check("흐름을 안 봤으면 카드를 그리지 않는다",
          "if render_year_flow():" in result_body)
    check("Step 배지는 1/3·2/3·3/3 그대로다",
          "{step} / 3" in result_body)
    check("올해의 흐름에는 Step 번호를 붙이지 않는다",
          "4 / 3" not in result_body and "4/3" not in result_body)

    # (9) year_flow_view 는 rerun 으로 중복되지 않는지 (track 으로 남깁니다)
    flow_body = app_source.split("def render_year_flow()")[1].split("\ndef ")[0]
    check('year_flow_view 는 track() 으로 남긴다 (세션당 한 번)',
          'track("year_flow_view")' in flow_body)
    check('year_flow_click 은 track_action() 으로 남긴다',
          'track_action("year_flow_click")' in flow_body)

    # (10) 올해의 카드 정책은 그대로인지
    card_body = app_source.split("def ensure_year_card()")[1].split("\ndef ")[0]
    card_code = "\n".join(
        line for line in card_body.splitlines()
        if not line.strip().startswith("#")
    )
    for leak in ("year_flow", "daeun", "sewoon", "history",
                 "고민 분야", "추가 질문"):
        check(f"카드 준비에 '{leak}' 이 섞이지 않는다", leak not in card_code)
    check("카드 열쇠 만드는 방식이 그대로다",
          "card_store.build_card_key(" in card_code)

    card_payload_source = open("halmae_ai.py", encoding="utf-8").read()
    card_prompt = card_payload_source.split("def build_year_card_prompt")[1] \
        .split("\ndef ")[0]
    for leak in ("daeun", "sewoon", "대운", "세운"):
        check(f"카드 프롬프트에 '{leak}' 이 없다", leak not in card_prompt)

    # (11) 모바일 — 새로 넣은 칸이 좁은 화면 규칙에 들어 있는지
    import theme

    css = theme.build_css()
    for name in ("halmae-luck-row", "halmae-luck-cell",
                 "halmae-luck-value", "halmae-teaser", "halmae-flow-badge"):
        check(f"CSS 에 {name} 가 있다", name in css)
    mobile = css.split("@media (max-width: 480px)")[-1]
    check("좁은 화면에서 대운 칸 크기를 줄인다", ".halmae-luck-cell" in mobile)
    # 고정 폭(width: …)을 주면 좁은 화면에서 칸이 밖으로 밀려 가로 스크롤이
    # 생깁니다. flex + min-width 로만 폭을 잡았는지 확인합니다.
    luck_css = css.split(".halmae-luck-cell {")[1].split("}")[0]
    check("대운 칸은 고정 폭을 쓰지 않는다 (가로 스크롤 방지)",
          "flex:" in luck_css and "min-width:" in luck_css
          and "\n        width:" not in luck_css,
          luck_css.strip().replace("\n", " ")[:60])

    # 대운·세운이 행동 로그에 새어 들어가지 않는지
    import analytics

    check("analytics 가 저장하는 칸은 예전 여섯 개 그대로다",
          analytics.FIELDNAMES
          == ["session_id", "timestamp", "event_name", "concern",
              "model", "step"],
          str(analytics.FIELDNAMES))
    # 설명(docstring · 주석)에는 "생년월일은 여기까지 오지 않는다" 같은 문장이
    # 일부러 들어 있습니다. 실제로 도는 코드 줄만 남겨서 봅니다.
    write_event_node = next(
        node for node in ast.walk(app_tree)
        if isinstance(node, ast.FunctionDef) and node.name == "_write_event"
    )
    statements = write_event_node.body
    if ast.get_docstring(write_event_node):
        statements = statements[1:]      # 설명글은 빼고 실제 코드만
    write_event = "\n".join(ast.unparse(node) for node in statements)
    for leak in ("daeun", "sewoon", "생년월일", "출생", "추가 질문"):
        check(f"이벤트 한 줄에 '{leak}' 이 들어가지 않는다", leak not in write_event)

    # 새 이벤트가 등록되어 있는지
    for name in ("year_flow_click", "year_flow_view"):
        check(f"{name} 이 analytics 에 등록되어 있다",
              name in analytics.EVENT_NAMES)
    check("year_card_click 이라는 중복 이름을 새로 만들지 않았다",
          "year_card_click" not in analytics.EVENT_NAMES
          and "year_card_click" not in app_source)

    # 대운 실패가 Step1~3 을 죽이지 않는지
    luck_body = app_source.split("def compute_luck_info")[1].split("\ndef ")[0]
    check("대운 계산 실패를 붙잡아 문구로만 남긴다",
          "except Exception" in luck_body
          and "daeun_error" in luck_body
          and "raise" not in luck_body)
    check("대운이 실패해도 흐름 구간에서만 안내한다",
          "st.warning(st.session_state.year_flow_error)" in flow_body)

    # 계산 재사용 (지문)
    prepare = app_source.split("def prepare_calculations")[1].split("\ndef ")[0]
    check("입력이 그대로면 다시 계산하지 않는다",
          "input_fingerprint" in prepare and "return" in prepare)
    check("입력이 바뀌면 예전 계산값을 비운다",
          "clear_calculations()" in prepare)

    # 처리시간이 사용자 화면에 새지 않는지
    tree_calls = [
        node for node in ast.walk(app_tree)
        if isinstance(node, ast.Call)
    ]
    del tree_calls
    perf_at = app_source.find("perf.format_summary")
    check("처리시간 요약은 개발자 화면 안쪽에만 있다",
          perf_at > 0
          and "USE_DEV_MODE" in app_source[max(0, perf_at - 1500):perf_at],
          "개발자용 · 처리시간 보기")


# ===============================================================
def check_gender_ui_and_display() -> None:
    section("10. 성별 안내와 대운 표시 — 나이보다 연도")

    import ast

    import daeun as module
    import theme

    app_source = open("app.py", encoding="utf-8").read()
    app_tree = ast.parse(app_source)
    css = theme.build_css()

    def literal(name: str):
        """app.py 에 적힌 상수 값을 그대로 읽어옵니다."""
        for node in ast.walk(app_tree):
            if (isinstance(node, ast.Assign)
                    and any(getattr(target, "id", "") == name
                            for target in node.targets)):
                return ast.literal_eval(node.value)
        return None

    # --- (1) 성별 칸 아래 짧은 안내문 ---------------------------
    note = literal("GENDER_FIELD_NOTE")
    check("성별 안내 문구가 있다", bool(note), str(note))
    check("안내 문구가 대운과 성별을 함께 말한다",
          "대운" in (note or "") and "성별" in (note or ""))
    check("안내 문구가 한 문장으로 짧다 (동의문처럼 길지 않게)",
          note is not None and len(note) <= 60 and note.count(".") <= 1,
          f"{len(note or '')}자")

    input_body = app_source.split("def render_input()")[1].split("\ndef ")[0]
    gender_at = input_body.find('key="in_gender"')
    note_at = input_body.find("GENDER_FIELD_NOTE")
    check("안내문이 성별 선택 바로 아래에 있다",
          0 < gender_at < note_at, f"성별 {gender_at} · 안내 {note_at}")
    check("성별 선택지는 예전 그대로다",
          '"여성", "남성", "응답하지 않음"' in input_body)

    # 안내문을 그리는 그 줄만 봅니다.
    # (같은 함수 안의 다른 st.warning — 이름 미입력 안내 — 은 상관없습니다)
    note_line = input_body[note_at - 200:note_at + 200]
    check("안내문은 halmae-fieldnote 로 그린다 (경고 상자가 아님)",
          'class="halmae-fieldnote"' in note_line
          and "st.warning" not in note_line
          and "st.error" not in note_line
          and "st.info" not in note_line)

    field_css = css.split(".halmae-fieldnote {")[1].split("}")[0]
    check("안내문에 테두리·배경이 없다 (경고처럼 보이지 않게)",
          "border:" not in field_css and "background" not in field_css,
          field_css.strip().replace("\n", " ")[:60])
    check("한국어 낱말 가운데가 끊기지 않는다 (모바일 줄바꿈)",
          "word-break: keep-all" in field_css)
    check("좁은 화면에서 글자를 한 단계 줄인다",
          ".halmae-fieldnote" in css.split("@media (max-width: 480px)")[-1])

    # --- (2) 성별 미선택은 '실패' 가 아니라 '건너뜀' --------------
    luck_body = app_source.split("def compute_luck_info")[1].split("\ndef ")[0]
    check("성별을 안 고르면 daeun_skipped 로 표시한다",
          "daeun_skipped = True" in luck_body)
    check("성별 미선택을 오류로 세우지 않는다 (daeun_error 를 쓰지 않음)",
          "daeun_error = GENDER" not in luck_body
          and "GENDER_REQUIRED_MESSAGE" not in luck_body)

    flow_body = app_source.split("def ensure_year_flow()")[1].split("\ndef ")[0]
    check("건너뛴 경우에도 흐름을 그대로 진행한다",
          "daeun_skipped" in flow_body and "no_daeun_reason" in flow_body)
    check("계산 '실패' 만 안내로 막는다",
          "st.session_state.daeun_error and not st.session_state.daeun_info"
          in flow_body)

    render_flow = app_source.split("def render_year_flow()")[1].split("\ndef ")[0]
    check("대운이 없으면 A 파트를 통째로 생략한다",
          "if has_daeun:" in render_flow
          and "지금 네가 지나고 있는 대운" in render_flow)
    check("대운이 없을 때 제목에 '대운' 을 적지 않는다",
          "YEAR_FLOW_SUBTITLE_SEWOON" in render_flow)

    facts_body = app_source.split("def render_luck_facts()")[1].split("\ndef ")[0]
    check("생략 안내는 한 줄뿐이다 (긴 설명을 되풀이하지 않음)",
          "GENDER_SKIPPED_NOTE" in facts_body)
    check("생략 안내 문구 자체가 짧다",
          len(module.GENDER_SKIPPED_NOTE) <= 40,
          f"{len(module.GENDER_SKIPPED_NOTE)}자 · {module.GENDER_SKIPPED_NOTE}")

    # --- (3) 대운 표시 — 큰 글씨는 연도, 나이는 보조 -------------
    chip = facts_body.split('_luck_chip(\n            "지금 대운",')[1] \
        .split(")")[0]
    check("대운 칸의 큰 글씨는 연도 범위다",
          "start_year" in chip and "end_year" in chip and "start_age" not in chip,
          " ".join(chip.split())[:70])
    check("간지는 작은 글씨(보조)로 내려간다", "pillar_hanja" in chip)
    # 칸(chip)을 만드는 구간에는 나이가 들어가면 안 됩니다.
    # 나이는 그 아래 발치 안내(foot)에서만 나와야 합니다.
    chips_part = facts_body.split("cells = []")[1].split("foot = (")[0]
    check("칸(큰 글씨)에는 만 나이가 들어가지 않는다",
          "start_age" not in chips_part and "end_age" not in chips_part)
    check("만 나이는 발치 안내에서만 나온다",
          "start_age" in facts_body.split("foot = (")[1])
    check("나이가 만세력마다 다를 수 있다고 알려준다",
          "만세력마다 한 해쯤" in facts_body)
    check("연도를 기준으로 보라고 안내한다", "연도를 기준으로" in facts_body)

    # --- (4) 할매에게도 같은 규칙을 건다 -------------------------
    saju, daeun_result = build(FIXTURES[0])
    sewoon = compute_sewoon()
    with_daeun = format_year_flow_for_prompt(daeun_result, sewoon, saju)
    check("프롬프트도 '나이보다 연도로' 를 못 박는다",
          "나이보다" in with_daeun and "만세력마다 한 해쯤" in with_daeun)

    only_sewoon = format_year_flow_for_prompt(
        None, sewoon, saju, module.GENDER_SKIPPED_FOR_PROMPT
    )
    check("대운이 없으면 그 이유를 프롬프트에 적어 보낸다",
          "성별을 알 수 없어" in only_sewoon)
    check("대운 이야기를 하지 말라고 못 박는다",
          "대운 이야기는 아예 하지 마라" in only_sewoon)

    # --- (5) 세운 전용 과제문 -----------------------------------
    import halmae_ai

    answers = {"고민 분야": "연애", "추가 질문": "", "성별": "응답하지 않음"}
    sewoon_prompt = halmae_ai.build_year_flow_prompt(
        answers, saju, None, None, sewoon, module.GENDER_SKIPPED_FOR_PROMPT
    )
    check("대운이 없으면 세운 전용 과제문을 쓴다",
          "올해의 흐름 (세운)" in sewoon_prompt)
    check("A 파트를 비우라고 지시한다",
          "빈 글자로 두어라" in sewoon_prompt)
    check("성별을 알려달라고 조르지 말라고 못 박는다",
          "성별을 알려달라고 요구하거나" in sewoon_prompt)
    check("대운이 있으면 원래 과제문을 쓴다",
          "올해의 흐름 (대운 × 세운)" in halmae_ai.build_year_flow_prompt(
              answers, saju, None, daeun_result, sewoon))

    # 스키마가 A 파트를 비워둘 수 있는지 (세운만 있는 응답을 받아야 하므로)
    empty = halmae_ai.YearFlowAnswer(
        opening="ㄱ", sewoon_reading="ㄴ", push="ㄷ",
        careful="ㄹ", concern_link="ㅁ", closing="ㅂ",
    )
    check("daeun_reading 없이도 응답 구조가 만들어진다",
          empty.daeun_reading == "")

    # Mock 도 같은 모양인지 (개발 중 화면이 실제와 달라지지 않게)
    from mock_ai import mock_year_flow

    mock_without = mock_year_flow(answers, saju, None, sewoon)
    check("Mock 도 대운이 없으면 A 파트를 비운다",
          mock_without.daeun_reading == "")
    mock_with = mock_year_flow(answers, saju, daeun_result, sewoon)
    check("Mock 은 대운이 있으면 A 파트를 채운다",
          bool(mock_with.daeun_reading))

    # --- (6) 손대지 말아야 할 것들 -------------------------------
    check("올해의 카드 정책은 그대로다 (성별은 열쇠에만 쓰인다)",
          "성별" not in halmae_ai.build_year_card_prompt(
              saju, None, sewoon["ganji"], []))
    check("Step1~3 과제문은 그대로다",
          "대운" not in halmae_ai.STEP1_TASK
          and "대운" not in halmae_ai.STEP2_TASK)


# ===============================================================
def main() -> int:
    print("=" * 64)
    print(" 할매 · 대운 / 세운 계산 검증 (Gemini 호출 없음)")
    print("=" * 64)
    print(f" 계산 기준 · 방향   {daeun_module.DIRECTION_RULE}")
    print(f" 계산 기준 · 절기   {daeun_module.TERM_RULE}")
    print(f" 계산 기준 · 대운수 {daeun_module.START_AGE_RULE}")
    print(f" 계산 기준 · 간지   {daeun_module.PILLAR_RULE}")

    check_direction()
    check_start_age()
    check_periods_continuous()
    check_pillar_progression()
    check_current_period()
    check_sewoon()
    check_prompt_lock()
    check_no_regression()
    check_service_wiring()
    check_gender_ui_and_display()

    print()
    print("=" * 64)
    if _failures:
        print(f" 실패 {len(_failures)}건")
        for name in _failures:
            print(f"   - {name}")
        return 1
    print(" 전부 통과 — 대운·세운 계산을 할매에게 넘겨도 되는 상태입니다")
    return 0


if __name__ == "__main__":
    sys.exit(main())
