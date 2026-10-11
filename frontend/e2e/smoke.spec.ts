import { execFileSync } from "node:child_process";
import { rmSync } from "node:fs";
import os from "node:os";
import path from "node:path";
import { expect, type Page, test } from "@playwright/test";

// Where playwright.config.ts points the API, so a test can write into a sequence as
// Stage C would.
const SEQUENCES = path.join(os.tmpdir(), "video-bokeh-e2e", "sequences");
const LIBRARIES = path.join(os.tmpdir(), "video-bokeh-e2e", "library");

/** Write bokeh into the sequence on screen, as Stage C would: the API here renders none of
 *  its own, as without torch, so the stream is faked into the sequence on disk. */
async function fakeBokeh(page: Page) {
  const id = await page
    .getByRole("group", { name: "Sequence on screen" })
    .getByText(/^[0-9a-f]{16}$/)
    .innerText();
  execFileSync("uv", [
    "run",
    "--directory",
    "../backend",
    "--extra",
    "api",
    "python",
    "tests/api/fake_bokeh.py",
    path.join(SEQUENCES, id),
  ]);
}

/** The streams of the panes, left to right. */
function streamsInOrder(page: Page): Promise<string[]> {
  return page.getByRole("combobox", { name: "Stream" }).allInnerTexts();
}

/**
 * One path through the page, against the real API and a tiny real library: the library
 * loads, a sequence generates, and every stream the server lists reaches the browser as
 * video it can decode. This proves the wiring, not how the frames look.
 */
test("generates a sequence and decodes every stream", async ({ page }) => {
  await page.goto("/");
  await expect(page.getByText("2 objects, 2 backgrounds")).toBeVisible();

  await page.getByRole("button", { name: "Generate sequence" }).click();

  // all_in_focus, alpha, disparity and flow: one pane per stream the sequence has.
  const videos = page.locator("video");
  await expect(videos).toHaveCount(4, { timeout: 60_000 });
  await expect(
    page.getByRole("combobox", { name: "Stream" }).nth(3),
  ).toHaveText("Optical flow");

  // readyState 2 is HAVE_CURRENT_DATA: the file arrived and a frame was decoded.
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
  await page.goto("/");
  await expect(page.getByText("2 objects, 2 backgrounds")).toBeVisible();
  await page.getByRole("button", { name: "Generate sequence" }).click();
  const videos = page.locator("video");
  await expect(videos).toHaveCount(4, { timeout: 60_000 });

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
  await page.goto("/");
  const header = page.getByRole("banner");
  await expect(header.getByText("da2-small")).toBeVisible();

  const picker = page.getByRole("combobox", { name: "Depth estimator" });
  await picker.click();
  await expect(page.getByRole("option")).toHaveText(["da2-small", "depth-pro"]);
  await page.getByRole("option", { name: "depth-pro" }).click();
  await expect(header.getByText("depth-pro")).toBeVisible();

  await page.getByRole("button", { name: "Generate sequence" }).click();
  await expect(page.locator("video")).toHaveCount(4, { timeout: 60_000 });
  const shown = page.getByRole("group", { name: "Sequence on screen" });
  await expect(shown).toContainText("depth-pro");

  await picker.click();
  await page.getByRole("option", { name: "da2-small" }).click();
  await expect(header.getByText("da2-small")).toBeVisible();
  await expect(shown).toContainText("depth-pro");
});

/**
 * The API here renders no bokeh of its own, as without torch, so the stream is written
 * after the sequence exists, as Stage C writes it. Its frames are faked here; asking for
 * the same sequence again lists the stream, and a pane opens for it.
 */
test("opens a pane for bokeh once the sequence has it", async ({ page }) => {
  await page.goto("/");
  await expect(page.getByText("2 objects, 2 backgrounds")).toBeVisible();
  // A seed of its own: the other tests share seed 0, and this one writes into its sequence.
  await page.getByRole("spinbutton", { name: "Seed" }).fill("7");
  const generate = page.getByRole("button", { name: "Generate sequence" });
  await generate.click();
  const videos = page.locator("video");
  await expect(videos).toHaveCount(4, { timeout: 60_000 });

  await fakeBokeh(page);

  await generate.click();
  // After the panes already open, flow among them.
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
});

/**
 * A library built while the page is open shows in the picker once the page has focus
 * again, and a sequence from it is named by its directory as well as its estimator.
 */
