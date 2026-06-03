# KR 데이터 자체 수집 — 토큰/계정 준비 체크리스트

현재 `#kr-news` 는 `100m1s.com` 미러링(키움 + 네이버 카페 + Gemini 가공)이지만, 자체 수집으로 전환하기 위해 사전에 발급/확보해야 할 항목 정리. 다음 세션에서 실제 구현 시 참고용.

---

## 구현 현황 (2026-06-03 업데이트)

**`#kr-news` 4개 데이터 레이어 전부 자체생성 가능** — 100m1s 미러 없이 키움+네이버+Gemini 키로 생성. 100m1s 비공개 `news_pipeline`(대표 PC, 접근 불가)의 생성기들을 **출력물 역설계**로 trakit 에 재현.

### 레이어별 상태 (4 레이어 + OG)
| 레이어 | 파일 | 소스 | trakit 생성기 | 상태 |
|--------|------|------|--------------|------|
| **일봉(dailybars)** | `dailybars/{code}.json` | 키움 `ka10081` | `kr_data_build.py` | ✅ 풀빌드(456종목) |
| **랭킹** | `kiwoom/{date}.json` | 조건검색 `ka10171`+`ka10172` | `kr_ranking_capture.py` | ✅ 검증(장중 가동) |
| **뉴스 해석** | `interpreted/stock-{date}.json` | 네이버검색 + Gemini | `kr_interpret_build.py` | ✅ 코어 스키마 |
| **OG 이미지** | `og/news/stock/{date}/{code}.png` | dailybars + Pillow | `kr_og_build.py` | ✅ 디자인 재현 |
| 시세(현재가) | — | 키움 `ka10001` | `kiwoom_service` | ✅ 동작 |

### 비공개 `news_pipeline` 역설계 (핵심 발견)
100m1s 의 데이터 생성기는 공개 `100m1s-homepage` 가 아니라 **대표(박성진) 비공개 main 리포**(`/Users/seongjinpark/company/100m1s/.../scripts/news_pipeline/`)에 있음. 공개 리포엔 **결과물만** 커밋됨. 따라서 코드 복사가 아닌 **출력물 역설계**로 재현:

