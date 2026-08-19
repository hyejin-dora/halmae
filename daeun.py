"""대운(大運) · 세운(歲運) 계산 — 파이썬이 계산하고, 할매(Gemini)는 해석만 합니다

이 파일은 화면(Streamlit)과 상관없이 혼자서도 돌아가는 계산 전용 모듈입니다.

    python daeun.py 1999-04-12 08:49 여성
    python daeun.py 1985-06-15 모름 남성 음력 윤달

[이 서비스의 원칙 — 계산과 해석의 분리]
    대운과 세운도 사주 명식과 똑같이 취급합니다.
        파이썬  →  간지와 시기를 '계산'한다
        Gemini  →  계산이 끝난 값을 '해석'만 한다
    Gemini 에게 "내 대운이 뭔지 계산해줘" 같은 일을 시키지 않습니다.
    프롬프트로 나가는 글은 format_year_flow_for_prompt() 한 곳에서만 만듭니다.


===================================================================
 대운 계산 기준 (이 서비스가 쓰는 단 하나의 규칙)
===================================================================
명리 학파마다 세부가 갈리는 자리라, 여기서는 아래 네 가지를 '하나의 규칙'으로
못 박아둡니다. 다른 만세력과 1년 정도 어긋날 수 있는 이유도 함께 적어둡니다.

1) 순행 / 역행  (DIRECTION_RULE)
   년주 천간의 음양과 성별로 정합니다. 가장 널리 쓰이는 기준입니다.
       양간(갑·병·무·경·임) 해에 태어난 남자  →  순행
       음간(을·정·기·신·계) 해에 태어난 여자  →  순행
       그 밖(음남 · 양녀)                     →  역행
   ※ 성별이 필요합니다. 성별을 알 수 없으면 대운을 계산하지 않습니다.
     (임의로 한쪽을 골라 계산하면 절반은 틀린 값이 됩니다)

2) 절기 기준  (TERM_RULE)
   12절(節) — 입춘 · 경칩 · 청명 · 입하 · 망종 · 소서 ·
              입추 · 백로 · 한로 · 입동 · 대설 · 소한
   월주를 정할 때 쓴 것과 똑같은 표(saju.SOLAR_TERMS)를 씁니다.
   중기(우수 · 춘분 …)는 쓰지 않습니다.

3) 대운 시작 시점 = 대운수  (START_AGE_RULE)
   순행이면 '태어난 순간 → 다음 절입',
   역행이면 '직전 절입 → 태어난 순간' 까지의 시간을 잽니다.
       3일 = 1년   (1일 = 4개월, 2시간 = 10일)
   시·분까지 반영한 정확한 시간차를 3으로 나눈 뒤,
   소수 첫째 자리에서 반올림해 정수 한 개(대운수)로 만듭니다. 최소값은 1입니다.
   ※ 반올림 자리에 걸린 사람은 만세력에 따라 대운수가 1 차이 날 수 있습니다.
     이 서비스는 항상 위 규칙 하나만 씁니다.

4) 대운 간지 진행  (PILLAR_RULE)
   월주(月柱)에서 출발해 60갑자를 순행이면 +1, 역행이면 -1 씩 옮깁니다.
   한 대운은 10년입니다.
       n번째 대운의 시작 연도 = 사주 기준 출생연도 + 대운수 + 10 × (n-1)
   여기서 '사주 기준 출생연도'는 입춘으로 해가 바뀐 연도(saju['사주 기준 연도'])라,
   세운(입춘 기준)과 같은 자에 놓입니다.
   ※ 나이는 만 나이 기준입니다. 세는 나이로 적는 만세력과는 1살 차이가 납니다.
     이 서비스가 실제로 쓰는 값은 '연도'라 해석에는 영향이 없습니다.

===================================================================
 세운 계산 기준
===================================================================
   지금 연도를 코드에서 가져와(date.today()) 그 해의 간지를 계산합니다.
   해가 바뀌는 기준은 1월 1일이 아니라 입춘입니다.
   (saju.compute_year_ganji 를 그대로 씁니다 — 올해의 카드와 같은 값)
   연도를 코드에 적어두지 않으므로 해가 바뀌면 저절로 따라갑니다.
"""

import logging
from datetime import date, datetime, time

from saju import (
    CHEONGAN,
    JIJI,
    SOLAR_TERMS,
    STANDARD_TZ,
    _from_julian_day,
    _make_pillar,
    _term_index,
    compute_saju,
    compute_year_ganji,
    find_solar_term,
)

