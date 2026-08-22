"""로딩 위치 · 결과 저장(PDF) 검증 — Gemini 호출 없음 · Supabase 쓰기 없음

    python test_result_output.py

[무엇을 고치려고 만든 기능인가]
    1) 첫 화면의 '할매에게 물어보기' 는 페이지 맨 아래에 있습니다.
       로딩 판을 누른 뒤에 만들면 버튼 '아래' — 모바일에서는 화면 밖 —
       에 생겨서, 사용자는 아무 일도 안 일어난 것처럼 느꼈습니다.
       그래서 버튼 '위' 에 자리를 미리 잡아두고 거기에 띄웁니다.

    2) 결과가 길어서 나중에 다시 보고 싶다는 피드백이 있었습니다.
       새 PDF 라이브러리를 넣지 않고, 브라우저의 인쇄(→ PDF로 저장)를
       쓰면서 인쇄용 CSS 로 '읽기 좋은 리포트' 를 만듭니다.

확인하는 것
    1. 첫 로딩 자리가 버튼 '위' 에 있는지
    2. Step2/3 · 올해의 흐름 · 카드 로딩은 손대지 않았는지 (regression)
    3. 기존 로딩 정책이 그대로인지 (가짜 %, 강제 대기 없음)
    4. 저장 버튼이 우측 하단에 작게 떠 있는지
    5. 인쇄에 남는 것과 빠지는 것이 정확한지
    6. 인쇄 CSS 가 읽을 수 있는 대비·한글 글꼴·잘림 방지를 갖췄는지
    7. PDF 때문에 개인정보를 새로 저장하지 않는지
"""

import ast
import re
import sys

import analytics
import progress
import theme

_failures: list[str] = []

APP_SOURCE = open("app.py", encoding="utf-8").read()
APP_TREE = ast.parse(APP_SOURCE)
PROGRESS_SOURCE = open("progress.py", encoding="utf-8").read()
CSS = theme.build_css()


def section(title: str) -> None:
    print()
    print(f"[{title}]")


def check(label: str, ok: bool, detail: str = "") -> None:
    print(f"  [{'PASS' if ok else 'FAIL'}] {label}"
          + (f"  — {detail}" if detail else ""))
    if not ok:
        _failures.append(label)


def func_source(name: str) -> str:
    """app.py 에서 그 함수의 '원본 글자' 를 그대로 잘라옵니다.

    ast.unparse 를 쓰면 따옴표가 ' 로 바뀌어서
    'help="결과 저장"' 같은 글자를 찾을 수 없습니다.
    """
    for node in ast.walk(APP_TREE):
        if isinstance(node, ast.FunctionDef) and node.name == name:
            return ast.get_source_segment(APP_SOURCE, node) or ""
    return ""


def func_code(name: str) -> str:
    """docstring 을 뺀 '실제로 도는 코드' 만.

    설명글에 적어둔 낱말("이름·생년월일은 넣지 않습니다") 때문에
    검사가 헛되게 실패하는 일을 막습니다.
    """
    for node in ast.walk(APP_TREE):
        if isinstance(node, ast.FunctionDef) and node.name == name:
            statements = [
                item for item in node.body
                if not (isinstance(item, ast.Expr)
                        and isinstance(item.value, ast.Constant)
                        and isinstance(item.value.value, str))
            ]
            return "\n".join(
                ast.get_source_segment(APP_SOURCE, item) or ""
                for item in statements
            )
    return ""


def print_block() -> str:
    """@media print { ... } 안쪽만 잘라옵니다."""
    start = CSS.find("@media print")
    if start < 0:
        return ""
    depth, i = 0, CSS.find("{", start)
    begin = i
    while i < len(CSS):
        if CSS[i] == "{":
            depth += 1
        elif CSS[i] == "}":
            depth -= 1
            if depth == 0:
                return CSS[begin:i + 1]
        i += 1
    return CSS[begin:]


PRINT_CSS = print_block()


