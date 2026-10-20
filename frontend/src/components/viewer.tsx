"use client";

import {
  useCallback,
  useEffect,
  useLayoutEffect,
  useRef,
  useState,
} from "react";
import { Check, Copy, GripVertical, X } from "lucide-react";
import type { GenerationStep, Sequence } from "@/lib/api";
import { streamUrl } from "@/lib/api";
import { decodeFrames, frameTime } from "@/lib/frames";
import { Button } from "@/components/ui/button";
import { cn } from "@/lib/utils";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";
import { Slider } from "@/components/ui/slider";
import { colormapName, DepthLegend } from "./depth-legend";
import { FlowLegend } from "./flow-legend";
import { GenerationProgress } from "./generation-progress";
import { ObjectLegend } from "./object-legend";
import { OcclusionLegend } from "./occlusion-legend";
import { SpectralScale } from "./spectral-scale";

// A ceiling. "Add pane" adds only a stream not on screen, but a pane switched to a stream
// another already shows makes room for one more, which would otherwise have no end. Past
// what fits in a row the panes wrap rather than shrink; see `gridColumns`.
const MAX_PANES = 6;

// What a dragged pane carries, so that nothing else dropped on the grid, such as a file,
// moves a pane.
const PANE_DRAG = "application/x-video-bokeh-pane";

// How far an arrow key on a pane's grip moves the pane.
const ARROW_MOVES: Record<string, number> = { ArrowLeft: -1, ArrowRight: 1 };

// Between panes. The grid's style sets its gap from this, so the two cannot disagree.
const PANE_GAP_PX = 16;
// What a pane needs besides its square: the stream picker above, a legend of up to two
// lines below.
const PANE_CHROME_PX = 84;
// Kept free under the grid for the transport: its 36 px controls, its py-3 and the gap-5
// above it.
const TRANSPORT_PX = 88;
// Fitting every pane on the screen is worth it down to this size. Smaller, as on a phone,
// the panes are better big and scrolled through.
const MIN_FIT_PX = 200;
// When the panes scroll, narrower than this is too small to judge a frame on.
const MIN_PANE_PX = 280;

// Independent <video> elements drift apart as they play -- measured at about 1.75
// frames after a second and a half. A comparison is worthless if the panes are not on
// the same frame, so followers are snapped back whenever they slip past one frame.
// The tolerance matters: seeking on every tick would stutter.
const SYNC_TOLERANCE_SECONDS = 1 / 24;

// The steps a video player offers. Slower is the useful direction here: an 80-frame clip is
// over in a few seconds, and the depth ordering changes inside it.
const SPEEDS = [0.25, 0.5, 1, 2];

// The position slider's step, in frames: fine enough that a drag moves the thumb with the
// pointer, between frames, while the panes show the frame nearest to it.
const SCRUB_STEP = 0.01;

// The keys that move the position by whole frames, and how many. The slider's own would
// move it by its step, a hundredth of a frame.
const FRAME_KEYS: Record<string, number> = {
  ArrowLeft: -1,
  ArrowDown: -1,
  ArrowRight: 1,
  ArrowUp: 1,
  PageDown: -10,
  PageUp: 10,
};

/** A pane's frames decoded into memory, and the video they came from. */
type Decoded = { src: string; frames: ImageBitmap[]; abort: AbortController };

function dispose(decoded: Decoded) {
  decoded.abort.abort();
  decoded.frames.splice(0).forEach((frame) => frame.close());
}

type Pane = {
  key: number;
  stream: string;
  /** The colormap picked in this pane, for a stream that takes one. Unset, the server's
   *  default. */
  colormap?: string;
  /** Whether this pane draws its stream over the frames, for a stream that can be. */
  overlay?: boolean;
  /** Whether this pane shows its stream the other way, for a stream that has it. */
  backward?: boolean;
};

// Presentation only: an unknown name still reads sensibly, so a stream the server adds
// later needs no change here to appear.
const LABELS: Record<string, string> = {
  all_in_focus: "All in focus",
  disparity: "Disparity",
  alpha: "Alpha",
  bokeh: "Bokeh",
  flow: "Optical flow",
  occlusion: "Occlusion",
};

function label(name: string): string {
  return LABELS[name] ?? name.replaceAll("_", " ");
}

/** The room the panes have: the grid's width, and the window's height below its top. */
type Space = { width: number; height: number };

/**
 * The grid's columns. Every pane on the screen at once, at the largest square that allows,
 * since a comparison needs them all in view. Where that square would be too small, panes at
 * least MIN_PANE_PX wide, in rows the page scrolls through.
 *
 * Either way the rows come out even: five panes in two rows are three and two, not four
 * and one. The search gets that for free, since fewer columns over the same rows are never
 * smaller and it keeps the first of equals.
 */
