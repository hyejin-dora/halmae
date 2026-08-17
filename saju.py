"""생년월일 → 사주(四柱) 해석에 쓸 수 있는 구조화 데이터

이 파일은 화면(Streamlit)과 상관없이 혼자서도 돌아가는 계산 전용 모듈입니다.
그래서 터미널에서 바로 값을 확인해볼 수 있습니다.

    python saju.py 1999-04-12 08:49 양력
    python saju.py 1985-06-15 모름 음력 윤달

이 모듈이 하는 일은 크게 두 가지입니다.

    1) 양력 ↔ 음력 변환            → compute_calendar_info()
       korean_lunar_calendar 패키지가 담당합니다.

    2) 사주 네 기둥 + 오행 분포     → compute_saju()
       년주·월주는 '절기(節氣)' 기준, 일주는 '일진', 시주는 '시지'로 계산합니다.
       korean_lunar_calendar 가 알려주는 간지는 '음력 기준'이라 전통 사주와
       다르기 때문에, 사주 계산에는 쓰지 않고 이 모듈이 직접 계산합니다.

절기는 태양의 겉보기 황경(黃經)으로 정의됩니다.
    입춘 315° · 경칩 345° · 청명 15° · 입하 45° · 망종 75° · 소서 105°
    입추 135° · 백로 165° · 한로 195° · 입동 225° · 대설 255° · 소한 285°
황경은 Meeus 의 태양 위치 근사식으로 구합니다. (오차 약 ±10분)
"""

import math
from datetime import date, datetime, time, timedelta, timezone
from zoneinfo import ZoneInfo

from korean_lunar_calendar import KoreanLunarCalendar

# 이 패키지가 다룰 수 있는 날짜 범위 (양력 1000-02-13 ~ 2050-12-31)
SOLAR_MIN = date(1000, 2, 13)
SOLAR_MAX = date(2050, 12, 31)

# 한국 표준시. 서머타임과 과거의 UTC+8:30 시절까지 담고 있는 공식 시간대 자료입니다.
KOREA_TZ = ZoneInfo("Asia/Seoul")

# 사주에서 쓰는 기준 표준시 (동경 135도)
STANDARD_TZ = timezone(timedelta(hours=9))


class CalendarError(Exception):
    """사용자에게 그대로 보여줘도 되는, 이해하기 쉬운 계산 오류 메시지."""


# ===============================================================
#  천간 · 지지 기본 표
# ===============================================================
CHEONGAN = ["갑", "을", "병", "정", "무", "기", "경", "신", "임", "계"]
CHEONGAN_HANJA = ["甲", "乙", "丙", "丁", "戊", "己", "庚", "辛", "壬", "癸"]

JIJI = ["자", "축", "인", "묘", "진", "사", "오", "미", "신", "유", "술", "해"]
JIJI_HANJA = ["子", "丑", "寅", "卯", "辰", "巳", "午", "未", "申", "酉", "戌", "亥"]

# 천간의 오행 (갑을=목, 병정=화, 무기=토, 경신=금, 임계=수)
CHEONGAN_OHAENG = ["목", "목", "화", "화", "토", "토", "금", "금", "수", "수"]

# 지지의 오행 (자=수, 축=토, 인묘=목, 진=토, 사오=화, 미=토, 신유=금, 술=토, 해=수)
JIJI_OHAENG = ["수", "토", "목", "목", "토", "화", "화", "토", "금", "금", "토", "수"]

# 짝수 번째가 양(陽), 홀수 번째가 음(陰)
OHAENG_ORDER = ["목", "화", "토", "금", "수"]

# 지지에 대응하는 띠 (참고용)
JIJI_ANIMAL = [
    "쥐", "소", "호랑이", "토끼", "용", "뱀",
    "말", "양", "원숭이", "닭", "개", "돼지",
]

