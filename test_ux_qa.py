"""실사용 직전 최종 QA — UX · 데이터 · 운영 품질 점검 (개발 테스트 전용)

    python test_ux_qa.py

이 파일이 확인하는 것 (실사용자에게 공유하기 전 열 가지)
    1. 피드백 UI      제목 한 줄 + 버튼 두 개뿐인지 · 선택 상태가 보이는지
                      · 같은 세션이면 줄을 쌓지 않고 고쳐 쓰는지
    2. 개발자 UI      프롬프트 · Debug · 좌표 · 카드 열쇠가 USE_DEV_MODE 안에 갇혀 있는지
                      · Funnel 화면(?dev=)이 열쇠 없이 열리지 않는지
    3. 개인정보 안내   '할매에게 물어보기' 앞에 안내가 있고, 동의 없이는 눌리지 않는지
    4. 결과 고지      오락·자기성찰 / 의료·법률·투자 문구가 있는지
    5. Funnel 중복    화면 노출은 세션당 한 번, 버튼 클릭은 누를 때마다인지
    6. Premium        결제 코드가 한 줄도 없고, 베타 안내와 의향 버튼이 있는지
    7. 모바일         좁은 화면 손질(@media)이 실제로 CSS 에 들어갔는지
    8. 오류 처리      계산·Gemini·저장 실패가 전부 붙잡히는지 · st.exception 이 없는지
    9. 개인정보 저장   Supabase 세 테이블에 실제로 나가는 payload 에 원문이 없는지
   10. API 보호      rerun 으로 Gemini 를 다시 부르지 않도록 막혀 있는지

절대 하지 않는 일
    - Gemini API 호출
    - Supabase 읽기 / 쓰기 (연결을 가짜로 바꿔치기해서 payload 만 들여다봅니다)
    - 로컬 파일(data/*.csv · cards.json) 쓰기 (메모리 저장소만 씁니다)
"""

import ast
import json
import os
import sys
from fnmatch import fnmatch
from pathlib import Path

# 이 테스트는 저장소를 건드리지 않습니다.
# analytics 를 import 하는 순간 저장소가 정해지므로, 그 전에 못을 박아둡니다.
os.environ.setdefault("HALMAE_STORAGE", "local")

import analytics  # noqa: E402
import card_store  # noqa: E402
import config  # noqa: E402
import db  # noqa: E402
import theme  # noqa: E402

ROOT = Path(__file__).parent
APP_SOURCE = (ROOT / "app.py").read_text(encoding="utf-8")
APP_TREE = ast.parse(APP_SOURCE)

_failures: list[str] = []


def check(label: str, ok: bool, detail: str = "") -> None:
    mark = "PASS" if ok else "FAIL"
    print(f"  [{mark}] {label}" + (f"  — {detail}" if detail else ""))
    if not ok:
        _failures.append(label)


def section(title: str) -> None:
    print()
    print(f"[{title}]")


# ===============================================================
#  app.py 를 '읽어서' 확인하기 위한 도구들
#
#  app.py 는 import 하는 순간 Streamlit 화면을 그리려 하기 때문에
#  여기서는 실행하지 않고 코드를 구문 트리로 읽어 확인합니다.
# ===============================================================
def _func(name: str) -> ast.FunctionDef | None:
    for node in ast.walk(APP_TREE):
        if isinstance(node, ast.FunctionDef) and node.name == name:
            return node
    return None


def _source_of(node: ast.AST) -> str:
    return ast.get_source_segment(APP_SOURCE, node) or ""


def _snippet(text: str, term: str, span: int = 30) -> str:
    """검사에 걸린 자리를 앞뒤로 조금 붙여 보여줍니다. (없으면 빈 글자)"""
    at = text.find(term)
    if at < 0:
        return ""
    return "…" + text[max(0, at - span):at + len(term) + span] + "…"


def _consent_label_text() -> str:
    """동의 체크박스에 실제로 적히는 글.

    st.checkbox("...", key="in_consent") 의 첫 인자를 코드에서 꺼냅니다.
    문구가 여러 줄로 나뉘어 있어도(문자열 이어붙이기) 하나로 합쳐 돌려줍니다.
    """
    render_input = _func("render_input")
    if render_input is None:
        return ""
    for node in ast.walk(render_input):
        if not isinstance(node, ast.Call) or _call_name(node) != "st.checkbox":
            continue
        keys = [kw for kw in node.keywords
                if kw.arg == "key" and isinstance(kw.value, ast.Constant)
                and kw.value.value == "in_consent"]
        if keys and node.args:
            try:
                return str(ast.literal_eval(node.args[0]))
            except Exception:
                return _source_of(node.args[0])
    return ""


def _calls(tree: ast.AST):
    """트리 안의 모든 함수 호출."""
    return [n for n in ast.walk(tree) if isinstance(n, ast.Call)]


def _call_name(node: ast.Call) -> str:
    """호출된 이름. st.write → 'st.write', track → 'track'."""
    func = node.func
    if isinstance(func, ast.Name):
        return func.id
    if isinstance(func, ast.Attribute):
        base = func.value
        if isinstance(base, ast.Name):
            return f"{base.id}.{func.attr}"
        return f".{func.attr}"
    return ""


def _mentions(node: ast.AST, name: str) -> bool:
    return any(
        isinstance(n, ast.Name) and n.id == name for n in ast.walk(node)
    )


def _guarded_ranges(flag: str) -> list[tuple[int, int]]:
    """`if <flag> ...:` 의 본문이 차지하는 줄 범위를 모읍니다.

    여기에 들어 있는 줄은 그 설정이 켜져 있을 때만 실행됩니다.
    `if not <flag>: return` 으로 시작하는 함수는 함수 전체를 범위로 잡습니다.
    """
    ranges: list[tuple[int, int]] = []

    for node in ast.walk(APP_TREE):
        if isinstance(node, ast.If) and _mentions(node.test, flag):
            # 조건문 줄부터 본문 끝까지. (else 쪽은 잠긴 것이 아니므로 뺍니다)
            ranges.append((node.test.lineno, node.body[-1].end_lineno))

        # def f(): if not FLAG: return ...   → 함수 전체가 잠겨 있습니다
        if isinstance(node, ast.FunctionDef):
            first = _first_statement(node)
            if (
                isinstance(first, ast.If)
                and _mentions(first.test, flag)
                and any(isinstance(s, ast.Return) for s in first.body)
            ):
                ranges.append((node.lineno, node.end_lineno))

    return ranges


