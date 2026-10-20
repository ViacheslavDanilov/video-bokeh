import { execFileSync } from "node:child_process";
import { rmSync } from "node:fs";
import os from "node:os";
import path from "node:path";
import { expect, type Locator, type Page, test } from "@playwright/test";

// Where playwright.config.ts points the API, so a test can write into a sequence as
// Stage C would.
const SEQUENCES = path.join(os.tmpdir(), "video-bokeh-e2e", "sequences");
const LIBRARIES = path.join(os.tmpdir(), "video-bokeh-e2e", "library");

/** Open the page once its library is ready to generate. */
async function openPage(page: Page) {
  await page.goto("/");
  await expect(page.getByText("2 objects, 2 backgrounds")).toBeVisible();
}

/** Generate with the current parameters, optionally choosing a seed first. */
async function generateSequence(page: Page, seed?: number) {
  if (seed !== undefined)
    await page.getByRole("spinbutton", { name: "Seed" }).fill(String(seed));
  await page.getByRole("button", { name: "Generate sequence" }).click();
  const videos = page.locator("video");
  await expect(videos).toHaveCount(4, { timeout: 60_000 });
  return videos;
}

/** readyState 2 is HAVE_CURRENT_DATA: the file arrived and a frame was decoded. */
async function waitForDecoded(videos: Locator) {
  await expect
    .poll(
      async () =>
        Math.min(
          ...(await videos.evaluateAll((els) =>
            els.map((el) => (el as HTMLVideoElement).readyState),
          )),
        ),
      { timeout: 60_000 },
    )
    .toBeGreaterThanOrEqual(2);
}

/** Run a fixture script with the API's Python environment. */
function runBackend(script: string, ...args: string[]) {
  execFileSync("uv", [
    "run",
    "--directory",
    "../backend",
    "--extra",
    "api",
    "python",
    script,
    ...args,
  ]);
}

/** Write bokeh into the sequence on screen, as Stage C would: the API here renders none of
 *  its own, as without torch, so the stream is faked into the sequence on disk. */
async function fakeBokeh(page: Page) {
  const id = await page
    .getByRole("group", { name: "Sequence on screen" })
    .getByText(/^[0-9a-f]{16}$/)
    .innerText();
  runBackend("tests/api/fake_bokeh.py", path.join(SEQUENCES, id));
}

/** The streams of the panes, left to right. */
function streamsInOrder(page: Page): Promise<string[]> {
  return page.getByRole("combobox", { name: "Stream" }).allInnerTexts();
}

/** Start a native grip drag without dropping, so its feedback can be checked. */
async function startPaneDrag(page: Page, name: string) {
  const grip = page.getByRole("button", { name: `Move ${name} pane` });
  await grip.scrollIntoViewIfNeeded();
  const box = (await grip.boundingBox())!;
  const x = box.x + box.width / 2;
  const y = box.y + box.height / 2;
  await page.mouse.move(x, y);
  await page.mouse.down();
  await page.mouse.move(x + 12, y, { steps: 5 });
}

/** Every stream's full label fits its value and the header stays within the pane. */
async function expectFullStreamLabels(page: Page, labels: string[]) {
  const pickers = page.getByRole("combobox", { name: "Stream" });
  await expect(pickers).toHaveText(labels);
  await expect
    .poll(() =>
      pickers.evaluateAll((els) =>
        els.map((el) => {
          const value = el.querySelector('[data-slot="select-value"]')!;
          const header = el.closest("figcaption")!;
          return (
            value.scrollWidth <= value.clientWidth &&
            header.scrollWidth <= header.clientWidth
          );
        }),
      ),
    )
    .toEqual(labels.map(() => true));
}

/**
 * One path through the page, against the real API and a tiny real library: the library
 * loads, a sequence generates, and every stream the server lists reaches the browser as
 * video it can decode. This proves the wiring, not how the frames look.
 */
test("generates a sequence and decodes every stream", async ({ page }) => {
  await openPage(page);

  // all_in_focus, alpha, disparity and flow: one pane per stream the sequence has.
  const videos = await generateSequence(page);
  await expect(
    page.getByRole("combobox", { name: "Stream" }).nth(3),
  ).toHaveText("Optical flow");

  await waitForDecoded(videos);

  // The library holds two foregrounds, so the sequence places both, and the mask legend
  // names each of them.
  await expect(page.getByText(/^Object \d+$/)).toHaveCount(2);
  // Scoped to <main>: Next.js adds an empty route announcer with the same role.
  await expect(page.getByRole("main").getByRole("alert")).toHaveCount(0);
});

/**
 * The speed belongs to the viewer, not to one element: every pane plays at it, and a pane
 * whose source is swapped keeps it, although loading a new source resets an element's rate.
 */
test("sets every pane to the chosen speed", async ({ page }) => {
  await openPage(page);
  const videos = await generateSequence(page);

  const rates = () =>
    videos.evaluateAll((els) =>
      els.map((el) => (el as HTMLVideoElement).playbackRate),
    );

  await page.getByRole("combobox", { name: "Playback speed" }).click();
  await page.getByRole("option", { name: "0.5×" }).click();
  await expect.poll(rates).toEqual([0.5, 0.5, 0.5, 0.5]);

  await page.getByRole("combobox", { name: "Stream" }).first().click();
  await page.getByRole("option", { name: "Disparity" }).click();
  await expect
    .poll(() =>
      videos.first().evaluate((el) => (el as HTMLVideoElement).currentSrc),
    )
    .toContain("disparity");
  await expect.poll(rates).toEqual([0.5, 0.5, 0.5, 0.5]);
});

/**
 * The picker chooses the library a sequence comes from, and the sequence keeps naming its
 * own estimator after the picker moves on, so what is playing is never mislabeled.
 */
test("generates from the depth estimator picked", async ({ page }) => {
  await openPage(page);
  const header = page.getByRole("banner");
  await expect(header.getByText("da2-small")).toBeVisible();

  const picker = page.getByRole("combobox", { name: "Depth estimator" });
  await picker.click();
  await expect(page.getByRole("option")).toHaveText(["da2-small", "depth-pro"]);
  await page.getByRole("option", { name: "depth-pro" }).click();
  await expect(header.getByText("depth-pro")).toBeVisible();

  await generateSequence(page);
  const shown = page.getByRole("group", { name: "Sequence on screen" });
  await expect(shown).toContainText("depth-pro");

  await picker.click();
  await page.getByRole("option", { name: "da2-small" }).click();
  await expect(header.getByText("da2-small")).toBeVisible();
  await expect(shown).toContainText("depth-pro");
});

