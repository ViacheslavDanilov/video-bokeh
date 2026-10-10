"use client";

import { useCallback, useRef, useState } from "react";
import type { Sequence } from "@/lib/api";
import { streamUrl } from "@/lib/api";
import { Button } from "@/components/ui/button";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";
import { Slider } from "@/components/ui/slider";
import { ObjectLegend } from "./object-legend";
import { SpectralScale } from "./spectral-scale";

// Every stream a sequence has, and one more to compare two colormaps of the same one.
// Past what fits in a row the panes wrap rather than shrink; see `gridColumns`.
const MAX_PANES = 6;

// The grid's gap-4.
const PANE_GAP_PX = 16;
// What a pane needs besides its square: the stream picker above, a legend of up to two
// lines below.
const PANE_CHROME_PX = 84;
// Kept free under the grid for the transport and the gap above it.
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

type Pane = {
  key: number;
  stream: string;
  colormap: string;
};

// Presentation only: an unknown name still reads sensibly, so a stream the server adds
// later needs no change here to appear.
const LABELS: Record<string, string> = {
  all_in_focus: "All in focus",
  disparity: "Disparity",
  alpha: "Alpha",
  bokeh: "Bokeh",
  spectral_r: "Spectral",
  grey: "Grey",
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
  const fit = Math.floor(
    (space.width + PANE_GAP_PX) / (MIN_PANE_PX + PANE_GAP_PX),
  );
  const rows = Math.ceil(panes / Math.max(1, Math.min(panes, fit)));
  return `repeat(${Math.ceil(panes / rows)}, minmax(0, 1fr))`;
}

/** Open on everything the sequence has, in the order the server lists it: the frame,
 *  who is in it, and how far away they are. */
function initialPanes(streams: string[]): Pane[] {
  return streams
    .slice(0, MAX_PANES)
    .map((stream, i) => ({ key: i, stream, colormap: "" }));
}