def _first_statement(node: ast.FunctionDef) -> ast.stmt | None:
    """함수의 첫 '실행되는' 문장. 설명글(docstring)은 건너뜁니다."""
    for statement in node.body:
        if (
            isinstance(statement, ast.Expr)
            and isinstance(statement.value, ast.Constant)
            and isinstance(statement.value.value, str)
        ):
            continue
        return statement
    return None


def _inside(line: int, ranges: list[tuple[int, int]]) -> bool:
    return any(start <= line <= end for start, end in ranges)


def _string_values_assigned(scope: ast.AST, name: str) -> list[str]:
    """그 함수 안에서 이 변수에 넣은 글자 값들.

        chosen = "positive" / chosen = "negative"  →  ["positive", "negative"]

    f"feedback_{chosen}" 이 실제로 무엇이 되는지 알아내려고 씁니다.
    """
    found = []
    for node in ast.walk(scope):
        if isinstance(node, ast.Assign):
            targets = [t.id for t in node.targets if isinstance(t, ast.Name)]
            if name in targets:
                found += _possible_strings(node.value)
    return [v for v in found if "*" not in v]


def _possible_strings(node: ast.AST, scope: ast.AST | None = None) -> list[str]:
    """이벤트 이름 인자에서 나올 수 있는 값들.

        "landing_view"                        → ["landing_view"]
        "more_click" if step == 1 else "..."  → 둘 다
        f"step{step}_view"                    → ["step*_view"]  (별표는 아무 값)
    """
    if isinstance(node, ast.Constant) and isinstance(node.value, str):
        return [node.value]
    if isinstance(node, ast.IfExp):
        return _possible_strings(node.body) + _possible_strings(node.orelse)
    if isinstance(node, ast.JoinedStr):
        # 끼워 넣는 칸이 하나뿐이고, 그 값이 같은 함수 안에서 정해진
        # 글자라면 실제 이름으로 풀어냅니다. (f"feedback_{chosen}")
        slots = [
            v for v in node.values if isinstance(v, ast.FormattedValue)
        ]
        if scope is not None and len(slots) == 1 and isinstance(
            slots[0].value, ast.Name
        ):
            options = _string_values_assigned(scope, slots[0].value.id)
            if options:
                return [
                    "".join(
                        option if v is slots[0] else
                        (v.value if isinstance(v, ast.Constant) else "*")
                        for v in node.values
                    )
                    for option in options
                ]
        parts = []
        for value in node.values:
            if isinstance(value, ast.Constant) and isinstance(value.value, str):
                parts.append(value.value)
            else:
                parts.append("*")
        return ["".join(parts)]
    return []


# ===============================================================
#  1. 피드백 UI — 제목 한 줄 + 버튼 두 개
# ===============================================================
FEEDBACK_TITLE = "할매 말, 잘 맞았나요?"


def check_feedback_ui() -> None:
    section("1. 피드백 UI — 버튼 두 개만")

    node = _func("render_feedback")
    check("render_feedback() 이 있다", node is not None)
    if node is None:
        return
    body = _source_of(node)

    check("제목이 '할매 말, 잘 맞았나요?' 다", FEEDBACK_TITLE in body)

    buttons = [c for c in _calls(node) if _call_name(c).endswith(".button")]
    check("버튼이 정확히 두 개다", len(buttons) == 2, f"{len(buttons)}개")

    labels = list(getattr(sys.modules.get("app", None), "x", []) or [])  # noqa
    # app.py 를 실행하지 않으므로 라벨은 코드에서 직접 읽습니다.
    check("👍 맞아요 라벨이 있다", '"positive": "👍 맞아요"' in APP_SOURCE)
    check("👎 아니에요 라벨이 있다", '"negative": "👎 아니에요"' in APP_SOURCE)

    # 이모지 위젯(st.feedback)과 버튼이 함께 뜨면 같은 질문이 두 번 보입니다.
    check("이모지 위젯(st.feedback)을 쓰지 않는다",
          "st.feedback(" not in APP_SOURCE)
    check("이모지 위젯용 CSS 가 남아 있지 않다",
          "stFeedback" not in theme.build_css())

    # 고른 쪽만 primary → 선택 상태가 눈에 보입니다.
    check("고른 쪽을 primary 로 그린다",
          '"primary" if current == name else "secondary"' in body)
    check("두 버튼 모두 type 을 _button_type 으로 정한다",
          body.count("_button_type(") == 3,    # 정의 1 + 사용 2
          f"{body.count('_button_type(')}회")

    # 내부 값(positive/negative)이 화면 문구로 새어나가지 않아야 합니다.
    shown = [
        s.value for s in ast.walk(node)
        if isinstance(s, ast.Constant) and isinstance(s.value, str)
    ]
    leaked = [
        text for text in shown
        if ("positive" in text or "negative" in text) and (
            "<" in text or "맞" in text or "아니" in text
        )
    ]
    check("화면 문구에 positive/negative 가 없다", not leaked, str(leaked))

    # 답이 바뀌었을 때만 저장 → 같은 쪽을 또 눌러도 줄이 늘지 않습니다.
    check("답이 바뀔 때만 저장한다", "if chosen and chosen != current:" in body)


def check_feedback_storage() -> None:
    section("1-2. 피드백 저장 — 같은 세션이면 줄을 고쳐 씁니다")

    store = analytics.MemoryFeedbackStore()
    analytics.set_feedback_store(store)

    session = "qa-session-0001"
    analytics.save_feedback(session, "positive", concern="연애", model="qa")
    analytics.save_feedback(session, "negative", concern="연애", model="qa")
    analytics.save_feedback(session, "positive", concern="연애", model="qa")

    rows = store.read_all()
    check("👍 → 👎 → 👍 을 눌러도 한 줄만 남는다", len(rows) == 1, f"{len(rows)}줄")
    check("마지막 답이 남는다",
          rows and rows[0]["feedback_result"] == "positive",
          rows[0]["feedback_result"] if rows else "-")

    # 다른 사람은 다른 줄
    analytics.save_feedback("qa-session-0002", "negative", model="qa")
    check("다른 세션은 따로 한 줄", len(store.read_all()) == 2)

    # 정해진 두 값 말고는 저장하지 않습니다.
    analytics.save_feedback("qa-session-0003", "좋아요", model="qa")
    check("positive/negative 가 아니면 저장하지 않는다",
          len(store.read_all()) == 2)

    check("Supabase 는 session_id 로 upsert 한다",
          'on_conflict="session_id"'
          in (ROOT / "analytics.py").read_text(encoding="utf-8"))


