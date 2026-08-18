"""사주 계산 파이프라인 진단 — 개발 테스트 전용

    python test_saju_pipeline.py                     # 기본 케이스 + 검증 전체
    python test_saju_pipeline.py 1999-04-12 08:49    # 원하는 생년월일시로
    python test_saju_pipeline.py 1985-06-15 모름 음력 윤달

이 파일이 하는 일
    1. Gemini 에 보내기 직전의 saju_data 를 사람이 읽을 수 있게 출력합니다.
    2. 오행을 글자 하나씩 펼쳐 세고, 합계가 기준과 맞는지 assert 합니다.
    3. 일주를 korean_lunar_calendar 의 일진과 대조합니다. (1900~2050 전 구간)
    4. 절기 계산과 네 기둥 공식(오호둔·오서둔·절기 경계)을 검증합니다.
    5. Gemini 프롬프트에 '다시 계산하지 말라'는 못이 박혀 있는지 확인합니다.
    6. 화면에 뜨는 명식이 Gemini 응답이 아니라 파이썬 계산값인지 확인합니다.

절대 하지 않는 일
    - Gemini API 호출 (halmae_ai 의 프롬프트 조립 함수만 부릅니다)
    - analytics / Supabase 기록 (db · analytics 를 아예 import 하지 않습니다)
    - 생년월일이 운영 로그에 남는 일 (여기서 찍는 값은 터미널에만 나옵니다)

  ⚠ 출력에 생년월일·출생시간이 그대로 들어갑니다.
     개발용 터미널에서만 쓰고, 결과를 파일이나 이슈에 붙여넣지 마세요.
"""

import sys
from datetime import date, datetime, time, timedelta, timezone

from korean_lunar_calendar import KoreanLunarCalendar

from saju import (
    CHEONGAN,
    JIJI,
    _from_julian_day,
    _to_julian_day,
    OHAENG_BASIS,
    OHAENG_BASIS_NO_HOUR,
    OHAENG_ORDER,
    SOLAR_TERM_SOURCE,
    SOLAR_TERMS,
    _day_pillar_index,
    compute_saju,
    find_solar_term,
    format_saju_for_prompt,
    saju_facts,
)

KST = timezone(timedelta(hours=9))

_failures: list[str] = []


def check(label: str, ok: bool, detail: str = "") -> None:
    """assert 대신 — 하나 틀려도 나머지 검사를 계속 볼 수 있게."""
    mark = "PASS" if ok else "FAIL"
    print(f"  [{mark}] {label}" + (f"  — {detail}" if detail else ""))
    if not ok:
        _failures.append(label)


# ===============================================================
#  1. Gemini 에 넘어가기 직전의 값
# ===============================================================
def dump_saju(saju: dict, birth_time: time | None) -> None:
    facts = saju_facts(saju)
    solar = saju["양력 날짜"]
    stamp = (
        datetime.combine(solar, birth_time).isoformat()
        if birth_time
        else f"{solar.isoformat()} (출생시간 모름)"
    )

    print("[SAJU CALCULATION RESULT]")
    print(f"solar_datetime: {stamp}")
    print(f"year_pillar:    {facts['년주']}")
    print(f"month_pillar:   {facts['월주']}")
    print(f"day_pillar:     {facts['일주']}")
    print(f"hour_pillar:    {facts['시주'] or '(없음) ' + str(facts['시주 제외 사유'])}")
    print(f"day_master:     {facts['일간']}")
    print(f"five_elements:  {facts['오행 요약']}   ({facts['오행 기준']})")
    print("raw_payload_to_gemini:")
    for line in format_saju_for_prompt(saju).splitlines():
        print(f"    {line}")
    print()


