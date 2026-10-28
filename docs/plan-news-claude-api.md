# 플랜: 뉴스 예측 LLM 을 Claude API 로 전환 (`NEWS_LLM=claude_api`)

- 작성: 2026-10-28
- 대상: `backend/services/nasdaq_news.py` (뉴스 bias 분석), `backend/config.py`, 배포 서버 `ncp-kr2-aiharness-01`
- 상태: **구현 완료(브랜치 `feat/news-claude-api`)** · 서버 키 주입·배포 대기

## 1. 배경 / 문제

현재 뉴스 bias 분석(`_gemini_day_analysis` → `_llm_json`)은 두 백엔드 중 하나로 돈다.

| 백엔드 | 방식 | 문제 |
|---|---|---|
| `gemini` (기본) | Gemini REST | 무료 쿼터 소진(429) 시 분석 실패 → bias 0.0 강등 |
| `claude_cli` | 로컬 `claude -p` 서브프로세스 | **배포 서버(도커)에 claude CLI·로그인 없음** → 서버에서 사용 불가. 로컬 Mac 전용 |

사전장 예측(`predict_and_record(use_news=True)` → `day_bias(D-1)`)은 서버 스케줄러에서 돈다. 그래서 서버에서도 쓸 수 있는 Claude 경로가 필요하다.

추가로 발견한 버그: `analyze_day` 가 `NEWS_LLM` 과 무관하게 `GEMINI_API_KEY` 가 없으면 "API 키 없음"으로 분석을 건너뛴다. `claude_cli`/`claude_api` 만 쓰는 환경에서도 Gemini 키가 필요한 상태.

## 2. 목표 / 비목표

**목표**
- `NEWS_LLM=claude_api` 백엔드 추가: 공식 `anthropic` Python SDK 로 Messages API 직접 호출
- 서버 도커 컨테이너에서 동작 (CLI 의존 제거)
- JSON 파싱 안정화: 코드펜스 제거 같은 후처리 대신 **구조화 출력**(`messages.parse` + Pydantic 스키마) 사용
- API 키는 **llmvault 에 원본 보관**, 서버에는 `.env` 로만 주입 (git 미포함)

**비목표**
- 프롬프트 내용·bias 산출 로직 변경 (A/B 기준 유지)
- 기존 `gemini`, `claude_cli` 백엔드 제거 (폴백으로 유지)
- 과거 뉴스 캐시(`data/news_bias_cache/*.json`) 재빌드. 필요하면 별도 작업

## 3. API 키 발급 · 보관 · 주입

