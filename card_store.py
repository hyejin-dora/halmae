"""올해의 카드 저장소 — 같은 입력이면 언제나 같은 카드

카드는 "올해 너는 이런 사람이다"라고 못 박아주는 결과물입니다.
새로고침할 때마다 다른 카드가 나오면 믿음이 가지 않으니,
같은 사람이 같은 해에 물으면 늘 같은 카드가 나오도록 저장해둡니다.

    python card_store.py                       # 지금까지 만들어진 카드 목록
    python card_store.py --delete <열쇠앞자리>   # 그 카드 한 장만 지우기
    python card_store.py --clear               # 로컬 파일만 비우기 (개발용)
    python card_store.py --sql                 # Supabase 에서 지우는 SQL 보기

[어떻게 같은 카드가 나오게 하나]
    1) 카드를 결정하는 값들을 한 줄로 이어 붙입니다.
       양력 생년월일 · 출생시간 · 위도 · 경도 · 성별
       · 년주 · 월주 · 일주 · 시주 · Sun/Moon/Rising · 연도
    2) 그 줄을 SHA-256 으로 요약해 열쇠(key)를 만듭니다.
    3) 그 열쇠로 이미 만들어둔 카드가 있으면 Gemini 를 부르지 않고 꺼내 씁니다.

    출생지역은 '글자'가 아니라 '좌표'로 넣습니다.
    "서울"과 "서울특별시"를 다른 사람으로 보면 안 되기 때문입니다.
    좌표는 소수점 3자리(약 100m)로 끊어, 지오코딩 결과가 미세하게 달라져도
    같은 열쇠가 나오도록 했습니다.

    고민 분야와 추가 질문은 열쇠에 넣지 않습니다.
    올해의 카드는 "무엇을 물었는가"와 상관없이
    '그 사람의 그 해를 대표하는 한 장'이기 때문입니다.

    파이썬 기본 hash() 를 쓰지 않는 이유:
    hash() 는 프로그램을 껐다 켤 때마다 결과가 달라집니다.
    그래서 앱을 재시작하면 같은 사람인데도 열쇠가 달라져 카드가 새로 만들어집니다.
    hashlib.sha256 은 언제 어디서 돌려도 같은 값이 나옵니다.

[저장 파일에 개인정보를 넣지 않습니다]
    파일에는 열쇠(사람을 되돌려 알아낼 수 없는 요약값)와 카드 내용만 들어갑니다.
    생년월일·출생시간·출생지역 원본은 저장하지 않습니다.

[어디에 저장되나]
    기본은 Supabase public.cards 입니다.
        stable_key   위에서 만든 SHA-256 열쇠 (unique — 같은 열쇠는 한 줄만)
        card_year    몇 년도 카드인지
        card_data    카드 내용(JSON). 개인정보는 한 글자도 들어가지 않습니다.

    환경변수(SUPABASE_URL · SUPABASE_SECRET_KEY)가 없으면
    개발용 로컬 파일(data/cards.json)로 자동으로 내려옵니다.
    analytics.py 와 같은 규칙(HALMAE_STORAGE)을 따릅니다.

    카드를 만들기 전에 stable_key 로 먼저 조회하기 때문에,
    이미 있는 카드라면 Gemini 를 부르지 않습니다. (돈과 quota 를 아낍니다)
"""

import hashlib
import json
import re
import threading
from datetime import datetime, timezone
from pathlib import Path

import db

DEFAULT_JSON_PATH = Path(__file__).parent / "data" / "cards.json"


# ===============================================================
#  1. 열쇠(key) 만들기
# ===============================================================
def _text(value) -> str:
    """어떤 값이든 열쇠에 넣을 수 있는 반듯한 글자로 바꿉니다."""
    if value is None:
        return "-"
    if hasattr(value, "isoformat"):          # date · time
        return value.isoformat()
    return " ".join(str(value).split())      # 앞뒤 공백과 겹친 공백 정리


# 좌표를 소수점 몇 자리까지 볼지.
#   3자리 = 약 100m. 같은 도시를 다르게 적어도 좌표가 사실상 같으면 같은 카드가 나옵니다.
COORD_DECIMALS = 3


