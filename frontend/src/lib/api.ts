/**
 * Client for the scene API.
 *
 * Everything the interface knows about streams comes from the server's manifest
 * rather than from constants here, so a stream added later — bokeh, once the render
 * container exists — appears in the interface without a change on this side.
 */

const BASE = process.env.NEXT_PUBLIC_API_URL ?? "http://localhost:8000";

export type LibraryInfo = {
  id: string;
  n_foregrounds: number;
  n_backgrounds: number;
  depth_model: string | null;
  asset_size: number | null;
};

export type StreamInfo = {
  url: string;
  /** Empty when the stream is already RGB and a colormap would do nothing. */
  colormaps: string[];
};

export type Scene = {
  id: string;
  cached: boolean;
  seed: number;
  frames: number;
  size: number;
  n_objects: number;
  streams: Record<string, StreamInfo>;
};

export type SceneParams = {
  seed: number;
  frames: number;
  size: number;
  n_objects_min: number;
  n_objects_max: number;
};

/** An error the interface can show verbatim. The API puts its reason in `detail`. */
export class ApiError extends Error {
  readonly status: number;

  constructor(status: number, message: string) {
    super(message);
    this.name = "ApiError";
    this.status = status;
  }
}

async function readError(response: Response): Promise<never> {
  let detail = response.statusText;
  try {
    const body = await response.json();
    if (typeof body?.detail === "string") {
      detail = body.detail;
    } else if (Array.isArray(body?.detail) && body.detail[0]?.msg) {
      // FastAPI's validation errors arrive as a list of per-field objects.
      detail = body.detail.map((e: { msg: string }) => e.msg).join("; ");
    }
  } catch {
    // A response with no JSON body leaves the status text, which is better than nothing.
  }
  throw new ApiError(response.status, detail);
}

/** Turn a failed connection into the one thing the person can act on. */
function unreachable(cause: unknown): never {
  throw new ApiError(
    0,
    `Cannot reach the API at ${BASE}. Start it with "uv run uvicorn video_bokeh.api.main:app" ` +
      `from backend/, or set NEXT_PUBLIC_API_URL. (${String(cause)})`,
  );
}

export async function fetchLibrary(signal?: AbortSignal): Promise<LibraryInfo> {
  let response: Response;
  try {
    response = await fetch(`${BASE}/library`, { signal });
  } catch (cause) {
    if (cause instanceof DOMException && cause.name === "AbortError")
      throw cause;
    unreachable(cause);
  }
  if (!response.ok) await readError(response);
  return response.json();
}

export async function createScene(
  params: SceneParams,
  signal?: AbortSignal,
): Promise<Scene> {
  let response: Response;
  try {
    response = await fetch(`${BASE}/scenes`, {
      method: "POST",
      headers: { "content-type": "application/json" },
      body: JSON.stringify(params),
      signal,
    });
  } catch (cause) {
    if (cause instanceof DOMException && cause.name === "AbortError")
      throw cause;
    unreachable(cause);
  }
  if (!response.ok) await readError(response);
  return response.json();
}

/**
 * Absolute URL for a stream's video, with the colormap when the stream takes one.
 *
 * The server caches one file per colormap, so switching is a fetch the first time and
 * a file read after that.
 */
export function streamUrl(stream: StreamInfo, colormap?: string): string {
  const url = new URL(stream.url, BASE);
  if (colormap && stream.colormaps.includes(colormap)) {
    url.searchParams.set("colormap", colormap);
  }
  return url.toString();
}

export const apiBase = BASE;
