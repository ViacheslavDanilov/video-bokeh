# README video: storylines

Subject: Video Bokeh's web demo, which generates a synthetic sequence and shows its streams
side by side. Viewer: someone who opened the repository and wants to know, in about a
minute, what the dataset holds and what the demo does with it. One real sequence travels
through every option: the paper's night scene, seed 245 from the `da2-large` library at
1024 x 1024 with two objects. A woman with long white hair stands against fireworks over a
lake, in focus; a glowing lantern nearer the camera is blurred. Her hair gives the zoom its
fine detail. The sequence is generated on camera, so the progress bar is real.

## A. "One sequence, start to finish" (chosen)

- **Device and form:** one person's task, told as one continuous take inside the real app.
  Between chapters a full-frame white sheet whips in from the right with a headline of six
  words or fewer, and whips out to the left; inside a chapter the camera does the work.
- **What the viewer sees and feels:** the app doing real work. An estimator is picked from
  its list, a seed is typed, the bar fills, the panes swap to the new sequence, which plays
  and pauses where her hair moves. Three more panes are added there and one is dragged into
  place, then a double-click zooms all six panes in on the same strands of hair at once, and
  the slider steps through them frame by frame. The same sequence then loops at three bokeh
  strengths, and then as its six streams. It feels calm and exact.
- **First two seconds:** the poster: the aperture logo, "Video Bokeh" and "Synthetic video
  with exact depth, rendered bokeh and optical flow", finished at frame 0.
- **Beats:** poster, then "Pick an estimator and a seed": estimator list, seed, Generate,
  progress bar (sped up and labeled with its factor), three new panes, Play, Pause on frame
  71. "Every stream, side by side": Add pane three times to a 3 x 2 grid, Bokeh dragged
  next to All in focus. "Zoom in, frame by frame": double-click on the hair, slider dragged
  four frames, double-click back, Play. "One sequence. Any blur.": All in focus beside
  bokeh strengths 8, 16 and 32, looping. "One sequence. Every stream.": the six streams
  looping. End card: logo, the GitHub and Hugging Face addresses, held while the music
  fades.
- **Look:** the app's own: Inter, near-black ink, no accent color. The film's ground is
  white, one step lighter than the app's #fafafa, and pulled back the app sits on it with
  a 1 px border and a soft shadow. Pushed in, the app fills the frame.
- **Sound:** a light, steady bed of plucked guitar and marimba at 100 BPM, a soft click on
  every press of the mouse, a whoosh on every sheet, the music fading out under the end
  card.

**Why this one:** it keeps the intro and end card the owner likes and every beat of the
previous video, and adds the three new ones (panes added, zoom, scrub) without a caption
strip over the UI. A stranger can follow it without narration: one sequence, three short
headlines, and every frame of the UI is the running app.

## B. "The result first"

- **Device and form:** the payoff opens the film, then the camera pulls back to show where
  it came from.
- **What the viewer sees:** the six streams of one sequence fill the frame and play. The
  camera pulls back until they are panes in the app, and the film rewinds to show the seed
  being typed and the sequence being generated.
- **First two seconds:** the 3 x 2 grid of streams already playing.
- **Beats:** six streams, pull back into the app, rewind, estimator and seed, Generate,
  Add pane, zoom, end card.
- **Look and sound:** as A, with a rewind sound at the turn.
- **Not chosen because:** the owner asked to keep the intro, a poster with the name, and a
  result-first film shows the six streams twice. The rewind also has to fake the app
  running backwards, which the recording cannot do.

## C. "The hair, then everything"

- **Device and form:** an endless zoom in reverse. The film opens at 4x on one strand of
  hair in six panes and pulls out to the whole frame, then to the app, then to the poster.
- **What the viewer sees:** six views of the same few pixels, color, depth, mask, motion,
  blur and occlusion, before they know what any of them is.
- **First two seconds:** six square crops of the same hair, in six colorings.
- **Beats:** six crops, pull out to six panes, Play, out to the app, end card.
- **Look and sound:** as A, with the bed entering on the first pull-out.
- **Not chosen because:** it is the boldest picture, but a stranger cannot read the
  opening, and the generation, the Add pane clicks and the drag would have no place in it.

The chosen film borrows one thing from C: the zoom is the middle chapter's payoff, on all
six panes at once.

## Choices the brief left open

- **A small library.** The demo serves one background, the night lake, and seven
  foregrounds, the woman among them, copied from the lab's full library. The lab has them
  under `da2-large` only, so `da2-base`, `da2-small` and `depth-pro` are built from the
  same source images on a Mac; the estimator list then shows four entries, as the real app
  does with any directory of libraries. `README.md` says which ids come from where.