def _coord(value) -> str:
    """좌표를 소수점 3자리로 고정한 글자로 바꿉니다.

    round() 만 쓰면 35.179953 → 35.18 이 되어 '35.180' 과 다른 글자가 됩니다.
    자릿수를 고정해야 두 값이 같은 열쇠를 만듭니다.
    """
    if value is None:
        return "-"
    try:
        return f"{float(value):.{COORD_DECIMALS}f}"
    except (TypeError, ValueError):
        return "-"


def build_card_fingerprint(
    answers: dict,
    saju: dict | None,
    astro: dict | None,
    year: int,
    source: str = "gemini",
) -> str:
    """카드를 결정하는 값들을 사람이 읽을 수 있는 한 줄로 만듭니다.

    이 글자가 같으면 같은 카드, 다르면 다른 카드입니다.
    (열쇠가 왜 이렇게 나왔는지 확인할 수 있도록 일부러 읽을 수 있게 만듭니다.)

    [일부러 넣지 않는 것]
      · 출생지역 원문 — "서울"과 "서울특별시"를 다른 사람으로 보지 않기 위해
        글자 대신 좌표(위도·경도)를 씁니다.
      · 고민 분야, 추가 질문 — 올해의 카드는 "무엇을 물었는가"와 상관없이
        '그 사람의 그 해를 대표하는 한 장'이기 때문입니다.
      · 음력/양력, 평달/윤달 — 아래 양력 날짜에 이미 반영되어 있습니다.
    """
    # 날짜는 반드시 '양력으로 변환이 끝난' 날짜를 씁니다.
    # 음력으로 넣든 양력으로 넣든 같은 날이면 같은 카드가 나와야 하니까요.
    solar_date = saju.get("양력 날짜") if saju else None
    if solar_date is None:
        solar_date = answers.get("생년월일")

    # 출생시간도 사주 계산이 정리해둔 값을 씁니다. ("08:49" 또는 모르면 None)
    if saju and "출생시간" in saju:
        birth_time = saju["출생시간"]
    else:
        birth_time = None if answers.get("출생시간 모름") else answers.get("출생시간")

    parts = [
        # 개발용 Mock 카드와 진짜 카드가 섞이지 않도록 표시해둡니다.
        # (배포할 때는 늘 "gemini" 라 열쇠에 영향을 주지 않습니다.)
        f"source={_text(source)}",
        f"year={year}",
        f"solar_date={_text(solar_date)}",
        f"birth_time={_text(birth_time)}",
        # 출생지역은 글자가 아니라 좌표로 (소수점 3자리 ≈ 100m)
        f"lat={_coord(astro.get('latitude') if astro else None)}",
        f"lon={_coord(astro.get('longitude') if astro else None)}",
        f"gender={_text(answers.get('성별'))}",
    ]

    pillars = saju["기둥"] if saju else {}
    for name in ("년주", "월주", "일주", "시주"):
        pillar = pillars.get(name)
        parts.append(f"{name}={pillar['한글'] if pillar else '-'}")

    parts.append(f"sun={_text(astro.get('sun_sign') if astro else None)}")
    parts.append(f"moon={_text(astro.get('moon_sign') if astro else None)}")
    parts.append(f"rising={_text(astro.get('rising_sign') if astro else None)}")

    return "|".join(parts)


def build_card_key(
    answers: dict,
    saju: dict | None,
    astro: dict | None,
    year: int,
    source: str = "gemini",
) -> str:
    """위 한 줄을 SHA-256 으로 요약한 열쇠. 언제 어디서 돌려도 같은 값입니다."""
    fingerprint = build_card_fingerprint(answers, saju, astro, year, source)
    return hashlib.sha256(fingerprint.encode("utf-8")).hexdigest()