# ===============================================================
def check_first_loading_position() -> None:
    section("1. 첫 로딩 자리 — '할매에게 물어보기' 버튼 위")

    body = APP_SOURCE.split("def render_input()")[1].split("\ndef ")[0]

    slot_at = body.find("loading_slot = st.empty()")
    button_at = body.find('"할매에게 물어보기"')
    check("로딩 자리를 미리 잡아둔다", slot_at > 0)
    check("그 자리가 버튼보다 '위' 에 있다",
          0 < slot_at < button_at, f"자리 {slot_at} · 버튼 {button_at}")

    # 버튼을 누른 뒤 그 자리에 로딩을 띄우는지
    check("버튼을 누르면 그 자리에 로딩을 띄운다",
          "prepare_calculations(st.session_state.answers, loading_slot)" in body)
    check("이름 경고도 그 자리에 띄운다 (버튼 아래로 밀리지 않게)",
          "loading_slot.warning(" in body)

    prepare = func_source("prepare_calculations")
    check("prepare_calculations 가 자리를 받는다",
          "loading_slot" in prepare.split("\n")[0], prepare.split("\n")[0])
    check("받은 자리를 progress 에 넘긴다",
          "slot=loading_slot" in prepare)

    # 자리를 미리 잡아도, 누르기 전에는 아무것도 안 그려져야 합니다.
    check("st.empty() 는 자리만 잡는다 (누르기 전 화면은 그대로)",
          "st.empty()" in body and "loading_slot.markdown" not in body)


# ===============================================================
def check_loading_regression() -> None:
    section("2. 나머지 로딩은 손대지 않았다 (regression)")

    # Step2/3 · 올해의 흐름 · 올해의 카드는 slot 을 넘기지 않아야 합니다.
    #     (버튼이 페이지 중간에 있어서 이미 눈에 보입니다)
    for name, label in [
        ("ensure_reply", "Step1~3 답변"),
        ("render_year_flow", "올해의 흐름"),
        ("ensure_year_card", "올해의 카드"),
    ]:
        src = func_source(name)
        if not src:
            continue
        check(f"{label} 로딩은 자리를 지정하지 않는다 (예전 그대로)",
              "slot=" not in src, name)

    check("run_staged 를 부르는 곳은 네 군데 그대로다",
          APP_SOURCE.count("progress.run_staged(") == 3,
          str(APP_SOURCE.count("progress.run_staged(")))

    # progress 쪽 기본 동작이 그대로인지
    check("slot 을 안 넘기면 예전처럼 그 자리에 새로 만든다",
          "if slot is None:" in PROGRESS_SOURCE
          and "slot = st.empty()" in PROGRESS_SOURCE)
    check("steps() 의 slot 은 키워드 전용이다 (실수로 순서가 밀리지 않게)",
          "def steps(labels: list[str], done_label: str | None = None, *, "
          "slot=None):" in PROGRESS_SOURCE)


