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

// 주제 탭 — 백엔드 nasdaq_news.NEWS_TOPICS 키와 동일 (Google News RSS 검색)
const TOPIC_TABS = [
  { key: 'market', label: '미국 증시' },
  { key: 'bigtech', label: '빅테크' },
  { key: 'fed', label: '연준' },
  { key: 'indicators', label: '경제지표' },
  { key: 'tariff', label: '관세' },
  { key: 'war', label: '지정학' },
];

const PAGE_SIZE = 30;

function SourceBadge({ source }) {
  return <span className="news-src-tag src-default">{source || '뉴스'}</span>;
}

// RSS 는 본문을 주지 않으므로 원문 기사를 새 탭으로 연다
function openArticle(n) {
  if (n.link) window.open(n.link, '_blank', 'noopener,noreferrer');
}

export default function NewsPanel() {
  const [items, setItems] = useState([]);
  const [page, setPage] = useState(1);
  const [loading, setLoading] = useState(false);
  const [hasMore, setHasMore] = useState(true);
  const [error, setError] = useState(null);
  const [query, setQuery] = useState('');
  const [topic, setTopic] = useState('market');

  const loadPage = async (p, topicKey = topic) => {
    setLoading(true);
    const data = await fetchApi(`/news?topic=${topicKey}&page=${p}&page_size=${PAGE_SIZE}`);
    if (!data || !data.news_list) {
      setError('뉴스를 불러올 수 없습니다.');
      setHasMore(false);
    } else {
      setItems((prev) => (p === 1 ? data.news_list : [...prev, ...data.news_list]));
      setHasMore(p * PAGE_SIZE < data.total_count);
      setError(null);
    }
    setLoading(false);
  };

  useEffect(() => { loadPage(1); }, []);

  const resetAndLoad = (topicKey) => {
    setPage(1);
    setItems([]);
    setHasMore(true);
    loadPage(1, topicKey);
  };

  const onTopic = (key) => {
    if (key === topic) return;
    setTopic(key);
    resetAndLoad(key);
  };

  const filtered = useMemo(() => {
    const q = query.trim().toLowerCase();
    if (!q) return items;
    return items.filter((n) => (n.title || '').toLowerCase().includes(q));
  }, [items, query]);

  const onLoadMore = () => {
    const next = page + 1;
    setPage(next);
    loadPage(next);
  };

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
        {TOPIC_TABS.map((t) => (
          <button
            key={t.key}
            className={`news-source-tab ${topic === t.key ? 'active' : ''}`}
            onClick={() => onTopic(t.key)}
          >
            {t.label}
          </button>
        ))}
      </div>

      <section className="news-list-section">
        <div className="news-list-header">
          <h2 className="news-list-title">뉴스</h2>
          <div className="news-list-controls">
            <span className="news-sort">최근 2일 · 최신순</span>
            <button className="news-refresh-btn" onClick={() => resetAndLoad(topic)} title="새로고침">↻</button>
          </div>
        </div>

        {error && <div className="news-error">{error}</div>}

        <div className="news-list">
          {filtered.map((n) => (
            <article key={n.id} className="news-row" onClick={() => openArticle(n)}>
              <div className="news-row-main">
                <div className="news-row-meta">
                  <SourceBadge source={n.source} />
                </div>
                <h3 className="news-row-title">{n.title}</h3>
              </div>
              <div className="news-row-side">
                <span className="news-row-time">{timeAgo(n.created_at)}</span>
              </div>
            </article>
          ))}
          {filtered.length === 0 && !loading && (
            <div className="news-empty">표시할 뉴스가 없습니다.</div>
          )}
        </div>

        {loading && <div className="news-loading"><div className="spinner" />불러오는 중...</div>}
        {!loading && hasMore && items.length > 0 && (
          <button className="news-more-btn" onClick={onLoadMore}>더 보기</button>
        )}
        <div className="news-modal-disclaimer">
          출처: Google 뉴스 검색. 본 콘텐츠는 투자 권유 목적이 아닌 정보 제공용입니다.
        </div>
      </section>
    </div>
  );
}
