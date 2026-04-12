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