| 비공개 원본 | 산출물 | trakit 재현 |
|------------|--------|-------------|
| `build_daily.py` (뉴지) | interpreted/newzy | `kr_news_interpret.py`(`analyze_news_newzy`) |
| 영웅문 조건식 `500억이상` | kiwoom 랭킹 | `kr_ranking_capture.py` (우리 조건식 사용) |
| `generate_stock_og.py` | og/*.png | `kr_og_build.py` |
| (ka10081) | dailybars | `kr_data_build.py` |

⚠️ **스키마·디자인은 1:1 재현하나 값은 다를 수 있음** — 우리 프롬프트/조건식으로 생성하기 때문. 조건식 추가필터(등락률 등)·newzy 프롬프트는 비공개라 근사 재현.

### 키 / 설정 (`backend/.env`, gitignore — 전부 실제 호출로 검증)
- **키움(모의)**: `KIWOOM_APP_KEY/SECRET`, `KIWOOM_MODE=mock`. 실전/모의 **동일 도메인** `api.kiwoom.com`(투자구분은 appkey 에 포함, `mockapi…`는 8030 거부). 토큰 `POST /oauth2/token`(body `secretkey`, 응답 `token`/`expires_dt`), 디스크캐시 `data/.kiwoom_token.json`. ⚠️ 키움 `revoke_token`이 동일 토큰 폐기 → 스크레이퍼 셀프테스트 cleanup이 우리 캐시 무효화(8005) 가능, 캐시삭제 후 재발급 복구.
- **Gemini**: `GEMINI_API_KEY`(신형 `AQ.` 형식), `GEMINI_MODEL=gemini-2.5-flash`. generateContent 검증.
- **네이버 검색**: `NAVER_CLIENT_ID/SECRET`. 뉴스 검색(일 25,000회) 검증.
- config: `backend/config.py` 가 모두 env 에서 읽음. `.kiwoom_token.json` `.gitignore` 추가.

### 검증 근거 (요약)
- **일봉**: 우리 ka10081 = 100m1s dailybars **8거래일 전필드 원단위 100% 일치**(242040). 풀빌드 456종목 written=450/skip=6/실패 0.
- **랭킹**: 조건식 `500억이상` 등록→`ka10171` 인식→`ka10172` 실행 성공. 미러 6/1·6/2 거래대금과 우리 ka10081 9/9 일치(전일 이월 특성 규명). **조건은 실시간 전용 → 과거 소급 불가, 장중 캡처만 충실**(나무기술 6/1: EOD −24.7%인데 장중 +24.8% 스파이크에 매칭). 순수 거래대금≥500억(35~52종목) ≠ 미러(9~11) → 조건에 숨은 추가필터.
- **뉴스**: newzy 스키마 출력 2,546건 역설계 — `newzy_score = 5차원(freshness/persistence/magnitude/virality/tradability) 단순평균`(오차 0). 네이버검색→기사→Gemini 체인 검증(디앤디파마텍 호재 0.72).
- **OG**: 1200×630 카드(종목명·골드밑줄·현재가·등락률 pill·캔들/라인차트·날짜) Pillow 재현, 나무기술 카드 원본 대조 확인.

### 추가/변경된 파일
- `backend/services/kiwoom_service.py` — `get_token`, `get_daily_chart`(ka10081), `get_today_trade_amount`, 조건검색 `condition_list`/`condition_search`(ka10171/172 WebSocket)
- `backend/services/kr_news_interpret.py` — `analyze_news`(복사) + `analyze_news_newzy`(역설계)
- `backend/scripts/`: `kr_data_build.py`(일봉) · `kr_ranking_capture.py`(랭킹) · `kr_interpret_build.py`(뉴스) · `kr_og_build.py`(OG)
- `backend/config.py` — 키움·Gemini·네이버 설정
- `.gitignore` — `.kiwoom_token.json`; `frontend/public/kr-news/.gitignore` — `og/` 추가
- 검증보조: `100m1s-homepage/scripts/kiwoom-scraper/crosscheck_condition.py`(장중 교차검증)

### 가동 모델 — 서버 cron (KST, GitHub Actions 아님)
trakit 은 `kr-news/data`·`og` 가 gitignore(런타임 재생성)이라 100m1s 의 git-commit 방식 부적합 → **서버 cron**:
```cron
10 * * * 1-5   python3 scripts/kr_news_sync.py          # 미러 동기화(universe 공급) — 과도기
*/15 9-15 * * 1-5  python3 -m scripts.kr_ranking_capture # 랭킹 장중 캡처
20 16 * * 1-5  python3 -m scripts.kr_data_build          # 일봉(장 마감 후)
30 16 * * 1-5  python3 -m scripts.kr_interpret_build     # 뉴스 해석
40 16 * * 1-5  python3 -m scripts.kr_og_build            # OG 이미지
```

### 남은 한계 / 미완
- interpreted **코어 스키마만** 생성(themes_tree·status_badges·togusa_verdict·hugepark_grade·bullish_* 등은 100m1s 사설 파이프라인 의존 → 미생성, 렌더러 graceful degrade).
- 랭킹 조건의 **정확한 추가필터**(100m1s 영웅문)는 비공개 → 우리 조건식 결과와 다를 수 있음.
- 네이버 검색은 제목+요약+링크만(본문 X) — 본문 필요 시 §2-B/C(카페 OAuth/스크래핑).

---

## 1. 키움증권 (Kiwoom)

키움은 API 가 두 종류로 나뉘므로 어느 쪽을 쓸지 먼저 결정.

### (A) 키움 REST API "키움 OpenAPI" (신버전, 권장)
HTTP/REST 기반 — Linux/Mac/Docker 에서 사용 가능. trakit 의 KIS 와 동일한 패턴.

| 항목 | 발급처 | 비고 |
|------|--------|------|
| 키움증권 계좌 | 키움증권 영업점 또는 비대면 개설 | 모의투자 계좌도 별도 신청 (실전 키와 분리됨) |
| API 신청 | https://apiportal.kiwoom.com | "오픈API 사용 신청" → 약관 동의 → 승인까지 영업일 1~2일 |
| `app_key` | apiportal.kiwoom.com → 마이페이지 → 앱 관리 | 32자 영숫자 |
| `app_secret` | 동일 | 64자 영숫자 — 노출 금지 |
| `access_token` | OAuth POST 발급 | 만료 시간 있음 (KIS 처럼 디스크 캐시 권장) |
| 모의투자 도메인 / 실전 도메인 | 키움 API 문서 | URL 다름 (`mockapi.kiwoom.com` vs `api.kiwoom.com`) |

저장 위치 (예시):
```
backend/.env
  KIWOOM_APP_KEY=...
  KIWOOM_APP_SECRET=...
  KIWOOM_ACCOUNT_NO=...
  KIWOOM_MODE=real  # real | mock
