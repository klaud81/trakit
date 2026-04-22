import { useState, useRef, useEffect } from 'react';

const NEWS_PASSWORD = 'trakit-tq3609';
const STORAGE_KEY = 'trakit_news_auth_expiry';
const SESSION_TTL_MS = 60 * 60 * 1000; // 1시간

export function isNewsAuthed() {
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

export function setNewsAuthed() {
  try { sessionStorage.setItem(STORAGE_KEY, String(Date.now() + SESSION_TTL_MS)); } catch {}
}

export function logoutNews() {
  try { sessionStorage.removeItem(STORAGE_KEY); } catch {}
}

export function getNewsAuthExpiry() {
  try {
    const exp = parseInt(sessionStorage.getItem(STORAGE_KEY) || '0', 10);
    return exp || 0;
  } catch { return 0; }
}

export default function NewsGate({ onSuccess, onCancel }) {
  const [pw, setPw] = useState('');
  const [err, setErr] = useState('');
  const [shake, setShake] = useState(false);
  const inputRef = useRef(null);

  useEffect(() => { inputRef.current?.focus(); }, []);

  const submit = (e) => {
    e.preventDefault();
    if (pw === NEWS_PASSWORD) {
      setNewsAuthed();
      onSuccess();
    } else {
      setErr('비밀번호가 일치하지 않습니다.');
      setShake(true);
      setTimeout(() => setShake(false), 400);
      setPw('');
      inputRef.current?.focus();
    }
  };

  return (
    <div className="news-gate">
      <form className={`news-gate-card ${shake ? 'shake' : ''}`} onSubmit={submit}>
        <div className="news-gate-icon">🔒</div>
        <h2 className="news-gate-title">뉴스</h2>
        <p className="news-gate-desc">뉴스 페이지에 접근하려면 비밀번호를 입력하세요.</p>
        <input
          ref={inputRef}
          type="password"
          className="news-gate-input"
          placeholder="비밀번호"
          value={pw}
          onChange={(e) => { setPw(e.target.value); setErr(''); }}
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
