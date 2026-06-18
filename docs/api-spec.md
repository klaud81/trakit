# Trakit API 명세

Base URL: `https://trakit.stock-snow.com/api` (운영) 또는 `http://localhost:8000/api` (로컬)

---

## 1. Health Check

### `GET /api/health`

서버 상태 확인.

**Response** `200`
```json
{
  "status": "ok",
  "version": "0.1.0"
}
```

---

## 2. Portfolio

### `GET /api/portfolio`

현재 포트폴리오 상태 조회. 현재 날짜 기준으로 유효한 마지막 주차 데이터를 반환합니다.

**Query Parameters**

| 파라미터 | 타입 | 필수 | 설명 |
|----------|------|------|------|
| `price` | float | N | 실시간 가격 오버라이드 (평가금 재계산) |

**Response** `200`
```json
{
  "week_num": "258",
  "date_range": "2026/3/23-4/3",
  "price": 43.08,
  "shares": 1246,
  "avg_cost": 43.02,
  "valuation": 53677.68,
  "pool": 5480.47,
  "target_value": 49392.77,
  "min_band": 49392.77,
  "max_band": 73365.29,
  "growth_stage": 12,
  "total_value": 59158.15,
  "goal_progress": 5.97,
  "profit": 7106.88,
  "profit_pct": 12.03,
  "exchange_rate": 1496.3,
  "updated_at": "2026-04-01T14:30:00.000000"
}
```

**필드 설명**

| 필드 | 타입 | 설명 |
|------|------|------|
| `week_num` | string | 주차 번호 |
| `date_range` | string | 주차 날짜 범위 (YYYY/M/D-M/D) |
| `price` | float | 현재 가격 ($/주) |
| `shares` | int | 보유 수량 |
| `avg_cost` | float | 평균 매수가 |
| `valuation` | float | 평가금 (price x shares) |
| `pool` | float | Pool 잔고 ($) |
| `target_value` | float | 목표 가치 (V) |
| `min_band` | float | 최소 밴드 ($) |
| `max_band` | float | 최대 밴드 ($) |
| `growth_stage` | int | 성장 구간 (G) |
| `total_value` | float | 총 자산 (valuation + pool) |
| `goal_progress` | float | 목표 달성률 (%) |
| `profit` | float | 수익금 (현재가 - 평단) × 보유수량 (nullable) |
| `profit_pct` | float | 수익률 % (nullable) |
| `exchange_rate` | float | 적용 환율 (USD/KRW) |

---

### `GET /api/portfolio/history`

포트폴리오 히스토리 (차트 데이터). 현재 날짜 기준으로 시작일이 미래인 데이터는 제외됩니다.

**Response** `200`
```json
[
  {
    "week_num": "142",
    "date_range": "2025/1/1-1/12",
    "price": 50.34,
    "shares": 425,
    "valuation": 21394.50,
    "pool": 4442.28,
    "total": 25836.78,
    "target_value": 20971.38,
    "min_band": 17825.67,
    "max_band": 24117.09,
    "avg_cost": 39.03,
    "g": 12
  }
]
```

---

## 3. Signals

### `GET /api/signals`

현재 매매 시그널 조회. 평가금과 밴드 위치를 비교하여 BUY/SELL/HOLD 판단.

**Query Parameters**

| 파라미터 | 타입 | 필수 | 설명 |
|----------|------|------|------|
| `price` | float | N | 가격 오버라이드 |

**Response** `200`
```json
{
  "signal_type": "HOLD",
  "confidence": 0.7,
  "current_valuation": 53677.68,
  "target_value": 49392.77,
  "min_band": 49392.77,
  "max_band": 73365.29,
  "distance_to_buy": 4284.91,
  "distance_to_sell": 19687.61,
  "recommendation": "홀드: 밴드 내 18% 위치. 현재 상태 유지하세요.",
  "profit": 7106.88,
  "profit_pct": 12.03
}
```

**시그널 판단 기준**

| signal_type | 조건 |
|-------------|------|
| `BUY` | valuation < min_band |
| `SELL` | valuation > max_band |
| `HOLD` | min_band <= valuation <= max_band |

---

## 4. Price

### `GET /api/price`

실시간 TQQQ 가격 조회. KIS(한국투자증권) → yfinance → Yahoo API v8 → Yahoo quote 순서로 fallback.
30초 캐싱, KST 21~06시만 갱신.