# ===============================================================
#  2. 개발자 UI — 배포 화면에서 완전히 사라졌는지
# ===============================================================
# 이 호출들은 켜져 있으면 프롬프트 · 원본 응답 · 좌표 · 카드 열쇠를 화면에 띄웁니다.
DEV_ONLY_CALLS = {
    "render_saju_check",
    "render_astrology_check",
    "render_calendar_check",
    "build_prompt",
    "format_saju_for_prompt",
    "st.json",
    "st.write",
    "redraw_year_card",
}

# Funnel 지표 화면 전용 — USE_DEV_MODE 가 아니라 ?dev=<열쇠> 로 잠급니다.
FUNNEL_ONLY_FUNCS = {"render_dev_funnel", "render_storage_status"}

# 화면에 글자를 그리는 Streamlit 명령들 (st.markdown · col.button …)
UI_OUTPUT_CALLS = {
    "markdown", "caption", "write", "code", "json", "text", "latex",
    "button", "checkbox", "radio", "selectbox", "expander", "toggle",
    "info", "warning", "error", "success",
    "metric", "dataframe", "table", "header", "subheader", "title",
}

# 일반 사용자 화면에 절대 나오면 안 되는 낱말
DEV_ONLY_WORDS = (
    "DEV MODE", "개발자용", "개발용 모델", "Mock AI",
    "프롬프트", "Prompt", "System prompt", "Debug",
    "stable_key", "session_id", "fingerprint", "카드 열쇠",
    "Supabase", "gemini-", "SECRET_KEY",
)


def check_dev_ui_hidden() -> None:
    section("2. 개발자 UI — 배포 화면에서 완전히 사라졌는지")

    check("USE_DEV_MODE 기본값이 False 다", config.USE_DEV_MODE_DEFAULT is False)
    check("지금 설정도 USE_DEV_MODE = False 다", config.USE_DEV_MODE is False,
          f"USE_DEV_MODE={config.USE_DEV_MODE}")

    ranges = _guarded_ranges("USE_DEV_MODE")
    check("USE_DEV_MODE 로 잠근 구역이 있다", bool(ranges), f"{len(ranges)}곳")

    # Funnel 화면 안쪽은 ?dev= 로 따로 잠그므로 이 검사에서 뺍니다.
    skip_ranges = []
    for name in FUNNEL_ONLY_FUNCS:
        node = _func(name)
        if node:
            skip_ranges.append((node.lineno, node.end_lineno))

    leaks = []
    for call in _calls(APP_TREE):
        name = _call_name(call)
        if name not in DEV_ONLY_CALLS:
            continue
        if _inside(call.lineno, skip_ranges):
            continue
        if not _inside(call.lineno, ranges):
            leaks.append(f"{name}() · app.py:{call.lineno}")

    check("개발자용 출력이 전부 USE_DEV_MODE 안에 있다", not leaks,
          " / ".join(leaks) if leaks else "새는 곳 없음")

    # 화면에 '실제로 그려지는' 글자만 훑습니다.
    # (주석과 설명글은 브라우저로 내려가지 않으므로 세지 않습니다)
    unguarded_text = []
    for call in _calls(APP_TREE):
        name = _call_name(call)
        base, _, method = name.rpartition(".")
        # st.markdown(...) 이거나, 칸 변수의 버튼/지표(col.button)만 셉니다.
        # log.exception(...) 같은 '로그' 는 화면에 뜨지 않으므로 뺍니다.
        is_screen = base == "st" or method in ("button", "metric")
        if not is_screen or method not in UI_OUTPUT_CALLS:
            continue
        if _inside(call.lineno, skip_ranges) or _inside(call.lineno, ranges):
            continue
        shown = " ".join(
            n.value for n in ast.walk(call)
            if isinstance(n, ast.Constant) and isinstance(n.value, str)
        )
        for marker in DEV_ONLY_WORDS:
            if marker.lower() in shown.lower():
                unguarded_text.append(f"'{marker}' · app.py:{call.lineno}")

    check("개발자용 문구가 화면에 그려지는 곳이 없다", not unguarded_text,
          " / ".join(unguarded_text) if unguarded_text else "새는 곳 없음")

    # 모델 배지 · Mock 꼬리표는 함수 첫 줄에서 스스로 돌아섭니다.
    for name in ("render_model_badge", "render_mock_footer"):
        node = _func(name)
        first = node.body[1] if node and len(node.body) > 1 else None
        ok = node is not None and any(
            isinstance(s, ast.If) and _mentions(s.test, "USE_DEV_MODE")
            for s in node.body[:3]
        )
        check(f"{name}() 이 USE_DEV_MODE 아니면 곧바로 돌아선다", ok)

    # Supabase 상태 · 원본 이벤트는 Funnel 화면 안에만
    funnel_call_lines = [
        c.lineno for c in _calls(APP_TREE)
        if _call_name(c) == "render_dev_funnel"
    ]
    dev_funnel_ranges = _guarded_ranges("IS_DEV_FUNNEL")
    check("render_dev_funnel() 은 IS_DEV_FUNNEL 안에서만 불린다",
          bool(funnel_call_lines)
          and all(_inside(n, dev_funnel_ranges) for n in funnel_call_lines))

    storage_calls = [
        c.lineno for c in _calls(APP_TREE)
        if _call_name(c) == "render_storage_status"
    ]
    funnel = _func("render_dev_funnel")
    check("Supabase 상태 화면은 Funnel 화면 안에서만 불린다",
          bool(funnel) and all(
              funnel.lineno <= n <= funnel.end_lineno for n in storage_calls
          ))


def check_dev_funnel_locked() -> None:
    section("2-2. Funnel 지표 화면 — 열쇠 없이는 열리지 않는지")

    saved = os.environ.pop("HALMAE_DEV_KEY", None)
    try:
        # 열쇠를 정해두지 않았을 때: 어떤 주소로도 열리지 않아야 합니다.
        for guess in ("1", "true", "dev", "test", "admin", "halmae", "yes"):
            check(f"열쇠 없이 ?dev={guess} 는 열리지 않는다",
                  analytics.dev_dashboard_allowed(guess) is False)

        # 뻔한 열쇠는 열쇠로 인정하지 않습니다.
        os.environ["HALMAE_DEV_KEY"] = "dev"
        check("열쇠가 'dev' 면 인정하지 않는다",
              analytics.dev_dashboard_allowed("dev") is False)

        os.environ["HALMAE_DEV_KEY"] = "short12"          # 7자
        check("열쇠가 8자 미만이면 인정하지 않는다",
              analytics.dev_dashboard_allowed("short12") is False)

        # 제대로 정한 열쇠는 정확히 맞을 때만
        os.environ["HALMAE_DEV_KEY"] = "halmae-qa-key-2026"
        check("열쇠가 맞으면 열린다",
              analytics.dev_dashboard_allowed("halmae-qa-key-2026") is True)
        check("열쇠가 틀리면 열리지 않는다",
              analytics.dev_dashboard_allowed("halmae-qa-key-2025") is False)
        check("?dev 가 없으면 열리지 않는다",
              analytics.dev_dashboard_allowed(None) is False)
    finally:
        os.environ.pop("HALMAE_DEV_KEY", None)
        if saved is not None:
            os.environ["HALMAE_DEV_KEY"] = saved


