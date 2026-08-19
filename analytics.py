"""사용자 행동 로그 (익명) — MVP Funnel 측정용

화면(Streamlit) 코드와 분리해두어서, 나중에 저장소를 바꿀 때 이 파일만 고치면 됩니다.

    python analytics.py            # 지금까지 쌓인 로그로 Funnel 요약을 출력
    python analytics.py --raw      # 원본 이벤트를 그대로 출력

[개인정보를 저장하지 않습니다]
    이름, 생년월일, 출생시간, 출생지역, 추가 질문 원문, 성별은 절대 기록하지 않습니다.
    저장하는 값은 아래 FIELDNAMES 여섯 개뿐이고,
    그 밖의 값은 넘어와도 버려집니다(_clean_row 가 걸러냅니다).

    session_id  : 사용자를 알아볼 수 없는 무작위 UUID (브라우저 탭을 닫으면 끝)
    timestamp   : 기록 시각 (UTC, ISO 8601)
    event_name  : 어떤 일이 일어났는지
    concern     : 고민 분야 (연애 / 취업·커리어 … 같은 미리 정해진 선택지)
    model       : 그때 쓰던 Gemini 모델 이름
    step        : 그때의 단계 번호 (1 / 2 / 3)

[어디에 저장되나]
    기본은 Supabase 입니다. (public.events · public.feedback)
    환경변수 SUPABASE_URL · SUPABASE_SECRET_KEY 가 있으면 자동으로 Supabase 를 씁니다.
    없으면 개발용 로컬 파일(data/events.csv · data/feedback.csv)로 조용히 내려옵니다.

    저장소를 손으로 고르고 싶으면:
        HALMAE_STORAGE=supabase   무조건 Supabase
        HALMAE_STORAGE=local      무조건 로컬 파일 (개발용)
        HALMAE_STORAGE=auto       기본값 — 환경변수가 있으면 Supabase

    Supabase 저장이 실패하면 그 줄은 버리지 않고 로컬 파일에 대신 적어둡니다.
    동시에 db.record_failure() 로 개발 로그에 남기므로 ?dev=1 화면에서 몇 건이
    실패했는지 볼 수 있습니다. (조용히 사라지지 않게 하려는 장치입니다.)

    app.py 는 log_event() / save_feedback() 만 부르므로 화면 코드는 손대지 않습니다.
    저장소를 통째로 갈아끼우려면 set_store() · set_feedback_store() 를 쓰면 됩니다.

[Supabase 와 로컬 파일은 칸 이름이 다릅니다]
    코드 안에서 쓰는 이름      Supabase 테이블의 칸 이름
        timestamp        →    created_at        (DB 기본값을 쓰므로 보내지 않습니다)
        concern          →    concern_category
        model            →    model_name
        step             →    current_step
    이 변환은 SupabaseEventStore 안에서만 일어납니다.
    통계 함수들은 예전 이름 그대로 쓰면 됩니다.
"""

import csv
import threading
import uuid
from datetime import datetime, timezone
from pathlib import Path

import db
import perf
from config import get_secret

# 저장하는 칸은 이 여섯 개가 전부입니다. (개인정보가 섞여 들어가지 못하게 하는 울타리)
FIELDNAMES = ["session_id", "timestamp", "event_name", "concern", "model", "step"]

# 기록하는 이벤트 이름과, Funnel 화면에 보여줄 한글 이름
# 위에서 아래로 한 줄씩 좁아지는 '깔때기' 순서입니다.
FUNNEL_STEPS = [
    ("landing_view", "첫 화면 진입"),
    ("start_click", "할매 만나러 가기"),
    ("input_submit", "입력 완료"),
    ("step1_view", "Step 1 조회"),
    ("more_click", "더 듣고 싶어요"),
    ("step2_view", "Step 2 조회"),
    ("action_click", "행동 지령 클릭"),
    ("step3_view", "Step 3 조회"),
    ("premium_view", "Premium 영역 조회"),
    ("premium_click", "Premium CTA 클릭"),
]

# 구매 의향은 '예/아니오'로 갈라지는 갈림길이라 깔때기와 따로 셉니다.
INTENT_STEPS = [
    ("purchase_intent_yes", "구매 의향 Yes"),
    ("purchase_intent_no", "구매 의향 No"),
]

# 올해의 흐름(대운 × 세운)은 Step 3 다음에 붙는 다리(bridge) 구간입니다.
# Step 번호를 붙이지 않으므로 깔때기 본줄과 따로 셉니다.
YEAR_FLOW_STEPS = [
    ("year_flow_click", "올해의 흐름 보기 클릭"),
    ("year_flow_view", "올해의 흐름 조회"),
]

