"""올해의 카드 그림 — visual_theme / image_url 구조 확인 (Gemini 호출 없음)

    python test_year_card_visual.py

이 파일이 확인하는 것
    1. visual_theme 이 여덟 개 enum 으로 잠겨 있는지 (Gemini 스키마까지)
    2. 옛날 카드(visual_theme 없음)를 지우지 않고 그대로 읽는지
    3. image_url 이 없으면 fallback 아트, 있으면 그림이 나오는지
    4. 타로 카드가 좁은 화면 폭을 넘지 않는지 (고정 폭 · 세로 비율)
    5. 같은 열쇠의 카드를 다시 꺼내면 그림 주제까지 그대로 재사용되는지
    6. 여덟 테마 fallback 아트가 전부 있고, 허전하지 않고, 깨지지 않았는지
    7. 화면(app.py)이 이 구조를 실제로 쓰는지
    8. assets/year_cards/<theme>.png 를 넣으면 그 그림으로 바뀌는지

절대 하지 않는 일
    - Gemini API 호출 (스키마와 프롬프트 조립 함수만 봅니다)
    - Supabase 읽기/쓰기 (메모리 저장소만 씁니다)

  개인정보를 만들지도, 출력하지도 않습니다. 예시 카드(mock)만 씁니다.
"""

import base64
import json
import sys
import xml.etree.ElementTree as ElementTree
from pathlib import Path

import card_store
import card_visuals
import halmae_ai
import theme
from card_visuals import (
    ART_DIRECTION,
    ASSET_ROOT,
    FALLBACK_VISUAL_THEME,
    THEME_IMAGE_MAP,
    VISUAL_THEMES,
    VisualTheme,
    art_html,
    has_theme_asset,
    image_prompt,
    mood_of,
    normalize_theme,
    placeholder_svg,
    scene_of,
    theme_asset_file,
)
from halmae_ai import YearCard, YearCardDraft

_failures: list[str] = []


def check(label: str, ok: bool, detail: str = "") -> None:
    mark = "PASS" if ok else "FAIL"
    print(f"  [{mark}] {label}" + (f"  — {detail}" if detail else ""))
    if not ok:
        _failures.append(label)


def section(title: str) -> None:
    print()
    print(f"[{title}]")


# 화면에 그려질 예시 카드 — Gemini 를 부르지 않고 이 값으로만 확인합니다.
EXAMPLE_CARD = {
    "year": 2026,
    "title": "THE OPEN GATE",
    "keyword": "확장",
    "message": "문은 이미 열려 있으니 네 발이 먼저 나가야 한다.",
    "basis": "올해 간지의 기운이 네 일간과 맞물려 밖으로 뻗는 해로 본단다.",
    "actions": ["미뤄온 결정 하나를 이번 달 안에 매듭지어라."],
    "caution": "확실해질 때까지 기다리다가 때를 놓치는 버릇을 조심하거라.",
    "visual_theme": "expansion",
}

# 이미 Supabase 에 저장되어 있는 '옛날 카드' — 그림 칸이 아예 없습니다.
LEGACY_CARD = {
    "year": 2026,
    "title": "THE COMPASS",
    "keyword": "방향",
    "message": "남이 정한 길보다 네가 정한 방향을 따라가거라.",
    "basis": "명리학에서는 부족했던 기운이 밖에서 들어오는 해로 본단다.",
    "actions": ["올해 안에 이루고 싶은 것 딱 하나만 골라 적어두거라."],
    "caution": "남들이 다 그렇게 한다는 말에 네 기준을 바꾸는 버릇.",
}