# 12절기: (이름, 태양 황경, 이 절기부터 시작되는 월지 인덱스)
#   월지는 인월(寅月)부터 시작합니다. 인=2 이므로 인덱스 2부터 한 칸씩 나아갑니다.
SOLAR_TERMS = [
    ("입춘", 315, 2),   # 인월
    ("경칩", 345, 3),   # 묘월
    ("청명", 15, 4),    # 진월
    ("입하", 45, 5),    # 사월
    ("망종", 75, 6),    # 오월
    ("소서", 105, 7),   # 미월
    ("입추", 135, 8),   # 신월
    ("백로", 165, 9),   # 유월
    ("한로", 195, 10),  # 술월
    ("입동", 225, 11),  # 해월
    ("대설", 255, 0),   # 자월
    ("소한", 285, 1),   # 축월
]

# 시지 경계 (23시부터 자시가 시작되고, 두 시간씩 끊어집니다)
SIJI_RANGE = [
    "23:00~00:59", "01:00~02:59", "03:00~04:59", "05:00~06:59",
    "07:00~08:59", "09:00~10:59", "11:00~12:59", "13:00~14:59",
    "15:00~16:59", "17:00~18:59", "19:00~20:59", "21:00~22:59",
]

# 진태양시(경도 보정)를 쓸 때 필요한 출생지 경도. 모르면 보정하지 않습니다.
KOREA_LONGITUDES = {
    "서울": 126.978, "인천": 126.705, "수원": 127.029, "춘천": 127.734,
    "강릉": 128.896, "대전": 127.385, "청주": 127.489, "천안": 127.115,
    "전주": 127.148, "광주": 126.852, "목포": 126.392, "여수": 127.662,
    "대구": 128.601, "포항": 129.343, "부산": 129.075, "울산": 129.311,
    "창원": 128.682, "제주": 126.531,
}

# 시주 계산에 쓸 시각 기준
HOUR_BASIS_STANDARD = "표준시"      # 동경 135도 표준시 (UTC+9)
HOUR_BASIS_TRUE_SOLAR = "진태양시"  # 출생지 경도로 보정한 지방 평균시

NO_BIRTH_TIME_NOTE = "출생시간 미입력으로 시주 해석 제외"


# ===============================================================
#  양력 / 음력 변환  (기존 기능 그대로)
# ===============================================================
def _split_gapja(korean: str, chinese: str) -> dict:
    """'기사년 정축월 병인일' + '己巳年 丁丑月 丙寅日' 을 기둥별로 나눕니다.

    주의: 이 값은 korean_lunar_calendar 의 '음력 기준' 간지입니다.
    사주 계산에는 쓰지 않고, 참고용으로만 보여줍니다.
    """
    pillars = {}
    korean_parts = (korean or "").split()
    chinese_parts = (chinese or "").split()

    for index, name in enumerate(("년주", "월주", "일주")):
        # "기사년" 처럼 뒤에 붙은 년/월/일 글자는 떼어냅니다.
        ko = korean_parts[index][:-1] if index < len(korean_parts) else ""
        ch = chinese_parts[index][:-1] if index < len(chinese_parts) else ""
        pillars[name] = {"한글": ko, "한자": ch}

    return pillars