# ===============================================================
#  1-2. 카드에서 이름 지우기 (저장 전 마지막 울타리)
# ===============================================================
# 카드 글은 Gemini 가 씁니다. 프롬프트에 "이름을 적지 말 것"이라고 못 박아두었지만,
# 모델이 그 규칙을 어길 수도 있습니다. card_data 는 Supabase 에 남는 값이라
# 이름이 한 번 섞여 들어가면 그대로 저장되어 버립니다.
#
# 그래서 저장하기 전에 한 번 더 걸러냅니다.
#   · 성을 포함한 이름 전체("안혜진")   → 언제나 지웁니다
#   · 이름만("혜진")                    → 부르는 말일 때만 지웁니다 ("혜진아", "혜진이")
#     ('지원' 처럼 이름이 흔한 낱말과 겹칠 때 멀쩡한 문장까지 망가뜨리지 않으려고
#      호격 조사가 붙은 경우로 좁혔습니다.)
#
# 화면에 보여주는 카드에도 같은 처리를 하므로,
# "지금 본 카드"와 "저장된 카드"가 늘 같습니다. (다시 열어도 같은 카드)
NAME_REPLACEMENT = "너"

# 카드에서 글자가 들어 있는 칸. 나머지(year 등)는 손대지 않습니다.
CARD_TEXT_FIELDS = ("title", "keyword", "message", "basis", "caution")
CARD_LIST_FIELDS = ("actions",)


def _scrub_name_in_text(text: str, name: str) -> str:
    """글 한 덩이에서 이름을 지웁니다."""
    if not text or not name:
        return text
    cleaned = re.sub(re.escape(name), NAME_REPLACEMENT, text)
    if len(name) >= 3:                       # 성(1자) + 이름(2자 이상)으로 봅니다
        given = name[1:]
        # 부르는 말일 때만 — "혜진아" / "혜진이" / "혜진야"
        cleaned = re.sub(
            re.escape(given) + "[아야이](?![가-힣])", NAME_REPLACEMENT, cleaned
        )
    return cleaned


def scrub_card(card: dict, name: str | None) -> dict:
    """카드에서 이름을 지운 사본을 돌려줍니다. (원본은 건드리지 않습니다)"""
    name = " ".join(str(name or "").split())
    if not name or len(name) < 2 or not isinstance(card, dict):
        return card
    cleaned = dict(card)
    for field in CARD_TEXT_FIELDS:
        value = cleaned.get(field)
        if isinstance(value, str):
            cleaned[field] = _scrub_name_in_text(value, name)
    for field in CARD_LIST_FIELDS:
        value = cleaned.get(field)
        if isinstance(value, list):
            cleaned[field] = [
                _scrub_name_in_text(item, name) if isinstance(item, str) else item
                for item in value
            ]
    return cleaned


# ===============================================================
#  2. 저장소 (나중에 갈아끼울 수 있게 얇게 감쌌습니다)
# ===============================================================
class CardStore:
    """카드를 어디에 보관할지 정하는 껍데기."""

    def get(self, key: str) -> dict | None:
        raise NotImplementedError

    def put(self, key: str, card: dict, year: int, model: str) -> None:
        raise NotImplementedError

    def all_records(self) -> dict:
        raise NotImplementedError

    def delete(self, key: str) -> bool:
        """열쇠 하나에 해당하는 카드만 지웁니다. 지웠으면 True."""
        raise NotImplementedError