# ===============================================================
#  3. 개인정보 안내 · 동의
# ===============================================================
def check_privacy_notice() -> None:
    section("3. 개인정보 안내 — '할매에게 물어보기' 직전")

    notice = _source_of(_func("render_privacy_notice") or ast.Module())
    check("안내 함수가 있다", bool(notice))

    for word, label in (
        ("생년월일", "무엇을 받는지"),
        ("출생시간", "출생시간"),
        ("출생지역", "출생지역"),
        ("사주", "사주 계산에 쓴다"),
        ("별자리", "별자리 계산에 쓴다"),
        ("외부", "우리 밖으로 나간다"),
        ("전달될 수 있", "전달된다는 사실"),
        ("고민", "고민 내용도 전달된다"),
        ("남기지 않으마", "원문은 저장하지 않는다"),
    ):
        check(f"안내에 '{word}' 가 있다 ({label})", word in notice)

    check("안내가 길지 않다 (항목 5개 이하)", notice.count("<li>") <= 5,
          f"{notice.count('<li>')}줄")

    # 사용자 화면에는 기술 용어를 쓰지 않습니다.
    #     "무엇에 쓰이는지" 와 "밖으로 나갈 수 있다" 는 사실은 위에서 이미
    #     확인했습니다. 여기서는 그 사실을 '어떤 기술로' 하는지가 새어나오지
    #     않는지만 봅니다. 사용자에게 필요한 정보가 아니고, 서비스가 쓰는
    #     모델이 바뀌면 문구가 거짓이 되기 때문입니다.
    #     (개발자 화면 · 로그 · 주석에는 그대로 적어둡니다 — USE_DEV_MODE)
    consent_label = _consent_label_text()
    for term in ("Gemini", "API", "AI", "인공지능"):
        check(f"안내에 기술 용어 '{term}' 가 없다", term not in notice,
              _snippet(notice, term))
        check(f"동의 문구에 기술 용어 '{term}' 가 없다",
              term not in consent_label, _snippet(consent_label, term))

    render_input = _source_of(_func("render_input") or ast.Module())
    check("안내가 제출 버튼보다 먼저 나온다",
          0 < render_input.find("render_privacy_notice()")
          < render_input.find("할매에게 물어보기"))
    check("동의 체크박스가 있다", 'key="in_consent"' in render_input)
    check("동의 전에는 버튼이 눌리지 않는다",
          "disabled=not consent" in render_input)


def check_disclaimer() -> None:
    section("4. 결과 화면 고지 — 오락·자기성찰")

    text = _source_of(_func("render_disclaimer") or ast.Module())
    for word in ("오락", "자기성찰", "의료", "법률", "투자", "대신하지 않습니다"):
        check(f"고지에 '{word}' 가 있다", word in text)

    result = _source_of(_func("render_result") or ast.Module())
    check("결과 화면 맨 아래에 붙는다",
          result.rstrip().endswith("render_disclaimer()"))
    check("작게 보이도록 전용 스타일을 쓴다",
          ".halmae-disclaimer" in theme.build_css()
          and "0.72rem" in theme.build_css())


# ===============================================================
#  5. Funnel 중복 — rerun 만으로 쌓이면 안 됩니다
# ===============================================================
VIEW_EVENTS = {
    "landing_view", "step1_view", "step2_view", "step3_view",
    # 올해의 흐름은 Step3 과 카드 사이에 놓인 다리 구간입니다.
    # 화면 노출이므로 rerun 으로 두 번 세면 안 됩니다.
    "year_flow_view",
    "card_view", "feedback_view", "premium_view",
}
ACTION_EVENTS = {
    "start_click", "input_submit", "more_click", "action_click",
    "year_flow_click",
    # 올해의 카드 클릭은 예전부터 card_click 한 이름만 씁니다.
    # (year_card_click 을 새로 만들면 같은 행동이 두 이름으로 갈라집니다)
    "card_click", "premium_click",
    "purchase_intent_yes", "purchase_intent_no",
    "feedback_positive", "feedback_negative",
}


def _matches(pattern: str, names: set[str]) -> set[str]:
    return {name for name in names if fnmatch(name, pattern)}


