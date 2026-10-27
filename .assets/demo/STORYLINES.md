# README video: storylines

Subject: Video Bokeh's web demo, which generates a synthetic sequence and shows its streams
side by side. Viewer: someone who opened the repository and wants to know, in about a
minute, what the dataset holds and what the demo does with it. One real sequence travels
through every option: seed 512 from the `da2-large` library, three objects, one of them a
portrait whose long hair gives the zoom its fine detail. It is generated on camera, so the
progress bar is real.

## A. "One sequence, start to finish" (chosen)

- **Device and form:** one person's task, told as one continuous take inside the real app.
  Between chapters a full-frame white sheet whips in from the right with a headline of six
  words or fewer, and whips out to the left; inside a chapter the camera does the work.
- **What the viewer sees and feels:** the app doing real work. An estimator is picked from
  its list, a seed is typed, the bar fills, the panes swap to the new sequence. Three more
  panes are added and one is dragged into place, then a double-click zooms all six panes in
  on the same hair at once, and the slider steps through it frame by frame. It feels calm
  and exact.
- **First two seconds:** the poster: the aperture logo, "Video Bokeh" and "Synthetic video
  with exact depth, rendered bokeh and optical flow", finished at frame 0.
- **Beats:** poster, then "Pick an estimator and a seed": estimator list, seed, Generate,
  progress bar (sped up and labeled with its factor), three new panes. "Every stream, side
  by side": Add pane three times to a 3 x 2 grid, Bokeh dragged next to All in focus.
  "Zoom in, frame by frame": double-click on the hair, slider dragged ten frames,
  double-click back, Play. "One sequence. Every stream.": the six streams looping. End
  card: logo, the GitHub and Hugging Face addresses, held while the music fades.
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

- **Three panes to start.** The app opens a pane for every stream but Occlusion, so a first
  sequence shows five. Before the recording starts, off camera, the page generates an
  earlier sequence (seed 101, `da2-base`) and its Alpha and Optical flow panes are closed.
  The app keeps a closed pane closed while the streams stay the same, so the new sequence
  opens in All in focus, Disparity and Bokeh, and "Add pane" brings back the other three in
  stream order. The film therefore opens on a sequence already on screen, and the progress
  bar runs in the line above its panes rather than on an empty page.
- **No empty panes.** The API encodes a stream's video the first time a pane asks for it,
  and a pane reads "Preparing video" until its video has a first frame. Once the new
  sequence is on screen, the recording asks the API for the three videos still to come,
  again and again until each answers at once, so they are on disk before their panes ask.
  Even so a new pane takes a few frames to show its first frame, and the new sequence's
  panes take longer. `record.cjs` puts a red square in the page's corner in every frame
  painted while a pane is empty, and `edit.py` leaves those frames out and holds the frame
  before them. In the film each added pane appears with its first frame, and the earlier
  sequence's panes give way straight to the new ones.
- **The sped-up wait.** The wait runs from the click on Generate to the first frame in the
  last pane. `edit.py` speeds it up by a whole number, which the label on screen states. The
  label comes in once the camera has settled on the bar and leaves before the wait ends. For
  those few seconds the app's small step spinner turns next to the bar as it fills.
- **Headlines.** "Pick an estimator and a seed", "Every stream, side by side", "Zoom in,
  frame by frame", "One sequence. Every stream.": six words or fewer, centered, word by word.
- **Resolution.** 3840 x 2160: at CRF 28 the video and its sound fit under GitHub's 10 MB
  limit, and a 1:1 crop shows the UI text as clean as in the master.