# 올해의 카드는 Step 3 화면에서 Premium 과 나란히 보이는 '곁가지'입니다.
# 깔때기 중간에 끼워 넣으면 Premium 전환율이 이상해져서 따로 셉니다.
#
# [이름을 바꾸지 않은 이유]
#     카드 클릭 이벤트는 처음부터 card_click 이라는 이름으로 쌓여 있습니다.
#     year_card_click 이라는 이름을 새로 만들면 같은 행동이 두 이름으로
#     갈라져, 예전 기록과 새 기록을 함께 셀 수 없게 됩니다.
#     그래서 카드 클릭은 계속 card_click 하나만 씁니다.
CARD_STEPS = [
    ("card_click", "올해의 카드 받기 클릭"),
    ("card_view", "올해의 카드 조회"),
]

# 피드백도 Step 3 화면에 함께 뜨는 곁가지라 따로 셉니다.
FEEDBACK_STEPS = [
    ("feedback_view", "피드백 영역 노출"),
    ("feedback_positive", "👍 맞아요"),
    ("feedback_negative", "👎 아니에요"),
]

EVENT_NAMES = [
    name
    for name, _ in (
        FUNNEL_STEPS + INTENT_STEPS + YEAR_FLOW_STEPS
        + CARD_STEPS + FEEDBACK_STEPS
    )
]

DEFAULT_FEEDBACK_PATH = Path(__file__).parent / "data" / "feedback.csv"

# 피드백 파일에 저장하는 칸 (개인정보가 섞이지 못하게 하는 울타리)
FEEDBACK_FIELDNAMES = [
    "session_id", "timestamp", "feedback_result", "concern", "model",
]

DEFAULT_CSV_PATH = Path(__file__).parent / "data" / "events.csv"

# 개발자 Funnel 화면(?dev=...)을 여는 열쇠로 인정하지 않는 값들.
# 이 정도 값은 누구나 한 번에 맞히므로 잠근 것이 아닙니다.
WEAK_DEV_KEYS = frozenset({
    "1", "0", "dev", "test", "true", "false", "yes", "no",
    "admin", "halmae", "password", "secret",
})

# 열쇠는 이 길이 이상이어야 인정합니다.
MIN_DEV_KEY_LENGTH = 8


# ===============================================================
#  1. 익명 사용자 ID
# ===============================================================
def new_session_id() -> str:
    """사용자를 알아볼 수 없는 무작위 ID를 하나 만듭니다.

    무작위로 만든 값이라 이 값만으로는 누구인지 알 수 없습니다.
    같은 브라우저 탭에서는 st.session_state 에 담아두고 계속 같은 값을 씁니다.
    """
    return uuid.uuid4().hex


# ===============================================================
#  2. 저장소 (나중에 갈아끼울 수 있게 얇게 감쌌습니다)
# ===============================================================
class EventStore:
    """이벤트를 어디에 쌓을지 정하는 껍데기.

    나중에 DB를 붙일 때는 이 클래스를 상속해서 두 함수만 새로 만들면 됩니다.
    """

    def append(self, row: dict) -> None:
        raise NotImplementedError

    def read_all(self) -> list[dict]:
        raise NotImplementedError


class CsvEventStore(EventStore):
    """개발 테스트용 — data/events.csv 파일에 한 줄씩 덧붙입니다."""

    def __init__(self, path: Path | str = DEFAULT_CSV_PATH):
        self.path = Path(path)
        # 여러 사용자가 동시에 써도 줄이 섞이지 않도록 잠금장치를 둡니다.
        self._lock = threading.Lock()

    def append(self, row: dict) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with self._lock:
            is_new = not self.path.exists() or self.path.stat().st_size == 0
            with self.path.open("a", newline="", encoding="utf-8") as file:
                writer = csv.DictWriter(file, fieldnames=FIELDNAMES)
                if is_new:
                    writer.writeheader()      # 파일을 처음 만들 때만 제목 줄
                writer.writerow(row)

    def read_all(self) -> list[dict]:
        if not self.path.exists():
            return []
        with self._lock:
            with self.path.open(newline="", encoding="utf-8") as file:
                return list(csv.DictReader(file))


class MemoryEventStore(EventStore):
    """테스트용 — 파일을 만들지 않고 메모리에만 담아둡니다."""

    def __init__(self):
        self.rows: list[dict] = []

    def append(self, row: dict) -> None:
        self.rows.append(row)

    def read_all(self) -> list[dict]:
        return list(self.rows)


# 한 번에 읽어오는 줄 수. Supabase 는 한 번에 1000줄까지만 주기 때문에
# 그보다 많으면 나눠서 여러 번 읽어옵니다.
PAGE_SIZE = 1000


