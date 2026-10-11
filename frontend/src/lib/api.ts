/**
 * Client for the sequence API.
 *
 * Everything the interface knows about streams comes from what the server lists
 * rather than from constants here, so a stream that appears later — bokeh, added to a
 * sequence that had none — shows in the interface without a change on this side.
 */

const BASE = process.env.NEXT_PUBLIC_API_URL ?? "http://localhost:8000";

export type LibraryInfo = {
  id: string;
  /** The library's directory. Two libraries built by one estimator differ only here. */
  name: string;
  n_foregrounds: number;
  n_backgrounds: number;
  depth_estimator: string | null;
  asset_size: number | null;
};

export type StreamInfo = {
  url: string;
  /** Empty when the stream has one rendering and a colormap would do nothing. */
  colormaps: string[];
  /** Which of them `url` already renders, or null when the stream takes none. */
  default: string | null;
};

export type Sequence = {
  id: string;
  /** The id of the library it came from, which the picker may since have left. */
  library: string;
  cached: boolean;
  seed: number;
  frames: number;
  size: number;
  n_objects: number;
  /** One hex color per object, in alpha page order. The mask legend reads these
   *  rather than keeping a copy of the palette, so it cannot drift from the video. */
  object_colors: string[];
  streams: Record<string, StreamInfo>;
};

/** One step of a generation as the API reports it, and how far it has got. */
export type GenerationStep = {
  /** `sampling`, `frames`, `writing`, `flow` or `bokeh`; a later API may add more. */
  step: string;
  done: number;
  total: number;
};

export type SequenceParams = {
  /** A library id from `fetchLibraries`. */
  library: string;
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

/** A library's depth estimator, readable even when Stage A recorded none or the library
 *  is no longer mounted. */
export function estimatorName(library: LibraryInfo | null): string {
  return library?.depth_estimator ?? "unknown estimator";
}

/** A library's directory, when it says more than its estimator: a directory is often
 *  named after its estimator, and then naming both says nothing. */
export function libraryDirectory(library: LibraryInfo | null): string | null {
  return library && library.name !== estimatorName(library)
    ? library.name
    : null;
}

/** How the page names a library outside the picker, so two libraries from one estimator
 *  are told apart. */
export function libraryLabel(library: LibraryInfo | null): string {
  const directory = libraryDirectory(library);
  return directory
    ? `${estimatorName(library)}, ${directory}`
    : estimatorName(library);
}

/** Every mounted library, in the order the picker lists them. */
export async function fetchLibraries(
  signal?: AbortSignal,
): Promise<LibraryInfo[]> {
  let response: Response;
  try {
    response = await fetch(`${BASE}/libraries`, { signal });
  } catch (cause) {
    if (cause instanceof DOMException && cause.name === "AbortError")
      throw cause;
    unreachable(cause);
  }
  if (!response.ok) await readError(response);
  return response.json();
}

const NDJSON = "application/x-ndjson";

/**
 * Generate a sequence, hearing each step as the API takes it.
 *
 * The API streams one JSON object a line when asked for NDJSON: progress, then the
 * sequence or an error. One that answers plain JSON, as an older API does, is read as
 * before, with no progress on the way.
 */
export async function createSequence(
  params: SequenceParams,
  onStep?: (step: GenerationStep) => void,
  signal?: AbortSignal,
): Promise<Sequence> {
  let response: Response;
  try {
    response = await fetch(`${BASE}/sequences`, {
      method: "POST",
      headers: {
        "content-type": "application/json",
        accept: `${NDJSON}, application/json`,
      },
      body: JSON.stringify(params),
      signal,
    });
  } catch (cause) {
    if (cause instanceof DOMException && cause.name === "AbortError")
      throw cause;
    unreachable(cause);
  }
  if (!response.ok) await readError(response);
  if (
    !response.headers.get("content-type")?.startsWith(NDJSON) ||
    !response.body
  )
    return response.json();
  return readGeneration(response.body, onStep);
}

async function readGeneration(
  body: ReadableStream<Uint8Array>,
  onStep?: (step: GenerationStep) => void,
): Promise<Sequence> {
  const reader = body.getReader();
  const decoder = new TextDecoder();
  let buffered = "";
  for (;;) {
    let chunk: ReadableStreamReadResult<Uint8Array>;
    try {
      chunk = await reader.read();
    } catch (cause) {
      // The connection dropped mid-generation: the API stopped, or the network did.
      throw new ApiError(
        0,
        `Lost the API at ${BASE} while it generated. (${String(cause)})`,
      );
    }
    const { value, done } = chunk;
    buffered += decoder.decode(value, { stream: !done });
    const lines = buffered.split("\n");
    // The last piece may be a line still arriving.
    buffered = done ? "" : (lines.pop() ?? "");
    for (const line of lines) {
      if (!line.trim()) continue;
      const event = JSON.parse(line);
      if ("sequence" in event) return event.sequence;
      if ("error" in event)
        throw new ApiError(event.error.status, event.error.detail);
      onStep?.(event);
    }
    if (done) break;
  }
  throw new ApiError(
    0,
    "The API closed the stream before the sequence was ready.",
  );
}

/**
 * Absolute URL for a stream's video, in the colormap the server renders by default.
 *
 * The page shows disparity in Spectral only. The API also serves the gray rendering,
 * with `?colormap=grey`, for anyone asking for it by hand.
 */
export function streamUrl(stream: StreamInfo): string {
  return new URL(stream.url, BASE).toString();
}

export const apiBase = BASE;
