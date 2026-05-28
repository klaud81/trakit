/* KR 뉴스: 100m1s.com/news.html 셸을 frontend/public/kr-news/ 에 미러링.
   데이터/종목 페이지는 backend/scripts/kr_news_sync.py 가 주기적으로 동기화. */
export default function KrNewsPanel() {
  return (
    <iframe
      src="/kr-news/news.html"
      title="KR 뉴스"
      style={{
        width: '100%',
        height: 'calc(100vh - 16px)',
        border: 'none',
        display: 'block',
      }}
    />
  );
}
