import { useState, useEffect } from 'react';

const MENU = [
  { key: 'news', label: '뉴스', icon: '📰' },
  { key: 'tqqq', label: 'TQQQ', icon: '📊' },
];

function hashToKey() {
  const h = (window.location.hash || '').replace('#', '');
  return MENU.some((m) => m.key === h) ? h : 'tqqq';
}

export default function Sidebar({ newsAuthed, onNewsLogout }) {
  const [collapsed, setCollapsed] = useState(false);
  const [active, setActive] = useState(hashToKey());

  useEffect(() => {
    const onHashChange = () => setActive(hashToKey());
    window.addEventListener('hashchange', onHashChange);
    return () => window.removeEventListener('hashchange', onHashChange);
  }, []);

  return (
    <aside className={`sidebar ${collapsed ? 'collapsed' : ''}`}>
      <div className="sidebar-header">
        <span className="sidebar-logo">TRAKIT</span>
        <button
          className="sidebar-toggle"
          onClick={() => setCollapsed((v) => !v)}
          title={collapsed ? '메뉴 펼치기' : '메뉴 접기'}
        >
          {collapsed ? '»' : '«'}
        </button>
      </div>
      <nav className="sidebar-menu">
        {MENU.map((item) => (
          <a
            key={item.key}
            href={`#${item.key}`}
            className={`sidebar-item ${active === item.key ? 'active' : ''}`}
            title={item.label}
          >
            <span className="sidebar-icon">{item.icon}</span>
            <span className="sidebar-label">{item.label}</span>
          </a>
        ))}
      </nav>
      <div className="sidebar-auth">
        {newsAuthed ? (
          <>
            <div className="sidebar-auth-status" title="뉴스 로그인 성공 (1시간 유지)">
              <span className="sidebar-auth-dot" />
              <span className="sidebar-auth-label">로그인 성공</span>
            </div>
            <button
              className="sidebar-logout-btn"
              onClick={onNewsLogout}
              title="로그아웃"
            >
              <span className="sidebar-icon">⎋</span>
              <span className="sidebar-label">로그아웃</span>
            </button>
          </>
        ) : (
          <a
            href="#news"
            className="sidebar-login-btn"
            title="뉴스 로그인"
          >
            <span className="sidebar-icon">🔑</span>
            <span className="sidebar-label">로그인</span>
          </a>
        )}
      </div>
    </aside>
  );
}