class SupabaseEventStore(EventStore):
    """실사용 — Supabase public.events 테이블에 한 줄씩 넣습니다.

    created_at 은 보내지 않습니다. Supabase 쪽 기본값(now())이 채워줍니다.
    저장에 실패하면 그 줄을 버리지 않고 fallback(로컬 CSV)에 대신 적어둡니다.
    """

    def __init__(self, fallback: EventStore | None = None):
        self.fallback = fallback

    # --- 칸 이름 바꾸기 ------------------------------------------
    @staticmethod
    def _to_supabase(row: dict) -> dict:
        """코드에서 쓰는 이름 → 테이블의 칸 이름."""
        step = row.get("step")
        return {
            "session_id": row.get("session_id") or "",
            "event_name": row.get("event_name") or "",
            "concern_category": row.get("concern") or None,
            "model_name": row.get("model") or None,
            # 빈 칸은 0 이 아니라 '없음'으로 넣습니다.
            "current_step": int(step) if str(step or "").strip() else None,
        }

    @staticmethod
    def _from_supabase(row: dict) -> dict:
        """테이블의 칸 이름 → 코드에서 쓰는 이름."""
        step = row.get("current_step")
        return {
            "session_id": row.get("session_id") or "",
            "timestamp": row.get("created_at") or "",
            "event_name": row.get("event_name") or "",
            "concern": row.get("concern_category") or "",
            "model": row.get("model_name") or "",
            "step": "" if step is None else str(step),
        }

    # --- 쓰기 / 읽기 ---------------------------------------------
    def append(self, row: dict) -> None:
        client = db.get_client()
        if client is None:
            self._to_fallback(row)
            return
        try:
            # 이벤트 한 줄을 넣는 동안 화면이 멈춰 있으므로, 얼마나 걸리는지
            # 개발 로그에 남깁니다. (개인정보는 원래부터 이 줄에 없습니다)
            with perf.stage("supabase_write"):
                client.table(db.EVENTS_TABLE).insert(
                    self._to_supabase(row)
                ).execute()
        except Exception as exc:
            db.record_failure("events insert", exc, row.get("event_name", ""))
            self._to_fallback(row)

    def read_all(self) -> list[dict]:
        client = db.get_client()
        if client is None:
            return self.fallback.read_all() if self.fallback else []
        try:
            rows: list[dict] = []
            start = 0
            with perf.stage("supabase_read"):
                while True:                    # 1000줄씩 끝까지 읽어옵니다
                    page = (
                        client.table(db.EVENTS_TABLE)
                        .select("*")
                        .order("created_at")
                        .range(start, start + PAGE_SIZE - 1)
                        .execute()
                    ).data or []
                    rows.extend(page)
                    if len(page) < PAGE_SIZE:
                        break
                    start += PAGE_SIZE
            return [self._from_supabase(r) for r in rows]
        except Exception as exc:
            db.record_failure("events select", exc)
            return self.fallback.read_all() if self.fallback else []

    def _to_fallback(self, row: dict) -> None:
        """Supabase 에 못 넣은 줄을 로컬 파일에 적어둡니다. (데이터 유실 방지)"""
        if self.fallback is None:
            return
        try:
            self.fallback.append(row)
        except Exception:
            pass                               # 로그 때문에 앱이 멈추면 안 됩니다


# ===============================================================
#  2-2. 어떤 저장소를 쓸지 정하기
# ===============================================================
# 어떤 저장소를 쓸지는 db.py 가 정합니다 (HALMAE_STORAGE).
# 이벤트·피드백·카드가 서로 다른 곳에 저장되면 안 되니 판단을 한 곳에 모아둡니다.
storage_mode = db.storage_mode
use_supabase = db.use_supabase


def storage_label() -> str:
    """개발자 화면에 보여줄 '지금 어디에 저장 중인지' 한 줄."""
    if not use_supabase():
        return f"로컬 파일 · {DEFAULT_CSV_PATH}"
    if db.is_available():
        return f"Supabase · {db.get_url()}"
    return f"Supabase 연결 실패 → 로컬 파일 대체 · {DEFAULT_CSV_PATH}"


def _default_event_store() -> EventStore:
    if use_supabase():
        return SupabaseEventStore(fallback=CsvEventStore())
    return CsvEventStore()


_store: EventStore = _default_event_store()


def set_store(store: EventStore) -> None:
    """저장소를 갈아끼웁니다. (나중에 DB로 옮길 때 여기만 부르면 됩니다.)"""
    global _store
    _store = store


def get_store() -> EventStore:
    return _store


# ===============================================================
#  3. 이벤트 기록
# ===============================================================
def _clean_row(
    session_id: str,
    event_name: str,
    concern: str | None,
    model: str | None,
    step: int | None,
) -> dict:
    """저장할 값만 골라 한 줄을 만듭니다.

    FIELDNAMES 에 없는 값은 아예 만들지 않기 때문에,
    실수로 이름이나 생년월일을 넘겨도 파일에 들어갈 수 없습니다.
    """
    return {
        "session_id": str(session_id or ""),
        "timestamp": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "event_name": str(event_name or ""),
        "concern": str(concern or ""),
        "model": str(model or ""),
        "step": "" if step is None else str(step),
    }


def log_event(
    session_id: str,
    event_name: str,
    concern: str | None = None,
    model: str | None = None,
    step: int | None = None,
) -> None:
    """이벤트 한 줄을 남깁니다.

    로그를 남기다 문제가 생겨도 앱이 멈추면 안 되므로, 오류는 조용히 삼킵니다.
    (로그는 있으면 좋은 것이지, 서비스가 돌아가는 데 꼭 필요한 것이 아닙니다.)
    """
    try:
        _store.append(_clean_row(session_id, event_name, concern, model, step))
    except Exception as exc:
        # 저장소 안에서 이미 한 번 걸러지지만, 혹시 모를 오류까지 여기서 막습니다.
        # 조용히 넘기지 않고 개발 로그에는 반드시 남깁니다.
        db.record_failure("log_event", exc, event_name)


