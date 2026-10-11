"use client";

import { useEffect, useState } from "react";
import { Check, LoaderCircle } from "lucide-react";
import type { GenerationStep } from "@/lib/api";

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

function useSecondsSince(startedAt: number): number {
  const [seconds, setSeconds] = useState(0);
  useEffect(() => {
    const tick = () => setSeconds(Math.floor((Date.now() - startedAt) / 1000));
    const timer = setInterval(tick, 250);
    return () => clearInterval(timer);
  }, [startedAt]);
  return seconds;
}

/**
 * How a generation is going, on one line: one bar for the whole of it, the step under way,
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
}: {
  steps: GenerationStep[];
  startedAt: number;
}) {
  const seconds = useSecondsSince(startedAt);
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
      className="flex items-center gap-3"
    >
      {current ? (
        <LoaderCircle
          aria-hidden
          className="text-foreground size-3.5 shrink-0 animate-spin"
        />
      ) : (
        <Check aria-hidden className="text-foreground size-3.5 shrink-0" />
      )}
      <span className="text-foreground">
        {current ? stepName(current.step) : "Done"}
      </span>
      {current && (
        <span>
          step {index + 1} of {steps.length}
        </span>
      )}
      <div
        role="progressbar"
        aria-label="Generated"
        aria-valuemin={0}
        aria-valuemax={100}
        aria-valuenow={percent}
        className="bg-muted h-1.5 w-40 shrink-0 overflow-hidden rounded-full"
      >
        <div
          className="bg-foreground h-full rounded-full transition-[width] duration-150 ease-out"
          style={{ width: `${(done / total) * 100}%` }}
        />
      </div>
      <span className="tabular-nums">{percent}%</span>
      <span className="tabular-nums">{seconds} s</span>
    </div>
  );
}
