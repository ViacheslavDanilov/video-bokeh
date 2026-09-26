import os from "node:os";
import path from "node:path";
import { defineConfig } from "@playwright/test";

// Ports of their own, so a dev server or an API already running on 3000 and 8000 is
// never mistaken for the one this run started against the fixture library.
const WEB_PORT = 3765;
const API_PORT = 8765;
const DATA_ROOT = path.join(os.tmpdir(), "video-bokeh-e2e");
const LIBRARY = path.join(DATA_ROOT, "library");

export default defineConfig({
  testDir: "e2e",
  forbidOnly: !!process.env.CI,
  retries: 0,
  reporter: process.env.CI ? [["github"], ["list"]] : "list",
  use: {
    baseURL: `http://localhost:${WEB_PORT}`,
    trace: "retain-on-failure",
  },
  webServer: [
    {
      // A fresh tiny library every run: real files, gradient depth, no model.
      command: [
        `rm -rf "${DATA_ROOT}"`,
        `uv run --directory ../backend --extra api python tests/api/fixture_library.py "${LIBRARY}"`,
        `uv run --directory ../backend --extra api uvicorn video_bokeh.api.main:app --host 127.0.0.1 --port ${API_PORT}`,
      ].join(" && "),
      url: `http://127.0.0.1:${API_PORT}/health`,
      env: {
        VIDEO_BOKEH_DATA_ROOT: DATA_ROOT,
        VIDEO_BOKEH_LIBRARY: LIBRARY,
        CORS_ORIGINS: `http://localhost:${WEB_PORT},http://127.0.0.1:${WEB_PORT}`,
      },
      reuseExistingServer: false,
      timeout: 120_000,
    },
    {
      command: `pnpm dev --port ${WEB_PORT}`,
      url: `http://localhost:${WEB_PORT}`,
      env: { NEXT_PUBLIC_API_URL: `http://127.0.0.1:${API_PORT}` },
      reuseExistingServer: false,
      timeout: 120_000,
    },
  ],
});