/**
 * A library built while the page is open shows in the picker once the page has focus
 * again, and a sequence from it is named by its directory as well as its estimator.
 */
test("lists a library built while the page is open", async ({ page }) => {
  await openPage(page);

  // Removed again, because the other tests expect exactly two libraries.
  const extra = path.join(LIBRARIES, "extra");
  try {
    runBackend("tests/api/fixture_library.py", extra, "da2-large");
    await page.evaluate(() => window.dispatchEvent(new Event("focus")));
    await page.getByRole("combobox", { name: "Depth estimator" }).click();
    await expect(page.getByRole("option")).toHaveCount(3);
    await page.getByRole("option", { name: /extra/ }).click();
    await generateSequence(page, 11);
    await expect(
      page.getByRole("group", { name: "Sequence on screen" }),
    ).toContainText("da2-large, extra");
  } finally {
    rmSync(extra, { recursive: true, force: true });
  }
});

/**
 * A list read that fails leaves an error; the next one that works, on focus, clears it.
 */
test("clears a failed library read once one works", async ({ page }) => {
  await page.route("**/libraries", (route) => route.abort());
  await page.goto("/");
  const alert = page.getByRole("main").getByRole("alert");
  await expect(alert).toHaveCount(1);

  await page.unroute("**/libraries");
  await page.evaluate(() => window.dispatchEvent(new Event("focus")));
  await expect(page.getByText("2 objects, 2 backgrounds")).toBeVisible();
  await expect(alert).toHaveCount(0);
});

/**
 * The parameters fold away to give the panes the width, and stay folded across a reload:
 * hiding them is a choice about the page, not about one sequence.
 */
test("hides the parameters and keeps them hidden after a reload", async ({
  page,
}) => {
  await openPage(page);
  const toggle = page.getByRole("button", { name: "Parameters" });
  const generate = page.getByRole("button", { name: "Generate sequence" });
  await expect(toggle).toHaveAttribute("aria-expanded", "true");
  await expect(generate).toBeVisible();

  await toggle.click();
  await expect(toggle).toHaveAttribute("aria-expanded", "false");
  await expect(generate).toBeHidden();

  await page.reload();
  await expect(toggle).toHaveAttribute("aria-expanded", "false");
  await expect(generate).toBeHidden();

  await toggle.click();
  await expect(generate).toBeVisible();
});

/**
 * Folding the parameters in one tab leaves another tab as it is until that one reloads:
 * the choice changes only when its own button is clicked, not at the next render.
 */
test("leaves the parameters in another tab as they are", async ({
  page,
  context,
}) => {
  await openPage(page);

  const other = await context.newPage();
  await openPage(other);
  await other.getByRole("button", { name: "Parameters" }).click();
  await expect(
    other.getByRole("button", { name: "Generate sequence" }),
  ).toBeHidden();

  // Any render of the first tab, here editing a parameter.
  await page.getByRole("spinbutton", { name: "Seed" }).fill("11");
  await expect(
    page.getByRole("button", { name: "Parameters" }),
  ).toHaveAttribute("aria-expanded", "true");
  await expect(
    page.getByRole("button", { name: "Generate sequence" }),
  ).toBeVisible();
});

/**
 * Five panes are too many for one row beside the parameters in a 1280 px window, so they
 * wrap, and into rows of three and two rather than four and one.
 */
test("wraps five panes into rows of three and two", async ({ page }) => {
  await page.setViewportSize({ width: 1280, height: 800 });
  await openPage(page);
  // A seed of its own: this test writes into its sequence.
  const videos = await generateSequence(page, 41);
  const labels = ["All in focus", "Alpha", "Disparity", "Optical flow"];
  await expectFullStreamLabels(page, labels);
  const generate = page.getByRole("button", { name: "Generate sequence" });

  // A fifth stream, since a pane is added only for a stream not on screen.
  await fakeBokeh(page);
  await generate.click();
  await expect(videos).toHaveCount(5, { timeout: 60_000 });
  await expect(
    page.getByRole("combobox", { name: "Stream" }).nth(4),
  ).toHaveText("Bokeh");
  await expect
    .poll(
      () => videos.nth(4).evaluate((el) => (el as HTMLVideoElement).readyState),
      { timeout: 60_000 },
    )
    .toBeGreaterThanOrEqual(2);

  const rows = async () => {
    const tops = await videos.evaluateAll((els) =>
      els.map((el) => Math.round(el.getBoundingClientRect().top)),
    );
    return [...new Set(tops)].map(
      (top) => tops.filter((t) => t === top).length,
    );
  };
  await expect.poll(rows).toEqual([3, 2]);
  await expectFullStreamLabels(page, [...labels, "Bokeh"]);

  // Two rows share the available height. Reduce it to reach the grid's 200 px minimum.
  const paneWidth = (await videos.first().boundingBox())!.width;
  await page.setViewportSize({
    width: 1280,
    height: 800 - 2 * (paneWidth - 200),
  });
  await expect
    .poll(async () => (await videos.first().boundingBox())!.width)
    .toBe(200);
  await expectFullStreamLabels(page, [...labels, "Bokeh"]);

  // Too low a window to show them all at a useful size: the panes take the width and the
  // page scrolls instead, and the rows still come out even, where four would fit across.
  await page.setViewportSize({ width: 1512, height: 450 });
  await expect
    .poll(async () => ({
      rows: await rows(),
      wide: (await videos.first().boundingBox())!.width > 300,
    }))
    .toEqual({ rows: [3, 2], wide: true });
});

/**
 * Generate takes seconds, so the page says what it is doing: the steps the API reports,
 * each pane until its video arrives, and then what is on screen. A second ask for the same
 * sequence comes from the cache and says so.
 */
test("shows the steps of a generation, then what is on screen", async ({
  page,
}) => {
  await openPage(page);
  // A seed of its own, so this generation is not a cache hit left by another test.
  await page.getByRole("spinbutton", { name: "Seed" }).fill("21");
  const generate = page.getByRole("button", { name: "Generate sequence" });
  await generate.click();

  const progress = page.getByRole("status", { name: "Generation progress" });
  // As shown: the line keeps every step's name in it, hidden, to hold its width.
  await expect(progress).toContainText("Rendering frames", {
    useInnerText: true,
  });
  await expect(progress).toBeHidden({ timeout: 60_000 });

  const videos = page.locator("video");
  await expect(videos).toHaveCount(4);
  await expect(page.getByText("Preparing video")).toHaveCount(0, {
    timeout: 60_000,
  });
  await expect(page.getByText("80 frames")).toBeVisible();
  await expect(page.getByText("seed 21")).toBeVisible();
  await expect(page.getByText("cached", { exact: true })).toHaveCount(0);

  await generate.click();
  await expect(page.getByText("cached", { exact: true })).toBeVisible();
});