logger = logging.getLogger("halmae.daeun")


class DaeunError(Exception):
    """사용자에게 그대로 보여줘도 되는, 이해하기 쉬운 대운 계산 오류."""


# ===============================================================
#  계산 기준을 글로도 한 벌 — README·코드 주석·프롬프트가 같은 문장을 씁니다
# ===============================================================
DIRECTION_FORWARD = "순행"
DIRECTION_BACKWARD = "역행"

DIRECTION_RULE = (
    "양간년 남자 · 음간년 여자는 순행, 음간년 남자 · 양간년 여자는 역행"
)
TERM_RULE = "12절(입춘·경칩·청명·입하·망종·소서·입추·백로·한로·입동·대설·소한)"
START_AGE_RULE = (
    "3일 = 1년 (1일 = 4개월, 2시간 = 10일) · "
    "순행은 다음 절입까지, 역행은 직전 절입까지의 시간을 3으로 나누어 "
    "소수 첫째 자리에서 반올림 · 최소 1"
)
PILLAR_RULE = "월주에서 출발해 60갑자를 한 칸씩 (순행 +1 / 역행 -1) · 한 대운 10년"
AGE_RULE = "만 나이 기준 · n번째 대운 시작 연도 = 사주 기준 출생연도 + 대운수 + 10×(n-1)"

# 한 사람에게 몇 개의 대운을 만들어둘지 (10개 = 약 100년)
DEFAULT_PERIOD_COUNT = 10

# 성별을 알 수 없을 때.
# 조용히 한쪽으로 정해버리면 절반의 사람에게 틀린 값을 보여주게 됩니다.
#
#   GENDER_REQUIRED_MESSAGE  이 함수를 직접 잘못 부른 개발자에게 알리는 말
#   GENDER_SKIPPED_NOTE      화면에서 대운 자리를 대신할 짧은 한 줄
#   GENDER_SKIPPED_FOR_PROMPT 프롬프트에 적어 보낼 사실 한 줄
#
# 긴 설명은 입력 화면(성별 칸 아래)에서 이미 한 번 했습니다.
# 결과 화면에서 같은 말을 되풀이하지 않으려고 짧게 끊었습니다.
GENDER_REQUIRED_MESSAGE = (
    "대운은 성별에 따라 흐르는 방향이 갈리는 계산이란다. "
    "성별을 알려주지 않아 대운은 계산할 수 없구나."
)
GENDER_SKIPPED_NOTE = "성별을 고르지 않아 대운은 건너뛰었단다."
GENDER_SKIPPED_FOR_PROMPT = (
    "성별을 알 수 없어 대운은 계산하지 않았다. "
    "대운 이야기는 아예 하지 마라. 세운만 다뤄라."
)

MALE_WORDS = ("남성", "남자", "남", "male", "m")
FEMALE_WORDS = ("여성", "여자", "여", "female", "f")


# ===============================================================
#  1. 작은 도구들
# ===============================================================
def normalize_gender(gender: str | None) -> str | None:
    """입력된 성별을 'male' / 'female' / None 으로 정리합니다.

    None 은 "알 수 없음" 입니다. ('응답하지 않음' 을 고른 경우)
    """
    text = (gender or "").strip().lower()
    if not text:
        return None
    if text in MALE_WORDS:
        return "male"
    if text in FEMALE_WORDS:
        return "female"
    return None


def _has_final(word: str) -> bool:
    """한글 낱말의 마지막 글자에 받침이 있는지. (조사를 고르려고 씁니다)"""
    if not word:
        return False
    last = word[-1]
    if not ("가" <= last <= "힣"):
        return False
    return (ord(last) - 0xAC00) % 28 != 0


def _josa(word: str, with_final: str, without_final: str) -> str:
    """'지지' + (이/가) → '지지가' 처럼 받침에 맞는 조사를 붙입니다."""
    return word + (with_final if _has_final(word) else without_final)


def gapja_index(stem: str, branch: str) -> int:
    """천간·지지 글자 한 쌍 → 60갑자 번호 (0 = 갑자)."""
    try:
        stem_index = CHEONGAN.index(stem)
        branch_index = JIJI.index(branch)
    except ValueError as exc:
        raise DaeunError("간지 글자를 알아보지 못했어요.") from exc

    for index in range(60):
        if index % 10 == stem_index and index % 12 == branch_index:
            return index
    # 천간·지지 짝이 60갑자에 없는 경우(갑축 등)는 사주 계산이 깨진 것입니다.
    raise DaeunError("월주 간지가 60갑자에 없는 짝이에요. (개발자 확인 필요)")