1. **발급 (사용자)**: Anthropic Console → API Keys → `trakit-news` 이름으로 생성. 가능하면 전용 Workspace 를 만들어 월 한도(spend limit)를 건다.
2. **llmvault 보관 (사용자)**: 값이 클라이언트 측 E2E 암호화라서 에이전트 토큰으로는 쓸 수 없다. 사용자가 직접 넣는다.
   ```bash
   export LLMVAULT_ADDR=http://127.0.0.1:8201
   cd ~/git/claudkim/company/llm-vault
   .venv/bin/llmvault login <사용자명>
   .venv/bin/llmvault kv put anthropic/trakit api_key=sk-ant-... \
     --allowed-hosts api.anthropic.com --description "TRAKIT 뉴스 분석용 Claude API 키"
   ```
   (또는 UI http://127.0.0.1:8201/ui/ 에서 `anthropic/trakit` · `api_key`)
3. **서버 주입**: 서버(NCP)는 Mac 의 llmvault(127.0.0.1)에 접근할 수 없다. 그래서 키를 `/root/git/trakit/backend/.env` 에 `ANTHROPIC_API_KEY=` 로 넣는다. 두 방법 중 선택:
   - (a) 사용자가 vault 에서 꺼내 직접 서버 `.env` 에 기입
   - (b) Claude 가 llmvault STS `reveal` 요청 → 사용자 승인 → 서버 `.env` 에 기입 (대화에 키 원문이 노출됨)
   - `.env` 는 `.dockerignore` 로 이미지에서 제외되고 `env_file` 로만 주입된다(PR #2). 별도 조치 불필요.
4. 로컬 Mac(`backend/.env`)도 동일 키 추가 (뉴스 캐시 재빌드·스크립트용).

## 4. 설계

### 4.1 설정 (`backend/config.py`)
```python
# NEWS_LLM=claude_api → Anthropic Messages API (ANTHROPIC_API_KEY, NEWS_CLAUDE_API_MODEL)
ANTHROPIC_API_KEY = os.getenv("ANTHROPIC_API_KEY", "")
NEWS_CLAUDE_API_MODEL = os.getenv("NEWS_CLAUDE_API_MODEL", "claude-sonnet-5")
NEWS_CLAUDE_EFFORT = os.getenv("NEWS_CLAUDE_EFFORT", "medium")  # low|medium|high
```
- 기존 `NEWS_CLAUDE_MODEL`(CLI 별칭 `haiku|sonnet|opus`)과 섞이지 않게 API 모델 ID 는 별도 변수로 둔다.

### 4.2 출력 스키마 (Pydantic)
현재 프롬프트의 JSON 형식을 그대로 스키마로 옮긴다.
```python
class TickerEvent(BaseModel):
    ticker: str
    judgment: Literal["호재", "악재", "중립"]
    theme: str
    causal_chain: str

class MacroEvent(BaseModel):
    category: Literal["전쟁", "관세", "경제지표", "연준"]
    direction: Literal["상승", "하락"]
    causal_chain: str
    title: str

class DayAnalysis(BaseModel):
    nasdaq_bias: float          # -1.0 ~ +1.0 (후단 clamp 유지)
    confidence: Literal["강", "중", "약"]
    summary: str
    per_ticker: dict[str, Literal["호재", "악재", "중립"]]
    events: list[TickerEvent]
    macro_events: list[MacroEvent]
```
- 구현: `per_ticker` 는 스키마 호환을 위해 `list[{ticker, judgment}]` 로 받아 dict 로 변환한다.
- llmvault: `anthropic/trakit` 필드 `api_key`, 허용 호스트 `api.anthropic.com` 설정 완료.

### 4.3 호출 (`nasdaq_news._claude_api_json`)
```python
import anthropic
_client = anthropic.Anthropic(api_key=ANTHROPIC_API_KEY, timeout=120, max_retries=2)

def _claude_api_json(prompt: str) -> dict:
    resp = _client.messages.parse(
        model=NEWS_CLAUDE_API_MODEL,
        max_tokens=16000,
        output_config={"effort": NEWS_CLAUDE_EFFORT},
        messages=[{"role": "user", "content": prompt}],
        output_format=DayAnalysis,
    )
    if resp.stop_reason == "refusal":
        raise RuntimeError("Claude refusal")
    return resp.parsed_output.model_dump()
```
- `_llm_json` 디스패치에 `claude_api` 분기 추가.
- 프롬프트 끝의 "아래 JSON 으로만 답하세요 …" 예시는 스키마가 대신하므로 `claude_api` 경로에서는 그대로 두어도 무해하다(A/B 일관성 위해 유지).
- 예외 처리: `RateLimitError` / `APIStatusError` / `APIConnectionError` 순으로 잡아 로그를 남기고 raise → `analyze_day` 기존 `failed=True` 경로(캐시 안 함, bias 0.0 강등, 다음 실행 재시도)를 그대로 탄다.
- 구현 시 SDK 버전에서 `messages.parse` · `output_config` 시그니처와 refusal 폴백(`fallbacks`) 지원 여부를 확인하고, 지원하면 refusal 시 서버측 폴백을 켠다.

### 4.4 버그 수정 (`analyze_day` 키 게이트)
```python
def _llm_ready() -> bool:
    return {"gemini": bool(GEMINI_API_KEY), "claude_api": bool(ANTHROPIC_API_KEY),
            "claude_cli": True}.get(NEWS_LLM, False)
```
`not GEMINI_API_KEY` → `not _llm_ready()`. 로그 문구 "Gemini 실패"도 백엔드명으로 일반화.

### 4.5 의존성
- `backend/requirements.txt` 에 `anthropic` 추가 → 백엔드 이미지 재빌드 필요.

## 5. 모델 · 비용

- **결정: `claude-sonnet-5`** (기존 sonnet 캐시와 판단 경향 일관 · 저렴). 호출 빈도는 **하루 1회**(사전장 D-1 뉴스, 캐시 미스 시)라 비용 영향이 작다.
- 1회 입력은 헤드라인 수십~백여 줄 수준(수천 토큰), 출력 수천 토큰 이하로 예상 → 1회 수 센트 수준. 첫 주 `response.usage` 로그로 실측한다.
- 다른 모델로 바꾸려면 `.env` 의 `NEWS_CLAUDE_API_MODEL` 만 변경.

## 6. 검증

1. 단위: `_claude_api_json` 을 mock 클라이언트로 → 스키마 dict 반환, refusal/에러 시 raise 확인.
2. 실호출 1회(로컬): `python -m services.nasdaq_news <어제날짜>` (`use_cache=False`) → bias·events 형식, 비용(usage) 확인.
3. A/B: 최근 N일을 `claude_cli`(sonnet) 캐시 vs `claude_api` 결과로 bias 부호 일치율 비교 (실호출 N회 비용 발생 → 사전 승인).
4. 서버: 배포 후 컨테이너 안에서 2번 재실행 → 다음 사전장(17:00 KST) 🔮 메시지에 "뉴스 bias" 반영 확인.

## 7. 배포 순서

1. 코드 PR (config / nasdaq_news / requirements / 테스트)
2. 키 발급 → llmvault 보관 (사용자)
3. 서버 `.env`: `NEWS_LLM=claude_api`, `ANTHROPIC_API_KEY=...` (+ 모델/effort 선택)
4. `docker compose up -d --build backend`
5. 검증 6-4 → 문제 시 `.env` 의 `NEWS_LLM` 을 이전 값으로 되돌리고 재시작 (롤백)

## 8. 결정 필요 사항

- [x] 모델: `claude-sonnet-5`
- [ ] 서버 키 주입 방식: (a) 사용자 직접 / (b) STS reveal 승인 후 Claude 가 기입
- [ ] A/B 비교 범위(N일)와 비용 승인
