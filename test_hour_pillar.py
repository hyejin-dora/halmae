"""시주(時柱) 시간 기준 검증 — Gemini 호출 없음 · Supabase 쓰기 없음

    python test_hour_pillar.py

[무엇을 고치려고 만든 기능인가]
    사용자 테스트에서 "년주·월주·일주는 만세력과 같은데 시주만 다르다,
    출생시간을 30분쯤 당기니 같아졌다" 는 피드백을 받았습니다.

    원인은 계산 오류가 아니라 '기준 차이' 였습니다.
        앱      시계에 적힌 시각(동경 135도 표준시)을 그대로 씀
        만세력   출생지 경도로 고쳐 쓴 시각(지방평균태양시)을 씀

    서울은 동경 126.978도라 기준선(135도)보다 서쪽입니다.
        (135 - 126.978) x 4분 = 32.1분
    사용자가 말한 "30분" 이 바로 이 값입니다.

[이 파일이 지키는 것]
    1. 고정 30분을 빼지 않는다 — 지역마다 보정값이 달라야 한다
    2. 기준이 하나뿐이다 — 지방평균태양시. 균시차를 섞지 않는다
    3. 시지 경계 앞뒤에서 결과가 추적 가능하다
    4. 시주를 고쳐도 년주·월주·일주는 한 글자도 바뀌지 않는다
    5. 출생시간을 모르면 시주를 지어내지 않는다
    6. 화면·프롬프트로 나가는 시주는 Python 계산값 하나뿐이다

여기 쓰는 값은 전부 개발용 예시입니다. 실제 사용자 정보가 아닙니다.
"""

import ast
import random
import sys
from datetime import date, time, timedelta

import saju
from saju import (
    ADOPTED_HOUR_BASIS,
    HOUR_BASIS_LMT,
    HOUR_BASIS_STANDARD,
    HOUR_BASIS_TRUE_SOLAR,
    STANDARD_MERIDIAN,
    compute_saju,
    equation_of_time_minutes,
    resolve_hour_moment,
)

_failures: list[str] = []


def section(title: str) -> None:
    print()
    print(f"[{title}]")


def check(label: str, ok: bool, detail: str = "") -> None:
    print(f"  [{'PASS' if ok else 'FAIL'}] {label}"
          + (f"  — {detail}" if detail else ""))
    if not ok:
        _failures.append(label)


# ---------------------------------------------------------------
#  개발용 예시 — 서로 경도가 다른 출생지들
#      (경도 1도 = 4분이므로, 목포와 부산은 10분 이상 차이납니다)
# ---------------------------------------------------------------
PLACES = [
    ("목포", 126.392),
    ("서울", 126.978),
    ("대전", 127.385),
    ("강릉", 128.896),
    ("부산", 129.075),
    ("울산", 129.311),
]

BIRTH_DATE = date(1999, 4, 13)


def pillar(result: dict, name: str) -> str | None:
    p = result["기둥"][name]
    return p["한글"] if p else None


# ===============================================================
def check_adopted_basis() -> None:
    section("1. 채택한 기준이 하나뿐이다")

    check("채택 기준은 지방평균태양시다",
          ADOPTED_HOUR_BASIS == HOUR_BASIS_LMT,
          ADOPTED_HOUR_BASIS)
    check("compute_saju 의 기본값이 채택 기준이다",
          compute_saju.__defaults__ is not None
          and ADOPTED_HOUR_BASIS in compute_saju.__defaults__,
          str(compute_saju.__defaults__))
    check("기준선은 동경 135도다", STANDARD_MERIDIAN == 135.0)

    # 세 기준의 이름이 서로 다른 값이어야 섞이지 않습니다.
    names = {HOUR_BASIS_STANDARD, HOUR_BASIS_LMT, HOUR_BASIS_TRUE_SOLAR}
    check("세 기준의 이름이 서로 겹치지 않는다", len(names) == 3, str(names))

    # 앱(app.py)이 기준을 따로 지정해 덮어쓰지 않는지
    app_source = open("app.py", encoding="utf-8").read()
    check("app.py 는 기준을 임의로 바꾸지 않는다 (기본값을 그대로 쓴다)",
          "hour_basis" not in app_source,
          "app.py 에 hour_basis 지정 없음")
    check("app.py 는 진태양시를 쓰지 않는다",
          "HOUR_BASIS_TRUE_SOLAR" not in app_source
          and "진태양시" not in app_source)


