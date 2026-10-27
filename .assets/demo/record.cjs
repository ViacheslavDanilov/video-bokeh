// Records the real demo at :3000 through a CDP screencast: JPEG frames with wall-clock timestamps.
// The window is 1920 x 1080 CSS px, the film's 16:9, on a 2x screen, so the frames are 3840 x 2160
// and the app fills them edge to edge. The scale is the screen's (--force-device-scale-factor), not
// Playwright's emulated one: the screencast sends emulated pages at their CSS size.
//
// Before the screencast starts, the page is set to SIZE and to OBJECTS objects and shows an
// earlier sequence (SETUP_SEED, from the first library, with the same number of objects) with its
// Alpha and Optical flow panes closed. A closed pane stays closed for the next sequence when the
// streams are the same, so the new sequence opens in three panes, All in focus, Disparity and
// Bokeh, and "Add pane" brings back Alpha, Optical flow and Occlusion, in that order.
//
// On camera: the estimator picked from its list, the seed typed, Generate and its progress bar,
// Play and Pause on frame PAUSE_AT, three panes added, the Bokeh pane dragged next to All in focus,
// a double-click that zooms every pane in on the hair, the position slider dragged frame by frame,
// a double-click back to the whole frame, Play. Headless Chrome draws no pointer, so a cursor is
// drawn, and it dips on each press.
// Every step and every press is marked in frames.json for the edit and the composition, and a
// frame in which a pane shows no frame yet carries a mark the edit leaves it out by. The cursor
// holds still until every pane has shown a frame, so none of the frames left out hides a move; the
// spans of every move are in frames.json for the edit to check it.
//
// Usage, from this folder: node record.cjs SEED FRAMES_DIR
const fs = require('node:fs');
const { createRequire } = require('node:module');
const { chromium } = createRequire(`${__dirname}/../../frontend/package.json`)('@playwright/test');
const W = 1920, H = 1080, SCALE = 2;
const SEED = process.argv[2] || '245';
const out = process.argv[3] || `${__dirname}/frames`;
// The sequence's size and its count of objects, set before the film starts.
const SIZE = 1024, OBJECTS = 2;
// The sequence on screen when the film starts: another seed, from the first library in the list,
// with the same two objects to two, a falcon and a taxi, and not the woman.
const SETUP_SEED = '6';
// The frame the film pauses on, adds the panes on and zooms in on, and how many frames the slider
// is then dragged through, one at a time. For seed 245, chosen by measuring the zoom window: her
// hair moves there, so Optical flow and Occlusion show it (frame 1 has neither), and she is in
// focus in Bokeh. Another seed needs its own.
const PAUSE_AT = 71, SCRUB_FRAMES = 4;
// Where the double-click zooms in, as fractions of the All in focus pane: the tips of her hair
// against the night sky around PAUSE_AT. The 4x view keeps this point where it is.
const HAIR = { x: 0.76, y: 0.16 };
const API = 'http://127.0.0.1:8000';
// Where the cursor waits once there are six panes: in the margin right of them.
const REST = { x: 1765, y: 600 };
fs.mkdirSync(out, { recursive: true });

// Installed after hydration, so React never sees these nodes. The dev badge is hidden here too:
// hydration drops a style added before it.
function installCursor() {
  if (document.getElementById('__cursor')) return;
  const st = document.createElement('style');
  st.textContent = `
nextjs-portal{display:none!important}
#__cursor{position:fixed;left:0;top:0;width:36px;height:36px;z-index:2147483647;pointer-events:none}
#__cursor svg{display:block;width:36px;height:36px;transform-origin:6px 5px;transition:transform 90ms ease-out}
#__cursor.down svg{transform:scale(.84)}`;
  document.documentElement.appendChild(st);
  const c = document.createElement('div');
  c.id = '__cursor';
  c.innerHTML = '<svg viewBox="0 0 24 24"><path d="M4 3 L4 19.5 L8.4 15.4 L11.3 21.6 L14 20.4 L11.2 14.3 L17.2 14.3 Z" fill="#111" stroke="#fff" stroke-width="1.5" stroke-linejoin="round"/></svg>';
  document.documentElement.appendChild(c);
  const place = (x, y) => { c.style.transform = `translate(${x - 6}px, ${y - 5}px)`; };
  const move = (e) => { if (e.clientX || e.clientY) place(e.clientX, e.clientY); };
  for (const t of ['mousemove', 'pointermove', 'dragover', 'drag']) document.addEventListener(t, move, true);
  document.addEventListener('mousedown', () => c.classList.add('down'), true);
  for (const t of ['mouseup', 'dragend', 'drop']) document.addEventListener(t, () => c.classList.remove('down'), true);
}

