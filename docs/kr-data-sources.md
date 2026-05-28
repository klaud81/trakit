# KR 데이터 자체 수집 — 토큰/계정 준비 체크리스트

현재 `#kr-news` 는 `100m1s.com` 미러링(키움 + 네이버 카페 + Gemini 가공)이지만, 자체 수집으로 전환하기 위해 사전에 발급/확보해야 할 항목 정리. 다음 세션에서 실제 구현 시 참고용.

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

1. 키움 REST API 신청 (승인 1~2 영업일 — 가장 오래 걸림, 먼저 신청)
2. 네이버 개발자센터에서 검색 API 발급 (즉시)
3. Gemini API 키 발급 (즉시)
4. 키움 REST 로 시세/차트 동작 확인 → `services/kiwoom_service.py` 신규 작성
5. 검색 API + 선택적 (C) 트랙으로 `services/naver_cafe_service.py` 작성
6. `kr_news_sync.py` 의 100m1s 미러를 자체 수집으로 단계적 대체
