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
황경은 스위스 천체력(pyswisseph)으로 구합니다. 없는 환경에서는 Meeus 근사식으로
물러납니다. 어느 쪽을 썼는지는 SOLAR_TERM_SOURCE 에 적힙니다.

오행은 '표면 8자'(천간 4 + 지지 4) 만 셉니다. 지장간(支藏干)은 세지 않습니다.
이 기준은 OHAENG_BASIS 한 곳에만 적어두고, 화면·프롬프트·테스트가 모두
같은 값을 씁니다.
"""

import math
from datetime import date, datetime, time, timedelta, timezone
from zoneinfo import ZoneInfo

from korean_lunar_calendar import KoreanLunarCalendar

# 절기(節氣)는 태양의 겉보기 황경으로 정의됩니다.
# 스위스 천체력(pyswisseph)이 있으면 그것을 씁니다. 오차가 1초 안팎이라
# 절입 시각 근처에 태어난 사람의 월주가 뒤집히지 않습니다.
# 없으면 아래 Meeus 근사식으로 물러납니다. (오차 약 ±12분)
try:                                    # pragma: no cover - 환경에 따라 갈립니다
    import swisseph as _swe
    # FLG_MOSEPH: 별도 천체력 파일이 없어도 도는 Moshier 이론 (astrology.py 와 동일)
    _SWE_FLAG = _swe.FLG_MOSEPH
except Exception:                       # pragma: no cover
    _swe = None
    _SWE_FLAG = 0

SOLAR_TERM_SOURCE = "swisseph(Moshier)" if _swe else "Meeus 근사식"

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

# 오행을 세는 기준. 이 서비스는 '표면 8자'(천간 4 + 지지 4) 하나로 통일합니다.
#   - 지장간(지지 속에 숨은 천간)은 세지 않습니다.
#   - 출생시간을 모르면 시주가 빠지므로 6자만 셉니다.
# 화면·Gemini 프롬프트·테스트가 모두 이 문구를 그대로 씁니다.
OHAENG_BASIS = "표면 8자(천간 4 + 지지 4) · 지장간 제외"
OHAENG_BASIS_NO_HOUR = "표면 6자(천간 3 + 지지 3, 시주 제외) · 지장간 제외"

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

# 경도를 못 찾았을 때 쓰는 예비 표. 인터넷(geocoding)이 안 될 때만 씁니다.
#     평소에는 astrology.geocode_place() 가 찾아낸 실제 좌표를 씁니다.
KOREA_LONGITUDES = {
    "서울": 126.978, "인천": 126.705, "수원": 127.029, "춘천": 127.734,
    "강릉": 128.896, "대전": 127.385, "청주": 127.489, "천안": 127.115,
    "전주": 127.148, "광주": 126.852, "목포": 126.392, "여수": 127.662,
    "대구": 128.601, "포항": 129.343, "부산": 129.075, "울산": 129.311,
    "창원": 128.682, "제주": 126.531,
}

# ===============================================================
#  시주를 판정할 '시각의 기준'  (세 가지를 구분해 둡니다)
#
#  [왜 이 구분이 필요한가]
#      사용자 테스트에서 "년주·월주·일주는 맞는데 시주만 만세력과 다르다,
#      출생시간을 30분쯤 당기면 같아진다" 는 피드백을 받았습니다.
#      30분은 우연이 아닙니다 — 서울(동경 126.978도)과 한국 표준시의
#      기준 자오선(동경 135도) 사이의 차이가 딱 그만큼입니다.
#
#          (135 - 126.978) x 4분 = 32.1분
#
#      즉 앱은 '시계 시각' 을 그대로 썼고, 비교한 만세력은 '출생지의
#      해 위치' 로 고쳐 쓴 것입니다. 계산이 틀린 게 아니라 기준이 달랐습니다.
#
#  [세 가지 기준]
#      표준시          시계에 적힌 시각 그대로. 경도 보정을 하지 않습니다.
#      지방평균태양시   출생지 경도만으로 보정. (경도차 1도 = 4분)
#      진태양시        경도 보정 + 균시차(equation of time, 최대 +-16분)까지.
#
#  [이 서비스가 채택한 기준 — 지방평균태양시 하나뿐입니다]
#      · 한국 만세력이 '진태양시' 라는 이름으로 제공하는 보정은 실제로는
#        경도 보정만 하는 지방평균태양시입니다. (그래서 서울이 늘 -32분)
#      · 균시차는 날짜마다 값이 달라서, 같은 사람이 같은 시각에 태어나도
#        절기 위치에 따라 시지가 오갑니다. 만세력 호환성이 오히려 떨어집니다.
#      · 그래서 균시차는 '검토했고 채택하지 않은 방식' 으로 남겨둡니다.
#        (아래 equation_of_time_minutes 는 두 방식의 차이를 시험으로
#         확인하기 위한 것이고, 이 서비스의 시주 계산에는 쓰이지 않습니다)
#
#      두 방식을 섞어 쓰는 곳은 한 곳도 없습니다. ADOPTED_HOUR_BASIS 하나만 봅니다.
# ===============================================================
HOUR_BASIS_STANDARD = "표준시"            # 동경 135도 표준시 그대로
HOUR_BASIS_LMT = "지방평균태양시"          # 경도만 보정  ← 채택
HOUR_BASIS_TRUE_SOLAR = "진태양시"        # 경도 + 균시차 (검토했으나 채택 안 함)

# 이 서비스의 시주 기준. app.py 는 이 값만 씁니다.
ADOPTED_HOUR_BASIS = HOUR_BASIS_LMT

# 위 기준을 정규화한 시각이 딛고 서는 자오선.
#     계산은 늘 UTC 로 옮긴 뒤 UTC+9 로 되돌려 놓고 시작하므로(아래 1번 단계),
#     비교 대상 자오선은 언제나 동경 135도입니다.
#     한국이 UTC+8:30(자오선 127.5도) 이던 시절도 같은 순간을 UTC+9 시계로
#     바꿔 적은 것이라, 경도 보정을 하면 결국 같은 지방평균태양시가 나옵니다.
STANDARD_MERIDIAN = 135.0

NO_BIRTH_TIME_NOTE = "출생시간 미입력으로 시주 해석 제외"


# ===============================================================
#  양력 / 음력 변환  (기존 기능 그대로)
# ===============================================================
def _split_gapja(korean: str, chinese: str) -> dict:
    """'기사년 정축월 병인일' + '己巳年 丁丑月 丙寅日' 을 세 칸으로 나눕니다.

    주의: 이 값은 korean_lunar_calendar 의 '음력 기준' 간지입니다.
    사주 계산에는 쓰지 않고, 참고용으로만 보여줍니다.

    그래서 이름을 '년주/월주/일주'라고 붙이지 않습니다.
    사주의 네 기둥(compute_saju 의 '기둥')은 절기 기준이라 이 값과 다른데,
    같은 이름을 쓰면 어느 쪽이 명식인지 헷갈리기 때문입니다.
    """
    gapja = {}
    korean_parts = (korean or "").split()
    chinese_parts = (chinese or "").split()

    for index, name in enumerate(("음력 연간지", "음력 월간지", "음력 일간지")):
        # "기사년" 처럼 뒤에 붙은 년/월/일 글자는 떼어냅니다.
        ko = korean_parts[index][:-1] if index < len(korean_parts) else ""
        ch = chinese_parts[index][:-1] if index < len(chinese_parts) else ""
        gapja[name] = {"한글": ko, "한자": ch}

    return gapja


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
        "음력 간지(참고용)": _split_gapja(gapja_korean, gapja_chinese),
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
    """태양의 겉보기 황경(도, 0~360).

    이 값이 315도가 되는 순간이 입춘, 345도가 되는 순간이 경칩입니다.

    스위스 천체력이 있으면 그 값을(오차 ~1초), 없으면 Meeus 근사식을(오차 ~12분)
    씁니다. 어느 쪽을 썼는지는 SOLAR_TERM_SOURCE 에 적혀 있고, 계산 결과의
    '절기 계산 출처' 로도 함께 내보냅니다.
    """
    if _swe is not None:
        # calc_ut 은 그 시점의 춘분점을 기준으로 한 겉보기 황경을 돌려줍니다.
        # (광행차·장동 보정이 이미 들어 있어 절기 정의와 그대로 맞습니다)
        return _swe.calc_ut(julian_day, _swe.SUN, _SWE_FLAG)[0][0] % 360.0

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
#  균시차 (equation of time)  —  검토했고 채택하지 않은 방식
#
#  진태양시(해시계 시각)와 평균태양시(고르게 흐르는 시각)의 차이입니다.
#  지구 궤도가 타원이고 자전축이 기울어 있어서 생기며, 한 해 동안
#  대략 -14분 ~ +16분 사이를 오갑니다.
#
#  이 서비스의 시주 계산은 이 값을 쓰지 않습니다.
#  두 방식이 실제로 얼마나 다른지 시험(test)에서 확인하기 위해 남겨둡니다.
# ===============================================================
def equation_of_time_minutes(julian_day: float) -> float:
    """이 시각의 균시차(분). 양수면 해시계가 시계보다 앞섭니다."""
    t = (julian_day - 2451545.0) / 36525.0

    # 태양의 평균 황경과 평균 근점 이각
    mean_longitude = (280.46646 + 36000.76983 * t + 0.0003032 * t * t) % 360.0
    mean_anomaly = math.radians(
        (357.52911 + 35999.05029 * t - 0.0001537 * t * t) % 360.0
    )

    # 황도 경사각 (도)
    obliquity = (
        23.439291 - 0.0130042 * t - 1.64e-7 * t * t + 5.036e-7 * t * t * t
    )
    y = math.tan(math.radians(obliquity / 2.0)) ** 2

    # Smart 의 표준 근사식 (오차 수초 이내)
    radians_longitude = math.radians(mean_longitude)
    minutes = 4.0 * math.degrees(
        y * math.sin(2.0 * radians_longitude)
        - 2.0 * 0.016708634 * math.sin(mean_anomaly)
        + 4.0 * 0.016708634 * y * math.sin(mean_anomaly)
        * math.cos(2.0 * radians_longitude)
        - 0.5 * y * y * math.sin(4.0 * radians_longitude)
        - 1.25 * 0.016708634 ** 2 * math.sin(2.0 * mean_anomaly)
    )
    return minutes


# ===============================================================
#  시주를 판정할 시각 고르기  (여기 한 곳에서만 결정합니다)
#
#  [고정된 30분을 빼지 않습니다]
#      "모든 사용자에게서 30분을 뺀다" 는 방식은 서울에서만 맞고
#      부산(-23분)·목포(-34분)에서는 틀립니다. 경도로 계산합니다.
#
#  [추적할 수 있게 만듭니다]
#      standard_meridian / longitude_difference / correction_minutes /
#      corrected_birth_time 을 그대로 돌려줍니다. 어디서 어긋났는지
#      사람이 눈으로 따라갈 수 있어야 하니까요.
#
#  [개인정보]
#      이 함수는 값을 돌려주기만 하고, 아무것도 기록하지 않습니다.
#      로그 · analytics · Supabase 로 나가는 통로가 여기에는 없습니다.
# ===============================================================
# ===============================================================
#  이 서비스의 '시각 책임 분리' 정책  (확정 · 2026-08)
#
#  경도 보정을 도입하면서 반드시 갈라놓아야 하는 것이 하나 있습니다.
#  "보정한 시각이 날짜를 넘길 때 일주도 따라 넘어가는가?" 입니다.
#
#      [정책]  넘어가지 않습니다. 두 계산은 서로 다른 시각을 봅니다.
#
#          입력된 출생일 (달력 날짜)
#              → 년주 · 월주 · 일주
#                (절기 판정 · 일진. 기존에 검증된 기준 그대로)
#
#          출생지 경도로 보정한 시각
#              → 시지 · 시주
#                (지방평균태양시. 시주 판정에만 씁니다)
#
#  [왜 이렇게 가르는가]
#      · 년월일주는 이미 만세력과 맞는다고 확인된 계산입니다.
#        시주를 고치려고 도입한 보정이 검증된 계산을 흔들면 안 됩니다.
#      · 경도 보정은 "이 사람이 태어난 곳에서 해가 어디 있었나" 를 재는 것이지,
#        "며칠에 태어났나" 를 다시 정하는 것이 아닙니다.
#        태어난 날은 달력이 정하고, 그건 보정 대상이 아닙니다.
#      · 서울에서 00:20 에 태어난 사람은 보정하면 전날 23:48 이 되지만,
#        그 사람의 생일은 여전히 그날입니다. 일주도 그날 것을 씁니다.
#
#  [시주의 천간은 어디서 오는가]
#      시간 천간은 '일간' 으로부터 정해집니다. 그 일간은 위에서 이미 확정된
#      일주의 천간입니다 — 보정한 시각의 날짜에서 다시 뽑지 않습니다.
#      그래서 compute_hour_pillar() 는 일간을 인자로 받습니다.
#      (안에서 날짜를 다시 계산할 방법이 아예 없게 만들어 둔 것입니다)
#
#  [한 줄로]
#      출생일 → 년·월·일주 /  보정 시각 → 시주.  경계는 서로 넘지 않는다.
# ===============================================================
PILLAR_TIME_POLICY = (
    "출생지 경도 보정은 시주(시지·시간 천간) 판정에만 쓴다. "
    "년주·월주·일주는 입력된 출생일을 기준으로 한 기존 계산을 그대로 따르며, "
    "보정한 시각이 전날이나 다음날로 넘어가더라도 그 이유로 일주를 바꾸지 않는다."
)


def compute_hour_pillar(day_stem: int, judged: datetime) -> tuple[int, int]:
    """확정된 일간 + 보정한 시각 → (시간 천간, 시지) 번호.

    day_stem : **이미 확정된 일주의 천간 번호** (0=갑 … 9=계).
               compute_saju 의 5단계에서 입력된 출생일로 구한 값입니다.
               이 함수는 날짜를 받지 않습니다 — 일간을 다시 계산할 방법이
               없어야, 보정한 시각의 날짜가 일주에 스며들 수 없습니다.
    judged   : 시지를 판정할 시각 (resolve_hour_moment 가 돌려준 값).
               여기서는 시·분만 봅니다. 날짜는 보지 않습니다.

    [시지]  23시부터 자시가 시작되므로 한 시간 밀어서 두 시간씩 끊습니다.
    [천간]  갑기일 → 갑자시, 을경일 → 병자시, 병신일 → 무자시,
            정임일 → 경자시, 무계일 → 임자시 에서 시지만큼 나아갑니다.

    (PILLAR_TIME_POLICY 를 코드로 옮긴 자리입니다)
    """
    hour_branch = ((judged.hour + 1) // 2) % 12
    hour_stem = ((day_stem % 5) * 2 + hour_branch) % 10
    return hour_stem, hour_branch


def resolve_hour_moment(
    utc_moment: datetime,
    longitude: float | None,
    basis: str,
) -> tuple[datetime, dict]:
    """시주를 판정할 시각과, 그 시각이 나온 과정을 함께 돌려줍니다.

    utc_moment : 출생 순간(UTC). 서머타임·과거 표준시는 이미 정리된 값.
    longitude  : 출생지 경도(동경 양수). None 이면 보정하지 않습니다.
    basis      : HOUR_BASIS_* 중 하나.

    돌려주는 값 = (판정에 쓸 시각, 추적용 계산 과정)
    """
    # 늘 동경 135도 시계로 되돌려 놓고 시작합니다. (기준을 하나로 고정)
    standard_moment = utc_moment.astimezone(STANDARD_TZ)

    trace = {
        "basis": HOUR_BASIS_STANDARD,
        "standard_meridian": STANDARD_MERIDIAN,
        "longitude": None,
        "longitude_difference": None,
        "correction_minutes": 0.0,
        "equation_of_time_minutes": None,
        "standard_birth_time": standard_moment.strftime("%H:%M"),
        "corrected_birth_time": standard_moment.strftime("%H:%M"),
    }

    # 경도를 모르면 보정할 수 없습니다. 표준시 그대로 씁니다.
    if basis == HOUR_BASIS_STANDARD or longitude is None:
        return standard_moment, trace

    # --- 경도 보정 (지방평균태양시) ---------------------------------
    #     경도 1도 = 4분. 기준 자오선보다 서쪽이면 음수(시각이 당겨집니다).
    longitude_difference = float(longitude) - STANDARD_MERIDIAN
    correction_minutes = longitude_difference * 4.0

    trace["longitude"] = float(longitude)
    trace["longitude_difference"] = longitude_difference
    trace["correction_minutes"] = correction_minutes
    trace["basis"] = HOUR_BASIS_LMT

    # --- 균시차 (진태양시일 때만 · 이 서비스는 쓰지 않습니다) ---------
    if basis == HOUR_BASIS_TRUE_SOLAR:
        eot = equation_of_time_minutes(_to_julian_day(utc_moment))
        trace["equation_of_time_minutes"] = eot
        correction_minutes += eot
        trace["correction_minutes"] = correction_minutes
        trace["basis"] = HOUR_BASIS_TRUE_SOLAR

    corrected = standard_moment + timedelta(minutes=correction_minutes)
    trace["corrected_birth_time"] = corrected.strftime("%H:%M")
    return corrected, trace


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


def ohaeng_breakdown(pillars: dict) -> list[dict]:
    """오행을 어떻게 세었는지 글자 하나씩 펼쳐 보여줍니다.

    [{"기둥": "일주", "자리": "천간", "글자": "갑", "한자": "甲", "오행": "목"}, ...]

    합계가 왜 그렇게 나왔는지 사람이 눈으로 따라갈 수 있게 하려고 만들었습니다.
    세는 기준은 OHAENG_BASIS — 표면 8자만, 지장간은 세지 않습니다.
    """
    rows: list[dict] = []
    for pillar_name in ("년주", "월주", "일주", "시주"):
        pillar = pillars.get(pillar_name)
        if not pillar:
            continue
        for slot in ("천간", "지지"):
            part = pillar[slot]
            rows.append({
                "기둥": pillar_name,
                "자리": slot,
                "글자": part["한글"],
                "한자": part["한자"],
                "오행": part["오행"],
            })
    return rows


def _count_ohaeng(pillars: dict) -> dict:
    """네 기둥의 천간·지지를 모두 세어 오행 개수를 냅니다.

    기준은 OHAENG_BASIS 하나뿐입니다 — 표면 8자(천간 4 + 지지 4).
    지장간은 세지 않습니다. 시주가 없으면 6자만 셉니다.
    """
    counts = {name: 0 for name in OHAENG_ORDER}
    for row in ohaeng_breakdown(pillars):
        counts[row["오행"]] += 1
    return counts


# ===============================================================
#  사주 계산 (바깥에서 부르는 함수)
# ===============================================================
def compute_saju(
    birth_date: date,
    birth_time: time | None = None,
    calendar_type: str = "양력",
    leap_month: str | None = None,
    hour_basis: str = ADOPTED_HOUR_BASIS,
    birth_place: str | None = None,
    birth_longitude: float | None = None,
) -> dict:
    """생년월일시 → 년주·월주·일주·시주 + 오행 분포.

    birth_date      : 입력한 날짜 (양력이면 양력, 음력이면 음력)
    birth_time      : 출생시간. None 이면 시주를 계산하지 않습니다.
    calendar_type   : "양력" 또는 "음력"
    leap_month      : 음력일 때 "평달" / "윤달"
    hour_basis      : 시주를 판정할 시각의 기준. 기본값은 이 서비스가 채택한
                      지방평균태양시(출생지 경도 보정)입니다.
    birth_place     : 경도를 못 받았을 때 예비 표에서 찾을 지역 이름
    birth_longitude : 출생지 경도(동경 양수). geocoding 으로 얻은 실제 값이
                      있으면 이걸 넘겨주세요. 예비 표보다 이 값이 우선입니다.

    년주·월주·일주는 hour_basis 와 무관합니다.
    (절기·일진은 출생 순간 자체로 정해지므로 경도 보정과 상관이 없습니다)

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
        # 6-1. 경도 찾기 — 실제 좌표가 있으면 그것을, 없으면 예비 표를 씁니다.
        longitude = birth_longitude
        longitude_source = "출생지 좌표"
        if longitude is None:
            longitude = _lookup_longitude(birth_place)
            longitude_source = "지역명 예비 표"

        wanted_basis = hour_basis
        if wanted_basis != HOUR_BASIS_STANDARD and longitude is None:
            # 경도를 못 찾으면 보정할 수가 없습니다. 표준시로 물러나고,
            # 시지가 달라질 수 있다는 사실을 사용자에게 분명히 알립니다.
            notes.append(
                f"출생지 '{birth_place or '미입력'}' 의 경도를 찾지 못해 "
                "출생지 기준 시간 보정을 하지 못했어요. 시계 시각(동경 135도 "
                "표준시) 그대로 시주를 잡았습니다. 만세력과 시주가 다르면 "
                "출생지역을 더 자세히 적어주세요."
            )
            hour_basis = HOUR_BASIS_STANDARD
            longitude_source = "찾지 못함"

        # 6-2. 시주를 판정할 시각 (기준은 ADOPTED_HOUR_BASIS 하나뿐입니다)
        judged, hour_trace = resolve_hour_moment(
            utc_moment, longitude, hour_basis
        )

        # 6-3. 시지·시간 천간
        #     시간 천간은 위 5단계에서 '입력된 출생일'로 확정한 일간(day_stem)
        #     에서 나옵니다. 보정한 시각의 날짜로 일간을 다시 뽑지 않습니다.
        #     (compute_hour_pillar 는 날짜를 아예 받지 않습니다 — 정책을
        #      주석이 아니라 함수 모양으로 못 박아둔 것입니다)
        hour_stem, hour_branch = compute_hour_pillar(day_stem, judged)
        hour_pillar = _make_pillar(hour_stem, hour_branch)

        if hour_trace["basis"] == HOUR_BASIS_STANDARD:
            basis_label = "동경 135도 표준시(UTC+9) 그대로"
        else:
            basis_label = (
                f"{hour_trace['basis']}"
                f"(경도 {hour_trace['longitude']:g}°E · "
                f"{hour_trace['correction_minutes']:+.0f}분 보정)"
            )

        hour_detail = {
            "기준": basis_label,
            "기준 이름": hour_trace["basis"],
            "경도 출처": longitude_source,
            "standard_meridian": hour_trace["standard_meridian"],
            "longitude": hour_trace["longitude"],
            "longitude_difference": hour_trace["longitude_difference"],
            "correction_minutes": hour_trace["correction_minutes"],
            "입력 시각": birth_time.strftime("%H:%M"),
            "표준시 시각": hour_trace["standard_birth_time"],
            "corrected_birth_time": hour_trace["corrected_birth_time"],
            "판정에 쓴 시각": hour_trace["corrected_birth_time"],
            "시지 구간": f"{JIJI[hour_branch]}시 ({SIJI_RANGE[hour_branch]})",
        }

        if judged.hour == 23:
            notes.append(
                "보정한 시각이 밤 23시대라 시지를 자시로 잡았어요. "
                "이 시간을 '야자시'로 보아 일주를 다음 날로 넘기는 유파도 "
                "있지만, 이 서비스는 일주를 넘기지 않습니다. "
                "일주는 언제나 네가 적어준 출생일로 계산해요."
            )

        if hour_trace["basis"] == HOUR_BASIS_LMT:
            notes.append(
                f"시주는 출생지의 해 위치에 맞춰 잡았어요. "
                f"시계로는 {hour_trace['standard_birth_time']} 이지만, "
                f"출생지(동경 {hour_trace['longitude']:g}도)는 표준시 기준선인 "
                f"동경 135도보다 서쪽이라 실제 해의 위치는 "
                f"{hour_trace['corrected_birth_time']} 에 해당합니다. "
                "('지방평균태양시' — 만세력이 '진태양시'라고 부르는 그 보정입니다)"
            )
            # 보정 때문에 날짜가 넘어가는 경우 (자정 무렵 출생)
            #     예) 서울 00:20 출생 → 보정하면 전날 23:48
            #     기준선(135도)보다 동쪽에서 태어났으면 다음날로 넘어갑니다.
            #
            #     [이때도 일주는 '태어난 날' 그대로입니다 — 확정 정책]
            #     보정은 "해가 어디 있었나" 를 재는 것이고, "며칠에 태어났나" 를
            #     다시 정하는 것이 아닙니다. 태어난 날은 달력이 정합니다.
            #     (PILLAR_TIME_POLICY · compute_hour_pillar 참고)
            if judged.date() != solar_date:
                moved = "전날" if judged.date() < solar_date else "다음날"
                notes.append(
                    f"보정한 시각({hour_trace['corrected_birth_time']})은 "
                    f"{moved}에 걸치지만, 시지를 잡는 데만 썼어요. "
                    "년주·월주·일주는 네가 적어준 출생일 그대로 계산했단다. "
                    "(태어난 날은 달력이 정하는 것이라, 시간 보정으로 "
                    "바꾸지 않는다는 것이 이 서비스의 기준이에요)"
                )

            # 시지 경계에 아주 가까우면 옆 칸으로 넘어갈 수 있음을 알립니다.
            minutes_into = (judged.hour % 2) * 60 + judged.minute
            to_edge = min((minutes_into + 60) % 120, 120 - (minutes_into + 60) % 120)
            if to_edge <= 10:
                notes.append(
                    f"보정한 시각이 시지가 바뀌는 경계에서 {to_edge}분 안쪽이에요. "
                    "출생시간이 몇 분만 달라도 시주가 옆 칸으로 넘어갑니다. "
                    "출생시간을 정확히 아는지 한 번 더 확인해주세요."
                )
        elif hour_trace["basis"] == HOUR_BASIS_STANDARD:
            notes.append(
                "시주는 시계 시각(동경 135도 표준시) 그대로 계산했어요. "
                "출생지 경도로 20~35분을 앞당기는 만세력과는 "
                "경계 시각에서 시지가 달라질 수 있습니다."
            )

    # --- 7. 오행 분포 --------------------------------------------
    pillars = {
        "년주": year_pillar,
        "월주": month_pillar,
        "일주": day_pillar,
        "시주": hour_pillar,
    }
    breakdown = ohaeng_breakdown(pillars)
    ohaeng = _count_ohaeng(pillars)
    counted = 8 if has_time else 6

    # 세는 기준과 실제로 센 글자 수가 어긋나면 계산이 깨진 것입니다.
    # 조용히 틀린 값을 내보내느니 여기서 멈추는 편이 낫습니다.
    if len(breakdown) != counted or sum(ohaeng.values()) != counted:
        raise CalendarError(
            "오행을 세는 중 값이 어긋났어요. (개발자 확인 필요: "
            f"글자 {len(breakdown)}개 · 합계 {sum(ohaeng.values())} · 기대 {counted})"
        )

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
        # 시주를 어떤 시각 기준으로 잡았는지. 화면·프롬프트가 같은 값을 봅니다.
        "시주 기준": (hour_detail or {}).get("기준 이름"),
        # --- 오행 ---
        "오행 분포": ohaeng,
        "오행 요약": " / ".join(f"{k} {ohaeng[k]}" for k in OHAENG_ORDER),
        "오행 글자수": counted,
        "오행 기준": OHAENG_BASIS if has_time else OHAENG_BASIS_NO_HOUR,
        "오행 근거": breakdown,          # 글자 하나씩 → 어떤 오행으로 셌는지
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
        # 대운(daeun.py)이 절입까지의 거리를 재려면 '판정에 쓴 그 순간'이
        # 그대로 필요합니다. 사주와 대운이 서로 다른 시각을 보면 안 되므로
        # 여기서 계산한 값을 그대로 내보냅니다. (다시 만들지 않게)
        "기준 시각(UTC)": utc_moment,
        "기준 율리우스일": julian_day,
        "절기 계산 출처": SOLAR_TERM_SOURCE,
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
#  하나의 진실 (single source of truth)
#
#  화면·프롬프트·테스트가 서로 다른 값을 보면 안 되므로,
#  바깥에서 쓸 명식 값은 전부 이 함수 하나를 거쳐 나갑니다.
#  Gemini 가 만든 글에서 명식 값을 되읽어오는 일은 절대 없습니다.
# ===============================================================
def saju_facts(saju: dict) -> dict:
    """화면과 프롬프트가 함께 쓸 '확정 명식' 한 덩어리.

    여기 담긴 값이 이 서비스의 사주 원본입니다.
    Gemini 응답에서 명식을 다시 읽어오지 않습니다.
    """
    def pillar_text(name: str) -> str:
        pillar = saju["기둥"][name]
        if pillar is None:
            return ""
        return f"{pillar['한글']}({pillar['한자']})"

    ohaeng = saju["오행 분포"]
    day_stem = saju["일간"]

    return {
        "년주": pillar_text("년주"),
        "월주": pillar_text("월주"),
        "일주": pillar_text("일주"),
        "시주": pillar_text("시주"),
        "일간": f"{day_stem['한글']}{day_stem['오행']}({day_stem['한자']})",
        "일간 글자": day_stem["한글"],
        "일간 오행": day_stem["오행"],
        "오행 개수": {name: ohaeng[name] for name in OHAENG_ORDER},
        "오행 요약": saju["오행 요약"],
        "오행 기준": saju["오행 기준"],
        "오행 글자수": saju["오행 글자수"],
        "오행 근거": saju["오행 근거"],
        "월령": f"{saju['적용 절기']['월지']} ({saju['적용 절기']['현재 구간']} 이후)",
        "시주 계산 여부": saju["시주 계산 여부"],
        "시주 제외 사유": saju["시주 제외 사유"],
        "시주 기준": saju.get("시주 기준"),
    }