**Response** `200`
```json
{
  "symbol": "TQQQ",
  "price": 48.08,
  "change": 3.93,
  "change_pct": 8.90,
  "timestamp": "2026-04-09T02:53:22.212049",
  "prev_close": 44.15,
  "day_high": 48.92,
  "day_low": 47.15,
  "market_open": true
}
```

**필드 설명**

| 필드 | 타입 | 설명 |
|------|------|------|
| `symbol` | string | 티커 심볼 |
| `price` | float | 현재가 |
| `change` | float | 전일 대비 변동 ($) |
| `change_pct` | float | 전일 대비 변동률 (%) |
| `prev_close` | float | 전일 종가 |
| `day_high` | float | 당일 최고가 (장중 제공, 장 마감 시 null 가능) |
| `day_low` | float | 당일 최저가 (장중 제공, 장 마감 시 null 가능) |
| `market_open` | bool | 시장 개장 여부 (ET 9:30~16:00) |

---

### `GET /api/price/history`

TQQQ 가격 히스토리 조회.

**Query Parameters**

| 파라미터 | 타입 | 필수 | 기본값 | 설명 |
|----------|------|------|--------|------|
| `period` | string | N | `6mo` | 기간: `1d`, `5d`, `1mo`, `3mo`, `6mo`, `1y`, `2y` |

**Response** `200`
```json
[
  {
    "date": "2026-03-31",
    "open": 38.50,
    "high": 41.20,
    "low": 37.80,
    "close": 41.10,
    "volume": 125000000
  }
]
```

---

## 5. Trade Points

### `GET /api/trade-points`

현재 포트폴리오 기반 매수/매도 포인트 테이블.

**Query Parameters**

| 파라미터 | 타입 | 필수 | 설명 |
|----------|------|------|------|
| `price` | float | N | 가격 오버라이드 |

**Response** `200`
```json
{
  "buy_table": {
    "header": { "band": 49392.77, "shares": 1246, "pool": 5480.47 },
    "rows": [
      { "action": "BUY", "shares_after": 1256, "price": 39.64, "amount": 396.40, "pool_after": 5084.07 }
    ]
  },
  "sell_table": {
    "header": { "band": 73365.29, "shares": 1246, "pool": 5480.47 },
    "rows": [
      { "action": "SELL", "shares_after": 1236, "price": 58.88, "amount": 588.80, "pool_after": 6069.27 }
    ]
  },
  "unit_size": 10,
  "count": 6
}
```

---

### `GET /api/trade-points/calc`

파라미터 기반 매수/매도 포인트 계산. 주차 이동 시 프론트엔드에서 호출.

**Query Parameters**

| 파라미터 | 타입 | 필수 | 설명 |
|----------|------|------|------|
| `shares` | int | **Y** | 보유 수량 |
| `min_band` | float | **Y** | 최소 밴드 |
| `max_band` | float | **Y** | 최대 밴드 |
| `pool` | float | **Y** | Pool 잔고 |
| `unit` | int | N | 기준 단수 (미지정 시 자동계산) |

**Response** `200` - `/api/trade-points`와 동일 구조

**Error** `422` - 필수 파라미터 누락

---

### `GET /api/trade-points/saved`

CSV 파일에 저장된 매매 포인트 조회.

**Response** `200`
```json
{
  "buy_points": [...],
  "sell_points": [...],
  "settings": {}
}
```

---

## 6. Backtest

### `POST /api/backtest`

지정 주차 범위에 대한 백테스트 실행.

**Request Body**
```json
{
  "start_week": 142,
  "end_week": 258
}
```

| 필드 | 타입 | 필수 | 설명 |
|------|------|------|------|
| `start_week` | int | N | 시작 주차 (미지정 시 전체) |
| `end_week` | int | N | 종료 주차 (미지정 시 전체) |

**Response** `200`
```json
{
  "summary": {
    "start_week": 142,
    "end_week": 258,
    "total_contribution": 12400,
    "final_value": 59158.15,
    "return_pct": 377.1
  },
  "weeks": [...]
}
```

---

## 7. Remaining

### `GET /api/remaining`

남은 적립 횟수 및 진행률 조회.

**Response** `200`
```json
{
  "current_week": 258,
  "goal_week": 560,
  "remaining_weeks": 302,
  "remaining_cycles": 151,
  "progress_pct": 46.1
}
```

---

## 8. Visitors

### `POST /api/visit`