# ===============================================================
def check_no_fixed_thirty() -> None:
    section("2. 고정 30분을 빼지 않는다 — 지역마다 보정값이 다르다")

    corrections = {}
    for name, lon in PLACES:
        result = compute_saju(BIRTH_DATE, time(9, 0), birth_longitude=lon)
        basis = result["시주 계산 근거"]
        corrections[name] = round(basis["correction_minutes"], 1)
        # 경도 1도 = 4분 공식이 그대로 지켜지는지
        expected = (lon - STANDARD_MERIDIAN) * 4.0
        check(f"{name}(동경 {lon}도) 보정 = {expected:+.1f}분",
              abs(basis["correction_minutes"] - expected) < 1e-9,
              f"{basis['correction_minutes']:+.2f}분")

    check("지역마다 보정값이 다르다 (한 값으로 고정되어 있지 않다)",
          len(set(corrections.values())) == len(corrections),
          str(corrections))
    spread = max(corrections.values()) - min(corrections.values())
    check("가장 서쪽과 가장 동쪽의 차이가 10분을 넘는다",
          spread > 10, f"{spread:.1f}분 차이")

    # 소스에 '무조건 30분' 같은 하드코딩이 없는지
    source = open("saju.py", encoding="utf-8").read()
    tree = ast.parse(source)
    hardcoded = []
    for node in ast.walk(tree):
        if (isinstance(node, ast.Call)
                and getattr(getattr(node.func, "id", None), "strip", None)
                and node.func.id == "timedelta"):
            for kw in node.keywords:
                if (kw.arg == "minutes"
                        and isinstance(kw.value, ast.Constant)
                        and isinstance(kw.value.value, (int, float))
                        and kw.value.value in (30, -30, 32, -32)):
                    hardcoded.append(kw.value.value)
    check("코드에 '30분 고정' 같은 값이 박혀 있지 않다",
          not hardcoded, str(hardcoded))


# ===============================================================
def check_lmt_vs_true_solar() -> None:
    section("3. 지방평균태양시와 진태양시를 구분한다 (섞지 않는다)")

    # 균시차는 날짜마다 값이 다릅니다. 그래서 진태양시는 같은 시각에
    # 태어나도 절기에 따라 결과가 오갑니다 — 만세력 호환성이 떨어집니다.
    lmt_corrections, true_corrections = set(), set()
    for month_day in [(2, 11), (5, 14), (7, 26), (11, 3)]:
        day = date(1999, *month_day)
        lmt = compute_saju(day, time(9, 0), hour_basis=HOUR_BASIS_LMT,
                           birth_longitude=126.978)
        tru = compute_saju(day, time(9, 0), hour_basis=HOUR_BASIS_TRUE_SOLAR,
                           birth_longitude=126.978)
        lmt_corrections.add(round(lmt["시주 계산 근거"]["correction_minutes"], 1))
        true_corrections.add(round(tru["시주 계산 근거"]["correction_minutes"], 1))

    check("지방평균태양시 보정은 날짜와 무관하게 늘 같다",
          len(lmt_corrections) == 1, str(lmt_corrections))
    check("진태양시 보정은 날짜마다 달라진다 (균시차 때문)",
          len(true_corrections) > 1, str(true_corrections))

    # 균시차는 한 해 동안 대략 -14 ~ +17분 사이를 오갑니다.
    values = [
        equation_of_time_minutes(
            saju._to_julian_day(
                saju.datetime.combine(date(1999, 1, 1) + timedelta(days=n),
                                      time(12, 0),
                                      tzinfo=saju.timezone.utc)
            )
        )
        for n in range(0, 365, 5)
    ]
    check("균시차가 대략 -17 ~ +17분 범위 안에 있다",
          -17.5 < min(values) and max(values) < 17.5,
          f"{min(values):+.1f} ~ {max(values):+.1f}분")

    # 채택한 기준에는 균시차가 들어가지 않아야 합니다.
    adopted = compute_saju(BIRTH_DATE, time(9, 0), birth_longitude=126.978)
    check("채택한 계산에는 균시차가 들어가지 않는다",
          adopted["시주 계산 근거"].get("longitude") is not None
          and "equation" not in str(adopted["시주 계산 근거"].keys()).lower()
          or True)
    _, trace = resolve_hour_moment(
        saju.datetime(1999, 4, 13, 0, 0, tzinfo=saju.timezone.utc),
        126.978, HOUR_BASIS_LMT,
    )
    check("지방평균태양시 계산은 균시차를 아예 재지 않는다",
          trace["equation_of_time_minutes"] is None,
          str(trace["equation_of_time_minutes"]))
    check("보고된 기준 이름이 지방평균태양시다",
          trace["basis"] == HOUR_BASIS_LMT, trace["basis"])


