"""Supabase 연결 테스트 — 실제로 저장이 되는지 세 가지를 확인합니다.

    python test_supabase.py            # 테스트하고, 만든 테스트 데이터는 지웁니다
    python test_supabase.py --keep     # 지우지 않고 남겨둡니다 (Dashboard 에서 눈으로 확인용)
    python test_supabase.py --cleanup  # 테스트는 하지 않고, 남아 있는 test_ 데이터만 지웁니다

확인하는 것
    1) events    테스트 이벤트 1건 넣기
    2) feedback  테스트 피드백을 넣고 👍 → 👎 로 바꿔보기 (줄이 늘지 않아야 합니다)
    3) cards     테스트 카드를 저장하고 stable_key 로 다시 꺼내오기

테스트로 만든 줄은 모두 session_id / stable_key 가 "test_" 로 시작합니다.
실사용 데이터와 섞이지 않게 하려는 표시이고, 끝나면 이 접두사로 찾아서 지웁니다.
"""

import json
import sys

import analytics
import card_store
import db

# 테스트로 만드는 줄에 붙이는 표시. 이걸로 찾아서 지웁니다.
TEST_PREFIX = "test_"
TEST_SESSION = "test_supabase_connection"
TEST_CARD_KEY = "test_supabase_connection_card"
TEST_YEAR = 2026

PASS = "✅ 통과"
FAIL = "❌ 실패"


def _line(title: str) -> None:
    print()
    print(f"── {title} " + "─" * max(0, 50 - len(title)))


# ===============================================================
#  1. events
# ===============================================================
def test_events(client) -> bool:
    _line("1. events · 테스트 이벤트 1건 넣기")

    store = analytics.SupabaseEventStore()
    row = analytics._clean_row(
        session_id=TEST_SESSION,
        event_name="landing_view",
        concern="연애",
        model="test",
        step=1,
    )
    store.append(row)

    found = (
        client.table(db.EVENTS_TABLE)
        .select("*")
        .eq("session_id", TEST_SESSION)
        .execute()
    ).data

    if not found:
        print(f"{FAIL} — 넣은 줄을 다시 찾지 못했습니다.")
        return False

    saved = found[0]
    print(f"  넣은 줄: {saved}")

    checks = {
        "event_name": saved.get("event_name") == "landing_view",
        "concern_category": saved.get("concern_category") == "연애",
        "model_name": saved.get("model_name") == "test",
        "current_step": str(saved.get("current_step")) == "1",
        "created_at 자동 입력": bool(saved.get("created_at")),
    }
    for name, ok in checks.items():
        print(f"    {'✓' if ok else '✗'} {name}")

    ok = all(checks.values())
    print(f"{PASS if ok else FAIL} — events insert")
    return ok


# ===============================================================
#  2. feedback
# ===============================================================
def test_feedback(client) -> bool:
    _line("2. feedback · 넣은 뒤 👍 → 👎 로 바꾸기")

    store = analytics.SupabaseFeedbackStore()

    def upsert(result: str) -> None:
        store.upsert(
            {
                "session_id": TEST_SESSION,
                "timestamp": db.now_iso(),
                "feedback_result": result,
                "concern": "연애",
                "model": "test",
            }
        )

    def read() -> list[dict]:
        return (
            client.table(db.FEEDBACK_TABLE)
            .select("*")
            .eq("session_id", TEST_SESSION)
            .execute()
        ).data or []

    # --- 처음 넣기 (👍) -----------------------------------------
    upsert("positive")
    rows = read()
    if len(rows) != 1 or rows[0].get("feedback_result") != "positive":
        print(f"{FAIL} — 처음 넣기가 안 됐습니다: {rows}")
        return False
    first_id = rows[0].get("id")
    first_created = rows[0].get("created_at")
    print(f"  넣기   id={first_id}  결과={rows[0]['feedback_result']}")

    # --- 마음 바꾸기 (👎) ---------------------------------------
    upsert("negative")
    rows = read()
    print(f"  바꾸기 줄 개수={len(rows)}  결과={rows[0].get('feedback_result') if rows else '-'}")

    checks = {
        "줄이 늘지 않음 (1줄 유지)": len(rows) == 1,
        "결과가 negative 로 바뀜": bool(rows) and rows[0].get("feedback_result") == "negative",
        "같은 줄을 고쳐 씀 (id 동일)": bool(rows) and rows[0].get("id") == first_id,
        "created_at 은 그대로": bool(rows) and rows[0].get("created_at") == first_created,
        "updated_at 이 채워짐": bool(rows) and bool(rows[0].get("updated_at")),
    }
    for name, ok in checks.items():
        print(f"    {'✓' if ok else '✗'} {name}")

    ok = all(checks.values())
    print(f"{PASS if ok else FAIL} — feedback insert → update")
    return ok


