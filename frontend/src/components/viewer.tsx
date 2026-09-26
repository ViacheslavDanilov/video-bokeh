"use client";

import { useCallback, useRef, useState } from "react";
import type { Scene } from "@/lib/api";
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

// Four: the frame, the masks, the depth, and the bokeh render once that container
// exists. Past four the panes are too small to judge anything on a laptop.
const MAX_PANES = 4;

// Independent <video> elements drift apart as they play -- measured at about 1.75
// frames after a second and a half. A comparison is worthless if the panes are not on
// the same frame, so followers are snapped back whenever they slip past one frame.
// The tolerance matters: seeking on every tick would stutter.
const SYNC_TOLERANCE_SECONDS = 1 / 24;

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

/** Open on everything the scene has, in the order the server lists it: the frame,
 *  who is in it, and how far away they are. */
function initialPanes(streams: string[]): Pane[] {
  return streams
    .slice(0, MAX_PANES)
    .map((stream, i) => ({ key: i, stream, colormap: "" }));
}

export function Viewer({
  scene,
  generating,
}: {
  scene: Scene | null;
  generating: boolean;
}) {
  const names = scene ? Object.keys(scene.streams) : [];
  const [panes, setPanes] = useState<Pane[]>([]);
  const [playing, setPlaying] = useState(false);
  const [time, setTime] = useState(0);
  const [duration, setDuration] = useState(0);

  const videos = useRef(new Map<number, HTMLVideoElement>());
  // Read inside onLoadedMetadata, which fires long after the render that set the
  // src, so state captured by closure would be stale.
  const timeRef = useRef(0);
  const playingRef = useRef(false);
  // Which scene the refs above describe. Compared inside the load handler rather than
  // reset during render, because writing a ref while rendering is not allowed.
  const restoredScene = useRef<string | null>(null);

  // A new scene rewinds the transport. Adjusting state during render rather than in an
  // effect is React's own recommendation for state that has to follow a prop: an effect
  // would paint the old position once before correcting it.
  const [shownScene, setShownScene] = useState(scene?.id ?? null);
  if ((scene?.id ?? null) !== shownScene) {
    setShownScene(scene?.id ?? null);
    setPlaying(false);
    setTime(0);
    setDuration(0);
  }

  // Mounting happens before any scene exists, so there are no stream names to lay out
  // until the first one arrives.
  if (panes.length === 0 && names.length > 0) {
    setPanes(initialPanes(names));
  }

  // A pane naming a stream this scene does not have falls back to the first one. Derived
  // rather than stored, so no state has to be repaired when the manifest changes.
  const streamFor = (pane: Pane) =>
    scene && pane.stream in scene.streams
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

  const registerVideo = useCallback(
    (key: number, el: HTMLVideoElement | null) => {
      if (el) videos.current.set(key, el);
      else videos.current.delete(key);
    },
    [],
  );

  if (!scene) {
    return (
      <div className="border-border bg-card flex flex-1 flex-col items-center justify-center gap-5 rounded-lg border p-12">
        <div className="w-64">
          <SpectralScale sweeping={generating} />
        </div>
        <p className="text-muted-foreground max-w-xs text-center text-sm">
          {generating
            ? "Sampling trajectories, then rendering every frame."
            : "No scene yet. Set the parameters and generate one."}
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
  const lastFrame = Math.max(scene.frames - 1, 0);
  const frameIndex = duration
    ? Math.min(Math.round((time / duration) * scene.frames), lastFrame)
    : 0;
  const seekToFrame = (frame: number) =>
    seek(duration ? (frame / scene.frames) * duration : 0);

  return (
    <div className="flex flex-1 flex-col gap-5">
      <div className="flex items-start gap-4 max-lg:flex-col">
        <div className="grid min-w-0 flex-1 auto-cols-fr grid-flow-col items-start gap-4 max-lg:w-full max-lg:grid-flow-row">
          {panes.map((pane) => {
            const stream = streamFor(pane);
            const info = scene.streams[stream];
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
                    key={scene.id}
                    ref={(el) => registerVideo(pane.key, el)}
                    className="h-full w-full object-contain"
                    src={streamUrl(info, colormap || undefined)}
                    loop
                    muted
                    playsInline
                    preload="metadata"
                    onLoadedMetadata={(e) => {
                      setDuration(e.currentTarget.duration);
                      if (restoredScene.current !== scene.id) {
                        // First load of a new scene: the transport is at the start and
                        // nothing should resume on its own.
                        restoredScene.current = scene.id;
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

                {stream === "disparity" && (
                  <SpectralScale colormap={colormap} />
                )}
                {stream === "alpha" && (
                  <ObjectLegend colors={scene.object_colors} />
                )}
              </figure>
            );
          })}
        </div>

        {panes.length < MAX_PANES && names.length > 0 && (
          <Button
            type="button"
            variant="outline"
            onClick={addPane}
            className="text-muted-foreground mt-9 shrink-0 border-dashed max-lg:mt-0 max-lg:w-full"
          >
            Add pane
          </Button>
        )}
      </div>

      <div className="flex items-center gap-4">
        <Button
          type="button"
          variant="outline"
          className="w-24"
          onClick={togglePlay}
        >
          {playing ? "Pause" : "Play"}
        </Button>
        <Slider
          aria-label="Position"
          aria-valuetext={`Frame ${frameIndex + 1} of ${scene.frames}`}
          className="flex-1"
          min={0}
          max={lastFrame}
          step={1}
          value={[frameIndex]}
          onValueChange={([f]) => seekToFrame(f)}
        />
        <span className="text-muted-foreground w-20 text-right font-mono text-xs tabular-nums">
          {frameIndex + 1} / {scene.frames}
        </span>
      </div>

      <dl className="text-muted-foreground flex flex-wrap items-center gap-x-6 gap-y-1 text-xs">
        <div className="flex gap-2">
          <dt>scene</dt>
          <dd className="text-foreground font-mono">{scene.id}</dd>
        </div>
        <div className="flex gap-2">
          <dt>objects</dt>
          <dd className="text-foreground font-mono">{scene.n_objects}</dd>
        </div>
        <div className="flex gap-2">
          <dt>size</dt>
          <dd className="text-foreground font-mono">
            {scene.size}&times;{scene.size}
          </dd>
        </div>
        <div className="flex gap-2">
          <dt>seed</dt>
          <dd className="text-foreground font-mono">{scene.seed}</dd>
        </div>
        {scene.cached && <div className="text-far">served from cache</div>}
      </dl>
    </div>
  );
}
