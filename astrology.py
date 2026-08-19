"""출생정보 → 서양 점성술 기초 데이터 (태양궁 / 달궁 / 상승궁)

이 파일은 화면(Streamlit)과 상관없이 혼자서도 돌아가는 계산 전용 모듈입니다.
터미널에서 바로 값을 확인해볼 수 있습니다.

    python astrology.py 1999-04-13 08:49 서울
    python astrology.py 1999-04-13 모름 부산
    python astrology.py 1990-05-20 14:30 "New York"

계산 순서
    출생지역 텍스트
      → (geopy · Nominatim)      위도 / 경도
      → (timezonefinder)         그 지역의 시간대 이름   예) Asia/Seoul
      → (zoneinfo)               현지 시각 → UTC
      → (pyswisseph)             태양 황경 · 달 황경 · Ascendant
      → 황경 30도씩 끊어서        Sun / Moon / Rising Sign

쓰는 패키지
    geopy           지역 이름 → 좌표 (인터넷 연결 필요)
    timezonefinder  좌표 → 시간대 이름 (오프라인)
    pyswisseph      천체 위치 (Moshier 내장 이론을 써서 별도 자료 파일이 필요 없습니다)
"""

import logging
import threading
from datetime import date, datetime, time, timezone
from functools import lru_cache
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

import swisseph as swe
from geopy.exc import GeocoderServiceError, GeocoderTimedOut, GeocoderUnavailable
from geopy.geocoders import Nominatim
from timezonefinder import TimezoneFinder

import perf

from saju import compute_calendar_info

# 개발 로그 — 사용자에게는 짧은 안내만 보여주고, 진짜 원인은 여기 남깁니다.
# 출생지역 원문·좌표는 적지 않습니다. (개인정보)
logger = logging.getLogger("halmae.astrology")

# Nominatim 이용 정책상 어떤 프로그램이 요청하는지 밝혀야 합니다.
USER_AGENT = "halmae-mvp"

# 별도 성력(星曆) 파일 없이 pyswisseph 안에 들어있는 이론으로 계산합니다.
# 1800~2100년 구간에서 오차는 각도 1초 이내라 별자리 판정에는 충분합니다.
EPHEMERIS_FLAG = swe.FLG_MOSEPH

# 조건에 적힌 안내 문구 (화면에도 이 문장 그대로 나갑니다)
PLACE_NOT_FOUND_MESSAGE = (
    "출생지역을 찾지 못했어요. '서울', '부산', 'New York'처럼 다시 입력해주세요."
)
NO_BIRTH_TIME_NOTE = "출생시간을 몰라 상승궁은 계산하지 않았습니다."

# 출생시간을 모를 때 태양·달 위치를 잡아볼 기준 시각 (현지 정오)
DEFAULT_TIME_WHEN_UNKNOWN = time(12, 0)

# 황경 0도부터 30도씩 끊은 12별자리
ZODIAC_SIGNS = [
    ("Aries", "양자리"),
    ("Taurus", "황소자리"),
    ("Gemini", "쌍둥이자리"),
    ("Cancer", "게자리"),
    ("Leo", "사자자리"),
    ("Virgo", "처녀자리"),
    ("Libra", "천칭자리"),
    ("Scorpio", "전갈자리"),
    ("Sagittarius", "궁수자리"),
    ("Capricorn", "염소자리"),
    ("Aquarius", "물병자리"),
    ("Pisces", "물고기자리"),
]


class AstrologyError(Exception):
    """사용자에게 그대로 보여줘도 되는, 이해하기 쉬운 오류 메시지."""


