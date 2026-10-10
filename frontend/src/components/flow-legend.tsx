/**
 * The optical-flow legend: which colour is which direction.
 *
 * The wheel the backend colours the flow with, Baker et al.'s in `preview/_flow.py`: its
 * six anchor colours at the angles the backend puts them, rightward red and turning
 * clockwise through down, left and up, and white at the centre, where nothing moves. A pixel
 * is paler the slower it moves, fully saturated at the fastest in the sequence.
 */

// Each anchor's place on the wheel, 0 to 54, as the backend counts its 55 colours.
const ANCHORS: [string, number][] = [
  ["rgb(255 0 0)", 0],
  ["rgb(255 255 0)", 15],
  ["rgb(0 255 0)", 21],
  ["rgb(0 255 255)", 25],
  ["rgb(0 0 255)", 36],
  ["rgb(255 0 255)", 49],
  // The wheel's last colour, a step short of red, as the backend has it.
  ["rgb(255 0 43)", 54],
];

const WHEEL = [
  // Paler towards the centre, as the backend fades a slow pixel towards white.
  "radial-gradient(closest-side, rgb(255 255 255), rgb(255 255 255 / 0))",
  // Starting at 90deg, rightward, which is where the backend's wheel starts.
  `conic-gradient(from 90deg, ${ANCHORS.map(
    ([colour, k]) => `${colour} ${((k / 54) * 360).toFixed(1)}deg`,
  ).join(", ")})`,
].join(", ");

export function FlowLegend() {
  return (
    <div className="text-muted-foreground flex items-center gap-3 text-xs">
      <div
        className="border-border size-8 shrink-0 rounded-full border"
        style={{ background: WHEEL }}
        aria-hidden
      />
      <p>
        Colour is the direction, right is red. Paler is slower; white is still.
      </p>
    </div>
  );
}
