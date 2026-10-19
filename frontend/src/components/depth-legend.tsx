import { SpectralScale } from "./spectral-scale";

/**
 * The disparity legend, in the colormap the pane shows.
 *
 * Spectral is the depth scale the page draws everywhere else. Gray is the same axis under
 * another rendering, white near and black far as the backend's gray table runs, so it gets
 * the same bar: without one the gray pane loses every cue about which end is near. A
 * colormap the page has no bar for shows none rather than the wrong one.
 */

// Presentation only: a colormap the server adds later still reads sensibly by its id.
const NAMES: Record<string, string> = {
  spectral_r: "Spectral",
  grey: "Gray",
};

export function colormapName(colormap: string): string {
  return NAMES[colormap] ?? colormap.replaceAll("_", " ");
}

const GRAY = "linear-gradient(to right, #ffffff, #000000)";

export function DepthLegend({ colormap }: { colormap: string }) {
  if (colormap !== "spectral_r" && colormap !== "grey") return null;
  return (
    <div
      role="img"
      aria-label={`${colormapName(colormap)} scale, near to far`}
      className="min-w-0 flex-1"
    >
      {colormap === "spectral_r" ? (
        <SpectralScale />
      ) : (
        <div className="flex items-center gap-3">
          <span className="text-muted-foreground shrink-0 text-xs">near</span>
          <div
            className="border-border h-2 flex-1 rounded-full border"
            style={{ background: GRAY }}
          />
          <span className="text-muted-foreground shrink-0 text-xs">far</span>
        </div>
      )}
    </div>
  );
}
