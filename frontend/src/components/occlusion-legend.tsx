import { Layers2 } from "lucide-react";
import { Button } from "@/components/ui/button";
import {
  Tooltip,
  TooltipContent,
  TooltipProvider,
  TooltipTrigger,
} from "@/components/ui/tooltip";
import { cn } from "@/lib/utils";

/**
 * What the occlusion pane marks: the pixels whose surface the neighbor frame does not show,
 * the next one for the forward mask and the previous one for the backward mask. As stored
 * they are white on black; over the frames, cyan on the picture in gray.
 *
 * Built as the flow's legend is: beside the pane's controls one short caption, which a
 * narrow pane wraps onto two lines, level with the other panes' controls. The overlay's
 * toggle carries the colors, as the flow's wheel does. The full reading is a tooltip on
 * the caption, which a keyboard reaches as a button.
 */

// Cyan, #00E5FF, as `preview/pack.py` draws the overlay.
const CYAN = "rgb(0 229 255)";

/**
 * The overlay toggle: the two-layer icon, outlined and quiet while the overlay is off. On, the
 * button takes the soft fill of a pressed toggle, the icon its full color, and the top layer,
 * the mask, the cyan the backend draws it in, so the toggle is also the key to that color.
 */
export function OverlayToggle({
  overlay,
  onToggle,
}: {
  overlay: boolean;
  onToggle: () => void;
}) {
  return (
    <Button
      type="button"
      variant="outline"
      size="icon-sm"
      aria-label="Overlay"
      aria-pressed={overlay}
      title="Overlay: draw the mask over the frames in gray"
      className="text-muted-foreground aria-pressed:bg-muted aria-pressed:text-foreground aria-pressed:hover:bg-foreground/10 shrink-0 duration-150"
      onClick={onToggle}
    >
      <Layers2
        aria-hidden
        data-swatch
        style={{ "--mask": CYAN } as React.CSSProperties}
        className={cn(
          "[&>path:first-child]:fill-transparent [&>path:first-child]:transition-[fill] [&>path:first-child]:duration-150",
          overlay && "[&>path:first-child]:fill-(--mask)",
        )}
      />
    </Button>
  );
}

export function OcclusionLegend({ backward }: { backward: boolean }) {
  const neighbor = backward ? "previous" : "next";
  // Seen from the previous frame, a surface that is not there was covered or had not yet
  // come into the frame.
  const why = backward
    ? "something covered it, or it entered the frame"
    : "something covers it, or it leaves the frame";
  return (
    <TooltipProvider>
      <Tooltip>
        <TooltipTrigger asChild>
          <button
            type="button"
            className="text-muted-foreground focus-visible:ring-ring/50 flex min-h-7 min-w-0 cursor-help items-start rounded-md text-left text-xs outline-none focus-visible:ring-3"
          >
            {/* The height of the controls beside it, and level with their tops however
                many lines the caption takes. */}
            <span className="line-clamp-2 self-center tracking-tight">
              Hidden in the {neighbor} frame.
            </span>
          </button>
        </TooltipTrigger>
        <TooltipContent side="top" className="max-w-64">
          These pixels show a surface the {neighbor} frame does not: {why}. With
          the overlay on they are cyan over the picture in gray; with it off,
          the mask alone is white on black.
        </TooltipContent>
      </Tooltip>
    </TooltipProvider>
  );
}