- **Size and objects.** 1024 x 1024 and two objects to two, set off camera before the film
  starts and left alone, so on camera only the estimator and the seed change. At 1024 px
  the 4x zoom shows the hair at better than one video pixel to a screen pixel.
- **Three panes to start.** The app opens a pane for every stream but Occlusion, so a
  first sequence shows five. Before the recording starts, off camera, the page is set to
  1024 x 1024 and two objects to two, and generates an earlier sequence from the same
  library with those settings (seed 6, `da2-base`: a falcon and a taxi over the same lake,
  without the woman, so the opener does not give her away). Its Alpha and Optical flow
  panes are closed. The app keeps a closed pane closed while the streams stay the same, so
  the new sequence opens in All in focus, Disparity and Bokeh, and "Add pane" brings back
  the other three in stream order. The film therefore opens on a sequence already on
  screen, with its header and the sidebar agreeing on two objects, and the progress bar
  runs in the line above its panes rather than on an empty page.
- **No empty panes.** The API encodes a stream's video the first time a pane asks for it,
  and a pane reads "Preparing video" until its video has a first frame. Once the new
  sequence is on screen, the recording asks the API for the three videos still to come,
  again and again until each answers at once, so they are on disk before their panes ask.
  Even so a new pane takes a few frames to show its first frame, and the new sequence's
  panes take longer. `record.cjs` puts a red square in the page's corner in every frame
  painted while a pane is empty, and `edit.py` leaves those frames out and holds the frame
  before them. In the film each added pane appears with its first frame, and the earlier
  sequence's panes give way straight to the new ones. The cursor holds still until every
  pane has shown a frame, so no frame left out hides a move of it: it would seem to jump.
  `edit.py` counts the moves that fall inside a span left out, and the count is 0.
- **Where to pause.** On frame 1 her hair has not moved yet: Optical flow is white and
  Occlusion black, which reads as broken. So the film plays the new sequence and pauses
  on frame 71, adds the panes there and zooms in there. The frame was picked by measuring
  the sequence inside the zoom window: on frames 70 to 74 the flow there is 10.6 to 17.6 px
  a frame, against 0 on frame 1, Occlusion covers 7 to 9% of it, and she keeps 88 to 99% of
  her all-in-focus detail in Bokeh. Earlier frames have less motion, and on frames 50 to 67
  the renderer leaves her partly out of focus.
- **Bokeh strengths.** The strengths scene shows the renderer's own output: the API
  generated the same seed, objects, size and frames at bokeh strengths 8 and 32 beside the
  film's 16. Measured against All in focus over the sequence, the background keeps 7%, 3%
  and 1% of its detail at 8, 16 and 32, the lantern 3%, 1% and 0.3%, and the woman 86%, 76%
  and 57% on average: she stays the sharpest thing in every tile, softest on frames 50 to
  67, as at strength 16.
- **Where the loops run.** The two loop scenes play frames 30 to 79 of the sequence, not
  all 80. Optical flow and Occlusion are nearly blank at the start, where nothing has
  moved yet (on frames 1 to 25 the flow tile is almost white, and the occlusion mask holds
  hairlines), and the last frame has neither, as it moves nowhere. From frame 30 the
  lantern's and the woman's flow and the mask's edges are plain to see. All eight loops
  share the range, so the tiles of a scene wrap together, and both scenes start on frame
  71, where the recording paused, one wrap hidden under each scene's entering sheet.
- **Where the take ends.** After the last Play the app runs to frame 80, which has no flow
  or occlusion, and wraps to frame 1, so its Optical flow pane goes white and its Occlusion
  pane black. That is 0.18 s after the press, and the film does not show it: the strengths
  sheet whips in over the take 0.2 s before the press is made, and has passed the Optical
  flow pane three frames before the wrap. The take's last beat is Play, without a pull
  back to the whole app.
- **The wait under the first sheet.** At 1024 px the API takes longer to encode those three
  videos than the first chapter sheet stays up. `edit.py` cuts the rest of that wait while
  the sheet covers the frame, so the cursor moves again as the sheet leaves.
- **The sped-up wait.** The wait runs from the click on Generate to the first frame in the
  last pane. `edit.py` speeds it up by a whole number, which the label on screen states. The
  label comes in once the camera has settled on the bar and leaves before the wait ends. For
  those few seconds the app's small step spinner turns next to the bar as it fills.
- **Headlines.** "Pick an estimator and a seed", "Every stream, side by side", "Zoom in,
  frame by frame", "One sequence. Any blur.", "One sequence. Every stream.": six words or
  fewer, centered, word by word.
- **Resolution.** A 3840 x 2160 master, delivered at 1920 x 1080: scaled down with
  Lanczos, the master keeps the UI text sharper than a 1080p render, and CRF 13 gives a file
  of about 30 MB.
