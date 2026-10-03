// Site-surface probe (read-only GET). Baseline: see ../README.md
//
//   PW_CORE  optional absolute path to playwright-core/index.js
//            (default: bare specifier 'playwright-core', resolved from cwd/node_modules)
//   OUT      optional screenshot output dir (default: ./shots next to this script)
//
import fs from 'node:fs';
import path from 'node:path';
import { fileURLToPath } from 'node:url';

const __dir = path.dirname(fileURLToPath(import.meta.url));
const PW_CORE = process.env.PW_CORE || 'playwright-core';
const { chromium } = await import(PW_CORE);
const B = 'https://staging-api.goaidirect.com';
const OUT = process.env.OUT || path.join(__dir, 'shots');
fs.mkdirSync(OUT, { recursive: true });
const targets = [
  { name: 'root-404', url: B + '/', vp: { width: 1440, height: 900 } },
  { name: 'consumer-desktop', url: B + '/go-app/', vp: { width: 1440, height: 900 } },
  { name: 'consumer-mobile', url: B + '/go-app/', vp: { width: 390, height: 844 } },
  { name: 'admin-desktop', url: B + '/go-admin/', vp: { width: 1440, height: 900 } },
];
const b = await chromium.launch({ executablePath: 'C:/Program Files/Google/Chrome/Application/chrome.exe', headless: true });
const out = [];
for (const t of targets) {
  const ctx = await b.newContext({ viewport: t.vp, locale: 'zh-CN' });
  const page = await ctx.newPage();
  const errs = []; const statuses = [];
  page.on('pageerror', e => errs.push('PAGEERROR ' + e.message));
  page.on('console', m => { if (m.type() === 'error') errs.push('CONSOLE ' + m.text().slice(0, 200)); });
  page.on('response', r => statuses.push(r.status() + ' ' + r.url().replace(B, '')));
  let gotoErr = null;
  try { await page.goto(t.url, { waitUntil: 'networkidle', timeout: 45000 }); }
  catch (e) { gotoErr = String(e).slice(0, 160); }
  await page.waitForTimeout(800);
  await page.screenshot({ path: `${OUT}/${t.name}.png`, fullPage: false });
  await page.screenshot({ path: `${OUT}/${t.name}-full.png`, fullPage: true });
  const info = await page.evaluate(() => ({
    title: document.title,
    h1: document.querySelector('h1')?.textContent?.trim(),
    text: document.body.innerText.replace(/\n{2,}/g, '\n').trim().slice(0, 900),
    buttons: [...document.querySelectorAll('button,a.btn')].map(x => x.textContent.trim()).filter(Boolean).slice(0, 25),
    inputs: [...document.querySelectorAll('input')].map(i => ({ id: i.id, type: i.type, ph: i.placeholder || null })).slice(0, 20),
    docH: document.documentElement.scrollHeight,
    overflowX: document.documentElement.scrollWidth > window.innerWidth,
    links: [...document.querySelectorAll('a')].map(a => a.getAttribute('href')).filter(Boolean).slice(0, 20),
  }));
  info.name = t.name; info.vp = t.vp; info.gotoErr = gotoErr; info.errors = errs.slice(0, 6);
  info.failedRequests = statuses.filter(s => !/^2|^3/.test(s)).slice(0, 10);
  out.push(info);
  console.log('=== ' + t.name + ' ===');
  console.log('  gotoErr:', gotoErr, '| title:', info.title, '| h1:', info.h1);
  console.log('  text:', JSON.stringify(info.text.slice(0, 320)));
  console.log('  buttons:', JSON.stringify(info.buttons));
  console.log('  errors:', JSON.stringify(info.errors));
  console.log('  non-2xx:', JSON.stringify(info.failedRequests));
  await ctx.close();
}
await b.close();
fs.writeFileSync(path.join(OUT, '..', 'surface-results.json'), JSON.stringify(out, null, 2));