def compute_calendar_info(
    birth_date: date,
    calendar_type: str = "양력",
    leap_month: str | None = None,
) -> dict:
    """생년월일 하나로 양력·음력·간지를 한 번에 계산합니다.

    birth_date    : 사용자가 입력한 날짜 (양력이면 양력 날짜, 음력이면 음력 날짜)
    calendar_type : "양력" 또는 "음력"
    leap_month    : 음력일 때 "평달" 또는 "윤달" (양력이면 None)

    돌려주는 값: 화면에 그대로 뿌릴 수 있는 dict
    계산이 안 되면 CalendarError를 냅니다.
    """
    if birth_date is None:
        raise CalendarError("생년월일이 없어서 계산할 수 없어요.")

    is_lunar_input = calendar_type == "음력"
    wants_leap = is_lunar_input and leap_month == "윤달"

    calendar = KoreanLunarCalendar()

    if is_lunar_input:
        ok = calendar.setLunarDate(
            birth_date.year, birth_date.month, birth_date.day, wants_leap
        )
        if not ok:
            if wants_leap:
                raise CalendarError(
                    f"음력 {birth_date.year}년에는 윤{birth_date.month}월이 없어요. "
                    "'평달'로 바꾸어 다시 확인해주세요."
                )
            raise CalendarError(
                f"음력 {birth_date.year}년 {birth_date.month}월 {birth_date.day}일은 "
                "달력에 없는 날짜예요. 날짜를 다시 확인해주세요."
            )
    else:
        if not SOLAR_MIN <= birth_date <= SOLAR_MAX:
            raise CalendarError(
                "이 달력이 다룰 수 있는 범위(1000년 ~ 2050년)를 벗어난 날짜예요."
            )
        ok = calendar.setSolarDate(
            birth_date.year, birth_date.month, birth_date.day
        )
        if not ok:
            raise CalendarError(
                "양력 날짜를 음력으로 바꾸지 못했어요. 날짜를 다시 확인해주세요."
            )

    solar = date(calendar.solarYear, calendar.solarMonth, calendar.solarDay)
    is_leap = bool(calendar.isIntercalation)

    lunar_text = (
        f"{calendar.lunarYear}년 {calendar.lunarMonth}월 {calendar.lunarDay}일"
    )
    if is_leap:
        lunar_text += " (윤달)"

    input_text = f"{birth_date.year}년 {birth_date.month}월 {birth_date.day}일"
    if is_lunar_input:
        input_text += f" (음력 · {leap_month or '평달'})"
    else:
        input_text += " (양력)"

    gapja_korean = calendar.getGapJaString()          # 예) 기사년 정축월 병인일
    gapja_chinese = calendar.getChineseGapJaString()  # 예) 己巳年 丁丑月 丙寅日

    return {
        "입력 방식": calendar_type,
        "입력 날짜": input_text,
        "양력 날짜": solar,
        "양력 날짜 표기": f"{solar.year}년 {solar.month}월 {solar.day}일",
        "음력 날짜": lunar_text,
        "음력 연": calendar.lunarYear,
        "음력 월": calendar.lunarMonth,
        "음력 일": calendar.lunarDay,
        "윤달 여부": is_leap,
        "간지(음력 기준·참고용)": _split_gapja(gapja_korean, gapja_chinese),
        "간지 한글": gapja_korean,
        "간지 한자": gapja_chinese,
    }


# ===============================================================
#  태양 황경 → 절기
# ===============================================================
def _to_julian_day(moment: datetime) -> float:
    """UTC 시각을 율리우스일(JD)로 바꿉니다."""
    moment = moment.astimezone(timezone.utc)
    year, month = moment.year, moment.month
    if month <= 2:
        year -= 1
        month += 12
    century = year // 100
    gregorian = 2 - century + century // 4
    day_fraction = (
        moment.day
        + (moment.hour + moment.minute / 60 + moment.second / 3600) / 24
    )
    return (
        int(365.25 * (year + 4716))
        + int(30.6001 * (month + 1))
        + day_fraction
        + gregorian
        - 1524.5
    )


def _from_julian_day(julian_day: float) -> datetime:
    """율리우스일(JD)을 UTC 시각으로 되돌립니다."""
    base = datetime(2000, 1, 1, 12, tzinfo=timezone.utc)
    return base + timedelta(days=julian_day - 2451545.0)


def sun_longitude(julian_day: float) -> float:
    """태양의 겉보기 황경(도, 0~360). Meeus 근사식 · 오차 약 0.01도(≈15분).

    이 값이 315도가 되는 순간이 입춘, 345도가 되는 순간이 경칩입니다.
    """
    t = (julian_day - 2451545.0) / 36525.0

    # 태양의 기하 평균 황경
    mean_longitude = 280.46646 + 36000.76983 * t + 0.0003032 * t * t
    # 태양의 평균 근점 이각
    anomaly = math.radians(357.52911 + 35999.05029 * t - 0.0001537 * t * t)
    # 중심차 (타원 궤도 보정)
    center = (
        (1.914602 - 0.004817 * t - 0.000014 * t * t) * math.sin(anomaly)
        + (0.019993 - 0.000101 * t) * math.sin(2 * anomaly)
        + 0.000289 * math.sin(3 * anomaly)
    )
    true_longitude = mean_longitude + center

    # 장동(章動)과 광행차(光行差) 보정 → 겉보기 황경
    node = math.radians(125.04 - 1934.136 * t)
    apparent = true_longitude - 0.00569 - 0.00478 * math.sin(node)
    return apparent % 360.0


