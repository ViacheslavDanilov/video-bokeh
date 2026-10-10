---
type: topic
status: active
tags: [topic, bokeh, bokeh-renderer, layers]
related: [pipeline-explainer, dataset-layout, loader]
---

# How the layer-wise bokeh renderer works

Our layer-wise renderer blurs each layer of a frame on its own, by how far it is from the
focus, and then stacks the blurred layers back together. It is a classical algorithm in
PyTorch, under 300 lines, and it runs on a CPU, an NVIDIA card or a Mac's GPU.

- **Decision, 2026-10-09:** this renderer is to replace any-to-bokeh as the source of the
  dataset's bokeh. any-to-bokeh stays as a baseline. It follows the 2026-10-08 sync.

This page explains the method. [[0002-layers-are-stored-not-regenerated]] explains where its
layers come from.

---

## Why layers

**Blurring the all-in-focus frame gets object edges wrong.** A finger in front of a face, out
of focus, should turn see-through at its edges, and the face should show through. The
all-in-focus frame no longer holds the face behind the finger, so any method that works on it
has to invent what is there.

**Stage B has every layer whole.** It warps the whole background and every whole object
before it stacks them, so nothing has to be invented. A layer is one of those: the background,
or one object with its alpha mask, each with its own disparity.

---

## The method

1. **Each pixel gets a blur radius.** A pixel at disparity `d` spreads into a disk of radius
   `strength · |d − focus|`, in pixels of a frame 1024 pixels wide. At strength 16, a pixel
   half a unit of disparity from the focus spreads 8 pixels. On a 512-pixel frame the same
   setting spreads 4.
2. **The renderer blurs each layer on its own.** A pixel spreads only within its own layer.
   So the background never bleeds into an object, and the renderer blurs an object's alpha
   mask with its colour. That blurred alpha mask makes the object see-through at its edges.
3. **Every pixel spreads its own disk.** This is called scatter: the pixel sends its light
   out, rather than each output pixel averaging its neighbours. The renderer groups radii
   into bins 1 pixel wide and runs one convolution per bin, with a disk of the bin's average
   radius. A radius under half a pixel leaves the pixel sharp.
4. **The renderer corrects each layer for coverage.** Where two bins meet, or at the frame's
   edge, the disks do not add up to exactly one. Without a correction, a solid object turns
   up to 20 % see-through along those lines. So the renderer also blurs a frame of ones the
   same way, and divides by it where it falls short of one. Around the object, that frame of
   ones takes the radius of the nearest part of the object, so a blurred edge fades as far as
   its own blur reaches and an edge in focus stays solid.
5. **The blur runs in linear light.** The renderer raises colours to the power 2.2 before the
   blur and brings them back after it. A bright highlight then spreads into a brighter disc
   than a plain average gives. 8-bit frames clip their highlights, so the discs stay dimmer
   than a real lens makes them.
6. **The renderer stacks the layers far to near**, in the frame's paint order, as Stage B
   stacked them. A layer in focus therefore lands exactly where it is in the all-in-focus
   frame.

The convolutions use the fast Fourier transform. The cost of one convolution then does not
grow with the radius, where a direct convolution's grows with the radius squared. Wider
radii still mean more bins and more padding.

---

## Settings

- **Strength** — how strong the blur is. It means what any-to-bokeh's `k` means, in pixels at
  1024 pixels wide. any-to-bokeh runs at 16 by default.
- **Radius step** — the width of a radius bin, 1 pixel by default. A wider step means fewer
  convolutions, and a radius off by up to the step. A step wider than every radius gives
  one blur per layer.
- **Gamma** — the power for linear light, 2.2 by default. 1 blurs the colours as they are.

---

## Speed

Measured on 2026-10-10 on real layers from the development library, 1 to 5 objects, strength
16, in milliseconds per frame:

| device | 512 pixels | 1024 pixels |
|---|---|---|
| lab CPU, 1 thread | 137 | 560 |
| lab CPU, 24 threads | 53 | 303 |
| lab RTX 5090 | 2.8 | 11.6 |
| Mac M3 Pro GPU | 19 | 115 |

One thread is what each worker of a training loader gets. Runs vary: two runs of the same lab
CPU at 1024 pixels, a few hours apart, took 226 and 303 milliseconds.

---

## Choices and their limits

- **A disk, not a Gaussian.** A lens spreads a point into a disk, and Pablo preferred
  scattering disks to convolving Gaussians. A Gaussian splits into two one-dimensional passes,
  so it would cost less. We have not measured how much.
- **Inside one layer, nothing hides anything.** Two parts of one object at different
  disparities blur into each other without occlusion. Within one object the disparity spans
  at most about 0.32, which at strength 16 on a 1024-pixel frame is 5 pixels of radius. So a
  sharp part beside a blurred part of the same object takes some of its colour: on a
  synthetic layer, half in focus and half at radius 4, the sharp pixel at the seam drops
  from white to 0.85.
- **any-to-bokeh blurs differently in height and width.** It squashes our square frames to
  1024 × 576 and stretches the result back, so its blur is 1.78 times taller than it is wide.
  The same strength in both renderers matches only horizontally.
- **Prior art.** any-to-bokeh's own training data was made by a layered renderer, the
  `dataset_synthsis.py` script in its repository. That one gives every object a single
  disparity. Its blur kernel is not published.

## Related

- [[pipeline-explainer]] — the three stages, and where bokeh fits
- [[dataset-layout]] — the `layers/` stream the renderer reads
- [[loader]] — the layers in a training loop