방문 기록 + 통계 반환. 프론트엔드 초기 로딩 시 1회 호출.

```bash
curl -s -X POST https://trakit.stock-snow.com/api/visit
```

### `GET /api/visitors`

방문자 통계 조회 (기록 없이 조회만).

```bash
curl -s https://trakit.stock-snow.com/api/visitors
```

**Response** `200`
```json
{
  "today": 15,
  "month": 245,
  "total": 1234,
  "date": "2026/04/13"
}
```

| 필드 | 타입 | 설명 |
|------|------|------|
| `today` | int | 오늘 방문자 수 |
| `month` | int | 당월 방문자 수 |
| `total` | int | 누적 방문자 수 |

**저장 형식** (`data/visitors.json`)
```json
{
  "daily": {"2026/04/12": 15, "2026/04/13": 3},
  "monthly": {"2026/03": 245},
  "total": 1234
}
```

- `daily` — 당월 일별 방문자 (월 변경 시 `monthly`로 자동 집계)
- `monthly` — 이전 월별 집계
- `total` — 누적 합계

---

## 9. Refresh


### `POST /api/refresh`

Google Sheets 데이터 캐시를 강제 갱신합니다. 캐시는 기본 5일 유효하며, 이 API로 즉시 갱신할 수 있습니다.

```bash
# 운영
curl -s -X POST https://trakit.stock-snow.com/api/refresh

# 로컬
curl -s -X POST http://localhost:8000/api/refresh
```

**Response** `200`
```json
{
  "status": "ok",
  "rows": 214,
  "valid_rows": 63
}
```

| 필드 | 타입 | 설명 |
|------|------|------|
| `rows` | int | 전체 행 수 |
| `valid_rows` | int | 가격 데이터가 있는 유효 행 수 |

---

## 9. Config

> 이하 curl 예시는 운영 URL(`https://trakit.stock-snow.com`) 기준입니다.

### `GET /api/config`

프론트엔드 설정 조회. 가격 자동 갱신 시간대와 간격을 반환합니다.

```bash
curl -s https://trakit.stock-snow.com/api/config
```

**Response** `200`
```json
{
  "price_refresh_interval": 20,
  "price_refresh_start_hour": 21,
  "price_refresh_end_hour": 6,
  "timezone": "Asia/Seoul"
}
```

| 필드 | 타입 | 설명 |
|------|------|------|
| `price_refresh_interval` | int | 가격 자동 갱신 간격 (초) |
| `price_refresh_start_hour` | int | 자동 갱신 시작 시각 (KST) |
| `price_refresh_end_hour` | int | 자동 갱신 종료 시각 (KST) |
| `timezone` | string | 시간대 |

---

## 10. Exchange Rate

### `GET /api/exchange-rate`

USD/KRW 환율 조회. 하루 1회 외부 API에서 조회하여 캐싱합니다.
KST 17시 이후 첫 요청 시 갱신됩니다.

```bash
curl -s https://trakit.stock-snow.com/api/exchange-rate
```

**Response** `200`
```json
{
  "base": "USD",
  "target": "KRW",
  "rate": 1496.3,
  "date": "2026-04-09",
  "source": "live"
}
```

| 필드 | 타입 | 설명 |
|------|------|------|
| `base` | string | 기준 통화 |
| `target` | string | 대상 통화 |
| `rate` | float | 환율 (1 USD = N KRW) |
| `date` | string | 환율 날짜 |
| `source` | string | `live` (외부 API) 또는 `default` (기본값 1400) |

**캐시 정책:**
- 캐시 없음 → 외부 API 조회 → 캐시 저장
- 캐시 있음 + KST 17시 이후 + 아직 갱신 안 됨 → 재조회
- 그 외 → 캐시 반환

**외부 API 소스 (fallback 순서):**
```bash
# 1순위: exchangerate-api
curl -s "https://open.er-api.com/v6/latest/USD"

# 2순위: frankfurter (ECB 기반)
curl -s "https://api.frankfurter.dev/v1/latest?base=USD&symbols=KRW"
```

---

## 에러 응답

모든 엔드포인트는 서버 에러 시 동일한 형식으로 응답합니다.

**Response** `500`
```json
{
  "detail": "에러 메시지"
}
```

**Response** `422` (Validation Error)
```json
{
  "detail": [
    {
      "loc": ["query", "shares"],
      "msg": "field required",
      "type": "value_error.missing"
    }
  ]
}
```