backend/.kiwoom_token.json  (gitignore)
```

### (B) 키움 OpenAPI+ (구버전, ActiveX/Windows 전용)
HTS 기반 ActiveX — Windows VM 필수. 자동 매매 영역에서 많이 쓰이지만 데이터 수집만 위해서는 비효율.

| 항목 | 비고 |
|------|------|
| Windows 환경 (VM / 물리 PC) | macOS / Linux 직접 사용 불가 |
| 키움 HTS (영웅문) 설치 | 자동 로그인 설정 필요 |
| 공동인증서 (구 공인인증서) | HTS 로그인용, NPKI 폴더 복사 |
| 키움 OpenAPI+ 모듈 설치 | 키움 사이트에서 별도 다운로드 |
| Python 32-bit + PyQt5 | OpenAPI+ 는 32-bit ActiveX |

**판단 가이드**: 시세/차트/뉴스만 필요하면 (A) REST 로 충분. 호가창 실시간이나 자동 주문이 필요하면 (B) 고려.

---

## 2. 네이버 카페 (Naver Cafe)

네이버는 카페 본문 직접 조회용 공개 API 가 사실상 없음. 세 가지 트랙 중 선택:

### (A) NAVER 검색 API (가장 합법적, 데이터 제한)
카페/블로그/뉴스 검색 결과 (제목 + 요약 + 링크) 만 반환. 본문 X.

| 항목 | 발급처 | 비고 |
|------|--------|------|
| 네이버 개발자 계정 | https://developers.naver.com | 네이버 ID 로 로그인 |
| 애플리케이션 등록 | 개발자센터 → Application → 등록 | "검색" API 권한 추가 |
| `X-Naver-Client-Id` | 등록 후 발급 | 헤더용 |
| `X-Naver-Client-Secret` | 등록 후 발급 | 헤더용 |

쿼터: 일 25,000회 (검색 API 기본).

### (B) 카페 OAuth API (멤버 본인 카페 한정)
멤버로 가입된 카페에서 본인의 글/댓글만 조작 가능. 다른 사용자 글 읽기 X.

| 항목 | 비고 |
|------|------|
| 네이버 OAuth 2.0 Client ID/Secret | 개발자센터 등록 시 발급 |
| Redirect URI | OAuth 콜백용 (배포 도메인 등록 필수) |
| 카페 멤버십 | 대상 카페에 본인 계정이 가입돼 있어야 함 |
| `access_token` | OAuth 인가 코드 → 토큰 교환 |

### (C) 세션 쿠키 스크래핑 (비공식, ToS 위반 소지)
로그인 세션 쿠키로 실제 웹 페이지를 긁어옴. 자동화/대량 요청 시 차단/계정 정지 가능.

| 항목 | 비고 |
|------|------|
| 네이버 계정 (별도 봇 계정 권장) | 메인 계정 사용 시 정지 리스크 |
| `NID_AUT`, `NID_SES` 쿠키 | 브라우저 로그인 후 추출 — 만료 시 재로그인 자동화 필요 |
| User-Agent / Referer | 브라우저처럼 위장 |
| 캡차 대응 | 빈번 호출 시 캡차 페이지로 리다이렉트 |

**판단 가이드**: 제목/링크만으로 충분 → (A). 특정 카페 멤버로서 본인 글 관리 → (B). 외부 카페 본문 필요 → (C) (리스크 감수).

---

## 3. Gemini LLM (요약/가공)

100m1s 가 LLM 요약을 사용하므로 자체 구현 시 동등한 키 필요.

| 항목 | 발급처 | 비고 |
|------|--------|------|
| Google AI Studio 계정 | https://aistudio.google.com | 무료 quota 있음 |
| `GEMINI_API_KEY` | AI Studio → Get API key | 무료 tier: 분당 / 일당 호출 제한 |
| (선택) GCP Vertex AI | https://console.cloud.google.com | 프로덕션 / 높은 quota 필요 시 — 결제 계정 + IAM 서비스 계정 키 |

저장:
```
backend/.env
  GEMINI_API_KEY=...
```

---

## 4. 보안 / 운영 메모

- 모든 키는 `backend/.env` 또는 AWS Parameter Store (`/trakit/*`) 로 관리, gitignore 확인
- 토큰 만료 시각은 발급 응답의 명시 필드 사용 (KIS 의 `access_token_token_expired` 패턴)
- 디스크 캐시로 SMS 알림/재발급 최소화 (KIS 와 동일 전략)
- Naver 스크래핑 트랙은 차단 시 IP/계정 분리 전략 사전 검토
- 키움/네이버 모두 ToS 검토 — 데이터 재배포/대량 호출 시 제한 조항 확인

---

## 5. 작업 시작 시 우선순위

1. ✅ 키움 REST API 신청·발급 (모의 appkey 확보, `backend/.env`)
2. ✅ 네이버 검색 API 발급·설정 (`NAVER_CLIENT_ID/SECRET`, 검증 완료)
3. ✅ Gemini API 키 발급·설정 (`GEMINI_API_KEY`, gemini-2.5-flash, 검증 완료)
4. ✅ 키움 REST 시세/차트 → `services/kiwoom_service.py` (토큰·ka10081·조건검색)
5. ✅ 네이버 검색 + Gemini → `services/kr_news_interpret.py` (`analyze_news_newzy`)
6. ✅ 100m1s 미러를 자체 수집으로 대체 — **4레이어 전부 완료**: 일봉·랭킹·뉴스·OG (`kr_*_build.py` / `kr_ranking_capture.py`)

> 진척: 위 "구현 현황(2026-06-03)" 섹션 참조. **4개 레이어 전부 자체생성 가능** (잔여: interpreted 풍부 스키마·조건 추가필터는 비공개라 근사 재현).
