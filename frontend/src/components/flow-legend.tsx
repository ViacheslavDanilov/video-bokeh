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
    <div className="text-muted-foreground flex min-w-0 items-center gap-3 text-xs">
      <div
        className="border-border size-8 shrink-0 rounded-full border"
        style={{ background: WHEEL }}
        aria-hidden
      />
      <p>
        {backward
          ? "Color is where a pixel came from in the previous frame, so one moving right is cyan, the opposite of red."
          : "Color is where a pixel moves in the next frame, right is red."}{" "}
        Vivid is fast, paler is slower, white is still.
      </p>
    </div>
  );
}
