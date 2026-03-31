# Trakit - TQQQ 밸류 리밸런싱 퀀트 투자 시스템

## 프로젝트 개요
- **이름**: Trakit (Track + it)
- **목표**: TQQQ(3x 레버리지 나스닥100 ETF) 대상 밸류 리밸런싱(Value Rebalancing) 퀀트 투자 대시보드
- **결과물**: FastAPI 백엔드 + React 프론트엔드 웹 대시보드
- **경로**: `~/git/claudkim/trakit/`

## 투자 전략
- **대상**: TQQQ (ProShares UltraPro QQQ, 나스닥100 3배 레버리지 ETF)
- **전략**: Value Rebalancing (밸류 리밸런싱)
  - 목표 가치 경로(V)를 설정, 최소/최대 밴드로 매매 시점 결정
  - 평가금 < 최소밴드 → 매수 (pool에서 차감)
  - 평가금 > 최대밴드 → 매도 (pool로 환입)
  - 최소 ≤ 평가금 ≤ 최대 → 홀드
- **적립**: 2주마다 $200 적립, GOAL 560주차 (약 10년)

## 기술 스택

### 백엔드 (Python FastAPI)
- **프레임워크**: FastAPI + Uvicorn (port 8000)
- **데이터**: pandas, numpy (CSV 기반 포트폴리오 데이터)
- **주가 조회**: Yahoo Finance HTTP API v8 직접 호출 (requests), yfinance fallback
- **CORS**: `"*"` 허용 (개발 환경)

### 프론트엔드 (React)
- **빌드**: Vite 5 + React 18 (port 5173)
- **차트**: Recharts (ComposedChart, Area, Line, ReferenceLine)
- **API 통신**: fetch → `http://localhost:8000/api`
- **데모 모드**: 백엔드 미응답 시 demoData.js fallback

## 프로젝트 구조

```
trakit/
├── CONTEXT.md              # 이 문서
├── CLAUDE.md               # Claude 설정
├── data/
│   ├── ANALYSIS.md         # 스프레드시트 분석
│   ├── base.csv            # 핵심 투자 데이터 (142~560주차)
│   └── ...
├── backend/
│   ├── app.py              # FastAPI 앱 진입점
│   ├── config.py           # 설정 (SYMBOL="TQQQ", TRADE_UNIT 등)
│   ├── requirements.txt    # 의존성 (fastapi, uvicorn, pandas, requests 등)
│   ├── api/
│   │   ├── routes.py       # API 엔드포인트 정의
│   │   └── schemas.py      # Pydantic 스키마
│   ├── core/
│   │   ├── data_loader.py      # CSV 데이터 로딩
│   │   ├── models.py           # 데이터 모델
│   │   ├── rebalancing_engine.py  # 매수/매도 포인트 계산 엔진
│   │   └── signal_calculator.py   # 매매 시그널 생성
│   └── services/
│       ├── portfolio_service.py    # 포트폴리오 상태 조회
│       ├── price_service.py        # 실시간 TQQQ 가격 (Yahoo Finance API)
│       ├── trade_calculator.py     # 매수/매도 테이블 생성
│       └── backtesting_service.py  # 백테스팅
└── frontend/
    ├── vite.config.js
    ├── package.json
    └── src/
        ├── App.jsx             # 메인 컴포넌트 (상태 관리, 주차 이동, API 연동)
        ├── index.css           # 전역 스타일
        ├── main.jsx            # React 진입점
        ├── components/
        │   ├── Header.jsx          # 헤더 (주차 이동 ◀▶, TQQQ 실시간 가격)
        │   ├── SignalPanel.jsx     # 시그널 패널 (매수가/매도가 표시)
        │   ├── EquityChart.jsx     # 평가금 차트 (ComposedChart: 밴드 + 평가금)
        │   ├── ValueLineChart.jsx  # 주당 가치 차트 (가격, V/주, 밴드/주, E/주)
        │   ├── TradeTable.jsx      # 매수/매도 포인트 테이블
        │   ├── PortfolioCard.jsx   # 포트폴리오 카드
        │   ├── BandCard.jsx        # 밴드 정보 카드
        │   └── ProgressCard.jsx    # 진행률 카드
        └── utils/
            ├── api.js          # API 클라이언트 (fetchApi)
            ├── format.js       # 포맷 유틸 (fmt, fmtPct, fmtUSD)
            └── demoData.js     # 데모 데이터 (백엔드 없을 때)
```

## API 엔드포인트

| 엔드포인트 | 메서드 | 설명 |
|---|---|---|
| `/api/health` | GET | 서버 상태 확인 |
| `/api/portfolio` | GET | 현재 포트폴리오 상태 (?price= 가격 오버라이드) |
| `/api/portfolio/history` | GET | 포트폴리오 히스토리 (차트 데이터) |
| `/api/signals` | GET | 현재 매매 시그널 |
| `/api/price` | GET | 실시간 TQQQ 가격 (30초 캐시) |
| `/api/price/history` | GET | TQQQ 가격 히스토리 (?period=6mo) |
| `/api/trade-points` | GET | 현재 주차 매수/매도 포인트 |
| `/api/trade-points/calc` | GET | 파라미터 기반 매수/매도 포인트 계산 |
| `/api/trade-points/saved` | GET | CSV 저장된 매매 포인트 |
| `/api/remaining` | GET | 남은 적립 횟수 |
| `/api/backtest` | POST | 백테스트 실행 |