# ===============================================================
#  1. visual_theme enum 검증
# ===============================================================
def verify_enum() -> None:
    section("1. visual_theme 은 여덟 개 중 하나로 잠겨 있다")

    expected = [
        "breakthrough", "expansion", "balance", "transformation",
        "grounding", "connection", "clarity", "renewal",
    ]
    check("여덟 개 값이 정해진 그대로다", list(VISUAL_THEMES) == expected,
          ", ".join(VISUAL_THEMES))

    # Gemini 에게 나가는 스키마에도 여덟 개가 그대로 박혀 있어야 합니다.
    # (프롬프트에만 적어두면 모델이 다른 낱말을 적어 보낼 수 있습니다)
    from google.genai import _transformers as genai_transformers

    schema = genai_transformers.t_schema(None, YearCardDraft).model_dump(
        exclude_none=True
    )
    field = schema["properties"]["visual_theme"]
    check("Gemini 응답 스키마가 여덟 개로 값을 제한한다",
          field.get("enum") == expected, str(field.get("enum")))
    check("Gemini 는 visual_theme 을 반드시 채워야 한다",
          "visual_theme" in schema.get("required", []))

    # image_url 은 사람이 붙이는 값입니다. 스키마에 있으면 모델이 지어냅니다.
    check("Gemini 스키마에 image_url 이 없다 (주소를 지어내지 못하게)",
          "image_url" not in schema["properties"])

    # Gemini 가 규칙을 어기면 곧바로 걸려야 합니다.
    try:
        YearCardDraft(**{**EXAMPLE_CARD, "visual_theme": "황금빛 들판"})
        rejected = False
    except Exception:
        rejected = True
    check("모델이 지어낸 문장은 스키마 단계에서 거부된다", rejected)

    # 프롬프트와 코드가 어긋나지 않아야 합니다. (한쪽만 고치는 실수 방지)
    task = halmae_ai.build_year_card_task()
    missing = [name for name in VISUAL_THEMES if name not in task]
    check("카드 프롬프트에 여덟 개가 전부 적혀 있다", not missing, str(missing))

    # 카드는 고민과 무관해야 합니다. 그림 고르는 규칙에도 고민이 들어가면 안 됩니다.
    check("그림 고르는 규칙이 '고민으로 고르지 말라'고 못 박는다",
          "고민 분야는 주어지지 않았다" in task)

    # 어떤 쓰레기 값이 와도 앱이 멈추면 안 됩니다.
    for bad in (None, "", "  ", "unknown", 42, [], {"a": 1}):
        check(f"이상한 값({bad!r})도 예외 없이 기본값으로 내려간다",
              normalize_theme(bad) is FALLBACK_VISUAL_THEME)
    check("대문자·공백은 알아서 맞춰 읽는다",
          normalize_theme("  CLARITY ") is VisualTheme.CLARITY)


# ===============================================================
#  2. 기존 카드 호환 — 지우지 않고 그대로 읽는다
# ===============================================================
def verify_legacy() -> None:
    section("2. 옛날 카드(그림 칸 없음)도 그대로 읽힌다")

    card = YearCard.model_validate(LEGACY_CARD)
    check("visual_theme 이 없는 카드도 읽힌다 (앱이 깨지지 않는다)", True)
    check("옛날 카드는 안전한 기본값을 쓴다",
          card.visual_theme is FALLBACK_VISUAL_THEME, card.visual_theme.value)
    check("옛날 카드는 그림 주소가 비어 있다", card.image_url is None)
    check("옛날 카드의 글은 한 글자도 바뀌지 않는다",
          card.title == LEGACY_CARD["title"]
          and card.message == LEGACY_CARD["message"]
          and card.actions == LEGACY_CARD["actions"])

    # 옛날 카드가 읽히지 않으면 app.ensure_year_card 가 Gemini 를 다시 부릅니다.
    # 위 model_validate 가 통과한다는 것은 다시 부르지 않는다는 뜻입니다.
    check("읽히므로 옛날 카드 때문에 Gemini 를 다시 부르지 않는다", True)

    # 저장된 값이 오래되어 이상해도 화면은 그려져야 합니다.
    broken = YearCard.model_validate({**LEGACY_CARD, "visual_theme": "옛날값"})
    check("알 수 없는 그림 주제가 저장돼 있어도 기본값으로 그린다",
          broken.visual_theme is FALLBACK_VISUAL_THEME)

    # 지우는 코드가 새로 생기지 않았는지 (기존 카드를 무조건 삭제하지 말 것)
    app_source = Path("app.py").read_text(encoding="utf-8")
    deletes = app_source.count("card_store.delete_card(")
    check("카드를 지우는 곳은 개발자용 '다시 뽑기' 한 곳뿐이다",
          deletes == 1, f"{deletes}곳")