def _pillar_from_index(index: int) -> dict:
    """60갑자 번호 → 화면·프롬프트에 바로 쓸 수 있는 간지 dict."""
    index %= 60
    return _make_pillar(index % 10, index % 12)


def _birth_moment(saju: dict) -> datetime:
    """사주 계산이 실제로 판정에 쓴 그 순간(UTC).

    compute_saju() 가 내보내는 값을 그대로 씁니다. 대운이 다른 시각을 새로
    만들면 사주와 대운이 서로 어긋나므로, 없으면 만들어 쓰지 않고 멈춥니다.
    """
    moment = saju.get("기준 시각(UTC)")
    if isinstance(moment, datetime):
        return moment
    raise DaeunError(
        "출생 시각을 확인하지 못해 대운을 계산할 수 없어요. (개발자 확인 필요)"
    )


# ===============================================================
#  2. 순행 / 역행
# ===============================================================
def daeun_direction(saju: dict, gender: str | None) -> str:
    """대운이 어느 쪽으로 흐르는지. DIRECTION_RULE 하나만 씁니다.

    양간년 남자 · 음간년 여자  →  순행
    음간년 남자 · 양간년 여자  →  역행
    """
    normalized = normalize_gender(gender)
    if normalized is None:
        raise DaeunError(GENDER_REQUIRED_MESSAGE)

    # 년주 천간의 음양 — 짝수 번째(갑·병·무·경·임)가 양(陽)
    year_stem = saju["년주"]["천간"]["한글"]
    is_yang_year = CHEONGAN.index(year_stem) % 2 == 0
    is_male = normalized == "male"

    return DIRECTION_FORWARD if is_yang_year == is_male else DIRECTION_BACKWARD


# ===============================================================
#  3. 대운수 (교운 시점)
# ===============================================================
def daeun_start_age(saju: dict, forward: bool) -> dict:
    """태어난 순간부터 절입까지의 거리를 재서 대운이 시작되는 나이를 냅니다.

    START_AGE_RULE 하나만 씁니다.
        순행 → 다음 절입까지 / 역행 → 직전 절입까지
        3일 = 1년, 소수 첫째 자리에서 반올림, 최소 1
    """
    birth_utc = _birth_moment(saju)
    julian_day = saju.get("기준 율리우스일")
    if not isinstance(julian_day, (int, float)):
        raise DaeunError(
            "출생 시각을 확인하지 못해 대운을 계산할 수 없어요. (개발자 확인 필요)"
        )

    term_index = _term_index(julian_day)
    this_name, this_longitude, _ = SOLAR_TERMS[term_index]
    next_name, next_longitude, _ = SOLAR_TERMS[(term_index + 1) % 12]

    # 직전 절입 / 다음 절입 (사주 월주 판정에 쓴 것과 같은 표·같은 함수)
    previous_jd = find_solar_term(julian_day, this_longitude)
    next_jd = find_solar_term(julian_day + 32, next_longitude)

    if forward:
        gap_days = next_jd - julian_day
        boundary_name = next_name
        boundary_jd = next_jd
    else:
        gap_days = julian_day - previous_jd
        boundary_name = this_name
        boundary_jd = previous_jd

    gap_days = max(gap_days, 0.0)
    exact_years = gap_days / 3.0                       # 3일 = 1년
    # 소수 첫째 자리에서 반올림. round() 는 0.5 에서 짝수로 붙어(은행식 반올림)
    # 사람이 기대하는 값과 어긋나므로 쓰지 않습니다.
    start_age = int(exact_years + 0.5)
    start_age = max(start_age, 1)

    boundary_moment = _from_julian_day(boundary_jd).astimezone(STANDARD_TZ)

    return {
        "start_age": start_age,
        "exact_years": round(exact_years, 3),
        "gap_days": round(gap_days, 3),
        "boundary_term": boundary_name,
        "boundary_moment": f"{boundary_moment:%Y-%m-%d %H:%M} KST",
        "birth_moment_utc": birth_utc,
    }


