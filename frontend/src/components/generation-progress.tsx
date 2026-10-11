"use client";

import { useEffect, useState } from "react";
import { Check, LoaderCircle } from "lucide-react";
import type { GenerationStep } from "@/lib/api";
import { cn } from "@/lib/utils";

// Presentation only: a step a later API adds still shows, under its own name.
const STEP_NAMES: Record<string, string> = {
  sampling: "Choosing trajectories",
  frames: "Rendering frames",
  writing: "Writing frames",
  flow: "Adding optical flow",
  bokeh: "Rendering bokeh",
};

function stepName(step: string): string {
  return STEP_NAMES[step] ?? step;
}

/**
 * `text` in the room the widest of `widest` needs, so what follows it stays where it is
 * while `text` changes. The others share its cell, hidden.
 */
function Steady({
  text,
  widest,
  className,
}: {
  text: string;
  widest: string[];
  className?: string;
}) {
  return (
    <span className={cn("grid", className)}>
      <span className="col-start-1 row-start-1">{text}</span>
      {widest.map((w) => (
        <span key={w} className="invisible col-start-1 row-start-1">
          {w}
        </span>
      ))}
    </span>
  );
}

function useSecondsSince(startedAt: number, finishedAt: number | null): number {
  // From the start rather than from 0, so a line that mounts late reads the time so far
  // rather than "0 s" until its first tick.
  const [seconds, setSeconds] = useState(() =>
    Math.floor((Date.now() - startedAt) / 1000),
  );
  useEffect(() => {
    if (finishedAt !== null) return;
    const tick = () => setSeconds(Math.floor((Date.now() - startedAt) / 1000));
    const timer = setInterval(tick, 250);
    return () => clearInterval(timer);
  }, [startedAt, finishedAt]);
  return finishedAt === null
    ? seconds
    : Math.floor((finishedAt - startedAt) / 1000);
}

/**
 * How a generation is going: one bar for the whole of it, the step under way,
 * and the time so far.
 *
 * The bar is the counts done over the counts the API announced, summed over the steps, so it
 * fills once and never goes back at a new step. Every count weighs the same, which runs it a
 * little fast through the frames and slower through the bokeh. The step under way is the
 * first one not counted to its total; with none left, the line says it is done.
 */
export function GenerationProgress({
  steps,
  startedAt,
  finishedAt,
}: {
  steps: GenerationStep[];
  startedAt: number;
  finishedAt: number | null;
}) {
  const seconds = useSecondsSince(startedAt, finishedAt);
  const total = steps.reduce((sum, s) => sum + s.total, 0);
  if (total === 0) return null;
  const done = steps.reduce((sum, s) => sum + Math.min(s.done, s.total), 0);
  const percent = Math.floor((done / total) * 100);
  const index = steps.findIndex((s) => s.done < s.total);
  const current = steps[index];

  return (
    <div
      role="status"
      aria-label="Generation progress"
      className="grid grid-cols-[repeat(5,auto)] items-center gap-2 sm:flex sm:gap-3"
    >
      {current ? (
        <LoaderCircle
          aria-hidden
          className="text-foreground size-3.5 shrink-0 animate-spin"
        />
      ) : (
        <Check aria-hidden className="text-foreground size-3.5 shrink-0" />
      )}
      <Steady
        className="text-foreground col-span-5 row-start-1 justify-items-center sm:justify-items-start"
        text={current ? stepName(current.step) : "Done"}
        widest={[...Object.values(STEP_NAMES), "Done"]}
      />
      <Steady
        className="tabular-nums"
        text={current ? `step ${index + 1} of ${steps.length}` : ""}
        widest={[`step ${steps.length} of ${steps.length}`]}
      />
      <div
        role="progressbar"
        aria-label="Generated"
        aria-valuemin={0}
        aria-valuemax={100}
        aria-valuenow={percent}
        className="bg-muted h-1.5 w-12 shrink-0 overflow-hidden rounded-full sm:w-40"
      >
        <div
          className="bg-foreground h-full rounded-full transition-[width] duration-150 ease-out"
          style={{ width: `${(done / total) * 100}%` }}
        />
      </div>
      <Steady
        className="justify-items-end tabular-nums"
        text={`${percent}%`}
        widest={["100%"]}
      />
      {/* Centered on the empty screen, the line would move with each digit added. */}
      <Steady
        className="tabular-nums"
        text={`${seconds} s`}
        widest={["000 s"]}
      />
    </div>
  );
}