## 핵심 로직

### 매수/매도 포인트 계산 (rebalancing_engine.py)
- **기준수량(unit)**: `ROUND(pool / 13 / (min_band / shares) / 2)`
- **매수점**: `ROUND(min_band / current_shares, 2)` — 매수 전 보유수량 기준
- **매도점**: `ROUND(max_band / current_shares, 2)` — 매도 전 보유수량 기준
- **매수 중단 조건**: `remaining_pool ≤ initial_pool / 2`
- **매도 횟수**: 매수 횟수와 동일

### 매수 루프 (calculate_buy_points)
```
shares = current_shares
remaining_pool = pool
half_pool = pool / 2
while remaining_pool > half_pool:
    buy_price = ROUND(min_band / shares, 2)
    cost = buy_price * unit_size
    shares += unit_size
    remaining_pool -= cost
```

### 매도 루프 (calculate_sell_points)
```
for i in range(buy_count):
    sell_price = ROUND(max_band / shares, 2)
    proceeds = sell_price * unit_size
    shares -= unit_size
    remaining_pool += proceeds
```

### API 응답 구조 (trade-points/calc)
```json
{
  "buy_table": {
    "header": { "label": "최소값", "band": 49392.77, "shares": 1246, "pool": 5680.47 },
    "rows": [
      { "price": 39.64, "shares_after": 1256, "cost": 396.40, "pool_after": 5284.07 },
      ...
    ]
  },
  "sell_table": {
    "header": { "label": "최대값", "band": 73365.29, "shares": 1246, "pool": 5680.47 },
    "rows": [
      { "price": 58.88, "shares_after": 1236, "cost": 588.80, "pool_after": 6269.27 },
      ...
    ]
  },
  "unit_size": 10,
  "count": 5
}
```

### 실시간 가격 (price_service.py)
- **1차**: Yahoo Finance v8 API (`query1.finance.yahoo.com/v8/finance/chart/TQQQ`)
- **2차**: Yahoo Finance v7 Quote API (fallback)
- **3차**: yfinance 패키지 (설치된 경우)
- **캐시**: 30초 TTL
- **시장 상태**: EDT 기준 월~금 9:30~16:00 → market_open: true/false
- **자동 갱신**: 프론트엔드 30초 폴링 (useEffect interval)

## UI 구성

### Header
- 좌측: TRAKIT 로고, ◀ 주차 이동 ▶, 날짜 범위, GOAL: 560주차
- 우측: TQQQ $XX.XX +X.XX (X.XX%) [closed] — 실시간 가격, 30초 자동 갱신

### 차트
- **EquityChart (평가금 차트)**: ComposedChart, 최대밴드(Area), 최소밴드(Area), 평가금(E)(Line)
  - ReferenceLine으로 현재 주차 위치 표시 (주황색 점선)
  - cleanHistory: valuation 0 → null 변환
- **ValueLineChart (주당 가치 차트)**: 가격, V/주, 최대/주, 최소/주, 평가금(E)/주
  - ReferenceLine으로 현재 주차 위치 표시

### SignalPanel
- 매수까지: 매수 테이블 1행의 price (매수가/주)
- 매도까지: 매도 테이블 1행의 price (매도가/주)

### TradeTable
- 헤더 행: 밴드값, 잔여갯수, pool
- 데이터 행: 횟수별 매수점/매도점, 수량 변화, pool 변화
- 기준수량 표시 (동적 계산)
- 주차 이동 시 `/api/trade-points/calc` API로 재계산

## 실행 방법

```bash
# 백엔드 실행
cd backend
pip install -r requirements.txt
uvicorn app:app --reload --port 8000

# 프론트엔드 실행
cd frontend
npm install
npm run dev  # → http://localhost:5173
```

## 주요 데이터 (258주차 기준)
- **보유수량**: 1,246주
- **현재가**: ~$43.08
- **평가금(E)**: ~$53,677.68
- **pool**: ~$5,680.47
- **V (목표)**: $59,509.36
- **최소밴드**: $49,392.77
- **최대밴드**: $73,365.29
- **상태**: 밴드 내 → 홀드

## 개발 노트

### week_num 형식
- 일반: 숫자 (142, 144, ..., 258)
- 조정 행: "204-1" 형태의 문자열
- 미래 예측: 260 ~ 560

### 프론트엔드 fallback 패턴
- API 호출 → 성공: 데이터 사용 / 실패: 로컬 JS 계산 결과 사용
- 데모 모드: 백엔드 전체 미응답 시 demoData.js 사용

### ComposedChart 사용 이유
- Recharts의 AreaChart는 Line 컴포넌트를 렌더링하지 못함
- Area(밴드) + Line(평가금)을 동시에 표시하려면 ComposedChart 필수

## 참고
- 이 도구는 분석 보조 목적이며, 실제 투자 결정은 본인의 판단으로 해야 함
