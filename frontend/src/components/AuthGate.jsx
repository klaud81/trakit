import { useState, useRef, useEffect } from 'react';

// scripts/daily-shot/shot.mjs 가 같은 키로 캡처용 세션을 넣으므로 바꿀 때 함께 수정
const STORAGE_KEY = 'trakit_news_auth_expiry';
const SESSION_TTL_MS = 60 * 60 * 1000; // 1시간

export function isAuthed() {
  try {
    const exp = parseInt(sessionStorage.getItem(STORAGE_KEY) || '0', 10);
    if (!exp) return false;
    if (Date.now() > exp) {
      sessionStorage.removeItem(STORAGE_KEY);
      return false;
    }
    return true;
  } catch {
    return false;
  }
}

export function setAuthed() {
  try { sessionStorage.setItem(STORAGE_KEY, String(Date.now() + SESSION_TTL_MS)); } catch {}
}

export function logout() {
  try { sessionStorage.removeItem(STORAGE_KEY); } catch {}
}

export function getAuthExpiry() {
  try {
    const exp = parseInt(sessionStorage.getItem(STORAGE_KEY) || '0', 10);
    return exp || 0;
  } catch { return 0; }
}

// TQQQ 탭 비밀번호 게이트 (검증은 백엔드 /api/news/auth — 시트 AQ1 비밀번호)
export default function AuthGate({ onSuccess, onCancel }) {
  const [pw, setPw] = useState('');
  const [err, setErr] = useState('');
  const [shake, setShake] = useState(false);
  const inputRef = useRef(null);

  useEffect(() => { inputRef.current?.focus(); }, []);

  const submit = async (e) => {
    e.preventDefault();
    try {
      const res = await fetch('/api/news/auth', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ password: pw }),
      });
      const data = await res.json();
      if (data.ok) {
        setAuthed();
        onSuccess();
        return;
      }
    } catch {}
    setErr('비밀번호가 일치하지 않습니다.');
    setShake(true);
    setTimeout(() => setShake(false), 400);
    setPw('');
    inputRef.current?.focus();
  };

  return (
    <div className="news-gate">
      <form className={`news-gate-card ${shake ? 'shake' : ''}`} onSubmit={submit}>
        <div className="news-gate-icon">🔒</div>
        <h2 className="news-gate-title">TQQQ</h2>
        <p className="news-gate-desc">TQQQ 페이지에 접근하려면 비밀번호를 입력하세요.</p>
        <input
          ref={inputRef}
          type="password"
          className="news-gate-input"
          placeholder="비밀번호"
          value={pw}
          onChange={(e) => { setPw(e.target.value); setErr(''); }}
          onKeyDown={(e) => { if (e.key === 'Enter') submit(e); }}
          autoComplete="off"
        />
        {err && <div className="news-gate-error">{err}</div>}
        <div className="news-gate-actions">
          <button type="button" className="news-gate-btn news-gate-btn-ghost" onClick={onCancel}>
            취소
          </button>
          <button type="submit" className="news-gate-btn news-gate-btn-primary">
            확인
          </button>
        </div>
      </form>
    </div>
  );
}
