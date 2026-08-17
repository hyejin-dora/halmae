"""Supabase 연결 — 이 파일 하나만 DB 접속을 담당합니다.

다른 파일(analytics.py · card_store.py)은 여기서 만든 연결을 빌려 쓰기만 합니다.
그래서 "DB 주소나 열쇠를 어디서 읽는가"를 바꿀 일이 생기면 이 파일만 보면 됩니다.

    python db.py        # 지금 연결이 되는지 확인 (테이블 3개를 세어봅니다)

[열쇠는 코드에 적지 않습니다]
    설정값 두 개를 config.get_secret() 으로 읽습니다.

        SUPABASE_URL          프로젝트 주소   (https://xxxx.supabase.co)
        SUPABASE_SECRET_KEY   서버용 비밀 열쇠 (service_role)

    내 컴퓨터·Codespaces 에서는 환경변수로:
        export SUPABASE_URL="https://xxxx.supabase.co"
        export SUPABASE_SECRET_KEY="sb_secret_..."

    Streamlit Community Cloud 에서는 Settings → Secrets 에 같은 이름으로:
        SUPABASE_URL = "https://xxxx.supabase.co"
        SUPABASE_SECRET_KEY = "sb_secret_..."

    코드는 둘 다 알아서 읽으므로 배포용/개발용을 따로 만들 필요가 없습니다.

    SUPABASE_PUBLISHABLE_KEY(=anon key)는 브라우저에 노출되어도 되는 열쇠입니다.
    이 앱은 '서버에서' 저장하므로 그 열쇠는 쓰지 않습니다.
    비밀 열쇠는 절대 화면에 찍지 않습니다 (아래 mask_key 참고).

[연결이 안 돼도 앱은 멈추지 않습니다]
    get_client() 는 실패하면 예외를 던지지 않고 None 을 돌려줍니다.
    대신 실패한 이유를 개발 로그에 남기고 record_failure() 로 세어둡니다.
    개발자 화면(?dev=1)에서 그 기록을 볼 수 있습니다.
"""

import logging
import threading
from datetime import datetime, timezone

# 열쇠와 설정값은 config.get_secret() 한 곳으로만 읽습니다.
#   1순위 os.environ (내 컴퓨터·Codespaces) → 2순위 st.secrets (Streamlit Cloud)
from config import get_secret

logger = logging.getLogger("halmae.db")

# 환경변수 이름 (여기 적힌 이름만 읽습니다)
URL_ENV = "SUPABASE_URL"
SECRET_KEY_ENV = "SUPABASE_SECRET_KEY"

# 테이블 이름
EVENTS_TABLE = "events"
FEEDBACK_TABLE = "feedback"
CARDS_TABLE = "cards"

# 연결은 한 번만 만들어 두고 계속 씁니다. (Streamlit 은 화면을 다시 그릴 때마다
# 코드를 처음부터 실행하므로, 매번 새로 연결하면 느려집니다.)
_client = None
_client_ready = False          # 한 번이라도 만들어보려고 시도했는지
_client_error: str | None = None
_lock = threading.Lock()

# 저장에 실패한 기록 (개발자 화면에서 확인용). 메모리에만 두고 앱을 끄면 사라집니다.
_failures: list[dict] = []
MAX_FAILURES = 50


# ===============================================================
#  1. 설정값 읽기
# ===============================================================
def get_url() -> str:
    return get_secret(URL_ENV)


def get_secret_key() -> str:
    return get_secret(SECRET_KEY_ENV)


def is_configured() -> bool:
    """환경변수 두 개가 모두 있으면 True. (연결이 된다는 뜻은 아닙니다.)"""
    return bool(get_url() and get_secret_key())


def storage_mode() -> str:
    """HALMAE_STORAGE 설정. supabase / local / auto(기본값)."""
    return get_secret("HALMAE_STORAGE", "auto").strip().lower()


def use_supabase() -> bool:
    """지금 Supabase 를 저장소로 써야 하는지.

    analytics.py(이벤트·피드백)와 card_store.py(올해의 카드)가
    같은 판단을 쓰도록 이 함수 하나로 모아두었습니다.

        HALMAE_STORAGE=local      → 무조건 로컬 파일 (개발용)
        HALMAE_STORAGE=supabase   → 무조건 Supabase
        (없음 / auto)             → 환경변수가 있으면 Supabase
    """
    mode = storage_mode()
    if mode == "local":
        return False
    if mode == "supabase":
        return True
    return is_configured()