def should_log(logged_events: set, event_name: str) -> bool:
    """이 이벤트를 지금 기록해야 하는지 알려줍니다.

    Streamlit 은 버튼을 누르거나 화면이 바뀔 때마다 코드를 처음부터 다시 실행합니다.
    그래서 아무 장치 없이 두면 같은 이벤트가 몇 번이고 다시 쌓입니다.

    한 세션에서 같은 이벤트는 딱 한 번만 기록합니다.
    Funnel 은 "몇 명이 여기까지 왔는가"를 보는 것이라 한 번이면 충분합니다.

    기록해야 하면 True 를 돌려주면서 logged_events 에 표시까지 해둡니다.

    [화면에 보인 것 vs 사용자가 한 것]
        app.py 는 이 함수를 view 계열에만 씁니다 (app.track).
            landing_view · step1~3_view · card_view · feedback_view · premium_view
        사용자가 손으로 누른 행동은 app.track_action 이 매번 남깁니다.
            start_click · input_submit · more_click · action_click · card_click ·
            premium_click · purchase_intent_* · feedback_*
        버튼을 누른 자리에서만 불리므로 rerun 으로는 쌓이지 않고,
        마음을 바꿔 다시 누른 '진짜 행동'은 그대로 남습니다.

    아래 요약 함수들(funnel_summary · premium_summary · card_summary ·
    feedback_summary)은 모두 '세션 수'로 세기 때문에, 같은 세션이 같은 행동을
    두 번 남겨도 전환율이 부풀지 않습니다.
    """
    if event_name in logged_events:
        return False
    logged_events.add(event_name)
    return True


# ===============================================================
#  3-2. 피드백 저장 (한 세션에 한 줄만 — 마음이 바뀌면 덮어씁니다)
# ===============================================================
class FeedbackStore:
    """피드백을 어디에 보관할지 정하는 껍데기.

    이벤트 로그(events.csv)와 저장 방식이 다릅니다.
        이벤트  : 일어난 일을 계속 덧붙이는 '일지'
        피드백  : 이 사람의 '최종 답' 하나. 마음이 바뀌면 새 줄을 쌓지 않고 고쳐 씁니다.
    """

    def upsert(self, row: dict) -> None:
        raise NotImplementedError

    def read_all(self) -> list[dict]:
        raise NotImplementedError


class CsvFeedbackStore(FeedbackStore):
    """개발용 — data/feedback.csv. session_id 당 딱 한 줄만 남습니다."""

    def __init__(self, path: Path | str = DEFAULT_FEEDBACK_PATH):
        self.path = Path(path)
        self._lock = threading.Lock()

    def _read_rows(self) -> list[dict]:
        if not self.path.exists():
            return []
        with self.path.open(newline="", encoding="utf-8") as file:
            return list(csv.DictReader(file))

    def upsert(self, row: dict) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with self._lock:
            rows = self._read_rows()
            # 같은 사람의 옛 답은 빼고, 새 답을 뒤에 붙입니다. → 늘 한 줄만 남습니다.
            rows = [r for r in rows if r.get("session_id") != row["session_id"]]
            rows.append(row)

            temporary = self.path.with_suffix(".csv.tmp")
            with temporary.open("w", newline="", encoding="utf-8") as file:
                writer = csv.DictWriter(file, fieldnames=FEEDBACK_FIELDNAMES)
                writer.writeheader()
                writer.writerows(rows)
            # 쓰다가 멈춰도 원본이 깨지지 않도록 다 쓴 뒤에 갈아끼웁니다.
            temporary.replace(self.path)

    def read_all(self) -> list[dict]:
        if not self.path.exists():
            return []
        with self._lock:
            return self._read_rows()


class MemoryFeedbackStore(FeedbackStore):
    """테스트용 — 파일을 만들지 않고 메모리에만."""

    def __init__(self):
        self.rows: dict[str, dict] = {}

    def upsert(self, row: dict) -> None:
        self.rows[row["session_id"]] = row

    def read_all(self) -> list[dict]:
        return list(self.rows.values())