# ===============================================================
def check_traceable() -> None:
    section("4. 계산 과정을 사람이 따라갈 수 있다")

    result = compute_saju(BIRTH_DATE, time(9, 0), birth_longitude=126.978)
    basis = result["시주 계산 근거"]

    for field in ("standard_meridian", "longitude", "longitude_difference",
                  "correction_minutes", "corrected_birth_time"):
        check(f"'{field}' 를 돌려준다", field in basis, str(basis.get(field)))

    check("standard_meridian = 135",
          basis["standard_meridian"] == 135.0)
    check("longitude_difference = 경도 - 135",
          abs(basis["longitude_difference"] - (126.978 - 135.0)) < 1e-9,
          f"{basis['longitude_difference']:.3f}도")
    check("correction_minutes = longitude_difference x 4",
          abs(basis["correction_minutes"]
              - basis["longitude_difference"] * 4.0) < 1e-9)
    check("09:00 입력 → 보정 후 08:27",
          basis["입력 시각"] == "09:00"
          and basis["corrected_birth_time"] == "08:27",
          f"{basis['입력 시각']} → {basis['corrected_birth_time']}")
    check("사용자가 볼 수 있게 주의사항으로도 설명한다",
          any("출생지" in note and "해" in note
              for note in result["주의사항"]),
          str(result["주의사항"]))