def check_funnel_no_duplicates() -> None:
    section("5. Funnel 중복 — 화면 노출은 세션당 한 번")

    # --- (1) rerun 을 흉내내 실제로 세어봅니다 --------------------
    store = analytics.MemoryEventStore()
    analytics.set_store(store)
    logged: set[str] = set()

    def track(name: str) -> None:
        """app.track — 화면 노출용"""
        if not analytics.should_log(logged, name):
            return
        analytics.log_event("qa-session", name, concern="연애", model="qa")

    def track_action(name: str) -> None:
        """app.track_action — 버튼 클릭용"""
        logged.add(name)
        analytics.log_event("qa-session", name, concern="연애", model="qa")

    # 같은 화면을 30번 다시 그립니다 (Streamlit rerun)
    for _ in range(30):
        for name in sorted(VIEW_EVENTS):
            track(name)

    rows = store.read_all()
    counts: dict[str, int] = {}
    for row in rows:
        counts[row["event_name"]] = counts.get(row["event_name"], 0) + 1

    for name in sorted(VIEW_EVENTS):
        check(f"{name} 은 30번 다시 그려도 1줄", counts.get(name) == 1,
              f"{counts.get(name)}줄")

    # 버튼은 누를 때마다 남아야 합니다 (👍 → 👎 → 👍 처럼 마음이 바뀐 경우)
    before = len(store.read_all())
    track_action("feedback_positive")
    track_action("feedback_negative")
    track_action("feedback_positive")
    check("버튼 클릭은 누를 때마다 남는다",
          len(store.read_all()) - before == 3,
          f"{len(store.read_all()) - before}줄")

    # --- (2) app.py 가 두 함수를 제대로 갈라 쓰는지 ----------------
    view_calls: list[str] = []
    action_calls: list[str] = []
    for scope in [APP_TREE] + [
        n for n in ast.walk(APP_TREE) if isinstance(n, ast.FunctionDef)
    ]:
        for call in _calls(scope):
            name = _call_name(call)
            if not call.args:
                continue
            if name == "track":
                view_calls += _possible_strings(call.args[0], scope)
            elif name == "track_action":
                action_calls += _possible_strings(call.args[0], scope)
    view_calls = sorted(set(view_calls))
    action_calls = sorted(set(action_calls))

    bad_view = [
        p for p in view_calls
        if not _matches(p, VIEW_EVENTS) or _matches(p, ACTION_EVENTS)
    ]
    check("track() 에는 화면 노출 이벤트만 넘긴다", not bad_view, str(bad_view))

    bad_action = [
        p for p in action_calls
        if not _matches(p, ACTION_EVENTS) or _matches(p, VIEW_EVENTS)
    ]
    check("track_action() 에는 클릭 이벤트만 넘긴다", not bad_action,
          str(bad_action))

    covered_views: set[str] = set()
    for pattern in view_calls:
        covered_views |= _matches(pattern, VIEW_EVENTS)
    missing = VIEW_EVENTS - covered_views
    check(f"요청한 화면 노출 이벤트 {len(VIEW_EVENTS)}개가 모두 있다",
          not missing, str(missing))

    covered_actions: set[str] = set()
    for pattern in action_calls:
        covered_actions |= _matches(pattern, ACTION_EVENTS)
    missing_actions = ACTION_EVENTS - covered_actions
    check("요청한 클릭 이벤트가 모두 있다", not missing_actions,
          str(missing_actions))

    overlap = covered_views & covered_actions
    check("같은 이벤트를 양쪽에서 쓰지 않는다", not overlap, str(overlap))

    unknown = (covered_views | covered_actions) - set(analytics.EVENT_NAMES)
    check("모든 이벤트가 analytics 에 등록되어 있다", not unknown, str(unknown))

    # --- (3) 되돌아가도 다시 세지 않는지 ---------------------------
    reset = _source_of(_func("reset_conversation") or ast.Module())
    check("다시 물어봐도 logged_events 를 비우지 않는다",
          "logged_events" not in reset.replace(
              "# (logged_events 는 일부러 그대로 둡니다", ""))


# ===============================================================
#  6. Premium Fake-door — 결제는 어디에도 없어야 합니다
# ===============================================================
PAYMENT_TOKENS = (
    "stripe", "iamport", "portone", "tosspayments", "toss_payments",
    "paypal", "kakaopay", "naverpay", "payment_intent", "checkout_session",
    "card_number", "결제창", "결제하기", "카드번호",
)


def check_premium_fakedoor() -> None:
    section("6. Premium Fake-door — 실제 결제 없음")

    text = _source_of(_func("render_premium") or ast.Module())

    check("누르기 전에도 결제가 없다고 알린다",
          "베타 테스트로 실제 결제는 진행되지 않습니다" in text)
    check("누른 뒤에도 결제가 없다고 알린다",
          "실제 결제는 진행되지 않아요" in text)
    check("구매 의향을 묻는다", "이용해보고 싶으신가요?" in text)
    check("[이용해보고 싶어요] 버튼이 있다", '"이용해보고 싶어요"' in text)
    check("[아직은 아니에요] 버튼이 있다", '"아직은 아니에요"' in text)
    check("고른 뒤에도 결제가 없었다고 알린다",
          "결제는 이루어지지 않았습니다" in text)

    # 결제와 관련된 코드가 프로젝트 어디에도 없어야 합니다.
    found = []
    for path in sorted(ROOT.glob("*.py")):
        if path.name == Path(__file__).name:
            continue
        body = path.read_text(encoding="utf-8").lower()
        for token in PAYMENT_TOKENS:
            if token.lower() in body:
                found.append(f"{path.name}:{token}")
    check("결제 관련 코드가 한 줄도 없다", not found, str(found))

    # 바깥으로 나가는 요청은 Gemini · 지오코딩 · Supabase 뿐입니다.
    check("결제 라이브러리를 설치하지 않는다",
          not any(
              token in (ROOT / "requirements.txt").read_text(encoding="utf-8").lower()
              for token in ("stripe", "iamport", "portone", "paypal")
          ))


# ===============================================================
#  7. 모바일 — 좁은 화면 손질이 실제로 들어갔는지
# ===============================================================
def check_mobile() -> None:
    section("7. 모바일 — 좁은 화면에서 눌리지 않는지")

    css = theme.build_css()

    check("좁은 화면 손질(@media)이 있다", "@media" in css,
          f"{css.count('@media')}곳")
    check("휴대전화 폭(480px) 기준이 있다", "max-width: 480px" in css)
    check("아주 좁은 폭(360px) 기준도 있다", "max-width: 360px" in css)

    check("본문은 모바일 우선 폭(480px)이다",
          f"max-width: {theme.TOKENS['content_width']}" in css
          and theme.TOKENS["content_width"] == "480px")

    check("두 칸 배치가 좁아지면 아래로 쌓인다",
          "stColumn" in css and "min-width: 8.5rem" in css)
    check("버튼 글자가 잘리지 않고 줄이 바뀐다",
          "word-break: keep-all" in css and ".stButton > button p" in css)
    check("두 칸 안의 버튼은 한 단계 작게",
          'div[data-testid="stHorizontalBlock"] .stButton > button' in css)

    check("명식 값이 칸 밖으로 나가지 않는다", "nowrap" not in css)
    check("올해의 카드 제목이 좁은 화면에서 줄어든다",
          "font-size: 1.6rem" in css and "halmae-yearcard-title" in css)
    check("복사용 글상자에 좌우 스크롤이 생기지 않는다",
          "white-space: pre-wrap" in css)

    # 화면 밖으로 나가는 고정 폭이 남아 있지 않은지
    fixed = [
        line.strip() for line in css.splitlines()
        if "width:" in line
        and "px" in line
        and "max-width" not in line
        and "min-width" not in line
    ]
    too_wide = []
    for line in fixed:
        for token in line.replace(":", " ").replace(";", " ").split():
            if token.endswith("px"):
                try:
                    if float(token[:-2]) > 300:
                        too_wide.append(line)
                except ValueError:
                    pass
    check("300px 를 넘는 고정 폭이 없다", not too_wide, str(sorted(set(too_wide))))

    check("가로 스크롤을 만드는 layout='wide' 를 쓰지 않는다",
          'layout="centered"' in APP_SOURCE and 'layout="wide"' not in APP_SOURCE)


# ===============================================================
#  8. 오류 처리 — 빨간 화면으로 죽지 않는지
# ===============================================================
def _has_broad_except(node: ast.AST) -> bool:
    for handler in ast.walk(node):
        if isinstance(handler, ast.ExceptHandler):
            if handler.type is None:
                return True
            if isinstance(handler.type, ast.Name) and handler.type.id == "Exception":
                return True
    return False


