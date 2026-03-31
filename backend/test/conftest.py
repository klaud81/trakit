"""Trakit API 테스트 공통 설정"""
import sys
from pathlib import Path

# backend 디렉토리를 path에 추가
sys.path.insert(0, str(Path(__file__).parent.parent))

import pytest
from fastapi.testclient import TestClient
from app import app


@pytest.fixture
def client():
    """FastAPI 테스트 클라이언트"""
    return TestClient(app)