# ===============================================================
#  1. 출생지역 → 위도 / 경도
# ===============================================================
@lru_cache(maxsize=256)
def geocode_place(place: str) -> dict:
    """'서울' 같은 지역 이름을 위도·경도로 바꿉니다.

    Nominatim 은 무료 공개 서비스라 초당 1회 정도로 부드럽게 써야 합니다.
    그래서 같은 지역을 다시 물으면 인터넷에 나가지 않도록 결과를 기억해둡니다.

    못 찾으면 AstrologyError 를 냅니다. (임의의 좌표를 대신 쓰지 않습니다.)
    """
    query = (place or "").strip()
    if not query:
        raise AstrologyError(PLACE_NOT_FOUND_MESSAGE)

    geolocator = Nominatim(user_agent=USER_AGENT, timeout=10)
    try:
        # 인터넷에 한 번 다녀오는 구간이라 여기가 느려질 때가 많습니다.
        # 얼마나 걸렸는지 개발 로그에 남깁니다. (검색어는 남기지 않습니다)
        with perf.stage("geocoding"):
            location = geolocator.geocode(query, language="ko")
    except (GeocoderTimedOut, GeocoderUnavailable, GeocoderServiceError) as exc:
        raise AstrologyError(
            "출생지역을 찾는 중 인터넷 연결에 문제가 생겼어요. "
            "잠시 뒤에 다시 시도해주세요.\n" + PLACE_NOT_FOUND_MESSAGE
        ) from exc
    except Exception as exc:
        raise AstrologyError(PLACE_NOT_FOUND_MESSAGE) from exc

    if location is None:
        raise AstrologyError(PLACE_NOT_FOUND_MESSAGE)

    return {
        "검색어": query,
        "찾은 지역": location.address,
        "위도": float(location.latitude),
        "경도": float(location.longitude),
    }


# ===============================================================
#  2. 위도 / 경도 → 시간대
# ===============================================================
_TZ_LOCK = threading.Lock()

# 미리 읽기를 이미 시작했는지. (warm_up_async 가 서버당 한 번만 돌게 합니다)
_TZ_START_LOCK = threading.Lock()
_warm_started = False


@lru_cache(maxsize=1)
def _timezone_finder() -> TimezoneFinder:
    """TimezoneFinder 는 만드는 데 시간이 걸려서 한 번만 만들어 재사용합니다.

    처음 만들 때 자료 파일을 읽느라 0.7초쯤 걸립니다. warm_up() 이 미리
    불러둘 수 있으니, 두 갈래(thread)에서 동시에 들어와도 하나만 만들도록
    자물쇠로 감싸둡니다. (lru_cache 만으로는 동시에 둘이 만들 수 있습니다)
    """
    with _TZ_LOCK:
        return TimezoneFinder()


def warm_up() -> None:
    """무거운 자료를 미리 읽어둡니다. 실패해도 조용히 넘어갑니다.

    [왜 필요한가]
        TimezoneFinder 를 처음 만드는 0.7초는 '첫 사용자의 첫 계산' 에
        그대로 붙습니다. 사용자가 입력칸을 채우는 동안 미리 만들어두면
        그 0.7초가 첫 답변 대기시간에서 사라집니다.

    [안전한 이유]
        하는 일은 로컬 자료 파일을 읽는 것뿐입니다. 인터넷에 나가지 않고,
        st.session_state 를 보지 않고, 계산 결과를 바꾸지 않습니다.
        그래서 딴 갈래(thread)에서 불러도 됩니다.
    """
    try:
        _timezone_finder()
    except Exception:
        # 미리 읽기가 실패해도 나중에 실제 계산할 때 다시 시도합니다.
        logger.debug("시간대 자료 미리 읽기 실패", exc_info=True)


def warm_up_async() -> None:
    """warm_up() 을 딴 갈래(thread)에서 시작하고 바로 돌아옵니다.

    화면을 그리는 쪽이 이 줄에서 멈추면 안 되므로 join() 하지 않습니다.
    daemon 갈래라 서버를 끄는 것도 막지 않습니다.

    [서버당 딱 한 번만 돕니다]
        "이미 시작했는지" 표시를 이 모듈이 들고 있습니다.
        app.py 는 화면을 다시 그릴 때마다 처음부터 다시 실행되지만,
        import 된 모듈(sys.modules)은 그대로 살아 있어서 표시가 남습니다.
    """
    global _warm_started
    with _TZ_START_LOCK:
        if _warm_started:
            return
        _warm_started = True
    try:
        threading.Thread(
            target=warm_up, name="halmae-warmup", daemon=True,
        ).start()
    except Exception:
        # 갈래를 못 만드는 환경이면 미리 읽기를 그냥 포기합니다.
        logger.debug("미리 읽기 갈래를 만들지 못했습니다", exc_info=True)


def find_timezone(latitude: float, longitude: float) -> str:
    """좌표가 속한 시간대 이름. 예) 37.5665, 126.978 → 'Asia/Seoul'"""
    # TimezoneFinder 를 처음 만들 때 자료를 읽느라 몇 초가 걸릴 수 있습니다.
    # (두 번째부터는 lru_cache 덕분에 바로 나옵니다)
    with perf.stage("timezone"):
        name = _timezone_finder().timezone_at(lat=latitude, lng=longitude)
    if not name:
        raise AstrologyError(
            "출생지역의 시간대를 알아내지 못했어요. "
            "'서울'처럼 도시 이름으로 다시 입력해주세요."
        )
    return name