# ===============================================================
#  4. 대운 전체 구간
# ===============================================================
def compute_daeun(
    saju: dict,
    gender: str | None,
    *,
    today: date | None = None,
    period_count: int = DEFAULT_PERIOD_COUNT,
) -> dict:
    """대운 한 벌. 이 dict 하나만 보면 '지금 어느 대운인지' 알 수 있습니다.

        {
          "direction": "순행",
          "start_age": 3,
          "periods": [{"pillar": "무인", "start_age": 3, "end_age": 12,
                       "start_year": 2002, "end_year": 2011, ...}, ...],
          "current": {...같은 모양...} 또는 None,
          "current_status": "진행중" / "대운 시작 전",
        }

    today 를 주지 않으면 오늘 날짜를 씁니다. (연도를 코드에 적어두지 않습니다)
    """
    if not saju:
        raise DaeunError("사주를 계산하지 못해 대운을 낼 수 없어요.")

    direction = daeun_direction(saju, gender)
    forward = direction == DIRECTION_FORWARD

    timing = daeun_start_age(saju, forward)
    start_age = timing["start_age"]

    # --- 대운 간지: 월주에서 출발해 한 칸씩 ------------------------
    month_pillar = saju["월주"]
    month_index = gapja_index(
        month_pillar["천간"]["한글"], month_pillar["지지"]["한글"]
    )
    step = 1 if forward else -1

    birth_year = int(saju["사주 기준 연도"])       # 입춘 기준 연도

    periods: list[dict] = []
    for order in range(period_count):
        pillar = _pillar_from_index(month_index + step * (order + 1))
        period_start_age = start_age + 10 * order
        period_start_year = birth_year + period_start_age
        periods.append({
            "order": order + 1,
            "pillar": pillar["한글"],
            "pillar_hanja": pillar["한자"],
            "stem_ohaeng": pillar["천간"]["오행"],
            "branch_ohaeng": pillar["지지"]["오행"],
            "animal": pillar["지지"]["띠"],
            "start_age": period_start_age,
            "end_age": period_start_age + 9,
            "start_year": period_start_year,
            "end_year": period_start_year + 9,
            "ganji": pillar,
        })

    # --- 지금 어느 구간인지 ---------------------------------------
    #     '지금'의 기준도 세운과 같은 입춘 기준 연도를 씁니다.
    current_year = compute_year_ganji(today)["연도"]
    current = None
    for period in periods:
        if period["start_year"] <= current_year <= period["end_year"]:
            current = period
            break

    if current is not None:
        status = "진행중"
    elif current_year < periods[0]["start_year"]:
        status = "대운 시작 전"
    else:
        status = "계산 구간 밖"

    return {
        "direction": direction,
        "forward": forward,
        "start_age": start_age,
        "periods": periods,
        "current": current,
        "current_status": status,
        "current_year": current_year,
        "birth_year": birth_year,
        "month_pillar": month_pillar["한글"],
        # 계산 근거 — 개발자 화면과 테스트에서 확인용
        "basis": {
            "direction_rule": DIRECTION_RULE,
            "term_rule": TERM_RULE,
            "start_age_rule": START_AGE_RULE,
            "pillar_rule": PILLAR_RULE,
            "age_rule": AGE_RULE,
            "boundary_term": timing["boundary_term"],
            "boundary_moment": timing["boundary_moment"],
            "gap_days": timing["gap_days"],
            "exact_years": timing["exact_years"],
        },
    }


# ===============================================================
#  5. 세운 (올해의 간지)
# ===============================================================
def compute_sewoon(today: date | None = None) -> dict:
    """올해의 세운. 연도는 코드에서 가져옵니다 (하드코딩 금지).

        {"year": 2026, "pillar": "병오", ...}

    해가 바뀌는 기준은 입춘입니다. (올해의 카드와 같은 값을 씁니다)
    """
    ganji = compute_year_ganji(today)
    return {
        "year": ganji["연도"],
        "calendar_year": ganji["달력 연도"],
        "pillar": ganji["한글"],
        "pillar_hanja": ganji["한자"],
        "stem_ohaeng": ganji["천간 오행"],
        "branch_ohaeng": ganji["지지 오행"],
        "animal": ganji["띠"],
        "ipchun": ganji["입춘 시각"],
        "ganji": ganji,          # 올해의 카드가 쓰는 원본 그대로
    }


