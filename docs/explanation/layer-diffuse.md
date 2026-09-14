---
type: topic
status: active
tags: [topic, generation, rgba, transparent]
related: [magick, datasets]
---

# LayerDiffuse

Stable Diffusion approach for generating images with transparent backgrounds — RGBA jointly, not RGB-then-matte.

> Compare with [[magick]] (chroma-keying pipeline that computes alpha *after the fact*). Pablo's preference: LayerDiffuse, because RGBA is generated jointly so RGB/alpha alignment is tighter at pixel level. See discussion in [[2026-04-22-pablo-magick-review]].

## References

- [Stable Diffusion Art — transparent background](https://stable-diffusion-art.com/transparent-background/)
- [Juggernaut XL on Civitai](https://civitai.com/models/133005/juggernaut-xl?modelVersionId=288982)
- [ComfyUI-layerdiffuse (huchenlei)](https://github.com/huchenlei/ComfyUI-layerdiffuse)

## How it works

![[layer-diffuse-architecture.png]]

Layer Diffuse adds a newly trained VAE encoder (E) and decoder (D) that encode the transparent image to a new **latent transparency** image. The VAE works with 4-channel images: RGB + alpha.

This latent transparency image is added to the latent image of Stable Diffusion, effectively "hiding" in the original latent without affecting its perceptual quality.

The U-Net noise predictor is also trained to predict the noise of transparent images. To enable transparent images with any custom model, the change to U-Net is stored as a LoRA model.

The authors also released models that can add background to foreground, foreground to background, etc.

### Text-to-image flow

1. A random tensor (image) is generated in the latent space.
2. The U-Net noise estimator, modified with a Layer Diffusion LoRA, predicts the noise of the latent image at each sampling step.
3. The expected noise is subtracted from the latent image.
4. Steps 2 and 3 are repeated for each sampling step.
5. At the end of the sampling steps, you get a latent image encoding an image with a transparent background.
6. A special VAE decoder converts the latent image to a pixel image with RGB and alpha channels.

## Output channels — what each one is for

- **Alpha** — black-and-white mask (white = keep, black = drop, gray = partial). Used as the transparency channel.
- **Decoded** — full color RGB image from the LayerDiffuse VAE. Still has a soft background; not the final result.
- **Premultiplied** — RGB × alpha. Compositing-ready; foreground colors preserved, background fades to neutral. **This is the one you'd actually use.**
- **Reconstructed** — round-trip sanity check: encode the RGBA result, decode it again. Should match Decoded if the VAE is faithful.

In practice the most useful outputs are:

- **Alpha** + **Premultiplied** = final transparent PNG, ready to layer onto any background.
- **Decoded** vs **Reconstructed** = quality verification only.

## Generated examples

### Example 1
**Alpha** ![[alpha_00001_.png]]
**Decoded** ![[image_decoded_00001_.png]]
**Premultiplied** ![[image_premult_00001_.png]]
**Reconstructed** ![[image_reconst_00001_.png]]

### Example 2
**Alpha** ![[alpha_00002_.png]]
**Decoded** ![[image_decoded_00002_.png]]
**Premultiplied** ![[image_premult_00002_.png]]
**Reconstructed** ![[image_reconst_00002_.png]]

### Example 3
**Alpha** ![[alpha_00003_.png]]
**Decoded** ![[image_decoded_00003_.png]]
**Premultiplied** ![[image_premult_00003_.png]]
**Reconstructed** ![[image_reconst_00003_.png]]

### Example 4
**Alpha** ![[alpha_00004_.png]]
**Decoded** ![[image_decoded_00004_.png]]
**Premultiplied** ![[image_premult_00004_.png]]
**Reconstructed** ![[image_reconst_00004_.png]]

### Example 5
**Alpha** ![[alpha_00005_.png]]
**Decoded** ![[image_decoded_00005_.png]]
**Premultiplied** ![[image_premult_00005_.png]]
**Reconstructed** ![[image_reconst_00005_.png]]

### Example 6
**Alpha** ![[alpha_00006_.png]]
**Decoded** ![[image_decoded_00006_.png]]
**Premultiplied** ![[image_premult_00006_.png]]
**Reconstructed** ![[image_reconst_00006_.png]]

### Example 7
**Alpha** ![[alpha_00007_.png]]
**Decoded** ![[image_decoded_00007_.png]]
**Premultiplied** ![[image_premult_00007_.png]]
**Reconstructed** ![[image_reconst_00007_.png]]

### Example 8
**Alpha** ![[alpha_00008_.png]]
**Decoded** ![[image_decoded_00008_.png]]
**Premultiplied** ![[image_premult_00008_.png]]
**Reconstructed** ![[image_reconst_00008_.png]]

### Example 9
**Alpha** ![[alpha_00009_.png]]
**Decoded** ![[image_decoded_00009_.png]]
**Premultiplied** ![[image_premult_00009_.png]]
**Reconstructed** ![[image_reconst_00009_.png]]

### Example 10
**Alpha** ![[alpha_00010_.png]]
**Decoded** ![[image_decoded_00010_.png]]
**Premultiplied** ![[image_premult_00010_.png]]
**Reconstructed** ![[image_reconst_00010_.png]]
