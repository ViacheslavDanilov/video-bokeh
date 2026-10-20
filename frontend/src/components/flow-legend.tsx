import {
  Tooltip,
  TooltipContent,
  TooltipProvider,
  TooltipTrigger,
} from "@/components/ui/tooltip";

/**
 * The optical-flow legend: which color is which direction.
 *
 * The wheel the backend colors the flow with, Baker et al.'s in `preview/_flow.py`: its
 * six anchor colors at the angles the backend puts them, rightward red and turning
 * clockwise through down, left and up, and white at the center, where nothing moves. A pixel
 * is paler the slower it moves, fully saturated at the fastest in the sequence.
 *
 * The backward flow uses the same wheel, but its vectors point to where a pixel came from,
 * so a pixel moving right is drawn in the color of left, cyan.
 *
 * Under the pane it is one short line, which six narrow panes side by side can still fit
 * level with the other panes' controls. The full reading, which depends on the direction,
 * is a tooltip on the legend, which a keyboard reaches as a button.
 */

// Each anchor's place on the wheel, 0 to 54, as the backend counts its 55 colors.
const ANCHORS: [string, number][] = [
  ["rgb(255 0 0)", 0],
  ["rgb(255 255 0)", 15],
  ["rgb(0 255 0)", 21],
  ["rgb(0 255 255)", 25],
  ["rgb(0 0 255)", 36],
  ["rgb(255 0 255)", 49],
  // The wheel's last color, a step short of red, as the backend has it.
  ["rgb(255 0 43)", 54],
];

const WHEEL = [
  // Paler toward the center, as the backend fades a slow pixel toward white.
  "radial-gradient(closest-side, rgb(255 255 255), rgb(255 255 255 / 0))",
  // Starting at 90deg, rightward, which is where the backend's wheel starts.
  `conic-gradient(from 90deg, ${ANCHORS.map(
    ([color, k]) => `${color} ${((k / 54) * 360).toFixed(1)}deg`,
  ).join(", ")})`,
].join(", ");

export function FlowLegend({ backward }: { backward: boolean }) {
  return (
    <TooltipProvider>
      <Tooltip>
        <TooltipTrigger asChild>
          <button
            type="button"
            className="text-muted-foreground focus-visible:ring-ring/50 flex h-7 min-w-0 cursor-help items-center gap-2 rounded-md text-left text-xs outline-none focus-visible:ring-3"
          >
            {/* The height of the controls beside it, so the row stays theirs. */}
            <span
              className="border-border size-7 shrink-0 rounded-full border"
              style={{ background: WHEEL }}
              aria-hidden
            />
            <span className="truncate">Color = direction; paler = slower</span>
          </button>
        </TooltipTrigger>
        <TooltipContent side="top" className="max-w-64">
          {backward
            ? "Color is where a pixel came from in the previous frame, so one moving right is cyan, the opposite of red."
            : "Color is where a pixel moves in the next frame, right is red."}{" "}
          Vivid is fast, paler is slower, white is still.
        </TooltipContent>
      </Tooltip>
    </TooltipProvider>
  );
}