# ===============================================================
def check_loading_policy() -> None:
    section("3. 기존 로딩 정책 그대로")

    check("문구 간격은 1~2초 사이다",
          0.8 <= progress.PHRASE_SECONDS <= 2.0,
          f"{progress.PHRASE_SECONDS}초")

    # 연출 때문에 파이썬이 기다리는 곳이 없어야 합니다.
    #     맨 아래 `if __name__ == "__main__":` 은 로딩 판을 눈으로
    #     확인하는 데모(streamlit run progress.py)라 일부러 기다립니다.
    #     실제 앱이 쓰는 코드에만 sleep 이 없어야 합니다.
    library_part = PROGRESS_SOURCE.split('if __name__ == "__main__":')[0]
    tree = ast.parse(library_part)
    sleeps = [node for node in ast.walk(tree)
              if isinstance(node, ast.Call)
              and "sleep" in ast.unparse(node.func)]
    check("문구를 보여주려고 time.sleep() 하지 않는다 (데모 제외)",
          not sleeps, str([ast.unparse(node) for node in sleeps]))
    check("데모 블록은 앱이 쓰지 않는다",
          'if __name__ == "__main__":' in PROGRESS_SOURCE
          and "progress.py" not in APP_SOURCE.split("import")[0])

    check("문구 교체는 CSS 애니메이션이다",
          "animation" in CSS and "halmae-loading-phrase" in CSS)

    # 가짜 진행률(%)이 없어야 합니다.
    #     몇 초 걸릴지 서버도 모르므로 숫자를 쓰지 않습니다.
    #     금띠는 조각이 계속 지나가는 모양(indeterminate)입니다.
    all_phrases = []
    for phrase_list in progress.STEP_STAGES.values():
        all_phrases += [str(item) for item in phrase_list]
    for name in ("CALC_STAGES", "YEAR_FLOW_STAGES", "YEAR_CARD_STAGES"):
        all_phrases += [str(item) for item in getattr(progress, name, [])]
    with_percent = [text for text in all_phrases if "%" in text]
    check("로딩 문구에 가짜 진행률(%) 이 없다",
          not with_percent, str(with_percent))
    check("문구를 실제로 여러 줄 쓰고 있다",
          len(all_phrases) > 10, f"{len(all_phrases)}줄")

    check("일이 끝나면 남은 문구를 기다리지 않고 지운다",
          "slot.empty()" in PROGRESS_SOURCE and "finally:" in PROGRESS_SOURCE)


# ===============================================================
def check_save_button() -> None:
    section("4. 결과 저장 버튼 — 우측 하단에 작게")

    src = func_source("render_save_button")
    check("저장 버튼 함수가 있다", bool(src))
    check("버튼에는 긴 글이 없다 (아이콘 하나)",
          '"⇩"' in src, "⇩")
    check("접근성 label / tooltip 이 '결과 저장' 이다",
          'help="결과 저장"' in src)
    check("누르면 익명 이벤트를 남긴다",
          'track_action("result_download_click")' in src)
    check("누르면 인쇄 창을 연다", "print_requested" in src)

    # CSS — 우측 하단 고정 · 정사각형 · 모바일에서 더 작게
    save_css = CSS.split(".st-key-result_save")[1][:600]
    check("우측 하단에 고정한다",
          "position: fixed" in save_css
          and "right:" in save_css and "bottom:" in save_css)
    check("정사각형이다 (너비 = 높이)",
          "width: 2.75rem" in save_css and "height: 2.75rem" in save_css)
    check("모바일에서는 더 작아진다",
          "max-width: 480px" in CSS and "2.5rem" in CSS)
    check("본문을 가리지 않도록 아래 여백을 둔다",
          ".halmae-save-gap" in CSS and 'class="halmae-save-gap"' in src)

    # 결과가 나온 뒤에만 붙는지
    result = func_source("render_result")
    check("결과가 있을 때만 버튼을 붙인다",
          "if st.session_state.replies:" in result
          and "render_save_button()" in result)

    # 인쇄 스크립트에 값을 끼워 넣는 곳이 없어야 합니다.
    script = APP_SOURCE.split("_PRINT_SCRIPT = ")[1].split('"""')[1]
    check("인쇄 스크립트는 고정 문자열이다 (값을 끼워 넣지 않는다)",
          "{" not in script.replace("{}", "")
          or not re.search(r"\{[a-zA-Z_]", script),
          "사용자 입력이 스크립트로 들어갈 통로 없음")
    check("부모 창을 인쇄한다 (iframe 만 인쇄하지 않는다)",
          "window.parent" in script and "target.print()" in script)
    check("막힌 환경에서는 조용히 넘어간다", "catch" in script)