# ===============================================================
#  6. 원국과 견주어 눈에 띄는 점 (해석의 '근거'가 될 짧은 메모)
#
#  여기서 만드는 것은 해석문이 아니라 '사실 메모'입니다.
#  실제 해석은 할매(Gemini)가 합니다.
# ===============================================================
def _ohaeng_note(label: str, ohaeng: str, counts: dict) -> str | None:
    have = counts.get(ohaeng, 0)
    if have == 0:
        return (f"{label}의 {ohaeng} 기운은 이 사람 원국에 0개라, "
                f"평소 없던 기운이 이 시기에 들어온다.")
    if have >= 4:
        return (f"{label}도 {ohaeng}인데 원국에 이미 {have}개라, "
                f"{ohaeng} 기운이 더 과해진다.")
    return None


def daeun_notes(saju: dict, daeun: dict) -> list[str]:
    """현재 대운이 원국과 어떻게 만나는지 짧은 사실 메모."""
    current = daeun.get("current")
    if not current:
        return [
            f"아직 대운이 시작되기 전이다. (대운수 {daeun['start_age']}세부터 시작)"
            if daeun.get("current_status") == "대운 시작 전"
            else "현재 대운 구간을 찾지 못했다."
        ]

    counts = saju["오행 분포"]
    day_stem = saju["일간"]
    notes: list[str] = []

    for label, ohaeng in (
        (f"대운 천간({current['ganji']['천간']['한글']})",
         current["stem_ohaeng"]),
        (f"대운 지지({current['ganji']['지지']['한글']})",
         current["branch_ohaeng"]),
    ):
        note = _ohaeng_note(label, ohaeng, counts)
        if note:
            notes.append(note)

    if current["stem_ohaeng"] == day_stem["오행"]:
        notes.append(
            f"대운 천간의 오행이 일간({day_stem['한글']})과 같은 "
            f"{day_stem['오행']}이라, 나와 같은 기운이 10년간 곁에 있는 시기다."
        )

    if not notes:
        notes.append(
            f"이번 대운({current['pillar']})의 기운"
            f"({current['stem_ohaeng']}·{current['branch_ohaeng']})은 "
            "원국에서 특별히 비어 있거나 치우친 자리는 아니다."
        )
    return notes


def sewoon_notes(saju: dict, sewoon: dict) -> list[str]:
    """올해 세운이 원국과 어떻게 만나는지 짧은 사실 메모.

    올해의 카드가 쓰는 saju.year_luck_notes() 를 그대로 씁니다.
    (같은 해에 대해 두 곳이 다른 말을 하지 않도록)
    """
    from saju import year_luck_notes

    return year_luck_notes(saju, sewoon["ganji"])


def flow_notes(daeun: dict, sewoon: dict) -> list[str]:
    """대운과 세운이 만나는 자리의 사실 메모."""
    current = daeun.get("current")
    if not current:
        return ["아직 대운이 시작되기 전이라, 올해는 세운의 기운이 주로 드러난다."]

    notes: list[str] = []
    pairs = (
        ("천간", current["stem_ohaeng"], sewoon["stem_ohaeng"]),
        ("지지", current["branch_ohaeng"], sewoon["branch_ohaeng"]),
    )
    for label, daeun_ohaeng, sewoon_ohaeng in pairs:
        if daeun_ohaeng == sewoon_ohaeng:
            notes.append(
                f"대운 {_josa(label, '과', '와')} 세운 "
                f"{_josa(label, '이', '가')} 둘 다 "
                f"{_josa(daeun_ohaeng, '이라', '라')}, "
                f"올해 {daeun_ohaeng} 기운이 겹쳐 두껍게 들어온다."
            )

    if current["animal"] == sewoon["animal"]:
        notes.append(
            f"대운 지지와 세운 지지가 같은 {sewoon['animal']}띠 자리다."
        )

    remaining = current["end_year"] - sewoon["year"]
    if remaining <= 1:
        notes.append(
            f"올해는 이 대운({current['pillar']})의 끝자락"
            f"({current['start_year']}~{current['end_year']})이다."
        )
    elif sewoon["year"] - current["start_year"] <= 1:
        notes.append(
            f"올해는 이 대운({current['pillar']})에 막 들어선 무렵"
            f"({current['start_year']}~{current['end_year']})이다."
        )

    if not notes:
        notes.append(
            f"올해 세운({sewoon['pillar']})은 대운({current['pillar']})과 "
            "겹치거나 부딪히는 자리 없이 나란히 흐른다."
        )
    return notes