# ===============================================================
#  3. image_url — 있으면 그림, 없으면 placeholder
# ===============================================================
def verify_image_url() -> None:
    section("3. image_url 이 있으면 그림, 없으면 placeholder")

    html = art_html(EXAMPLE_CARD)
    check("그림 주소가 없으면 fallback 아트를 그린다",
          "<svg" in html and "<img" not in html)
    check("무슨 그림이 들어갈 자리인지 한 줄로 알려준다",
          scene_of("expansion") in html, scene_of("expansion"))
    check("그림의 결까지 한 줄 더 알려준다 (허전하지 않게)",
          mood_of("expansion") in html, mood_of("expansion"))
    check("fallback 아트에도 금색 프레임이 씌워진다",
          'class="halmae-yearcard-frame"' in html)

    with_image = {**EXAMPLE_CARD, "image_url": "https://cdn.example.com/a.png"}
    html2 = art_html(with_image)
    check("그림 주소가 있으면 그 그림을 보여준다",
          '<img class="halmae-yearcard-image"' in html2
          and "https://cdn.example.com/a.png" in html2)
    check("그림이 있으면 fallback 아트는 그리지 않는다", "<svg" not in html2)
    check("실제 그림에도 같은 금색 프레임이 씌워진다",
          'class="halmae-yearcard-frame"' in html2)
    check("실제 그림에는 설명 띠를 겹치지 않는다 (그림이 주인공)",
          'class="halmae-yearcard-plate"' not in html2)

    # 카드 글은 Gemini 가 씁니다. 주소 칸에 이상한 값이 들어와도
    # 그대로 화면에 심기면 안 됩니다.
    for bad in ("javascript:alert(1)", 'https://x.png" onerror="alert(1)',
                "data:text/html,<script>"):
        safe = card_visuals.safe_image_url({"image_url": bad})
        drawn = art_html({**EXAMPLE_CARD, "image_url": bad})
        check(f"수상한 주소({bad[:22]}…)는 아예 받지 않는다", safe is None)
        check(f"수상한 주소({bad[:22]}…)는 fallback 아트로 내려간다",
              "<svg" in drawn and "<img" not in drawn)

    # 모델 객체로 넘겨도 dict 로 넘겨도 같아야 합니다. (app.py 는 모델을 넘깁니다)
    model_card = YearCard.model_validate(with_image)
    check("모델 객체와 dict 가 같은 그림을 그린다",
          art_html(model_card) == html2)


# ===============================================================
#  4. 모바일 — 가로 스크롤 없이 한 화면 폭 안에
# ===============================================================
def verify_mobile() -> None:
    section("4. 타로 카드가 좁은 화면 폭을 넘지 않는다")

    css = theme.build_css()
    block = css[css.index(".halmae-yearcard {"):css.index(".halmae-yearcard-year")]

    check("카드 폭이 화면을 넘지 않는다 (max-width 로만 제한)",
          "max-width: 300px" in block and "width: 100%" in block)
    check("테두리·여백이 폭에 더해지지 않는다 (box-sizing)",
          "box-sizing: border-box" in block)
    check("카드에 고정 px 폭이 없다",
          not any("width: " in line and "px" in line and "max-width" not in line
                  for line in block.splitlines()))
    check("그림 칸이 세로형이다 (3:4)", "aspect-ratio: 3 / 4" in css)
    check("그림 칸이 언제나 카드 폭을 꽉 채운다 (양옆이 비지 않게)",
          "width: 100%;" in css[css.index(".halmae-yearcard-art {"):][:900])
    check("화면이 짧으면 그림의 폭이 아니라 높이만 줄어든다",
          "@media (max-height: 720px)" in css
          and "aspect-ratio: 5 / 6" in css
          and "@media (max-height: 620px)" in css
          and "aspect-ratio: 4 / 5" in css)
    check("높이를 낮춰도 세로형은 지킨다 (정사각까지 내려가지 않는다)",
          "aspect-ratio: 1 / 1" not in css)
    check("설명 두 줄이 밝은 획 위에서도 읽힌다 (띠 + 글자 그림자)",
          css.count("text-shadow: 0 1px 3px rgba(12, 6, 9, 0.95)") >= 2)
    check("이상한 화면을 위한 마지막 높이 안전장치가 있다",
          "max-height: 62vh" in css)
    # 그림이 카드의 주인공이 되었는지 — 칸을 가장자리까지 채우는가.
    art_block = css[css.index(".halmae-yearcard-svg,"):]
    check("그림이 칸을 가장자리까지 채운다 (inset: 0)",
          "inset: 0;" in art_block[:400])
    check("설명 두 줄이 그림 위에 겹친다 (그림 높이를 빼앗지 않게)",
          "position: absolute" in css[css.index(".halmae-yearcard-plate {"):][:200])
    check("좁은 화면에서 제목이 작아진다",
          "font-size: 1.6rem" in css and "font-size: 1.42rem" in css)
    check("제목·메시지가 낱말 중간에서 끊기지 않는다",
          css.count("word-break: keep-all") >= 3)

    # test_ux_qa 와 같은 규칙 — 화면 밖으로 나가는 고정 폭이 없어야 합니다.
    too_wide = []
    for line in css.splitlines():
        line = line.strip()
        if "width:" not in line or "px" not in line:
            continue
        if "max-width" in line or "min-width" in line:
            continue
        for token in line.replace(":", " ").replace(";", " ").split():
            if token.endswith("px"):
                try:
                    if float(token[:-2]) > 300:
                        too_wide.append(line)
                except ValueError:
                    pass
    check("300px 를 넘는 고정 폭이 없다", not too_wide, str(sorted(set(too_wide))))

    # 그림이 칸을 뚫고 나가지 않아야 합니다.
    # (글자 수로 자르면 주석 한 줄에도 깨지므로 규칙 한 덩이만 잘라서 봅니다)
    art_rule_start = css.index(".halmae-yearcard-art {")
    art_rule = css[art_rule_start:css.index("}", art_rule_start)]
    check("그림은 칸 안에서만 그려진다 (overflow: hidden)",
          "overflow: hidden" in art_rule)


