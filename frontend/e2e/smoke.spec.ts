import { execFileSync } from "node:child_process";
import { rmSync } from "node:fs";
import os from "node:os";
import path from "node:path";
import { expect, test } from "@playwright/test";

// Where playwright.config.ts points the API, so a test can write into a sequence as
// Stage C would.
const SEQUENCES = path.join(os.tmpdir(), "video-bokeh-e2e", "sequences");
const LIBRARIES = path.join(os.tmpdir(), "video-bokeh-e2e", "library");

/**
 * One path through the page, against the real API and a tiny real library: the library
 * loads, a sequence generates, and every stream the server lists reaches the browser as
 * video it can decode. This proves the wiring, not how the frames look.
 */
test("generates a sequence and decodes every stream", async ({ page }) => {
  await page.goto("/");
  await expect(page.getByText("2 objects, 2 backgrounds")).toBeVisible();

  await page.getByRole("button", { name: "Generate sequence" }).click();

  // all_in_focus, alpha and disparity: one pane per stream the sequence has.
  const videos = page.locator("video");
  await expect(videos).toHaveCount(3, { timeout: 60_000 });

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
  await expect(videos).toHaveCount(3, { timeout: 60_000 });

  const rates = () =>
    videos.evaluateAll((els) =>
      els.map((el) => (el as HTMLVideoElement).playbackRate),
    );

  await page.getByRole("combobox", { name: "Playback speed" }).click();
  await page.getByRole("option", { name: "0.5×" }).click();
  await expect.poll(rates).toEqual([0.5, 0.5, 0.5]);

  await page.getByRole("combobox", { name: "Stream" }).first().click();
  await page.getByRole("option", { name: "Disparity" }).click();
  await expect
    .poll(() =>
      videos.first().evaluate((el) => (el as HTMLVideoElement).currentSrc),
    )
    .toContain("disparity");
  await expect.poll(rates).toEqual([0.5, 0.5, 0.5]);
});

/**
 * The picker chooses the library a sequence comes from, and the sequence keeps naming its
 * own estimator after the picker moves on, so what is playing is never mislabelled.
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
  await expect(page.locator("video")).toHaveCount(3, { timeout: 60_000 });
  const shown = page.getByRole("definition").filter({ hasText: "depth-pro" });
  await expect(shown).toBeVisible();

  await picker.click();
  await page.getByRole("option", { name: "da2-small" }).click();
  await expect(header.getByText("da2-small")).toBeVisible();
  await expect(shown).toBeVisible();
});

/**
 * Bokeh is rendered after the sequence exists, by Stage C on a GPU. Its frames are faked
 * here; asking for the same sequence again lists the stream, and a pane opens for it.
 */
test("opens a pane for bokeh once the sequence has it", async ({ page }) => {
  await page.goto("/");
  await expect(page.getByText("2 objects, 2 backgrounds")).toBeVisible();
  // A seed of its own: the other tests share seed 0, and this one writes into its sequence.
  await page.getByRole("spinbutton", { name: "Seed" }).fill("7");
  const generate = page.getByRole("button", { name: "Generate sequence" });
  await generate.click();
  const videos = page.locator("video");
  await expect(videos).toHaveCount(3, { timeout: 60_000 });

  const id = await page
    .locator("dt", { hasText: /^sequence$/ })
    .locator("xpath=following-sibling::dd[1]")
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

  await generate.click();
  await expect(videos).toHaveCount(4, { timeout: 60_000 });
  await expect(
    page.getByRole("combobox", { name: "Stream" }).nth(3),
  ).toHaveText("Bokeh");
  await expect
    .poll(
      () => videos.nth(3).evaluate((el) => (el as HTMLVideoElement).readyState),
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
    await expect(page.locator("video")).toHaveCount(3, { timeout: 60_000 });
    await expect(
      page.getByRole("definition").filter({ hasText: "da2-large, extra" }),
    ).toBeVisible();
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
