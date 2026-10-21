import {
  Tooltip,
  TooltipContent,
  TooltipProvider,
  TooltipTrigger,
} from "@/components/ui/tooltip";

/**
 * What the occlusion pane marks: the pixels whose surface the next frame does not show. As
 * stored they are white on black; over the frames, cyan on the picture in gray.
 *
 * Built as the flow's legend is: under the pane one short caption, which a narrow pane
 * wraps onto two lines, the swatch staying level with the other panes' controls. The full
 * reading is a tooltip on the legend, which a keyboard reaches as a button.
 */

// Cyan, #00E5FF, as `preview/pack.py` draws the overlay.
const CYAN = "rgb(0 229 255)";

export function OcclusionLegend({ overlay }: { overlay: boolean }) {
  return (
    <TooltipProvider>
      <Tooltip>
        <TooltipTrigger asChild>
          <button
            type="button"
            className="text-muted-foreground focus-visible:ring-ring/50 flex min-h-7 min-w-0 cursor-help items-start gap-1 rounded-md text-left text-xs outline-none focus-visible:ring-3"
          >
            {/* The height of the controls beside it, with the swatch centered in it, and
                level with their tops however many lines the caption takes. Only as wide
                as the swatch needs, so the caption keeps the room for two lines. */}
            <span className="flex h-7 w-4 shrink-0 items-center justify-center">
              <span
                aria-hidden
                data-swatch
                className="border-border size-2.5 rounded-[2px] border"
                style={{ background: overlay ? CYAN : "rgb(255 255 255)" }}
              />
            </span>
            <span className="line-clamp-2 self-center tracking-tight">
              {overlay ? "Cyan" : "White"} marks what is hidden next.
            </span>
          </button>
        </TooltipTrigger>
        <TooltipContent side="top" className="max-w-64">
          These pixels show a surface the next frame does not: something covers
          it, or it leaves the frame. With the overlay on they are cyan over the
          picture in gray, with it off the mask alone is white on black.
        </TooltipContent>
      </Tooltip>
    </TooltipProvider>
  );
}