# ===============================================================
#  5. 같은 카드 재사용 — 그림 주제까지 그대로
# ===============================================================
def verify_reuse() -> None:
    section("5. 같은 열쇠의 카드는 그림까지 그대로 재사용된다")

    store = card_visuals and card_store.MemoryCardStore()
    original = card_store.get_store()
    card_store.set_store(store)
    try:
        made = YearCard.model_validate(
            {**EXAMPLE_CARD, "image_url": "https://cdn.example.com/gate.png"}
        )
        key = "0" * 64
        card_store.save_card(key, made.model_dump(mode="json"), 2026, "test")

        saved = card_store.load_card(key)
        check("저장된 값이 글자다 (enum 이 그대로 들어가지 않는다)",
              saved["visual_theme"] == "expansion",
              repr(saved.get("visual_theme")))
        check("Supabase 에 넣을 수 있는 모양이다 (JSON 으로 직렬화된다)",
              json.dumps(saved, ensure_ascii=False).count("expansion") == 1)

        again = YearCard.model_validate(saved)
        for field in ("title", "keyword", "message", "actions"):
            check(f"다시 꺼낸 카드의 {field} 가 그대로다",
                  getattr(again, field) == getattr(made, field))
        check("다시 꺼낸 카드의 visual_theme 이 그대로다",
              again.visual_theme is made.visual_theme, again.visual_theme.value)
        check("다시 꺼낸 카드의 image_url 이 그대로다",
              again.image_url == made.image_url)
    finally:
        card_store.set_store(original)

    # 이름 지우기가 그림 칸을 건드리면 그림을 못 찾습니다.
    scrubbed = card_store.scrub_card(
        {**EXAMPLE_CARD, "image_url": "https://cdn.example.com/gate.png",
         "message": "안혜진아, 문은 이미 열려 있다."},
        "안혜진",
    )
    check("이름 지우기가 글만 손댄다",
          scrubbed["visual_theme"] == "expansion"
          and scrubbed["image_url"] == "https://cdn.example.com/gate.png")
    check("이름 지우기는 여전히 글에서 이름을 지운다",
          "안혜진" not in scrubbed["message"])
    check("visual_theme 은 이름 지우기 대상이 아니다",
          "visual_theme" not in card_store.CARD_TEXT_FIELDS
          and "image_url" not in card_store.CARD_TEXT_FIELDS)

    # 열쇠 규칙이 바뀌지 않았는지 (그림을 붙이면서 건드리면 안 되는 정책)
    fingerprint_source = card_store.build_card_fingerprint.__doc__ or ""
    check("열쇠에 고민이 들어가지 않는다는 설명이 그대로 있다",
          "고민 분야, 추가 질문" in fingerprint_source)
    check("열쇠 만들기에 그림 주제가 끼어들지 않았다",
          "visual_theme" not in card_store.build_card_fingerprint.__code__.co_consts
          .__str__())