/** What the progress bar did: every value it took, however briefly; its bounds on the page
 *  whenever the line changed, over the empty card or the panes; and how long it stayed full
 *  where it filled. */
type BarSeen = {
  values: number[];
  bounds: { left: number; top: number; width: number; height: number }[];
  places: string[];
  fits: boolean[];
  fullFor: number;
};

/** Start recording the progress bar, for `takeBar` to read. */
async function watchBar(page: Page) {
  await page.evaluate(() => {
    const fresh = () => ({
      values: [] as number[],
      bounds: [] as BarSeen["bounds"],
      places: [] as string[],
      fits: [] as boolean[],
      fullFor: 0,
      fullAt: 0,
      fullPlace: "",
    });
    const w = window as unknown as {
      bar: ReturnType<typeof fresh>;
      freshBar: typeof fresh;
    };
    w.bar = fresh();
    w.freshBar = fresh;
    new MutationObserver(() => {
      const bar = w.bar;
      const element = document.querySelector('[role="progressbar"]');
      const value = element?.getAttribute("aria-valuenow");
      // A sequence's panes on screen, or the empty card.
      const place = document.querySelector("video") ? "panes" : "empty";
      if (
        bar.fullAt &&
        !bar.fullFor &&
        (value == null || place !== bar.fullPlace)
      )
        bar.fullFor = performance.now() - bar.fullAt;
      if (element == null || value == null) return;
      if (Number(value) !== bar.values.at(-1)) bar.values.push(Number(value));
      // From the page's edge rather than the line's: on the empty screen the line is
      // centered, and a line that grew after the bar would move the bar but not its offset.
      // Record even when only the seconds or step name changed, at the same percentage.
      const bounds = element.getBoundingClientRect();
      bar.bounds.push({
        left: bounds.left + window.scrollX,
        top: bounds.top + window.scrollY,
        width: bounds.width,
        height: bounds.height,
      });
      bar.places.push(place);
      const progress = element.closest('[role="status"]')!;
      // The viewer's column: the empty card and the caption above the panes both span it.
      const card = progress.closest("section")!.getBoundingClientRect();
      bar.fits.push(
        // Not the spinner: it turns, and a turned square's box pokes out of its own.
        [
          progress,
          ...progress.querySelectorAll("*:not(.animate-spin, .animate-spin *)"),
        ].every((child) => {
          const bounds = child.getBoundingClientRect();
          return (
            bounds.left >= card.left - 0.5 &&
            bounds.right <= card.right + 0.5 &&
            bounds.top >= card.top - 0.5 &&
            bounds.bottom <= card.bottom + 0.5
          );
        }),
      );
      if (Number(value) === 100 && !bar.fullAt) {
        bar.fullAt = performance.now();
        bar.fullPlace = place;
      }
    }).observe(document.body, {
      subtree: true,
      childList: true,
      characterData: true,
      attributes: true,
    });
  });
}

/** What the bar did since `watchBar`, or since the last take, which starts it afresh. */
async function takeBar(page: Page): Promise<BarSeen> {
  return page.evaluate(() => {
    const w = window as unknown as {
      bar: BarSeen;
      freshBar: () => BarSeen;
    };
    const seen = w.bar;
    w.bar = w.freshBar();
    return seen;
  });
}

/** One bar that fills once, without going back, in one place on the page and without moving
 *  in it, and stays full there long enough to be seen. */
function expectOneSteadyBar(seen: BarSeen, place: string) {
  expect(seen.values.length).toBeGreaterThan(2);
  expect(seen.values).toEqual([...seen.values].sort((a, b) => a - b));
  expect(seen.values.at(-1)).toBe(100);
  expect(new Set(seen.places)).toEqual(new Set([place]));
  expect(new Set(seen.bounds.map((bounds) => bounds.left)).size).toBe(1);
  expect(seen.fits).toEqual(seen.bounds.map(() => true));
  // Where on its own it would last a frame or none.
  expect(seen.fullFor).toBeGreaterThanOrEqual(400);
}

/** On a phone, the bar also keeps its vertical position and width in each placement. */
function expectOneSteadyBox(seen: BarSeen, place: string) {
  expectOneSteadyBar(seen, place);
  for (const axis of ["top", "width"] as const)
    expect(new Set(seen.bounds.map((bounds) => bounds[axis])).size).toBe(1);
}

/**
 * One bar for the whole generation: it fills once, never going back at a new step, stays
 * where it is while the step's name changes beside it, and is seen full there before the
 * sequence takes the screen. On the empty screen first, then in the line above the panes,
 * where the next sequence's progress shows while one is on screen.
 */
test("fills one progress bar for the whole generation", async ({ page }) => {
  // Two generations, about 14 s each in CI, leave no room in the default 30 s.
  test.slow();
  await openPage(page);
  await watchBar(page);
  const seed = page.getByRole("spinbutton", { name: "Seed" });
  const generate = page.getByRole("button", { name: "Generate sequence" });
  const progress = page.getByRole("status", { name: "Generation progress" });

  await seed.fill("61");
  await generate.click();
  await expect(progress).toBeVisible();
  await expect(progress).toBeHidden({ timeout: 60_000 });
  expectOneSteadyBar(await takeBar(page), "empty");

  const videos = page.locator("video");
  await expect(videos).toHaveCount(4, { timeout: 60_000 });
  const top = () =>
    videos.first().evaluate((el) => Math.round(el.getBoundingClientRect().top));
  const before = await top();

  await seed.fill("62");
  await generate.click();
  await expect(progress).toBeVisible();
  expect(await top()).toBe(before);
  await expect(progress).toBeHidden({ timeout: 60_000 });
  expectOneSteadyBar(await takeBar(page), "panes");
});

