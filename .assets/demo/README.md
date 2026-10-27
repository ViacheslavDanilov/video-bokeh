# README demo video

`video-bokeh-demo.mp4` is the video the repository's README plays: 74.0 s, 1920 × 1080,
30 fps, with sound, encoded from a 3840 × 2160 master. `poster.png` is its first frame, a
finished title card, because GitHub shows a video's first frame until it plays. The README
links a copy uploaded to GitHub, so a new version needs a new upload too.

It shows the paper's night scene at 1024 × 1024: a woman with white hair against
fireworks over a lake, and a lantern nearer the camera. This folder tracks the scripts and
the project, and the sound, since no step makes it. The library, the recording, the loops
and the master are not tracked; the steps below remake them.

| Path | What it is |
|---|---|
| `record.cjs` | Records the demo in Chromium through a CDP screencast, with a drawn cursor |
| `edit.py` | Speeds up the generation wait, leaves out frames with an empty pane, and prints the step marks the composition is timed by |
| `stream_frames.py` | Writes the streams' frames for the loop scenes, colored the way the demo colors them |
| `STORYLINES.md` | The storylines considered, the one chosen, and the choices made along the way |
| `project/` | The [HyperFrames](https://github.com/heygen-com/hyperframes) project: HTML scenes rendered to video |
| `project/SPEC.md` | The film's look, motion and shots, in numbers |
| `project/assets/audio/` | The music bed, the click and the whooshes, with `CREDITS.md` |

## Scenes

| Time | Scene | Content |
|---|---|---|
| 0 to 5.5 s | `compositions/intro.html` | The poster, then the first chapter's line on the same sheet |
| 4.8 to 57.6 s | `compositions/demo.html` | The recording, with a camera and the speed label |
| 26.2 s, 42.0 s | `compositions/sheet-add.html`, `sheet-zoom.html` | Chapter sheets that whip across the recording |
| 57.1 to 63.1 s | `compositions/strengths.html` | The sequence at three bokeh strengths, looping beside All in focus |
| 62.5 to 69.0 s | `compositions/streams.html` | The six streams, looping: All in focus, Bokeh, Disparity, Alpha, Optical flow, Occlusion |
| 68.4 to 74.0 s | `compositions/end.html` | Logo, the GitHub and Hugging Face addresses |

The sheets sit over the recording while it waits, so the recording runs as one take under
them. `project/assets/` also keeps the shared style (`composition.css`), the logo, Inter
Variable with its license, and GSAP, so the render needs no network.

## The demo's library

The demo serves a small library of one background and seven foregrounds, from the lab's
full library, under four depth estimators. Its folder, `backend/data/library_demo/`, is
ignored like every library.

| Asset | Lab id |
|---|---|
| Background, the night lake with fireworks | `train__h_6dbbc3f6` |
| The woman with white hair | `8V__8V95zPFQAb` |
| Six more foregrounds: a bauble, a falcon, a taxi, a lantern, a helicopter, a porcupinefish | `1Z__1ZwVfuotr0`, `4u__4utFk5cf41`, `6J__6JwGEDXl0A`, `7M__7M7iteGLJW`, `8H__8Hq8GqfviD`, `Xe__Xe17RZvrgx` |

The lab's library has these assets under `da2-large` only, so the other three estimators
are built here from the same source images. From `backend/`, with the lab reachable as
`upf` (read only):

1. Copy the `da2-large` assets:

   ```bash
   LAB=upf:/mnt/storage/projects/upf/video-bokeh/backend/data
   mkdir -p data/library_demo/da2-large/foregrounds data/library_demo/da2-large/backgrounds
   for id in 1Z__1ZwVfuotr0 4u__4utFk5cf41 6J__6JwGEDXl0A 7M__7M7iteGLJW 8H__8Hq8GqfviD 8V__8V95zPFQAb Xe__Xe17RZvrgx; do
     scp -q -r $LAB/library/da2-large/foregrounds/$id data/library_demo/da2-large/foregrounds/
   done
   scp -q -r $LAB/library/da2-large/backgrounds/train__h_6dbbc3f6 data/library_demo/da2-large/backgrounds/
   ```

2. Copy their source images, the MAGICK cut-outs each foreground's `meta.json` names as
   `source_ref`, and the BG-20k photo:

   ```bash
   mkdir -p data/bg-20k_demo/images/train
   for ref in 1Z/1ZwVfuotr0 4u/4utFk5cf41 6J/6JwGEDXl0A 7M/7M7iteGLJW 8H/8Hq8GqfviD 8V/8V95zPFQAb Xe/Xe17RZvrgx; do
     mkdir -p data/magick_demo/images/$(dirname $ref)
     scp -q $LAB/magick/images/$ref.png data/magick_demo/images/$ref.png
   done
   scp -q $LAB/bg-20k/images/train/h_6dbbc3f6.jpg data/bg-20k_demo/images/train/
   ```

3. Build the other estimators, about a minute and a half in all on a Mac:

   ```bash
   for m in da2-base da2-small depth-pro; do
     VIDEO_BOKEH_RUNNER=local uv run --extra library python -m video_bokeh.library.build \
       --fg-data-root data/magick_demo --bg-data-root data/bg-20k_demo \
       --output data/library_demo/.$m --model $m && mv data/library_demo/.$m data/library_demo/$m
   done
   ```

## Make the video

The demo must run at `http://localhost:3000` on that library: `make api
LIBRARY=backend/data/library_demo` and `make web` from the repository root. The sequence
it generates must not be cached, or there is no progress bar to film: find its folder with
`grep -l '"seed": 245,' backend/data/sequences/*/sequence.json` and delete it.

1. Record. From this folder:

   ```bash
   node record.cjs 245 frames
   ```

   The window is 1920 × 1080 CSS px on a 2× screen, so the frames are 3840 × 2160 and the
   app fills them. Off camera the script sets the size to 1024 × 1024 and the objects to 2
   to 2, and shows seed 6 from the first library, `da2-base`: a falcon and a taxi over the
   same lake, without the woman. It closes that sequence's Alpha and Optical flow panes,
   so the new sequence opens in three panes. On camera it picks `da2-large`, types the
   seed and generates. It plays the new sequence and pauses on frame 71 (`PAUSE_AT`), adds
   three panes there, drags Bokeh next to All in focus, zooms in on her hair, drags the
   position slider four frames, zooms back out and plays. It marks every step and every
   press in `frames/frames.json`. While any pane has no frame to show yet, a red square
   sits in the page's top left corner, and the cursor holds still until every pane has
   shown a frame. Another seed needs its own `PAUSE_AT`, zoom point (`HAIR`) and count of
   objects (`OBJECTS`): pick the frame where Optical flow and Occlusion show her hair and
   she is in focus in Bokeh. Its `SETUP_SEED` must name a sequence of the same size and
   objects that does not show her.

2. Edit. `python3 edit.py frames` leaves out every frame with the red square and holds the
   frame before it instead, so no empty pane reaches the film. Under the first chapter
   sheet the recording waits for the API to encode the streams still to be added, which at
   1024 px outlasts the sheet; the edit cuts that wait while the sheet covers the frame. It
   prints the frames it left out, how many moves of the cursor fall inside them (it must
   be 0), the cut, the generation's speed-up factor, every step mark and press in the
   edit's time and the film's, and an ffmpeg command that writes
   `project/assets/ui-edit.mp4`. Run that command.

3. Time the composition from what `edit.py` printed. `index.html` takes film times, the
   last column; `compositions/demo.html` takes edit times, the column before it.

   | Where | Value |
   |---|---|
   | `#sheet-add` and `#sheet-zoom` in `index.html` | `data-start`: the film times of `chapter2` and `chapter3` |
   | `#strengths` | `data-start`: the film time of `play` minus 0.2 |
   | `#streams` | `data-start`: `#strengths` plus 5.4 |
   | `#end` | `data-start`: `#streams` plus 5.9; the root's `data-duration`: that plus 5.6; the music's 0.4 s less, or its 80 s if shorter |
   | `#demo` and its video | `data-duration`: from 4.8 to 0.5 s after `#strengths` starts |
   | `#dm-speed` in `demo.html` | the factor; shown at `generate` + 1.2, once the camera has settled on the progress line, and faded out from 0.45 s before the sped-up span ends |
   | the camera in `demo.html` | `estimator` - 0.25, `toGenerate` - 0.18, `generate` + 0.2, `panes` + 0.13, `add2` + 0.1 |
   | `#click-1` to `#click-16` | each press 0.04 s early, so the click peaks a frame after it; the second of a double-click on track 13 |
   | `#whoosh-1` to `#whoosh-8` | each whip: the intro's exit at 5.0 s, each chapter sheet's start and its exit 2.15 s later, the starts of `#strengths`, `#streams` and `#end`; plus 0.096 s for `whoosh-a`, 0.065 s for `whoosh-b` |

   The recording keeps playing after `play`, and the app wraps from frame 80, which has
   no flow or occlusion, to frame 1, so its Optical flow and Occlusion panes go white and
   black 0.18 s after the press. The film must not show that. The strengths sheet starts
   0.2 s before `play`, so that three frames before the wrap its left edge, 0.28 s in, is
   already past the Optical flow pane, and the wrap lies under the sheet. If the wrap moves,
   find its first frame in `project/assets/ui-edit.mp4`, where the Optical flow pane goes
   white, and start the sheet 0.38 s before it.

4. Stream frames. The strengths scene needs the same sequence's bokeh at strengths 8 and
   32 as well, which the API renders as two more sequences of their own: same seed,
   objects, size and frames. With the API running, from anywhere:

   ```bash
   LIB=$(curl -s 127.0.0.1:8000/libraries | python3 -c "import json,sys; print(next(l['id'] for l in json.load(sys.stdin) if l['name'] == 'da2-large'))")
   for k in 8 32; do
     curl -s -X POST 127.0.0.1:8000/sequences -H 'content-type: application/json' -H 'accept: application/json' \
       -d "{\"library\": \"$LIB\", \"seed\": 245, \"frames\": 80, \"size\": 1024, \"n_objects_min\": 2, \"n_objects_max\": 2, \"bokeh_strength\": $k}" \
       | python3 -c "import json,sys; print(json.load(sys.stdin)['id'])"
   done
   ```

   It prints each sequence's id; each takes about a minute. Then from `backend/`, with the
   recorded sequence, which `frames/frames.json` names, and the two just made:

   ```bash
   uv run python ../.assets/demo/stream_frames.py data/sequences/<id> ../.assets/demo/streams
   uv run python ../.assets/demo/stream_frames.py data/sequences/<id of 8> ../.assets/demo/streams/strength-8 bokeh
   uv run python ../.assets/demo/stream_frames.py data/sequences/<id of 32> ../.assets/demo/streams/strength-32 bokeh
   ```

   Each frame is 688 px, a 344 CSS px tile at 2×.

5. Stream loops. Optical flow and Occlusion are nearly blank at the start of the
   sequence and have no last frame, so the loops play frames 30 to 79, 50 frames, not all
   80: from frame 30 their tiles are plain to see. Each stream's 50 frames at 24 fps
   become one 1.875 s cycle at 30 fps, played five and a third times: 300 frames, 10 s.
   Both loop scenes start them 1.54 s in, on frame 71, where the recording paused. From
   this folder, for each `NAME` of `all_in_focus`, `alpha`, `disparity`, `bokeh`, `flow`
   and `occlusion`:

   ```bash
   mkdir -p project/assets/readme-loops
   ffmpeg -y -framerate 24 -start_number 30 -i streams/NAME/%03d.png \
     -vf 'trim=end_frame=50,settb=AVTB,setpts=N/(24*TB),loop=loop=5:size=50:start=0,setpts=0.9*N/(24*TB),fps=30,format=yuv420p' \
     -frames:v 300 -an -c:v libx264 -preset slow -crf 10 \
     -movflags +faststart project/assets/readme-loops/NAME.mp4
   ```

   and the same command with `-i streams/strength-K/bokeh/%03d.png` and
   `project/assets/readme-loops/bokeh-K.mp4` for each `K` of 8 and 32.

6. Check and render a master. From `project/`:

   ```bash
   HYPERFRAMES_SKIP_SKILLS=1 DO_NOT_TRACK=1 npx hyperframes@0.8.206 check
   HYPERFRAMES_SKIP_SKILLS=1 DO_NOT_TRACK=1 npx hyperframes@0.8.206 render \
     --resolution 4k --crf 10 --video-frame-format jpg --frames-cache-dir off -o ../master.mp4
   ```

   `--frames-cache-dir off` keeps the 4K frames it extracts from piling up in the system's
   temporary folder.

7. Encode at 1920 × 1080. From this folder:

   ```bash
   ffmpeg -y -i master.mp4 -vf 'scale=1920:1080:flags=lanczos' -c:v libx264 -preset veryslow \
     -crf 13 -profile:v high -level:v 4.1 -pix_fmt yuv420p -force_key_frames 69.99 \
     -c:a aac -b:a 192k -movflags +faststart video-bokeh-demo.mp4
   ```

   The 4K master, scaled down with Lanczos, keeps the UI text sharper than a render at
   1080p would. CRF 13 makes a file of about 30 MB. `-force_key_frames 69.99` puts a
   keyframe just after the end card has settled, 1.6 s after `#end` starts, so none falls
   inside its hold, where it would show as a jump in quality.

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