# ===============================================================
#  7. Gemini 프롬프트에 그대로 넣을 수 있는 글
#
#  대운·세운도 사주 명식과 똑같이 "이미 계산이 끝난 확정값"으로 넣습니다.
#  Gemini 가 스스로 간지를 뽑거나 시기를 바꾸지 못하게 규칙을 함께 붙입니다.
# ===============================================================
LUCK_LOCK_HEADER = "[CALCULATED_LUCK — 대운·세운 확정 입력값]"
LUCK_LOCK_RULES = """[CALCULATED_LUCK 사용 규칙 — 어기면 답변 실패로 본다]
- 위 대운·세운은 Python 에서 계산이 끝난 확정값이다.
- 다시 계산하지 말고, 추정하지 말고, 바꾸지 말고, 그대로 해석만 하라.
- 생년월일·성별을 보고 대운을 스스로 뽑아내려 하지 마라. 이미 다 주어졌다.
- 간지(예: 무인)와 연도 구간은 위에 적힌 글자·숫자를 그대로 옮겨 적어라.
- 위에 없는 대운 구간이나 다른 해의 세운을 만들어내지 마라.
- 시기를 말할 때는 **나이보다 연도**로 말하라. ("2017년부터" 처럼)
  나이(만 O세)는 만세력마다 한 해쯤 다를 수 있으니 단정하지 마라.
- 월운(月運)·일운(日運)은 주어지지 않았다. 몇 월에 무엇이 일어난다고 쓰지 마라."""


def format_year_flow_for_prompt(
    daeun: dict | None,
    sewoon: dict,
    saju: dict | None = None,
    no_daeun_reason: str | None = None,
) -> str:
    """대운·세운 계산 결과를 프롬프트에 붙일 수 있는 글자로 바꿉니다.

    이 함수가 대운·세운이 프롬프트로 나가는 유일한 통로입니다.

    no_daeun_reason : 대운이 없을 때 '왜 없는지' 한 줄.
        (성별 미선택처럼 계산을 일부러 건너뛴 경우를 밝혀둡니다.
         이유를 적어주지 않으면 모델이 대운을 지어내려 합니다)
    """
    lines = [LUCK_LOCK_HEADER, ""]

    # --- 대운 ---------------------------------------------------
    if daeun and daeun.get("current"):
        current = daeun["current"]
        lines.append("[지금 지나고 있는 대운]")
        lines.append(
            f"- 대운 간지: {current['pillar']}({current['pillar_hanja']}) · "
            f"천간 {current['ganji']['천간']['한글']}={current['stem_ohaeng']}, "
            f"지지 {current['ganji']['지지']['한글']}={current['branch_ohaeng']}"
        )
        lines.append(
            f"- 이 대운의 기간: {current['start_year']}년 ~ {current['end_year']}년 "
            f"(참고로 만 나이로는 {current['start_age']}~{current['end_age']}세이나, "
            "나이는 만세력마다 한 해쯤 다르니 연도로 말할 것)"
        )
        lines.append(
            f"- 대운이 흐르는 방향: {daeun['direction']} · "
            f"대운수 {daeun['start_age']} (월주 {daeun['month_pillar']}에서 출발)"
        )
        neighbours = [p for p in daeun["periods"]
                      if abs(p["order"] - current["order"]) == 1]
        if neighbours:
            lines.append(
                "- 앞뒤 대운(참고): "
                + " / ".join(
                    f"{p['pillar']} {p['start_year']}~{p['end_year']}"
                    for p in neighbours
                )
            )
    elif daeun:
        lines.append("[지금 지나고 있는 대운]")
        lines.append(
            f"- {daeun.get('current_status', '확인 불가')} — "
            f"대운은 {daeun['start_age']}세({daeun['periods'][0]['start_year']}년)부터 "
            f"{daeun['periods'][0]['pillar']} 대운으로 시작된다."
        )
        lines.append("- 아직 대운에 들어서지 않았으므로 대운 해석은 조심스럽게 하라.")
    else:
        lines.append("[지금 지나고 있는 대운]")
        lines.append(
            "- " + (no_daeun_reason
                    or "계산하지 못했다. 대운을 근거로 든 해석은 하지 말 것.")
        )

    # --- 세운 ---------------------------------------------------
    lines.append("")
    lines.append("[올해의 세운]")
    lines.append(
        f"- {sewoon['year']}년(사주 기준, 입춘 이후): "
        f"{sewoon['pillar']}({sewoon['pillar_hanja']}) · {sewoon['animal']}띠"
    )
    lines.append(
        f"- 올해 천간의 오행: {sewoon['stem_ohaeng']} / "
        f"지지의 오행: {sewoon['branch_ohaeng']}"
    )

    # --- 원국과 견준 메모 -----------------------------------------
    if saju:
        if daeun:
            lines.append("")
            lines.append("[대운이 원국과 만나는 자리]")
            lines.extend(f"- {note}" for note in daeun_notes(saju, daeun))
        lines.append("")
        lines.append("[세운이 원국과 만나는 자리]")
        lines.extend(f"- {note}" for note in sewoon_notes(saju, sewoon))

    if daeun:
        lines.append("")
        lines.append("[대운 × 세운이 겹치는 자리]")
        lines.extend(f"- {note}" for note in flow_notes(daeun, sewoon))

    lines.append("")
    lines.append(LUCK_LOCK_RULES)
    return "\n".join(lines)