/** The fixed text cells fit a phone's card and caption without moving the bar. */
test("fits generation progress at 390 px without shifting the bar", async ({
  page,
}) => {
  test.slow();
  await page.setViewportSize({ width: 390, height: 844 });
  await openPage(page);
  await watchBar(page);
  const seed = page.getByRole("spinbutton", { name: "Seed" });
  const generate = page.getByRole("button", { name: "Generate sequence" });
  const progress = page.getByRole("status", { name: "Generation progress" });

  await seed.fill("71");
  await generate.click();
  await expect(progress).toBeVisible();
  await expect(progress).toBeHidden({ timeout: 60_000 });
  expectOneSteadyBox(await takeBar(page), "empty");
  await expect(page.locator("video")).toHaveCount(4);
  // On a phone each pane's header, picker and close button included, fits its pane.
  await expect
    .poll(() =>
      page
        .locator("figcaption")
        .evaluateAll((els) =>
          els.map((el) => el.scrollWidth <= el.clientWidth),
        ),
    )
    .toEqual([true, true, true, true]);

  await seed.fill("72");
  await generate.click();
  await expect(progress).toBeVisible();
  await expect(progress).toBeHidden({ timeout: 60_000 });
  expectOneSteadyBox(await takeBar(page), "panes");
});

/** Completion stops the running indicators while the full bar still holds its place. */
test("stops the button, scale, and timer during the full bar hold", async ({
  page,
}) => {
  const now = new Date("2026-01-01T00:00:00Z");
  await page.clock.install({ time: new Date(now.getTime() - 60_000) });
  await openPage(page);
  await page.clock.pauseAt(now);

  let finish!: () => void;
  const completion = new Promise<void>((resolve) => {
    finish = resolve;
  });
  await page.route("**/sequences", async (route) => {
    await completion;
    const params = route.request().postDataJSON();
    await route.fulfill({
      contentType: "application/x-ndjson",
      body:
        [
          { steps: [{ step: "frames", total: 80 }] },
          { step: "frames", done: 80, total: 80 },
          {
            sequence: {
              id: "0123456789abcdef",
              library: params.library,
              cached: false,
              seed: params.seed,
              frames: 80,
              size: 512,
              n_objects: 2,
              object_colors: ["#ff0000", "#00ff00"],
              streams: {},
            },
          },
        ]
          .map((event) => JSON.stringify(event))
          .join("\n") + "\n",
    });
  });

  const generate = page.getByRole("button", { name: "Generate sequence" });
  await generate.click();
  await expect(
    page.getByRole("button", { name: "Generating", exact: true }),
  ).toBeDisabled();
  await expect(page.locator(".depth-sweep")).toHaveCount(1);
  await expect(page.locator(".depth-sweep")).toHaveCSS(
    "animation-name",
    "depth-sweep",
  );

  // Finish just before a seconds boundary; the hold crosses it but must keep "1 s".
  await page.clock.runFor(1750);
  finish();
  const progress = page.getByRole("status", { name: "Generation progress" });
  await expect(progress).toContainText("Done", { useInnerText: true });
  await expect(
    page.getByRole("progressbar", { name: "Generated" }),
  ).toHaveAttribute("aria-valuenow", "100");
  await expect(generate).toBeDisabled();
  await expect(generate).toHaveText("Generate sequence");
  await expect(page.locator(".depth-sweep")).toHaveCount(0);
  await expect(progress).toContainText("1 s", { useInnerText: true });

  await page.clock.runFor(499);
  await expect(progress).toBeVisible();
  await expect(progress).toContainText("1 s", { useInnerText: true });
  await expect(generate).toBeDisabled();
  await expect(page.locator(".depth-sweep")).toHaveCount(0);

  await page.clock.runFor(1);
  await expect(progress).toBeHidden();
  await expect(generate).toBeEnabled();
  await expect(
    page.getByRole("group", { name: "Sequence on screen" }),
  ).toBeVisible();
});

/** The sweep crosses the whole scale, from beyond "near" to beyond "far". */
test("sweeps the depth scale from end to end", async ({ page }) => {
  await openPage(page);
  let release!: () => void;
  const held = new Promise<void>((resolve) => {
    release = resolve;
  });
  await page.route("**/sequences", async (route) => {
    await held;
    await route.abort();
  });
  await page.getByRole("button", { name: "Generate sequence" }).click();
  const sweep = page.locator(".depth-sweep");
  await expect(sweep).toHaveCount(1);

  /** Where the highlight sits at a time in its cycle, against the bar it is clipped to. */
  const at = (time: "start" | "end") =>
    sweep.evaluate((el, time) => {
      const [animation] = el.getAnimations();
      const duration = Number(animation.effect!.getTiming().duration);
      animation.pause();
      // A full duration wraps an infinite animation back to its start, so take 1 ms less.
      animation.currentTime = time === "start" ? 0 : duration - 1;
      const bar = el.parentElement!;
      const left = bar.getBoundingClientRect().left + bar.clientLeft;
      const box = el.getBoundingClientRect();
      return {
        barLeft: left,
        barRight: left + bar.clientWidth,
        left: box.left,
        right: box.right,
      };
    }, time);

  const start = await at("start");
  expect(start.right).toBeLessThanOrEqual(start.barLeft + 0.5);
  const end = await at("end");
  expect(end.left).toBeGreaterThanOrEqual(end.barRight - 0.5);
  release();
});

/** The outer halves offer the first and last places, regardless of drag direction. */
test("moves a pane before the first pane and after the last", async ({
  page,
}) => {
  await page.setViewportSize({ width: 1920, height: 720 });
  await openPage(page);
  await generateSequence(page);
  expect(await streamsInOrder(page)).toEqual([
    "All in focus",
    "Alpha",
    "Disparity",
    "Optical flow",
  ]);

  const first = page.getByRole("figure").first();
  const firstBox = (await first.boundingBox())!;
  await page
    .getByRole("button", { name: "Move Optical flow pane" })
    .dragTo(first, { targetPosition: { x: firstBox.width / 4, y: 64 } });
  await expect
    .poll(() => streamsInOrder(page))
    .toEqual(["Optical flow", "All in focus", "Alpha", "Disparity"]);

  const last = page.getByRole("figure").last();
  const lastBox = (await last.boundingBox())!;
  await page
    .getByRole("button", { name: "Move Optical flow pane" })
    .dragTo(last, { targetPosition: { x: (lastBox.width * 3) / 4, y: 64 } });
  await expect
    .poll(() => streamsInOrder(page))
    .toEqual(["All in focus", "Alpha", "Disparity", "Optical flow"]);
});

