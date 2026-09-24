/**
 * Which colour is which object in the mask pane.
 *
 * The colours come from the scene, not from a copy of the palette here, so the legend
 * and the video cannot disagree. The numbering is the alpha page order, which the
 * pipeline fixes for the whole clip — an object keeps its colour from the first frame
 * to the last, which is what makes a crossing readable.
 */
export function ObjectLegend({ colors }: { colors: string[] }) {
  return (
    <div className="flex flex-wrap items-center gap-x-3 gap-y-1">
      {colors.map((color, i) => (
        <span key={color + i} className="flex items-center gap-1.5">
          <span
            aria-hidden
            className="border-border size-2.5 rounded-[2px] border"
            style={{ background: color }}
          />
          <span className="text-muted-foreground text-xs">Object {i + 1}</span>
        </span>
      ))}
    </div>
  );
}
