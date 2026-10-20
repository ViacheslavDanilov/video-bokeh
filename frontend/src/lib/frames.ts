/**
 * A video's frames, decoded once into memory, so that scrubbing draws a frame rather than
 * seeks to one.
 *
 * A seek has to decode from the last keyframe, and the API's videos have one, at the start:
 * six panes seeking together took 22 to 69 ms a step, which a drag shows as lag. Drawing
 * a decoded frame takes well under a millisecond.
 *
 * The frames are kept at the size the pane is shown, in CSS pixels, not the video's,
 * because memory grows with the pixels: 80 frames of 1024 px are 320 MiB a pane. Six panes
 * of 1024 px video on a 1920 px screen measured 637 MiB at a device pixel ratio of 2 and
 * 159 MiB in CSS pixels. A drag shows the frames that much softer on a high-density
 * screen; let go, the video is back at its own resolution.
 */

/** The time inside frame `index`, halfway, which no rounding moves into a neighbor. */
export function frameTime(index: number, frames: number, duration: number) {
  return ((index + 0.5) / frames) * duration;
}

/**
 * Decode `frames` frames of `src`, each scaled to `width` pixels square at most, into
 * `into`, in order, as each is ready, so the first ones can be drawn before the last are
 * decoded. Stops at `signal`, closing what it decoded. A video that fails stops it too.
 */
export async function decodeFrames(
  src: string,
  frames: number,
  width: number,
  into: ImageBitmap[],
  signal: AbortSignal,
  onFrame: () => void,
): Promise<void> {
  // A video of its own, out of the page, so decoding moves no pane.
  const video = document.createElement("video");
  video.muted = true;
  video.preload = "auto";
  // No CORS: the panes' own requests carry none, and a CORS request answered from their
  // cached response fails. A canvas only ever draws these frames, never reads them back.
  const event = (name: string) =>
    new Promise<boolean>((resolve) => {
      const done = (ok: boolean) => {
        video.removeEventListener(name, onEvent);
        video.removeEventListener("error", onError);
        signal.removeEventListener("abort", onError);
        resolve(ok);
      };
      const onEvent = () => done(true);
      const onError = () => done(false);
      video.addEventListener(name, onEvent);
      video.addEventListener("error", onError);
      signal.addEventListener("abort", onError);
    });
  try {
    const loaded = event("loadeddata");
    video.src = src;
    if (!(await loaded)) return;
    const scale = Math.min(1, width / video.videoWidth);
    const size = {
      resizeWidth: Math.max(1, Math.round(video.videoWidth * scale)),
      resizeHeight: Math.max(1, Math.round(video.videoHeight * scale)),
      resizeQuality: "high" as const,
    };
    for (let index = 0; index < frames; index++) {
      const seeked = event("seeked");
      video.currentTime = frameTime(index, frames, video.duration);
      if (!(await seeked)) return;
      const bitmap = await createImageBitmap(video, size);
      if (signal.aborted) {
        bitmap.close();
        return;
      }
      into.push(bitmap);
      onFrame();
    }
  } finally {
    if (signal.aborted) into.splice(0).forEach((bitmap) => bitmap.close());
    // Lets the browser drop the decoder and the file.
    video.removeAttribute("src");
    video.load();
  }
}