export function Viewer({
  sequence,
  library,
  generating,
}: {
  sequence: Sequence | null;
  /** The library this sequence came from, as the page names libraries. */
  library: string;
  generating: boolean;
}) {
  const names = sequence ? Object.keys(sequence.streams) : [];
  const [panes, setPanes] = useState<Pane[]>([]);
  const [playing, setPlaying] = useState(false);
  const [time, setTime] = useState(0);
  const [duration, setDuration] = useState(0);
  // A viewer setting rather than part of the sequence, so a new sequence keeps it.
  const [speed, setSpeed] = useState(1);

  const videos = useRef(new Map<number, HTMLVideoElement>());
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
  // The room the pane grid has, which the parameters folding away or the window changes.
  const [space, setSpace] = useState<Space>({ width: 0, height: 0 });
  const measureGrid = useCallback((el: HTMLDivElement) => {
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
  }

  // Mounting happens before any sequence exists, so there are no stream names to lay out
  // until the first one arrives.
  if (panes.length === 0 && names.length > 0) {
    setPanes(initialPanes(names));
  }

  // A stream the server did not list for the last sequence gets a pane of its own while
  // there is room: bokeh appears this way, when a sequence that had none is asked for again
  // with it. Only a stream new since the last sequence, so a closed pane stays
  // closed while the streams do not change.
  const [knownStreams, setKnownStreams] = useState<string[]>([]);
  if (names.join(",") !== knownStreams.join(",")) {
    setKnownStreams(names);
    const appeared = names.filter(
      (n) => !knownStreams.includes(n) && !panes.some((p) => p.stream === n),
    );
    const room = MAX_PANES - panes.length;
    if (panes.length > 0 && appeared.length > 0 && room > 0) {
      const nextKey = Math.max(0, ...panes.map((p) => p.key)) + 1;
      setPanes([
        ...panes,
        ...appeared
          .slice(0, room)
          .map((stream, i) => ({ key: nextKey + i, stream, colormap: "" })),
      ]);
    }
  }

  // A pane naming a stream this sequence does not have falls back to the first one. Derived
  // rather than stored, so no state has to be repaired when the streams listed change.
  const streamFor = (pane: Pane) =>
    sequence && pane.stream in sequence.streams
      ? pane.stream
      : (names[0] ?? pane.stream);

  const eachVideo = useCallback((fn: (v: HTMLVideoElement) => void) => {
    videos.current.forEach(fn);
  }, []);

  // One transport drives every pane, the way vpv drives its panes: a comparison is only
  // worth anything if the frames line up.
  // Side effects live outside the updater: React may call an updater twice under
  // StrictMode, and pausing or playing twice is not what it is for.
  const togglePlay = useCallback(() => {
    const next = !playingRef.current;
    playingRef.current = next;
    setPlaying(next);
    if (!next) {
      eachVideo((v) => v.pause());
      return;
    }
    const lead = videos.current.values().next().value;
    const at = lead ? lead.currentTime : 0;
    timeRef.current = at;
    eachVideo((v) => {
      v.currentTime = at;
      void v.play();
    });
  }, [eachVideo]);

  const seek = useCallback(
    (to: number) => {
      timeRef.current = to;
      setTime(to);
      eachVideo((v) => {
        v.currentTime = to;
      });
    },
    [eachVideo],
  );

  // Loading a new src resets an element's rate to its default rate, so both are set: a
  // stream or colormap switch then keeps the speed without any handler of its own.
  const applySpeed = useCallback((v: HTMLVideoElement) => {
    v.defaultPlaybackRate = speedRef.current;
    v.playbackRate = speedRef.current;
  }, []);

  const changeSpeed = useCallback(
    (to: number) => {
      speedRef.current = to;
      setSpeed(to);
      eachVideo(applySpeed);
    },
    [eachVideo, applySpeed],
  );

  const registerVideo = useCallback(
    (key: number, el: HTMLVideoElement | null) => {
      if (el) {
        // A pane added later, or remounted for a new sequence, starts at the chosen speed.
        applySpeed(el);
        videos.current.set(key, el);
      } else {
        videos.current.delete(key);
      }
    },
    [applySpeed],
  );

  if (!sequence) {
    return (
      <div className="border-border bg-card flex flex-1 flex-col items-center justify-center gap-5 rounded-lg border p-12">
        <div className="w-64">
          <SpectralScale sweeping={generating} />
        </div>
        <p className="text-muted-foreground max-w-xs text-center text-sm">
          {generating
            ? "Sampling trajectories, then rendering every frame."
            : "No sequence yet. Set the parameters and generate one."}
        </p>
      </div>
    );
  }

  const addPane = () => {
    // Prefer a stream not on screen yet; falling back to a repeat is deliberate, since
    // two panes of disparity under different colormaps is a real comparison.
    const unused =
      names.find((n) => !panes.some((p) => p.stream === n)) ?? names[0];
    setPanes((current) => [
      ...current,
      {
        key: Math.max(0, ...current.map((p) => p.key)) + 1,
        stream: unused,
        colormap: "",
      },
    ]);
  };

  // The transport counts frames, not seconds. A slider stepping by duration/frames
  // lands on fractions the browser then rounds back, so arrow keys stalled after two
  // presses -- and a screen reader read out seconds when the interesting number is the
  // frame. Integers fix both.
  const lastFrame = Math.max(sequence.frames - 1, 0);
  const frameIndex = duration
    ? Math.min(Math.round((time / duration) * sequence.frames), lastFrame)
    : 0;
  const seekToFrame = (frame: number) =>
    seek(duration ? (frame / sequence.frames) * duration : 0);

  return (
    <div className="flex flex-1 flex-col gap-5">
      <div
        ref={measureGrid}
        className="grid items-start gap-4"
        style={{
          gridTemplateColumns: gridColumns(panes.length, space),
        }}
      >
        {panes.map((pane) => {
          const stream = streamFor(pane);
          const info = sequence.streams[stream];
          // The server names its default. Deriving it from the order of `colormaps`
          // would make adding one whose name sorts last change this silently.
          const colormap = pane.colormap || info.default || "";
          return (
            <figure key={pane.key} className="flex min-w-0 flex-col gap-2">
              <figcaption className="flex items-center gap-2">
                <Select
                  value={stream}
                  onValueChange={(v) =>
                    setPanes((c) =>
                      c.map((p) =>
                        p.key === pane.key
                          ? { ...p, stream: v, colormap: "" }
                          : p,
                      ),
                    )
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

                {info.colormaps.length > 0 && (
                  <Select
                    value={colormap}
                    onValueChange={(v) =>
                      setPanes((c) =>
                        c.map((p) =>
                          p.key === pane.key ? { ...p, colormap: v } : p,
                        ),
                      )
                    }
                  >
                    <SelectTrigger
                      aria-label="Colormap"
                      size="sm"
                      className="min-w-0"
                    >
                      <SelectValue />
                    </SelectTrigger>
                    <SelectContent>
                      {info.colormaps.map((c) => (
                        <SelectItem key={c} value={c}>
                          {label(c)}
                        </SelectItem>
                      ))}
                    </SelectContent>
                  </Select>
                )}

                {panes.length > 1 && (
                  <Button
                    type="button"
                    variant="ghost"
                    size="sm"
                    aria-label={`Close ${label(stream)} pane`}
                    className="text-muted-foreground ml-auto"
                    onClick={() => {
                      videos.current.delete(pane.key);
                      setPanes((c) => c.filter((p) => p.key !== pane.key));
                    }}
                  >
                    Close
                  </Button>
                )}
              </figcaption>

              <div className="border-border bg-card aspect-square overflow-hidden rounded-lg border">
                <video
                  key={sequence.id}
                  ref={(el) => registerVideo(pane.key, el)}
                  className="h-full w-full object-contain"
                  src={streamUrl(info, colormap || undefined)}
                  loop
                  muted
                  playsInline
                  preload="metadata"
                  onLoadedMetadata={(e) => {
                    setDuration(e.currentTarget.duration);
                    if (restoredSequence.current !== sequence.id) {
                      // First load of a new sequence: the transport is at the start and
                      // nothing should resume on its own.
                      restoredSequence.current = sequence.id;
                      timeRef.current = 0;
                      playingRef.current = false;
                      return;
                    }
                    // A stream or colormap change swapped src on an element React
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
              </div>

              {stream === "disparity" && <SpectralScale colormap={colormap} />}
              {stream === "alpha" && (
                <ObjectLegend colors={sequence.object_colors} />
              )}
            </figure>
          );
        })}
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
            step={1}
            value={[frameIndex]}
            onValueChange={([f]) => seekToFrame(f)}
          />
          <span className="text-muted-foreground w-20 text-right font-mono text-xs tabular-nums">
            {frameIndex + 1} / {sequence.frames}
          </span>
        </div>
        {/* Here rather than beside the panes, where it took a column's width from them. */}
        {panes.length < MAX_PANES && names.length > 0 && (
          <Button
            type="button"
            variant="outline"
            onClick={addPane}
            className="text-muted-foreground border-dashed"
          >
            Add pane
          </Button>
        )}
      </div>

      <dl className="text-muted-foreground flex flex-wrap items-center gap-x-6 gap-y-1 text-xs">
        <div className="flex gap-2">
          <dt>sequence</dt>
          <dd className="text-foreground font-mono">{sequence.id}</dd>
        </div>
        <div className="flex gap-2">
          <dt>library</dt>
          <dd className="text-foreground font-mono">{library}</dd>
        </div>
        <div className="flex gap-2">
          <dt>objects</dt>
          <dd className="text-foreground font-mono">{sequence.n_objects}</dd>
        </div>
        <div className="flex gap-2">
          <dt>size</dt>
          <dd className="text-foreground font-mono">
            {sequence.size}&times;{sequence.size}
          </dd>
        </div>
        <div className="flex gap-2">
          <dt>seed</dt>
          <dd className="text-foreground font-mono">{sequence.seed}</dd>
        </div>
        {sequence.cached && <div className="text-far">served from cache</div>}
      </dl>
    </div>
  );
}