/** A pane's halves mean before and after, even when the drag comes from the other side. */
test("inserts on the chosen side regardless of drag direction", async ({
  page,
}) => {
  await page.setViewportSize({ width: 1920, height: 720 });
  await openPage(page);
  await generateSequence(page);
  const figures = page.getByRole("figure");
  const disparity = figures.nth(2);
  const disparityBox = (await disparity.boundingBox())!;
  await page
    .getByRole("button", { name: "Move All in focus pane" })
    .dragTo(disparity, {
      targetPosition: { x: disparityBox.width / 4, y: 64 },
    });
  await expect
    .poll(() => streamsInOrder(page))
    .toEqual(["Alpha", "All in focus", "Disparity", "Optical flow"]);

  const alpha = figures.first();
  const alphaBox = (await alpha.boundingBox())!;
  await page
    .getByRole("button", { name: "Move Optical flow pane" })
    .dragTo(alpha, {
      targetPosition: { x: (alphaBox.width * 3) / 4, y: 64 },
    });
  await expect
    .poll(() => streamsInOrder(page))
    .toEqual(["Alpha", "Optical flow", "All in focus", "Disparity"]);
});

/** The space between figures offers the same insertion as their facing halves. */
test("inserts a pane dropped in the gap between panes", async ({ page }) => {
  await page.setViewportSize({ width: 1920, height: 720 });
  await openPage(page);
  await generateSequence(page);
  const figures = page.getByRole("figure");
  const left = (await figures.nth(1).boundingBox())!;
  const right = (await figures.nth(2).boundingBox())!;
  expect(left.y).toBe(right.y);
  const x = (left.x + left.width + right.x) / 2;
  const y = left.y + 64;
  await startPaneDrag(page, "Optical flow");
  await page.mouse.move(x, y, { steps: 10 });
  await page.mouse.move(x, y);
  await expect(page.getByTestId("pane-drop-indicator")).toBeVisible();
  await page.mouse.up();
  await expect
    .poll(() => streamsInOrder(page))
    .toEqual(["All in focus", "Alpha", "Optical flow", "Disparity"]);
  await expect(page.getByTestId("pane-drop-indicator")).toHaveCount(0);
  await expect(figures.nth(2)).toHaveCSS("opacity", "1");
});

/** The line marks where the pane would land, and the pane stays dimmed for the whole drag. */
test("shows insertion feedback and clears it after a drop", async ({
  page,
}) => {
  await page.setViewportSize({ width: 1920, height: 720 });
  await openPage(page);
  await generateSequence(page);
  const figures = page.getByRole("figure");
  const left = (await figures.nth(1).boundingBox())!;
  const right = (await figures.nth(2).boundingBox())!;
  expect(left.y).toBe(right.y);
  const own = (await figures.last().boundingBox())!;
  const dragged = figures.filter({
    has: page.getByRole("button", { name: "Move Optical flow pane" }),
  });
  const indicator = page.getByTestId("pane-drop-indicator");
  const opacity = () =>
    dragged.evaluate((el) => Number(getComputedStyle(el).opacity));
  await startPaneDrag(page, "Optical flow");
  await page.mouse.move(right.x + right.width / 4, right.y + 64, { steps: 10 });
  await page.mouse.move(right.x + right.width / 4, right.y + 64);
  await expect(indicator).toBeVisible();
  const line = (await indicator.boundingBox())!;
  expect(line.x + line.width / 2).toBeGreaterThan(left.x + left.width);
  expect(line.x + line.width / 2).toBeLessThan(right.x);
  expect(line.width).toBe(3);
  expect(line.y).toBe(right.y);
  expect(line.height).toBe(right.height);
  await expect.poll(opacity).toBeLessThan(1);

  await page.mouse.move(right.x + right.width / 4, right.y - 12, {
    steps: 10,
  });
  await expect(indicator).toBeHidden();
  await expect.poll(opacity).toBeLessThan(1);
  await page.mouse.move(right.x + right.width / 4, right.y + 64, {
    steps: 10,
  });
  await page.mouse.move(right.x + right.width / 4, right.y + 64);
  await expect(indicator).toBeVisible();
  await expect.poll(opacity).toBeLessThan(1);

  for (const fraction of [0.25, 0.75]) {
    await page.mouse.move(own.x + own.width * fraction, own.y + 64, {
      steps: 10,
    });
    await page.mouse.move(own.x + own.width * fraction, own.y + 64);
    await expect(indicator).toBeHidden();
  }
  await page.mouse.up();
  await expect(indicator).toHaveCount(0);
  await expect.poll(opacity).toBe(1);
  expect(await streamsInOrder(page)).toEqual([
    "All in focus",
    "Alpha",
    "Disparity",
    "Optical flow",
  ]);
});

/** A shared slot follows the row under the pointer, including the gap between rows. */
test("places the insertion line beside the nearest row", async ({ page }) => {
  await page.setViewportSize({ width: 1280, height: 1000 });
  await openPage(page);
  await generateSequence(page);
  const figures = page.getByRole("figure");
  await expect
    .poll(async () => {
      const boxes = await figures.evaluateAll((els) =>
        els.map((el) => el.getBoundingClientRect().top),
      );
      return [
        boxes[0] === boxes[1],
        boxes[2] === boxes[3],
        boxes[2] > boxes[0],
      ];
    })
    .toEqual([true, true, true]);
  const end = (await figures.nth(1).boundingBox())!;
  const start = (await figures.nth(2).boundingBox())!;
  const indicator = page.getByTestId("pane-drop-indicator");
  await startPaneDrag(page, "Optical flow");
  await page.mouse.move(end.x + end.width * 0.75, end.y + 64, { steps: 10 });
  await page.mouse.move(end.x + end.width * 0.75, end.y + 64);
  await expect(indicator).toBeVisible();
  const atEnd = (await indicator.boundingBox())!;
  expect(atEnd.x + atEnd.width / 2).toBe(end.x + end.width + 8);
  expect(atEnd.y).toBe(end.y);
  expect(atEnd.height).toBe(end.height);

  const x = start.x + start.width / 4;
  const y = start.y - 2;
  await page.mouse.move(x, y, { steps: 10 });
  await page.mouse.move(x, y);
  // Still visible from the first row, so wait for the line to move rather than to show.
  await expect
    .poll(async () => {
      const line = await indicator.boundingBox();
      return line && [line.x + line.width / 2, line.y, line.height];
    })
    .toEqual([start.x - 8, start.y, start.height]);
  await page.mouse.up();
  await expect
    .poll(() => streamsInOrder(page))
    .toEqual(["All in focus", "Alpha", "Optical flow", "Disparity"]);
  await expect(indicator).toHaveCount(0);
});