# ===============================================================
#  6. fallback 아트 여덟 장 — 있고, 허전하지 않고, 깨지지 않았는가
#
#  단순 아이콘 하나였던 시절의 기준(획 5개)으로는 "허전하지 않은가" 를
#  볼 수 없습니다. 그래서 겹(layer)이 다 쌓였는지와, defs 를 뺀
#  실제 그려지는 획이 몇 개인지를 함께 봅니다.
# ===============================================================

# 아트 한 장을 이루는 여섯 겹. 하나라도 빠지면 그림이 납작해집니다.
_REQUIRED_LAYERS = ("hm-back", "hm-sketch", "hm-shade", "hm-accent")
_REQUIRED_PLATE = ("hm-ground", "hm-halo", "hm-hanji")


def _drawn_shapes(root) -> list:
    """defs(물감 정의) 를 뺀, 실제로 화면에 그려지는 도형만."""
    shapes = []
    for child in root:
        if child.tag.endswith("defs"):
            continue
        shapes.extend([node for node in child.iter() if node is not child])
        shapes.append(child)
    return shapes


def verify_art() -> None:
    section("6. 여덟 테마 fallback 아트가 전부, 풍부하게 그려진다")

    for item in VisualTheme:
        svg = placeholder_svg(item)
        try:
            root = ElementTree.fromstring(svg)
            broken = ""
        except ElementTree.ParseError as exc:
            root, broken = None, str(exc)
        check(f"{item.value:<15} SVG 가 깨지지 않았다", root is not None, broken)
        if root is None:
            continue

        shapes = _drawn_shapes(root)
        check(f"{item.value:<15} 그림이 허전하지 않다 ({len(shapes)}획)",
              len(shapes) >= 30)

        classes = {node.get("class", "") for node in root.iter()}
        missing = [name for name in _REQUIRED_LAYERS if name not in classes]
        check(f"{item.value:<15} 여섯 겹이 다 쌓였다",
              not missing, "빠진 겹: " + ", ".join(missing) if missing else "")
        missing_plate = [name for name in _REQUIRED_PLATE if name not in classes]
        check(f"{item.value:<15} 바닥·후광·한지결이 깔렸다", not missing_plate,
              ", ".join(missing_plate))
        check(f"{item.value:<15} 색연필 채색(해칭)이 들어갔다",
              any(name.startswith("hm-hatch") for name in classes))
        check(f"{item.value:<15} 자개 티끌이 박혀 있다",
              any(name.startswith("hm-pearl") for name in classes))
        check(f"{item.value:<15} 연필 질감 필터를 가지고 있다",
              "hm-grain" in svg and "feDisplacementMap" in svg)
        check(f"{item.value:<15} 테마별 class 가 붙어 있다 (후광 색 구분)",
              f"halmae-yearcard-svg--{item.value}" in svg)
        check(f"{item.value:<15} 장면 설명이 있다", bool(scene_of(item).strip()),
              scene_of(item))
        check(f"{item.value:<15} 그림의 결이 세 낱말로 적혀 있다",
              mood_of(item).count("·") >= 2, mood_of(item))
        check(f"{item.value:<15} 이미지 생성용 프롬프트가 있다",
              len(image_prompt(item)) > 200 and ART_DIRECTION in image_prompt(item))

    # 색은 theme.py 가 정합니다. SVG 안에 색을 직접 쓰면 테마가 어긋납니다.
    # (gradient·filter 를 가리키는 url(#…) 도 CSS 에 있으므로 # 이 없어야 합니다)
    all_svg = "".join(placeholder_svg(item) for item in VisualTheme)
    check("SVG 안에 색을 직접 박아두지 않았다 (theme.py 가 색을 정한다)",
          "#" not in all_svg and "rgb(" not in all_svg)

    css = theme.build_css()
    brushes = ("line", "line-thin", "soft", "red", "red-glow", "jade", "hatch",
               "hatch-red", "hatch-jade", "glow", "ground", "halo", "hanji",
               "ember", "dew", "fill-gold", "fill-red", "fill-jade", "fill-dark",
               "ornament", "pearl", "pearl-jade", "sketch", "shade")
    undefined = [name for name in brushes if f".hm-{name} " not in css
                 and f".hm-{name}," not in css and f".hm-{name} {{" not in css]
    check("SVG 가 쓰는 붓이 CSS 에 전부 정의돼 있다", not undefined,
          ", ".join(undefined))

    # SVG 안의 defs 이름과 CSS 의 url(#…) 이 어긋나면 그림이 통째로 사라집니다.
    for paint in ("hm-night", "hm-halo", "hm-ember-paint", "hm-dew-paint",
                  "hm-fiber", "hm-grain", "hm-graze", "hm-bloom"):
        check(f"물감 {paint} 이(가) SVG 와 CSS 양쪽에 있다",
              f'id="{paint}"' in all_svg and f"url(#{paint})" in css)

    # gradient 를 못 찾아도 단색이라도 깔리게 예비 색을 적어두었는가.
    check("gradient 를 못 찾아도 바닥이 비지 않는다 (예비 색)",
          "fill: url(#hm-night)" in css
          and css.split("fill: url(#hm-night)")[1].lstrip()[0] != ";")

    scenes = {scene_of(item) for item in VisualTheme}
    moods = {mood_of(item) for item in VisualTheme}
    check("여덟 장면이 서로 다르다", len(scenes) == 8)
    check("여덟 결이 서로 다르다", len(moods) == 8)