# ===============================================================
#  8. 개발용 요약 (화면·테스트에서 눈으로 확인할 때)
# ===============================================================
def describe(daeun: dict | None, sewoon: dict) -> str:
    """터미널·개발자 화면에서 계산값을 한눈에 보는 글."""
    lines = ["[DAEUN CALCULATION]"]
    if daeun is None:
        lines.append("  (계산하지 않음 — 성별 미확인)")
    else:
        current = daeun.get("current")
        lines.append(f"  direction      : {daeun['direction']}")
        lines.append(f"  start_age      : {daeun['start_age']}")
        lines.append(
            f"  current_pillar : {current['pillar'] if current else '-'}"
        )
        lines.append(
            "  current_period : "
            + (f"{current['start_year']}~{current['end_year']} "
               f"(만 {current['start_age']}~{current['end_age']}세)"
               if current else daeun.get("current_status", "-"))
        )
    lines.append("")
    lines.append("[SEWOON CALCULATION]")
    lines.append(f"  year           : {sewoon['year']}")
    lines.append(f"  pillar         : {sewoon['pillar']}({sewoon['pillar_hanja']})")
    return "\n".join(lines)


# ---------------------------------------------------------------
#  터미널에서 바로 확인해보기
#      python daeun.py 1999-04-12 08:49 여성
#      python daeun.py 1985-06-15 모름 남성 음력 윤달
#
#  여기 적힌 값은 개발용 예시(fixture)입니다. 실제 사용자 정보가 아닙니다.
# ---------------------------------------------------------------
if __name__ == "__main__":
    import sys

    argv = sys.argv[1:]
    raw_date = argv[0] if argv else "1999-04-12"
    raw_time = argv[1] if len(argv) > 1 else "08:49"
    raw_gender = argv[2] if len(argv) > 2 else "여성"
    kind = argv[3] if len(argv) > 3 else "양력"
    leap = argv[4] if len(argv) > 4 else None

    parsed_time = None
    if raw_time not in ("모름", "-", "none", "None"):
        parsed_time = time.fromisoformat(raw_time)

    saju_result = compute_saju(
        date.fromisoformat(raw_date), parsed_time, kind, leap
    )
    sewoon_result = compute_sewoon()

    try:
        daeun_result = compute_daeun(saju_result, raw_gender)
    except DaeunError as error:
        print(f"[대운 계산 안 됨] {error}")
        daeun_result = None

    print(f"명식      : "
          f"{saju_result['년주']['한글']} {saju_result['월주']['한글']} "
          f"{saju_result['일주']['한글']} "
          f"{saju_result['시주']['한글'] if saju_result['시주'] else '(시주 없음)'}")
    print()
    print(describe(daeun_result, sewoon_result))

    if daeun_result:
        print()
        print("[대운 전체 구간]")
        for period in daeun_result["periods"]:
            mark = " ←지금" if period is daeun_result.get("current") else ""
            print(
                f"  {period['order']:>2}. {period['pillar']}"
                f"({period['pillar_hanja']})  "
                f"{period['start_year']}~{period['end_year']}  "
                f"만 {period['start_age']:>2}~{period['end_age']:>2}세{mark}"
            )
        print()
        print("[계산 기준]")
        for name, value in daeun_result["basis"].items():
            print(f"  {name:<16} {value}")

    print()
    print("[프롬프트로 나가는 글]")
    print(format_year_flow_for_prompt(daeun_result, sewoon_result, saju_result))