/** A pane let go outside the grid stays where it was, and the drag leaves nothing behind. */
test("keeps the order when a pane is dropped outside the grid", async ({
  page,
}) => {
  await page.setViewportSize({ width: 1920, height: 720 });
  await openPage(page);
  await generateSequence(page);
  const figures = page.getByRole("figure");
  const first = (await figures.first().boundingBox())!;
  const dragged = figures.filter({
    has: page.getByRole("button", { name: "Move Optical flow pane" }),
  });
  const indicator = page.getByTestId("pane-drop-indicator");
  await startPaneDrag(page, "Optical flow");
  await page.mouse.move(first.x + first.width / 4, first.y + 64, { steps: 10 });
  await page.mouse.move(first.x + first.width / 4, first.y + 64);
  await expect(indicator).toBeVisible();
  // Up to the page's header, outside the grid, and let go there.
  await page.mouse.move(first.x + first.width / 4, 20, { steps: 10 });
  await page.mouse.move(first.x + first.width / 4, 20);
  await expect(indicator).toBeHidden();
  await page.mouse.up();
  await expect(indicator).toHaveCount(0);
  await expect
    .poll(() => dragged.evaluate((el) => Number(getComputedStyle(el).opacity)))
    .toBe(1);
  expect(await streamsInOrder(page)).toEqual([
    "All in focus",
    "Alpha",
    "Disparity",
    "Optical flow",
  ]);
});

/**
 * The grip moves its pane with the arrow keys too, keeps the focus for the next press, and
 * the panes play on in step: a reorder moves the video elements, it does not reload them.
 */
test("moves a pane with the arrow keys while the panes play", async ({
  page,
}) => {
  await openPage(page);
  const videos = await generateSequence(page);
  // Every pane decoded before Play. The API encodes a stream the first time it is asked
  // for, so run alone, before any other test has asked, a pane would still sit at the
  // start when the times are read.
  await waitForDecoded(videos);
  await page.getByRole("button", { name: "Play" }).click();

  const grip = page.getByRole("button", { name: "Move All in focus pane" });
  await grip.focus();
  const original = await streamsInOrder(page);
  for (const modifier of ["Alt", "Control", "Meta", "Shift"]) {
    await page.keyboard.press(`${modifier}+ArrowRight`);
    expect(await streamsInOrder(page)).toEqual(original);
    await expect(grip).toBeFocused();
  }
  await page.keyboard.press("ArrowRight");
  await page.keyboard.press("ArrowRight");
  await expect
    .poll(() => streamsInOrder(page))
    .toEqual(["Alpha", "Disparity", "All in focus", "Optical flow"]);
  await expect(grip).toBeFocused();
  await page.keyboard.press("ArrowLeft");
  await expect
    .poll(() => streamsInOrder(page))
    .toEqual(["Alpha", "All in focus", "Disparity", "Optical flow"]);
  await expect(grip).toBeFocused();
  expect(
    await videos.evaluateAll((els) =>
      els.map((el) => (el as HTMLVideoElement).paused),
    ),
  ).toEqual([false, false, false, false]);

  // In step: still on one frame, give or take the transport's tolerance, and moving.
  const times = () =>
    videos.evaluateAll((els) =>
      els.map((el) => (el as HTMLVideoElement).currentTime),
    );
  const before = await times();
  await page.waitForTimeout(400);
  const after = await times();
  expect(Math.max(...after) - Math.min(...after)).toBeLessThan(0.15);
  expect(Math.min(...after)).toBeGreaterThan(Math.max(...before));
});

/** With every stream on screen there is nothing left to add, and the button says so. */
test("offers no pane once every stream is on screen", async ({ page }) => {
  await openPage(page);
  const videos = await generateSequence(page);
  // Occlusion opens no pane of its own; "Add pane" offers it. The backward flow is no
  // stream of its own but a direction of the optical flow, so nothing else is left.
  const add = page.getByRole("button", { name: "Add pane" });
  await add.click();
  await expect(videos).toHaveCount(5);
  expect((await streamsInOrder(page)).at(-1)).toBe("Occlusion");
  await expect(
    page.getByRole("button", { name: "All streams shown" }),
  ).toBeDisabled();

  await page.getByRole("button", { name: "Close Alpha pane" }).click();
  await add.click();
  await expect(videos).toHaveCount(5);
  expect((await streamsInOrder(page)).at(-1)).toBe("Alpha");
  await expect(
    page.getByRole("button", { name: "All streams shown" }),
  ).toBeDisabled();
});

/**
 * A pane whose stream the next sequence lacks shows the first stream instead, and counts as
 * showing it: "Add pane" must not offer that stream a second time.
 */
test("counts the stream a pane falls back to as shown", async ({ page }) => {
  // Two generations, about 14 s each in CI, leave no room in the default 30 s.
  test.slow();
  await openPage(page);
  const seed = page.getByRole("spinbutton", { name: "Seed" });
  const generate = page.getByRole("button", { name: "Generate sequence" });
  // A seed of its own: this test writes into its sequence.
  const videos = await generateSequence(page, 51);
  await fakeBokeh(page);
  await generate.click();
  await expect(videos).toHaveCount(5, { timeout: 60_000 });

  await page.getByRole("button", { name: "Close All in focus pane" }).click();
  await expect(page.getByRole("button", { name: "Add pane" })).toBeEnabled();

  // No bokeh here, so the bokeh pane falls back to all in focus. What is left to add is
  // the stream that opens no pane of its own, and all in focus is not it.
  await seed.fill("52");
  await generate.click();
  await expect(page.getByText("seed 52")).toBeVisible({ timeout: 60_000 });
  const add = page.getByRole("button", { name: "Add pane" });
  await add.click();
  expect((await streamsInOrder(page)).at(-1)).toBe("Occlusion");
  await expect(
    page.getByRole("button", { name: "All streams shown" }),
  ).toBeDisabled();
});

/** Open a pane on a stream that opens none of its own, and wait for it to decode. */
async function addPaneFor(page: Page, label: string) {
  const pickers = page.getByRole("combobox", { name: "Stream" });
  const before = await pickers.count();
  await page.getByRole("button", { name: "Add pane" }).click();
  await expect(pickers).toHaveCount(before + 1);
  const last = pickers.last();
  if ((await last.innerText()) !== label) {
    await last.click();
    await page.getByRole("option", { name: label, exact: true }).click();
  }
  await expect(last).toHaveText(label);
  // "Add pane" puts the pane last.
  const figure = page.locator("figure").last();
  await waitForDecoded(figure.locator("video"));
  return figure;
}

/**
 * The occlusion mask comes with every sequence, waits in the stream picker rather than open
 * a pane, and decodes as video once a pane shows it.
 */
