// Records the real demo at :3000 through a CDP screencast: JPEG frames with wall-clock timestamps,
// at twice the CSS size so the 4K render shows the interface 1:1. The scale is the screen's
// (--force-device-scale-factor), not Playwright's emulated one: the screencast sends emulated
// pages at their CSS size.
//
// A drawn cursor and a ripple on every press (headless Chrome draws no pointer), real mouse
// steps with pauses, the estimator picked from its list, the seed typed, panes reordered by
// dragging. Every step is marked in frames.json for the edit and the camera.
//
// Usage, from this folder: node record.cjs SEED FRAMES_DIR
const fs = require('node:fs');
const { createRequire } = require('node:module');
const { chromium } = createRequire(`${__dirname}/../../frontend/package.json`)('@playwright/test');
const W = 1800, H = 837, SCALE = 2;
const out = process.argv[3] || `${__dirname}/frames`;
fs.mkdirSync(out, { recursive: true });

// Installed after hydration, so React never sees these nodes. The dev badge is hidden here
// too: hydration drops a style added before it.
function installCursor() {
  if (document.getElementById('__cursor')) return;
  const st = document.createElement('style');
  st.textContent = `
nextjs-portal{display:none!important}
#__cursor{position:fixed;left:0;top:0;width:32px;height:32px;z-index:2147483647;pointer-events:none}
#__cursor svg{display:block;width:32px;height:32px;transform-origin:5px 4px;transition:transform 90ms ease-out}
#__cursor.down svg{transform:scale(.85)}
.__ripple{position:fixed;z-index:2147483646;pointer-events:none;width:72px;height:72px;margin:-36px 0 0 -36px;border-radius:50%;
  border:3px solid rgba(37,99,235,.9);background:rgba(37,99,235,.2);animation:__rip 700ms cubic-bezier(.2,.7,.3,1) forwards}
@keyframes __rip{from{transform:scale(.2);opacity:1}to{transform:scale(1);opacity:0}}`;
  document.documentElement.appendChild(st);
  const c = document.createElement('div');
  c.id = '__cursor';
  c.innerHTML = '<svg viewBox="0 0 24 24"><path d="M4 3 L4 19.5 L8.4 15.4 L11.3 21.6 L14 20.4 L11.2 14.3 L17.2 14.3 Z" fill="#111" stroke="#fff" stroke-width="1.5" stroke-linejoin="round"/></svg>';
  document.documentElement.appendChild(c);
  const place = (x, y) => { c.style.transform = `translate(${x - 5}px, ${y - 4}px)`; };
  window.__placeCursor = place;
  const move = (e) => { if (e.clientX || e.clientY) place(e.clientX, e.clientY); };
  for (const t of ['mousemove', 'pointermove', 'dragover', 'drag']) document.addEventListener(t, move, true);
  const press = (x, y) => {
    c.classList.add('down');
    const r = document.createElement('div');
    r.className = '__ripple';
    r.style.left = `${x}px`;
    r.style.top = `${y}px`;
    document.documentElement.appendChild(r);
    setTimeout(() => r.remove(), 800);
  };
  document.addEventListener('mousedown', (e) => press(e.clientX, e.clientY), true);
  for (const t of ['mouseup', 'dragend', 'drop']) document.addEventListener(t, () => c.classList.remove('down'), true);
}