class JsonCardStore(CardStore):
    """개발용 — data/cards.json 파일 하나에 모아둡니다."""

    def __init__(self, path: Path | str = DEFAULT_JSON_PATH):
        self.path = Path(path)
        self._lock = threading.Lock()

    def _read(self) -> dict:
        if not self.path.exists():
            return {}
        try:
            with self.path.open(encoding="utf-8") as file:
                data = json.load(file)
            return data if isinstance(data, dict) else {}
        except (json.JSONDecodeError, OSError):
            # 파일이 깨져 있어도 앱이 멈추면 안 되니, 없는 셈 치고 새로 만듭니다.
            return {}

    def get(self, key: str) -> dict | None:
        with self._lock:
            record = self._read().get(key)
        return record.get("card") if record else None

    def put(self, key: str, card: dict, year: int, model: str) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with self._lock:
            data = self._read()
            data[key] = {
                "card": card,
                "year": year,
                "model": model,
                "created_at": datetime.now(timezone.utc).isoformat(
                    timespec="seconds"
                ),
            }
            temporary = self.path.with_suffix(".json.tmp")
            with temporary.open("w", encoding="utf-8") as file:
                json.dump(data, file, ensure_ascii=False, indent=2)
            # 쓰다가 멈춰도 원본이 깨지지 않도록 다 쓴 뒤에 갈아끼웁니다.
            temporary.replace(self.path)

    def all_records(self) -> dict:
        with self._lock:
            return self._read()

    def delete(self, key: str) -> bool:
        with self._lock:
            data = self._read()
            if key not in data:
                return False
            del data[key]
            self.path.parent.mkdir(parents=True, exist_ok=True)
            temporary = self.path.with_suffix(".json.tmp")
            with temporary.open("w", encoding="utf-8") as file:
                json.dump(data, file, ensure_ascii=False, indent=2)
            temporary.replace(self.path)
            return True


class MemoryCardStore(CardStore):
    """테스트용 — 파일을 만들지 않고 메모리에만 담아둡니다."""

    def __init__(self):
        self.records: dict = {}

    def get(self, key: str) -> dict | None:
        record = self.records.get(key)
        return record.get("card") if record else None

    def put(self, key: str, card: dict, year: int, model: str) -> None:
        self.records[key] = {"card": card, "year": year, "model": model}

    def all_records(self) -> dict:
        return dict(self.records)

    def delete(self, key: str) -> bool:
        return self.records.pop(key, None) is not None


class SupabaseCardStore(CardStore):
    """실사용 — Supabase public.cards.

    stable_key 에 unique 제약이 걸려 있어서 같은 열쇠는 한 줄만 남습니다.
    같은 사람이 같은 해에 다시 물으면 이 줄을 꺼내 그대로 보여줍니다.

    [저장하지 않는 것]
        모델 이름(model)은 이 테이블에 칸이 없어 저장하지 않습니다.
        card_data 에는 카드 결과(YearCard)만 넣습니다 —
        이름·생년월일·출생시간·출생지역·좌표·질문 원문은 넣지 않습니다.
    """

    def __init__(self, fallback: CardStore | None = None):
        self.fallback = fallback

    def get(self, key: str) -> dict | None:
        client = db.get_client()
        if client is None:
            return self.fallback.get(key) if self.fallback else None
        try:
            rows = (
                client.table(db.CARDS_TABLE)
                .select("card_data")
                .eq("stable_key", key)
                .limit(1)
                .execute()
            ).data
        except Exception as exc:
            db.record_failure("cards select", exc, key[:16])
            return self.fallback.get(key) if self.fallback else None

        if not rows:
            return None
        card = rows[0].get("card_data")
        # jsonb 칸이면 dict 로, text 칸이면 글자로 돌아옵니다. 둘 다 받아줍니다.
        if isinstance(card, str):
            try:
                card = json.loads(card)
            except json.JSONDecodeError:
                return None
        return card if isinstance(card, dict) else None

    def put(self, key: str, card: dict, year: int, model: str) -> None:
        client = db.get_client()
        if client is None:
            self._to_fallback(key, card, year, model)
            return
        payload = {
            "stable_key": key,
            "card_year": int(year),
            "card_data": card,          # 카드 결과만. 개인정보는 들어 있지 않습니다.
        }
        try:
            # 같은 열쇠가 이미 있으면 새로 쌓지 않고 그 줄을 씁니다.
            client.table(db.CARDS_TABLE).upsert(
                payload, on_conflict="stable_key"
            ).execute()
        except Exception as exc:
            db.record_failure("cards upsert", exc, key[:16])
            self._to_fallback(key, card, year, model)

    def all_records(self) -> dict:
        """개발용 목록 보기. {열쇠: {card, year, created_at}}"""
        client = db.get_client()
        if client is None:
            return self.fallback.all_records() if self.fallback else {}
        try:
            rows = (
                client.table(db.CARDS_TABLE)
                .select("*")
                .order("created_at")
                .limit(1000)
                .execute()
            ).data or []
        except Exception as exc:
            db.record_failure("cards select all", exc)
            return self.fallback.all_records() if self.fallback else {}

        records = {}
        for row in rows:
            card = row.get("card_data")
            if isinstance(card, str):
                try:
                    card = json.loads(card)
                except json.JSONDecodeError:
                    card = {}
            records[row.get("stable_key", "")] = {
                "card": card or {},
                "year": row.get("card_year"),
                "model": "-",               # 테이블에 칸이 없습니다
                "created_at": row.get("created_at", ""),
            }
        return records

    def delete(self, key: str) -> bool:
        """열쇠 하나짜리 줄만 지웁니다.

        .eq("stable_key", key) 없이 delete() 를 부르면 테이블이 통째로 비어버리므로,
        열쇠가 빈 값이면 아무것도 하지 않고 돌아섭니다. (실수 방지)
        """
        if not key:
            return False
        client = db.get_client()
        if client is None:
            return self.fallback.delete(key) if self.fallback else False
        try:
            rows = (
                client.table(db.CARDS_TABLE)
                .delete()
                .eq("stable_key", key)
                .execute()
            ).data or []
        except Exception as exc:
            db.record_failure("cards delete", exc, key[:16])
            return False
        deleted = len(rows) > 0
        # 로컬 대체 파일에도 같은 열쇠가 남아 있을 수 있어 함께 지웁니다.
        if self.fallback is not None:
            try:
                deleted = self.fallback.delete(key) or deleted
            except Exception:
                pass
        return deleted

    def _to_fallback(self, key: str, card: dict, year: int, model: str) -> None:
        """Supabase 에 못 넣은 카드를 로컬 파일에 적어둡니다. (유실 방지)"""
        if self.fallback is None:
            return
        try:
            self.fallback.put(key, card, year, model)
        except Exception:
            pass


