# Product

<!-- impeccable:product-schema 1 -->

## Platform

web

## Users

- **Researchers who train on the dataset**, first of all Pablo Arias and Valery Dewil. They
  open the demo to see what a sequence holds and to compare its streams frame by frame.
- **The paper's reviewers and readers**, who open the demo to check what the paper claims:
  exact alpha, disparity, optical flow, occlusion and bokeh on one sequence.
- **Viacheslav**, who uses it to inspect generated sequences and to record the demo video.

All of them know what a matte, a disparity map and optical flow are. None needs onboarding.

## Product Purpose

A local web demo of the Video Bokeh pipeline. It generates one sequence from a seed and shows
its streams side by side, in step, so a person can judge them against each other. It is a
viewer for a dataset, not a product with accounts, and it does not edit anything.

Success is a researcher who sees a stream is wrong, or right, within seconds of generating the
sequence.

## Positioning

The streams are the content. The interface stays out of their way: light and monochrome, so
the video carries the color, as `DESIGN.md` says.

## Operating Context

- Runs on a laptop or a lab machine against a local FastAPI backend, on a screen from a phone
  to a wide monitor, with up to six panes.
- Panes play in lockstep and can be reordered, so a control must never move a frame.
- A sequence is generated per request and cached, so generation time is part of the experience.

## Capabilities and Constraints

- Next.js 16 and React 19, Tailwind 4, shadcn/ui copied into `frontend/src/components/ui/`.
- Light theme only. Fonts and tokens are in `DESIGN.md`.
- Stream names and what they mean come from the backend's `StreamInfo`, so the page adds no
  stream of its own.

## Product Principles

1. The frames come first. Controls are small, quiet and stay out of the picture.
2. Every pane answers its own question, and a control that changes what a pane shows sits
   with that pane.
3. The default shows the most informative view. A mask drawn over the frame says more than the
   mask alone.
4. The same control looks and behaves the same in every pane.
5. Real data only. The page never invents a number, a stream or a result.
