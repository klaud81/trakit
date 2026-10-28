// TQQQ 대시보드 일일 스샷 → Discord 전송.
// :5173/#tqqq 를 Goal Progress 카드까지 클립 캡처 → data/daily-shots/tqqq-YYYY-MM-DD.png 저장 → 웹훅 첨부.
// env: PW_PKG(전역 playwright index.js), DISCORD_WEBHOOK_URL, DISCORD_BOT_TOKEN?, DISCORD_PUSH_CHANNEL_IDS?, SHOT_URL?, SHOT_DIR?
import fs from 'node:fs';
import path from 'node:path';

const PW = process.env.PW_PKG;
const WEBHOOK = process.env.DISCORD_WEBHOOK_URL || '';
const BOT_TOKEN = process.env.DISCORD_BOT_TOKEN || '';
// 웹훅 외에 봇으로 함께 푸시할 채널 ID (쉼표 구분)
const CHANNEL_IDS = (process.env.DISCORD_PUSH_CHANNEL_IDS || '').split(',').map(s => s.trim()).filter(Boolean);
const URL = process.env.SHOT_URL || 'http://localhost:5173/#tqqq';
const OUTDIR = process.env.SHOT_DIR || 'data/daily-shots';

if (!PW) { console.error('❌ PW_PKG 미설정 (전역 playwright index.js 경로)'); process.exit(2); }
const { chromium } = (await import(PW)).default;

// KST 날짜 (파일명/메시지)
const kst = new Date(Date.now() + 9 * 3600 * 1000);
const date = kst.toISOString().slice(0, 10);
fs.mkdirSync(OUTDIR, { recursive: true });
const OUT = path.join(OUTDIR, `tqqq-${date}.png`);

const browser = await chromium.launch();
try {
  const page = await browser.newPage({ viewport: { width: 1440, height: 3400 }, deviceScaleFactor: 2 });
  // #tqqq 비밀번호 게이트(AuthGate)는 sessionStorage 의 만료시각으로 로그인 판정 →
  // 페이지 스크립트 실행 전에 1시간 세션을 넣어 로그인된 화면을 캡처한다.
  // 키는 frontend/src/components/AuthGate.jsx 의 STORAGE_KEY 와 같아야 함.
  await page.addInitScript(() => {
    sessionStorage.setItem('trakit_news_auth_expiry', String(Date.now() + 60 * 60 * 1000));
  });
  await page.goto(URL, { waitUntil: 'domcontentloaded', timeout: 30000 });
  await page.waitForFunction(
    () => [...document.querySelectorAll('.card-title')].some(t => t.textContent.includes('Goal Progress')),
    { timeout: 25000 });
  await page.waitForTimeout(1500); // 차트/데이터 안정화
  const box = await page.evaluate(() => {
    const gt = [...document.querySelectorAll('.card-title')].find(t => t.textContent.includes('Goal Progress'));
    const card = gt.closest('.card');
    const r = card.getBoundingClientRect();
    return { bottom: r.bottom + window.scrollY, width: document.documentElement.scrollWidth };
  });
  await page.screenshot({ path: OUT, clip: { x: 0, y: 0, width: box.width, height: Math.ceil(box.bottom) + 20 } });
  console.log('📸 saved', OUT);
} finally {
  await browser.close();
}

if (!WEBHOOK) { console.error('❌ DISCORD_WEBHOOK_URL 미설정 — 전송 스킵'); process.exit(1); }
const buf = fs.readFileSync(OUT);
const content = `📊 ${date} TQQQ 대시보드 — 시그널·매수/매도·Goal`;
const form = (payload) => {
  const fd = new FormData();
  fd.append('payload_json', JSON.stringify(payload));
  fd.append('files[0]', new Blob([buf], { type: 'image/png' }), `tqqq-${date}.png`);
  return fd;
};
const r = await fetch(WEBHOOK, { method: 'POST', body: form({ username: 'TRAKIT', content }), headers: { 'User-Agent': 'TRAKIT/1.0' } });
console.log('📨 discord', r.status);
if (!(r.status === 200 || r.status === 204)) { console.error(await r.text()); process.exit(1); }

for (const ch of BOT_TOKEN ? CHANNEL_IDS : []) {
  const rc = await fetch(`https://discord.com/api/v10/channels/${ch}/messages`, {
    method: 'POST', body: form({ content }),
    headers: { 'User-Agent': 'TRAKIT/1.0', Authorization: `Bot ${BOT_TOKEN}` },
  });
  console.log(`📨 discord channel ${ch}`, rc.status);
  if (rc.status !== 200) console.error(await rc.text());
}