def _default_card_store() -> CardStore:
    """analytics.py 와 같은 규칙으로 저장소를 고릅니다 (db.use_supabase)."""
    if db.use_supabase():
        return SupabaseCardStore(fallback=JsonCardStore())
    return JsonCardStore()


def storage_label() -> str:
    """개발자 화면에 보여줄 '카드가 지금 어디에 저장되는지' 한 줄."""
    if not db.use_supabase():
        return f"로컬 파일 · {DEFAULT_JSON_PATH}"
    if db.is_available():
        return f"Supabase · {db.CARDS_TABLE}"
    return f"Supabase 연결 실패 → 로컬 파일 대체 · {DEFAULT_JSON_PATH}"


_store: CardStore = _default_card_store()


def set_store(store: CardStore) -> None:
    """저장소를 갈아끼웁니다. (나중에 DB로 옮길 때 여기만 부르면 됩니다.)"""
    global _store
    _store = store


def get_store() -> CardStore:
    return _store


# ===============================================================
#  3. 바깥에서 쓰는 함수
# ===============================================================
def load_card(key: str) -> dict | None:
    """이미 만들어둔 카드를 꺼냅니다. 없으면 None."""
    try:
        return _store.get(key)
    except Exception:
        return None      # 저장소 문제로 앱이 멈추면 안 됩니다


def save_card(key: str, card: dict, year: int, model: str) -> None:
    """새로 만든 카드를 저장해둡니다."""
    try:
        _store.put(key, card, year, model)
    except Exception:
        pass


def delete_card(key: str) -> bool:
    """열쇠 하나에 해당하는 카드만 지웁니다. (개발 중 다시 뽑고 싶을 때)

    지우는 범위는 딱 그 한 줄입니다. 테이블을 비우는 길은 없습니다.
    """
    if not key:
        return False
    try:
        return bool(_store.delete(key))
    except Exception:
        return False


