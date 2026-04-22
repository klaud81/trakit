import { useEffect, useMemo, useState } from 'react';
import { fetchApi } from '../utils/api';

function timeAgo(iso) {
  if (!iso) return '';
  const diffMs = Date.now() - new Date(iso).getTime();
  const m = Math.floor(diffMs / 60000);
  if (m < 1) return '방금';
  if (m < 60) return `${m}분 전`;
  const h = Math.floor(m / 60);
  if (h < 24) return `${h}시간 전`;
  const d = Math.floor(h / 24);
  return `${d}일 전`;
}

function formatCount(n) {
  if (n == null) return 0;
  if (n >= 1000) return `${(n / 1000).toFixed(1)}K`;
  return n;
}

const SOURCE_TABS = [
  { key: 'all', label: '전체', group: null },
  { key: 'save', label: '일반뉴스', group: 2 },
  { key: 'reuters', label: '로이터', group: 3 },
  { key: 'financial-juice', label: '파이낸셜뉴스', group: 4 },
];

// SAVE 뉴스 탭의 하위 카테고리는 label_name 값으로 구분
const SAVE_CATEGORIES = [
  { key: 1, label: '전체' },
  { key: 2, label: '종합' },
  { key: 3, label: '속보' },
  { key: 4, label: '정보' },
  { key: 5, label: '분석' },
  { key: 6, label: '암호화폐' },
  { key: 7, label: '경제지표' },
  { key: 8, label: '에너지' },
  { key: 9, label: '연준' },
  { key: 10, label: '일정' },
  { key: 11, label: '투자 의견' },
];

// 탭별 카테고리 정의 (key는 tag_name 매칭, 'all'은 전체, 'general'은 기타 일반)
const CATEGORIES_BY_TAB = {
  all: [
    { key: 'all', label: '전체' },
    { key: 'general', label: '종합' },
    { key: '속보', label: '속보' },
    { key: '분석', label: '분석' },
  ],
  reuters: [
    { key: 'all', label: '전체' },
    { key: 'general', label: '종합' },
    { key: '속보', label: '속보' },
    { key: '시황/분석', label: '시황/분석' },
  ],
  'financial-juice': [],
};

const SORT_OPTIONS = [
  { key: 'latest', label: '최신순' },
  { key: 'views', label: '조회순' },
];

function formatDateTime(iso) {
  if (!iso) return '';
  const d = new Date(iso);
  const pad = (n) => String(n).padStart(2, '0');
  return `${d.getFullYear()}. ${pad(d.getMonth() + 1)}. ${pad(d.getDate())}. ${pad(d.getHours())}:${pad(d.getMinutes())}:${pad(d.getSeconds())}`;
}

function TagBadge({ kind, children }) {
  return <span className={`news-md-tag news-md-tag-${kind}`}>{children}</span>;
}

function resolveTopTag(data) {
  const tags = data.tag_names || [];
  if (tags.includes('속보')) return '속보';
  if (tags.includes('시황/분석')) return '시황/분석';
  if (tags.includes('분석')) return '분석';
  if (tags.length > 0 && !tags[0].startsWith('$')) return tags[0];
  return null;
}

function NewsDetailModal({ id, onClose }) {
  const [data, setData] = useState(null);
  const [loading, setLoading] = useState(true);
  const [err, setErr] = useState(null);

  useEffect(() => {
    let cancelled = false;
    setLoading(true);
    fetchApi(`/news/detail/${id}`).then((r) => {
      if (cancelled) return;
      if (!r || !r.news) setErr('뉴스 상세를 불러올 수 없습니다.');
      else setData(r.news);
      setLoading(false);
    });
    const onKey = (e) => { if (e.key === 'Escape') onClose(); };
    window.addEventListener('keydown', onKey);
    document.body.style.overflow = 'hidden';
    return () => { cancelled = true; window.removeEventListener('keydown', onKey); document.body.style.overflow = ''; };
  }, [id, onClose]);

  const paragraphs = (data?.content || [])
    .map((b) => (b.type === 'text' ? b.content : ''))
    .join('')
    .split('\n')
    .map((s) => s.trim())
    .filter(Boolean);

  const isSave = data?.source && !['reuters', 'financial-juice'].includes(data.source);
  const topTag = data ? resolveTopTag(data) : null;

  return (
    <div className="news-modal-overlay" onClick={onClose}>
      <div className="news-modal" onClick={(e) => e.stopPropagation()}>
        <div className="news-modal-topbar">
          <div className="news-modal-tags">
            {isSave && <TagBadge kind="save">SAVE</TagBadge>}
            {topTag && <TagBadge kind="cat">{topTag}</TagBadge>}
          </div>
          <div className="news-modal-actions">
            <button className="news-modal-icon" title="북마크">🔖</button>
            <button className="news-modal-icon" title="더보기">⋮</button>
            <button className="news-modal-close" onClick={onClose} title="닫기">✕</button>
          </div>
        </div>
        {loading && <div className="news-loading"><div className="spinner" />불러오는 중...</div>}
        {err && <div className="news-error">{err}</div>}
        {data && (
          <article className="news-modal-body">
            <div className="news-modal-date">{formatDateTime(data.created_at)}</div>
            <h2 className="news-modal-title">{data.title}</h2>
            {paragraphs.length > 0 ? (
              <div className="news-modal-content">
                {paragraphs.map((p, i) => <p key={i}>{p}</p>)}
              </div>
            ) : (
              <div className="news-modal-empty">본문이 제공되지 않은 헤드라인 뉴스입니다.</div>
            )}
            <div className="news-modal-disclaimer">
              본 콘텐츠는 투자 권유 목적이 아닌 정보 제공용입니다.
            </div>
          </article>
        )}
      </div>
    </div>
  );
}

