# Trakit API 명세

Base URL: `http://localhost:8000/api`

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
  "recommendation": "홀드: 밴드 내 18% 위치. 현재 상태 유지하세요."
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

실시간 TQQQ 가격 조회. yfinance → Yahoo API v8 → Yahoo quote 순서로 fallback.
30초 캐싱 적용.

**Response** `200`
```json
{
  "symbol": "TQQQ",
  "price": 41.10,
  "change": 3.21,
  "change_pct": 8.47,
  "timestamp": "2026-04-01T14:30:00.000000",
  "prev_close": 37.89,
  "day_high": 41.50,
  "day_low": 40.20,
  "market_open": false
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
| `day_high` | float | 당일 최고가 (nullable) |
| `day_low` | float | 당일 최저가 (nullable) |
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
