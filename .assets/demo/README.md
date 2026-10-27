# README demo video

`video-bokeh-demo.mp4` is the video the repository's README plays: 67.3 s, 3840 × 2160,
30 fps, with sound. `poster.png` is its first frame, a finished title card, because GitHub
shows a video's first frame until it plays. The README links a copy uploaded to GitHub, so
a new version needs a new upload too.

Everything that makes the video is here. The heavy media it is built from, the screen
recording, the stream loops and the master render, is not tracked: the steps below make it
again from the running demo. The sound is tracked, since nothing makes it again.

| Path | What it is |
|---|---|
| `record.cjs` | Records the demo in Chromium through a CDP screencast, with a drawn cursor |
| `edit.py` | Speeds up the generation wait and prints the step marks the composition is timed by |
| `stream_frames.py` | Writes the six streams' frames, colored the way the demo colors them |
| `STORYLINES.md` | The storylines considered, the one chosen, and the choices made along the way |
| `project/` | The [HyperFrames](https://github.com/heygen-com/hyperframes) project: HTML scenes rendered to video |
| `project/SPEC.md` | The film's look, motion and shots, in numbers |
| `project/assets/audio/` | The music bed, the click and the whooshes, with `CREDITS.md` |

## Scenes

| Time | Scene | Content |
|---|---|---|
| 0 to 5.5 s | `compositions/intro.html` | The poster, then the first chapter's line on the same sheet |
| 4.8 to 56.3 s | `compositions/demo.html` | The recording, with a camera and the speed label |
| 21.3 s, 36.9 s | `compositions/sheet-add.html`, `sheet-zoom.html` | Chapter sheets that whip across the recording |
| 55.8 to 62.3 s | `compositions/streams.html` | The six streams, looping: All in focus, Bokeh, Disparity, Alpha, Optical flow, Occlusion |
| 61.7 to 67.3 s | `compositions/end.html` | Logo, the GitHub and Hugging Face addresses |

The sheets sit over the recording while it waits, so the recording runs as one take under
them. `project/assets/` also keeps the shared style (`composition.css`), the logo, Inter
Variable with its license, and GSAP, so the render needs no network.

## Make the video

The demo must run at `http://localhost:3000`: `make api` and `make web` from the repository
root. The sequence it generates must not be cached, or there is no progress bar to film:
find its folder with `grep -l '"seed": 512,' backend/data/sequences/*/sequence.json` and
delete it, or pick a new seed. A new seed needs a new zoom point, `HAIR` in `record.cjs`.

1. Record. From this folder:

   ```bash
   node record.cjs 512 frames
   ```

   The window is 1920 × 1080 CSS px on a 2× screen, so the frames are 3840 × 2160 and the
   app fills them. Off camera the script first shows seed 101 from the first library with
   its Alpha and Optical flow panes closed, so the new sequence opens in three panes. On
   camera it picks `da2-large`, types the seed, generates, adds three panes, drags Bokeh
   next to All in focus, zooms in on the hair, drags the position slider ten frames, zooms
   back out and plays. It marks every step and every press in `frames/frames.json`. While
   any pane has no frame to show yet, a red square sits in the page's top left corner.

2. Edit. `python3 edit.py frames` leaves out every frame with the red square and holds the
   frame before it instead, so no empty pane reaches the film. It prints the frames it left
   out, the generation's speed-up factor, every step mark and press in the edit's time and
   the film's, and an ffmpeg command that writes `project/assets/ui-edit.mp4`. Run that
   command.

3. Time the composition from what `edit.py` printed. `index.html` takes film times, the
   last column; `compositions/demo.html` takes edit times, the column before it.

   | Where | Value |
   |---|---|
   | `#sheet-add` and `#sheet-zoom` in `index.html` | `data-start`: the film times of `chapter2` and `chapter3` |
   | `#streams` | `data-start`: the film time of `play` plus 2.45 |
   | `#end` | `data-start`: `#streams` plus 5.9; the root's `data-duration`: that plus 5.6, and the music's 0.4 less |
   | `#demo` and its video | `data-duration`: from 4.8 to 0.5 s after `#streams` starts |
   | `#dm-speed` in `demo.html` | the factor; shown at `generate` + 1.2, once the camera has settled on the progress line, and faded out from 0.45 s before the sped-up span ends |
   | the camera in `demo.html` | `estimator` - 0.25, `toGenerate` - 0.18, `generate` + 0.2, `panes` + 0.13, `add2` + 0.1, `play` + 0.3 |
   | `#click-1` to `#click-14` | each press 0.04 s early, so the click peaks a frame after it; the second of a double-click on track 13 |
   | `#whoosh-1` to `#whoosh-7` | each whip: the intro's exit at 5.0 s, each chapter sheet's start and its exit 2.15 s later, the starts of `#streams` and `#end`; plus 0.096 s for `whoosh-a`, 0.065 s for `whoosh-b` |

4. Stream frames. From `backend/`, with the sequence the recording generated, which
   `frames/frames.json` names:

   ```bash
   uv run python ../.assets/demo/stream_frames.py data/sequences/<id> ../.assets/demo/streams
   ```

   Each frame is 688 px, a 344 CSS px tile at 2×.

5. Stream loops. Each stream's 80 frames at 24 fps become one 3 s cycle at 30 fps, played
   about two and a third times: 210 frames, 7 s. From this folder, for each of
   `all_in_focus`, `alpha`, `disparity`, `bokeh`, `flow` and `occlusion`:

   ```bash
   mkdir -p project/assets/readme-loops
   ffmpeg -framerate 24 -i streams/NAME/%03d.png \
     -vf 'settb=AVTB,setpts=0.9*(PTS-STARTPTS),fps=30,loop=loop=2:size=90:start=0,setpts=N/(30*TB),format=yuv420p' \
     -frames:v 210 -an -c:v libx264 -preset slow -crf 10 \
     -movflags +faststart project/assets/readme-loops/NAME.mp4
   ```

6. Check and render a master. From `project/`:

   ```bash
   HYPERFRAMES_SKIP_SKILLS=1 DO_NOT_TRACK=1 npx hyperframes@0.8.206 check
   HYPERFRAMES_SKIP_SKILLS=1 DO_NOT_TRACK=1 npx hyperframes@0.8.206 render \
     --resolution 4k --crf 10 --video-frame-format jpg --frames-cache-dir off -o ../master.mp4
   ```

   `--frames-cache-dir off` keeps the 4K frames it extracts from piling up in the system's
   temporary folder.

7. Encode. From this folder:

   ```bash
   ffmpeg -i master.mp4 -c:v libx264 -preset veryslow -crf 28 -profile:v high \
     -level:v 5.1 -refs 4 -pix_fmt yuv420p -force_key_frames 63.3 \
     -c:a aac -b:a 128k -movflags +faststart video-bokeh-demo.mp4
   ```

   CRF 28 keeps the file, sound included, under GitHub's 10 MB limit for a video in a
   README. `-level:v 5.1 -refs 4` matter: without them x264 picks level 6.0 with 16
   reference frames, and the Mac hardware decoder stops partway through the video.
   `-force_key_frames 63.3` puts a keyframe just after the end card has settled, 1.6 s after
   `#end` starts, so none falls inside its hold, where it would show as a jump in quality.

8. Poster. From `project/`:

   ```bash
   HYPERFRAMES_SKIP_SKILLS=1 DO_NOT_TRACK=1 npx hyperframes@0.8.206 snapshot \
     --at 0 --zoom 0,0,1920,1080 --zoom-scale 2 --no-end -o .hyperframes/poster
   cp .hyperframes/poster/frame-00-at-0s.png ../poster.png
   ```

9. Check the file decodes in full on the Mac's hardware decoder:

   ```bash
   ffmpeg -hwaccel videotoolbox -i video-bokeh-demo.mp4 -f null -
   ```

10. Upload. Drag `video-bokeh-demo.mp4` into a GitHub comment box, and put the link it gives
    in place of the `user-attachments` link in the root README.

`npx hyperframes@0.8.206 preview` from `project/` opens the composition in a browser for
checking timing before a render.