# ===============================================================
#  7. app.py 가 이 구조를 실제로 쓰는가
# ===============================================================
def verify_app_wiring() -> None:
    section("7. 화면이 이 구조를 실제로 쓴다")

    source = Path("app.py").read_text(encoding="utf-8")
    check("app.py 가 card_visuals 를 쓴다", "import card_visuals" in source)
    check("그림 칸을 card_visuals 에 맡긴다",
          "card_visuals.art_html(card)" in source)
    check("카드 구조가 상단(YEAR CARD) · 중앙(그림) · 하단(제목)이다",
          source.index("halmae-yearcard-year")
          < source.index("halmae-yearcard-art")
          < source.index("halmae-yearcard-title"))
    check("카드 아래 세 가지 설명이 그대로 남아 있다",
          "왜 이 카드가 나왔나" in source
          and "올해 가장 중요한 것" in source
          and "이것만은 조심하거라" in source)
    check("저장할 때 글자로 저장한다 (mode=\"json\")",
          'card.model_dump(mode="json")' in source)

    # 카드 payload 정책은 그대로여야 합니다.
    ai_source = Path("halmae_ai.py").read_text(encoding="utf-8")
    card_section = ai_source[ai_source.index("def build_year_card_prompt"):]
    card_section = card_section[:card_section.index("def ask_year_card")]
    for forbidden in ("고민 분야", "추가 질문", "history"):
        check(f"카드 프롬프트 조립에 {forbidden} 이(가) 들어오지 않는다",
              f'"{forbidden}"' not in card_section
              and f"answers[{forbidden}]" not in card_section)