test("lists a library built while the page is open", async ({ page }) => {
  await page.goto("/");
  await expect(page.getByText("2 objects, 2 backgrounds")).toBeVisible();

  // Removed again, because the other tests expect exactly two libraries.
  const extra = path.join(LIBRARIES, "extra");
  try {
    execFileSync("uv", [
      "run",
      "--directory",
      "../backend",
      "--extra",
      "api",
      "python",
      "tests/api/fixture_library.py",
      extra,
      "da2-large",
    ]);
    await page.evaluate(() => window.dispatchEvent(new Event("focus")));
    await page.getByRole("combobox", { name: "Depth estimator" }).click();
    await expect(page.getByRole("option")).toHaveCount(3);
    await page.getByRole("option", { name: /extra/ }).click();
    await page.getByRole("spinbutton", { name: "Seed" }).fill("11");
    await page.getByRole("button", { name: "Generate sequence" }).click();
    await expect(page.locator("video")).toHaveCount(4, { timeout: 60_000 });
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
  await page.goto("/");
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
  await page.goto("/");
  await expect(page.getByText("2 objects, 2 backgrounds")).toBeVisible();

  const other = await context.newPage();
  await other.goto("/");
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
  await page.goto("/");
  await expect(page.getByText("2 objects, 2 backgrounds")).toBeVisible();
  // A seed of its own: this test writes into its sequence.
  await page.getByRole("spinbutton", { name: "Seed" }).fill("41");
  const generate = page.getByRole("button", { name: "Generate sequence" });
  await generate.click();
  const videos = page.locator("video");
  await expect(videos).toHaveCount(4, { timeout: 60_000 });

  // A fifth stream, since a pane is added only for a stream not on screen.
  await fakeBokeh(page);
  await generate.click();
  await expect(videos).toHaveCount(5, { timeout: 60_000 });

  const rows = async () => {
    const tops = await videos.evaluateAll((els) =>
      els.map((el) => Math.round(el.getBoundingClientRect().top)),
    );
    return [...new Set(tops)].map(
      (top) => tops.filter((t) => t === top).length,
    );
  };
  await expect.poll(rows).toEqual([3, 2]);

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
  await page.goto("/");
  await expect(page.getByText("2 objects, 2 backgrounds")).toBeVisible();
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
  await expect(page.getByText(/Bokeh comes with each sequence/)).toHaveCount(0);

  await generate.click();
  await expect(page.getByText("cached", { exact: true })).toBeVisible();
});

/**
 * The next generation shows its progress where the caption above the panes was, at its
 * height, so the sequence on screen does not move while the next one is made.
 */
test("keeps the panes in place while the next sequence generates", async ({
  page,
}) => {
  // Two generations, about 14 s each in CI, leave no room in the default 30 s.
  test.slow();
  await page.goto("/");
  await expect(page.getByText("2 objects, 2 backgrounds")).toBeVisible();
  const seed = page.getByRole("spinbutton", { name: "Seed" });
  const generate = page.getByRole("button", { name: "Generate sequence" });
  await seed.fill("31");
  await generate.click();
  const videos = page.locator("video");
  await expect(videos).toHaveCount(4, { timeout: 60_000 });
  const top = () =>
    videos.first().evaluate((el) => Math.round(el.getBoundingClientRect().top));
  const before = await top();

  await seed.fill("32");
  await generate.click();
  const progress = page.getByRole("status", { name: "Generation progress" });
  await expect(progress).toBeVisible();
  expect(await top()).toBe(before);
  await expect(progress).toBeHidden({ timeout: 60_000 });
});

/** What the progress bar did: every value it took, however briefly; where on the page it sat
 *  at each, over the empty card or the panes, and how far from the left edge; and how long it
 *  stayed full where it filled. */
type BarSeen = {
  values: number[];
  lefts: number[];
  places: string[];
  fullFor: number;
};

/** Start recording the progress bar, for `takeBar` to read. */
async function watchBar(page: Page) {
  await page.evaluate(() => {
    const fresh = () => ({
      values: [] as number[],
      lefts: [] as number[],
      places: [] as string[],
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
      if (
        element == null ||
        value == null ||
        Number(value) === bar.values.at(-1)
      )
        return;
      bar.values.push(Number(value));
      // From the page's edge rather than the line's: on the empty screen the line is
      // centered, and a line that grew after the bar would move the bar but not its offset.
      bar.lefts.push(element.getBoundingClientRect().left);
      bar.places.push(place);
      if (Number(value) === 100) {
        bar.fullAt = performance.now();
        bar.fullPlace = place;
      }
    }).observe(document.body, {
      subtree: true,
      childList: true,
      attributes: true,
      attributeFilter: ["aria-valuenow"],
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
  expect(new Set(seen.lefts).size).toBe(1);
  // Where on its own it would last a frame or none.
  expect(seen.fullFor).toBeGreaterThanOrEqual(400);
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
  await page.goto("/");
  await expect(page.getByText("2 objects, 2 backgrounds")).toBeVisible();
  await watchBar(page);
  const seed = page.getByRole("spinbutton", { name: "Seed" });
  const generate = page.getByRole("button", { name: "Generate sequence" });
  const progress = page.getByRole("status", { name: "Generation progress" });

  await seed.fill("61");
  await generate.click();
  await expect(progress).toBeVisible();
  await expect(progress).toBeHidden({ timeout: 60_000 });
  expectOneSteadyBar(await takeBar(page), "empty");

  await seed.fill("62");
  await generate.click();
  await expect(progress).toBeVisible();
  await expect(progress).toBeHidden({ timeout: 60_000 });
  expectOneSteadyBar(await takeBar(page), "panes");
});

/** A pane goes where it is dropped: dragged by its grip onto another, it takes that place. */
test("moves a pane by dragging its grip onto another", async ({ page }) => {
  await page.goto("/");
  await expect(page.getByText("2 objects, 2 backgrounds")).toBeVisible();
  await page.getByRole("button", { name: "Generate sequence" }).click();
  await expect(page.locator("video")).toHaveCount(4, { timeout: 60_000 });
  expect(await streamsInOrder(page)).toEqual([
    "All in focus",
    "Alpha",
    "Disparity",
    "Optical flow",
  ]);

  await page
    .getByRole("button", { name: "Move Optical flow pane" })
    .dragTo(page.getByRole("figure").first());
  await expect
    .poll(() => streamsInOrder(page))
    .toEqual(["Optical flow", "All in focus", "Alpha", "Disparity"]);

  // And rightwards: onto the last pane, it takes the last place.
  await page
    .getByRole("button", { name: "Move Optical flow pane" })
    .dragTo(page.getByRole("figure").last());
  await expect
    .poll(() => streamsInOrder(page))
    .toEqual(["All in focus", "Alpha", "Disparity", "Optical flow"]);
});

/**
 * The grip moves its pane with the arrow keys too, keeps the focus for the next press, and
 * the panes play on in step: a reorder moves the video elements, it does not reload them.
 */
test("moves a pane with the arrow keys while the panes play", async ({
  page,
}) => {
  await page.goto("/");
  await expect(page.getByText("2 objects, 2 backgrounds")).toBeVisible();
  await page.getByRole("button", { name: "Generate sequence" }).click();
  const videos = page.locator("video");
  await expect(videos).toHaveCount(4, { timeout: 60_000 });
  // Every pane decoded before Play. The API encodes a stream the first time it is asked
  // for, so run alone, before any other test has asked, a pane would still sit at the
  // start when the times are read.
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
  await page.getByRole("button", { name: "Play" }).click();

  const grip = page.getByRole("button", { name: "Move All in focus pane" });
  await grip.focus();
  await page.keyboard.press("ArrowRight");
  await page.keyboard.press("ArrowRight");
  await expect
    .poll(() => streamsInOrder(page))
    .toEqual(["Alpha", "Disparity", "All in focus", "Optical flow"]);
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
  await page.goto("/");
  await expect(page.getByText("2 objects, 2 backgrounds")).toBeVisible();
  await page.getByRole("button", { name: "Generate sequence" }).click();
  const videos = page.locator("video");
  await expect(videos).toHaveCount(4, { timeout: 60_000 });
  await expect(
    page.getByRole("button", { name: "All streams shown" }),
  ).toBeDisabled();

  await page.getByRole("button", { name: "Close Alpha pane" }).click();
  await page.getByRole("button", { name: "Add pane" }).click();
  await expect(videos).toHaveCount(4);
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
  await page.goto("/");
  await expect(page.getByText("2 objects, 2 backgrounds")).toBeVisible();
  const seed = page.getByRole("spinbutton", { name: "Seed" });
  const generate = page.getByRole("button", { name: "Generate sequence" });
  // A seed of its own: this test writes into its sequence.
  await seed.fill("51");
  await generate.click();
  const videos = page.locator("video");
  await expect(videos).toHaveCount(4, { timeout: 60_000 });
  await fakeBokeh(page);
  await generate.click();
  await expect(videos).toHaveCount(5, { timeout: 60_000 });

  await page.getByRole("button", { name: "Close All in focus pane" }).click();
  await expect(page.getByRole("button", { name: "Add pane" })).toBeEnabled();

  // No bokeh here, so the bokeh pane falls back to all in focus.
  await seed.fill("52");
  await generate.click();
  await expect(page.getByText("seed 52")).toBeVisible({ timeout: 60_000 });
  await expect(
    page.getByRole("button", { name: "All streams shown" }),
  ).toBeDisabled();
});
