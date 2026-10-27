# Sound credits

Every sound in the video, where it came from, and the license it is used under.

| File | Source | License |
|---|---|---|
| `music.mp3` | Generated with Google Lyria RealTime (`models/lyria-realtime-exp`) through the Gemini API | [Gemini API Additional Terms of Service](https://ai.google.dev/gemini-api/terms) |
| `click.mp3` | `click-soft.mp3` from the HyperFrames sound-effect bundle | [Pixabay Content License](https://pixabay.com/service/license-summary/) |
| `whoosh-a.mp3` | `whoosh.mp3` from the HyperFrames sound-effect bundle | [Pixabay Content License](https://pixabay.com/service/license-summary/) |
| `whoosh-b.mp3` | `whoosh-a.mp3` pitched down about three semitones | [Pixabay Content License](https://pixabay.com/service/license-summary/) |

## Music

The terms say Google does not claim ownership of generated content, and that Google may
generate the same or similar content for others. Use stays subject to those terms and to
Google's Generative AI Prohibited Use Policy.

The bed was generated from this prompt, at 100 BPM, brightness 0.65, density 0.45, in a
major scale:

> Light acoustic electronic bed, plucked guitar and marimba motif, soft synth pads, subtle
> kick and shaker, curious and focused, clean modern production, instrumental

The negative prompt was "vocals, heavy drums, distortion, dramatic strings". The bed was
then:

1. trimmed to 74 s, starting 1 s in, and lengthened to 80 s: a copy of its seconds 25 to 40
   crossfades onto its end over 3 s, at constant power;
2. low-passed at 12 kHz, since the generated audio had noise above that, and cut 4 dB below
   110 Hz with a low shelf;
3. brought to -16 LUFS with a limiter, true peak -2.0 dBTP;
4. encoded as MP3 at 128 kbit/s.

## Sound effects

The click and the whoosh come from the sound-effect bundle of HyperFrames' `media-use`
skill (`audio/assets/sfx`). The bundle credits all its sounds to
[Pixabay](https://pixabay.com/sound-effects/) under the Pixabay Content License, but
neither the bundle nor the files name the Pixabay page or the author of each sound, so they
cannot be traced further.

The license allows use without attribution and allows modifying the content, which is how
`whoosh-b.mp3` was made. It does not allow distributing the content on a standalone basis.
These files are here only as parts of this video's project.
