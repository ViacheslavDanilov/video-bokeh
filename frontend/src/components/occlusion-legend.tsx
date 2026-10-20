/**
 * What the occlusion pane marks: the pixels whose surface the next frame does not show. As
 * stored they are white on black; over the frames, cyan on the picture in gray.
 */

// Cyan, #00E5FF, as `preview/pack.py` draws the overlay.
const CYAN = "rgb(0 229 255)";

export function OcclusionLegend({ overlay }: { overlay: boolean }) {
  return (
    <span className="flex min-w-0 items-center gap-1.5">
      <span
        aria-hidden
        data-swatch
        className="border-border size-2.5 shrink-0 rounded-[2px] border"
        style={{ background: overlay ? CYAN : "rgb(255 255 255)" }}
      />
      <span className="text-muted-foreground text-xs">
        {overlay ? "Cyan" : "White"}: hidden in the next frame
      </span>
    </span>
  );
}