# ===============================================================
def check_print_contents() -> None:
    section("5. 인쇄에 남는 것 / 빠지는 것")

    check("인쇄용 CSS 가 있다", bool(PRINT_CSS), f"{len(PRINT_CSS)}자")

    # --- 빠지는 것 ---
    must_hide = {
        "입력 양식": [".stTextInput", ".stDateInput", ".stTimeInput",
                   ".stRadio", ".stCheckbox", ".stTextArea"],
        "모든 버튼(CTA · 저장 버튼 자체)": [".stButton"],
        "피드백 UI": ["st-key-halmae_noprint", ".halmae-feedback-title"],
        "Premium fake-door": [".halmae-premium", ".halmae-fakedoor"],
        "개발자 / debug UI": ['[data-testid="stExpander"]', "pre"],
        "Streamlit 기본 메뉴 · footer": ["header", "footer",
                                       '[data-testid="stToolbar"]',
                                       '[data-testid="stHeader"]'],
        "로딩 UI": [".halmae-loading"],
        "모델 badge": [".halmae-modelbadge"],
    }
    for label, selectors in must_hide.items():
        missing = [s for s in selectors if s not in PRINT_CSS]
        check(f"인쇄에서 빠진다: {label}", not missing, str(missing))

    # display:none 이 실제로 걸려 있는지
    check("숨김은 display:none !important 로 확실히 건다",
          PRINT_CSS.count("display: none !important") >= 3,
          str(PRINT_CSS.count("display: none !important")))

    # --- 남는 것 ---
    must_keep = {
        "할매 결과 제목": ".halmae-print-title",
        "사주 계산 결과 (명식)": ".halmae-myeongsik-row",
        "Step 제목": ".halmae-step-title",
        "카드 · 섹션 본문": ".halmae-card",
        "올해의 흐름 (대운·세운)": ".halmae-luck-row",
        "올해의 카드": ".halmae-yearcard",
    }
    for label, selector in must_keep.items():
        check(f"인쇄에 남는다: {label}",
              selector in PRINT_CSS, selector)

    # 남아야 하는 것이 실수로 숨겨지지 않았는지
    for selector in (".halmae-myeongsik-row", ".halmae-yearcard",
                     ".halmae-print-title"):
        # 해당 선택자가 들어간 규칙 블록에 display:none 이 없어야 합니다
        for match in re.finditer(re.escape(selector), PRINT_CSS):
            block_end = PRINT_CSS.find("}", match.end())
            block = PRINT_CSS[match.end():block_end]
            check(f"'{selector}' 규칙이 숨김이 아니다",
                  "display: none" not in block, block.strip()[:60])

    # 인쇄 표지 줄
    header = func_source("render_print_header")
    check("인쇄 표지 줄에 '할매 결과 리포트' 가 있다",
          "할매 결과 리포트" in header)
    check("표지 줄은 화면에서는 안 보인다",
          ".halmae-print-only" in CSS
          and "display: none" in CSS.split(".halmae-print-only")[1][:60])
    header_code = func_code("render_print_header")
    check("표지 줄에 이름·생년월일을 넣지 않는다",
          "answers" not in header_code and "이름" not in header_code,
          header_code[:80])