# ===============================================================
#  3. cards
# ===============================================================
def test_cards(client) -> bool:
    _line("3. cards · 저장한 뒤 stable_key 로 다시 꺼내기")

    store = card_store.SupabaseCardStore()
    card = {
        "year": TEST_YEAR,
        "title": "테스트 카드",
        "keyword": "연결 확인",
        "message": "이 줄은 테스트용이라 곧 지워집니다.",
        "reason": "Supabase 연결을 확인하려고 만든 카드입니다.",
        "actions": ["첫째", "둘째", "셋째"],
    }

    store.put(TEST_CARD_KEY, card, TEST_YEAR, "test")
    loaded = store.get(TEST_CARD_KEY)

    print(f"  꺼낸 카드: {json.dumps(loaded, ensure_ascii=False)[:80]}…"
          if loaded else "  꺼낸 카드: (없음)")

    rows = (
        client.table(db.CARDS_TABLE)
        .select("*")
        .eq("stable_key", TEST_CARD_KEY)
        .execute()
    ).data or []

    checks = {
        "stable_key 로 다시 찾아짐": loaded is not None,
        "내용이 그대로": loaded == card,
        "card_year 저장됨": bool(rows) and rows[0].get("card_year") == TEST_YEAR,
        "줄이 하나만 (unique)": len(rows) == 1,
    }

    # 같은 열쇠로 한 번 더 저장해도 줄이 늘지 않아야 합니다.
    store.put(TEST_CARD_KEY, card, TEST_YEAR, "test")
    again = (
        client.table(db.CARDS_TABLE)
        .select("id")
        .eq("stable_key", TEST_CARD_KEY)
        .execute()
    ).data or []
    checks["같은 열쇠로 또 저장해도 1줄"] = len(again) == 1

    for name, ok in checks.items():
        print(f"    {'✓' if ok else '✗'} {name}")

    ok = all(checks.values())
    print(f"{PASS if ok else FAIL} — cards insert → select")
    return ok


# ===============================================================
#  4. 테스트 데이터 지우기
# ===============================================================
def cleanup(client) -> None:
    _line("테스트 데이터 지우기 (test_ 로 시작하는 줄만)")

    targets = [
        (db.EVENTS_TABLE, "session_id"),
        (db.FEEDBACK_TABLE, "session_id"),
        (db.CARDS_TABLE, "stable_key"),
    ]
    for table, column in targets:
        try:
            # like 'test_%' 의 _ 는 '아무 글자 하나'라는 뜻이라 그대로 쓰면 위험합니다.
            # 그래서 앞 네 글자 'test' 로 찾고, 파이썬에서 한 번 더 확인합니다.
            rows = (
                client.table(table)
                .select(f"id,{column}")
                .like(column, "test%")
                .execute()
            ).data or []
            ids = [
                r["id"] for r in rows
                if str(r.get(column, "")).startswith(TEST_PREFIX)
            ]
            if not ids:
                print(f"  {table:<10} 지울 것 없음")
                continue
            client.table(table).delete().in_("id", ids).execute()
            print(f"  {table:<10} {len(ids)}건 지웠습니다")
        except Exception as error:
            print(f"  {table:<10} 지우기 실패 · {type(error).__name__}: {error}")

    # 남은 게 없는지 확인
    print()
    for table, column in targets:
        try:
            left = (
                client.table(table)
                .select("id", count="exact")
                .like(column, "test%")
                .execute()
            )
            total = (
                client.table(table).select("id", count="exact").execute()
            )
            print(f"  {table:<10} test_ 남은 것 {left.count}건 · 전체 {total.count}건")
        except Exception as error:
            print(f"  {table:<10} 확인 실패 · {error}")


# ===============================================================
#  실행
# ===============================================================
def main() -> int:
    client = db.get_client()
    if client is None:
        print(f"Supabase 에 연결하지 못했습니다 — {db.last_error()}")
        print("환경변수 SUPABASE_URL · SUPABASE_SECRET_KEY 를 확인하세요.")
        return 1

    print("[Supabase 연결 테스트]")
    print(f"  URL        {db.get_url()}")
    print(f"  SECRET_KEY {db.mask_key(db.get_secret_key())}")

    if "--cleanup" in sys.argv:
        cleanup(client)
        return 0

    results = {
        "1. events insert": test_events(client),
        "2. feedback insert → update": test_feedback(client),
        "3. cards insert → select": test_cards(client),
    }

    if "--keep" in sys.argv:
        print()
        print("--keep 이라 테스트 데이터를 남겨둡니다. "
              "나중에 `python test_supabase.py --cleanup` 으로 지우세요.")
    else:
        cleanup(client)

    _line("결과")
    for name, ok in results.items():
        print(f"  {PASS if ok else FAIL}  {name}")

    if db.failure_count():
        print()
        print(f"⚠ 저장 실패로 기록된 것 {db.failure_count()}건:")
        for failure in db.failures():
            print(f"   {failure['where']} · {failure['error']}")

    return 0 if all(results.values()) else 1


if __name__ == "__main__":
    raise SystemExit(main())