(async () => {
  // localhost pinned to IPv4: the API listens on 127.0.0.1 only, and anything else bound to
  // [::1]:8000 would answer instead.
  const b = await chromium.launch({ args: [`--force-device-scale-factor=${SCALE}`, `--window-size=${W},${H}`, '--host-resolver-rules=MAP localhost 127.0.0.1'] });
  const ctx = await b.newContext({ viewport: null });
  const p = await ctx.newPage();
  await p.addInitScript(() => { const st = document.createElement('style'); st.textContent = 'nextjs-portal{display:none!important}'; document.documentElement.appendChild(st); });
  await p.goto('http://localhost:3000', { waitUntil: 'networkidle' });
  await p.getByRole('button', { name: 'Generate sequence' }).waitFor();
  await p.waitForTimeout(500);
  await p.evaluate(installCursor);

  // The mouse, moved along an ease-in-out path so it reads as a hand, not a jump.
  let pos = { x: 1040, y: 470 };
  await p.mouse.move(pos.x, pos.y);
  const glide = async (x, y, ms = 700) => {
    const n = Math.max(2, Math.round(ms / 16));
    const from = { ...pos };
    for (let i = 1; i <= n; i++) {
      const t = i / n, e = t < 0.5 ? 4 * t * t * t : 1 - (-2 * t + 2) ** 3 / 2;
      await p.mouse.move(from.x + (x - from.x) * e, from.y + (y - from.y) * e);
      await p.waitForTimeout(16);
    }
    pos = { x, y };
  };
  const center = async (locator) => { const r = await locator.boundingBox(); return { x: r.x + r.width / 2, y: r.y + r.height / 2 }; };
  const click = async (locator, { before = 350, ms = 700 } = {}) => {
    const c = await center(locator);
    await glide(c.x, c.y, ms);
    await p.waitForTimeout(before);
    await p.mouse.down(); await p.waitForTimeout(90); await p.mouse.up();
  };

  const cdp = await ctx.newCDPSession(p);
  const frames = [];
  cdp.on('Page.screencastFrame', async ({ data, metadata, sessionId }) => {
    const name = `${String(frames.length).padStart(5, '0')}.jpg`;
    frames.push({ name, t: metadata.timestamp });
    fs.writeFileSync(`${out}/${name}`, Buffer.from(data, 'base64'));
    await cdp.send('Page.screencastFrameAck', { sessionId }).catch(() => {});
  });
  await cdp.send('Page.startScreencast', { format: 'jpeg', quality: 95, everyNthFrame: 1, maxWidth: W * SCALE, maxHeight: H * SCALE });
  const marks = {};
  const mark = (s) => { marks[s] = Date.now() / 1000; console.log(s); };
  mark('start');
  await p.waitForTimeout(1000);

  // 1. The depth estimator, from its list.
  mark('estimator');
  await click(p.locator('#library'), { ms: 900, before: 450 });
  mark('listOpen');
  await p.waitForTimeout(900);
  await click(p.getByRole('option', { name: 'da2-large' }), { ms: 650, before: 450 });
  mark('picked');
  await p.waitForTimeout(900);

  // 2. The seed, typed.
  mark('seed');
  const seed = p.getByRole('spinbutton', { name: 'Seed' });
  await click(seed, { ms: 750, before: 350 });
  await p.keyboard.press('ControlOrMeta+a');
  await p.keyboard.type(process.argv[2] || '2031', { delay: 190 });
  mark('typed');
  await p.waitForTimeout(900);

  // 3. Generate.
  const generate = p.getByRole('button', { name: 'Generate sequence' });
  const g = await center(generate);
  mark('toGenerate');
  await glide(g.x, g.y, 800);
  await p.waitForTimeout(500);
  mark('generate');
  await p.mouse.down(); await p.waitForTimeout(90); await p.mouse.up();
  await p.waitForTimeout(300);
  await glide(g.x + 260, g.y - 120, 600);
  await p.waitForFunction(() => [...document.querySelectorAll('video')].length >= 5 && [...document.querySelectorAll('video')].every((v) => v.readyState >= 2), null, { timeout: 180000 });
  mark('panes');
  await p.waitForTimeout(1500);

  // 4. Play, then out of the way.
  mark('play');
  await click(p.getByRole('button', { name: 'Play' }), { ms: 800, before: 450 });
  mark('playing');
  await p.waitForTimeout(300);
  await glide(1040, 700, 800);
  await p.waitForTimeout(3200);

  // 5. Reorder: Bokeh dragged next to All in focus.
  mark('drag');
  const grip = await center(p.getByRole('button', { name: 'Move Bokeh pane' }));
  await glide(grip.x, grip.y, 1000);
  await p.waitForTimeout(600);
  mark('down');
  await p.mouse.down();
  const alpha = await center(p.getByRole('button', { name: 'Move Alpha pane' }));
  await glide(grip.x - 20, grip.y + 6, 200);
  await glide(alpha.x + 60, alpha.y + 40, 1400);
  await p.waitForTimeout(600);
  await p.mouse.up();
  mark('drop');
  await p.waitForTimeout(700);
  await glide(1040, 700, 800);
  await p.waitForTimeout(3800);
  mark('end');

  await cdp.send('Page.stopScreencast');
  const order = await p.evaluate(() => [...document.querySelectorAll('figure')].map((f) => f.querySelector('button[aria-label^="Move"]')?.getAttribute('aria-label')));
  console.log('order', JSON.stringify(order));
  fs.writeFileSync(`${out}/frames.json`, JSON.stringify({ frames, marks }, null, 1));
  await ctx.close(); await b.close();
  console.log(frames.length, 'frames');
})();
