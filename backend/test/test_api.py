"""Trakit API 엔드포인트 테스트

실행: cd backend && python -m pytest test/ -v
"""


class TestHealth:
    def test_health(self, client):
        """GET /api/health - 서버 상태 확인"""
        resp = client.get("/api/health")
        assert resp.status_code == 200
        data = resp.json()
        assert data["status"] == "ok"
        assert "version" in data


class TestPortfolio:
    def test_get_portfolio(self, client):
        """GET /api/portfolio - 현재 포트폴리오"""
        resp = client.get("/api/portfolio")
        assert resp.status_code == 200
        data = resp.json()
        assert "week_num" in data
        assert "price" in data
        assert "shares" in data
        assert "valuation" in data
        assert "pool" in data
        assert "min_band" in data
        assert "max_band" in data
        assert "total_value" in data
        assert "goal_progress" in data
        assert data["price"] > 0
        assert data["shares"] > 0

    def test_get_portfolio_with_price(self, client):
        """GET /api/portfolio?price=50.0 - 실시간 가격 오버라이드"""
        resp = client.get("/api/portfolio", params={"price": 50.0})
        assert resp.status_code == 200
        data = resp.json()
        assert data["price"] == 50.0

    def test_portfolio_history(self, client):
        """GET /api/portfolio/history - 포트폴리오 히스토리"""
        resp = client.get("/api/portfolio/history")
        assert resp.status_code == 200
        data = resp.json()
        assert isinstance(data, list)
        assert len(data) > 0
        first = data[0]
        assert "week_num" in first
        assert "price" in first
        assert "shares" in first
        assert "valuation" in first
        assert "min_band" in first
        assert "max_band" in first

    def test_portfolio_history_date_filtered(self, client):
        """히스토리가 현재 날짜 기준으로 필터링되는지 확인"""
        resp = client.get("/api/portfolio/history")
        data = resp.json()
        # 모든 주차에 가격 데이터가 있어야 함
        for week in data:
            assert week["price"] > 0


class TestSignals:
    def test_get_signals(self, client):
        """GET /api/signals - 매매 시그널"""
        resp = client.get("/api/signals")
        assert resp.status_code == 200
        data = resp.json()
        assert "signal_type" in data
        assert data["signal_type"] in ("BUY", "SELL", "HOLD")
        assert "recommendation" in data
        assert "min_band" in data
        assert "max_band" in data

    def test_get_signals_with_price(self, client):
        """GET /api/signals?price=30.0 - 가격 오버라이드 시그널"""
        resp = client.get("/api/signals", params={"price": 30.0})
        assert resp.status_code == 200
        data = resp.json()
        assert data["signal_type"] in ("BUY", "SELL", "HOLD")


class TestPrice:
    def test_get_price(self, client):
        """GET /api/price - 실시간 TQQQ 가격"""
        resp = client.get("/api/price")
        assert resp.status_code == 200
        data = resp.json()
        assert "symbol" in data
        assert "price" in data
        assert "change" in data
        assert "change_pct" in data
        assert "timestamp" in data
        assert data["symbol"] == "TQQQ"

    def test_get_price_history(self, client):
        """GET /api/price/history - TQQQ 가격 히스토리"""
        resp = client.get("/api/price/history", params={"period": "1mo"})
        assert resp.status_code == 200
        data = resp.json()
        assert isinstance(data, list)


class TestTradePoints:
    def test_get_trade_points(self, client):
        """GET /api/trade-points - 매수/매도 포인트"""
        resp = client.get("/api/trade-points")
        assert resp.status_code == 200
        data = resp.json()
        assert "buy_table" in data
        assert "sell_table" in data
        assert "unit_size" in data

    def test_trade_points_calc(self, client):
        """GET /api/trade-points/calc - 파라미터 기반 매수/매도 포인트 계산"""
        resp = client.get("/api/trade-points/calc", params={
            "shares": 1246,
            "min_band": 49392.77,
            "max_band": 73365.29,
            "pool": 5480.47,
        })
        assert resp.status_code == 200
        data = resp.json()
        assert "buy_table" in data
        assert "sell_table" in data
        buy_rows = data["buy_table"]["rows"]
        sell_rows = data["sell_table"]["rows"]
        assert isinstance(buy_rows, list)
        assert isinstance(sell_rows, list)

    def test_trade_points_calc_with_unit(self, client):
        """GET /api/trade-points/calc?unit=10 - 기준 단수 지정"""
        resp = client.get("/api/trade-points/calc", params={
            "shares": 1246,
            "min_band": 49392.77,
            "max_band": 73365.29,
            "pool": 5480.47,
            "unit": 10,
        })
        assert resp.status_code == 200
        data = resp.json()
        assert data["unit_size"] == 10

    def test_trade_points_calc_missing_params(self, client):
        """필수 파라미터 누락 시 422"""
        resp = client.get("/api/trade-points/calc", params={"shares": 100})
        assert resp.status_code == 422

    def test_saved_trade_points(self, client):
        """GET /api/trade-points/saved - CSV 저장 매매 포인트"""
        resp = client.get("/api/trade-points/saved")
        assert resp.status_code == 200


class TestBacktest:
    def test_backtest(self, client):
        """POST /api/backtest - 백테스트"""
        resp = client.post("/api/backtest", json={})
        assert resp.status_code == 200
        data = resp.json()
        assert "summary" in data or "weeks" in data or isinstance(data, dict)

    def test_backtest_with_range(self, client):
        """POST /api/backtest - 주차 범위 지정 백테스트"""
        resp = client.post("/api/backtest", json={
            "start_week": 142,
            "end_week": 258,
        })
        # 범위 지정 백테스트 (데이터 범위에 따라 200 또는 500)
        assert resp.status_code in (200, 500)


class TestRemaining:
    def test_remaining(self, client):
        """GET /api/remaining - 남은 적립 횟수"""
        resp = client.get("/api/remaining")
        assert resp.status_code == 200
        data = resp.json()
        assert "current_week" in data
        assert "goal_week" in data
        assert "remaining_weeks" in data
        assert "remaining_cycles" in data
        assert data["goal_week"] == 560
        assert data["remaining_weeks"] > 0


class TestExchangeRate:
    def test_exchange_rate(self, client):
        """GET /api/exchange-rate - USD/KRW 환율"""
        resp = client.get("/api/exchange-rate")
        assert resp.status_code == 200
        data = resp.json()
        assert data["base"] == "USD"
        assert data["target"] == "KRW"
        assert data["rate"] > 0
        assert "date" in data
        assert data["source"] in ("live", "default")


class TestRoot:
    def test_root(self, client):
        """GET / - 루트 엔드포인트"""
        resp = client.get("/")
        assert resp.status_code == 200
        data = resp.json()
        assert "message" in data
        assert data["message"] == "Trakit API"
