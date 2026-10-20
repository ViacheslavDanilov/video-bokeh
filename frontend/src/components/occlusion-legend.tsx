/**
 * What the occlusion pane marks: the pixels whose surface the next frame does not show. As
 * stored they are white on black; over the frames, orange on the picture in gray.
 */

// Okabe-Ito orange, #E69F00, as `preview/pack.py` draws the overlay.
const ORANGE = "rgb(230 159 0)";

export function OcclusionLegend({ overlay }: { overlay: boolean }) {
  return (
    <span className="flex min-w-0 items-center gap-1.5">
      <span
        aria-hidden
        className="border-border size-2.5 shrink-0 rounded-[2px] border"
        style={{ background: overlay ? ORANGE : "rgb(255 255 255)" }}
      />
      <span className="text-muted-foreground text-xs">
        {overlay ? "Orange" : "White"}: hidden in the next frame
      </span>
    </span>
  );
}