class SupabaseFeedbackStore(FeedbackStore):
    """실사용 — Supabase public.feedback. session_id 당 딱 한 줄만 남습니다.

    👍 를 눌렀다가 👎 로 바꾸면 새 줄을 쌓지 않고 그 사람의 줄을 고쳐 씁니다.
    session_id 에 unique 제약이 걸려 있어서, 같은 값이 들어오면
    Postgres 가 '새로 넣기' 대신 '고쳐 쓰기'를 하도록 upsert 로 보냅니다.
    (혹시 upsert 가 막히면 select → update / insert 로 한 번 더 시도합니다.)
    """

    def __init__(self, fallback: FeedbackStore | None = None):
        self.fallback = fallback

    @staticmethod
    def _to_supabase(row: dict) -> dict:
        return {
            "session_id": row.get("session_id") or "",
            "feedback_result": row.get("feedback_result") or "",
            "concern_category": row.get("concern") or None,
            "model_name": row.get("model") or None,
            # 마음을 바꾼 시각. created_at(처음 남긴 시각)은 그대로 둡니다.
            "updated_at": row.get("timestamp") or db.now_iso(),
        }

    @staticmethod
    def _from_supabase(row: dict) -> dict:
        return {
            "session_id": row.get("session_id") or "",
            "timestamp": row.get("updated_at") or row.get("created_at") or "",
            "feedback_result": row.get("feedback_result") or "",
            "concern": row.get("concern_category") or "",
            "model": row.get("model_name") or "",
        }

    def upsert(self, row: dict) -> None:
        client = db.get_client()
        if client is None:
            self._to_fallback(row)
            return

        payload = self._to_supabase(row)
        table = db.FEEDBACK_TABLE
        try:
            client.table(table).upsert(payload, on_conflict="session_id").execute()
            return
        except Exception as exc:
            db.record_failure("feedback upsert", exc, payload["session_id"])

        # upsert 가 실패했을 때의 대비책 — 있는지 먼저 보고 고치거나 새로 넣습니다.
        try:
            found = (
                client.table(table)
                .select("id")
                .eq("session_id", payload["session_id"])
                .limit(1)
                .execute()
            ).data
            if found:
                client.table(table).update(payload).eq(
                    "session_id", payload["session_id"]
                ).execute()
            else:
                client.table(table).insert(payload).execute()
        except Exception as exc:
            db.record_failure("feedback update/insert", exc, payload["session_id"])
            self._to_fallback(row)

    def read_all(self) -> list[dict]:
        client = db.get_client()
        if client is None:
            return self.fallback.read_all() if self.fallback else []
        try:
            rows: list[dict] = []
            start = 0
            while True:
                page = (
                    client.table(db.FEEDBACK_TABLE)
                    .select("*")
                    .range(start, start + PAGE_SIZE - 1)
                    .execute()
                ).data or []
                rows.extend(page)
                if len(page) < PAGE_SIZE:
                    break
                start += PAGE_SIZE
            return [self._from_supabase(r) for r in rows]
        except Exception as exc:
            db.record_failure("feedback select", exc)
            return self.fallback.read_all() if self.fallback else []

    def _to_fallback(self, row: dict) -> None:
        if self.fallback is None:
            return
        try:
            self.fallback.upsert(row)
        except Exception:
            pass


def _default_feedback_store() -> FeedbackStore:
    if use_supabase():
        return SupabaseFeedbackStore(fallback=CsvFeedbackStore())
    return CsvFeedbackStore()


_feedback_store: FeedbackStore = _default_feedback_store()


def set_feedback_store(store: FeedbackStore) -> None:
    """저장소를 갈아끼웁니다. (나중에 DB로 옮길 때 여기만 부르면 됩니다.)"""
    global _feedback_store
    _feedback_store = store


def get_feedback_store() -> FeedbackStore:
    return _feedback_store


def save_feedback(
    session_id: str,
    feedback_result: str,
    concern: str | None = None,
    model: str | None = None,
) -> None:
    """이 세션의 최종 피드백을 저장합니다.

    feedback_result 는 "positive" 또는 "negative".
    같은 세션이 다시 부르면 새 줄을 쌓지 않고 기존 줄을 고쳐 씁니다.
    """
    if feedback_result not in ("positive", "negative"):
        return
    row = {
        "session_id": str(session_id or ""),
        "timestamp": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "feedback_result": feedback_result,
        "concern": str(concern or ""),
        "model": str(model or ""),
    }
    try:
        _feedback_store.upsert(row)
    except Exception as exc:
        # 로그 때문에 앱이 멈추면 안 되지만, 조용히 사라지게 두지도 않습니다.
        db.record_failure("save_feedback", exc, feedback_result)


# ===============================================================
#  4. Funnel 요약
# ===============================================================
def snapshot_store(store: EventStore | None = None) -> MemoryEventStore:
    """지금 쌓인 이벤트를 '한 번만' 읽어와 메모리에 담아 돌려줍니다.

    아래 요약 함수들(funnel · card · feedback · premium)은 저마다 read_all() 을
    부릅니다. 로컬 파일일 때는 괜찮았지만 Supabase 는 그때마다 인터넷을 다녀오므로
    개발자 화면 한 번에 네 번 다녀오게 됩니다.

    그래서 화면에서는 이 함수로 한 번만 읽어두고, 그 사본을 네 함수에 넘겨줍니다.
        snapshot = analytics.snapshot_store()
        analytics.funnel_summary(snapshot)
        analytics.card_summary(snapshot)
    """
    snapshot = MemoryEventStore()
    try:
        snapshot.rows = (store or _store).read_all()
    except Exception as exc:
        db.record_failure("snapshot", exc)
    return snapshot


