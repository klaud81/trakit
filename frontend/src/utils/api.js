/**
 * API 클라이언트
 *
 * 개발 환경: 백엔드 http://localhost:8000/api 에 직접 연결
 * Vite proxy 대신 직접 호출하여 CORS로 통신
 */
const API_BASE = import.meta.env.VITE_API_URL || 'http://localhost:8000/api';

export async function fetchApi(path) {
  try {
    const res = await fetch(`${API_BASE}${path}`);
    if (!res.ok) throw new Error(`API Error: ${res.status}`);
    return await res.json();
  } catch (e) {
    console.error(`API fetch failed: ${path}`, e);
    return null;
  }
}