// At least `count` videos on the page, each showing a frame of the sequence of `seed`.
function ready({ seed, count }) {
  const info = document.querySelector('[aria-label="Sequence on screen"]');
  const videos = [...document.querySelectorAll('video')];
  return !!info && info.textContent.includes(`seed ${seed}`) && !document.querySelector('[aria-label="Generation progress"]')
    && videos.length >= count && videos.every((v) => v.readyState >= 2);
}

// Marks every frame in which some pane has no frame to show, its "Preparing video" placeholder
// up or its video not yet at a first frame, with a red square in the page's top left corner,
// clear otherwise. Checked on every animation frame, so the square and the panes are painted
// together, and edit.py leaves out the frames that carry it. A new pane's video counts as shown
// once it has a frame and has finished the seek to the transport's time; one that has shown a
// frame and only seeks again, as the slider makes it, does not count.
function watchPanes() {
  const shown = new WeakSet();
  const flag = document.createElement('div');
  flag.style.cssText = 'position:fixed;left:0;top:0;width:8px;height:8px;z-index:2147483647;pointer-events:none';
  document.documentElement.appendChild(flag);
  const tick = () => {
    const videos = [...document.querySelectorAll('video')];
    for (const v of videos) if (v.readyState >= 2 && !v.seeking) shown.add(v);
    const empty = videos.some((v) => !shown.has(v))
      || [...document.querySelectorAll('[data-pane-view]')].some((el) => el.textContent.includes('Preparing video'));
    flag.style.background = empty ? '#ff0000' : 'transparent';
    window.__empty = empty;
    requestAnimationFrame(tick);
  };
  requestAnimationFrame(tick);
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

  // Off camera: the size and the count of objects the film generates, then the sequence the film
  // opens on, in three panes. Raising the fewest objects raises the most with it, and lowering
  // the most lowers the fewest.
  const pick = async (trigger, option) => {
    await p.locator(trigger).click();
    await p.getByRole('option', { name: option, exact: true }).click();
  };
  await pick('#size', `${SIZE} × ${SIZE}`);
  await pick('#objects-min', `${OBJECTS}`);
  await pick('#objects-max', `${OBJECTS}`);
  const seedBox = p.getByRole('spinbutton', { name: 'Seed' });
  await seedBox.fill(SETUP_SEED);
  await p.getByRole('button', { name: 'Generate sequence' }).click();
  await p.waitForFunction(ready, { seed: SETUP_SEED, count: 5 }, { timeout: 300000 });
  await p.getByRole('button', { name: 'Close Alpha pane' }).click();
  await p.getByRole('button', { name: 'Close Optical flow pane' }).click();

  // The mouse, moved along an ease-in-out path so it reads as a hand, not a jump.
  let pos = { x: 1120, y: 940 };
  await p.mouse.click(pos.x, pos.y); // off every control, so nothing keeps the focus
  await p.waitForTimeout(1500);
  const moves = [];
  const glide = async (x, y, ms = 700) => {
    const n = Math.max(2, Math.round(ms / 16));
    const from = { ...pos };
    const began = Date.now() / 1000;
    for (let i = 1; i <= n; i++) {
      const t = i / n, e = t < 0.5 ? 4 * t * t * t : 1 - (-2 * t + 2) ** 3 / 2;
      await p.mouse.move(from.x + (x - from.x) * e, from.y + (y - from.y) * e);
      await p.waitForTimeout(16);
    }
    pos = { x, y };
    moves.push([began, Date.now() / 1000]);
  };
  const center = async (locator) => { const r = await locator.boundingBox(); return { x: r.x + r.width / 2, y: r.y + r.height / 2 }; };
  // Every press is timed too, for the click sounds.
  const presses = [];
  const down = async (options) => { presses.push(Date.now() / 1000); await p.mouse.down(options); };
  const press = async (count = 1) => { await down({ clickCount: count }); await p.waitForTimeout(90); await p.mouse.up({ clickCount: count }); };
  const click = async (locator, { before = 350, ms = 700 } = {}) => {
    const c = await center(locator);
    await glide(c.x, c.y, ms);
    await p.waitForTimeout(before);
    await press();
  };
  const doubleClick = async () => { await press(1); await p.waitForTimeout(70); await press(2); };

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
  await p.evaluate(watchPanes);
  mark('start');
  await p.waitForTimeout(1000);

  // 1. The depth estimator, from its list.
  mark('estimator');
  await click(p.locator('#library'), { ms: 900, before: 450 });
  mark('listOpen');
  await p.waitForTimeout(700);
  await click(p.getByRole('option', { name: 'da2-large' }), { ms: 650, before: 450 });
  mark('picked');
  await p.waitForTimeout(600);

  // 2. The seed, typed.
  mark('seed');
  await click(seedBox, { ms: 750, before: 350 });
  await p.keyboard.press('ControlOrMeta+a');
  await p.keyboard.type(SEED, { delay: 190 });
  mark('typed');
  await p.waitForTimeout(600);

  // 3. Generate, then wait for every pane of the new sequence. Then the API is asked for the
  // videos of the streams still to be added, as an earlier look at those panes would have: it
  // encodes a video the first time it is asked, and asked again until it answers at once, each
  // video is on disk before its pane asks for it.
  const generate = p.getByRole('button', { name: 'Generate sequence' });
  const g = await center(generate);
  mark('toGenerate');
  await glide(g.x, g.y, 800);
  await p.waitForTimeout(400);
  mark('generate');
  await press();
  await p.waitForTimeout(300);
  await glide(g.x + 520, g.y + 160, 700);
  await p.waitForFunction(ready, { seed: SEED, count: 3 }, { timeout: 300000, polling: 50 });
  mark('panes');
  const id = (await p.evaluate(() => document.querySelector('video').currentSrc)).split('/sequences/')[1].split('/')[0];
  const warm = async (stream) => {
    for (;;) {
      const t = Date.now();
      await fetch(`${API}/sequences/${id}/${stream}.mp4`).then((r) => r.arrayBuffer());
      if (Date.now() - t < 300) return;
    }
  };
  const warmed = Promise.all(['alpha', 'flow', 'occlusion'].map(warm));
  await p.waitForTimeout(1200);

  // 4. Play for a moment, and pause on PAUSE_AT. The press lands about three frames after it is
  // made, so it is made that much earlier.
  await click(p.getByRole('button', { name: 'Play' }), { ms: 800, before: 300 });
  mark('play1');
  await p.waitForFunction((at) => {
    const v = document.querySelector('video');
    return v.currentTime / v.duration * 80 >= at;
  }, PAUSE_AT - 1 - 3, { polling: 'raf' });
  await press();
  mark('paused');
  const position = p.getByRole('slider', { name: 'Position' });
  await p.waitForTimeout(300);
  console.log('paused on', await position.getAttribute('aria-valuetext'));
  await p.waitForTimeout(900);
  mark('chapter2');
  await Promise.all([warmed, p.waitForTimeout(2300)]); // under the chapter sheet
  mark('warmed');

  // 5. Three more panes, one per click on "Add pane", which moves as the grid rearranges. The
  // cursor waits for each new pane's first frame before it moves on.
  for (const [i, ms] of [[1, 900], [2, 600], [3, 600]]) {
    await click(p.getByRole('button', { name: 'Add pane' }), { ms, before: 300 });
    mark(`add${i}`);
    await p.waitForFunction(ready, { seed: SEED, count: 3 + i }, { timeout: 60000, polling: 20 });
    // Still until every pane has shown a frame, and a moment more for that frame to be painted.
    await p.waitForFunction(() => window.__empty === false, null, { timeout: 60000, polling: 'raf' });
    await p.waitForTimeout(120);
    if (i < 3) await p.waitForTimeout(530);
  }
  mark('six');

  // 6. Reorder: Bokeh dragged next to All in focus, in front of Disparity. The cursor leaves
  // as soon as the last pane has shown a frame, by the margin right of the panes: the last pane opens over the button, and a legend's
  // tooltip opens as soon as the pointer is over it.
  mark('drag');
  await glide(REST.x - 10, pos.y - 60, 350);
  const grip = await center(p.getByRole('button', { name: 'Move Bokeh pane' }));
  await glide(grip.x, grip.y, 900);
  await p.waitForTimeout(450);
  mark('down');
  await down();
  const disparity = await center(p.getByRole('button', { name: 'Move Disparity pane' }));
  await glide(grip.x - 20, grip.y + 6, 200);
  await glide(disparity.x + 60, disparity.y + 40, 1300);
  await p.waitForTimeout(500);
  await p.mouse.up();
  mark('drop');
  await p.waitForTimeout(500);
  await glide(REST.x, REST.y, 800);
  await p.waitForTimeout(600);
  mark('chapter3');
  await p.waitForTimeout(2300); // under the chapter sheet

  // 7. Every pane zoomed in on the hair, by a double-click on All in focus.
  const view = await p.locator('figure').first().locator('[data-pane-view]').boundingBox();
  await glide(view.x + HAIR.x * view.width, view.y + HAIR.y * view.height, 1000);
  await p.waitForTimeout(450);
  mark('zoom');
  await doubleClick();
  await p.waitForTimeout(1100);

  // 8. The position slider, dragged one frame at a time from the frame on screen. The track maps
  // its width to the 79 steps between frames, so the press is made where that frame sits on it, a
  // third of a step on, rather than at the thumb's center, which can be a frame off.
  const thumb = await center(position);
  const track = await p.locator('[data-slot="slider"]', { has: position }).locator('[data-slot="slider-track"]').boundingBox();
  const shown = Number((await position.getAttribute('aria-valuetext')).match(/Frame (\d+)/)[1]);
  const perFrame = track.width / 79;
  const grab = { x: track.x + (shown - 1 + 0.3) * perFrame, y: thumb.y };
  // Down the first column, whose legend has no tooltip, then along the transport: a legend's
  // tooltip opens as soon as the pointer crosses it.
  const lane = view.x + 0.15 * view.width;
  await glide(lane, grab.y, 600);
  await glide(grab.x, grab.y, 500);
  await p.waitForTimeout(300);
  mark('scrub');
  await down();
  for (let i = 1; i <= SCRUB_FRAMES; i++) {
    await glide(grab.x + i * perFrame, grab.y, 80);
    await p.waitForTimeout(420);
  }
  await p.mouse.up();
  mark('scrubbed');
  console.log('at', await position.getAttribute('aria-valuetext'));
  await p.waitForTimeout(500);

  // 9. Back to the whole frame, the same way, then play.
  await glide(lane, grab.y, 450);
  await glide(view.x + 0.5 * view.width, view.y + 0.55 * view.height, 650);
  await p.waitForTimeout(250);
  mark('unzoom');
  await doubleClick();
  await p.waitForTimeout(600);
  await click(p.getByRole('button', { name: 'Play' }), { ms: 800, before: 300 });
  mark('play');
  await p.waitForTimeout(250);
  await glide(REST.x, REST.y, 900);
  await p.waitForTimeout(2600);
  mark('end');

  await cdp.send('Page.stopScreencast');
  const order = await p.evaluate(() => [...document.querySelectorAll('figure')].map((f) => f.querySelector('button[aria-label^="Move"]')?.getAttribute('aria-label')));
  console.log('order', JSON.stringify(order));
  fs.writeFileSync(`${out}/frames.json`, JSON.stringify({ frames, marks, presses, moves, sequence: id }, null, 1));
  await ctx.close(); await b.close();
  console.log(frames.length, 'frames');
})();