def funnel_summary(store: EventStore | None = None) -> dict:
    """쌓인 로그를 단계별로 세어 Funnel 표를 만듭니다.

    같은 사람이 같은 이벤트를 여러 번 남겼더라도
    '세션 수' 로 세기 때문에 사람 수 기준으로 계산됩니다.
    """
    rows = (store or _store).read_all()

    sessions_by_event: dict[str, set] = {name: set() for name in EVENT_NAMES}
    all_sessions: set = set()

    for row in rows:
        session_id = (row.get("session_id") or "").strip()
        event_name = (row.get("event_name") or "").strip()
        if not session_id:
            continue
        all_sessions.add(session_id)
        if event_name in sessions_by_event:
            sessions_by_event[event_name].add(session_id)

    total = len(all_sessions)
    steps = []
    previous_count = None

    for event_name, label in FUNNEL_STEPS:
        count = len(sessions_by_event[event_name])
        steps.append(
            {
                "event": event_name,
                "label": label,
                "세션 수": count,
                # 바로 앞 단계에서 몇 %가 넘어왔는지
                "직전 대비": (
                    None if previous_count in (None, 0)
                    else round(count / previous_count * 100, 1)
                ),
                # 첫 화면 진입 기준으로 몇 %가 남았는지
                "전체 대비": (
                    None if total == 0 else round(count / total * 100, 1)
                ),
            }
        )
        previous_count = count

    return {
        "총 세션": total,
        "총 이벤트": len(rows),
        "단계": steps,
    }


def _rate(numerator: int, denominator: int) -> float | None:
    """비율(%)을 냅니다. 분모가 0이면 계산하지 않고 None."""
    if not denominator:
        return None
    return round(numerator / denominator * 100, 1)


def premium_summary(store: EventStore | None = None) -> dict:
    """Premium Fake-door 테스트 지표만 따로 모아 봅니다.

    실제 결제는 일어나지 않습니다. "얼마면 낼 의향이 있는가"를
    사용자의 클릭으로만 재는 것이 목적입니다.
    """
    rows = (store or _store).read_all()

    wanted = [
        "step3_view", "premium_view", "premium_click",
        "purchase_intent_yes", "purchase_intent_no",
    ]
    sessions: dict[str, set] = {name: set() for name in wanted}

    for row in rows:
        session_id = (row.get("session_id") or "").strip()
        event_name = (row.get("event_name") or "").strip()
        if session_id and event_name in sessions:
            sessions[event_name].add(session_id)

    counts = {name: len(sessions[name]) for name in wanted}
    answered = counts["purchase_intent_yes"] + counts["purchase_intent_no"]

    return {
        "지표": [
            ("Step 3 조회자", counts["step3_view"]),
            ("Premium 영역 조회자", counts["premium_view"]),
            ("Premium CTA 클릭자", counts["premium_click"]),
            ("구매 의향 Yes", counts["purchase_intent_yes"]),
            ("구매 의향 No", counts["purchase_intent_no"]),
        ],
        "counts": counts,
        # Premium 을 본 사람 중 몇 %가 눌렀나
        "CTA 클릭률": _rate(counts["premium_click"], counts["premium_view"]),
        # CTA 를 누른 사람 중 몇 %가 "이용해보고 싶다"고 했나
        "구매 의향률": _rate(counts["purchase_intent_yes"], counts["premium_click"]),
        # 참고용 — CTA 를 누른 사람 중 몇 %가 답을 남겼나
        "의향 응답률": _rate(answered, counts["premium_click"]),
        # 참고용 — Step 3 까지 온 사람 중 몇 %가 Premium 을 봤나
        "Premium 도달률": _rate(counts["premium_view"], counts["step3_view"]),
    }


def card_summary(store: EventStore | None = None) -> dict:
    """올해의 카드 지표.

    Step 3 까지 온 사람 중 몇 %가 카드를 받아봤는지를 봅니다.
    (카드는 Premium 과 같은 화면에 나란히 있어서 깔때기와는 따로 셉니다.)
    """
    rows = (store or _store).read_all()

    wanted = ["step3_view", "card_click", "card_view"]
    sessions: dict[str, set] = {name: set() for name in wanted}
    for row in rows:
        session_id = (row.get("session_id") or "").strip()
        event_name = (row.get("event_name") or "").strip()
        if session_id and event_name in sessions:
            sessions[event_name].add(session_id)

    counts = {name: len(sessions[name]) for name in wanted}
    return {
        "counts": counts,
        # Step 3 까지 온 사람 중 몇 %가 카드 버튼을 눌렀나
        "카드 클릭률": _rate(counts["card_click"], counts["step3_view"]),
        # 누른 사람 중 몇 %가 카드를 실제로 봤나 (실패하면 낮아집니다)
        "카드 완료율": _rate(counts["card_view"], counts["card_click"]),
    }


def format_card_text(summary: dict | None = None) -> str:
    """올해의 카드 지표를 터미널용 글로."""
    summary = summary or card_summary()
    counts = summary["counts"]
    lines = [
        f"{'Step 3 조회자':<22} {counts['step3_view']:>4}",
        f"{'카드 받기 클릭':<22} {counts['card_click']:>4}",
        f"{'카드 조회 완료':<22} {counts['card_view']:>4}",
        "",
    ]
    for label in ("카드 클릭률", "카드 완료율"):
        value = summary[label]
        lines.append(
            f"{label:<22} {'계산 불가 (아직 표본 없음)' if value is None else f'{value:>5.1f}%'}"
        )
    return "\n".join(lines)