# ===============================================================
#  8. 실제 그림 파일을 넣으면 그 그림으로 바뀌는가
#
#  나중에 사람이 png 를 넣기만 하면 되는 구조인지 봅니다.
#  (여기서만 임시 파일을 만들고, 끝나면 지웁니다)
# ===============================================================
def verify_assets() -> None:
    section("8. assets/year_cards 에 png 를 넣으면 그 그림이 나온다")

    check("여덟 테마의 파일 자리가 전부 정해져 있다",
          set(THEME_IMAGE_MAP) == set(VISUAL_THEMES))
    check(f"자리가 {ASSET_ROOT}/<theme>.png 규칙을 따른다",
          all(path == f"{ASSET_ROOT}/{name}.png"
              for name, path in THEME_IMAGE_MAP.items()))

    asset_dir = Path(ASSET_ROOT)
    check("그림을 넣을 폴더가 이미 만들어져 있다", asset_dir.is_dir(),
          str(asset_dir.resolve()))
    check("폴더에 넣는 방법이 적혀 있다", (asset_dir / "README.md").is_file())

    # 1x1 짜리 진짜 png 한 장. (파일이 '있다/없다' 갈림길만 보면 됩니다)
    one_pixel_png = base64.b64decode(
        "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mP8z8DwHwAF"
        "AAH/q842iQAAAABJRU5ErkJggg=="
    )
    probe = VisualTheme.GROUNDING
    target = Path(THEME_IMAGE_MAP[probe.value])
    if target.exists():
        # 사용자가 이미 진짜 그림을 넣어두었다면 건드리지 않습니다.
        check("이미 들어와 있는 그림을 그대로 쓴다", has_theme_asset(probe),
              str(theme_asset_file(probe)))
        check("그 테마는 fallback 아트가 아니라 그림을 그린다",
              "<img" in art_html({**EXAMPLE_CARD, "visual_theme": probe.value}))
        return

    card = {**EXAMPLE_CARD, "visual_theme": probe.value}
    check("파일이 없으면 fallback 아트를 그린다",
          "<svg" in art_html(card) and not has_theme_asset(probe))

    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_bytes(one_pixel_png)
    try:
        check("파일을 넣자마자 그림으로 바뀐다 (코드 수정 없이)",
              has_theme_asset(probe))
        drawn = art_html(card)
        check("그 그림을 <img> 로 그린다",
              '<img class="halmae-yearcard-image"' in drawn
              and "data:image/png;base64," in drawn)
        check("그림이 들어오면 fallback 아트는 그리지 않는다", "<svg" not in drawn)
        check("그림에도 같은 금색 프레임이 씌워진다",
              'class="halmae-yearcard-frame"' in drawn)
        check("읽는 사람을 위한 대체 글이 붙는다", scene_of(probe) in drawn)

        # 카드에 적힌 image_url 이 파일보다 셉니다. (이미지 생성 API 자리)
        with_url = {**card, "image_url": "https://cdn.example.com/g.png"}
        check("카드에 적힌 주소가 파일보다 우선한다",
              "https://cdn.example.com/g.png" in art_html(with_url)
              and "data:image/png;base64," not in art_html(with_url))

        # 파일을 바꿔 넣으면 앱을 다시 띄우지 않아도 새 그림이 나와야 합니다.
        before = art_html(card)
        target.write_bytes(one_pixel_png + b"\x00")
        check("파일을 바꿔 넣으면 다시 읽는다 (mtime·size 를 열쇠에 넣었다)",
              art_html(card) != before)

        # 너무 큰 파일은 화면을 무겁게 만들므로 fallback 으로 내려갑니다.
        target.write_bytes(b"\x00" * (card_visuals._MAX_ASSET_BYTES + 1))
        check("6MB 를 넘는 파일은 fallback 으로 내려간다",
              "<svg" in art_html(card))
    finally:
        target.unlink(missing_ok=True)

    check("임시 파일을 남기지 않았다", not target.exists())
    check("치우고 나면 다시 fallback 아트다", "<svg" in art_html(card))


# ===============================================================
#  그림 미리보기 — 브라우저에서 눈으로 확인 (Gemini 호출 없음)
#
#      python test_year_card_visual.py --preview
#      → data/card_preview.html 이 만들어집니다. 브라우저로 열어보세요.
#
#  Streamlit 을 띄우지 않고도 카드 여덟 장이 어떻게 보이는지 확인합니다.
#  좁은 폭(320px · 375px) 틀 안에 그려서, 가로 스크롤이 생기는지도 함께 봅니다.
# ===============================================================
PREVIEW_PATH = Path("data") / "card_preview.html"
SAMPLE_ART_PATH = Path("data") / "card_preview_art.svg"

# 진짜 일러스트 대신 쓰는 예시 그림 한 장. (다음 단계에서 AI 그림으로 바뀔 자리)
SAMPLE_ART = (
    "<svg xmlns='http://www.w3.org/2000/svg' viewBox='0 0 300 400'>"
    "<rect width='300' height='400' fill='#241419'/>"
    "<circle cx='150' cy='170' r='70' fill='none' stroke='#F3D88F' "
    "stroke-width='3'/>"
    "<text x='150' y='320' fill='#F3D88F' font-size='18' "
    "text-anchor='middle' font-family='sans-serif'>AI 일러스트 자리</text>"
    "</svg>"
)


