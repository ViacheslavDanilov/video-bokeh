# SPEC: README video

```text
GOAL:    a visitor to the repository finishes the film knowing the demo generates one
         sequence and shows its six streams side by side, frame-accurate, down to a single
         strand of hair.
OUTPUT:  HyperFrames, 1920 x 1080 at 30 fps, rendered at 2x (3840 x 2160); H.264 High,
         yuv420p, AAC.
TIME:    67.33 s x 30 = 2020 frames. Music bed at 100 BPM.
LOOK:    ground #ffffff; ink #171717; secondary #666666; lines #e5e5e5. No accent color.
         Inter (assets/fonts): titles 600 at 104-116 px, tracking -0.04 to -0.055 em;
         the streams heading 600 at 64 px; subtitle 400 at 46 px; stream labels 500 at
         32 px; the speed label 600 at 32 px; end card links 42 px.
         The app is the screen recording, 1920 x 1080 CSS px at 2x. Pulled back it sits at
         scale 0.94 on the white ground: 14 px radius, a 1 px #dedede ring, shadows
         0 4px 12px and 0 30px 80px of #171717 at 6% and 12%. Pushed in, scale 1.17 to 2.4,
         it fills the frame.
OBJECTS: the drawn cursor: a black arrow with a white 1.5 px edge, 36 CSS px, dipping to
         0.84 on each press. No ring on a click.
MOTION:  camera moves 1.0 s power2.inOut (0.9 s onto the progress line), one at a time,
         never across a click; 2D transforms only.
         sheet: full-frame #ffffff, in from x 2050 and out to x -2050, 0.45 s power3.inOut,
         blur 10 px at its fastest. Chapters change this way, and the streams scene and
         the end card enter this way.
         headline words: opacity 0 to 1 and blur 8 to 0 px, 0.16 s each, 0.08 s apart, no
         move; landed lines hold still.
         poster lines leave rising 28 px with blur 8 px, 0.3 s power2.in; the end card's
         lines rise 28 px into place, 0.55 s power3.out, title first, then each link.
SHOTS (film seconds):
  0.0-2.4     poster, finished at frame 0: logo, "Video Bokeh", subtitle.
  2.4-5.45    poster lines rise out; "Pick an estimator and a seed" lands; the sheet whips
              out onto the app at 0.94.
  5.55-21.3   sidebar at 2.0x: estimator list, da2-large, seed typed; down to Generate;
              onto the progress line at 2.4x, the speed label once the camera settles;
              the three new panes in one row at 1.17x.
  21.3-23.9   sheet "Every stream, side by side".
  23.9-36.9   the row at 1.17x: Add pane twice; then both rows and the transport at
              1.175x: the third Add pane, Bokeh dragged in front of Disparity.
  36.9-39.5   sheet "Zoom in, frame by frame".
  39.5-55.8   same framing: double-click on the hair (4x in all six panes), slider dragged
              ten frames, double-click back, Play; pull back to 0.94.
  55.8-61.7   sheet "One sequence. Every stream.": six loops in a 3 x 2 grid, labeled.
  61.7-67.33  end card: logo and title, "Code" and "Dataset" links; music fades out from
              64.1 s, silence from 66.9 s.
SOUND:   bed at -16 LUFS, true peak -2.8 dBTP, low-passed at 12 kHz; a soft click one frame
         after each press; a whoosh peaking one frame after each sheet's fastest frame,
         two takes alternating.
BANNED:  a caption strip over the UI; browser chrome; click rings; a gray or dark void
         around a small window; text under 28 px of our own; a spinner without progress
         held over 1 s; a sped-up wait whose bar fills without its factor on screen; the logo docked
         in a corner.
QA:      frames every 2 s and around every seam; text and links unclipped; the speed label
         matches edit.py's factor; audio -16 LUFS, true peak at most -1 dBTP; the mp4 under
         10 MB and decoded in full by VideoToolbox.
```