test("shows occlusion from the stream picker", async ({ page }) => {
  await openPage(page);
  const videos = await generateSequence(page);
  await expect(page.getByRole("combobox", { name: "Stream" })).toHaveText([
    "All in focus",
    "Alpha",
    "Disparity",
    "Optical flow",
  ]);

  const occlusion = await addPaneFor(page, "Occlusion");
  await expect(occlusion.locator("video")).toHaveAttribute(
    "src",
    /occlusion\.mp4$/,
  );
  await expect(videos).toHaveCount(5);
});

/**
 * One optical flow stream, its direction picked under the pane as the disparity's colormap
 * is: forward first, backward from the same dropdown, each with its own caption. The
 * backward flow is no stream of its own in the picker.
 */
test("picks the optical flow direction under its pane", async ({ page }) => {
  // Two generations, about 14 s each in CI, leave no room in the default 30 s.
  test.slow();
  await openPage(page);
  const videos = await generateSequence(page);
  const pane = page.locator("figure").filter({
    has: page
      .getByRole("combobox", { name: "Stream" })
      .getByText("Optical flow"),
  });
  const video = pane.locator("video");

  await pane.getByRole("combobox", { name: "Stream" }).click();
  await expect(page.getByRole("option")).toHaveText([
    "All in focus",
    "Alpha",
    "Disparity",
    "Optical flow",
    "Occlusion",
  ]);
  await page.keyboard.press("Escape");

  const direction = pane.getByRole("combobox", { name: "Direction" });
  await expect(direction).toHaveText("Forward");
  await expect(video).toHaveAttribute("src", /\/flow\.mp4$/);
  // One short line under the pane; the full reading is a tooltip, by keyboard too.
  const legend = pane.getByRole("button", {
    name: "Color = direction; paler = slower",
  });
  await expect(legend).toBeVisible();
  const tooltip = page.getByRole("tooltip");
  await expect(tooltip).toHaveCount(0);
  await direction.focus();
  await page.keyboard.press("Tab");
  await expect(legend).toBeFocused();
  await expect(tooltip).toContainText("where a pixel moves in the next frame");
  await expect(legend).toHaveAccessibleDescription(
    /where a pixel moves in the next frame/,
  );
  await page.keyboard.press("Escape");
  await expect(tooltip).toHaveCount(0);

  await direction.click();
  await expect(page.getByRole("option")).toHaveText(["Forward", "Backward"]);
  await page.getByRole("option", { name: "Backward" }).click();
  await expect(direction).toHaveText("Backward");
  await expect(video).toHaveAttribute("src", /\/flow_back\.mp4$/);
  await waitForDecoded(videos);
  await legend.hover();
  await expect(tooltip).toContainText(
    "where a pixel came from in the previous frame",
  );
  await expect(tooltip).not.toContainText(
    "where a pixel moves in the next frame",
  );
  // Away from it, as a hand moves: the tooltip stays while the pointer heads for it.
  const away = (await video.boundingBox())!;
  await page.mouse.move(away.x + 8, away.y + 8, { steps: 10 });
  await expect(tooltip).toHaveCount(0);
  // Only the flow pane has a direction.
  await expect(page.getByRole("combobox", { name: "Direction" })).toHaveCount(
    1,
  );

  // A new sequence keeps the direction, as it keeps a colormap.
  await page.getByRole("spinbutton", { name: "Seed" }).fill("7");
  await page.getByRole("button", { name: "Generate sequence" }).click();
  await expect(page.getByText("seed 7")).toBeVisible({ timeout: 60_000 });
  await expect(direction).toHaveText("Backward");
  await expect(video).toHaveAttribute("src", /\/flow_back\.mp4$/);
  await waitForDecoded(videos);
});

/**
 * The occlusion pane shows the mask as stored, white on black, and a toggle in the pane
 * draws it cyan over the frames in gray instead, and back.
 */
test("switches the occlusion pane to the overlay and back", async ({
  page,
}) => {
  await openPage(page);
  await generateSequence(page);
  const pane = await addPaneFor(page, "Occlusion");
  const video = pane.locator("video");
  const toggle = pane.getByRole("button", { name: "Overlay" });
  await expect(toggle).toHaveAttribute("aria-pressed", "false");
  await expect(pane.getByText("White: hidden in the next frame")).toBeVisible();

  await toggle.click();
  await expect(toggle).toHaveAttribute("aria-pressed", "true");
  await expect(video).toHaveAttribute("src", /occlusion\.mp4\?overlay=true$/);
  await waitForDecoded(video);
  await expect(pane.getByText("Cyan: hidden in the next frame")).toBeVisible();
  // The swatch is the cyan the backend draws, #00E5FF.
  await expect(pane.locator("[data-swatch]")).toHaveCSS(
    "background-color",
    "rgb(0, 229, 255)",
  );

  await toggle.click();
  await expect(toggle).toHaveAttribute("aria-pressed", "false");
  await expect(video).toHaveAttribute("src", /occlusion\.mp4$/);
});

/**
 * The disparity pane picks among the colormaps the API lists, Spectral first, and the
 * legend under it follows the map on screen.
 */
test("chooses the disparity colormap and its legend", async ({ page }) => {
  await openPage(page);
  const videos = await generateSequence(page);
  const pane = page.locator("figure").filter({
    has: page.getByRole("combobox", { name: "Stream" }).getByText("Disparity"),
  });
  const colormap = pane.getByRole("combobox", { name: "Colormap" });
  await expect(colormap).toHaveText("Spectral");
  await expect(
    pane.getByRole("img", { name: /^Spectral scale/ }),
  ).toBeVisible();

  await colormap.click();
  await expect(page.getByRole("option")).toHaveText(["Gray", "Spectral"]);
  await page.getByRole("option", { name: "Gray" }).click();
  await expect(colormap).toHaveText("Gray");
  await expect(pane.locator("video")).toHaveAttribute(
    "src",
    /disparity\.mp4\?colormap=grey$/,
  );
  await waitForDecoded(videos);
  await expect(pane.getByRole("img", { name: /^Gray scale/ })).toBeVisible();
  // Only the disparity pane takes a colormap.
  await expect(page.getByRole("combobox", { name: "Colormap" })).toHaveCount(1);
});

/** Open all six streams: bokeh faked into the sequence, and occlusion from "Add pane". */
async function openSixPanes(page: Page, seed: number) {
  const videos = await generateSequence(page, seed);
  await fakeBokeh(page);
  await page.getByRole("button", { name: "Generate sequence" }).click();
  await expect(videos).toHaveCount(5, { timeout: 60_000 });
  await addPaneFor(page, "Occlusion");
  await expect(videos).toHaveCount(6);
  await waitForDecoded(videos);
  return videos;
}