# ===============================================================
#  Gemini 에 그대로 넣을 수 있는 글 (다시 계산하지 말라는 지시 포함)
# ===============================================================
#  Gemini 가 이 값을 고쳐 쓰지 못하게 막는 문장. 여러 곳에서 쓰므로 상수로 둡니다.
SAJU_LOCK_HEADER = "[CALCULATED_SAJU — 확정 입력값]"
SAJU_LOCK_RULES = """[CALCULATED_SAJU 사용 규칙 — 어기면 답변 실패로 본다]
- 위 CALCULATED_SAJU 는 Python 에서 계산이 끝난 확정값이다.
- 다시 계산하지 말고, 추정하지 말고, 바꾸지 말고, 그대로 해석만 하라.
- 생년월일·출생시간을 보고 간지를 스스로 뽑아내려 하지 마라. 이미 다 주어졌다.
- 명식 값(년주·월주·일주·시주·일간·오행 개수)을 글에 적을 때는
  위에 적힌 글자를 그대로 옮겨 적어라. 한 글자도 바꾸지 마라.
- 위에 없는 명식 값(대운·세운·지장간·신살 등)은 만들어내지 마라.
- 오행 개수는 위에 적힌 숫자만 쓴다. 더하거나 빼서 새로 세지 마라.
- 시주(시간 천간 · 시지)는 특히 손대지 마라. 출생시간에 경도 보정이 이미
  들어간 값이라, 출생시간만 보고 다시 계산하면 반드시 틀린다.
  "몇 시니까 무슨 시" 같은 말로 시지를 새로 정하지 마라.
- 시간 보정 · 표준시 · 진태양시 · 경도 같은 계산 과정을 답변에 설명하지 마라.
  그건 Python 이 이미 끝낸 일이고, 사용자에게는 결과만 필요하다."""