# ===============================================================
#  2. 오행 — 글자 하나씩 세고 합계를 맞춰봅니다
# ===============================================================
def verify_ohaeng(saju: dict) -> None:
    print("[OHAENG BREAKDOWN]")
    facts = saju_facts(saju)
    rows = facts["오행 근거"]

    tally = {name: 0 for name in OHAENG_ORDER}
    for row in rows:
        print(f"  {row['기둥']} {row['자리']}  {row['글자']}({row['한자']}) -> {row['오행']}")
        tally[row["오행"]] += 1

    print("  " + "-" * 40)
    print("  " + " / ".join(f"{name} {tally[name]}" for name in OHAENG_ORDER))
    print(f"  세는 기준: {facts['오행 기준']}")
    print()

    expected_basis = (
        OHAENG_BASIS if facts["시주 계산 여부"] else OHAENG_BASIS_NO_HOUR
    )
    expected_count = 8 if facts["시주 계산 여부"] else 6

    print("[OHAENG ASSERT]")
    check("세는 기준이 한 가지로 통일되어 있다", facts["오행 기준"] == expected_basis,
          facts["오행 기준"])
    check(f"펼친 글자 수 = {expected_count}", len(rows) == expected_count,
          f"{len(rows)}자")
    check("펼친 합계 = 계산 결과의 오행 개수", tally == facts["오행 개수"],
          f"{tally} vs {facts['오행 개수']}")
    check(f"오행 총합 = {expected_count}", sum(tally.values()) == expected_count,
          str(sum(tally.values())))
    check("지장간은 세지 않았다 (지지 1자당 오행 1개)",
          sum(1 for r in rows if r["자리"] == "지지") == expected_count // 2)

    # 위 check 들과 같은 내용을 요구사항대로 assert 로도 한 번 더 박아둡니다.
    assert sum(tally.values()) == expected_count
    assert tally == facts["오행 개수"]
    print()


# ===============================================================
#  3. 일주 대조 — korean_lunar_calendar 의 일진과 맞는지
# ===============================================================
def verify_day_pillar(sample_only: bool = False) -> None:
    print("[DAY PILLAR CROSS-CHECK vs korean_lunar_calendar 일진]")
    start, end = date(1900, 1, 1), date(2050, 12, 31)
    if sample_only:
        start, end = date(1990, 1, 1), date(2000, 12, 31)

    mismatches = []
    checked = 0
    day = start
    while day <= end:
        cal = KoreanLunarCalendar()
        if cal.setSolarDate(day.year, day.month, day.day):
            parts = cal.getGapJaString().split()
            if len(parts) >= 3:
                index = _day_pillar_index(day)
                mine = CHEONGAN[index % 10] + JIJI[index % 12]
                if mine != parts[2][:-1]:
                    mismatches.append((day, mine, parts[2][:-1]))
                checked += 1
        day += timedelta(days=1)

    check(f"{checked:,}일 전부 일치", not mismatches,
          f"불일치 {len(mismatches)}건" if mismatches else f"{start}~{end}")
    for bad in mismatches[:5]:
        print(f"        {bad[0]}: 우리 {bad[1]} / 라이브러리 {bad[2]}")
    print()


# ===============================================================
#  4. 절기 — 두 계산 방식 대조 + 경계에서 월지가 넘어가는지
# ===============================================================
def verify_solar_terms(years=(1985, 1999, 2000, 2024, 2026)) -> None:
    """절기는 두 갈래로 확인합니다.

    (1) saju.py 가 실제로 쓰는 계산(스위스 천체력)과, 예비로 남겨둔
        Meeus 근사식이 서로 얼마나 벌어지는지. 크게 벌어지면 둘 중 하나가
        깨진 것입니다.
    (2) 절입 시각 앞뒤로 몇 분씩 옮겨 태어났다고 놓았을 때, 월지가 정확히
        그 지점에서 한 칸 넘어가는지. 월주가 '음력 월'이 아니라
        '절기 경계' 기준인지를 직접 확인하는 검사입니다.
    """
    print(f"[SOLAR TERM CROSS-CHECK] saju.py 가 쓰는 계산: {SOLAR_TERM_SOURCE}")

    import saju as saju_module

    # (1) 스위스 천체력 vs Meeus 근사식
    worst = 0.0
    worst_label = ""
    saved = saju_module._swe
    try:
        for year in years:
            probe = _to_julian_day(datetime(year, 6, 1, tzinfo=timezone.utc))
            for name, target, _branch in SOLAR_TERMS:
                saju_module._swe = saved          # 천체력
                precise = find_solar_term(probe, target)
                saju_module._swe = None           # 근사식
                approx = find_solar_term(probe, target)
                minutes = abs(precise - approx) * 24 * 60
                if minutes > worst:
                    worst, worst_label = minutes, f"{year} {name}"
    finally:
        saju_module._swe = saved

    check("천체력과 근사식의 절입 시각 차이 < 20분", worst < 20.0,
          f"최대 {worst:.1f}분 ({worst_label})")

    # (2) 절입 경계에서 월지가 한 칸 넘어가는가
    boundary_ok = True
    detail = "2024년 12개 절기 전부"
    probe = _to_julian_day(datetime(2024, 6, 1, tzinfo=timezone.utc))
    for name, target, branch in SOLAR_TERMS:
        moment = _from_julian_day(find_solar_term(probe, target)).astimezone(KST)
        before = moment - timedelta(minutes=5)
        after = moment + timedelta(minutes=5)

        got_before = compute_saju(before.date(), before.time())["적용 절기"]["월지"]
        got_after = compute_saju(after.date(), after.time())["적용 절기"]["월지"]
        want_after = JIJI[branch] + "월"
        want_before = JIJI[(branch - 1) % 12] + "월"

        if (got_before, got_after) != (want_before, want_after):
            boundary_ok = False
            detail = (f"{name} 경계에서 {got_before}→{got_after} "
                      f"(기대 {want_before}→{want_after})")
            break

    check("절입 순간에 월지가 정확히 한 칸 넘어간다", boundary_ok, detail)
    print()


# ===============================================================
#  4-2. 네 기둥의 공식 자체가 명리 규칙과 맞는지
# ===============================================================
def verify_pillar_rules() -> None:
    """만세력 표가 아니라 '규칙'을 직접 확인합니다.

    - 년주: 서기 4년 갑자년 기준 + 입춘에서 해가 바뀐다
    - 월주: 월지는 절기 경계, 월간은 오호둔(五虎遁) — 년간이 인월 천간을 정한다
    - 일주: 율리우스일수(JDN)에서 바로 나오는 60갑자
    - 시주: 시지는 23시 시작 2시간 단위, 시간은 오서둔(五鼠遁) — 일간이 자시를 정한다
    """
    print("[PILLAR RULE CHECK]")

    # --- 년주: 입춘 경계 ---------------------------------------------
    before = compute_saju(date(2024, 2, 4), time(17, 0))   # 2024 입춘 17:27 직전
    after = compute_saju(date(2024, 2, 4), time(18, 0))    # 직후
    check("입춘 전에는 지난해 년주(계묘)", before["년주"]["한글"] == "계묘",
          before["년주"]["한글"])
    check("입춘 후에는 그해 년주(갑진)", after["년주"]["한글"] == "갑진",
          after["년주"]["한글"])
    check("입춘 경계에서 년주만 바뀌고 일주는 그대로",
          before["일주"]["한글"] == after["일주"]["한글"])

    # --- 월주: 오호둔 (년간 → 인월 천간) ------------------------------
    #     갑기년 병인월 · 을경년 무인월 · 병신년 경인월 · 정임년 임인월 · 무계년 갑인월
    ohodun = {"갑": "병", "기": "병", "을": "무", "경": "무", "병": "경",
              "신": "경", "정": "임", "임": "임", "무": "갑", "계": "갑"}
    rule_ok, detail = True, "1960~2040 인월 전부"
    for year in range(1960, 2041):
        # 인월 한복판(입춘~경칩 사이) 이라 2월 20일이면 안전합니다.
        result = compute_saju(date(year, 2, 20), time(12, 0))
        year_stem = result["년주"]["천간"]["한글"]
        month = result["월주"]["한글"]
        if result["적용 절기"]["월지"] != "인월":
            continue
        if month[0] != ohodun[year_stem] or month[1] != "인":
            rule_ok = False
            detail = f"{year}년 {year_stem}년의 인월이 {month} (기대 {ohodun[year_stem]}인)"
            break
    check("월간이 오호둔(년간 → 인월 천간) 규칙과 맞는다", rule_ok, detail)

    # --- 시주: 오서둔 (일간 → 자시 천간) ------------------------------
    #     갑기일 갑자시 · 을경일 병자시 · 병신일 무자시 · 정임일 경자시 · 무계일 임자시
    oseodun = {"갑": "갑", "기": "갑", "을": "병", "경": "병", "병": "무",
               "신": "무", "정": "경", "임": "경", "무": "임", "계": "임"}
    rule_ok, detail = True, "2024년 366일 · 0시대 전부"
    day = date(2024, 1, 1)
    while day <= date(2024, 12, 31):
        result = compute_saju(day, time(0, 30))     # 0시 30분 → 자시
        day_stem = result["일주"]["천간"]["한글"]
        hour = result["시주"]["한글"]
        if hour[1] != "자" or hour[0] != oseodun[day_stem]:
            rule_ok = False
            detail = f"{day} {day_stem}일의 자시가 {hour} (기대 {oseodun[day_stem]}자)"
            break
        day += timedelta(days=1)
    check("시간이 오서둔(일간 → 자시 천간) 규칙과 맞는다", rule_ok, detail)

    # --- 시지: 23시 시작 · 2시간 단위 ---------------------------------
    expected = ["자", "축", "축", "인", "인", "묘", "묘", "진", "진", "사", "사",
                "오", "오", "미", "미", "신", "신", "유", "유", "술", "술",
                "해", "해", "자"]
    got = [
        compute_saju(date(2024, 5, 20), time(hour, 30))["시주"]["지지"]["한글"]
        for hour in range(24)
    ]
    check("시지가 23시부터 2시간 단위로 끊긴다", got == expected,
          "".join(got))

    # --- 일주: 하루가 지나면 60갑자가 정확히 한 칸 ---------------------
    step_ok = True
    day = date(1970, 1, 1)
    previous = _day_pillar_index(day)
    for _ in range(4000):
        day += timedelta(days=1)
        current = _day_pillar_index(day)
        if current != (previous + 1) % 60:
            step_ok = False
            break
        previous = current
    check("일주가 하루에 정확히 한 칸씩 나아간다", step_ok)

    # --- 월주가 '음력 월'이 아니라 '절기'를 따른다는 확인 ---------------
    #     음력 1월 1일(설날)은 해마다 입춘 앞뒤로 오갑니다.
    #     월지가 음력 월에 매여 있다면 늘 같은 글자가 나와야 하는데,
    #     실제로는 설날이 입춘보다 이르냐 늦냐에 따라 축월/인월로 갈립니다.
    branches = {}
    for year in range(2015, 2031):
        result = compute_saju(date(year, 1, 1), time(12, 0), "음력")
        branches.setdefault(result["적용 절기"]["월지"], []).append(year)
    check("음력 1월 1일의 월지가 해마다 갈린다 (월주 = 절기 기준, 음력 월 무관)",
          len(branches) > 1,
          " · ".join(f"{k} {len(v)}년" for k, v in sorted(branches.items())))
    print()


# ===============================================================
#  5. 프롬프트 — Gemini 가 다시 계산하지 못하게 막았는지
# ===============================================================
def verify_prompt_lock(saju: dict) -> None:
    print("[PROMPT LOCK-DOWN CHECK]")
    from halmae_ai import SYSTEM_INSTRUCTION, build_prompt

    payload = format_saju_for_prompt(saju)
    facts = saju_facts(saju)

    check("확정값 블록 이름(CALCULATED_SAJU)이 있다", "CALCULATED_SAJU" in payload)
    check("'다시 계산하지 말라'가 적혀 있다", "다시 계산하지" in payload)
    check("'그대로 옮겨 적으라'가 적혀 있다", "그대로 옮겨 적" in payload)
    check("오행 세는 기준이 프롬프트에 적혀 있다", facts["오행 기준"] in payload)
    check("글자별 오행 근거가 프롬프트에 있다", "→" in payload and "글자 하나씩" in payload)

    check("시스템 프롬프트가 계산/해석을 나눈다",
          "계산과 해석의 분리" in SYSTEM_INSTRUCTION)
    check("시스템 프롬프트에 굳은 예시 명식이 없다",
          "네 일간이 갑목이고 토 기운이 강한" not in SYSTEM_INSTRUCTION)

    for step in (2, 3):
        prompt = build_prompt(step, {}, saju, None)
        check(f"{step}단계 프롬프트에 확정 명식이 다시 붙는다",
              "CALCULATED_SAJU" in prompt and facts["일주"] in prompt)

    # 2·3단계에는 개인정보를 다시 붙이지 않습니다.
    step2 = build_prompt(2, {"이름": "홍길동"}, saju, None)
    check("2단계 재확인 블록에 개인정보가 없다", "홍길동" not in step2)

    # 그래도 할매가 명식을 바꿔 말하면 잡히는지 (사용자가 겪은 '무인/무토' 상황)
    from halmae_ai import Evidence, Step1Answer, find_saju_contradictions

    clean = Step1Answer(
        headline="h",
        evidences=[Evidence(source="사주",
                            fact=f"일간 {facts['일간 글자']}{facts['일간 오행']}",
                            reading="r")],
        concern_reading="c", closing="c",
    )
    dirty = Step1Answer(
        headline="h",
        evidences=[Evidence(source="사주", fact="일주 무인, 일간 무토", reading="r")],
        concern_reading="c", closing="c",
    )
    check("확정 명식과 맞는 답변은 경고가 없다",
          find_saju_contradictions(clean, saju) == [])
    found = find_saju_contradictions(dirty, saju)
    check("확정 명식에 없는 간지를 말하면 잡아낸다",
          bool(found) and "무인" in found[0],
          found[0] if found else "못 잡음")
    print()


# ===============================================================
#  6. 화면 — 명식을 Gemini 응답이 아니라 파이썬 값에서 가져오는지
# ===============================================================
def verify_ui_source_of_truth() -> None:
    """app.py 를 import 하면 streamlit 이 뜨므로 소스만 읽어 확인합니다."""
    print("[UI SOURCE-OF-TRUTH CHECK]")
    source = open("app.py", encoding="utf-8").read()

    check("명식 화면 함수(render_myeongsik)가 있다", "def render_myeongsik" in source)
    check("명식 화면이 saju_facts() 를 쓴다",
          "facts = saju_facts(saju)" in source)
    # render_result 안에서, USE_DEV_MODE 로 감싸지 않은 자리에서 불려야 합니다.
    result_body = source.split("def render_result()")[1].split("\ndef ")[0]
    called = [
        line for line in result_body.splitlines()
        if line.strip() == "render_myeongsik()"
    ]
    check("명식 화면이 render_result 에서 불린다", len(called) == 1)
    check("명식 화면이 개발자 모드(USE_DEV_MODE)에 갇혀 있지 않다",
          bool(called) and not called[0].startswith("        "),
          called[0].strip() if called else "호출 없음")

    body = source.split("def render_myeongsik")[1].split("\ndef ")[0]
    check("명식 화면이 Gemini 응답(answer/reply)을 읽지 않는다",
          "answer" not in body and "replies" not in body)

    # 음력 간지(참고용)를 '년주/월주/일주'라고 부르면 어느 쪽이 명식인지 헷갈립니다.
    from saju import compute_calendar_info

    reference = compute_calendar_info(date(1999, 4, 12))["음력 간지(참고용)"]
    check("음력 간지가 '년주/월주/일주' 이름을 쓰지 않는다",
          not ({"년주", "월주", "일주"} & set(reference)),
          " · ".join(reference))

    calendar_panel = source.split("def render_calendar_check")[1].split("\ndef ")[0]
    check("달력 패널 화면에도 '년주/월주/일주' 라벨이 없다",
          not any(word in calendar_panel for word in ("년주 {", "월주 {", "일주 {")))

    # 같은 날의 음력 월간지와 사주 월주가 실제로 다른지 (이름을 나눈 이유)
    saju_month = compute_saju(date(1999, 4, 12), time(8, 49))["월주"]["한글"]
    lunar_month = reference["음력 월간지"]["한글"]
    check("음력 월간지와 사주 월주는 실제로 다른 값이다",
          saju_month != lunar_month,
          f"음력 월간지 {lunar_month} vs 월주 {saju_month}")
    print()


# ===============================================================
#  실행
# ===============================================================
def main() -> int:
    argv = sys.argv[1:]
    raw_date = argv[0] if argv else "1999-04-12"
    raw_time = argv[1] if len(argv) > 1 else "08:49"
    kind = argv[2] if len(argv) > 2 else "양력"
    leap = argv[3] if len(argv) > 3 else None

    birth_time = None
    if raw_time not in ("모름", "-", "none", "None"):
        birth_time = time.fromisoformat(raw_time)

    print("=" * 64)
    print(" 사주 계산 파이프라인 진단 (개발 테스트 전용 · Gemini 호출 없음)")
    print("=" * 64)
    print()

    saju = compute_saju(
        birth_date=date.fromisoformat(raw_date),
        birth_time=birth_time,
        calendar_type=kind,
        leap_month=leap,
    )

    dump_saju(saju, birth_time)
    verify_ohaeng(saju)
    verify_day_pillar()
    verify_solar_terms()
    verify_pillar_rules()
    verify_prompt_lock(saju)
    verify_ui_source_of_truth()

    print("=" * 64)
    if _failures:
        print(f" 실패 {len(_failures)}건")
        for name in _failures:
            print(f"   - {name}")
        return 1
    print(" 전부 통과")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
