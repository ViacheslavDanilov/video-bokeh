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
            className="text-muted-foreground focus-visible:ring-ring/50 flex min-h-7 min-w-0 cursor-help items-start gap-1.5 rounded-md text-left text-xs outline-none focus-visible:ring-3"
          >
            {/* The height of the controls beside it, with the swatch centered in it, and
                level with their tops however many lines the caption takes. */}
            <span className="flex size-7 shrink-0 items-center justify-center">
              <span
                aria-hidden
                data-swatch
                className="border-border size-2.5 rounded-[2px] border"
                style={{ background: overlay ? CYAN : "rgb(255 255 255)" }}
              />
            </span>
            <span className="line-clamp-2 self-center tracking-tight">
              {overlay ? "Cyan" : "White"} marks what the next frame hides.
            </span>
          </button>
        </TooltipTrigger>
        <TooltipContent side="top" className="max-w-64">
          Pixels whose surface the next frame does not show, because something
          moves over them. With the overlay on they are cyan over the picture.
          With it off, the mask alone is white on black.
        </TooltipContent>
      </Tooltip>
    </TooltipProvider>
  );
}