def check_error_handling() -> None:
    section("8. 오류 처리 — 빨간 Streamlit 화면이 뜨지 않는지")

    for name, label in (
        ("compute_calendar", "달력 계산 실패"),
        ("compute_saju_info", "사주 계산 실패"),
        ("compute_astro_info", "출생지 검색 · 점성술 계산 실패"),
        ("ensure_reply", "Gemini 실패"),
        ("ensure_year_card", "올해의 카드 생성 실패"),
    ):
        node = _func(name)
        check(f"{label} 을 {name}() 이 붙잡는다",
              node is not None and _has_broad_except(node))

    # 마지막 안전망 — 화면 그리기 전체를 감쌉니다.
    top_try = [
        n for n in APP_TREE.body
        if isinstance(n, ast.Try)
        and any(
            _call_name(c) == "render_current_page" for c in _calls(n)
        )
    ]
    check("화면 그리기 전체를 감싼 마지막 안전망이 있다", bool(top_try))
    check("rerun · stop 은 오류로 삼키지 않는다",
          "CONTROL_FLOW_EXCEPTIONS" in APP_SOURCE
          and "RerunException" in APP_SOURCE)

    # 사용자에게는 짧은 안내 + 다시 하는 방법
    check("사용자에게 다시 시작하는 버튼을 준다",
          'key="fatal_restart"' in APP_SOURCE)
    check("단계 실패에도 다시 물어보기 버튼이 있다",
          'key=f"retry_{step}"' in APP_SOURCE)
    check("카드 실패에도 다시 뽑기 버튼이 있다",
          'key="year_card_retry"' in APP_SOURCE)

    # 개발 로그에는 진짜 원인을 남깁니다.
    check("실패 원인을 개발 로그에 남긴다",
          APP_SOURCE.count("log.exception(") >= 5,
          f"{APP_SOURCE.count('log.exception(')}곳")
    check("Supabase 실패를 세어둔다", "db.record_failure(" in APP_SOURCE)

    # 사용자 화면에 traceback 을 띄우는 명령이 없어야 합니다.
    check("st.exception() 을 쓰지 않는다", "st.exception(" not in APP_SOURCE)
    check("저장 실패가 앱을 멈추지 않는다 (log_event 가 예외를 삼킨다)",
          _has_broad_except(
              [
                  n for n in ast.walk(ast.parse(
                      (ROOT / "analytics.py").read_text(encoding="utf-8")))
                  if isinstance(n, ast.FunctionDef) and n.name == "log_event"
              ][0]
          ))

    # 사용자에게 그대로 보여주는 오류 문구에 개발자용 지시가 섞이지 않았는지.
    # (사용자는 pip 도, 환경변수 이름도 모릅니다)
    DEV_INSTRUCTIONS = ("pip install", "GEMINI_API_KEY", "SUPABASE_",
                        "환경변수", "Secrets", "config.py")
    for module, error_class in (
        ("astrology.py", "AstrologyError"),
        ("halmae_ai.py", "HalmaeError"),
        ("saju.py", "CalendarError"),
    ):
        source = (ROOT / module).read_text(encoding="utf-8")
        messages = []
        for node in ast.walk(ast.parse(source)):
            if (
                isinstance(node, ast.Call)
                and isinstance(node.func, ast.Name)
                and node.func.id == error_class
            ):
                messages.append(ast.get_source_segment(source, node) or "")
        joined = "\n".join(messages)
        leaked = [word for word in DEV_INSTRUCTIONS if word in joined]
        check(f"{module} 의 사용자 안내에 개발자용 지시가 없다", not leaked,
              str(leaked))


# ===============================================================
#  9. 개인정보 — 실제로 나가는 payload 를 들여다봅니다
# ===============================================================
#  Supabase 연결을 가짜로 바꿔치기해서, insert/upsert 에 실린 값만 받아옵니다.
#  (진짜 Supabase 에는 한 글자도 보내지 않습니다)
class _FakeTable:
    def __init__(self, name: str, sink: list):
        self.name, self.sink = name, sink

    def insert(self, payload):
        self.sink.append((self.name, "insert", payload))
        return self

    def upsert(self, payload, on_conflict=None):
        self.sink.append((self.name, "upsert", payload))
        return self

    def update(self, payload):
        self.sink.append((self.name, "update", payload))
        return self

    def select(self, *a, **k):
        return self

    def delete(self):
        return self

    def eq(self, *a, **k):
        return self

    def limit(self, *a, **k):
        return self

    def range(self, *a, **k):
        return self

    def order(self, *a, **k):
        return self

    def execute(self):
        class _Result:
            data = []
            count = 0
        return _Result()


class _FakeClient:
    def __init__(self):
        self.calls: list = []

    def table(self, name: str):
        return _FakeTable(name, self.calls)


# 화면에서 받는 값 — 이 중 어느 것도 저장소에 남으면 안 됩니다.
PII_PROBES = {
    "이름": "안혜진",
    "생년월일 원문": "1999-04-12",
    "출생시간": "08:49",
    "출생지역 원문": "서울특별시 강남구 역삼동",
    "위도": "37.4979",
    "경도": "127.0276",
    "추가 질문 원문": "지금 회사를 그만두고 이직해도 될까요",
    "Gemini 프롬프트": "CALCULATED_SAJU",
    "Gemini 응답 원문": "네 일간이 갑목이라 밀어붙이는 성정이란다",
}