function gridColumns(panes: number, space: Space): string {
  if (panes === 0 || space.width === 0) {
    // Not measured yet: one row, as before the grid could measure.
    return `repeat(${Math.max(panes, 1)}, minmax(0, 1fr))`;
  }
  let best = { columns: panes, size: 0 };
  for (let columns = 1; columns <= panes; columns++) {
    const rows = Math.ceil(panes / columns);
    const size = Math.min(
      (space.width - (columns - 1) * PANE_GAP_PX) / columns,
      (space.height - (rows - 1) * PANE_GAP_PX) / rows - PANE_CHROME_PX,
    );
    if (size > best.size) best = { columns, size };
  }
  if (best.size >= MIN_FIT_PX) {
    return `repeat(${best.columns}, ${Math.floor(best.size)}px)`;
  }
  const maxColumns = Math.floor(
    (space.width + PANE_GAP_PX) / (MIN_PANE_PX + PANE_GAP_PX),
  );
  const rows = Math.ceil(panes / Math.max(1, Math.min(panes, maxColumns)));
  return `repeat(${Math.ceil(panes / rows)}, minmax(0, 1fr))`;
}

/** A slot and its line stay on the nearest row, even in a gap or past a row's end. */
function paneSlot(grid: HTMLDivElement, x: number, y: number) {
  const rects = Array.from(
    grid.querySelectorAll(":scope > figure"),
    (el, index) => ({
      rect: el.getBoundingClientRect(),
      index,
    }),
  );
  const nearestRow = rects.reduce((a, b) =>
    Math.max(b.rect.top - y, y - b.rect.bottom, 0) <
    Math.max(a.rect.top - y, y - a.rect.bottom, 0)
      ? b
      : a,
  );
  const row = rects.filter(({ rect }) => rect.top === nearestRow.rect.top);
  const nearest = row.reduce((a, b) =>
    Math.max(b.rect.left - x, x - b.rect.right, 0) <
    Math.max(a.rect.left - x, x - a.rect.right, 0)
      ? b
      : a,
  );
  const after = x >= nearest.rect.left + nearest.rect.width / 2;
  const slot = nearest.index + (after ? 1 : 0);
  const beforePane = row.find(({ index }) => index === slot - 1);
  const afterPane = row.find(({ index }) => index === slot);
  const center =
    beforePane && afterPane
      ? (beforePane.rect.right + afterPane.rect.left) / 2
      : afterPane
        ? afterPane.rect.left - PANE_GAP_PX / 2
        : beforePane!.rect.right + PANE_GAP_PX / 2;
  const container = grid.getBoundingClientRect();
  return {
    slot,
    left: center - container.left,
    top: nearest.rect.top - container.top,
    height: nearest.rect.height,
  };
}