def _longitude_gap(julian_day: float, target: float) -> float:
    """목표 황경까지 얼마나 남았는지 (-180 ~ +180). 이미 지났으면 양수."""
    return (sun_longitude(julian_day) - target + 180.0) % 360.0 - 180.0


def find_solar_term(julian_day: float, target_longitude: float) -> float:
    """주어진 시각 이전에 태양이 target_longitude 를 마지막으로 지난 순간(JD)."""
    upper = julian_day
    # 아직 지나기 전이면 하루씩 뒤로 물러납니다.
    steps = 0
    while _longitude_gap(upper, target_longitude) < 0 and steps < 400:
        upper -= 1.0
        steps += 1

    lower = upper - 2.0
    steps = 0
    while _longitude_gap(lower, target_longitude) > 0 and steps < 400:
        lower -= 1.0
        steps += 1

    # 이분법으로 초 단위까지 좁혀 나갑니다.
    for _ in range(60):
        middle = (lower + upper) / 2
        if _longitude_gap(middle, target_longitude) >= 0:
            upper = middle
        else:
            lower = middle
    return (lower + upper) / 2


def _term_index(julian_day: float) -> int:
    """이 시각이 SOLAR_TERMS 의 몇 번째 절기 구간에 있는지 (0=입춘 구간)."""
    longitude = sun_longitude(julian_day)
    return int(((longitude - 315.0) % 360.0) // 30.0)


# ===============================================================
#  네 기둥 만들기
# ===============================================================
def _make_pillar(stem_index: int, branch_index: int) -> dict:
    """천간·지지 번호 한 쌍을 화면과 프롬프트에 바로 쓸 수 있는 dict로."""
    stem_index %= 10
    branch_index %= 12
    return {
        "한글": CHEONGAN[stem_index] + JIJI[branch_index],
        "한자": CHEONGAN_HANJA[stem_index] + JIJI_HANJA[branch_index],
        "천간": {
            "한글": CHEONGAN[stem_index],
            "한자": CHEONGAN_HANJA[stem_index],
            "오행": CHEONGAN_OHAENG[stem_index],
            "음양": "양" if stem_index % 2 == 0 else "음",
        },
        "지지": {
            "한글": JIJI[branch_index],
            "한자": JIJI_HANJA[branch_index],
            "오행": JIJI_OHAENG[branch_index],
            "음양": "양" if branch_index % 2 == 0 else "음",
            "띠": JIJI_ANIMAL[branch_index],
        },
    }


def _day_pillar_index(day: date) -> int:
    """일주의 60갑자 번호(0=갑자). 율리우스일에서 바로 나옵니다.

    (JDN + 49) % 60 이라는 관계는 korean_lunar_calendar 의 일진과
    1901~2049년 전 구간에서 일치하는 것을 확인했습니다.
    """
    a = (14 - day.month) // 12
    y = day.year + 4800 - a
    m = day.month + 12 * a - 3
    julian_day_number = (
        day.day + (153 * m + 2) // 5 + 365 * y
        + y // 4 - y // 100 + y // 400 - 32045
    )
    return (julian_day_number + 49) % 60


def _count_ohaeng(pillars: dict) -> dict:
    """네 기둥의 천간·지지를 모두 세어 오행 개수를 냅니다."""
    counts = {name: 0 for name in OHAENG_ORDER}
    for pillar in pillars.values():
        if not pillar:
            continue
        counts[pillar["천간"]["오행"]] += 1
        counts[pillar["지지"]["오행"]] += 1
    return counts


# ===============================================================
#  사주 계산 (바깥에서 부르는 함수)
# ===============================================================
def compute_saju(
    birth_date: date,
    birth_time: time | None = None,
    calendar_type: str = "양력",
    leap_month: str | None = None,
    hour_basis: str = HOUR_BASIS_STANDARD,
    birth_place: str | None = None,
) -> dict:
    """생년월일시 → 년주·월주·일주·시주 + 오행 분포.

    birth_date    : 입력한 날짜 (양력이면 양력, 음력이면 음력)
    birth_time    : 출생시간. None 이면 시주를 계산하지 않습니다.
    calendar_type : "양력" 또는 "음력"
    leap_month    : 음력일 때 "평달" / "윤달"
    hour_basis    : "표준시"(동경 135도) 또는 "진태양시"(출생지 경도 보정)
    birth_place   : 진태양시를 쓸 때 경도를 찾기 위한 지역 이름

    계산이 안 되면 CalendarError를 냅니다.
    """
    calendar_info = compute_calendar_info(birth_date, calendar_type, leap_month)
    solar_date: date = calendar_info["양력 날짜"]

    notes: list[str] = []          # 사람이 확인해야 할 주의사항
    has_time = birth_time is not None

    # --- 1. 출생 시각을 UTC 로 옮깁니다 --------------------------
    #     서머타임이 있던 해, UTC+8:30 이던 시절까지 시간대 자료가 처리해줍니다.
    reference_time = birth_time if has_time else time(12, 0)
    local_naive = datetime.combine(solar_date, reference_time)
    local_aware = local_naive.replace(tzinfo=KOREA_TZ)
    utc_moment = local_aware.astimezone(timezone.utc)

    utc_offset = local_aware.utcoffset() or timedelta(0)
    dst_offset = local_aware.dst() or timedelta(0)
    if dst_offset:
        notes.append(
            f"출생일에 서머타임이 시행 중이었어요(+{int(dst_offset.total_seconds() // 3600)}시간). "
            "표준시로 되돌려 계산했습니다."
        )
    if utc_offset - dst_offset != timedelta(hours=9):
        base_hours = (utc_offset - dst_offset).total_seconds() / 3600
        notes.append(
            f"출생 당시 한국 표준시는 UTC+{base_hours:g} 였어요. "
            "동경 135도(UTC+9) 기준으로 환산해 계산했습니다."
        )

    julian_day = _to_julian_day(utc_moment)

    # --- 2. 월주의 근거가 되는 절기 구간 -------------------------
    term_index = _term_index(julian_day)
    term_name, term_longitude, month_branch = SOLAR_TERMS[term_index]
    term_jd = find_solar_term(julian_day, term_longitude)
    term_moment = _from_julian_day(term_jd).astimezone(STANDARD_TZ)

    next_name, next_longitude, _ = SOLAR_TERMS[(term_index + 1) % 12]
    next_jd = find_solar_term(julian_day + 32, next_longitude)
    next_moment = _from_julian_day(next_jd).astimezone(STANDARD_TZ)

    # 절입 시각에 너무 가까우면 년주·월주가 뒤집힐 수 있으니 알려줍니다.
    hours_since_term = (julian_day - term_jd) * 24
    hours_to_next = (next_jd - julian_day) * 24
    boundary_margin = min(hours_since_term, hours_to_next)
    if boundary_margin < 6:
        notes.append(
            f"출생 시각이 절입({term_name} 또는 {next_name})과 "
            f"{boundary_margin:.1f}시간밖에 차이가 나지 않아요. "
            "절기 계산 오차(±15분 내외) 때문에 월주(경우에 따라 년주)가 "
            "달라질 수 있으니 만세력으로 한 번 더 확인해주세요."
        )
    if not has_time:
        notes.append(
            "출생시간을 몰라 절기 판정에는 정오(12:00)를 기준으로 삼았어요."
        )

    # --- 3. 년주 : 입춘을 기준으로 해가 바뀝니다 ------------------
    ipchun_jd = find_solar_term(julian_day, 315)
    ipchun_moment = _from_julian_day(ipchun_jd).astimezone(STANDARD_TZ)
    saju_year = ipchun_moment.year          # 입춘이 속한 해가 곧 사주의 해

    # 서기 4년이 갑자년입니다.
    year_stem = (saju_year - 4) % 10
    year_branch = (saju_year - 4) % 12
    year_pillar = _make_pillar(year_stem, year_branch)

    if saju_year != solar_date.year:
        notes.append(
            f"입춘({ipchun_moment:%Y-%m-%d %H:%M} KST) 전에 태어나서 "
            f"사주상 해는 {saju_year}년으로 봅니다."
        )

    # --- 4. 월주 : 년간에서 인월의 천간이 정해집니다 --------------
    #     갑기년 → 병인월, 을경년 → 무인월, 병신년 → 경인월,
    #     정임년 → 임인월, 무계년 → 갑인월
    first_month_stem = (year_stem % 5) * 2 + 2
    steps_from_tiger = (month_branch - 2) % 12
    month_stem = (first_month_stem + steps_from_tiger) % 10
    month_pillar = _make_pillar(month_stem, month_branch)

    # --- 5. 일주 : 날짜만으로 정해집니다 --------------------------
    day_index = _day_pillar_index(solar_date)
    day_stem = day_index % 10
    day_branch = day_index % 12
    day_pillar = _make_pillar(day_stem, day_branch)

    # --- 6. 시주 : 출생시간이 있을 때만 ---------------------------
    hour_pillar = None
    hour_detail: dict | None = None
    hour_skip_reason = None

    if not has_time:
        hour_skip_reason = NO_BIRTH_TIME_NOTE
    else:
        # 6-1. 시주를 판정할 시각 (표준시 또는 진태양시)
        longitude = None
        if hour_basis == HOUR_BASIS_TRUE_SOLAR:
            longitude = _lookup_longitude(birth_place)
            if longitude is None:
                notes.append(
                    f"출생지 '{birth_place or '미입력'}' 의 경도를 찾지 못해 "
                    "진태양시 보정을 하지 못했어요. 표준시로 계산했습니다."
                )
                hour_basis = HOUR_BASIS_STANDARD

        if hour_basis == HOUR_BASIS_TRUE_SOLAR and longitude is not None:
            shift = timedelta(hours=longitude / 15.0)
            judged = utc_moment + shift
            basis_label = f"진태양시(경도 {longitude:g}°E · 평균태양시)"
        else:
            judged = utc_moment.astimezone(STANDARD_TZ)
            basis_label = "동경 135도 표준시(UTC+9)"

        # 6-2. 23시부터 자시가 시작되므로 한 시간 밀어서 2로 나눕니다.
        hour_branch = ((judged.hour + 1) // 2) % 12
        hour_stem = ((day_stem % 5) * 2 + hour_branch) % 10
        hour_pillar = _make_pillar(hour_stem, hour_branch)

        hour_detail = {
            "기준": basis_label,
            "판정에 쓴 시각": judged.strftime("%H:%M"),
            "시지 구간": f"{JIJI[hour_branch]}시 ({SIJI_RANGE[hour_branch]})",
        }

        if judged.hour == 23:
            notes.append(
                "밤 23시대에 태어났어요. 이 시간을 '야자시'로 보아 일주를 "
                "다음 날로 넘기는 유파도 있습니다. 여기서는 일주를 넘기지 않고, "
                "시지만 자시로 잡았습니다."
            )
        if hour_basis == HOUR_BASIS_STANDARD:
            notes.append(
                "시주는 동경 135도 표준시 그대로 계산했어요. "
                "출생지 경도로 30분 안팎을 앞당기는 '진태양시' 방식을 쓰면 "
                "경계 시각(홀수시 정각 부근)에서는 시지가 달라질 수 있습니다."
            )

    # --- 7. 오행 분포 --------------------------------------------
    pillars = {
        "년주": year_pillar,
        "월주": month_pillar,
        "일주": day_pillar,
        "시주": hour_pillar,
    }
    ohaeng = _count_ohaeng(pillars)
    counted = 8 if has_time else 6

    return {
        # --- 기둥 ---
        "기둥": pillars,
        "년주": year_pillar,
        "월주": month_pillar,
        "일주": day_pillar,
        "시주": hour_pillar,
        # --- 시주 상태 ---
        "시주 계산 여부": has_time,
        "시주 제외 사유": hour_skip_reason,
        "시주 계산 근거": hour_detail,
        # --- 오행 ---
        "오행 분포": ohaeng,
        "오행 요약": " / ".join(f"{k} {ohaeng[k]}" for k in OHAENG_ORDER),
        "오행 글자수": counted,
        "일간": day_pillar["천간"],          # 사주 해석의 중심이 되는 글자
        # --- 계산 근거 ---
        "양력 날짜": solar_date,
        "양력 날짜 표기": calendar_info["양력 날짜 표기"],
        "음력 날짜": calendar_info["음력 날짜"],
        "출생시간": birth_time.strftime("%H:%M") if has_time else None,
        "적용 절기": {
            "현재 구간": term_name,
            "절입 시각": f"{term_moment:%Y-%m-%d %H:%M} KST",
            "다음 절기": next_name,
            "다음 절입 시각": f"{next_moment:%Y-%m-%d %H:%M} KST",
            "월지": f"{JIJI[month_branch]}월",
        },
        "입춘 시각": f"{ipchun_moment:%Y-%m-%d %H:%M} KST",
        "사주 기준 연도": saju_year,
        "달력 정보": calendar_info,
        "주의사항": notes,
    }


def compute_year_ganji(target_date: date | None = None) -> dict:
    """'올해'의 간지(세운·歲運)를 계산합니다.

    사주에서 해가 바뀌는 기준은 1월 1일이 아니라 입춘입니다.
    그래서 1월에 이 함수를 부르면 아직 지난해의 간지가 나옵니다.

    올해의 카드처럼 "올해는 어떤 기운인가"를 이야기할 때 근거로 씁니다.
    """
    target_date = target_date or date.today()
    noon_utc = datetime.combine(target_date, time(12, 0)).replace(
        tzinfo=KOREA_TZ
    ).astimezone(timezone.utc)
    julian_day = _to_julian_day(noon_utc)

    ipchun_jd = find_solar_term(julian_day, 315)
    ipchun_moment = _from_julian_day(ipchun_jd).astimezone(STANDARD_TZ)
    saju_year = ipchun_moment.year

    stem = (saju_year - 4) % 10
    branch = (saju_year - 4) % 12
    pillar = _make_pillar(stem, branch)

    return {
        "연도": saju_year,
        "달력 연도": target_date.year,
        "간지": pillar,
        "한글": pillar["한글"],
        "한자": pillar["한자"],
        "천간 오행": pillar["천간"]["오행"],
        "지지 오행": pillar["지지"]["오행"],
        "띠": pillar["지지"]["띠"],
        "입춘 시각": f"{ipchun_moment:%Y-%m-%d %H:%M} KST",
    }


def year_luck_notes(saju: dict, year_ganji: dict) -> list[str]:
    """올해 기운과 내 사주를 견줘, 눈에 띄는 점을 짧게 짚어줍니다.

    '올해는 화 기운이 강한데 네 사주에는 화가 하나도 없더라' 처럼
    사람이 이해할 수 있는 형태로 만들어, 카드 해석의 근거로 넘깁니다.
    """
    notes: list[str] = []
    counts = saju["오행 분포"]
    day_stem = saju["일간"]

    for label, ohaeng in (
        ("천간", year_ganji["천간 오행"]),
        ("지지", year_ganji["지지 오행"]),
    ):
        have = counts.get(ohaeng, 0)
        if have == 0:
            notes.append(
                f"올해 {label}의 {ohaeng} 기운은 이 사람 사주에 0개라 "
                f"평소 부족했던 기운이 올해 들어온다."
            )
        elif have >= 4:
            notes.append(
                f"올해 {label}도 {ohaeng}인데 이 사람 사주에 이미 {have}개라 "
                f"{ohaeng} 기운이 더 과해진다."
            )

    if year_ganji["천간 오행"] == day_stem["오행"]:
        notes.append(
            f"올해 천간({year_ganji['간지']['천간']['한글']})의 오행이 "
            f"일간({day_stem['한글']})과 같은 {day_stem['오행']}이라, "
            "나와 비슷한 기운이 하나 더 들어오는 해다."
        )

    if not notes:
        notes.append(
            f"올해 기운({year_ganji['천간 오행']}·{year_ganji['지지 오행']})은 "
            "이 사람 사주에서 특별히 치우치거나 비어 있던 자리는 아니다."
        )
    return notes


def _lookup_longitude(place: str | None) -> float | None:
    """'서울특별시' 같은 입력에서 경도를 찾습니다. 못 찾으면 None."""
    if not place:
        return None
    text = place.strip()
    for city, longitude in KOREA_LONGITUDES.items():
        if city in text:
            return longitude
    return None


# ===============================================================
#  Gemini 에 그대로 넣을 수 있는 글 (다시 계산하지 말라는 지시 포함)
# ===============================================================
def format_saju_for_prompt(saju: dict) -> str:
    """계산된 사주를 프롬프트에 붙일 수 있는 글자로 바꿉니다.

    Gemini 가 이 값을 다시 계산하지 않도록, 확정값이라는 점을 못 박아둡니다.
    (프롬프트에 실제로 붙이는 일은 다음 단계에서 합니다.)
    """
    lines = ["[사주 명식 — Python에서 계산 완료. 다시 계산하지 말고 그대로 사용할 것]"]

    for name in ("년주", "월주", "일주", "시주"):
        pillar = saju["기둥"][name]
        if pillar is None:
            lines.append(f"- {name}: (없음) — {saju['시주 제외 사유']}")
            continue
        stem, branch = pillar["천간"], pillar["지지"]
        lines.append(
            f"- {name}: {pillar['한글']}({pillar['한자']}) · "
            f"천간 {stem['한글']}={stem['오행']}, 지지 {branch['한글']}={branch['오행']}"
        )

    ohaeng = saju["오행 분포"]
    lines.append("")
    lines.append(f"[오행 분포 — 총 {saju['오행 글자수']}글자]")
    for name in OHAENG_ORDER:
        lines.append(f"- {name}: {ohaeng[name]}")

    lines.append("")
    lines.append(f"[일간] {saju['일간']['한글']}({saju['일간']['한자']}) · {saju['일간']['오행']}")
    lines.append(
        f"[월령] {saju['적용 절기']['월지']} "
        f"({saju['적용 절기']['현재 구간']} 이후)"
    )

    if not saju["시주 계산 여부"]:
        lines.append("")
        lines.append(f"[주의] {saju['시주 제외 사유']}. 시주와 관련된 해석은 하지 말 것.")

    return "\n".join(lines)


# ---------------------------------------------------------------
#  터미널에서 바로 확인해보기
#      python saju.py 1999-04-12 08:49 양력
#      python saju.py 1985-06-15 모름 음력 윤달
# ---------------------------------------------------------------
if __name__ == "__main__":
    import sys

    argv = sys.argv[1:]
    raw_date = argv[0] if argv else "1999-04-12"
    raw_time = argv[1] if len(argv) > 1 else "08:49"
    kind = argv[2] if len(argv) > 2 else "양력"
    leap = argv[3] if len(argv) > 3 else None

    parsed_time = None
    if raw_time not in ("모름", "-", "none", "None"):
        parsed_time = time.fromisoformat(raw_time)

    result = compute_saju(
        date.fromisoformat(raw_date), parsed_time, kind, leap
    )

    print(f"양력      : {result['양력 날짜 표기']}")
    print(f"음력      : {result['음력 날짜']}")
    print(f"출생시간  : {result['출생시간'] or '모름'}")
    print()
    for name in ("년주", "월주", "일주", "시주"):
        pillar = result["기둥"][name]
        if pillar is None:
            print(f"{name}      : (제외) {result['시주 제외 사유']}")
        else:
            print(f"{name}      : {pillar['한글']} ({pillar['한자']})")
    print()
    for name in OHAENG_ORDER:
        print(f"{name}        : {result['오행 분포'][name]}")
    print()
    print(f"절기      : {result['적용 절기']}")
    print(f"입춘      : {result['입춘 시각']}")
    if result["시주 계산 근거"]:
        print(f"시주 근거 : {result['시주 계산 근거']}")
    for note in result["주의사항"]:
        print(f"! {note}")
