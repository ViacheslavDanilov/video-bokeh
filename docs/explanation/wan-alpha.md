---
type: topic
status: blocked
tags: [topic, video-generation, rgba, ruche]
related: [layer-diffuse, datasets]
---

# Wan-Alpha

Text-to-RGBA-video model — generates videos with a transparent background. Built as a DoRA adapter on top of Wan2.1.

> Status: **shelved** for our setup — 14B model needs >24 GB VRAM (out of reach on Ruche). 1.3B model crashes on flash-attn / CUDA_HOME issues. Switched to alternative pipeline (see below). See [[2026-04-08-wan-alpha-pivot]] for the run logs and stack traces.

## What's in the pipeline

1. **Wan2.1-T2V-14B (or 1.3B)** — base model. Contains:
    - T5 text encoder (`models_t5_umt5-xxl-enc-bf16.pth`) — converts text prompt → embeddings
    - T5 tokenizer (`google/umt5-xxl`)
    - VAE (`Wan2.1_VAE.pth`) — decodes latents → pixel-space video frames
    - DiT transformer (large `.safetensors`) — core diffusion model conditioned on text embeddings
2. **LightX2V LoRA** — distillation LoRA. Base model needs ~50 denoising steps; LightX2V gets comparable quality in 4 (`--sample_steps 4`). Speed optimization, not quality.
3. **Wan-Alpha DoRA** (`t2v.safetensors` in Wan-Alpha-v2.0) — the key innovation. A DoRA (Weight-Decomposed Low-Rank Adaptation) adapter that teaches the base Wan model to generate RGBA video instead of RGB. **This is what produces transparent backgrounds.**
4. **Wan-Alpha VAE decoder** (`decoder.bin`) — LoRA-adapted VAE decoder that outputs two streams: RGB video and alpha video. Base VAE only outputs RGB. Contains weights for both `vae_fgr` (foreground RGB) and `vae_pha` (alpha).
5. **Gauss mask** — precomputed Gaussian attention mask that biases alpha prediction toward frame center, improving subject vs background separation.

**Flow:** Text → T5 → DiT+DoRA (4 steps w/ LightX2V) → latents → VAE+decoder LoRA → RGB frames + Alpha frames → composited RGBA video.

## Why we shelved it (Apr 2026)

- **14B model**: needs >24 GB VRAM even at 832×480 / 5 frames with offloading. Crashes during init on Ruche GPUs.
- **1.3B model**: fails on `FLASH_ATTN_2_AVAILABLE` assertion at runtime; flash-attn install fails because `CUDA_HOME` is unset under the conda env (no nvcc on login node).
- The dataset isn't fully released either — it's a methodology + partial data + scripts ([issue #6](https://github.com/WeChatCV/Wan-Alpha/issues/6)).

## Alternative we picked

`Prompt → FLUX (image) / WAN (video) → BRIA RMBG-2.0 → RGBA`

- **FLUX** — 1024×1024 model family (3.5B base; 6.6B base+refiner). Stable, widely used.
- **BRIA RMBG-2.0** — modern background-removal model (~0.2B params), produces soft 8-bit alpha mask.
- Faster to implement, stable, scalable. Trade-off: not joint RGBA (alpha computed after) — same caveat as [[magick]] vs [[layer-diffuse]].

References:
- [Wan2.2 repo](https://github.com/Wan-Video/Wan2.2)
- [briaai/RMBG-2.0](https://huggingface.co/briaai/RMBG-2.0)
- [Runpod cloud GPUs](https://www.runpod.io/product/cloud-gpus) — option if we revisit Wan-Alpha 14B.
