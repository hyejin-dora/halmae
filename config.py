"""할매 앱 설정 — 개발 중에 바꾸는 값은 여기 한 곳에 모여 있습니다.

바꿀 일이 있으면 이 파일의 ★ 설정 표시가 붙은 줄만 보면 됩니다.
다른 파일에는 설정값을 적지 않습니다.

    python config.py        # 지금 설정과 열쇠가 제대로 읽히는지 확인

[열쇠(API Key)는 코드에 적지 않습니다]
    내 컴퓨터·Codespaces 에서는 환경변수로,
    Streamlit Community Cloud 에서는 Secrets 로 넣습니다.
    코드는 get_secret() 하나로 두 곳을 모두 읽으므로 파일을 두 벌 만들 필요가 없습니다.
"""

import os


# ===============================================================
#  0. 설정값·열쇠 읽기 (환경변수 → Streamlit Secrets)
# ===============================================================
def _from_streamlit_secrets(name: str) -> str:
    """Streamlit Community Cloud 의 Settings → Secrets 에 넣은 값을 읽습니다.

    Secrets 를 넣지 않았거나 Streamlit 밖(터미널)에서 돌릴 때는
    오류를 내지 않고 빈 글자를 돌려줍니다.
    """
    try:
        import streamlit as st

        return str(st.secrets.get(name, "") or "").strip()
    except Exception:
        return ""


def get_secret(name: str, default: str = "") -> str:
    """설정값 하나를 읽습니다. 앱 전체가 쓰는 단 하나의 창구입니다.

        get_secret("SUPABASE_URL")
        get_secret("GEMINI_API_KEY")

    찾는 순서
        1순위  os.environ          내 컴퓨터 · Codespaces · `export ...`
        2순위  st.secrets          Streamlit Community Cloud 의 Secrets
        3순위  default             둘 다 없을 때 쓸 값

    이 함수 덕분에 배포용 코드와 개발용 코드를 따로 만들지 않아도 됩니다.
    """
    value = (os.environ.get(name) or "").strip()
    if value:
        return value
    value = _from_streamlit_secrets(name)
    return value if value else default


def get_flag(name: str, default: bool) -> bool:
    """켜기/끄기 설정을 읽습니다. 값이 없으면 default 를 그대로 씁니다.

    코드를 고치지 않고 잠깐 다르게 돌려보고 싶을 때:
        HALMAE_USE_MOCK_AI=0 streamlit run app.py

    Streamlit Cloud 에서는 Secrets 에 이렇게 넣으면 같은 효과가 납니다:
        HALMAE_USE_MOCK_AI = "false"

    끄는 값으로 인정하는 글자: 0 · false · no · off · (빈 값)
    """
    raw = get_secret(name, "")
    if not raw:
        return default
    return raw.strip().lower() not in ("0", "false", "no", "off")


# 예전 이름 — 다른 파일에서 쓰고 있어서 남겨둡니다.
_env_flag = get_flag


# ===============================================================
#  ★ 설정 1 · Mock AI 모드 ★           ← 배포 후 여기 한 줄만 바꾸면 됩니다
#
#      True   →  Gemini API 를 절대 호출하지 않고, 미리 만들어둔
#                가짜 응답(mock_ai.py)으로 화면과 흐름만 테스트합니다.
#                무료 quota 를 하나도 쓰지 않습니다.
#
#      False  →  실제 Gemini API 를 호출합니다. (실사용자 테스트용)
#
#  [진짜 할매로 바꾸는 두 가지 방법]
#    ① 코드를 고치지 않고 (추천 · 배포된 앱에서 바로)
#         Streamlit Cloud → Settings → Secrets 에 한 줄 추가
#         HALMAE_USE_MOCK_AI = "false"
#         저장하면 앱이 알아서 다시 켜집니다. git push 가 필요 없습니다.
#
#    ② 코드로 아예 고정하고 싶으면
#         아래 MOCK_AI_DEFAULT 를 False 로 바꾸고 push
#
#  내 컴퓨터에서 잠깐만: HALMAE_USE_MOCK_AI=0 streamlit run app.py
# ===============================================================
MOCK_AI_DEFAULT = True                 # ★ 여기 (배포 초기에는 True 로 둡니다)

USE_MOCK_AI = get_flag("HALMAE_USE_MOCK_AI", MOCK_AI_DEFAULT)


# ===============================================================
#  ★ 설정 2 · 어떤 Gemini 모델을 쓸지 ★
#
#      True   →  개발·기능 테스트  (gemini-3.5-flash-lite · quota 절약)
#      False  →  최종 답변 품질 테스트 (gemini-3.6-flash)
#
#  USE_MOCK_AI = True 이면 API 를 아예 부르지 않으므로 이 값은 쓰이지 않습니다.
#  Secrets 로 바꾸려면: HALMAE_DEV_MODE = "false"
# ===============================================================
DEV_MODE_DEFAULT = True                # ★ 여기

DEV_MODE = get_flag("HALMAE_DEV_MODE", DEV_MODE_DEFAULT)

# 모델 이름은 이 두 줄이 전부입니다. 다른 파일에는 모델 이름을 적지 않습니다.
DEV_MODEL = "gemini-3.5-flash-lite"    # 개발·기능 테스트용
PROD_MODEL = "gemini-3.6-flash"        # 최종 답변 품질 테스트용

# 코드를 고치지 않고 딱 한 번 다른 모델을 써보고 싶을 때 쓰는 비상구.
# (비어 있으면 위 DEV_MODE 규칙을 그대로 따릅니다.)
MODEL_OVERRIDE = get_secret("GEMINI_MODEL", "")

# 지금 실제로 쓰는 모델 이름. halmae_ai.py 가 이 값을 가져다 씁니다.
GEMINI_MODEL = MODEL_OVERRIDE or (DEV_MODEL if DEV_MODE else PROD_MODEL)


# ---------------------------------------------------------------
#  배포하기 전 확인표
#      HALMAE_USE_MOCK_AI = "false"   ← 진짜 할매가 답하도록 (Secrets)
#      HALMAE_DEV_MODE    = "false"   ← 좋은 모델로 (Secrets)
#      GEMINI_API_KEY                 ← Gemini 열쇠 (Secrets)
#      SUPABASE_URL · SUPABASE_SECRET_KEY  ← 저장소 (Secrets)
#      HALMAE_DEV_KEY                 ← 개발자 Funnel 화면 잠그기 (Secrets)
# ---------------------------------------------------------------


# ---------------------------------------------------------------
#  터미널에서 지금 설정 확인하기
#      python config.py
#  (열쇠 값은 찍지 않고 '있다/없다'만 보여줍니다.)
# ---------------------------------------------------------------
if __name__ == "__main__":
    print("[할매 설정]")
    print(f"  USE_MOCK_AI    {USE_MOCK_AI}    "
          f"{'(Gemini 호출 안 함)' if USE_MOCK_AI else '(실제 Gemini 호출)'}")
    print(f"  DEV_MODE       {DEV_MODE}")
    print(f"  GEMINI_MODEL   {GEMINI_MODEL}")
    print()
    print("[열쇠 · 값은 보여주지 않습니다]")
    for key_name in ("GEMINI_API_KEY", "SUPABASE_URL", "SUPABASE_SECRET_KEY"):
        found = get_secret(key_name)
        where = ""
        if found:
            where = "환경변수" if os.environ.get(key_name) else "st.secrets"
        print(f"  {key_name:<22} {'✅ 있음 · ' + where if found else '❌ 없음'}")