def year_flow_summary(store: EventStore | None = None) -> dict:
    """올해의 흐름(대운 × 세운) 지표.

    Step 3 → 올해의 흐름 → 올해의 카드 로 이어지는 다리 구간이 실제로
    건너지고 있는지 봅니다. 깔때기 본줄(funnel_summary)은 건드리지 않습니다.
    """
    rows = (store or _store).read_all()

    wanted = ["step3_view", "year_flow_click", "year_flow_view", "card_click"]
    sessions: dict[str, set] = {name: set() for name in wanted}
    for row in rows:
        session_id = (row.get("session_id") or "").strip()
        event_name = (row.get("event_name") or "").strip()
        if session_id and event_name in sessions:
            sessions[event_name].add(session_id)

    counts = {name: len(sessions[name]) for name in wanted}
    return {
        "counts": counts,
        # Step 3 까지 온 사람 중 몇 %가 흐름 버튼을 눌렀나
        "흐름 클릭률": _rate(counts["year_flow_click"], counts["step3_view"]),
        # 누른 사람 중 몇 %가 실제로 흐름을 봤나 (실패하면 낮아집니다)
        "흐름 완료율": _rate(counts["year_flow_view"], counts["year_flow_click"]),
        # 흐름을 본 사람 중 몇 %가 카드로 넘어갔나
        "카드로 이어진 비율": _rate(counts["card_click"], counts["year_flow_view"]),
    }


def format_year_flow_text(summary: dict | None = None) -> str:
    """올해의 흐름 지표를 터미널용 글로."""
    summary = summary or year_flow_summary()
    counts = summary["counts"]
    lines = [
        f"{'Step 3 조회자':<22} {counts['step3_view']:>4}",
        f"{'올해의 흐름 클릭':<22} {counts['year_flow_click']:>4}",
        f"{'올해의 흐름 조회':<22} {counts['year_flow_view']:>4}",
        f"{'이어서 카드 클릭':<22} {counts['card_click']:>4}",
        "",
    ]
    for label in ("흐름 클릭률", "흐름 완료율", "카드로 이어진 비율"):
        value = summary[label]
        lines.append(
            f"{label:<22} "
            f"{'계산 불가 (아직 표본 없음)' if value is None else f'{value:>5.1f}%'}"
        )
    return "\n".join(lines)


def feedback_summary(
    store: EventStore | None = None,
    feedback_store: FeedbackStore | None = None,
) -> dict:
    """피드백 통계.

    👍/👎 개수는 '이벤트 일지'가 아니라 '최종 답 파일'에서 셉니다.
    그래야 마음을 바꾼 사람이 양쪽에 두 번 세어지지 않습니다.
    """
    rows = (store or _store).read_all()
    answers = (feedback_store or _feedback_store).read_all()

    # 이벤트에서 '누가 어디까지 봤는지'를 모읍니다.
    wanted = ["card_view", "feedback_view", "premium_view", "premium_click"]
    sessions: dict[str, set] = {name: set() for name in wanted}
    for row in rows:
        session_id = (row.get("session_id") or "").strip()
        event_name = (row.get("event_name") or "").strip()
        if session_id and event_name in sessions:
            sessions[event_name].add(session_id)

    positive = {
        r["session_id"] for r in answers
        if r.get("feedback_result") == "positive"
    }
    negative = {
        r["session_id"] for r in answers
        if r.get("feedback_result") == "negative"
    }
    answered = positive | negative
    total = len(answered)

    return {
        "전체 피드백": total,
        "긍정": len(positive),
        "부정": len(negative),
        "긍정 비율": _rate(len(positive), total),
        "부정 비율": _rate(len(negative), total),
        "노출": len(sessions["feedback_view"]),
        # 피드백 영역을 본 사람 중 몇 %가 눌렀나
        "응답률": _rate(total, len(sessions["feedback_view"])),
        # 카드까지 본 사람 중 몇 %가 피드백을 남겼나
        "카드 조회자 중 응답률": _rate(total, len(sessions["card_view"])),
        # 👍 를 준 사람 중 몇 %가 Premium CTA 를 눌렀나
        "긍정→CTA 클릭률": _rate(
            len(positive & sessions["premium_click"]), len(positive)
        ),
        # 👎 를 준 사람 중 몇 %가 Premium CTA 를 눌렀나
        "부정→CTA 클릭률": _rate(
            len(negative & sessions["premium_click"]), len(negative)
        ),
    }