export function Viewer({
  sequence,
  library,
  generating,
  steps,
  startedAt,
  finishedAt,
}: {
  sequence: Sequence | null;
  /** The library this sequence came from, as the page names libraries. */
  library: string;
  generating: boolean;
  /** The steps of the generation under way, each at its latest count, and when it began. */
  steps: GenerationStep[];
  startedAt: number;
  finishedAt: number | null;
}) {
  const names = sequence ? Object.keys(sequence.streams) : [];
  const [panes, setPanes] = useState<Pane[]>([]);
  const [playing, setPlaying] = useState(false);
  const [time, setTime] = useState(0);
  const [duration, setDuration] = useState(0);
  // A viewer setting rather than part of the sequence, so a new sequence keeps it.
  const [speed, setSpeed] = useState(1);

  const videos = useRef(new Map<number, HTMLVideoElement>());
  // Scrubbing draws each pane's frames from memory onto a canvas over its video, since a
  // seek per step lags behind the pointer. `scrub` is the slider's position, between
  // frames, while it is dragged; `covering`, the panes whose canvas is on top, which stay
  // so after the drag until their video has caught up with the frame.
  const decoded = useRef(new Map<number, Decoded>());
  const canvases = useRef(new Map<number, HTMLCanvasElement>());
  const [scrub, setScrub] = useState<number | null>(null);
  const scrubRef = useRef<number | null>(null);
  const [covering, setCovering] = useState<ReadonlySet<number>>(new Set());
  // The pane being dragged: the ref for the drag handlers, the state to dim it for the whole
  // drag, and where it would land, shown as a line while the pointer is over the grid.
  const dragged = useRef<number | null>(null);
  const [draggedKey, setDraggedKey] = useState<number | null>(null);
  const [dropSlot, setDropSlot] = useState<ReturnType<typeof paneSlot> | null>(
    null,
  );
  // Read inside onLoadedMetadata, which fires long after the render that set the
  // src, so state captured by closure would be stale.
  const timeRef = useRef(0);
  const playingRef = useRef(false);
  // Which sequence the refs above describe. Compared inside the load handler rather than
  // reset during render, because writing a ref while rendering is not allowed.
  const restoredSequence = useRef<string | null>(null);
  // Read when an element attaches, which happens on React's schedule rather than inside
  // the render that chose the speed.
  const speedRef = useRef(1);
  // The room the pane grid has, which the parameters folding away, the window, or an alert
  // appearing above the grid changes.
  const [space, setSpace] = useState<Space>({ width: 0, height: 0 });
  // Which pane has its current video from the API, or failed to get it. The API encodes a
  // video the first time it is asked for, up to two seconds, and a pane says so meanwhile
  // rather than sit blank. Its metadata is the sign, not its first frame: with
  // `preload="metadata"`, WebKit loads no frame until the video plays.
  const [loaded, setLoaded] = useState<ReadonlyMap<string, "ready" | "failed">>(
    new Map(),
  );
  const [copied, setCopied] = useState(false);
  const observeGrid = useCallback((el: HTMLDivElement) => {
    const measure = () => {
      const top = el.getBoundingClientRect().top + window.scrollY;
      const width = el.clientWidth;
      const height = window.innerHeight - top - TRANSPORT_PX;
      setSpace((was) =>
        was.width === width && was.height === height ? was : { width, height },
      );
    };
    const observer = new ResizeObserver(measure);
    observer.observe(el);
    // Anything above the grid that grows or shrinks moves its top without resizing it, and
    // changes the page's height.
    observer.observe(document.body);
    window.addEventListener("resize", measure);
    return () => {
      observer.disconnect();
      window.removeEventListener("resize", measure);
    };
  }, []);

  // A new sequence rewinds the transport. Adjusting state during render rather than in an
  // effect is React's own recommendation for state that has to follow a prop: an effect
  // would paint the old position once before correcting it.
  const [shownSequence, setShownSequence] = useState(sequence?.id ?? null);
  if ((sequence?.id ?? null) !== shownSequence) {
    setShownSequence(sequence?.id ?? null);
    setPlaying(false);
    setTime(0);
    setDuration(0);
    // The last sequence's frames, which a canvas waiting on a video now gone would keep.
    setCovering(new Set());
    // A drag under way when it arrives ends with it; one that goes on starts afresh.
    setScrub(null);
  }
  // The refs follow in the commit, before any event can read them: a drag let go before
  // the new videos load would otherwise play them behind a button that reads Play.
  const sequenceId = sequence?.id ?? null;
  useLayoutEffect(() => {
    playingRef.current = false;
    scrubRef.current = null;
  }, [sequenceId]);

  // While playing, the time comes from the leading video every animation frame rather
  // than from its timeupdate events, about four a second, so the thumb glides instead of
  // jumping several frames at a time. Nothing runs while paused or while the page is
  // hidden, nor during a drag, which places the thumb itself.
  useEffect(() => {
    if (!playing) return;
    let frame = 0;
    const follow = () => {
      const lead = videos.current.values().next().value;
      // A lead loading a new stream reads 0 until it is put back where the transport is.
      if (
        lead &&
        lead.readyState >= HTMLMediaElement.HAVE_METADATA &&
        scrubRef.current === null
      )
        setTime(lead.currentTime);
      frame = requestAnimationFrame(follow);
    };
    const resume = () => {
      cancelAnimationFrame(frame);
      if (!document.hidden) frame = requestAnimationFrame(follow);
    };
    resume();
    document.addEventListener("visibilitychange", resume);
    return () => {
      cancelAnimationFrame(frame);
      document.removeEventListener("visibilitychange", resume);
    };
  }, [playing]);

  // A stream the server did not list for the last sequence gets a pane of its own while
  // there is room: bokeh appears this way, when a sequence that had none is asked for again
  // with it. Only a stream new since the last sequence, so a closed pane stays
  // closed while the streams do not change, and only one the server says opens a pane: the
  // rest wait in the stream picker.
  const [knownStreams, setKnownStreams] = useState<string[]>([]);
  if (names.join(",") !== knownStreams.join(",")) {
    setKnownStreams(names);
    const appeared = names.filter(
      (n) =>
        sequence?.streams[n].opens_pane !== false &&
        !knownStreams.includes(n) &&
        !panes.some((p) => p.stream === n),
    );
    const room = MAX_PANES - panes.length;
    if (appeared.length > 0 && room > 0) {
      const nextKey = Math.max(0, ...panes.map((p) => p.key)) + 1;
      setPanes([
        ...panes,
        ...appeared
          .slice(0, room)
          .map((stream, i) => ({ key: nextKey + i, stream })),
      ]);
    }
  }

  // A closed pane's frames are let go, and all of them when the viewer goes.
  const paneKeys = panes.map((p) => p.key).join(" ");
  useEffect(() => {
    const open = new Set(paneKeys.split(" ").map(Number));
    const all = decoded.current;
    all.forEach((frames, key) => {
      if (open.has(key)) return;
      dispose(frames);
      all.delete(key);
    });
  }, [paneKeys]);
  useEffect(() => {
    const all = decoded.current;
    return () => {
      all.forEach(dispose);
      all.clear();
    };
  }, []);

  // A pane naming a stream this sequence does not have falls back to the first one. Derived
  // rather than stored, so no state has to be repaired when the streams listed change.
  const streamFor = (pane: Pane) =>
    sequence && pane.stream in sequence.streams
      ? pane.stream
      : (names[0] ?? pane.stream);

  // One transport drives every pane, the way vpv drives its panes: a comparison is only
  // worth anything if the frames line up.
  // Side effects live outside the updater: React may call an updater twice under
  // StrictMode, and pausing or playing twice is not what it is for.
  function togglePlay() {
    const next = !playingRef.current;
    playingRef.current = next;
    setPlaying(next);
    if (!next) {
      videos.current.forEach((v) => v.pause());
      return;
    }
    const lead = videos.current.values().next().value;
    const at = lead ? lead.currentTime : 0;
    timeRef.current = at;
    videos.current.forEach((v) => {
      v.currentTime = at;
      void v.play();
    });
  }

  // Loading a new src resets an element's rate to its default rate, so both are set: a
  // stream switch then keeps the speed without any handler of its own.
  function applySpeed(v: HTMLVideoElement) {
    v.defaultPlaybackRate = speedRef.current;
    v.playbackRate = speedRef.current;
  }

  function changeSpeed(to: number) {
    speedRef.current = to;
    setSpeed(to);
    videos.current.forEach(applySpeed);
  }

  function registerVideo(key: number, el: HTMLVideoElement | null) {
    if (el) {
      // A pane added later, or remounted for a new sequence, starts at the chosen speed.
      applySpeed(el);
      videos.current.set(key, el);
    } else {
      videos.current.delete(key);
    }
  }

  const showingProgress = steps.length > 0;

  if (!sequence) {
    return (
      <div className="border-border bg-card flex flex-1 flex-col items-center justify-center gap-5 rounded-lg border p-12">
        <div className="w-64">
          <SpectralScale sweeping={generating} />
        </div>
        {showingProgress ? (
          <div className="text-muted-foreground text-sm">
            <GenerationProgress
              steps={steps}
              startedAt={startedAt}
              finishedAt={finishedAt}
            />
          </div>
        ) : (
          <p className="text-muted-foreground max-w-xs text-center text-sm">
            {generating
              ? "Generating the sequence."
              : "No sequence yet. Set the parameters and generate one."}
          </p>
        )}
      </div>
    );
  }

  // Takes the pane out and puts it back at `to`, so the panes between shift by one. Each
  // keeps its key, so React moves its video element rather than loading it again.
  const movePane = (key: number, to: number) =>
    setPanes((current) => {
      const from = current.findIndex((p) => p.key === key);
      if (from < 0 || to < 0 || to >= current.length || from === to)
        return current;
      const next = [...current];
      next.splice(to, 0, ...next.splice(from, 1));
      return next;
    });

  // A stream no pane shows. Once every stream is on screen there is nothing to add; a repeat
  // comes from switching a pane's stream instead.
  // By what each pane shows, which for a stream this sequence lacks is the first one.
  const unshown = names.find((n) => !panes.some((p) => streamFor(p) === n));
  const addPane = () => {
    if (unshown === undefined) return;
    setPanes((current) => [
      ...current,
      {
        key: Math.max(0, ...current.map((p) => p.key)) + 1,
        stream: unshown,
      },
    ]);
  };

  // The transport counts frames, not seconds. A slider stepping by duration/frames
  // lands on fractions the browser then rounds back, so arrow keys stalled after two
  // presses -- and a screen reader read out seconds when the interesting number is the
  // frame. The keys move it by whole frames, and its text names the frame shown.
  // The frame on screen is the one whose time span holds the current time, so the counter
  // rounds down, and a seek goes to the middle of a frame, which no rounding moves out.
  const lastFrame = Math.max(sequence.frames - 1, 0);
  const nearest = (position: number) =>
    Math.min(Math.max(Math.round(position), 0), lastFrame);
  const frameIndex =
    scrub !== null
      ? nearest(scrub)
      : duration
        ? Math.min(Math.floor((time / duration) * sequence.frames), lastFrame)
        : 0;
  // Playing, the thumb sits between frames, where the time is: half a frame back, so that
  // the frame nearest it is the one shown, as while dragging. Paused, it rests on that frame.
  const thumbAt =
    scrub ??
    (playing && duration
      ? Math.min(
          Math.max((time / duration) * sequence.frames - 0.5, 0),
          lastFrame,
        )
      : frameIndex);
  const seekToFrame = (frame: number) => {
    const to = duration ? frameTime(frame, sequence.frames, duration) : 0;
    timeRef.current = to;
    setTime(to);
    videos.current.forEach((v) => {
      v.currentTime = to;
    });
  };

  // A pane's frames, decoded once its video is there, at the size its canvas is shown.
  // Decoded again only for another video: a new sequence, stream, colormap or direction.
  const decodeFor = (key: number, src: string) => {
    const was = decoded.current.get(key);
    const canvas = canvases.current.get(key);
    if (was?.src === src || !canvas) return;
    if (was) dispose(was);
    const now: Decoded = { src, frames: [], abort: new AbortController() };
    decoded.current.set(key, now);
    canvas.dataset.decoded = "0";
    // A frame that cannot be decoded leaves the rest to seeking, as before.
    decodeFrames(
      src,
      sequence.frames,
      Math.ceil(canvas.clientWidth),
      now.frames,
      now.abort.signal,
      () => {
        canvas.dataset.decoded = String(now.frames.length);
      },
    ).catch(() => {});
  };

  // Every pane shows the frame nearest the thumb at once: drawn from memory where it is
  // decoded, and where it is not yet, sought as before.
  const scrubTo = (position: number) => {
    // Playing panes hold still under the drag, so no sync seek lands after the last one,
    // and play on from the frame let go at.
    if (scrubRef.current === null && playingRef.current)
      videos.current.forEach((v) => v.pause());
    scrubRef.current = position;
    setScrub(position);
    const frame = nearest(position);
    const drawn = new Set<number>();
    videos.current.forEach((video, key) => {
      const canvas = canvases.current.get(key);
      // Only frames of the video the pane has now: a switched stream keeps the last one's
      // until its own video loads.
      const frames = decoded.current.get(key);
      const bitmap =
        frames?.src === video.getAttribute("src")
          ? frames.frames[frame]
          : undefined;
      if (canvas && bitmap) {
        if (canvas.width !== bitmap.width) canvas.width = bitmap.width;
        if (canvas.height !== bitmap.height) canvas.height = bitmap.height;
        canvas.getContext("2d")?.drawImage(bitmap, 0, 0);
        canvas.dataset.frame = String(frame);
        drawn.add(key);
      } else if (duration) {
        video.currentTime = frameTime(frame, sequence.frames, duration);
      }
    });
    setCovering(drawn);
  };

  // Let go, the thumb rests on the frame shown and the videos go there. Each canvas comes
  // off once its video has the frame, so no pane flashes back to where it was.
  const endScrub = () => {
    const position = scrubRef.current;
    if (position === null) return;
    scrubRef.current = null;
    setScrub(null);
    seekToFrame(nearest(position));
    videos.current.forEach((video, key) => {
      if (playingRef.current) void video.play();
      // A video with nothing loaded yet does not seek, and covers nothing.
      if (video.readyState === HTMLMediaElement.HAVE_NOTHING) return;
      video.addEventListener(
        "seeked",
        () => {
          if (scrubRef.current !== null) return;
          setCovering((was) => {
            const next = new Set(was);
            next.delete(key);
            return next;
          });
        },
        { once: true },
      );
    });
  };

  const copyId = () => {
    // Only in a secure context, which the page on localhost is; elsewhere the id is
    // there to select by hand.
    navigator.clipboard?.writeText(sequence.id).then(
      () => {
        setCopied(true);
        setTimeout(() => setCopied(false), 1500);
      },
      () => {},
    );
  };

  return (
    <div className="flex flex-1 flex-col gap-5">
      {/* What is on screen, and while the next one generates, how that is going, over it.
          The caption keeps its place, hidden, so the progress takes exactly its height and
          the panes below do not move. The library is the sequence's own, which the picker
          may have left since. */}
      <div className="text-muted-foreground relative -mb-1 text-xs">
        {showingProgress && (
          <div className="absolute inset-0 flex items-center">
            <GenerationProgress
              steps={steps}
              startedAt={startedAt}
              finishedAt={finishedAt}
            />
          </div>
        )}
        <div
          role="group"
          aria-label="Sequence on screen"
          className={cn(
            "flex flex-wrap items-center gap-x-4 gap-y-1",
            showingProgress && "invisible",
          )}
        >
          <span className="text-foreground">{library}</span>
          <span>
            seed{" "}
            <span className="text-foreground font-mono">{sequence.seed}</span>
          </span>
          <span>{sequence.n_objects} objects</span>
          <span>{sequence.frames} frames</span>
          <span>
            {sequence.size} &times; {sequence.size}
          </span>
          {sequence.cached && (
            <span
              className="border-border rounded border px-1.5"
              title="Generated before from this library with these parameters, and read back from disk."
            >
              cached
            </span>
          )}
          <span className="ml-auto flex items-center gap-1">
            sequence{" "}
            <span className="text-foreground font-mono">{sequence.id}</span>
            <Button
              type="button"
              variant="ghost"
              size="icon-xs"
              aria-label="Copy the sequence id"
              title="Copy the sequence id"
              onClick={copyId}
            >
              {copied ? <Check /> : <Copy />}
            </Button>
          </span>
        </div>
      </div>

      <div
        ref={observeGrid}
        className="relative grid items-start"
        style={{
          gap: PANE_GAP_PX,
          gridTemplateColumns: gridColumns(panes.length, space),
        }}
        onDragOver={(e) => {
          if (!e.dataTransfer.types.includes(PANE_DRAG)) return;
          e.preventDefault();
          e.dataTransfer.dropEffect = "move";
          const from = panes.findIndex((p) => p.key === dragged.current);
          const target = paneSlot(e.currentTarget, e.clientX, e.clientY);
          const next =
            from < 0 || target.slot === from || target.slot === from + 1
              ? null
              : target;
          // dragover fires many times a second; render only when the line moves.
          setDropSlot((was) =>
            was &&
            next &&
            was.slot === next.slot &&
            was.left === next.left &&
            was.top === next.top &&
            was.height === next.height
              ? was
              : next,
          );
        }}
        onDragLeave={(e) => {
          if (!e.currentTarget.contains(e.relatedTarget as Node | null))
            setDropSlot(null);
        }}
        onDrop={(e) => {
          if (!e.dataTransfer.types.includes(PANE_DRAG)) return;
          e.preventDefault();
          const key = Number(e.dataTransfer.getData(PANE_DRAG));
          const from = panes.findIndex((p) => p.key === key);
          const { slot } = paneSlot(e.currentTarget, e.clientX, e.clientY);
          if (from >= 0 && slot !== from && slot !== from + 1)
            movePane(key, slot > from ? slot - 1 : slot);
          dragged.current = null;
          setDraggedKey(null);
          setDropSlot(null);
        }}
      >
        {panes.map((pane, index) => {
          const stream = streamFor(pane);
          const info = sequence.streams[stream];
          // The server names its default. Deriving it from the order of `colormaps` would
          // make adding one whose name sorts last change this silently.
          const colormap = pane.colormap ?? info.default ?? undefined;
          const overlay = !!pane.overlay && info.overlay !== null;
          const backward = !!pane.backward && info.backward !== null;
          const src = streamUrl(info, { colormap, overlay, backward });
          const readyKey = `${pane.key} ${src}`;
          const updatePane = (change: Partial<Pane>) =>
            setPanes((c) =>
              c.map((p) => (p.key === pane.key ? { ...p, ...change } : p)),
            );
          return (
            <figure
              key={pane.key}
              className={cn(
                "flex min-w-0 flex-col gap-2 rounded-lg",
                draggedKey === pane.key && "opacity-50",
              )}
            >
              <figcaption className="flex items-center gap-2">
                {panes.length > 1 && (
                  <Button
                    type="button"
                    variant="ghost"
                    size="icon-sm"
                    aria-label={`Move ${label(stream)} pane`}
                    title="Drag between panes, or press the left or right arrow, to move this pane"
                    className="text-muted-foreground -ml-1.5 cursor-grab active:cursor-grabbing"
                    draggable
                    onDragStart={(e) => {
                      dragged.current = pane.key;
                      setDraggedKey(pane.key);
                      e.dataTransfer.setData(PANE_DRAG, String(pane.key));
                      e.dataTransfer.effectAllowed = "move";
                      const figure = e.currentTarget.closest("figure");
                      if (figure) e.dataTransfer.setDragImage(figure, 24, 16);
                    }}
                    onDragEnd={() => {
                      dragged.current = null;
                      setDraggedKey(null);
                      setDropSlot(null);
                    }}
                    onKeyDown={(e) => {
                      if (e.metaKey || e.altKey || e.ctrlKey || e.shiftKey)
                        return;
                      const by = ARROW_MOVES[e.key];
                      if (by === undefined) return;
                      e.preventDefault();
                      movePane(pane.key, index + by);
                    }}
                  >
                    <GripVertical />
                  </Button>
                )}
                <Select
                  value={stream}
                  onValueChange={(v) =>
                    updatePane({
                      stream: v,
                      colormap: undefined,
                      overlay: undefined,
                      backward: undefined,
                    })
                  }
                >
                  <SelectTrigger
                    aria-label="Stream"
                    size="sm"
                    className="min-w-0"
                  >
                    <SelectValue />
                  </SelectTrigger>
                  <SelectContent>
                    {names.map((n) => (
                      <SelectItem key={n} value={n}>
                        {label(n)}
                      </SelectItem>
                    ))}
                  </SelectContent>
                </Select>

                {panes.length > 1 && (
                  <Button
                    type="button"
                    variant="ghost"
                    size="icon-xs"
                    aria-label={`Close ${label(stream)} pane`}
                    title="Close"
                    className="text-muted-foreground ml-auto"
                    onClick={() =>
                      setPanes((c) => c.filter((p) => p.key !== pane.key))
                    }
                  >
                    <X />
                  </Button>
                )}
              </figcaption>

              <div className="border-border bg-card relative aspect-square overflow-hidden rounded-lg border">
                {loaded.get(readyKey) !== "ready" && (
                  <p className="text-muted-foreground absolute inset-0 flex items-center justify-center text-xs">
                    {loaded.get(readyKey) === "failed"
                      ? "Could not load this video"
                      : "Preparing video"}
                  </p>
                )}
                <video
                  key={sequence.id}
                  ref={(el) => registerVideo(pane.key, el)}
                  className="h-full w-full object-contain"
                  src={src}
                  onError={() =>
                    setLoaded((seen) => new Map(seen).set(readyKey, "failed"))
                  }
                  loop
                  muted
                  playsInline
                  preload="metadata"
                  onLoadedMetadata={(e) => {
                    setLoaded((seen) => new Map(seen).set(readyKey, "ready"));
                    setDuration(e.currentTarget.duration);
                    decodeFor(pane.key, src);
                    // A seek a new source cut short never ends; its canvas would stay.
                    setCovering((was) => {
                      const next = new Set(was);
                      next.delete(pane.key);
                      return next;
                    });
                    if (restoredSequence.current !== sequence.id) {
                      // First load of a new sequence: the transport is at the start and
                      // nothing should resume on its own.
                      restoredSequence.current = sequence.id;
                      timeRef.current = 0;
                      playingRef.current = false;
                      return;
                    }
                    // A stream change swapped src on an element React
                    // kept, which resets it. Put it back where the transport is and
                    // resume with the others, or this pane silently stops driving
                    // the ones that follow it.
                    e.currentTarget.currentTime = timeRef.current;
                    if (playingRef.current) void e.currentTarget.play();
                  }}
                  onTimeUpdate={(e) => {
                    // Only the first pane reports, or the panes fight over the value.
                    const lead = videos.current.values().next().value;
                    if (lead !== e.currentTarget) return;
                    const at = e.currentTarget.currentTime;
                    timeRef.current = at;
                    setTime(at);
                    videos.current.forEach((v) => {
                      if (
                        v !== e.currentTarget &&
                        Math.abs(v.currentTime - at) > SYNC_TOLERANCE_SECONDS
                      ) {
                        v.currentTime = at;
                      }
                    });
                  }}
                />
                {/* The frame a scrub is on, drawn from memory over the video. */}
                <canvas
                  ref={(el) => {
                    if (el) canvases.current.set(pane.key, el);
                    else canvases.current.delete(pane.key);
                  }}
                  aria-hidden
                  className="pointer-events-none absolute inset-0 h-full w-full"
                  style={{
                    visibility: covering.has(pane.key) ? "visible" : "hidden",
                  }}
                />
              </div>

              {/* Under the pane rather than in its header, which a narrow pane cannot
                  spare. */}
              {info.colormaps.length > 0 && colormap && (
                <div className="flex items-center gap-3">
                  <Select
                    value={colormap}
                    onValueChange={(v) => updatePane({ colormap: v })}
                  >
                    <SelectTrigger
                      aria-label="Colormap"
                      size="sm"
                      className="shrink-0"
                    >
                      <SelectValue />
                    </SelectTrigger>
                    <SelectContent>
                      {info.colormaps.map((c) => (
                        <SelectItem key={c} value={c}>
                          {colormapName(c)}
                        </SelectItem>
                      ))}
                    </SelectContent>
                  </Select>
                  <DepthLegend colormap={colormap} />
                </div>
              )}
              {/* The button on top, level with the other panes' controls however far a
                  narrow pane wraps the legend beside it. */}
              {info.overlay !== null && (
                <div className="flex items-start gap-3">
                  <Button
                    type="button"
                    variant="outline"
                    size="sm"
                    aria-pressed={overlay}
                    title="Draw the mask over the frames in gray"
                    className="aria-pressed:bg-muted aria-pressed:text-foreground shrink-0"
                    onClick={() => updatePane({ overlay: !overlay })}
                  >
                    Overlay
                  </Button>
                  <OcclusionLegend overlay={overlay} />
                </div>
              )}
              {stream === "alpha" && (
                <ObjectLegend colors={sequence.object_colors} />
              )}
              {/* The direction comes from the stream info, as the colormap does; the
                  legend is the flow's own. Top-aligned, as the overlay's row is, so a
                  caption wrapped onto two lines does not push the dropdown down, and
                  with narrower gaps, which leave that caption room for two lines at six
                  panes, not three. */}
              {(info.backward !== null || stream === "flow") && (
                <div className="flex items-start gap-1.5">
                  {info.backward !== null && (
                    <Select
                      value={backward ? "backward" : "forward"}
                      onValueChange={(v) =>
                        updatePane({ backward: v === "backward" })
                      }
                    >
                      <SelectTrigger
                        aria-label="Direction"
                        size="sm"
                        className="shrink-0"
                      >
                        <SelectValue />
                      </SelectTrigger>
                      <SelectContent>
                        <SelectItem value="forward">Forward</SelectItem>
                        <SelectItem value="backward">Backward</SelectItem>
                      </SelectContent>
                    </Select>
                  )}
                  {stream === "flow" && <FlowLegend backward={backward} />}
                </div>
              )}
            </figure>
          );
        })}
        {dropSlot && (
          <div
            data-testid="pane-drop-indicator"
            aria-hidden="true"
            className="bg-ring pointer-events-none absolute w-[3px] -translate-x-1/2 rounded-full"
            style={{
              left: dropSlot.left,
              top: dropSlot.top,
              height: dropSlot.height,
            }}
          />
        )}
      </div>

      {/* Wraps on a narrow screen, where Play and the speed would otherwise leave the
          position slider a few pixels wide. The slider and its counter wrap together.
          Held at the bottom of the window, so it stays in reach when the panes take two
          rows and the page scrolls. */}
      <div className="bg-background sticky bottom-0 z-10 flex flex-wrap items-center gap-4 py-3">
        <Button
          type="button"
          variant="outline"
          className="w-24"
          onClick={togglePlay}
        >
          {playing ? "Pause" : "Play"}
        </Button>
        <Select
          value={String(speed)}
          onValueChange={(v) => changeSpeed(Number(v))}
        >
          <SelectTrigger aria-label="Playback speed" className="w-20">
            <SelectValue />
          </SelectTrigger>
          <SelectContent>
            {SPEEDS.map((s) => (
              <SelectItem key={s} value={String(s)}>
                {s}&times;
              </SelectItem>
            ))}
          </SelectContent>
        </Select>
        <div className="flex min-w-60 flex-1 items-center gap-4">
          <Slider
            aria-label="Position"
            aria-valuetext={`Frame ${frameIndex + 1} of ${sequence.frames}`}
            className="flex-1"
            min={0}
            max={lastFrame}
            step={SCRUB_STEP}
            value={[thumbAt]}
            onValueChange={([position]) => scrubTo(position)}
            onValueCommit={endScrub}
            // A drag that ends where it began commits nothing, and must still end. So must
            // one the browser cancels, or one the page losing focus cuts short: the thumb
            // a drag focuses loses it then.
            onPointerUp={endScrub}
            onPointerCancel={endScrub}
            onBlur={endScrub}
            onKeyDown={(e) => {
              // Home and End too: the slider's own commits before it changes, which would
              // leave the scrub it starts open.
              let to: number;
              if (e.key === "Home") to = 0;
              else if (e.key === "End") to = lastFrame;
              else {
                const by = FRAME_KEYS[e.key];
                if (by === undefined) return;
                // Shift with an arrow is ten frames, as Page Up and Page Down are.
                to =
                  frameIndex +
                  (e.shiftKey && Math.abs(by) === 1 ? by * 10 : by);
              }
              e.preventDefault();
              scrubTo(nearest(to));
              endScrub();
            }}
          />
          <span className="text-muted-foreground w-20 text-right font-mono text-xs tabular-nums">
            {frameIndex + 1} / {sequence.frames}
          </span>
        </div>
        {/* Here rather than beside the panes, where it took a column's width from them. */}
        {names.length > 0 && (
          <Button
            type="button"
            variant="outline"
            onClick={addPane}
            disabled={unshown === undefined || panes.length >= MAX_PANES}
            className="text-muted-foreground border-dashed"
          >
            {unshown === undefined
              ? "All streams shown"
              : panes.length >= MAX_PANES
                ? `${MAX_PANES} panes at most`
                : "Add pane"}
          </Button>
        )}
      </div>
    </div>
  );
}
