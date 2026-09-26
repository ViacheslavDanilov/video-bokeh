import { expect, test } from "@playwright/test";

/**
 * One path through the page, against the real API and a tiny real library: the library
 * loads, a scene generates, and every stream the server lists reaches the browser as
 * video it can decode. This proves the wiring, not how the frames look.
 */
test("generates a scene and decodes every stream", async ({ page }) => {
  await page.goto("/");
  await expect(page.getByText("2 objects, 2 backgrounds")).toBeVisible();

  await page.getByRole("button", { name: "Generate scene" }).click();

  // all_in_focus, alpha and disparity: one pane per stream the scene has.
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

  // The library holds two foregrounds, so the scene places both, and the mask legend
  // names each of them.
  await expect(page.getByText(/^Object \d+$/)).toHaveCount(2);
  // Scoped to <main>: Next.js adds an empty route announcer with the same role.
  await expect(page.getByRole("main").getByRole("alert")).toHaveCount(0);
});
