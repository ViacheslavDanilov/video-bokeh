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

/** The steps of a generation, in the order they were reported, each at its latest count. */
export function addStep(
  steps: GenerationStep[],
  next: GenerationStep,
): GenerationStep[] {
  const last = steps.at(-1);
  return last?.step === next.step
    ? [...steps.slice(0, -1), next]
    : [...steps, next];
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

/** How far a step has got: a bar and its count, or, for a step of one part, a bar that
 *  only says it is under way, since nothing finer is known. */
function StepBar({ step, active }: { step: GenerationStep; active: boolean }) {
  if (step.total <= 1) {
    return active ? (
      <div className="bg-muted h-1.5 w-40 shrink-0 overflow-hidden rounded-full">
        <div className="bg-foreground/40 h-full w-full animate-pulse rounded-full" />
      </div>
    ) : null;
  }
  return (
    <>
      <div className="bg-muted h-1.5 w-40 shrink-0 overflow-hidden rounded-full">
        <div
          className="bg-foreground h-full rounded-full transition-[width] duration-200"
          style={{ width: `${(step.done / step.total) * 100}%` }}
        />
      </div>
      <span className="text-muted-foreground font-mono text-xs tabular-nums">
        {step.done} / {step.total}
      </span>
    </>
  );
}

/**
 * What a generation is doing, as the API reports it.
 *
 * A step shows only once the API reports it, so the list is never a guess: bokeh shows only
 * when the API renders it, and a cached sequence, which reports nothing, shows nothing.
 *
 * `line` is one line, the current step alone, for where a sequence is already on screen:
 * there it takes the place of the caption above the panes, at the caption's height, so
 * nothing below it moves. Without it, every step so far is listed, done ones ticked, for
 * the empty screen.
 */
export function GenerationProgress({
  steps,
  startedAt,
  line = false,
}: {
  steps: GenerationStep[];
  startedAt: number;
  line?: boolean;
}) {
  const seconds = useSecondsSince(startedAt);
  const current = steps.at(-1);
  if (current === undefined) return null;

  if (line) {
    return (
      <div
        role="status"
        aria-label="Generation progress"
        className="flex items-center gap-3"
      >
        <LoaderCircle
          aria-hidden
          className="text-foreground size-3.5 shrink-0 animate-spin"
        />
        <span className="text-foreground">{stepName(current.step)}</span>
        {/* Keyed on the step, so the next one's bar starts empty instead of shrinking
            back from where the last one ended. */}
        <StepBar key={current.step} step={current} active />
        <span className="tabular-nums">{seconds} s</span>
      </div>
    );
  }

  return (
    <div
      role="status"
      aria-label="Generation progress"
      className="flex flex-col gap-2 text-sm"
    >
      <ol className="flex flex-col gap-1.5">
        {steps.map((step, index) => {
          const active = step === current && step.done < step.total;
          return (
            <li key={index} className="flex items-center gap-3">
              {active ? (
                <LoaderCircle
                  aria-hidden
                  className="text-foreground size-4 shrink-0 animate-spin"
                />
              ) : (
                <Check
                  aria-hidden
                  className="text-muted-foreground size-4 shrink-0"
                />
              )}
              <span
                className={
                  active
                    ? "text-foreground w-44 shrink-0"
                    : "text-muted-foreground w-44 shrink-0"
                }
              >
                {stepName(step.step)}
              </span>
              <StepBar step={step} active={active} />
            </li>
          );
        })}
      </ol>
      <p className="text-muted-foreground text-xs tabular-nums">{seconds} s</p>
    </div>
  );
}
