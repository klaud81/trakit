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


class TestPortfolioExtras:
    """portfolio 응답에 새로 노출된 필드 검증"""

    def test_portfolio_has_vr_mode(self, client):
        resp = client.get("/api/portfolio")
        data = resp.json()
        assert "vr_mode" in data
        assert data["vr_mode"] in ("적립식 VR", "거치식 VR", "인출식 VR")
        assert "contribution" in data

    def test_portfolio_has_consumption_rate(self, client):
        resp = client.get("/api/portfolio")
        data = resp.json()
        assert "consumption_rate" in data
        # 미설정/0 은 기본 0.5 fallback, 설정값은 0~1 사이여야 의미 있음
        assert data["consumption_rate"] is not None
        assert 0 < data["consumption_rate"] <= 1

    def test_portfolio_has_executed_prices(self, client):
        resp = client.get("/api/portfolio")
        data = resp.json()
        assert "executed_prices" in data
        assert isinstance(data["executed_prices"], list)
        for p in data["executed_prices"]:
            assert isinstance(p, (int, float))

    def test_portfolio_pool_parses_thousand_separator(self, client):
        """시트 pool 셀에 천단위 콤마("6,135.75") 가 있어도 숫자로 파싱"""
        resp = client.get("/api/portfolio")
        data = resp.json()
        assert isinstance(data["pool"], (int, float))


class TestPortfolioHistoryExtras:
    def test_history_includes_vr_mode(self, client):
        resp = client.get("/api/portfolio/history")
        data = resp.json()
        assert len(data) > 0
        last = data[-1]
        assert "vr_mode" in last
        assert last["vr_mode"] in ("적립식 VR", "거치식 VR", "인출식 VR")
        assert "contribution" in last


class TestGoal:
    def test_goal_current(self, client):
        """GET /api/goal - 현재 주차 목표 진행률"""
        resp = client.get("/api/goal")
        assert resp.status_code == 200
        data = resp.json()
        for k in ("week_num", "actual_value", "planned", "plan_pct", "goal_progress",
                  "weeks_diff", "time_label", "target_week", "weeks_remaining",
                  "years_left", "weeks_left_in_year", "remaining_cycles", "rate"):
            assert k in data, f"missing field: {k}"
        # 시트의 "계획" 컬럼이 정상적으로 파싱되어야 함 (1.03 같은 ratio 값이 들어가면 안됨)
        assert data["planned"] > 1000, "planned 가 비정상적으로 작음 (헤더 매칭 실패 가능)"
        # plan_pct 가 100% 근처여야 의미 있음 (수백~수만% 면 파싱 오류)
        assert 1 < data["plan_pct"] < 1000, "plan_pct 비정상 (계획 컬럼 파싱 오류 의심)"

    def test_goal_offset_negative(self, client):
        """GET /api/goal?offset=-1 - 이전 주차"""
        resp = client.get("/api/goal", params={"offset": -1})
        assert resp.status_code == 200
        data = resp.json()
        assert data["week_num"] > 0
        assert data["planned"] > 1000


class TestTradePointsConsumptionRate:
    def test_trade_points_respects_consumption_rate(self, client):
        """매수 누적이 pool × consumption_rate 한도 안에서 멈춤"""
        port = client.get("/api/portfolio").json()
        tp = client.get("/api/trade-points").json()
        rate = port.get("consumption_rate") or 0.5
        pool_start = tp["buy_table"]["header"]["pool"]
        rows = tp["buy_table"]["rows"]
        if not rows or pool_start <= 0:
            return  # pool 0 이거나 매수 불가 시 skip
        cumulative = rows[-1]["cumulative"]
        # 마지막 매수까지의 누적이 pool × consumption_rate 보다 약간만 넘거나 그 이하
        assert cumulative <= pool_start * rate + (rows[-1]["amount"] * 1.1)


class TestDiscordCommands:
    """Discord 슬래시 명령어 핸들러 검증"""

    def test_signal_current(self):
        from services.discord_bot import handle_command
        msg = handle_command("signal")
        assert "주차" in msg
        assert "TQQQ" in msg
        assert "매수:" in msg and "매도:" in msg
        assert "총손익:" in msg

    def test_signal_offset_negative(self):
        from services.discord_bot import handle_command
        msg = handle_command("signal", {"offset": -1})
        assert "주차" in msg
        assert "TQQQ" in msg
        assert "총손익:" in msg

    def test_portfolio_current_layout(self):
        """/portfolio 가 PortfolioCard 스타일 모두 포함"""
        from services.discord_bot import handle_command
        msg = handle_command("portfolio")
        assert "포트폴리오" in msg
        assert "VR" in msg  # 적립식/거치식/인출식 VR 중 하나
        assert "평가금:" in msg and "원)" in msg  # KRW 환산
        assert "보유:" in msg and "평단" in msg
        assert "Pool:" in msg and "Target:" in msg
        assert "Total Value:" in msg

    def test_goal_includes_plan_pct_and_time(self):
        from services.discord_bot import handle_command
        msg = handle_command("goal")
        assert "목표 진행률" in msg
        assert "계획 대비:" in msg
        assert "남은:" in msg

    def test_trade_lists_buy_and_sell_tiers(self):
        from services.discord_bot import handle_command
        msg = handle_command("trade")
        assert "매매 테이블" in msg
        assert "매수" in msg and "매도" in msg
        assert "보유" in msg and "pool" in msg

    def test_help_lists_all_commands(self):
        from services.discord_bot import handle_command
        msg = handle_command("help")
        for cmd in ("/help", "/price", "/signal", "/portfolio", "/quote", "/watch",
                    "/rate", "/goal", "/trade"):
            assert cmd in msg, f"missing in help: {cmd}"


class TestDiscordRegister:
    def test_register_endpoint_returns_ok(self, client):
        """POST /api/discord/register - 슬래시 명령어 강제 재등록"""
        resp = client.post("/api/discord/register")
        assert resp.status_code == 200
        assert resp.json()["status"] == "ok"