# ---------------------------------------------------------------
#  터미널에서 확인하기
#      python card_store.py                      저장된 카드 목록
#      python card_store.py --delete <열쇠앞자리>  그 카드 한 장만 지우기
#      python card_store.py --clear              로컬 파일만 비우기 (개발용)
#      python card_store.py --sql                Supabase 에서 지우는 SQL 보기
#
#  --delete 는 열쇠 앞자리(8자 이상)로 찾습니다.
#  목록에 찍히는 앞 16자를 그대로 붙여 넣으면 됩니다.
#  여러 장이 걸리면 아무것도 지우지 않고 멈춥니다. (실수 방지)
# ---------------------------------------------------------------
DELETE_SQL = """-- Supabase Dashboard → SQL Editor 에 붙여 넣으세요.
-- 1) 무엇이 지워질지 먼저 눈으로 확인합니다. (개인정보는 이 테이블에 없습니다)
select stable_key, card_year, created_at, card_data->>'title' as title
from public.cards
where card_year = {year}
order by created_at desc;

-- 2) 위 목록에서 지울 줄의 stable_key 를 그대로 넣어 한 줄만 지웁니다.
delete from public.cards
where stable_key = '여기에_위에서_고른_stable_key_붙여넣기';

-- where 절 없는 delete 는 절대 쓰지 마세요. 테이블이 통째로 비워집니다.
-- 카드를 지우면 다음 접속에서 같은 열쇠로 새 카드가 만들어집니다."""


def _print_records(records: dict) -> None:
    print(f"[저장된 올해의 카드]  저장소: {storage_label()}")
    print(f"총 {len(records)}장")
    print()
    for card_key, record in records.items():
        card = record.get("card", {})
        print(f"  {card_key[:16]}…  {record.get('year')}  "
              f"{card.get('title', '?'):<20} {card.get('keyword', '')}")
        print(f"      만든 때 {record.get('created_at', '?')} · "
              f"모델 {record.get('model', '?')}")
        actions = card.get("actions") or []
        for action in actions:
            print(f"      행동 · {action}")


if __name__ == "__main__":
    import sys

    argv = sys.argv[1:]

    if "--sql" in argv:
        print(DELETE_SQL.format(year=datetime.now(timezone.utc).year))
        sys.exit(0)

    if "--delete" in argv:
        position = argv.index("--delete")
        prefix = argv[position + 1] if len(argv) > position + 1 else ""
        prefix = prefix.strip().rstrip("…")
        if len(prefix) < 8:
            print("지울 카드의 열쇠 앞자리를 8자 이상 적어주세요.")
            print("  예) python card_store.py --delete 3f9a12bc4d5e6f70")
            print("  앞자리는 python card_store.py 목록에 찍힙니다.")
            sys.exit(2)

        matches = [
            key for key in get_store().all_records() if key.startswith(prefix)
        ]
        if not matches:
            print(f"'{prefix}' 로 시작하는 카드가 없습니다.")
            sys.exit(1)
        if len(matches) > 1:
            print(f"'{prefix}' 로 시작하는 카드가 {len(matches)}장입니다. "
                  "앞자리를 더 길게 적어 한 장만 고르세요.")
            sys.exit(1)

        if delete_card(matches[0]):
            print(f"지웠습니다: {matches[0][:16]}… (1장)")
            print("다음 접속에서 같은 열쇠로 카드가 새로 만들어집니다.")
        else:
            print("지우지 못했습니다. 저장소 연결을 확인해주세요.")
            sys.exit(1)
        sys.exit(0)

    if "--clear" in argv:
        # 로컬 파일만 지웁니다. Supabase 는 실수로 지우면 되돌릴 수 없으므로
        # 여기서 건드리지 않고 --delete 로 한 장씩, 또는 Dashboard 에서 지웁니다.
        if DEFAULT_JSON_PATH.exists():
            DEFAULT_JSON_PATH.unlink()
            print(f"지웠습니다: {DEFAULT_JSON_PATH}")
        else:
            print("지울 파일이 없습니다.")
        if db.use_supabase():
            print("※ Supabase 에 저장된 카드는 지우지 않았습니다.")
            print("   한 장만 지우려면  python card_store.py --delete <열쇠앞자리>")
            print("   SQL 로 지우려면   python card_store.py --sql")
        sys.exit(0)

    _print_records(get_store().all_records())