def check_no_pii_stored() -> None:
    section("9. 개인정보 — 저장소에 원문이 남는지")

    check("이벤트 칸은 여섯 개뿐이다",
          analytics.FIELDNAMES == [
              "session_id", "timestamp", "event_name", "concern", "model", "step",
          ], str(analytics.FIELDNAMES))
    check("피드백 칸은 다섯 개뿐이다",
          analytics.FEEDBACK_FIELDNAMES == [
              "session_id", "timestamp", "feedback_result", "concern", "model",
          ], str(analytics.FEEDBACK_FIELDNAMES))

    # 실수로 개인정보를 넘겨도 칸 자체가 없어서 들어가지 못합니다.
    row = analytics._clean_row(
        session_id="qa", event_name="step1_view",
        concern="연애", model="qa", step=1,
    )
    check("이벤트 한 줄에 정해진 칸만 있다",
          set(row) == set(analytics.FIELDNAMES), str(sorted(row)))

    # --- 실제로 Supabase 로 나가는 payload 세 가지 -----------------
    fake = _FakeClient()
    original = db.get_client
    db.get_client = lambda: fake
    try:
        analytics.SupabaseEventStore(fallback=None).append({
            "session_id": "qa-session", "timestamp": "2026-08-19T00:00:00+00:00",
            "event_name": "card_view", "concern": "연애", "model": "gemini",
            "step": 3,
            # 아래는 있어서는 안 되는 값 — 일부러 섞어봅니다.
            **{f"몰래_{k}": v for k, v in PII_PROBES.items()},
        })

        analytics.SupabaseFeedbackStore(fallback=None).upsert({
            "session_id": "qa-session", "timestamp": "2026-08-19T00:00:00+00:00",
            "feedback_result": "positive", "concern": "연애", "model": "gemini",
            **{f"몰래_{k}": v for k, v in PII_PROBES.items()},
        })

        card = {
            "year": 2026, "title": "뿌리를 내리는 해", "keyword": "뿌리",
            "message": "올해는 넓히기보다 깊이 내리거라.",
            "basis": "일간이 굳세고 토 기운이 두터운 해라 그렇단다.",
            "actions": ["하나만 골라 끝까지 해보거라"],
            "caution": "급히 옮겨 심지 말거라.",
        }
        card_store.SupabaseCardStore(fallback=None).put(
            "a" * 64, card, 2026, "gemini-3.6-flash",
        )
    finally:
        db.get_client = original

    tables = {name: payload for name, _, payload in fake.calls}
    check("세 테이블에 모두 한 번씩 나갔다", len(fake.calls) == 3,
          str([f"{n}/{op}" for n, op, _ in fake.calls]))

    check("events 칸이 다섯 개뿐이다",
          set(tables.get("events", {})) == {
              "session_id", "event_name", "concern_category",
              "model_name", "current_step",
          }, str(sorted(tables.get("events", {}))))
    check("feedback 칸이 다섯 개뿐이다",
          set(tables.get("feedback", {})) == {
              "session_id", "feedback_result", "concern_category",
              "model_name", "updated_at",
          }, str(sorted(tables.get("feedback", {}))))
    check("cards 칸이 세 개뿐이다",
          set(tables.get("cards", {})) == {
              "stable_key", "card_year", "card_data",
          }, str(sorted(tables.get("cards", {}))))

    everything = json.dumps(fake.calls, ensure_ascii=False, default=str)
    for label, value in PII_PROBES.items():
        check(f"{label} 이 저장 payload 에 없다", value not in everything)

    # --- 카드 열쇠는 되돌릴 수 없는 요약값이어야 합니다 -------------
    from datetime import date, time

    answers = {
        "이름": "안혜진", "생년월일": date(1999, 4, 12), "출생시간": time(8, 49),
        "출생지역": "서울특별시 강남구 역삼동", "성별": "여성",
        "고민 분야": "취업/커리어", "추가 질문": "이직해도 될까요",
        "달력 유형": "양력", "출생시간 모름": False,
    }
    from saju import compute_saju

    saju = compute_saju(
        birth_date=answers["생년월일"], birth_time=answers["출생시간"],
        calendar_type="양력", leap_month=None, birth_place="서울",
    )
    astro = {"latitude": 37.4979, "longitude": 127.0276,
             "sun_sign": "Aries", "moon_sign": "Leo", "rising_sign": "Cancer"}

    key = card_store.build_card_key(answers, saju, astro, 2026)
    fingerprint = card_store.build_card_fingerprint(answers, saju, astro, 2026)

    check("열쇠가 SHA-256 요약값이다 (64자 16진수)",
          len(key) == 64 and all(c in "0123456789abcdef" for c in key))
    for label, value in ("이름", "안혜진"), ("추가 질문", "이직"), ("고민 분야", "커리어"):
        check(f"열쇠 재료(지문)에 {label} 이 없다", value not in fingerprint)
    check("지문에는 좌표가 들어 있다 (그래서 DB 에 저장하면 안 됩니다)",
          "lat=37.498" in fingerprint)
    check("app.py 는 지문을 저장하지 않는다",
          "save_card(key" in APP_SOURCE
          and "fingerprint" not in APP_SOURCE.split("card_store.save_card(")[1][:200])

    # --- 카드 글에서 이름을 지웁니다 -------------------------------
    dirty = dict(card, message="안혜진아, 올해는 뿌리를 내리거라.",
                 basis="혜진아 잘 듣거라. 안혜진의 올해는 다르단다.")
    cleaned = card_store.scrub_card(dirty, "안혜진")
    check("카드 글에 이름이 섞여도 저장 전에 지운다",
          "안혜진" not in json.dumps(cleaned, ensure_ascii=False)
          and "혜진" not in json.dumps(cleaned, ensure_ascii=False),
          cleaned["message"])
    # 이름만 지우고 조사를 남기면 "너아, 올해는…" 같은 문장이 됩니다.
    check("이름을 지운 자리에 조사가 남지 않는다",
          "너아" not in json.dumps(cleaned, ensure_ascii=False)
          and "너야" not in json.dumps(cleaned, ensure_ascii=False),
          cleaned["message"])

    # --- 개발 로그에 원문을 남기지 않는지 ---------------------------
    for module, forbidden in (
        ("app.py", ("answers[", "st.session_state.answers,")),
        ("halmae_ai.py", ("card.title", "card.keyword", "question)", "raw)")),
    ):
        body = (ROOT / module).read_text(encoding="utf-8")
        log_lines = [
            line.strip() for line in body.splitlines()
            if ("log.exception(" in line or "logger.info(" in line
                or "logger.warning(" in line or "log.warning(" in line)
        ]
        leaked = [
            line for line in log_lines
            for token in forbidden if token in line
        ]
        check(f"{module} 로그에 입력값·응답 원문이 없다", not leaked, str(leaked))


