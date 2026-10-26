# README demo video

`video-bokeh-demo.mp4` is the video the repository's README plays: 46.3 s, 3840 × 2160, 30 fps,
no audio. The README links a copy uploaded to GitHub, so a new version needs a new upload too.

Everything that makes the video is here. The heavy media it is built from, the screen
recording and the stream loops, is not tracked: the steps below make it again from the
running demo.

| Path | What it is |
|---|---|
| `record.cjs` | Records the demo in Chromium through a CDP screencast, with a drawn cursor |
| `edit.py` | Speeds up the generation wait and prints the ffmpeg command for `ui-edit.mp4` |
| `stream_frames.py` | Writes the streams scene's frames, colored the way the demo colors them |
| `project/` | The [HyperFrames](https://github.com/heygen-com/hyperframes) project: HTML scenes rendered to video |

## Scenes

| Time | Scene | Content |
|---|---|---|
| 0 to 3 s | `compositions/intro.html` | Logo and title |
| 3 to 37.3 s | `compositions/demo.html` | The recording in a browser frame, with numbered step captions and a "4× speed" badge |
| 37.3 to 43.3 s | `compositions/streams.html` | Four streams side by side: All in focus, Bokeh, Disparity, Optical flow |
| 43.3 to 46.3 s | `compositions/end.html` | Logo and the repository URL |

The caption, badge and camera times in `demo.html` come from the step marks `edit.py` prints.
A new recording moves them, so set them again from its output.
The scene lengths are in `index.html` and in each scene's `data-duration`.

`project/assets/` keeps the shared style (`composition.css`), the logo, Inter Variable with its
license, and GSAP, so the render needs no network.

## Make the video

The demo must run at `http://localhost:3000` (`make web` from the repository root), and the
sequence it generates must not be cached, or there is no progress bar to film.

1. Record. From this folder:

   ```bash
   node record.cjs 2031 frames
   ```

   The window is 1800 × 837 CSS px on a 2× screen, so all five panes sit in one row and the
   frames are 3600 × 1674. The script picks `da2-large`, types the seed, generates, plays, and
   drags two panes. It marks every step in `frames/frames.json`.

2. Edit. `python3 edit.py frames` prints the step times and an ffmpeg command. Run that
   command, then move the result and take its last frame:

   ```bash
   mv frames/ui-edit.mp4 project/assets/ui-edit.mp4
   ffmpeg -sseof -1 -i project/assets/ui-edit.mp4 -update 1 project/assets/ui-last-frame.png
   ```

3. Stream frames. From `backend/`, with the sequence the recording generated:

   ```bash
   uv run python ../.assets/demo/stream_frames.py data/sequences/<id> ../.assets/demo/streams
   ```

   Each frame is 824 px, a 412 CSS px tile at 2×.

4. Stream loops. Each stream's 80 frames at 24 fps become one 3 s cycle at 30 fps, played
   twice: 180 frames, 6 s. From this folder, for each of `all_in_focus`, `bokeh`,
   `disparity` and `flow`:

   ```bash
   mkdir -p project/assets/readme-loops
   ffmpeg -framerate 24 -i streams/NAME/%03d.png \
     -vf 'settb=AVTB,setpts=0.9*(PTS-STARTPTS),fps=30,loop=loop=1:size=90:start=0,setpts=N/(30*TB),format=yuv420p' \
     -frames:v 180 -an -c:v libx264 -preset slow -crf 10 \
     -movflags +faststart project/assets/readme-loops/NAME.mp4
   ```

5. Render a master and encode it. From `project/`:

   ```bash
   HYPERFRAMES_SKIP_SKILLS=1 DO_NOT_TRACK=1 npx hyperframes@0.8.149 render \
     --resolution 4k --crf 10 --video-frame-format png -o ../master.mp4
   cd .. && ffmpeg -i master.mp4 -c:v libx264 -preset veryslow -crf 25 -profile:v high \
     -level:v 5.1 -refs 4 -pix_fmt yuv420p -movflags +faststart -an video-bokeh-demo.mp4
   ```

   CRF 25 keeps the file under GitHub's 10 MB limit for a video in a README.
   `-level:v 5.1 -refs 4` matter: without them x264 picks level 6.0 with 16 reference
   frames, and the Mac hardware decoder stops partway through the video.

6. Upload. Drag `video-bokeh-demo.mp4` into a GitHub comment box, and put the link it gives
   in place of the `user-attachments` link in the root README.

`npx hyperframes@0.8.149 preview` from `project/` opens the composition in a browser for
checking timing before a render.