/**
 * Under every pane the controls start on one line, directly beneath the frame, however
 * narrow six panes side by side make them: the flow's caption stays one line rather than
 * push its dropdown down.
 */
test("lines up the controls under six narrow panes", async ({ page }) => {
  test.slow();
  await page.setViewportSize({ width: 1760, height: 640 });
  await openPage(page);
  await openSixPanes(page, 81);
  await page.getByRole("button", { name: "Overlay" }).click();

  const figures = page.locator("figure");
  // Six panes side by side, each too narrow for a long caption.
  const tops = await figures.evaluateAll((els) =>
    els.map((el) => Math.round(el.getBoundingClientRect().top)),
  );
  expect(new Set(tops).size).toBe(1);
  expect((await figures.first().boundingBox())!.width).toBeLessThan(260);

  const frameBottom = await figures
    .first()
    .locator("video")
    .evaluate((el) => el.parentElement!.getBoundingClientRect().bottom);
  for (const control of [
    page.getByRole("combobox", { name: "Colormap" }),
    page.getByRole("button", { name: "Overlay" }),
    page.getByRole("combobox", { name: "Direction" }),
    // The wheel, with the caption beside it.
    page.getByRole("button", { name: "Color = direction; paler = slower" }),
  ]) {
    // Directly beneath the frame: the figure's 8 px gap, no more.
    await expect
      .poll(async () => Math.round((await control.boundingBox())!.y))
      .toBe(Math.round(frameBottom + 8));
  }
  // The caption is one line, not a paragraph wrapped down the pane.
  const caption = page.getByText("Color = direction; paler = slower");
  expect((await caption.boundingBox())!.height).toBeLessThan(20);
});

/**
 * Dragging the position slider moves its thumb smoothly, between frames, and every pane
 * shows the frame nearest to it at once: one decoded in memory, not a seek. Let go, the
 * videos are on that frame.
 */
test("scrubs every pane to the nearest frame while dragging", async ({
  page,
}) => {
  test.slow();
  await page.setViewportSize({ width: 1760, height: 640 });
  await openPage(page);
  const videos = await openSixPanes(page, 91);
  const canvases = page.locator("figure canvas");
  await expect(canvases).toHaveCount(6);
  // Every pane's frames decoded into memory.
  await expect
    .poll(
      () =>
        canvases.evaluateAll((els) =>
          els.map((el) => el.getAttribute("data-decoded")),
        ),
      { timeout: 60_000 },
    )
    .toEqual(Array(6).fill("80"));

  /** The first pane as it looks on screen, canvas or video, as RGBA values. */
  const frameBox = videos.first().locator("xpath=..");
  const pixels = async () => {
    const png = (await frameBox.screenshot()).toString("base64");
    return page.evaluate(async (png) => {
      const image = new Image();
      image.src = `data:image/png;base64,${png}`;
      await image.decode();
      const probe = document.createElement("canvas");
      probe.width = image.width;
      probe.height = image.height;
      const context = probe.getContext("2d")!;
      context.drawImage(image, 0, 0);
      return Array.from(
        context.getImageData(0, 0, probe.width, probe.height).data,
      );
    }, png);
  };
  const meanDifference = (a: number[], b: number[]) =>
    a.reduce((sum, value, i) => sum + Math.abs(value - b[i]), 0) / a.length;
  const start = await pixels();

  const slider = page.getByRole("slider", { name: "Position" });
  const track = (await page
    .locator('[data-slot="slider"]', { has: slider })
    .boundingBox())!;
  const thumb = (await slider.boundingBox())!;
  const y = thumb.y + thumb.height / 2;
  await page.mouse.move(thumb.x + thumb.width / 2, y);
  await page.mouse.down();
  const values: number[] = [];
  for (let i = 1; i <= 30; i++) {
    await page.mouse.move(track.x + (track.width * 0.4 * i) / 30, y);
    values.push(Number(await slider.getAttribute("aria-valuenow")));
  }
  // Continuous: the thumb sits between frames, not only on them.
  expect(values.some((v) => !Number.isInteger(v))).toBe(true);
  expect(values).toEqual([...values].sort((a, b) => a - b));

  // Mid-drag, every pane shows the counter's frame, drawn from memory.
  const counter = page.getByText(/^\d+ \/ 80$/);
  const shown = Number((await counter.innerText()).split(" / ")[0]) - 1;
  expect(shown).toBe(Math.round(values.at(-1)!));
  expect(
    await canvases.evaluateAll((els) =>
      els.map((el) => [
        getComputedStyle(el).visibility,
        el.getAttribute("data-frame"),
      ]),
    ),
  ).toEqual(Array(6).fill(["visible", String(shown)]));
  const dragged = await pixels();

  await page.mouse.up();
  // Let go, the thumb rests on the frame shown and the videos have caught up with it.
  await expect(slider).toHaveAttribute("aria-valuenow", String(shown));
  await expect
    .poll(() =>
      canvases.evaluateAll((els) =>
        els.map((el) => getComputedStyle(el).visibility),
      ),
    )
    .toEqual(Array(6).fill("hidden"));
  // The frame drawn from memory is the one the video shows there, and not the first.
  const settled = await pixels();
  const there = meanDifference(dragged, settled);
  expect(there).toBeLessThan(4);
  expect(meanDifference(start, settled)).toBeGreaterThan(there);
  expect(
    await videos.evaluateAll((els) =>
      els.map((el) => {
        const video = el as HTMLVideoElement;
        return Math.floor((video.currentTime / video.duration) * 80);
      }),
    ),
  ).toEqual(Array(6).fill(shown));

  // The arrow keys still step one whole frame. The frames either side of the one shown
  // look less like it than the video's own: the frame drawn is that frame, not a neighbor.
  const settledAt = async (frame: number) => {
    await expect(counter).toHaveText(`${frame + 1} / 80`);
    await expect(slider).toHaveAttribute("aria-valuenow", String(frame));
    await expect
      .poll(() =>
        canvases.evaluateAll((els) =>
          els.map((el) => getComputedStyle(el).visibility),
        ),
      )
      .toEqual(Array(6).fill("hidden"));
    return pixels();
  };
  await slider.focus();
  await page.keyboard.press("ArrowRight");
  const next = await settledAt(shown + 1);
  await page.keyboard.press("ArrowLeft");
  await page.keyboard.press("ArrowLeft");
  const previous = await settledAt(shown - 1);
  expect(meanDifference(dragged, next)).toBeGreaterThan(there);
  expect(meanDifference(dragged, previous)).toBeGreaterThan(there);
});