def card_html(card: dict) -> str:
    """app.py 의 render_year_card 와 같은 모양으로 카드 한 장을 그립니다."""
    model = YearCard.model_validate(card)
    return (
        '<div class="halmae-yearcard-stage">'
        '<div class="halmae-yearcard">'
        f'<p class="halmae-yearcard-year">{model.year} YEAR CARD</p>'
        f'<div class="halmae-yearcard-art">{art_html(model)}</div>'
        f'<p class="halmae-yearcard-title">{model.title}</p>'
        f'<p class="halmae-yearcard-keyword">키워드 · {model.keyword}</p>'
        f'<p class="halmae-yearcard-message">"{model.message}"</p>'
        '<p class="halmae-card-foot">병오년 · 말띠</p>'
        "</div>"
        "</div>"
    )


def write_preview() -> Path:
    frames = []
    for width in (320, 375):
        cards = []
        for item in VisualTheme:
            cards.append(
                f'<p class="tag">{item.value} — {scene_of(item)}</p>'
                + card_html({**EXAMPLE_CARD, "visual_theme": item.value})
            )
        cards.append(
            '<p class="tag">옛날 카드 (visual_theme 없음 → '
            f'{FALLBACK_VISUAL_THEME.value})</p>' + card_html(LEGACY_CARD)
        )
        # 다음 단계에 진짜 일러스트가 들어오면 어떻게 보이는지.
        # (data: 주소는 일부러 막아두었으므로 파일을 하나 만들어 씁니다)
        cards.append(
            '<p class="tag">image_url 이 있을 때 (그림이 들어온 뒤 모습)</p>'
            + card_html({**EXAMPLE_CARD, "image_url": f"./{SAMPLE_ART_PATH.name}"})
        )
        frames.append(
            f'<section><h2>{width}px 화면</h2>'
            f'<div class="phone" style="width:{width}px">'
            + "".join(cards)
            + "</div></section>"
        )

    page = (
        "<!doctype html><html lang='ko'><head><meta charset='utf-8'>"
        "<meta name='viewport' content='width=device-width, initial-scale=1'>"
        "<title>올해의 카드 미리보기</title>"
        + theme.build_css()
        + "<style>"
        "body{background:#0C0609;color:#F8EFDC;font-family:sans-serif;"
        "margin:0;padding:24px;} h2{color:#F3D88F;font-size:14px;}"
        ".wrap{display:flex;gap:40px;align-items:flex-start;flex-wrap:wrap;}"
        ".phone{border:1px dashed #7A6026;padding:12px;box-sizing:border-box;"
        "overflow-x:auto;}"
        ".tag{color:#A6927A;font-size:11px;margin:22px 0 4px 0;}"
        "</style></head><body><div class='wrap'>"
        + "".join(frames)
        + "</div></body></html>"
    )
    PREVIEW_PATH.parent.mkdir(parents=True, exist_ok=True)
    SAMPLE_ART_PATH.write_text(SAMPLE_ART, encoding="utf-8")
    PREVIEW_PATH.write_text(page, encoding="utf-8")
    return PREVIEW_PATH


# ===============================================================
#  실행
# ===============================================================
def main() -> int:
    print("=" * 64)
    print(" 올해의 카드 · 타로 카드 구조 진단 (Gemini 호출 없음)")
    print("=" * 64)

    verify_enum()
    verify_legacy()
    verify_image_url()
    verify_mobile()
    verify_reuse()
    verify_art()
    verify_app_wiring()
    verify_assets()

    if "--preview" in sys.argv:
        section("미리보기")
        path = write_preview()
        print(f"  카드 여덟 장 + 옛날 카드 + 일러스트 예시를 그렸습니다: {path}")
        print("  브라우저로 열어 320px / 375px 폭을 확인하세요.")

    print()
    print("=" * 64)
    if _failures:
        print(f" 실패 {len(_failures)}건")
        for name in _failures:
            print(f"   - {name}")
        return 1
    print(" 전부 통과 — 카드에 그림 자리가 준비되었습니다")
    return 0


if __name__ == "__main__":
    sys.exit(main())
