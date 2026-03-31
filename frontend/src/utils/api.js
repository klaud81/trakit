/**
 * API 클라이언트
 *
 * 개발 환경: Vite proxy를 통해 /api로 호출
 * 배포 환경: nginx proxy를 통해 /api로 호출
 */
const API_BASE = import.meta.env.VITE_API_URL || '/api';

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
