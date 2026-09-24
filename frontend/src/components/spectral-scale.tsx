/**
 * The depth legend, and the one piece of motion on the page.
 *
 * A colormap with no legend cannot be read, so this has to exist anyway. The eleven
 * stops are the ColorBrewer Spectral anchors in the order the backend's lookup table
 * uses them — red is near, violet is far — so the bar and the depth map beside it are
 * the same scale.
 *
 * While a scene generates it sweeps along that axis instead of showing a spinner: the
 * wait is the pipeline walking the depth axis, and the bar says so.
 */

const SPECTRAL_R = [
  "#9e0142",
  "#d53e4f",
  "#f46d43",
  "#fdae61",
  "#fee08b",
  "#ffffbf",
  "#e6f598",
  "#abdda4",
  "#66c2a5",
  "#3288bd",
  "#5e4fa2",
];

const RAMP = `linear-gradient(to right, ${SPECTRAL_R.join(", ")})`;

export function SpectralScale({ sweeping = false }: { sweeping?: boolean }) {
  return (
    <div className="flex items-center gap-3">
      <span className="text-muted-foreground shrink-0 text-xs">near</span>
      <div className="border-border relative h-2 flex-1 overflow-hidden rounded-full border">
        <div className="absolute inset-0" style={{ background: RAMP }} />
        {sweeping && (
          <div
            className="depth-sweep absolute inset-y-0 w-1/3"
            style={{
              background:
                "linear-gradient(to right, transparent, rgba(255,255,255,0.9), transparent)",
            }}
          />
        )}
      </div>
      <span className="text-muted-foreground shrink-0 text-xs">far</span>
    </div>
  );
}