def format_feedback_text(summary: dict | None = None) -> str:
    """피드백 통계를 터미널에서 보기 좋은 글자로."""
    summary = summary or feedback_summary()

    def pct(value):
        return "계산 불가 (아직 표본 없음)" if value is None else f"{value:>5.1f}%"

    lines = [
        f"{'전체 피드백':<24} {summary['전체 피드백']:>4}",
        f"{'👍 맞아요':<24} {summary['긍정']:>4}   ({pct(summary['긍정 비율']).strip()})",
        f"{'👎 아니에요':<24} {summary['부정']:>4}   ({pct(summary['부정 비율']).strip()})",
        "",
        f"{'피드백 영역 노출':<24} {summary['노출']:>4}",
        f"{'응답률(노출 대비)':<24} {pct(summary['응답률'])}",
        f"{'카드 조회자 중 응답률':<24} {pct(summary['카드 조회자 중 응답률'])}",
        "",
        f"{'긍정 → Premium CTA':<24} {pct(summary['긍정→CTA 클릭률'])}",
        f"{'부정 → Premium CTA':<24} {pct(summary['부정→CTA 클릭률'])}",
    ]
    return "\n".join(lines)


def format_premium_text(summary: dict | None = None) -> str:
    """Premium 지표를 터미널에서 보기 좋은 글자로 바꿉니다."""
    summary = summary or premium_summary()
    lines = []
    for label, count in summary["지표"]:
        lines.append(f"{label:<22} {count:>4}")
    lines.append("")
    for label in ("CTA 클릭률", "구매 의향률", "의향 응답률", "Premium 도달률"):
        value = summary[label]
        lines.append(
            f"{label:<22} {'계산 불가 (아직 표본 없음)' if value is None else f'{value:>5.1f}%'}"
        )
    return "\n".join(lines)


def format_funnel_text(summary: dict | None = None) -> str:
    """Funnel 요약을 터미널에서 보기 좋은 글자로 바꿉니다."""
    summary = summary or funnel_summary()
    lines = [
        f"총 세션: {summary['총 세션']}   (기록된 이벤트 {summary['총 이벤트']}건)",
        "",
    ]
    for step in summary["단계"]:
        parts = [f"{step['label']:<18} {step['세션 수']:>4}"]
        if step["직전 대비"] is not None:
            parts.append(f"직전 대비 {step['직전 대비']:>5.1f}%")
        if step["전체 대비"] is not None:
            parts.append(f"전체 대비 {step['전체 대비']:>5.1f}%")
        lines.append("  ".join(parts))
    return "\n".join(lines)


# ===============================================================
#  5. 개발용 Funnel 화면을 열어도 되는지
# ===============================================================
def dev_dashboard_allowed(query_value: str | None) -> bool:
    """주소창에 ?dev=... 를 붙였을 때 분석 화면을 보여줘도 되는지 판단합니다.

    [잠긴 문이 기본입니다]
        HALMAE_DEV_KEY 를 정해두지 않으면 어떤 주소로도 열리지 않습니다.
        예전에는 열쇠가 없을 때 ?dev=1 만으로도 열렸는데, 그러면 배포된 앱에서
        주소만 아는 사람이 저장소 상태(Supabase 주소·연결 오류)와
        원본 이벤트(session_id 목록)를 그대로 볼 수 있었습니다.
        실사용자에게 공유하는 앱이라 '깜빡 잊으면 열리는' 쪽이 아니라
        '깜빡 잊으면 닫히는' 쪽으로 뒤집었습니다.

    열쇠를 정해두면 그 값과 똑같아야만 열립니다.
        내 컴퓨터    export HALMAE_DEV_KEY="아무거나정한암호"
        Cloud       Settings → Secrets 에  HALMAE_DEV_KEY = "아무거나정한암호"
        → https://.../?dev=아무거나정한암호

    너무 쉬운 값(1 · dev · true 같은 것)은 사실상 잠그지 않은 것과 같아서
    열쇠로 인정하지 않습니다.
    """
    if not query_value:
        return False
    expected = get_secret("HALMAE_DEV_KEY", "").strip()
    if not expected:
        # 열쇠가 없으면 열지 않습니다. (배포 기본값)
        return False
    if expected.lower() in WEAK_DEV_KEYS or len(expected) < MIN_DEV_KEY_LENGTH:
        return False
    return query_value == expected


# ---------------------------------------------------------------
#  터미널에서 Funnel 확인하기
#      python analytics.py
#      python analytics.py --raw
# ---------------------------------------------------------------
if __name__ == "__main__":
    import sys

    if "--raw" in sys.argv:
        for event_row in get_store().read_all():
            print(event_row)
    else:
        print(f"[할매 Funnel]  저장소: {storage_label()}")
        if db.failure_count():
            print(f"  ⚠ Supabase 저장 실패 {db.failure_count()}건 "
                  f"(마지막: {db.failures()[-1]['error']})")
        print()
        print(format_funnel_text())
        print()
        print("[올해의 흐름 · 대운 × 세운]")
        print()
        print(format_year_flow_text())
        print()
        print("[올해의 카드]")
        print()
        print(format_card_text())
        print()
        print("[사용자 피드백]")
        print()
        print(format_feedback_text())
        print()
        print("[Premium Fake-door]  ※ 실제 결제는 일어나지 않습니다")
        print()
        print(format_premium_text())