# ===============================================================
#  3. 현지 시각 → UTC
# ===============================================================
def to_utc(local_date: date, local_time: time, timezone_name: str) -> datetime:
    """출생지 현지 시각을 UTC 로 바꿉니다.

    zoneinfo 가 그 지역의 과거 표준시와 서머타임까지 알고 있어서,
    예전에 서머타임을 쓰던 해에 태어났어도 알아서 맞춰줍니다.
    """
    try:
        local_zone = ZoneInfo(timezone_name)
    except ZoneInfoNotFoundError as exc:
        # 사용자에게는 무엇을 하면 되는지만 알려주고,
        # 진짜 원인(서버에 tzdata 가 없음)은 개발 로그에 남깁니다.
        logger.error(
            "시간대 자료를 찾지 못했습니다 (%s) — 서버에 tzdata 를 설치해야 합니다.",
            timezone_name,
        )
        raise AstrologyError(
            "별자리를 계산하는 데 필요한 시간대 자료를 불러오지 못했어요. "
            "잠시 뒤에 다시 시도해주세요."
        ) from exc

    local_moment = datetime.combine(local_date, local_time, tzinfo=local_zone)
    return local_moment.astimezone(timezone.utc)


# ===============================================================
#  4. 황경 → 별자리
# ===============================================================
def sign_from_longitude(longitude: float) -> dict:
    """황경(0~360도)을 30도씩 끊어 별자리 이름으로 바꿉니다.

    0~30 Aries · 30~60 Taurus · 60~90 Gemini · … · 330~360 Pisces
    """
    normalized = longitude % 360.0
    index = int(normalized // 30)
    english, korean = ZODIAC_SIGNS[index]
    degree_in_sign = normalized - index * 30

    return {
        "sign": english,
        "이름": korean,
        "황경": round(normalized, 4),
        "별자리 내 각도": round(degree_in_sign, 4),
        "표기": f"{english}({korean}) {degree_in_sign:.2f}°",
        # 별자리가 바뀌는 경계까지 얼마나 남았는지 (경고를 띄울 때 씁니다)
        "경계까지": round(min(degree_in_sign, 30 - degree_in_sign), 4),
    }


# ===============================================================
#  5. 천체 위치 계산
# ===============================================================
def _julian_day(utc_moment: datetime) -> float:
    """UTC 시각을 pyswisseph 가 쓰는 율리우스일(UT)로."""
    hours = (
        utc_moment.hour
        + utc_moment.minute / 60
        + utc_moment.second / 3600
        + utc_moment.microsecond / 3_600_000_000
    )
    return swe.julday(utc_moment.year, utc_moment.month, utc_moment.day, hours)


def _body_longitude(julian_day: float, body: int) -> float:
    """태양(swe.SUN) 또는 달(swe.MOON)의 황경."""
    position, _flag = swe.calc_ut(julian_day, body, EPHEMERIS_FLAG)
    return position[0] % 360.0


def _ascendant(julian_day: float, latitude: float, longitude: float) -> float:
    """Ascendant(상승점) 황경. 그 순간 동쪽 지평선에 떠오르던 지점입니다."""
    try:
        _cusps, ascmc = swe.houses_ex(
            julian_day, latitude, longitude, b"P"   # Placidus
        )
    except Exception:
        # 위도가 아주 높은 곳에서는 Placidus 가 실패할 수 있어 등분법으로 바꿉니다.
        # (Ascendant 값 자체는 하우스 방식과 상관없이 같습니다.)
        _cusps, ascmc = swe.houses_ex(
            julian_day, latitude, longitude, b"A"   # Equal house
        )
    return ascmc[0] % 360.0


# ===============================================================
#  바깥에서 부르는 함수
# ===============================================================
def compute_astrology(
    birth_date: date,
    birth_time: time | None,
    birth_place: str,
    calendar_type: str = "양력",
    leap_month: str | None = None,
) -> dict:
    """출생정보 하나로 태양궁·달궁·상승궁을 계산합니다.

    birth_date    : 입력한 날짜 (양력이면 양력, 음력이면 음력)
    birth_time    : 출생시간. None 이면 상승궁을 계산하지 않습니다.
    birth_place   : 출생지역 텍스트. 예) "서울", "부산", "New York"
    calendar_type : "양력" 또는 "음력"
    leap_month    : 음력일 때 "평달" / "윤달"

    계산이 안 되면 AstrologyError 를 냅니다.
    """
    if birth_date is None:
        raise AstrologyError("생년월일이 없어서 계산할 수 없어요.")

    # --- 0. 음력으로 입력했으면 먼저 양력으로 바꿉니다 -------------
    #     (사주 모듈이 쓰는 변환기를 그대로 씁니다. 두 기능의 날짜가 어긋나지 않게.)
    calendar_info = compute_calendar_info(birth_date, calendar_type, leap_month)
    solar_date: date = calendar_info["양력 날짜"]

    notes: list[str] = []
    has_time = birth_time is not None

    # --- 1. 지역 → 좌표 ------------------------------------------
    place = geocode_place(birth_place)
    latitude = place["위도"]
    longitude = place["경도"]

    # --- 2. 좌표 → 시간대 ----------------------------------------
    timezone_name = find_timezone(latitude, longitude)

    # --- 3. 현지 시각 → UTC --------------------------------------
    reference_time = birth_time if has_time else DEFAULT_TIME_WHEN_UNKNOWN
    utc_moment = to_utc(solar_date, reference_time, timezone_name)
    local_moment = utc_moment.astimezone(ZoneInfo(timezone_name))

    if not has_time:
        notes.append(
            "출생시간을 몰라 현지 정오(12:00)를 기준으로 태양궁·달궁을 계산했어요."
        )

    utc_offset = local_moment.utcoffset()
    dst_offset = local_moment.dst()
    if dst_offset:
        hours = int(dst_offset.total_seconds() // 3600)
        notes.append(
            f"출생일에 그 지역은 서머타임(+{hours}시간)을 쓰고 있었어요. "
            "시간대 자료가 자동으로 반영했습니다."
        )

    # --- 4. 천체 위치 --------------------------------------------
    julian_day = _julian_day(utc_moment)
    sun = sign_from_longitude(_body_longitude(julian_day, swe.SUN))
    moon = sign_from_longitude(_body_longitude(julian_day, swe.MOON))

    rising = None
    rising_note = None
    if has_time:
        rising = sign_from_longitude(_ascendant(julian_day, latitude, longitude))
    else:
        rising_note = NO_BIRTH_TIME_NOTE

    # --- 5. 값이 경계에 가까우면 알려줍니다 ------------------------
    #     태양은 하루에 약 1도, 달은 약 13도씩 움직입니다.
    if sun["경계까지"] < 0.5:
        notes.append(
            f"태양이 별자리 경계에서 {sun['경계까지']:.2f}도밖에 떨어져 있지 않아요. "
            "출생 날짜가 하루만 달라도 태양궁이 바뀔 수 있습니다."
        )
    if has_time:
        if moon["경계까지"] < 1:
            notes.append(
                f"달이 별자리 경계에서 {moon['경계까지']:.2f}도밖에 떨어져 있지 않아요. "
                "출생시간이 두 시간만 달라도 달궁이 바뀔 수 있습니다."
            )
        if rising and rising["경계까지"] < 1:
            notes.append(
                f"상승점이 별자리 경계에서 {rising['경계까지']:.2f}도밖에 "
                "떨어져 있지 않아요. 출생시간이 몇 분만 달라도 상승궁이 바뀔 수 있습니다."
            )
    else:
        # 정오를 기준으로 잡았으니 달은 ±6.6도쯤 흔들릴 수 있습니다.
        if moon["경계까지"] < 7:
            notes.append(
                "출생시간을 모르는 상태에서 달이 별자리 경계 근처에 있어요. "
                f"실제 출생시간에 따라 달궁이 {moon['sign']} 가 아닐 수 있습니다."
            )

    return {
        # --- 조건 7에 적힌 기본 형태 ---
        "sun_sign": sun["sign"],
        "moon_sign": moon["sign"],
        "rising_sign": rising["sign"] if rising else None,
        "latitude": round(latitude, 6),
        "longitude": round(longitude, 6),
        "timezone": timezone_name,
        # --- 화면에 보여줄 자세한 값 ---
        "상승궁 계산 여부": has_time,
        "상승궁 제외 사유": rising_note,
        "태양": sun,
        "달": moon,
        "상승점": rising,
        "출생지역 입력": place["검색어"],
        "찾은 지역": place["찾은 지역"],
        "현지 시각": local_moment.strftime("%Y-%m-%d %H:%M %Z"),
        "UTC 시각": utc_moment.strftime("%Y-%m-%d %H:%M UTC"),
        "UTC 차이": f"{utc_offset.total_seconds() / 3600:+g}시간" if utc_offset else "+0시간",
        "율리우스일": round(julian_day, 6),
        "양력 날짜 표기": calendar_info["양력 날짜 표기"],
        "출생시간": birth_time.strftime("%H:%M") if has_time else None,
        "주의사항": notes,
    }


# ===============================================================
#  Gemini 에 그대로 넣을 수 있는 글
# ===============================================================
def format_astrology_for_prompt(astro: dict) -> str:
    """계산된 점성술 데이터를 프롬프트에 붙일 수 있는 글자로 바꿉니다.

    Gemini 가 이 값을 다시 계산하지 않도록, 확정값이라는 점을 못 박아둡니다.
    """
    lines = [
        "[점성술 데이터 — Python에서 계산 완료. 다시 계산하지 말고 그대로 사용할 것]",
        f"- 출생지: {astro['출생지역 입력']} "
        f"(위도 {astro['latitude']}, 경도 {astro['longitude']}, {astro['timezone']})",
        f"- 출생 시각: {astro['현지 시각']} = {astro['UTC 시각']}",
        f"- Sun Sign(태양궁): {astro['sun_sign']} / {astro['태양']['이름']} "
        f"({astro['태양']['별자리 내 각도']:.1f}도)",
        f"- Moon Sign(달궁): {astro['moon_sign']} / {astro['달']['이름']} "
        f"({astro['달']['별자리 내 각도']:.1f}도)",
    ]

    if astro["상승점"]:
        lines.append(
            f"- Rising Sign(상승궁): {astro['rising_sign']} / {astro['상승점']['이름']} "
            f"({astro['상승점']['별자리 내 각도']:.1f}도)"
        )
    else:
        lines.append(f"- Rising Sign(상승궁): 없음 — {astro['상승궁 제외 사유']}")
        lines.append("  → 상승궁을 근거로 든 해석은 하지 말 것.")

    return "\n".join(lines)


# ---------------------------------------------------------------
#  터미널에서 바로 확인해보기
#      python astrology.py 1999-04-13 08:49 서울
#      python astrology.py 1999-04-13 모름 부산
# ---------------------------------------------------------------
if __name__ == "__main__":
    import sys

    argv = sys.argv[1:]
    raw_date = argv[0] if argv else "1999-04-13"
    raw_time = argv[1] if len(argv) > 1 else "08:49"
    place_name = argv[2] if len(argv) > 2 else "서울"
    kind = argv[3] if len(argv) > 3 else "양력"
    leap = argv[4] if len(argv) > 4 else None

    parsed_time = None
    if raw_time not in ("모름", "-", "none", "None"):
        parsed_time = time.fromisoformat(raw_time)

    try:
        result = compute_astrology(
            date.fromisoformat(raw_date), parsed_time, place_name, kind, leap
        )
    except AstrologyError as error:
        print(f"[안내] {error}")
        sys.exit(1)

    print("[점성술 데이터 테스트]")
    print()
    print(f"출생지역   : {result['출생지역 입력']}  →  {result['찾은 지역']}")
    print(f"위도       : {result['latitude']}")
    print(f"경도       : {result['longitude']}")
    print(f"시간대     : {result['timezone']} ({result['UTC 차이']})")
    print(f"Sun Sign   : {result['sun_sign']}")
    print(f"Moon Sign  : {result['moon_sign']}")
    print(f"Rising Sign: {result['rising_sign'] or '(제외) ' + result['상승궁 제외 사유']}")
    print()
    print(f"현지 시각  : {result['현지 시각']}")
    print(f"UTC 시각   : {result['UTC 시각']}")
    print(f"태양 황경  : {result['태양']['황경']}°   ({result['태양']['표기']})")
    print(f"달 황경    : {result['달']['황경']}°   ({result['달']['표기']})")
    if result["상승점"]:
        print(f"상승점 황경: {result['상승점']['황경']}°   ({result['상승점']['표기']})")
    for note in result["주의사항"]:
        print(f"! {note}")
