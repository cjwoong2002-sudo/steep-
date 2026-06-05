# AI 사업기회 도출 워크숍 — STEEP 시나리오 플래닝 Tool

LG그룹 임원 대상 / Kearney 퍼실리테이션 세미나용 도구.
조별 토론으로 도출한 내용을 **기입·정리·취합·시각화**까지 자동화하고,
Activity별 Output을 개인별로 추출합니다. 단일 HTML 파일, 빌드 불필요, 오프라인 동작.

## 🗺 워크숍 구조 (1일차)

```
세션 설정(조·성함·직책)
   → Activity I   STEEP 변수 수집 → AI 분류(⚡AI 연계 태그)
   → Activity II  변수 Scoring → 영향도·불확실성 매트릭스 → 2×2 시나리오 → 실습 시나리오 1개 선정
   → Activity III 비즈니스 캔버스 As-Is → To-Be (직책·시나리오 반영 AI 추천)
   → Activity IV  핵심 드라이버별 기회/위협 + Rationale → AI 핵심 시사점
   → Output       개인별 종합 리포트(PDF) / JSON / CSV / 매트릭스 PNG
```
- 각 단계 결과가 다음 단계로 **자동 주입**됩니다 (선정 시나리오 → 캔버스·기회/위협).
- 시간 지평은 **향후 5년**으로 고정.
- 2일차(본업 개선 Action Item, 인접영역 확장)는 네비게이션에 placeholder만 — 별도 구현 예정.

## ✨ 핵심 기능

| Activity | 내용 |
|----------|------|
| **세션 설정** | 조 선택(1~6조) · 성함 · **직책** 입력(모든 AI 프롬프트에 자동 주입) · **방 코드**. **조 공유 저장 & 연결을 해야 시작 가능** |
| **I. STEEP 변수** | 변수 기입 + **🤖 AI 변수 추천**(직책·사업 맥락 기반). Claude가 S·T·E·Ec·P 분류 + 근거, **AI는 전 영역 교차 외생변수**로 취급해 ⚡태그·연쇄효과 코멘트. **🔀 조 변수 AI 취합**으로 조원 전원 변수를 중복 제거→공통 목록 동기화(점수는 개인별) |
| **II. 핵심변수·시나리오** | 영향도·불확실성 Scoring → 2×2 매트릭스 → **🎙 조 토론 받아쓰기(STT)로 시나리오 자동 생성** → 2×2 시나리오 → **실습 시나리오 1개 선정** |
| **III. 비즈니스 캔버스** | 개인 As-Is/To-Be 9블록(와이드 레이아웃). 사이드패널에 선정 시나리오+드라이버. 블록별 🤖 AI 추천. **👥 조 전체 캔버스 실시간 보기** |
| **IV. 기회/위협** | Activity III 캔버스를 불러와 **블록을 클릭해 기회(초록)/위협(빨강) 지정** + Rationale. AI 핵심 시사점 생성 |
| **Output** | 종합 리포트(PDF) · JSON · CSV · 매트릭스 PNG. 진행자용 JSON 병합 |

### 📖 Kearney 예시(데모) 프리로드
세션 설정의 **`📖 Kearney 예시 불러오기`** 버튼으로 Activity I~IV가 완성된 데모 샘플(생활가전 사업의 AI 대응)을 한 번에 로드해 시연할 수 있습니다. (조·성함·직책은 유지)

- 실제 Kearney 샘플로 교체하려면 `index.html` 내 **`KEARNEY_EXAMPLE` 객체**(주석 `⬇⬇⬇ KEARNEY 예시 교체 지점 ⬇⬇⬇`)만 바꾸면 됩니다.
- 변수 `id`는 `ex1`~`ex8`처럼 고정해 두세요 — 기회/위협(`oppthreat.sel`/`rat`) 키가 이 id를 참조합니다.

### 👥 조별 실시간 공유 (Firebase) → [설정 가이드](docs/firebase-setup.md)
같은 **조 + 방 코드**를 선택한 참가자끼리 캔버스를 실시간 공유합니다.
- 진행자가 Firebase Realtime Database를 만들어 config를 `index.html`의 `FIREBASE_CONFIG`에 넣어 커밋하면, 참가자는 **조만 선택**하면 자동 연결됩니다. (헤더 **👥 조 공유**에서 화면 붙여넣기도 가능)
- **Activity III → 👥 조 전체 캔버스 보기**로 조원들의 As-Is/To-Be를 실시간 열람
- Firebase 미설정/오프라인이면 **개인 모드**로 정상 동작 (공유만 비활성)

- **STEEP** = Social(사회) · Technological(기술) · Economic(경제) · Environmental(환경) · Political(정치)
- **각 Activity 진입 시 Framework 설명 패널**(접이식)로 개념·해석 가이드 제공
- **📖 Kearney 예시 드로어**: 각 Activity 우측에 해당 단계의 데모 예시를 상시 표시(열기/닫기 가능)
- **🎙 토론 받아쓰기(STT)**: 브라우저 음성인식(Web Speech API, Chrome/Edge 권장)으로 조 토론을 실시간 받아써 시나리오 자동 생성. 조원에게 자막 실시간 공유 옵션

## 🚀 사용 방법

### 로컬
`index.html` 더블클릭 → 브라우저에서 실행.

### 세미나 (GitHub Pages)
1. 저장소 → Settings → Pages → Branch `claude/eloquent-rubin-iTxUl`(또는 main) `/root`
2. 접속 URL: `https://cjwoong2002-sudo.github.io/steep-/` (모바일 포함)
3. 각자 진행 → **Output**에서 개인 결과 다운로드
4. (선택) 진행자가 **Output → JSON 병합**으로 조원 변수 취합

> 데이터는 각 브라우저 localStorage에 **자동 저장**됩니다.

## 🤖 Claude API 키 설정
1. 우측 상단 **⚙ AI 설정**
2. Anthropic 키(`sk-ant-...`) 입력 + 모델 선택 (기본 `claude-sonnet-4-6`)
3. AI 분류 / 평가 제안 / 시나리오 초안 / 캔버스 추천 / 기회·위협 시사점 동작

- 키는 **해당 브라우저에만** 저장, Anthropic API 직접 호출에만 사용. 세션 JSON에 미포함.
- 키 없이도 규칙 기반 분류 + 수동 입력으로 전체 진행 가능.

## 📤 산출물
- `*_session_*.json` : 전체 세션(재불러오기/병합용)
- `*_variables_*.csv` : 변수·분류·AI연계·연쇄효과·점수
- `*_matrix_*.png` : 영향도–불확실성 매트릭스
- 종합 리포트 : 브라우저 인쇄 → PDF (프로필·STEEP·시나리오·캔버스·기회/위협 포함)

## 🛠 기술 메모
- 단일 파일(`index.html`), 외부 의존성 없음, localStorage 자동 저장
- AI 호출: `https://api.anthropic.com/v1/messages` (브라우저 직접 호출, `anthropic-dangerous-direct-browser-access` 헤더)