def mask_key(value: str) -> str:
    """열쇠를 화면에 보여줘야 할 때 가운데를 가립니다. 앞뒤 4글자만 남깁니다."""
    if not value:
        return "(없음)"
    if len(value) <= 12:
        return "*" * len(value)
    return f"{value[:4]}…{value[-4:]} ({len(value)}자)"


# ===============================================================
#  2. 연결 만들기
# ===============================================================
def get_client():
    """Supabase 연결을 돌려줍니다. 못 만들면 None (예외를 던지지 않습니다).

    None 이 나오는 경우는 두 가지입니다.
        · 환경변수가 없다          → 로컬 파일 저장으로 자동으로 넘어갑니다
        · 연결을 만들다 실패했다   → 이유가 last_error() 에 남습니다
    """
    global _client, _client_ready, _client_error

    if _client_ready:
        return _client

    with _lock:
        if _client_ready:                      # 다른 실행이 먼저 만들었으면 그걸 씁니다
            return _client
        _client_ready = True

        url, key = get_url(), get_secret_key()
        if not url or not key:
            missing = [
                name for name, value in ((URL_ENV, url), (SECRET_KEY_ENV, key))
                if not value
            ]
            _client_error = f"환경변수가 없습니다: {', '.join(missing)}"
            logger.warning("[Supabase] %s — 로컬 파일에 저장합니다.", _client_error)
            return None

        try:
            from supabase import create_client

            _client = create_client(url, key)
            logger.info("[Supabase] 연결 준비 완료 (%s)", url)
        except Exception as exc:               # 패키지 없음 · 주소 오류 등
            _client = None
            _client_error = f"{type(exc).__name__}: {exc}"
            logger.error("[Supabase] 연결을 만들지 못했습니다 — %s", _client_error)

        return _client


def reset_client() -> None:
    """연결을 버리고 다음 호출 때 새로 만들게 합니다. (테스트·환경변수 변경용)"""
    global _client, _client_ready, _client_error
    with _lock:
        _client = None
        _client_ready = False
        _client_error = None


def is_available() -> bool:
    """지금 Supabase 에 저장할 수 있는 상태인지."""
    return get_client() is not None


def last_error() -> str | None:
    """마지막 연결 오류 메시지. 문제가 없었으면 None."""
    get_client()
    return _client_error


# ===============================================================
#  3. 실패 기록 (조용히 사라지지 않게)
# ===============================================================
def record_failure(where: str, exc: Exception, detail: str = "") -> None:
    """Supabase 저장이 실패했을 때 개발 로그에 남기고 개수를 세어둡니다.

    사용자 화면은 그대로 흘러가지만, 개발자는 ?dev=1 화면에서
    "몇 건이 Supabase 에 못 들어갔는지"를 바로 볼 수 있습니다.
    """
    message = f"{type(exc).__name__}: {exc}"
    logger.error("[Supabase] %s 실패 — %s %s", where, message, detail)
    _failures.append(
        {
            "when": datetime.now(timezone.utc).isoformat(timespec="seconds"),
            "where": where,
            "error": message,
            "detail": detail,
        }
    )
    if len(_failures) > MAX_FAILURES:          # 너무 많이 쌓이지 않게 앞에서 버립니다
        del _failures[:-MAX_FAILURES]


def failures() -> list[dict]:
    return list(_failures)


def failure_count() -> int:
    return len(_failures)


def clear_failures() -> None:
    _failures.clear()


def status() -> dict:
    """개발자 화면에 보여줄 연결 상태 한 묶음."""
    return {
        "설정됨": is_configured(),
        "연결됨": is_available(),
        "URL": get_url() or "(없음)",
        "SECRET_KEY": mask_key(get_secret_key()),
        "오류": last_error(),
        "저장 실패 건수": failure_count(),
    }


# ===============================================================
#  4. 시간 도우미
# ===============================================================
def now_iso() -> str:
    """UTC 현재 시각 (Postgres timestamptz 가 그대로 알아듣는 모양)."""
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


# ---------------------------------------------------------------
#  터미널에서 연결 확인하기
#      python db.py
# ---------------------------------------------------------------
if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")

    print("[Supabase 연결 확인]")
    for label, value in status().items():
        print(f"  {label:<14} {value}")
    print()

    client = get_client()
    if client is None:
        print("연결이 없습니다. 위 '오류' 줄을 확인하세요.")
        raise SystemExit(1)

    for table in (EVENTS_TABLE, FEEDBACK_TABLE, CARDS_TABLE):
        try:
            result = (
                client.table(table)
                .select("id", count="exact")
                .limit(1)
                .execute()
            )
            print(f"  {table:<10} OK · 현재 {result.count}건")
        except Exception as error:
            print(f"  {table:<10} 실패 · {type(error).__name__}: {error}")
