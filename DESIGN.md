# Vercel — Style Reference

The demo uses a light monochrome interface so the video streams carry the color.
This is the subset of the Vercel reference used by `globals.css` and `layout.tsx`.
The frontend defines the semantic tokens and loads Geist through the `geist` package.

## Tokens — Colors

The canvas, text, and borders establish the interface hierarchy.

| Name | Value | Demo role |
|------|-------|-----------|
| Paper White | `#fafafa` | Page background |
| Pure White | `#ffffff` | Cards, popovers, and primary button text |
| Hairline | `#ebebeb` | Borders, inputs, muted surfaces, and hover backgrounds |
| Stone | `#666666` | Captions, helper text, and secondary metadata |
| Charcoal | `#4d4d4d` | Secondary text |
| Obsidian | `#171717` | Primary text, filled buttons, and focus rings |

The original reference defines no error color. The error treatment in `globals.css` is a
demo extension. Color in the depth, alpha, and flow legends represents data.

## Tokens — Typography

Geist Sans carries interface text. Geist Mono carries identifiers, frame counters, and
metadata. `layout.tsx` loads both families and exposes their font variables.

### Geist Sans

Use normal tracking at body sizes and tight tracking for headings.
The CSS heading rule uses `-0.02em`. The demo uses compact text from 12 to 18px, with regular
body text and medium weight for headings and controls.

### Geist Mono

Use 12px text for metadata and counters. The reference's mono label treatment uses
`0.071em` tracking, as recorded by the `.label-mono` rule in `globals.css`.
Use tabular numbers for the frame counter so its width stays steady during playback.

## Tokens — Spacing & Shapes

The interface uses a compact spacing scale based on 4px increments.
Smaller control gaps use 6px, 8px, and 12px. The page uses 24px padding and gaps, while the
viewer uses 16px gaps. On wide screens, the parameter sidebar is 256px wide.

### Border Radius

Buttons, cards, inputs, and select triggers use a 6px radius.
The frontend maps both its medium and large radius tokens to 6px.
Slider tracks and thumbs use fully rounded shapes.

### Borders

Use 1px Hairline borders to separate controls, panes, and the header.
The reference's `.hairline` treatment combines an inset black ring at 8% opacity with an
outer ring in the canvas color. Depth comes from tonal contrast and borders.

## Components

### Filled Black Button

The Generate action uses an Obsidian fill with white text and a 6px radius.
Disabled controls reduce opacity. Keyboard focus remains visible through the focus ring.

### Outline and Ghost Buttons

Playback and Add pane use outline buttons. Pane actions and the sidebar toggle use ghost
buttons. Muted hover backgrounds show interaction without adding decorative color.

### Inputs, Selects, and Sliders

Parameter controls share compact sizing, Hairline borders, and visible focus rings.
Select menus use white popover surfaces. Sliders use monochrome tracks and thumbs.

### Video Panes

Each stream sits in a square white pane with a Hairline border and a 6px radius.
Its stream picker and pane actions sit above it. Data legends sit below it.
The panes share playback controls so viewers can compare the same frame across streams.

### Progress

Generation shows the current steps and their counts in compact text.
The depth sweep uses the data legend's colors while a sequence generates.
With reduced motion enabled, the sweep stops and uses a static half-opacity treatment.

## Layout

The header names the demo and reports the selected library.
A parameter sidebar sits beside the viewer on wide screens and above it on narrow screens.
The sidebar can collapse when it sits beside the panes.
The viewer arranges panes to fit the available space, and playback controls stay at the
bottom of the viewport.

## Do's and Don'ts

Keep interface text and surfaces on the monochrome scale.
Reserve color for data legends and the demo's error treatment.
Use Geist Sans for reading and Geist Mono for identifiers and counters.
Keep borders thin, corners compact, and keyboard focus visible.
