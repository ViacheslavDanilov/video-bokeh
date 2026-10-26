import { execFileSync } from "node:child_process";
import { rmSync } from "node:fs";
import os from "node:os";
import path from "node:path";
import { expect, type Locator, type Page, test } from "@playwright/test";

// Where playwright.config.ts points the API, so a test can write into a sequence as
// a renderer would.
const SEQUENCES = path.join(os.tmpdir(), "video-bokeh-e2e", "sequences");
const LIBRARIES = path.join(os.tmpdir(), "video-bokeh-e2e", "library");

/**
 * The side, in pixels, of the sequences the tests generate. The page's own default is
 * 512, four times the pixels, and nearly all of the time a run takes is the API building
 * sequences, while what the tests look at is the page, which is the same at either size.
 */
const E2E_SIZE = 256;

/** Open the page once its library is ready to generate, with the size the tests use. */
async function openPage(page: Page) {
  await page.goto("/");
  await expect(page.getByText("2 objects, 2 backgrounds")).toBeVisible();
  const picker = page.getByRole("combobox", { name: "Size" });
  await picker.click();
  await page.getByRole("option", { name: `${E2E_SIZE} × ${E2E_SIZE}` }).click();
  await expect(picker).toHaveText(`${E2E_SIZE} × ${E2E_SIZE}`);
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

/** Write bokeh into the sequence on screen, as a renderer would: the API here renders none of
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
 * The transport's button shows a triangle to play and two bars to pause, with no words, and
 * says which it is to a screen reader. The button stays where it was and keeps its size.
 */
test("shows the play and pause symbols on the transport button", async ({
  page,
}) => {
  await openPage(page);
  const videos = await generateSequence(page);
  await waitForDecoded(videos);
  const play = page.getByRole("button", { name: "Play", exact: true });
  const pause = page.getByRole("button", { name: "Pause", exact: true });

  await expect(play).toHaveText("");
  await expect(play.locator("svg.lucide-play")).toBeVisible();
  const box = await play.boundingBox();

  await play.click();
  await expect(pause).toBeFocused();
  await expect(pause).toHaveText("");
  await expect(pause.locator("svg.lucide-pause")).toBeVisible();
  await expect(play).toHaveCount(0);
  expect(await pause.boundingBox()).toEqual(box);
  expect(
    await videos.evaluateAll((els) =>
      els.map((el) => (el as HTMLVideoElement).paused),
    ),
  ).toEqual([false, false, false, false]);

  // The keyboard works it as before: Enter on the focused button.
  await page.keyboard.press("Enter");
  await expect(play).toBeFocused();
  await expect(play.locator("svg.lucide-play")).toBeVisible();
  await expect
    .poll(() =>
      videos.evaluateAll((els) =>
        els.map((el) => (el as HTMLVideoElement).paused),
      ),
    )
    .toEqual([true, true, true, true]);
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

/**
 * The bokeh strength is k, the blur radius in pixels at 1024 px: 16 until moved, from 0 to
 * 64. It goes with Generate like the other parameters, stays where it was put, and the line
 * above the panes names the one the sequence came with. Another k is another sequence.
 */
test("sends the bokeh strength and names the sequence by it", async ({
  page,
}) => {
  // Two sequences generated, which on a CI runner takes longer than the default budget.
  test.slow();
  await openPage(page);
  const strength = page.getByRole("slider", { name: "Bokeh strength" });
  await expect(strength).toHaveAttribute("aria-valuenow", "16");
  await expect(strength).toHaveAttribute("aria-valuemin", "0");
  await expect(strength).toHaveAttribute("aria-valuemax", "64");
  // The helper text under it, read with the control rather than only seen near it.
  await expect(strength).toHaveAccessibleDescription(
    /^k, the blur radius in pixels at 1024 px/,
  );

  const sent: unknown[] = [];
  page.on("request", (request) => {
    if (request.method() === "POST" && request.url().endsWith("/sequences"))
      sent.push(request.postDataJSON().bokeh_strength);
  });
  const shown = page.getByRole("group", { name: "Sequence on screen" });
  const sequenceId = () => shown.getByText(/^[0-9a-f]{16}$/).innerText();

  await generateSequence(page, 31);
  await expect(shown).toContainText("bokeh 16");
  const first = await sequenceId();

  // The ends of the range, then one step at a time.
  await strength.focus();
  await page.keyboard.press("End");
  await expect(strength).toHaveAttribute("aria-valuenow", "64");
  await page.keyboard.press("Home");
  await expect(strength).toHaveAttribute("aria-valuenow", "0");
  for (let k = 0; k < 24; k++) await page.keyboard.press("ArrowRight");
  await expect(strength).toHaveAttribute("aria-valuenow", "24");
  await expect(
    page.locator("#parameters").getByText("24", { exact: true }),
  ).toBeVisible();

  await page.getByRole("button", { name: "Generate sequence" }).click();
  await expect(shown).toContainText("bokeh 24", { timeout: 60_000 });
  expect(await sequenceId()).not.toBe(first);
  await expect(page.getByText("cached", { exact: true })).toHaveCount(0);
  await expect(strength).toHaveAttribute("aria-valuenow", "24");
  expect(sent).toEqual([16, 24]);
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
              bokeh_strength: params.bokeh_strength,
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
    name: "Color is direction, pale is slow.",
  });
  await expect(legend).toBeVisible();
  const tooltip = page.getByRole("tooltip");
  await expect(tooltip).toHaveCount(0);
  await direction.focus();
  await page.keyboard.press("Tab");
  await expect(legend).toBeFocused();
  await expect(tooltip).toContainText("where it moves in the next frame");
  await expect(legend).toHaveAccessibleDescription(
    /where it moves in the next frame/,
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
    "where it came from in the previous frame",
  );
  await expect(tooltip).not.toContainText("where it moves in the next frame");
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
  // One short line under the pane, as the flow's; the full reading is a tooltip, by
  // keyboard too.
  const legend = pane.getByRole("button", {
    name: "White marks what the next frame hides.",
  });
  await expect(legend).toBeVisible();
  const tooltip = page.getByRole("tooltip");
  await expect(tooltip).toHaveCount(0);
  // On screen first: a focus that scrolls the page closes the tooltip it has just opened.
  await legend.scrollIntoViewIfNeeded();
  // The scroll event it dispatches comes a frame later, so wait it out, or it closes the
  // tooltip the Tab below opens.
  await page.evaluate(
    () =>
      new Promise<void>((done) =>
        requestAnimationFrame(() => requestAnimationFrame(() => done())),
      ),
  );
  await toggle.focus();
  await page.keyboard.press("Tab");
  await expect(legend).toBeFocused();
  await expect(tooltip).toContainText(
    "These pixels show a surface the next frame does not",
  );
  await expect(legend).toHaveAccessibleDescription(
    /These pixels show a surface the next frame does not/,
  );
  await page.keyboard.press("Escape");
  await expect(tooltip).toHaveCount(0);

  await toggle.click();
  await expect(toggle).toHaveAttribute("aria-pressed", "true");
  await expect(video).toHaveAttribute("src", /occlusion\.mp4\?overlay=true$/);
  await waitForDecoded(video);
  await expect(
    pane.getByRole("button", { name: "Cyan marks what the next frame hides." }),
  ).toBeVisible();
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

/**
 * The seed of the one sequence every six-pane test opens, so the API builds it once. It
 * gets bokeh faked into it, which no other test's sequence may have: the default seed's
 * stays at four streams.
 */
const SIX_PANE_SEED = 81;

/**
 * Open all six streams: bokeh faked into the sequence, and occlusion from "Add pane". The
 * sequence is shared, so it may already have its bokeh from an earlier test: generating
 * it then lists five streams at once, and faking the bokeh again changes nothing.
 */
async function openSixPanes(page: Page) {
  await page
    .getByRole("spinbutton", { name: "Seed" })
    .fill(String(SIX_PANE_SEED));
  await page.getByRole("button", { name: "Generate sequence" }).click();
  const videos = page.locator("video");
  await expect
    .poll(() => videos.count(), { timeout: 60_000 })
    .toBeGreaterThanOrEqual(4);
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
 * narrow six panes side by side make them: a caption wraps beside its wheel or swatch,
 * onto two lines at most, whole, rather than push its dropdown or button down or lose its
 * end. The occlusion's is checked with the overlay off and on.
 */
test("lines up the controls under six narrow panes", async ({ page }) => {
  test.slow();
  await page.setViewportSize({ width: 1760, height: 640 });
  await openPage(page);
  await openSixPanes(page);
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
    .evaluate(
      (el) => el.closest("[data-pane-view]")!.getBoundingClientRect().bottom,
    );
  const flowCaption = "Color is direction, pale is slow.";
  // The overlay is off when a sequence opens, so its caption starts with the longer
  // "White"; switching it on gives "Cyan".
  for (const occlusionCaption of [
    "White marks what the next frame hides.",
    "Cyan marks what the next frame hides.",
  ]) {
    if (occlusionCaption.startsWith("Cyan"))
      await page.getByRole("button", { name: "Overlay" }).click();
    for (const control of [
      page.getByRole("combobox", { name: "Colormap" }),
      page.getByRole("button", { name: "Overlay" }),
      page.getByRole("combobox", { name: "Direction" }),
      page.getByRole("button", { name: flowCaption }),
      page.getByRole("button", { name: occlusionCaption }),
    ]) {
      // Directly beneath the frame: the figure's 8 px gap, no more.
      await expect
        .poll(async () => Math.round((await control.boundingBox())!.y))
        .toBe(Math.round(frameBottom + 8));
    }
    // The margin is the width a caption could lose and still fit. The flow's row has none
    // to spare, because the dropdown beside it keeps its width.
    for (const [text, margin] of [
      [flowCaption, 0],
      [occlusionCaption, 10],
    ] as const) {
      // The wheel's, and the swatch's, 28 px box is the height of the dropdowns and level
      // with them too, not pushed down by the caption beside it.
      const swatchBox = page
        .getByRole("button", { name: text })
        .locator("span")
        .first();
      const box = (await swatchBox.boundingBox())!;
      expect(Math.round(box.y)).toBe(Math.round(frameBottom + 8));
      expect(box.height).toBe(28);
      // The caption shows all of itself, on two lines at most, not a paragraph wrapped
      // down the pane and not cut off with an ellipsis, and would still with the margin's
      // width less, which is room for another machine's text rendering.
      const caption = page.getByText(text, { exact: true });
      const shown = await caption.evaluate((el, margin) => {
        const whole = () =>
          el.scrollWidth <= el.clientWidth &&
          el.scrollHeight <= el.clientHeight;
        const lines =
          el.getBoundingClientRect().height /
          parseFloat(getComputedStyle(el).lineHeight);
        const wholeNow = whole();
        el.style.maxWidth = `${el.clientWidth - margin}px`;
        const slack = whole();
        el.style.maxWidth = "";
        return { whole: wholeNow, lines, slack };
      }, margin);
      expect(shown.whole).toBe(true);
      expect(shown.lines).toBeLessThanOrEqual(2);
      expect(shown.slack).toBe(true);
    }
  }
});

/**
 * Where the work area and the three parts of the column in it sit: the sequence info, the
 * pane grid and the transport.
 */
async function columnEdges(page: Page) {
  const edges = (locator: Locator) =>
    locator.evaluate((el) => {
      const box = el.getBoundingClientRect();
      return { left: box.left, right: box.right };
    });
  return {
    area: await edges(page.locator("main > section")),
    info: await edges(page.getByRole("group", { name: "Sequence on screen" })),
    // The panes' own extent, which the grid element's box need not match.
    grid: await page.locator("figure").evaluateAll((els) => {
      const boxes = els.map((el) => el.getBoundingClientRect());
      return {
        left: Math.min(...boxes.map((box) => box.left)),
        right: Math.max(...boxes.map((box) => box.right)),
      };
    }),
    transport: await edges(
      page.getByRole("button", { name: "Play" }).locator("xpath=.."),
    ),
    overflow: await page.evaluate(
      () =>
        document.documentElement.scrollWidth -
        document.documentElement.clientWidth,
    ),
  };
}

/**
 * Six panes in two rows are held to the window's height, so on a wide screen they need
 * less than the work area's width. The sequence info, the grid and the transport are then
 * one column of the same width, centered, rather than panes against the left edge under
 * rows that stretch across.
 */
test("centers the info, six panes and transport as one column", async ({
  page,
}) => {
  test.slow();
  await page.setViewportSize({ width: 2560, height: 1300 });
  await openPage(page);
  await openSixPanes(page);

  const expectCentered = async (place: string) => {
    await expect
      .poll(
        async () => {
          const { area, info, grid, transport, overflow } =
            await columnEdges(page);
          const margins = {
            left: grid.left - area.left,
            right: area.right - grid.right,
          };
          return {
            // Half the free space on each side, to a pixel.
            even: Math.abs(margins.left - margins.right) <= 1,
            // Not the whole width: the case this guards is the one with room to spare.
            narrower: grid.right - grid.left < area.right - area.left - 100,
            // One column: the same edges, to a pixel.
            info: [info.left - grid.left, info.right - grid.right].map((d) =>
              Math.abs(d) <= 1 ? 0 : d,
            ),
            transport: [
              transport.left - grid.left,
              transport.right - grid.right,
            ].map((d) => (Math.abs(d) <= 1 ? 0 : d)),
            overflow,
          };
        },
        { message: place },
      )
      .toEqual({
        even: true,
        narrower: true,
        info: [0, 0],
        transport: [0, 0],
        overflow: 0,
      });
  };

  // Equal margins hold for a stale width too, so the panes must have taken their new size
  // before the margins mean anything.
  const paneWidth = async () =>
    (await page.locator("figure").first().boundingBox())!.width;
  const resize = async (width: number, height: number) => {
    const before = await paneWidth();
    await page.setViewportSize({ width, height });
    await expect.poll(paneWidth).not.toBe(before);
  };
  await expectCentered("2560 x 1300");
  await resize(1920, 1080);
  await expectCentered("1920 x 1080");
  // The parameters fold away, the work area grows, and the column stays in its middle.
  await page.getByRole("button", { name: "Parameters" }).click();
  await expect(
    page.getByRole("button", { name: "Generate sequence" }),
  ).toBeHidden();
  await expectCentered("1920 x 1080, parameters folded");
  // Low enough that one row of six is held to the height and leaves room to spare; at 1000
  // px high they would fill the width.
  await resize(3440, 800);
  await expectCentered("3440 x 800");
});

/**
 * A small pane in a 1100 px window is narrower than the transport needs for one line, so
 * the column is wider than it is and the pane sits in the middle of it. The transport
 * stays on a single line, which the height it keeps free assumes. One pane, so that the
 * grid is far from the width where it would take the whole work area.
 */
test("keeps the transport on one line under a small pane", async ({ page }) => {
  await page.setViewportSize({ width: 1100, height: 800 });
  await openPage(page);
  await generateSequence(page);
  for (const name of ["Alpha", "Disparity", "Optical flow"])
    await page.getByRole("button", { name: `Close ${name} pane` }).click();
  await expect(page.locator("figure")).toHaveCount(1);
  await expect
    .poll(async () => {
      const { info, grid, overflow } = await columnEdges(page);
      const box = (await page
        .getByRole("button", { name: "Play" })
        .locator("xpath=..")
        .boundingBox())!;
      return {
        // Well inside the column, as this test is about.
        small: grid.right - grid.left < info.right - info.left - 100,
        centered:
          Math.abs(grid.left - info.left - (info.right - grid.right)) <= 1,
        oneLine: box.height <= 60,
        overflow,
      };
    })
    .toEqual({ small: true, centered: true, oneLine: true, overflow: 0 });
});

/**
 * The info row is wider on one line than the column's minimum when the seed has many
 * digits. If the column were narrower than the row it would wrap, the grid would drop by
 * a line, six panes only just fitting at 200 px would no longer fit, and the page would
 * flip between fitting them and scrolling for good. The column holds the row on one line
 * instead, and the layout stays put.
 */
test("keeps the layout still when the info row is wider than the minimum", async ({
  page,
}) => {
  test.slow();
  // Only the number shown is long: the page reads it from the generation's last line, and
  // the files are the sequence's own.
  await page.route("**/sequences", async (route) => {
    if (route.request().method() !== "POST") return route.fallback();
    const response = await route.fetch();
    const body = (await response.text())
      .split("\n")
      .map((line) => {
        if (!line.includes('"sequence"')) return line;
        const event = JSON.parse(line);
        event.sequence.seed = 123456789012345;
        return JSON.stringify(event);
      })
      .join("\n");
    await route.fulfill({ response, body });
  });
  await openPage(page);
  await openSixPanes(page);
  await expect(page.getByText("123456789012345")).toBeVisible();
  // Narrowed afterwards: a page that flips between fitting and scrolling cannot be clicked.
  const first = page.locator("figure").first();
  const before = (await first.boundingBox())!.width;
  // Wide enough for the row on one line: it is a few pixels wider with "256 × 256" than
  // with "512 × 512", the digit 1 being narrower, and a work area it does not fit takes
  // the column whole and wraps it, which is another case than this one.
  await page.setViewportSize({ width: 1160, height: 800 });
  await expect
    .poll(async () => (await first.boundingBox())!.width)
    .not.toBe(before);
  // Past the first layout, which is not what is being tested.
  await page.waitForTimeout(500);

  const info = page.getByRole("group", { name: "Sequence on screen" });
  const grid = page.locator("figure").first().locator("xpath=..");
  const sampled = await grid.evaluate(async (el) => {
    const seen = new Set<string>();
    for (let i = 0; i < 24; i++) {
      seen.add(getComputedStyle(el).gridTemplateColumns);
      await new Promise((done) => setTimeout(done, 50));
    }
    return [...seen];
  });
  expect(sampled).toHaveLength(1);
  // One line is under 30 px high, two over 40.
  expect((await info.boundingBox())!.height).toBeLessThan(30);
});

/**
 * Where the panes already take the whole width, as six do in a window too low to fit them
 * at 200 px, there is nothing to center: the column is the work area, as it was.
 */
test("keeps six panes that fill the width across the work area", async ({
  page,
}) => {
  test.slow();
  await page.setViewportSize({ width: 1100, height: 600 });
  await openPage(page);
  await openSixPanes(page);
  for (const [width, height] of [
    [1100, 600],
    [390, 800],
  ]) {
    await page.setViewportSize({ width, height });
    await expect
      .poll(async () => {
        const { area, info, grid, transport, overflow } =
          await columnEdges(page);
        return [
          grid.left - area.left,
          area.right - grid.right,
          info.left - area.left,
          info.right - area.right,
          transport.left - area.left,
          transport.right - area.right,
          overflow,
        ].map((d) => Math.round(d));
      })
      .toEqual([0, 0, 0, 0, 0, 0, 0]);
  }
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
  const videos = await openSixPanes(page);
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
  const frameBox = page.locator("[data-pane-view]").first();
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
  // End and Home go to either end and leave no scrub open.
  await page.keyboard.press("End");
  await settledAt(79);
  await page.keyboard.press("Home");
  await settledAt(0);

  // A drag while playing holds the panes still under it, and they play on after.
  await page.getByRole("button", { name: "Play" }).click();
  const at = (await slider.boundingBox())!;
  await page.mouse.move(at.x + at.width / 2, y);
  await page.mouse.down();
  await page.mouse.move(track.x + track.width / 2, y, { steps: 10 });
  expect(
    await videos.evaluateAll((els) =>
      els.map((el) => (el as HTMLVideoElement).paused),
    ),
  ).toEqual(Array(6).fill(true));
  await page.mouse.up();
  await expect
    .poll(() =>
      videos.evaluateAll((els) =>
        els.map((el) => (el as HTMLVideoElement).paused),
      ),
    )
    .toEqual(Array(6).fill(false));
  await expect(page.getByRole("button", { name: "Pause" })).toBeVisible();
});

/**
 * While the panes play, the position thumb glides: it follows the leading video every
 * animation frame, between frames, at every speed, and does not jump from one timeupdate
 * event to the next, about four a second. The counter names the frame shown, the one
 * nearest the thumb. Paused, the thumb rests on that frame.
 */
test("moves the position thumb smoothly while the panes play", async ({
  page,
}) => {
  await openPage(page);
  const videos = await generateSequence(page);
  await waitForDecoded(videos);
  const slider = page.getByRole("slider", { name: "Position" });

  /** The thumb's position, the frame named and when, every 25 ms for a second. */
  const sample = () =>
    slider.evaluate(async (el) => {
      const seen: { at: number; frame: number; when: number }[] = [];
      const until = performance.now() + 1000;
      while (performance.now() < until) {
        seen.push({
          at: Number(el.getAttribute("aria-valuenow")),
          frame: Number(el.getAttribute("aria-valuetext")!.split(" ")[1]) - 1,
          when: performance.now() / 1000,
        });
        await new Promise((resolve) => setTimeout(resolve, 25));
      }
      return seen;
    });

  for (const speed of [0.25, 1, 2]) {
    await slider.focus();
    await page.keyboard.press("Home");
    await expect(slider).toHaveAttribute("aria-valuenow", "0");
    await page.getByRole("combobox", { name: "Playback speed" }).click();
    await page.getByRole("option", { name: `${speed}×` }).click();
    await page.getByRole("button", { name: "Play" }).click();
    const seen = await sample();
    await page.getByRole("button", { name: "Pause" }).click();

    const positions = seen.map((s) => s.at);
    // More positions than the four or five timeupdate events a second would give.
    expect(new Set(positions).size, `${speed}×`).toBeGreaterThan(10);
    // Forward only, and from one sample to the next by no more than the frames the video
    // played in between, at 24 a second, plus 200 ms: the thumb may trail a busy main
    // thread, as on a CI runner, but never by the quarter second between timeupdate events.
    seen.slice(1).forEach((s, i) => {
      const step = s.at - seen[i].at;
      expect(step, `${speed}×`).toBeGreaterThanOrEqual(0);
      expect(step, `${speed}×`).toBeLessThanOrEqual(
        speed * 24 * (s.when - seen[i].when + 0.2),
      );
    });
    // The counter names the whole frame nearest the thumb.
    expect(
      seen.map((s) => s.frame),
      `${speed}×`,
    ).toEqual(positions.map((p) => Math.round(p)));

    // Paused, the thumb rests on the whole frame shown.
    const resting = Number(await slider.getAttribute("aria-valuenow"));
    expect(Number.isInteger(resting), `${speed}×`).toBe(true);
    await expect(page.getByText(/^\d+ \/ 80$/)).toHaveText(
      `${resting + 1} / 80`,
    );
  }

  // A drag let go while playing goes on from where it was let go, from the first frame
  // drawn after, and does not flash back to where the drag began.
  await slider.focus();
  await page.keyboard.press("Home");
  await page.getByRole("button", { name: "Play" }).click();
  await page.waitForTimeout(500);
  const track = (await page
    .locator('[data-slot="slider"]', { has: slider })
    .boundingBox())!;
  const thumb = (await slider.boundingBox())!;
  const y = thumb.y + thumb.height / 2;
  await page.mouse.move(thumb.x + thumb.width / 2, y);
  await page.mouse.down();
  await page.mouse.move(track.x + track.width * 0.5, y, { steps: 5 });
  const target = Number(await slider.getAttribute("aria-valuenow"));
  // The thumb's position on every animation frame from here until 300 ms on.
  await slider.evaluate((el) => {
    const seen: number[] = [];
    (window as unknown as { seen: number[] }).seen = seen;
    const until = performance.now() + 300;
    const read = () => {
      seen.push(Number(el.getAttribute("aria-valuenow")));
      if (performance.now() < until) requestAnimationFrame(read);
    };
    requestAnimationFrame(read);
  });
  await page.mouse.up();
  await page.waitForTimeout(400);
  const after = await page.evaluate(
    () => (window as unknown as { seen: number[] }).seen,
  );
  expect(Math.min(...after)).toBeGreaterThanOrEqual(Math.round(target) - 0.5);
  await page.getByRole("button", { name: "Pause" }).click();
});

/**
 * Six panes playing on a slow machine, which CPU throttling stands in for: on every animation
 * frame the thumb is where the leading video is, not a render behind it. A thumb that waits
 * for a render stands still while the video moves on, then jumps. Measured on its rendered
 * position against the video's time, read in the same animation frame. Following the video
 * renders nothing either, which the script time shows, at this throttling: a render of
 * every pane on each timeupdate took 470 ms of it a second, one of the slider on each
 * animation frame 140 ms, and following without rendering 8 ms.
 */
test("keeps the position thumb on the playing video under a loaded main thread", async ({
  page,
}) => {
  test.slow();
  await page.setViewportSize({ width: 1760, height: 640 });
  await openPage(page);
  const videos = await openSixPanes(page);
  const slider = page.getByRole("slider", { name: "Position" });
  const cdp = await page.context().newCDPSession(page);
  await cdp.send("Emulation.setCPUThrottlingRate", { rate: 4 });
  await cdp.send("Performance.enable");
  const scriptSeconds = async () =>
    (await cdp.send("Performance.getMetrics")).metrics.find(
      (m) => m.name === "ScriptDuration",
    )!.value;

  await slider.focus();
  await page.keyboard.press("Home");
  await page.getByRole("button", { name: "Play" }).click();
  // Started after the play, so each animation frame reads the thumb after it has moved.
  await page.waitForTimeout(400);
  const scriptBefore = await scriptSeconds();
  const seen = await slider.evaluate(
    async (thumb, lead) => {
      const video = lead as HTMLVideoElement;
      const track = thumb
        .closest('[data-slot="slider"]')!
        .querySelector('[data-slot="slider-track"]')!;
      const lastFrame = Number(thumb.getAttribute("aria-valuemax"));
      // Where the thumb is, in frames: its center travels the track less its own width.
      const position = () => {
        const box = thumb.getBoundingClientRect();
        const rail = track.getBoundingClientRect();
        return ((box.left - rail.left) / (rail.width - box.width)) * lastFrame;
      };
      // Where the video is, in frames, half a frame back, as the slider shows it.
      const playing = () =>
        Math.min(
          Math.max(
            (video.currentTime / video.duration) * (lastFrame + 1) - 0.5,
            0,
          ),
          lastFrame,
        );
      const behind: number[] = [];
      const started = performance.now();
      await new Promise<void>((done) => {
        const read = (when: number) => {
          behind.push(playing() - position());
          if (when < started + 2000) requestAnimationFrame(read);
          else done();
        };
        requestAnimationFrame(read);
      });
      return { behind, seconds: (performance.now() - started) / 1000 };
    },
    await videos.first().elementHandle(),
  );
  const scriptPerSecond =
    ((await scriptSeconds()) - scriptBefore) / seen.seconds;
  await page.getByRole("button", { name: "Pause" }).click();
  await cdp.send("Emulation.setCPUThrottlingRate", { rate: 1 });

  expect(seen.behind.length).toBeGreaterThan(20);
  // How far the thumb trails the video, in frames, apart from the loop back to the start.
  const trailing = seen.behind.filter((d) => Math.abs(d) < 40);
  const spread = Math.sqrt(
    trailing.reduce((sum, d) => sum + d * d, 0) / trailing.length,
  );
  // About 0.01 of a frame following the video, against 0.8 a render behind and 1.5 when
  // every pane renders too.
  expect(spread).toBeLessThan(0.25);
  expect(scriptPerSecond).toBeLessThan(0.05);
});

/**
 * A drag the browser cancels, or one cut short by the page losing focus, ends like one let
 * go: the panes play on rather than sit paused until the slider is touched again.
 */
test("plays on after a drag that is canceled", async ({ page }) => {
  await openPage(page);
  const videos = await generateSequence(page);
  await waitForDecoded(videos);
  const slider = page.getByRole("slider", { name: "Position" });
  const track = (await page
    .locator('[data-slot="slider"]', { has: slider })
    .boundingBox())!;
  const paused = () =>
    videos.evaluateAll((els) =>
      els.map((el) => (el as HTMLVideoElement).paused),
    );
  await page.getByRole("button", { name: "Play" }).click();

  const cancels: [string, () => Promise<void>][] = [
    ["pointercancel", () => slider.dispatchEvent("pointercancel")],
    ["blur", () => slider.evaluate((el) => (el as HTMLElement).blur())],
  ];
  for (const [name, cancel] of cancels) {
    const thumb = (await slider.boundingBox())!;
    const y = thumb.y + thumb.height / 2;
    await page.mouse.move(thumb.x + thumb.width / 2, y);
    await page.mouse.down();
    await page.mouse.move(thumb.x + track.width / 4, y, { steps: 5 });
    expect(await paused(), name).toEqual([true, true, true, true]);
    await cancel();
    await expect
      .poll(paused, { message: name })
      .toEqual([false, false, false, false]);
    await expect(page.getByRole("button", { name: "Pause" })).toBeVisible();
    await page.mouse.up();
  }
});

/**
 * A new sequence arriving while the slider is held rewinds the transport to a stop, and
 * letting go then does not start the new videos behind a button that reads Play.
 */
test("keeps a sequence that arrives mid-drag paused", async ({ page }) => {
  // Two sequences generated and encoded, which takes a CI runner most of the default.
  test.slow();
  await openPage(page);
  const videos = await generateSequence(page, 7);
  await waitForDecoded(videos);
  const slider = page.getByRole("slider", { name: "Position" });
  const sequenceId = page
    .getByRole("group", { name: "Sequence on screen" })
    .getByText(/^[0-9a-f]{16}$/);
  const first = await sequenceId.innerText();
  // The next sequence's seed, set before the drag, which a click into the field would end.
  await page.getByRole("spinbutton", { name: "Seed" }).fill("8");
  await page.getByRole("button", { name: "Play" }).click();

  const track = (await page
    .locator('[data-slot="slider"]', { has: slider })
    .boundingBox())!;
  const thumb = (await slider.boundingBox())!;
  const y = thumb.y + thumb.height / 2;
  await page.mouse.move(thumb.x + thumb.width / 2, y);
  await page.mouse.down();
  await page.mouse.move(thumb.x + track.width / 4, y, { steps: 5 });
  // A click that moves neither the pointer nor the focus, as a generation finishing while
  // the slider is held would.
  await page
    .getByRole("button", { name: "Generate sequence" })
    .evaluate((el) => (el as HTMLButtonElement).click());
  await expect(sequenceId).not.toHaveText(first, { timeout: 60_000 });
  await page.mouse.up();

  await waitForDecoded(videos);
  await expect(page.getByRole("button", { name: "Play" })).toBeVisible();
  const times = () =>
    videos.evaluateAll((els) =>
      els.map((el) => (el as HTMLVideoElement).currentTime),
    );
  const before = await times();
  await page.waitForTimeout(400);
  expect(
    await videos.evaluateAll((els) =>
      els.map((el) => (el as HTMLVideoElement).paused),
    ),
  ).toEqual([true, true, true, true]);
  expect(await times()).toEqual(before);
});

/**
 * Loading another video in a pane, by its stream, colormap, direction or overlay, keeps
 * every pane on the frame the transport is at, playing or paused. A video given a new
 * source reads time 0 until it loads, and the first pane's once dragged every pane there.
 */
test("keeps the frame when a pane loads another video", async ({ page }) => {
  // A generation and every switch encoded on first request, at a quarter speed.
  test.slow();
  await openPage(page);
  const videos = await generateSequence(page);
  await waitForDecoded(videos);
  await addPaneFor(page, "Occlusion");
  await expect(videos).toHaveCount(5);
  await waitForDecoded(videos);
  const slider = page.getByRole("slider", { name: "Position" });
  const counter = page.getByText(/^\d+ \/ 80$/);
  const panes = page.locator("figure");

  /** Pick `option` in the `name` dropdown of the pane at `index`. */
  const choose = async (index: number, name: string, option: string) => {
    await panes.nth(index).getByRole("combobox", { name }).click();
    await page.getByRole("option", { name: option, exact: true }).click();
  };
  // Each one loads another video in one pane: there and, on the second pass, back.
  const switches: [string, number, (back: boolean) => Promise<void>][] = [
    [
      "first pane's stream",
      0,
      (back) => choose(0, "Stream", back ? "All in focus" : "Disparity"),
    ],
    [
      "second pane's stream",
      1,
      (back) => choose(1, "Stream", back ? "Alpha" : "Optical flow"),
    ],
    [
      "colormap",
      2,
      (back) => choose(2, "Colormap", back ? "Spectral" : "Gray"),
    ],
    [
      "flow direction",
      3,
      (back) => choose(3, "Direction", back ? "Forward" : "Backward"),
    ],
    [
      "occlusion overlay",
      4,
      () => panes.nth(4).getByRole("button", { name: "Overlay" }).click(),
    ],
  ];

  /** The frame each pane with a loaded video shows, null for one still loading. */
  const frames = () =>
    videos.evaluateAll((els) =>
      els.map((el) => {
        const v = el as HTMLVideoElement;
        return v.readyState < 1
          ? null
          : Math.floor((v.currentTime / v.duration) * 80);
      }),
    );
  /** Until the pane at `index` has a new video, decoded. */
  const reloaded = async (index: number, was: string) => {
    const video = videos.nth(index);
    await expect(video).not.toHaveAttribute("src", was);
    await waitForDecoded(video);
  };
  const seekTo = async (frame: number) => {
    await slider.focus();
    await page.keyboard.press("Home");
    for (let i = 0; i < frame / 10; i++) await page.keyboard.press("PageUp");
  };

  await page.getByRole("combobox", { name: "Playback speed" }).click();
  await page.getByRole("option", { name: "0.25×" }).click();
  await page.getByRole("button", { name: "Play" }).click();
  for (const [name, index, change] of switches) {
    await seekTo(20);
    await expect
      .poll(async () => Math.min(...((await frames()) as number[])))
      .toBeGreaterThan(20);
    const before = Math.min(...((await frames()) as number[]));
    const was = (await videos.nth(index).getAttribute("src"))!;
    await change(false);
    // Every pane and the counter, from the switch until the new video plays.
    const seen: number[] = [];
    const watch = async () => {
      seen.push(
        ...((await frames()).filter((f) => f !== null) as number[]),
        Number((await counter.innerText()).split(" ")[0]) - 1,
      );
    };
    await watch();
    await reloaded(index, was);
    for (let i = 0; i < 5; i++) {
      await watch();
      await page.waitForTimeout(100);
    }
    expect.soft(Math.min(...seen), name).toBeGreaterThanOrEqual(before - 1);
    const after = (await frames()) as number[];
    expect
      .soft(Math.max(...after) - Math.min(...after), name)
      .toBeLessThanOrEqual(1);
    expect(
      await videos.evaluateAll((els) =>
        els.map((el) => (el as HTMLVideoElement).paused),
      ),
      name,
    ).toEqual([false, false, false, false, false]);
  }

  await page.getByRole("button", { name: "Pause" }).click();
  for (const [name, index, change] of switches) {
    await seekTo(30);
    await expect.poll(frames).toEqual([30, 30, 30, 30, 30]);
    const was = (await videos.nth(index).getAttribute("src"))!;
    await change(true);
    await reloaded(index, was);
    await expect.poll(frames, { message: name }).toEqual([30, 30, 30, 30, 30]);
    await expect(counter, name).toHaveText("31 / 80");
    await expect(slider, name).toHaveAttribute("aria-valuenow", "30");
  }
});

/** Every video the page asks for arrives `ms` late, so a test can act while one loads. */
async function delayVideos(page: Page, ms: number) {
  await page.route("**/*", async (route) => {
    if (route.request().resourceType() === "media")
      await new Promise((resolve) => setTimeout(resolve, ms));
    await route.continue().catch(() => {});
  });
}

/**
 * A pane added while paused and moved first before its video arrives does not lead the
 * others back to the start once it loads: it starts where they are.
 */
test("keeps the frame when a pane moved first loads", async ({ page }) => {
  await openPage(page);
  const videos = await generateSequence(page);
  await waitForDecoded(videos);
  const slider = page.getByRole("slider", { name: "Position" });
  await slider.focus();
  await page.keyboard.press("Home");
  for (let i = 0; i < 3; i++) await page.keyboard.press("PageUp");
  await expect(page.getByText(/^\d+ \/ 80$/)).toHaveText("31 / 80");

  await delayVideos(page, 2000);
  await page.getByRole("button", { name: "Add pane" }).click();
  await expect(videos).toHaveCount(5);
  await page
    .locator("figure")
    .last()
    .getByRole("button", { name: /^Move / })
    .focus();
  for (let i = 0; i < 4; i++) await page.keyboard.press("ArrowLeft");
  await waitForDecoded(videos);
  await page.waitForTimeout(300);
  expect(
    await videos.evaluateAll((els) =>
      els.map((el) => {
        const v = el as HTMLVideoElement;
        return Math.floor((v.currentTime / v.duration) * 80);
      }),
    ),
  ).toEqual([30, 30, 30, 30, 30]);
  await expect(page.getByText(/^\d+ \/ 80$/)).toHaveText("31 / 80");
});

/**
 * A pane switched to another stream before a new sequence's first video arrives still
 * leads the transport once that loads: the counter moves as it plays.
 */
test("follows a pane switched before its first video loads", async ({
  page,
}) => {
  // Two sequences generated and encoded.
  test.slow();
  await openPage(page);
  const videos = await generateSequence(page);
  await waitForDecoded(videos);
  while ((await videos.count()) > 1)
    await page
      .getByRole("button", { name: /^Close .* pane$/ })
      .first()
      .click();

  await delayVideos(page, 2000);
  const was = (await videos.first().getAttribute("src"))!;
  await page.getByRole("spinbutton", { name: "Seed" }).fill("5");
  await page.getByRole("button", { name: "Generate sequence" }).click();
  await expect(videos.first()).not.toHaveAttribute("src", was, {
    timeout: 60_000,
  });
  await page.getByRole("combobox", { name: "Stream" }).click();
  await page.getByRole("option", { name: "Alpha", exact: true }).click();
  await waitForDecoded(videos);
  await page.getByRole("button", { name: "Play" }).click();
  const counter = page.getByText(/^\d+ \/ 80$/);
  await expect(counter).toHaveText("1 / 80");
  await expect(counter).not.toHaveText("1 / 80");
});

/**
 * The region of the frame each pane shows: the frame's fractions at the pane's left, top,
 * right and bottom edges, inside its border, to three places.
 */
function shownRegions(page: Page) {
  return page.locator("[data-pane-view]").evaluateAll((panes) =>
    panes.map((pane) => {
      const box = pane.getBoundingClientRect();
      const frame = pane.querySelector("video")!.getBoundingClientRect();
      const left = box.left + pane.clientLeft;
      const top = box.top + pane.clientTop;
      return [
        (left - frame.left) / frame.width,
        (top - frame.top) / frame.height,
        (left + pane.clientWidth - frame.left) / frame.width,
        (top + pane.clientHeight - frame.top) / frame.height,
      ].map((v) => Math.round(v * 1000) / 1000 + 0);
    }),
  );
}

/** Every pane shows `region` of the frame. */
async function expectRegions(page: Page, region: number[]) {
  const panes = await page.locator("[data-pane-view]").count();
  await expect
    .poll(() => shownRegions(page))
    .toEqual(Array(panes).fill(region));
}

/** The frame point under the screen point (`x`, `y`) in the pane at `index`. */
function framePointAt(page: Page, index: number, x: number, y: number) {
  return page
    .locator("[data-pane-view] video")
    .nth(index)
    .evaluate(
      (el, [x, y]) => {
        const frame = el.getBoundingClientRect();
        return [(x - frame.left) / frame.width, (y - frame.top) / frame.height];
      },
      [x, y],
    );
}

/** Record whether each wheel event that reaches the window was kept from scrolling. */
async function watchWheel(page: Page) {
  await page.evaluate(() => {
    const seen: boolean[] = [];
    (window as unknown as { wheels: boolean[] }).wheels = seen;
    window.addEventListener("wheel", (e) => seen.push(e.defaultPrevented));
  });
  return () =>
    page.evaluate(() => (window as unknown as { wheels: boolean[] }).wheels);
}

/**
 * Zoom is one view for every pane: the keys and the buttons zoom about the middle, a drag
 * or the wheel moves the view anywhere in the frame but never past its edges, and a pane
 * that switches its stream or is added shows the same region.
 */
test("zooms and moves every pane's view together", async ({ page }) => {
  test.slow();
  await page.setViewportSize({ width: 1500, height: 800 });
  await openPage(page);
  await waitForDecoded(await generateSequence(page));
  const factor = page.getByRole("button", { name: /show the whole frame$/ });
  await expect(factor).toHaveText("1×");
  await expect(page.getByRole("button", { name: "Zoom out" })).toBeDisabled();
  await expectRegions(page, [0, 0, 1, 1]);

  await page.keyboard.press("+");
  await expect(factor).toHaveText("2×");
  await expectRegions(page, [0.25, 0.25, 0.75, 0.75]);
  await page.getByRole("button", { name: "Zoom in" }).click();
  await expect(factor).toHaveText("4×");
  await expectRegions(page, [0.375, 0.375, 0.625, 0.625]);

  // A drag in one pane by a fifth of its width moves the frame under the pointer with it,
  // in every pane: a fifth of the quarter of the frame on screen.
  const pane = page.locator("[data-pane-view]").nth(1);
  const box = (await pane.boundingBox())!;
  const x = box.x + box.width / 2;
  const y = box.y + box.height / 2;
  await page.mouse.move(x, y);
  await page.mouse.down();
  await page.mouse.move(x + (box.width - 2) / 5, y, { steps: 5 });
  await page.mouse.up();
  await expectRegions(page, [0.325, 0.375, 0.575, 0.625]);

  // The wheel moves it too, and the page does not scroll.
  const wheels = await watchWheel(page);
  await page.mouse.wheel(0, 40);
  await expect.poll(wheels).toEqual([true]);
  const [, top] = (await shownRegions(page))[0];
  expect(top).toBeGreaterThan(0.375);
  expect(await page.evaluate(() => window.scrollY)).toBe(0);

  // Dragged far past the frame's corner, the view stops at it.
  await page.mouse.move(x, y);
  await page.mouse.down();
  await page.mouse.move(x + box.width * 3, y + box.height * 3, { steps: 5 });
  await page.mouse.up();
  await expectRegions(page, [0, 0, 0.25, 0.25]);

  // Another stream in a pane, and a pane added, show the same region.
  await page.getByRole("combobox", { name: "Stream" }).first().click();
  await page.getByRole("option", { name: "Disparity", exact: true }).click();
  await addPaneFor(page, "Occlusion");
  await expectRegions(page, [0, 0, 0.25, 0.25]);

  // Zoomed out about the middle of the view, which the edges then hold.
  await page.getByRole("button", { name: "Zoom out" }).click();
  await expect(factor).toHaveText("2×");
  await expectRegions(page, [0, 0, 0.5, 0.5]);
  await page.keyboard.press("0");
  await expect(factor).toHaveText("1×");
  await expectRegions(page, [0, 0, 1, 1]);
  // At the whole frame the wheel over a pane is the page's again.
  await page.mouse.move(x, y);
  await page.mouse.wheel(0, 40);
  await expect.poll(wheels).toEqual([true, false]);

  // Panes the page scrolls through, as on a phone, show one region too.
  await page.setViewportSize({ width: 390, height: 800 });
  await page.keyboard.press("+");
  await expectRegions(page, [0.25, 0.25, 0.75, 0.75]);
});

/**
 * A pinch, which arrives as the wheel with Ctrl, or in Safari as gesture events, zooms
 * about the pointer, and so does the wheel with Cmd: the frame point under it stays there,
 * in the pane it is over and the same point in every other pane. A double-click zooms in
 * about the point, and back out.
 */
test("zooms about the pointer with a pinch and a double-click", async ({
  page,
}) => {
  test.slow();
  await page.setViewportSize({ width: 1500, height: 800 });
  await openPage(page);
  await waitForDecoded(await generateSequence(page));
  const factor = page.getByRole("button", { name: /show the whole frame$/ });
  const box = (await page.locator("[data-pane-view]").nth(2).boundingBox())!;
  const x = box.x + box.width * 0.3;
  const y = box.y + box.height * 0.6;
  const before = await framePointAt(page, 2, x, y);

  const wheels = await watchWheel(page);
  await page.mouse.move(x, y);
  await page.keyboard.down("Control");
  await page.mouse.wheel(0, -60);
  await page.keyboard.up("Control");
  await expect(factor).not.toHaveText("1×");
  const once = await factor.innerText();
  await page.keyboard.down("Meta");
  await page.mouse.wheel(0, -60);
  await page.keyboard.up("Meta");
  await expect(factor).not.toHaveText(once);
  // Kept from zooming the page.
  await expect.poll(wheels).toEqual([true, true]);
  const after = await framePointAt(page, 2, x, y);
  expect(after[0]).toBeCloseTo(before[0], 2);
  expect(after[1]).toBeCloseTo(before[1], 2);
  const regions = await shownRegions(page);
  expect(new Set(regions.map((r) => r.join())).size).toBe(1);

  // Safari's pinch: each event scales the zoom the pinch began at.
  await page.keyboard.press("0");
  await expectRegions(page, [0, 0, 1, 1]);
  const prevented = await page
    .locator("[data-pane-view]")
    .nth(2)
    .evaluate(
      (pane, [x, y]) =>
        [
          ["gesturestart", 1],
          ["gesturechange", 1.5],
          ["gesturechange", 3],
          ["gestureend", 3],
        ].map(([type, scale]) => {
          const event = Object.assign(
            new Event(type as string, { bubbles: true, cancelable: true }),
            { scale, clientX: x, clientY: y },
          );
          pane.dispatchEvent(event);
          return event.defaultPrevented;
        }),
      [x, y],
    );
  expect(prevented).toEqual([true, true, true, true]);
  await expect(factor).toHaveText("3×");
  const pinched = await framePointAt(page, 2, x, y);
  expect(pinched[0]).toBeCloseTo(before[0], 2);
  expect(pinched[1]).toBeCloseTo(before[1], 2);
  // A pinch that ends off the panes leaves the wheel with Ctrl free to zoom.
  await page.locator("[data-pane-view]").nth(2).dispatchEvent("gesturestart");
  await page
    .locator("figure")
    .first()
    .locator("xpath=..")
    .dispatchEvent("gestureend");
  await page.mouse.move(x, y);
  await page.keyboard.down("Control");
  await page.mouse.wheel(0, -60);
  await page.keyboard.up("Control");
  await expect(factor).not.toHaveText("3×");

  await page.keyboard.press("0");
  await expectRegions(page, [0, 0, 1, 1]);
  await page.mouse.dblclick(x, y);
  await expect(factor).toHaveText("4×");
  const zoomed = await framePointAt(page, 2, x, y);
  expect(zoomed[0]).toBeCloseTo(before[0], 2);
  expect(zoomed[1]).toBeCloseTo(before[1], 2);
  await page.mouse.dblclick(x, y);
  await expect(factor).toHaveText("1×");
  await expectRegions(page, [0, 0, 1, 1]);
});

/**
 * The zoom keys are not taken from a field, a list, or the browser's own zoom, and a new
 * sequence starts at the whole frame. Zoomed in far enough, the video's pixels show as
 * squares; the frames from memory, at the pane's size, stay smooth.
 */
test("keeps the zoom keys out of fields and starts each sequence whole", async ({
  page,
}) => {
  test.slow();
  await page.setViewportSize({ width: 1500, height: 800 });
  await openPage(page);
  await waitForDecoded(await generateSequence(page));
  const factor = page.getByRole("button", { name: /show the whole frame$/ });
  const video = page.locator("[data-pane-view] video").first();
  const canvas = page.locator("[data-pane-view] canvas").first();
  const rendering = (locator: Locator) =>
    locator.evaluate((el) => getComputedStyle(el).imageRendering);
  await expect.poll(() => rendering(video)).toBe("auto");

  await page.keyboard.press("+");
  await expect(factor).toHaveText("2×");

  const seed = page.getByRole("spinbutton", { name: "Seed" });
  await seed.fill("11");
  await seed.press("0");
  await expect(seed).toHaveValue("110");
  await page.getByRole("combobox", { name: "Playback speed" }).click();
  await page.keyboard.press("0");
  await page.keyboard.press("Escape");
  await expect(
    page.getByRole("combobox", { name: "Playback speed" }),
  ).toHaveText("1×");
  await page.locator("body").click({ position: { x: 5, y: 5 } });
  await page.keyboard.press("Control+0");
  await page.keyboard.press("Control+Minus");
  await page.keyboard.press("Alt+Equal");
  await expect(factor).toHaveText("2×");
  // The gestures are named where the factor is.
  await expect(page.getByRole("group", { name: "Zoom" })).toHaveAttribute(
    "title",
    /^Pinch/,
  );

  for (let i = 0; i < 4; i++) await page.keyboard.press("=");
  await expect(factor).toHaveText("16×");
  await expect(page.getByRole("button", { name: "Zoom in" })).toBeDisabled();
  await expect.poll(() => rendering(video)).toBe("pixelated");
  expect(await rendering(canvas)).toBe("auto");

  await page.getByRole("button", { name: "Generate sequence" }).click();
  await expect(
    page.getByRole("group", { name: "Sequence on screen" }),
  ).toContainText(/seed\s*110/, { timeout: 60_000 });
  await expect(factor).toHaveText("1×");
  await waitForDecoded(page.locator("video"));
  await expectRegions(page, [0, 0, 1, 1]);
  await expect.poll(() => rendering(video)).toBe("auto");
});

/**
 * Zoomed in, a frame step shows the video's own frame: the frames in memory, at the
 * pane's size, would be soft there until the videos had sought.
 */
test("steps a frame zoomed in without the frames from memory", async ({
  page,
}) => {
  test.slow();
  await page.setViewportSize({ width: 1500, height: 800 });
  await openPage(page);
  const videos = await generateSequence(page);
  await waitForDecoded(videos);
  const canvases = page.locator("figure canvas");
  await expect
    .poll(
      () =>
        canvases.evaluateAll((els) =>
          els.map((el) => el.getAttribute("data-decoded")),
        ),
      { timeout: 60_000 },
    )
    .toEqual(Array(4).fill("80"));
  await page.keyboard.press("+");
  await expect(
    page.getByRole("button", { name: /show the whole frame$/ }),
  ).toHaveText("2×");
  // Every time a canvas is shown, from here on.
  await canvases.evaluateAll((els) => {
    const shown: string[] = [];
    (window as unknown as { shown: string[] }).shown = shown;
    for (const el of els)
      new MutationObserver(() => {
        if (getComputedStyle(el).visibility === "visible") shown.push("canvas");
      }).observe(el, { attributes: true, attributeFilter: ["style"] });
  });
  const slider = page.getByRole("slider", { name: "Position" });
  await slider.focus();
  await page.keyboard.press("ArrowRight");
  await page.keyboard.press("ArrowRight");
  await expect(page.getByText(/^\d+ \/ 80$/)).toHaveText("3 / 80");
  await expect
    .poll(() =>
      videos.evaluateAll((els) =>
        els.map((el) => {
          const video = el as HTMLVideoElement;
          return Math.floor((video.currentTime / video.duration) * 80);
        }),
      ),
    )
    .toEqual([2, 2, 2, 2]);
  expect(
    await page.evaluate(() => (window as unknown as { shown: string[] }).shown),
  ).toEqual([]);

  // Zoomed in, the panes play, and the view stays where it is.
  await page.getByRole("button", { name: "Play" }).click();
  await expect
    .poll(() =>
      videos.evaluateAll((els) =>
        els.map((el) => (el as HTMLVideoElement).paused),
      ),
    )
    .toEqual([false, false, false, false]);
  await expect(page.getByText(/^\d+ \/ 80$/)).not.toHaveText("3 / 80");
  await expectRegions(page, [0.25, 0.25, 0.75, 0.75]);
});

/**
 * The zoom makes the transport wider, up to 743 px on one line. The column takes that
 * width where the work area has it, so the transport stays on one line under panes that
 * need less. Only a narrower work area wraps it, and the page still fits the window then.
 * The panes leave room for a second line only when there is one.
 */
test("keeps the transport on one line wherever the work area allows", async ({
  page,
}) => {
  test.slow();
  await page.setViewportSize({ width: 1100, height: 860 });
  await openPage(page);
  await generateSequence(page);
  const bar = page.getByRole("button", { name: "Play" }).locator("xpath=..");
  const layout = () =>
    bar.evaluate((el) => ({
      lines: el.getBoundingClientRect().height > 60 ? 2 : 1,
      overflow: Math.max(
        0,
        document.documentElement.scrollHeight -
          document.documentElement.clientHeight,
      ),
    }));

  // Every stream on screen, so that "Add pane" reads its longest, "All streams shown".
  await addPaneFor(page, "Occlusion");
  await expect(
    page.getByRole("button", { name: "All streams shown" }),
  ).toBeVisible();
  await expect.poll(layout).toEqual({ lines: 1, overflow: 0 });
  await page.setViewportSize({ width: 1024, height: 860 });
  await expect.poll(layout).toEqual({ lines: 2, overflow: 0 });

  // One pane, held to the window's height, is as large in a work area too narrow for the
  // longest line as in a wider one: "Add pane" leaves its line short enough for both.
  for (const name of ["Alpha", "Disparity", "Optical flow", "Occlusion"])
    await page.getByRole("button", { name: `Close ${name} pane` }).click();
  const pane = page.locator("[data-pane-view]");
  await expect(pane).toHaveCount(1);
  const sizeAt = async (width: number) => {
    await page.setViewportSize({ width, height: 760 });
    await expect.poll(layout).toEqual({ lines: 1, overflow: 0 });
    // Settled: the same height twice, a quarter of a second apart.
    let height = 0;
    await expect
      .poll(
        async () => {
          const was = height;
          height = (await pane.boundingBox())!.height;
          return height === was;
        },
        { intervals: [250] },
      )
      .toBe(true);
    return height;
  };
  expect(await sizeAt(1050)).toBe(await sizeAt(1200));
});