# ===============================================================
#  10. API 호출 보호 — rerun 으로 다시 부르지 않는지
# ===============================================================
def check_api_guards() -> None:
    section("10. API 호출 보호 — rerun 으로 Gemini 를 다시 부르지 않는지")

    reply = _func("ensure_reply")
    first = reply.body[1] if reply and len(reply.body) > 1 else None
    check("ensure_reply() 는 이미 받은 답이 있으면 곧바로 돌아선다",
          isinstance(first, ast.If)
          and any(isinstance(s, ast.Return) for s in first.body)
          and "replies" in _source_of(first),
          _source_of(first).splitlines()[0] if first else "-")

    card = _func("ensure_year_card")
    card_first = card.body[1] if card and len(card.body) > 1 else None
    check("ensure_year_card() 는 이미 뽑은 카드가 있으면 곧바로 돌아선다",
          isinstance(card_first, ast.If)
          and any(isinstance(s, ast.Return) for s in card_first.body)
          and "year_card" in _source_of(card_first))

    body = _source_of(card)
    check("카드는 저장소를 먼저 뒤진 뒤에만 Gemini 를 부른다",
          body.find("card_store.load_card(") < body.find("ask_year_card("))
    check("저장된 카드를 찾으면 Gemini 를 부르지 않고 돌아선다",
          "return                      # Gemini를 부르지 않습니다" in body)
    check("새로 만든 카드는 곧바로 저장해둔다", "card_store.save_card(" in body)

    # 올해의 흐름도 같은 방식으로 막혀 있는지
    flow = _func("ensure_year_flow")
    flow_first = flow.body[1] if flow and len(flow.body) > 1 else None
    check("ensure_year_flow() 는 이미 받은 흐름이 있으면 곧바로 돌아선다",
          isinstance(flow_first, ast.If)
          and any(isinstance(s, ast.Return) for s in flow_first.body)
          and "year_flow" in _source_of(flow_first))

    # 버튼을 두 번 눌러도 요청이 두 번 나가지 않는지 —
    # 누르면 표시(pending)만 세우고 화면을 다시 그려 버튼을 치웁니다.
    render_flow = _source_of(_func("render_year_flow"))
    check("흐름 버튼은 누르는 즉시 사라진다 (중복 클릭 방지)",
          "year_flow_pending = True" in render_flow
          and "st.rerun()" in render_flow)
    render_card = _source_of(_func("render_year_card"))
    check("카드 버튼도 누르는 즉시 사라진다 (중복 클릭 방지)",
          "year_card_pending = True" in render_card
          and "st.rerun()" in render_card)

    # Gemini 를 부르는 자리가 이 셋뿐인지
    ai_names = ("ask_halmae", "ask_year_card", "ask_year_flow")
    ai_calls = [
        f"app.py:{c.lineno}" for c in _calls(APP_TREE)
        if _call_name(c) in ai_names
    ]
    check("Gemini 를 부르는 곳이 세 군데뿐이다", len(ai_calls) == 3, str(ai_calls))

    inside = []
    for name in ("ensure_reply", "ensure_year_card", "ensure_year_flow"):
        node = _func(name)
        inside += [
            c.lineno for c in _calls(node)
            if _call_name(c) in ai_names
        ]
    check("세 호출 모두 '한 번만' 검사를 통과한 뒤에 있다", len(inside) == 3)

    # 올해의 카드 정책 — 흐름 답변이나 고민이 카드로 새어 들어가지 않는지
    card_body = _source_of(_func("ensure_year_card"))
    card_code = "\n".join(
        line for line in card_body.splitlines()
        if not line.strip().startswith("#")
    )
    for leak in ("year_flow", "daeun", "sewoon", "고민 분야", "추가 질문"):
        check(f"카드 준비 코드에 '{leak}' 이 들어가지 않는다",
              leak not in card_code)

    # 카드는 같은 사람·같은 해면 같은 열쇠 (고민이 달라도)
    from datetime import date, time

    from saju import compute_saju

    base = {
        "이름": "안혜진", "생년월일": date(1999, 4, 12), "출생시간": time(8, 49),
        "출생지역": "서울", "성별": "여성",
        "달력 유형": "양력", "출생시간 모름": False,
    }
    saju = compute_saju(
        birth_date=base["생년월일"], birth_time=base["출생시간"],
        calendar_type="양력", leap_month=None, birth_place="서울",
    )
    astro = {"latitude": 37.5665, "longitude": 126.978,
             "sun_sign": "Aries", "moon_sign": "Leo", "rising_sign": "Cancer"}

    key_a = card_store.build_card_key(
        {**base, "고민 분야": "연애", "추가 질문": "그 사람과 잘 될까요"},
        saju, astro, 2026,
    )
    key_b = card_store.build_card_key(
        {**base, "고민 분야": "취업/커리어", "추가 질문": "이직해도 될까요"},
        saju, astro, 2026,
    )
    check("고민이 달라도 같은 카드 열쇠가 나온다", key_a == key_b,
          f"{key_a[:12]} / {key_b[:12]}")

    key_next = card_store.build_card_key({**base, "고민 분야": "돈"},
                                         saju, astro, 2027)
    check("해가 바뀌면 다른 카드 열쇠가 나온다", key_a != key_next)


# ===============================================================
#  배포 설정 최종 확인
# ===============================================================
def check_deploy_settings() -> None:
    section("0. 배포 설정")

    check("Mock AI 가 꺼져 있다 (진짜 할매가 답합니다)",
          config.USE_MOCK_AI is False, f"USE_MOCK_AI={config.USE_MOCK_AI}")
    check("개발자 화면이 꺼져 있다",
          config.USE_DEV_MODE is False, f"USE_DEV_MODE={config.USE_DEV_MODE}")
    check("Gemini 열쇠가 있다", bool(config.get_secret("GEMINI_API_KEY")))
    check("Supabase 설정이 있다", db.is_configured())

    if config.DEV_MODE:
        print("  [ 참고 ] 지금은 가벼운 개발용 모델입니다 "
              f"({config.GEMINI_MODEL}). 실사용자 테스트 전에 "
              f'Secrets 에 HALMAE_DEV_MODE = "false" 를 넣어 '
              f"{config.PROD_MODEL} 로 올리세요.")

    if not config.get_secret("HALMAE_DEV_KEY"):
        print("  [ 참고 ] HALMAE_DEV_KEY 가 없습니다 — Funnel 지표 화면(?dev=)이 "
              "잠겨 있습니다. 지표를 보려면 Secrets 에 8자 이상으로 정하세요.")


# ===============================================================
def main() -> int:
    print("=" * 64)
    print(" 할매 · 실사용 직전 최종 QA (Gemini 호출 없음 · Supabase 쓰기 없음)")
    print("=" * 64)

    check_deploy_settings()
    check_feedback_ui()
    check_feedback_storage()
    check_dev_ui_hidden()
    check_dev_funnel_locked()
    check_privacy_notice()
    check_disclaimer()
    check_funnel_no_duplicates()
    check_premium_fakedoor()
    check_mobile()
    check_error_handling()
    check_no_pii_stored()
    check_api_guards()

    print()
    print("=" * 64)
    if _failures:
        print(f" 실패 {len(_failures)}건")
        for name in _failures:
            print(f"   - {name}")
        return 1
    print(" 전부 통과 — 실사용자에게 공유해도 되는 상태입니다")
    return 0


if __name__ == "__main__":
    sys.exit(main())