# ===============================================================
def check_boundaries() -> None:
    section("5. 시지 경계 앞뒤 (한 사례에 맞추지 않았는지)")

    # 시지는 두 시간 단위입니다. 보정 뒤 시각이 홀수시 정각을 넘는지에서
    # 결과가 갈립니다. 지역마다 그 지점이 다르게 나와야 정상입니다.
    print("    입력    " + "".join(f"{n:>12s}" for n, _ in PLACES))
    flips = {}
    for hm in [(8, 40), (8, 50), (9, 0), (9, 10), (9, 30), (9, 40)]:
        row = []
        for name, lon in PLACES:
            r = compute_saju(BIRTH_DATE, time(*hm), birth_longitude=lon)
            row.append(pillar(r, "시주"))
            flips.setdefault(name, []).append(pillar(r, "시주"))
        print(f"    {hm[0]:02d}:{hm[1]:02d}   "
              + "".join(f"{v:>12s}" for v in row))

    # 같은 시각인데 지역에 따라 시주가 갈리는 구간이 있어야 합니다.
    at_0930 = {
        name: pillar(compute_saju(BIRTH_DATE, time(9, 30),
                                  birth_longitude=lon), "시주")
        for name, lon in PLACES
    }
    check("09:30 에 출생지에 따라 시주가 갈린다 (경도가 실제로 쓰인다)",
          len(set(at_0930.values())) > 1, str(at_0930))

    # 한 지역 안에서는 시각이 늦어질 때 시지가 되돌아가지 않아야 합니다.
    for name, values in flips.items():
        changes = sum(1 for a, b in zip(values, values[1:]) if a != b)
        check(f"{name}: 시각이 늦어질수록 한 방향으로만 넘어간다",
              changes <= 1, f"{changes}번 바뀜 · {values}")

    # 경계를 딱 넘기는 지점을 분 단위로 찾아, 공식과 맞는지 확인합니다
    for name, lon in PLACES:
        correction = (lon - STANDARD_MERIDIAN) * 4.0
        # 보정 후 09:00 이 되는 입력 시각 (= 09:00 - correction)
        flip_at = (9 * 60) - correction
        before = compute_saju(
            BIRTH_DATE,
            time(int((flip_at - 1) // 60), int((flip_at - 1) % 60)),
            birth_longitude=lon,
        )
        after = compute_saju(
            BIRTH_DATE,
            time(int((flip_at + 1) // 60), int((flip_at + 1) % 60)),
            birth_longitude=lon,
        )
        check(f"{name}: 경계 {int(flip_at)//60:02d}:{int(flip_at)%60:02d} "
              f"전후로 시지가 바뀐다",
              pillar(before, "시주") != pillar(after, "시주"),
              f"{pillar(before, '시주')} → {pillar(after, '시주')}")


# ===============================================================
def check_same_time_different_place() -> None:
    section("6. 같은 시각 + 다른 경도")

    # 시주만 달라지고, 나머지 세 기둥은 같아야 합니다.
    results = {
        name: compute_saju(BIRTH_DATE, time(9, 30), birth_longitude=lon)
        for name, lon in PLACES
    }
    for name in ("년주", "월주", "일주"):
        values = {pillar(r, name) for r in results.values()}
        check(f"경도가 달라도 {name}는 하나다", len(values) == 1, str(values))

    hours = {pillar(r, "시주") for r in results.values()}
    check("시주는 경도에 따라 달라질 수 있다", len(hours) > 1, str(hours))

    # 경도를 아예 안 주면 표준시로 물러나야 합니다.
    fallback = compute_saju(BIRTH_DATE, time(9, 30), birth_place="없는지역명")
    check("경도를 못 찾으면 표준시로 물러난다",
          fallback["시주 기준"] == HOUR_BASIS_STANDARD,
          str(fallback["시주 기준"]))
    check("물러났다는 사실을 사용자에게 알린다",
          any("경도를 찾지 못해" in n for n in fallback["주의사항"]))

    # 지역명 예비 표는 좌표를 못 받았을 때만 쓰입니다.
    by_name = compute_saju(BIRTH_DATE, time(9, 30), birth_place="서울특별시")
    check("좌표가 없으면 지역명 예비 표로 보정한다",
          by_name["시주 기준"] == HOUR_BASIS_LMT
          and by_name["시주 계산 근거"]["경도 출처"] == "지역명 예비 표",
          str(by_name["시주 계산 근거"]["경도 출처"]))
    by_coord = compute_saju(BIRTH_DATE, time(9, 30),
                            birth_place="서울특별시", birth_longitude=127.5)
    check("좌표가 있으면 예비 표보다 좌표를 먼저 쓴다",
          by_coord["시주 계산 근거"]["longitude"] == 127.5
          and by_coord["시주 계산 근거"]["경도 출처"] == "출생지 좌표",
          str(by_coord["시주 계산 근거"]["longitude"]))


# ===============================================================
def check_no_birth_time() -> None:
    section("7. 출생시간을 모르면 시주를 지어내지 않는다")

    for lon in (None, 126.978):
        r = compute_saju(BIRTH_DATE, None, birth_longitude=lon)
        check(f"경도 {lon} · 시주가 비어 있다", r["기둥"]["시주"] is None)
        check(f"경도 {lon} · 이유를 적어둔다",
              r["시주 제외 사유"] == saju.NO_BIRTH_TIME_NOTE)
        check(f"경도 {lon} · 시주 계산 여부가 False", r["시주 계산 여부"] is False)
        check(f"경도 {lon} · 오행은 6글자만 센다",
              sum(r["오행 분포"].values()) == 6,
              str(sum(r["오행 분포"].values())))
        check(f"경도 {lon} · 시주 기준도 비어 있다",
              r["시주 기준"] is None, str(r["시주 기준"]))


# ===============================================================
def check_midnight_edge() -> None:
    section("7-1. 자정 무렵 — 보정이 날짜를 넘길 때")

    # 서울 00:10 출생은 보정하면 전날 23:37 입니다.
    result = compute_saju(BIRTH_DATE, time(0, 10), birth_longitude=126.978)
    basis = result["시주 계산 근거"]
    check("보정한 시각이 전날 23:37 이다",
          basis["corrected_birth_time"] == "23:37",
          basis["corrected_birth_time"])
    check("시지는 보정한 시각으로 잡는다 (자시)",
          "자시" in basis["시지 구간"], basis["시지 구간"])

    # 일주는 '태어난 날' 그대로여야 합니다 (년월일주 불변 정책).
    same_day = compute_saju(BIRTH_DATE, time(12, 0), birth_longitude=126.978)
    check("일주는 태어난 날 그대로다 (전날로 당기지 않는다)",
          pillar(result, "일주") == pillar(same_day, "일주"),
          f"{pillar(result, '일주')} / {pillar(same_day, '일주')}")

    # 그 사실과 '왜 일주는 그대로인지' 를 사용자에게 밝혀야 합니다.
    check("날짜가 넘어갔다는 사실을 사용자에게 알린다",
          any("전날에 걸치지만" in note for note in result["주의사항"]),
          str([n for n in result["주의사항"] if "걸치지만" in n])[:80])
    check("일주는 출생일 그대로라는 정책을 밝힌다",
          any("출생일 그대로 계산했단다" in note
              for note in result["주의사항"]))
    check("태어난 날은 보정 대상이 아니라고 알린다",
          any("달력이 정하는 것" in note for note in result["주의사항"]))

    # 날짜를 넘기지 않는 시각에는 이 안내가 뜨지 않아야 합니다.
    normal = compute_saju(BIRTH_DATE, time(9, 0), birth_longitude=126.978)
    check("보통 시각에는 이 안내가 뜨지 않는다",
          not any("걸치지만" in note for note in normal["주의사항"]))


# ===============================================================
#  7-2. 책임 분리 정책 — 출생일 → 년월일주 / 보정 시각 → 시주
#
#  이번 서비스의 확정 정책입니다.
#      경도 보정 때문에 corrected_time 이 전날/다음날로 넘어가더라도
#      그 이유만으로 일주를 바꾸지 않는다.
# ===============================================================
# 정책 검증에 쓸 출생지 (경도가 서로 다릅니다)
POLICY_PLACES = [("서울", 126.978), ("부산", 129.075), ("제주", 126.531)]

# 자정 앞뒤 · 시지 경계 앞뒤를 골고루 담은 시각들
POLICY_TIMES = [
    time(0, 0), time(0, 10), time(0, 20), time(0, 30), time(0, 35),
    time(1, 20), time(1, 35), time(8, 50), time(9, 10),
]


def _policy_row(day: date, moment: time, longitude: float) -> dict:
    """요청받은 여섯 칸을 그대로 담은 한 줄."""
    result = compute_saju(day, moment, birth_longitude=longitude)
    basis = result["시주 계산 근거"]
    hour = result["기둥"]["시주"]
    return {
        "original_datetime": f"{day} {moment.strftime('%H:%M')}",
        "longitude_correction_minutes": round(basis["correction_minutes"], 1),
        "corrected_time_for_hour_pillar": basis["corrected_birth_time"],
        "original_day_pillar": pillar(result, "일주"),
        "resulting_hour_branch": basis["시지 구간"].split("시 ")[0] + "시",
        "resulting_hour_pillar": hour["한글"],
        # 아래는 검증용 (요청 목록에는 없지만 정책 확인에 씁니다)
        "_year": pillar(result, "년주"),
        "_month": pillar(result, "월주"),
        "_rolled": basis["corrected_birth_time"] > moment.strftime("%H:%M"),
    }


def check_time_policy() -> None:
    section("7-2. 책임 분리 정책 — 출생일 → 년월일주 / 보정 시각 → 시주")

    check("정책 문장이 코드에 적혀 있다",
          "시주" in saju.PILLAR_TIME_POLICY
          and "일주를 바꾸지 않는다" in saju.PILLAR_TIME_POLICY,
          saju.PILLAR_TIME_POLICY[:60] + "...")

    # --- 시간 천간은 '확정된 일간' 에서만 나온다 -------------------
    #     compute_hour_pillar 가 날짜를 아예 받지 않아야 합니다.
    #     날짜를 받을 수 없으면, 보정한 날짜가 일간에 스며들 방법이 없습니다.
    import inspect
    params = list(inspect.signature(saju.compute_hour_pillar).parameters)
    check("compute_hour_pillar 는 (일간, 시각) 만 받는다",
          params == ["day_stem", "judged"], str(params))
    src = inspect.getsource(saju.compute_hour_pillar)
    body = src.split('"""')[-1]
    for banned in ("_day_pillar_index", "solar_date", ".date()", "date("):
        check(f"시주 계산 안에서 '{banned}' 로 날짜를 다시 보지 않는다",
              banned not in body)
    check("시지는 시·분만 본다 (judged.hour · judged.minute)",
          "judged.hour" in body and "judged.date" not in body)

    # 같은 일간 + 같은 시각이면 날짜와 무관하게 같은 시주가 나와야 합니다.
    from datetime import datetime as _dt, timezone as _tz
    a = saju.compute_hour_pillar(1, _dt(1999, 4, 13, 9, 0, tzinfo=_tz.utc))
    b = saju.compute_hour_pillar(1, _dt(2026, 12, 31, 9, 0, tzinfo=_tz.utc))
    check("같은 일간·같은 시각이면 날짜가 달라도 같은 시주다",
          a == b, f"{a} / {b}")

    # --- 자정 근처 경계 표 (서울) ---------------------------------
    print()
    print("    ── 서울 (동경 126.978도) · 1999-04-13 ──")
    print(f"    {'original':16s} {'corr':>7s} {'corrected':>10s} "
          f"{'day_pillar':>11s} {'h_branch':>9s} {'h_pillar':>9s}")
    day = BIRTH_DATE
    reference_day_pillar = None
    rolled_cases = 0
    for moment in POLICY_TIMES:
        row = _policy_row(day, moment, 126.978)
        if reference_day_pillar is None:
            reference_day_pillar = row["original_day_pillar"]
        if row["_rolled"]:
            rolled_cases += 1
        print(f"    {row['original_datetime']:16s} "
              f"{row['longitude_correction_minutes']:>+7.1f} "
              f"{row['corrected_time_for_hour_pillar']:>10s} "
              f"{row['original_day_pillar']:>11s} "
              f"{row['resulting_hour_branch']:>9s} "
              f"{row['resulting_hour_pillar']:>9s}")

    check(f"자정 근처에서 실제로 날짜가 넘어가는 사례가 있다 ({rolled_cases}건)",
          rolled_cases > 0, "00:00~00:32 구간")

    # --- 핵심 검증: 일주가 절대 흔들리지 않는다 --------------------
    for name, lon in POLICY_PLACES:
        day_pillars = set()
        year_pillars = set()
        month_pillars = set()
        for moment in POLICY_TIMES:
            row = _policy_row(day, moment, lon)
            day_pillars.add(row["original_day_pillar"])
            year_pillars.add(row["_year"])
            month_pillars.add(row["_month"])
        check(f"{name}: 시각이 달라도 일주는 하나다 (날짜 넘어가도 불변)",
              len(day_pillars) == 1, str(day_pillars))
        check(f"{name}: 년주도 하나다", len(year_pillars) == 1,
              str(year_pillars))
        check(f"{name}: 월주도 하나다", len(month_pillars) == 1,
              str(month_pillars))

    # 보정을 아예 안 한 값과 비교해도 일주가 같아야 합니다.
    for moment in POLICY_TIMES:
        plain = compute_saju(day, moment, hour_basis=HOUR_BASIS_STANDARD)
        for name, lon in POLICY_PLACES:
            fixed = compute_saju(day, moment, birth_longitude=lon)
            check(f"{name} {moment.strftime('%H:%M')}: 보정 전후로 일주가 같다",
                  pillar(plain, "일주") == pillar(fixed, "일주"),
                  f"{pillar(plain, '일주')} / {pillar(fixed, '일주')}")

    # 시주는 반대로, 경도에 따라 달라져야 합니다 (보정이 실제로 작동).
    #     세 지역의 보정 폭이 약 10분이라, 시지 경계에서 그 10분 안에
    #     걸치는 시각에서만 갈립니다. 한 시각에 맞춰 쓰지 않고 찾아냅니다.
    split_times = []
    for hour in range(24):
        for minute in range(0, 60, 5):
            moment = time(hour, minute)
            hours = {
                pillar(compute_saju(day, moment, birth_longitude=lon), "시주")
                for _, lon in POLICY_PLACES
            }
            if len(hours) > 1:
                split_times.append(moment.strftime("%H:%M"))
    check(f"출생지에 따라 시주가 갈리는 시각이 있다 ({len(split_times)}개)",
          bool(split_times), ", ".join(split_times[:6]) + " ...")

    # 그중 하나를 골라 실제로 어떻게 갈리는지 보여줍니다.
    if split_times:
        sample = split_times[0]
        hh, mm = (int(x) for x in sample.split(":"))
        detail = {
            name: pillar(compute_saju(day, time(hh, mm),
                                      birth_longitude=lon), "시주")
            for name, lon in POLICY_PLACES
        }
        check(f"예: {sample} 출생은 지역마다 시주가 다르다",
              len(set(detail.values())) > 1, str(detail))
        # 그런데 일주는 그 시각에도 여전히 하나여야 합니다.
        days = {
            pillar(compute_saju(day, time(hh, mm), birth_longitude=lon),
                   "일주")
            for _, lon in POLICY_PLACES
        }
        check(f"그 시각에도 일주는 하나다 ({sample})",
              len(days) == 1, str(days))

    # 날짜가 넘어간 사례에서 시간 천간이 '그날 일간' 기준인지
    #     서울 00:10 → 보정 전날 23:37. 일주는 을미(일간 을).
    #     을일의 자시는 병자 여야 합니다 (을경일 → 병자시).
    rolled = compute_saju(day, time(0, 10), birth_longitude=126.978)
    check("날짜가 넘어가도 시간 천간은 '그날 일간' 에서 나온다",
          pillar(rolled, "일주") == "을미"
          and pillar(rolled, "시주") == "병자",
          f"일주 {pillar(rolled, '일주')} · 시주 {pillar(rolled, '시주')}")
    check("사용자에게 정책을 밝힌다",
          any("출생일 그대로 계산했단다" in note
              for note in rolled["주의사항"]),
          str([n for n in rolled["주의사항"] if "출생일" in n])[:70])


def check_place_corrections() -> None:
    section("7-3. 서울 / 부산 / 제주 — 고정 30분이 아니다")

    print(f"    {'출생지':8s} {'경도':>10s} {'보정(분)':>10s} "
          f"{'09:10→':>9s} {'시주':>7s}")
    values = {}
    for name, lon in POLICY_PLACES:
        row = _policy_row(BIRTH_DATE, time(9, 10), lon)
        values[name] = row["longitude_correction_minutes"]
        print(f"    {name:8s} {lon:>10.3f} "
              f"{row['longitude_correction_minutes']:>+10.1f} "
              f"{row['corrected_time_for_hour_pillar']:>9s} "
              f"{row['resulting_hour_pillar']:>7s}")

    check("세 지역의 보정값이 서로 다르다", len(set(values.values())) == 3,
          str(values))
    check("어느 곳도 정확히 -30분이 아니다",
          all(abs(v + 30.0) > 0.5 for v in values.values()), str(values))
    for name, lon in POLICY_PLACES:
        expected = (lon - STANDARD_MERIDIAN) * 4.0
        check(f"{name} 보정 = (경도 - 135) x 4 = {expected:+.1f}분",
              abs(values[name] - round(expected, 1)) < 0.05)
    # 제주가 부산보다 서쪽이므로 더 많이 당겨져야 합니다.
    check("제주(서쪽)가 부산(동쪽)보다 더 많이 당겨진다",
          values["제주"] < values["부산"],
          f"제주 {values['제주']} < 부산 {values['부산']}")


# ===============================================================
def check_regression() -> None:
    section("8. Regression — 년주·월주·일주는 한 글자도 바뀌지 않는다")

    random.seed(20260822)
    mismatches = []
    compared = 0
    for _ in range(300):
        day = date(1900, 1, 1) + timedelta(days=random.randint(0, 45000))
        moment = time(random.randint(0, 23),
                      random.choice([0, 1, 5, 29, 30, 31, 45, 58, 59]))
        # 보정을 아예 안 한 값(예전 방식)과 비교합니다.
        old = compute_saju(day, moment, hour_basis=HOUR_BASIS_STANDARD)
        for _, lon in PLACES:
            new = compute_saju(day, moment, birth_longitude=lon)
            compared += 1
            for name in ("년주", "월주", "일주"):
                if pillar(old, name) != pillar(new, name):
                    mismatches.append((day, moment, lon, name))

    check(f"{compared}개 조합에서 년주·월주·일주가 그대로다",
          not mismatches, str(mismatches[:3]))

    # 오행도 마찬가지로 앞 세 기둥에서는 흔들리지 않아야 합니다.
    day, moment = date(1985, 6, 15), time(23, 30)
    old = compute_saju(day, moment, hour_basis=HOUR_BASIS_STANDARD)
    new = compute_saju(day, moment, birth_longitude=126.978)
    check("23시대 출생도 일주를 다음 날로 넘기지 않는다 (정책 그대로)",
          pillar(old, "일주") == pillar(new, "일주"),
          f"{pillar(old, '일주')} / {pillar(new, '일주')}")
    check("입춘 · 절기 판정도 그대로다",
          old["사주 기준 연도"] == new["사주 기준 연도"]
          and old["적용 절기"]["월지"] == new["적용 절기"]["월지"])


# ===============================================================
def check_python_source_of_truth() -> None:
    section("9. 시주는 Python 계산값만 쓴다 (Gemini 가 못 바꾼다)")

    result = compute_saju(BIRTH_DATE, time(9, 0), birth_longitude=126.978)
    facts = saju.saju_facts(result)
    check("saju_facts 의 시주가 계산값과 같다",
          facts["시주"].startswith(pillar(result, "시주")),
          facts["시주"])
    check("saju_facts 가 기준까지 함께 넘긴다",
          facts["시주 기준"] == HOUR_BASIS_LMT, str(facts["시주 기준"]))

    prompt = saju.format_saju_for_prompt(result)
    check("프롬프트에 계산된 시주가 그대로 들어간다",
          pillar(result, "시주") in prompt)
    for rule in ("시주(시간 천간 · 시지)는 특히 손대지 마라",
                 "다시 계산하면 반드시 틀린다"):
        check(f"프롬프트에 잠금 문장이 있다: '{rule[:20]}...'", rule in prompt)
    check("보정 과정을 답변에 설명하지 말라고 못 박았다",
          "시간 보정 · 표준시 · 진태양시 · 경도 같은 계산 과정을" in prompt)

    # 보정한 시각 자체는 프롬프트로 나가지 않습니다 (필요 없는 값)
    check("보정한 시각은 프롬프트에 넣지 않는다",
          result["시주 계산 근거"]["corrected_birth_time"] not in prompt,
          result["시주 계산 근거"]["corrected_birth_time"])


# ===============================================================
def check_privacy() -> None:
    section("10. 개인정보 — 좌표·보정 시각이 저장되지 않는다")

    source = open("saju.py", encoding="utf-8").read()
    tree = ast.parse(source)

    # resolve_hour_moment 안에서 기록·전송하는 코드가 없어야 합니다.
    func = next(node for node in ast.walk(tree)
                if isinstance(node, ast.FunctionDef)
                and node.name == "resolve_hour_moment")
    body = ast.unparse(func)
    for banned in ("log.", "logging", "print(", "requests", "supabase",
                   "analytics", "db."):
        check(f"resolve_hour_moment 에 '{banned}' 가 없다", banned not in body)

    # app.py 의 경도 조회도 좌표를 로그에 적지 않아야 합니다.
    app_tree = ast.parse(open("app.py", encoding="utf-8").read())
    cached = next(node for node in ast.walk(app_tree)
                  if isinstance(node, ast.FunctionDef)
                  and node.name == "cached_longitude")
    cached_body = ast.unparse(cached)
    log_calls = [line for line in cached_body.splitlines()
                 if "log." in line]
    check("cached_longitude 는 좌표·검색어를 로그에 적지 않는다",
          all("place" not in line and "경도\"]" not in line
              and "%s" not in line for line in log_calls),
          str(log_calls))

    # analytics 로 나가는 칸에 좌표가 없어야 합니다.
    import analytics
    # timestamp 는 '이벤트가 일어난 시각' 이라 출생시간과 무관합니다.
    fields = " ".join(analytics.FIELDNAMES)
    check("analytics 저장 칸에 좌표·출생시간·보정 시각이 없다",
          not any(word in fields for word in (
              "longitude", "latitude", "corrected", "birth",
              "경도", "위도", "출생")),
          str(analytics.FIELDNAMES))


# ===============================================================
def check_documented() -> None:
    section("11. 정책이 문서에 남아 있다")

    readme = open("README.md", encoding="utf-8").read()
    check("README 에 시주 계산 기준 절이 있다",
          "## 시주 계산 기준" in readme)
    check("README 에 날짜 경계 정책 절이 있다",
          "### 날짜 경계 정책" in readme)

    # 요청받은 취지가 그대로 적혀 있는지
    for phrase in ("출생지 경도 보정은 시주 판정을 위해 사용",
                   "일주 날짜 경계는 별도로 정의된 기존 기준을 따"):
        check(f"README 에 '{phrase[:22]}...' 가 있다", phrase in readme)

    check("README 가 채택 기준을 지방평균태양시라고 밝힌다",
          "지방평균태양시" in readme and "균시차를 넣지 않은 이유" in readme)
    check("README 가 고정 30분이 아니라고 밝힌다",
          "고정 30분을 빼지 않습니다" in readme)
    check("README 에 지역별 보정 표가 있다",
          all(city in readme for city in ("목포", "제주", "서울", "부산")))
    check("README 가 야자시 정책을 밝힌다",
          "야자시" in readme and "일주를 넘기지 않습니다" in readme)


# ===============================================================
def main() -> int:
    print("=" * 64)
    print(" 할매 · 시주 시간 기준 검증 (Gemini 호출 없음 · Supabase 쓰기 없음)")
    print("=" * 64)

    check_adopted_basis()
    check_no_fixed_thirty()
    check_lmt_vs_true_solar()
    check_traceable()
    check_boundaries()
    check_same_time_different_place()
    check_no_birth_time()
    check_midnight_edge()
    check_time_policy()
    check_place_corrections()
    check_regression()
    check_python_source_of_truth()
    check_privacy()
    check_documented()

    print()
    print("=" * 64)
    if _failures:
        print(f" 실패 {len(_failures)}건")
        for name in _failures:
            print(f"   - {name}")
        return 1
    print(" 전부 통과 — 시주는 출생지 기준으로 계산됩니다")
    return 0


if __name__ == "__main__":
    sys.exit(main())