function SourceBadge({ source }) {
  const map = {
    reuters: { label: '로이터', cls: 'src-reuters' },
    save: { label: 'SAVE', cls: 'src-save' },
    'financial-juice': { label: '파이낸셜뉴스', cls: 'src-financialjuice' },
    bloomberg: { label: 'Bloomberg', cls: 'src-bloomberg' },
    cnbc: { label: 'CNBC', cls: 'src-cnbc' },
    미잔: { label: '미잔', cls: 'src-default' },
    뉴욕타임즈: { label: '뉴욕타임즈', cls: 'src-default' },
    워싱턴포스트: { label: '워싱턴포스트', cls: 'src-default' },
  };
  const s = map[source] || { label: source || 'SAVE', cls: 'src-save' };
  return <span className={`news-src-tag ${s.cls}`}>{s.label}</span>;
}

export default function NewsPanel() {
  const [items, setItems] = useState([]);
  const [page, setPage] = useState(1);
  const [loading, setLoading] = useState(false);
  const [hasMore, setHasMore] = useState(true);
  const [error, setError] = useState(null);

  const [openId, setOpenId] = useState(null);
  const [query, setQuery] = useState('');
  const [sourceTab, setSourceTab] = useState('all');
  const [tagCategory, setTagCategory] = useState('all');  // 기타 탭용 클라이언트 필터
  const [saveLabelName, setSaveLabelName] = useState(1); // SAVE 탭용 label_name
  const [sort, setSort] = useState('latest');
  const [topOpen, setTopOpen] = useState(true);

  const buildParams = (tabKey, saveLabel) => {
    const tab = SOURCE_TABS.find((t) => t.key === tabKey) || SOURCE_TABS[0];
    if (!tab.group) return '';
    const ln = tabKey === 'save' ? saveLabel : 1;
    return `&label_group=${tab.group}&label_name=${ln}`;
  };

  const loadPage = async (p, tabKey = sourceTab, saveLabel = saveLabelName) => {
    setLoading(true);
    const data = await fetchApi(`/news?page=${p}&page_size=30${buildParams(tabKey, saveLabel)}`);
    if (!data || !data.news_list) {
      setError('뉴스를 불러올 수 없습니다.');
      setHasMore(false);
    } else {
      setItems((prev) => p === 1 ? data.news_list : [...prev, ...data.news_list]);
      setHasMore(data.news_list.length >= 30);
      setError(null);
    }
    setLoading(false);
  };

  useEffect(() => { loadPage(1); setPage(1); }, []);

  const resetAndLoad = (tabKey, saveLabel) => {
    setPage(1);
    setItems([]);
    setHasMore(true);
    loadPage(1, tabKey, saveLabel);
  };

  const onSourceTab = (key) => {
    if (key === sourceTab) return;
    setSourceTab(key);
    setTagCategory('all');
    setSaveLabelName(1);
    resetAndLoad(key, 1);
  };

  const onSaveCategory = (labelName) => {
    if (labelName === saveLabelName) return;
    setSaveLabelName(labelName);
    resetAndLoad('save', labelName);
  };

  const filtered = useMemo(() => {
    let list = items;
    if (sourceTab !== 'save') {
      if (tagCategory === 'general') {
        list = list.filter((n) => {
          const tags = n.tag_names || [];
          return !tags.includes('속보') && !tags.includes('시황/분석') && !tags.includes('분석');
        });
      } else if (tagCategory === '분석') {
        list = list.filter((n) => {
          const tags = n.tag_names || [];
          return tags.includes('분석') || tags.includes('시황/분석');
        });
      } else if (tagCategory !== 'all') {
        list = list.filter((n) => (n.tag_names || []).includes(tagCategory));
      }
    }
    if (query.trim()) {
      const q = query.trim().toLowerCase();
      list = list.filter((n) => (n.title || '').toLowerCase().includes(q));
    }
    if (sort === 'views') list = [...list].sort((a, b) => (b.view_count || 0) - (a.view_count || 0));
    return list;
  }, [items, sourceTab, tagCategory, query, sort]);

  const topStories = useMemo(() => {
    const flagged = filtered.filter((n) => n.is_top_story);
    if (flagged.length >= 2) return flagged.slice(0, 4);
    return [...filtered].sort((a, b) => (b.view_count || 0) - (a.view_count || 0)).slice(0, 4);
  }, [filtered]);

  const topIds = useMemo(() => new Set(topStories.map((n) => n.id)), [topStories]);
  const mainList = useMemo(() => filtered.filter((n) => !topIds.has(n.id)), [filtered, topIds]);

  const onLoadMore = () => {
    const next = page + 1;
    setPage(next);
    loadPage(next, sourceTab);
  };

  const onRefresh = () => { setPage(1); setItems([]); setHasMore(true); loadPage(1, sourceTab); };

  return (
    <div className="news-panel">
      <div className="news-search">
        <span className="news-search-icon">🔍</span>
        <input
          type="text"
          placeholder="검색어 입력"
          value={query}
          onChange={(e) => setQuery(e.target.value)}
        />
      </div>

      <div className="news-source-tabs">
        {SOURCE_TABS.map((t) => (
          <button
            key={t.key}
            className={`news-source-tab ${sourceTab === t.key ? 'active' : ''}`}
            onClick={() => onSourceTab(t.key)}
          >
            {t.label}
          </button>
        ))}
      </div>

      {sourceTab === 'save' ? (
        <div className="news-pills">
          {SAVE_CATEGORIES.map((p) => (
            <button
              key={p.key}
              className={`news-pill ${saveLabelName === p.key ? 'active' : ''}`}
              onClick={() => onSaveCategory(p.key)}
            >
              {p.label}
            </button>
          ))}
        </div>
      ) : (CATEGORIES_BY_TAB[sourceTab] || []).length > 0 && (
        <div className="news-pills">
          {(CATEGORIES_BY_TAB[sourceTab] || []).map((p) => (
            <button
              key={p.key}
              className={`news-pill ${tagCategory === p.key ? 'active' : ''}`}
              onClick={() => setTagCategory(p.key)}
            >
              {p.label}
            </button>
          ))}
        </div>
      )}

      {topStories.length > 0 && (
        <section className="news-top">
          <div className="news-top-header" onClick={() => setTopOpen((v) => !v)}>
            <span className="news-top-title">🔥 오늘 주요뉴스</span>
            <span className="news-top-chevron">{topOpen ? '▲' : '▼'}</span>
          </div>
          {topOpen && (
            <div className="news-top-grid">
              {topStories.map((n) => (
                <article key={n.id} className="news-top-card" onClick={() => setOpenId(n.id)}>
                  <div className="news-top-meta">
                    <SourceBadge source={n.source} />
                    {(n.tag_names || []).slice(0, 1).map((t) => (
                      <span key={t} className="news-meta-sub">· {t}</span>
                    ))}
                    <span className="news-top-time">{timeAgo(n.created_at)}</span>
                  </div>
                  <h3 className="news-top-text">{n.title}</h3>
                  <div className="news-top-foot">
                    <span className="news-stat">👁 {formatCount(n.view_count)}</span>
                  </div>
                </article>
              ))}
            </div>
          )}
        </section>
      )}

      <section className="news-list-section">
        <div className="news-list-header">
          <h2 className="news-list-title">뉴스</h2>
          <div className="news-list-controls">
            <div className="news-sort">
              <span>전체 · </span>
              <select value={sort} onChange={(e) => setSort(e.target.value)}>
                {SORT_OPTIONS.map((o) => <option key={o.key} value={o.key}>{o.label}</option>)}
              </select>
            </div>
            <button className="news-refresh-btn" onClick={onRefresh} title="새로고침">↻</button>
          </div>
        </div>

        {error && <div className="news-error">{error}</div>}

        <div className="news-list">
          {mainList.map((n) => (
            <article key={n.id} className="news-row" onClick={() => setOpenId(n.id)}>
              <div className="news-row-main">
                <div className="news-row-meta">
                  <SourceBadge source={n.source} />
                  {(n.tag_names || []).slice(0, 1).map((t) => (
                    <span key={t} className="news-meta-sub">· {t}</span>
                  ))}
                </div>
                <h3 className="news-row-title">{n.title}</h3>
              </div>
              <div className="news-row-side">
                <span className="news-row-time">{timeAgo(n.created_at)}</span>
                <span className="news-stat">👁 {formatCount(n.view_count)}</span>
              </div>
            </article>
          ))}
          {mainList.length === 0 && !loading && (
            <div className="news-empty">표시할 뉴스가 없습니다.</div>
          )}
        </div>

        {loading && <div className="news-loading"><div className="spinner" />불러오는 중...</div>}
        {!loading && hasMore && items.length > 0 && (
          <button className="news-more-btn" onClick={onLoadMore}>더 보기</button>
        )}
      </section>

      {openId && <NewsDetailModal id={openId} onClose={() => setOpenId(null)} />}
    </div>
  );
}
