# TODO Features

## 예약 매수/매도 자동화 (KIS API)

### 개요
한국투자증권 REST API를 이용한 TQQQ 예약 매수/매도 자동 주문 기능.
매수/매도 포인트 테이블의 가격으로 자동 예약주문을 접수.

### 사전 요구사항
- 사용자 인증 (로그인/회원가입)
- 사용자별 KIS 앱키/시크릿/계좌번호 관리
- DB (사용자, 주문 이력 저장)

### KIS API 엔드포인트

| API | Method | URL | tr_id (실전/모의) |
|-----|--------|-----|-------------------|
| 예약 매수 | POST | `/uapi/overseas-stock/v1/trading/order-resv` | `TTTT3014U` / `VTTT3014U` |
| 예약 매도 | POST | `/uapi/overseas-stock/v1/trading/order-resv` | `TTTT3016U` / `VTTT3016U` |
| 예약 취소 | POST | `/uapi/overseas-stock/v1/trading/order-resv-ccnl` | `TTTT3017U` / `VTTT3017U` |
| 예약 조회 | GET | `/uapi/overseas-stock/v1/trading/order-resv-list` | `TTTT3039R` (모의 불가) |

### 주문 파라미터

```python
{
    "CANO": "계좌번호 앞 8자리",
    "ACNT_PRDT_CD": "01",
    "PDNO": "TQQQ",
    "OVRS_EXCG_CD": "NASD",
    "FT_ORD_QTY": "수량",
    "FT_ORD_UNPR3": "지정가",
    "ORD_DVSN": "00",         # 지정가
}
```

### 제약사항
- 접수 시간: KST 10:00~23:20 (서머타임 시 ~22:20)
- 지정가만 가능 (매도는 MOO 추가 가능)
- 증거금 체크는 전송 시점(23:30)에 수행
- 당일만 유효, 미체결 시 자동 취소

### 구현 단계

1. **Phase 1: 개인용 (단일 사용자)**
   - `.env`에 계좌번호 추가
   - 대시보드에서 예약주문 버튼
   - 주문 결과 로깅

2. **Phase 2: 멀티 사용자**
   - 사용자 인증 (OAuth/JWT)
   - DB (PostgreSQL/SQLite)
   - 사용자별 KIS 키/계좌 암호화 저장
   - 주문 이력 관리 UI
   - 주문 상태 알림 (웹소켓/폴링)

---

## WebSocket 실시간 통신

### 개요
현재 폴링(20초) 방식을 WebSocket으로 전환하여 실시간 데이터 push 구현.

### 도입 시점
- 예약주문 기능 구현 시 (주문 체결/취소 상태 실시간 push)
- 다중 사용자 서비스 확장 시 (폴링 부하 감소)
- KIS WebSocket 실시간 체결가 연동 시

### 아키텍처

```
[KIS WebSocket] → [Backend (relay)] → [Client WebSocket]
                                     → [Discord Webhook]
```

### 백엔드 (FastAPI WebSocket)

```python
# FastAPI 네이티브 WebSocket 지원
from fastapi import WebSocket

@app.websocket("/ws")
async def websocket_endpoint(websocket: WebSocket):
    await websocket.accept()
    while True:
        data = get_current_price()
        await websocket.send_json(data)
        await asyncio.sleep(20)
```

### 프론트엔드 (React)

```javascript
useEffect(() => {
  const ws = new WebSocket('wss://trakit.stock-snow.com/ws');
  ws.onmessage = (e) => setPrice(JSON.parse(e.data));
  return () => ws.close();
}, []);
```

### KIS WebSocket 실시간 체결가

| 항목 | 내용 |
|------|------|
| URL | `ws://ops.koreainvestment.com:21000` (실전) |
| URL (모의) | `ws://ops.koreainvestment.com:31000` |
| 구독 | `tr_id: HDFSCNT0` (해외주식 실시간 체결가) |
| 데이터 | 체결가, 체결량, 시간 등 tick 단위 |

```python
# KIS WebSocket 구독 예시
import websockets

async def kis_realtime():
    async with websockets.connect("ws://ops.koreainvestment.com:21000") as ws:
        # 인증 + TQQQ 구독
        await ws.send(json.dumps({
            "header": {"tr_id": "HDFSCNT0", "tr_key": "DNAS|TQQQ"},
            "body": {"tr_id": "HDFSCNT0", "tr_key": "DNAS|TQQQ"}
        }))
        async for message in ws:
            data = parse_kis_message(message)
            # 클라이언트에 relay
```

### Push 이벤트 종류

| 이벤트 | 데이터 | 트리거 |
|--------|--------|--------|
| `price_update` | 현재가, 변동, 등락률 | KIS 실시간 체결 또는 20초 폴링 |
| `signal_change` | BUY/SELL/HOLD 변경 | 밴드 기준 판단 변경 시 |
| `order_update` | 주문 상태 (접수/체결/취소) | 예약주문 상태 변경 시 |
| `data_refresh` | 갱신 결과 | Google Sheets 갱신 완료 시 |

### 구현 단계

1. **Phase 1: 기본 WebSocket**
   - FastAPI WebSocket 엔드포인트 (`/ws`)
   - 가격 데이터 20초 push (폴링 대체)
   - 프론트엔드 WebSocket 클라이언트
   - nginx WebSocket proxy 설정 (`proxy_set_header Upgrade`)

2. **Phase 2: KIS 실시간 연동**
   - KIS WebSocket 구독 (TQQQ 실시간 체결가)
   - 백엔드에서 수신 → 클라이언트에 relay
   - 시그널 변경 자동 감지 및 push

3. **Phase 3: 주문 상태 push**
   - 예약주문 상태 변경 시 WebSocket push
   - Discord webhook 동시 알림
   - 연결 관리 (reconnect, heartbeat)

### nginx WebSocket 설정

```nginx
location /ws {
    proxy_pass http://backend:8000;
    proxy_http_version 1.1;
    proxy_set_header Upgrade $http_upgrade;
    proxy_set_header Connection "upgrade";
    proxy_set_header Host $host;
}
```

### 의존성
- `websockets>=12.0` (KIS WebSocket 클라이언트)
- FastAPI 내장 WebSocket (추가 패키지 불필요)