def format_saju_for_prompt(saju: dict) -> str:
    """계산된 사주를 프롬프트에 붙일 수 있는 글자로 바꿉니다.

    Gemini 가 이 값을 다시 계산하지 않도록, 확정값이라는 점을 못 박아둡니다.
    """
    facts = saju_facts(saju)
    lines = [SAJU_LOCK_HEADER]

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

    lines.append(f"- 일간: {facts['일간']} — 이 사람 해석의 중심 글자")
    lines.append(f"- 월령: {facts['월령']}")

    lines.append("")
    lines.append(
        f"- 오행 개수 (세는 기준: {facts['오행 기준']} · 총 {facts['오행 글자수']}글자)"
    )
    for name in OHAENG_ORDER:
        lines.append(f"    {name}: {facts['오행 개수'][name]}")
    lines.append(f"    → 요약: {facts['오행 요약']}")

    lines.append("")
    lines.append("- 위 개수는 이렇게 세었다 (글자 하나씩)")
    lines.append(
        "    " + ", ".join(
            f"{row['글자']}→{row['오행']}" for row in facts["오행 근거"]
        )
    )

    if not facts["시주 계산 여부"]:
        lines.append("")
        lines.append(
            f"- [주의] {facts['시주 제외 사유']}. 시주를 근거로 든 해석은 하지 말 것."
        )

    lines.append("")
    lines.append(SAJU_LOCK_RULES)

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
