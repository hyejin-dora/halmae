# HALMAE · 할매

AI 기반 사주·점성술 자기성찰 서비스 MVP

생년월일과 출생 정보로 사주 네 기둥과 태양궁·달궁·상승궁을 계산하고,
그 값을 근거로 "할매" 캐릭터가 3단계에 걸쳐 조언을 건넵니다.

> 엔터테인먼트와 자기성찰을 위한 서비스입니다.
> 건강·투자·법률 판단을 대신하지 않습니다.

---

## Tech Stack

- **Python** 3.11+
- **Streamlit** — 화면
- **Gemini API** (`google-genai`) — 할매의 3단계 답변과 올해의 카드
- **Supabase** (PostgreSQL) — 행동 로그 · 피드백 · 올해의 카드 저장
- **Korean Lunar Calendar** — 음력/양력 변환과 간지 계산
- **Swiss Ephemeris** (`pyswisseph`) — 태양·달 위치와 Ascendant

---

## Run locally

```bash
pip install -r requirements.txt
streamlit run app.py
```

환경변수는 `.env.example` 을 복사해서 채우면 됩니다.

```bash
cp .env.example .env
set -a && source .env && set +a
streamlit run app.py
```

`.env` 는 `.gitignore` 에 있어 커밋되지 않습니다.

---

## 필요한 환경변수 / Secrets

이름만 적습니다. **실제 값은 이 파일이나 코드에 절대 적지 마세요.**

| 이름 | 필수 | 설명 |
|---|---|---|
| `GEMINI_API_KEY` | ✅ | Gemini API 열쇠. Mock 모드에서는 없어도 앱이 뜹니다 |
| `SUPABASE_URL` | ✅ | Supabase 프로젝트 주소 |
| `SUPABASE_SECRET_KEY` | ✅ | Supabase 서버용 비밀 열쇠(service_role) |
| `HALMAE_DEV_KEY` | 권장 | 개발자 지표 화면 `?dev=...` 의 암호. 없으면 `?dev=1` 로 누구나 열림 |
| `HALMAE_USE_MOCK_AI` | 선택 | `"false"` 면 실제 Gemini 호출 |
| `HALMAE_DEV_MODE` | 선택 | `"false"` 면 품질용 모델 사용 |
| `HALMAE_STORAGE` | 선택 | `auto`(기본) / `supabase` / `local` |

`SUPABASE_PUBLISHABLE_KEY`(anon key)는 이 앱에서 **쓰지 않습니다.**
저장은 모두 서버 쪽에서 일어나기 때문입니다.

읽는 순서는 `config.get_secret()` 한 곳에 있습니다.

```
1순위  os.environ    내 컴퓨터 · Codespaces
2순위  st.secrets    Streamlit Community Cloud
```

덕분에 개발용 코드와 배포용 코드를 따로 만들 필요가 없습니다.

---

## Deploy · Streamlit Community Cloud

1. GitHub 저장소에 push
2. [share.streamlit.io](https://share.streamlit.io) → **New app** → 저장소 선택
3. **Main file path** 를 `app.py` 로 지정
4. **Advanced settings → Secrets** 에 위 표의 값을 TOML 형식으로 입력

```toml
GEMINI_API_KEY = "..."
SUPABASE_URL = "https://xxxxxxxx.supabase.co"
SUPABASE_SECRET_KEY = "..."
HALMAE_DEV_KEY = "..."
```

5. **Deploy**

배포 직후에는 Mock AI 모드로 뜹니다 (Gemini 무료 quota를 쓰지 않습니다).
실제 Gemini로 바꿀 때는 Secrets 에 `HALMAE_USE_MOCK_AI = "false"` 한 줄을 추가하고
저장하면 됩니다. **코드를 고치거나 다시 push 할 필요가 없습니다.**

---

## 설정 한 곳에서 관리하기

모델과 Mock 여부는 `config.py` 에만 있습니다. 다른 파일에는 설정값을 적지 않습니다.

```bash
python config.py        # 지금 설정과 열쇠가 제대로 읽히는지 확인 (값은 안 찍힘)
python db.py            # Supabase 연결 확인
python test_supabase.py # events · feedback · cards 저장 테스트 (끝나면 자동 정리)
python analytics.py     # 터미널에서 Funnel 지표 보기
```

---

## 개인정보

다음 값은 로컬 파일에도, Supabase 에도 **저장하지 않습니다.**

이름 · 생년월일 원문 · 출생시간 · 출생지역 원문 · 위도/경도 ·
추가 질문 원문 · Gemini 프롬프트 원문 · Gemini 답변 원문

저장되는 것은 익명 세션 ID, 이벤트 이름, 고민 분야(미리 정해진 선택지),
모델 이름, 단계 번호뿐입니다.
올해의 카드는 되돌릴 수 없는 SHA-256 열쇠와 카드 결과만 저장합니다.

---

## 파일 구조

```
app.py            화면 · 흐름 (Streamlit entrypoint)
config.py         ★ 설정과 열쇠 읽기 (get_secret)
db.py             Supabase 연결
analytics.py      행동 로그 · 피드백 저장과 Funnel 집계
card_store.py     올해의 카드 저장 · stable key
halmae_ai.py      할매 캐릭터 · 프롬프트 · Gemini 호출
mock_ai.py        Gemini 없이 쓰는 가짜 응답
saju.py           사주 네 기둥 · 오행 · 간지
astrology.py      태양궁 · 달궁 · 상승궁
theme.py          디자인 시스템 (색 · 글꼴 · CSS)
test_supabase.py  Supabase 연결 테스트
```