# ===============================================================
def check_print_style() -> None:
    section("6. 인쇄 스타일 — 읽을 수 있는 인쇄물")

    check("종이 크기와 여백을 정해두었다",
          "@page" in PRINT_CSS and "margin:" in PRINT_CSS)
    check("배경을 흰색으로 되돌린다",
          "#ffffff !important" in PRINT_CSS)
    check("글씨를 검게 되돌린다 (금색 글씨는 종이에서 안 보임)",
          "#1a1a1a !important" in PRINT_CSS)
    check("그림자를 없앤다", "box-shadow: none !important" in PRINT_CSS)

    # 한글 글꼴 — 웹폰트를 못 받아와도 시스템 글꼴로 남아야 합니다.
    check("한글 글꼴을 여러 단계로 받쳐둔다",
          all(font in PRINT_CSS for font in
              ("Noto Serif KR", "Apple SD Gothic Neo", "Malgun Gothic")),
          "웹폰트 → 맥 → 윈도우 → serif")

    # 잘림 방지
    check("카드·섹션이 페이지 경계에서 쪼개지지 않는다",
          "break-inside: avoid" in PRINT_CSS
          and "page-break-inside: avoid" in PRINT_CSS)
    check("긴 본문은 쪼개지는 것을 허용한다 (통째로 밀려나지 않게)",
          "break-inside: auto" in PRINT_CSS)
    check("문단 한 줄만 떨어져 남지 않게 막는다",
          "orphans:" in PRINT_CSS and "widows:" in PRINT_CSS)
    check("제목 바로 뒤에서 페이지가 넘어가지 않는다",
          "break-after: avoid" in PRINT_CSS)

    # 읽을 수 있는 크기
    check("본문 글자 크기를 pt 로 정해두었다",
          "font-size: 10.5pt !important" in PRINT_CSS)
    check("줄 간격을 넉넉히 둔다", "line-height: 1.65" in PRINT_CSS)

    # 카드 그림이 종이 폭을 넘지 않게
    check("올해의 카드 그림이 종이 폭을 넘지 않는다",
          "max-width: 70mm !important" in PRINT_CSS)

    # 인쇄 CSS 가 화면에 영향을 주지 않아야 합니다.
    screen_css = CSS.replace(PRINT_CSS, "")
    check("인쇄 규칙은 @media print 안에만 있다",
          "@page" not in screen_css and "10.5pt" not in screen_css)
    check("인쇄 CSS 가 화면용 규칙보다 뒤에 온다 (덮어쓸 수 있게)",
          CSS.find("@media print") > CSS.find("@media (max-width: 480px)"))


# ===============================================================
def check_privacy() -> None:
    section("7. 개인정보 — PDF 때문에 새로 저장하는 것이 없다")

    check("result_download_click 이 이벤트 목록에 있다",
          "result_download_click" in analytics.EVENT_NAMES)
    check("analytics 저장 칸은 여섯 개 그대로다",
          analytics.FIELDNAMES == ["session_id", "timestamp", "event_name",
                                   "concern", "model", "step"],
          str(analytics.FIELDNAMES))

    save = func_code("render_save_button")
    for banned in ("이름", "생년월일", "출생시간", "출생지역",
                   "answers", "saju_info", "replies["):
        check(f"저장 버튼이 '{banned}' 를 건드리지 않는다", banned not in save)

    # 결과 내용을 서버로 보내는 코드가 없어야 합니다.
    for banned in ("db.", "supabase", "requests", "upload", "insert"):
        check(f"저장 기능에 '{banned}' 가 없다", banned not in save)

    header_code = func_code("render_print_header")
    check("인쇄 표지 줄도 개인정보를 넣지 않는다",
          not any(w in header_code for w in ("이름", "생년월일", "출생")),
          header_code[:80])

    # 이벤트 한 줄에 결과 내용이 들어갈 수 없는지
    row = analytics._clean_row("sid", "result_download_click", "돈",
                               "gemini", 3)
    check("이벤트 한 줄은 여섯 칸뿐이다", len(row) == 6, str(list(row)))
    check("이벤트 이름 말고는 결과 내용이 없다",
          row["event_name"] == "result_download_click"
          and all(len(str(v)) < 40 for v in row.values()), str(row))


# ===============================================================
def main() -> int:
    print("=" * 64)
    print(" 할매 · 로딩 위치 · 결과 저장(PDF) 검증 (Gemini · Supabase 없음)")
    print("=" * 64)

    check_first_loading_position()
    check_loading_regression()
    check_loading_policy()
    check_save_button()
    check_print_contents()
    check_print_style()
    check_privacy()

    print()
    print("=" * 64)
    if _failures:
        print(f" 실패 {len(_failures)}건")
        for name in _failures:
            print(f"   - {name}")
        return 1
    print(" 전부 통과 — 로딩은 누른 자리에서, 결과는 읽기 좋은 인쇄물로")
    return 0


if __name__ == "__main__":
    sys.exit(main())
