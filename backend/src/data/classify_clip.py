#!/usr/bin/env python3
"""Classify MAGICK dataset images into coarse categories using OpenCLIP.

Reads `<data_root>/metadata.csv`, loads each image from
`<data_root>/images/<pp>/<page_id>.png`, encodes it with an OpenCLIP model,
and scores it against two orthogonal taxonomies — *subject* (what is in the
image) and *style* (how it is rendered). Writes a sibling `predictions.csv`
(page_id, top_label, top_score, top_style, top_style_score, per-class
scores for both axes, subject) without touching the authoritative metadata.

Subject taxonomy (edit `SUBJECT_TAXONOMY` / `SUBJECT_TEMPLATES` to tweak):
    person   — humans, portraits, body parts
    animal   — any living creature (mammal, bird, insect, reptile, fish)
    plant    — flowers, leaves, trees, bark, botanical subjects
    food     — cooked or raw edibles (fruit, meat, baked goods, drinks)
    object   — inanimate man-made items (containers, tools, furniture, clothing, electronics)
    text     — letters, logos, stamps, banners, typography
    effect   — water splashes, smoke, fire, bubbles, particle FX

Style taxonomy (edit `STYLE_TAXONOMY` / `STYLE_TEMPLATES` to tweak):
    photo        — real-world photographs (DSLR, candid, documentary)
    illustration — digital illustration, vector art, stickers, concept art
    drawing      — pencil/ink/line drawings, tattoo line art, sketches
    painting     — oil, watercolour, acrylic, digital painting
    render       — 3D render, CGI, octane render
    cartoon      — cartoon, anime, comic book panel

Each class has multiple noun phrasings × multiple templates; the text
embeddings are averaged per class (prompt ensembling), which typically yields
+3–5 pp over a single prompt string. The two axes are scored independently
(separate softmaxes) so a "real wolf photograph" can be tagged
animal+photo while an "ornate wolf tattoo" is animal+drawing.

Usage:
    uv run python -m data.classify_clip \
        --data-root backend/data/magick_dev \
        --batch-size 16

    # Full mirror (populate via `huggingface-cli download OneOverZero/MAGICK
    # --repo-type dataset --local-dir backend/data/magick`), on a GPU:
    uv run python -m data.classify_clip \
        --data-root backend/data/magick \
        --batch-size 64 --device cuda
"""

from __future__ import annotations

import argparse
import csv
import sys
from pathlib import Path

import open_clip
import torch
from PIL import Image
from torch.utils.data import DataLoader, Dataset

# fmt: off
SUBJECT_TAXONOMY: dict[str, list[str]] = {
    "person": [
        "a person",
        "a human",
        "a portrait of a person",
        "people",
    ],
    "animal": [
        "an animal",
        "a mammal",
        "a bird",
        "a fish",
        "an insect",
        "a reptile",
    ],
    "plant": [
        "a plant",
        "a flower",
        "a tree",
        "a leaf",
        "tree bark",
    ],
    "food": [
        "food",
        "a meal on a plate",
        "a piece of fruit",
        "a baked good",
        "a drink in a glass",
    ],
    "object": [
        "an inanimate object",
        "a household item",
        "a tool",
    ],
    "text": [
        "text",
        "letters of the alphabet",
        "a logo",
        "a sign with writing",
        "typography",
    ],
    "effect": [
        "a water splash",
        "smoke rising in the air",
        "fire and flames",
        "soap bubbles",
    ],
}
# fmt: on

SUBJECT_TEMPLATES: list[str] = [
    "a photo of {}",
    "a picture of {}",
    "an image of {}",
    "a photograph of {}",
    "a close-up photo of {}",
    "a cropped photo of {}",
    "a studio photo of {}",
]

STYLE_TAXONOMY: dict[str, list[str]] = {
    "photo": [
        "a photograph",
        "a real photograph",
        "a candid photo",
        "a DSLR photograph",
        "a documentary photograph",
    ],
    "illustration": [
        "a digital illustration",
        "vector art",
        "a sticker",
        "concept art",
        "a graphic illustration",
    ],
    "drawing": [
        "a pencil drawing",
        "a line drawing",
        "tattoo line art",
        "an ink sketch",
        "ornate line art",
    ],
    "painting": [
        "an oil painting",
        "a watercolour painting",
        "a digital painting",
        "an acrylic painting",
    ],
    "render": [
        "a 3D render",
        "CGI",
        "an octane render",
        "a computer-generated render",
    ],
    "cartoon": [
        "a cartoon",
        "anime",
        "a comic book panel",
    ],
}

STYLE_TEMPLATES: list[str] = [
    "{}",
    "an image of {}",
    "this image is {}",
    "this looks like {}",
    "an example of {}",
]


def image_path(root: Path, page_id: str) -> Path:
    return root / "images" / page_id[:2] / f"{page_id}.png"


def pick_device(preferred: str) -> str:
    if preferred != "auto":
        return preferred
    if torch.cuda.is_available():
        return "cuda"
    if torch.backends.mps.is_available():
        return "mps"
    return "cpu"


class MagickImageDataset(Dataset):
    def __init__(
        self,
        rows: list[dict[str, str]],
        data_root: Path,
        preprocess,
    ) -> None:
        self.rows = rows
        self.data_root = data_root
        self.preprocess = preprocess

    def __len__(self) -> int:
        return len(self.rows)

    def __getitem__(self, index: int) -> tuple[torch.Tensor, int]:
        row = self.rows[index]
        path = image_path(self.data_root, row["page_id"])
        image = Image.open(path).convert("RGB")
        return self.preprocess(image), index


def read_metadata(
    metadata_csv: Path,
    data_root: Path,
) -> tuple[list[str], list[dict[str, str]]]:
    with metadata_csv.open("r", encoding="utf-8-sig", newline="") as f:
        reader = csv.DictReader(f)
        if reader.fieldnames is None:
            raise ValueError(f"{metadata_csv}: missing header row")
        fieldnames = list(reader.fieldnames)
        rows = [r for r in reader if r.get("page_id", "").strip()]

    present = [r for r in rows if image_path(data_root, r["page_id"]).exists()]
    missing = len(rows) - len(present)
    if missing:
        print(
            f"  WARN {missing}/{len(rows)} images missing on disk; skipping",
            file=sys.stderr,
        )
    return fieldnames, present


def encode_class_prompts(
    model,
    tokenizer,
    taxonomy: dict[str, list[str]],
    templates: list[str],
    device: str,
) -> torch.Tensor:
    """Build one averaged, L2-normalised embedding per class.

    For each class we expand `nouns × templates` into a flat prompt list,
    encode them, L2-normalise each, mean-pool over the prompts, then
    L2-normalise the mean. Averaging on the unit sphere (normalise → mean →
    re-normalise) is the standard CLIP ensemble recipe — smooths out the
    single-prompt jitter.
    """
    class_embeddings: list[torch.Tensor] = []
    with torch.no_grad():
        for nouns in taxonomy.values():
            prompts = [t.format(n) for n in nouns for t in templates]
            tokens = tokenizer(prompts).to(device)
            features = model.encode_text(tokens)
            features = features / features.norm(dim=-1, keepdim=True)
            mean = features.mean(dim=0)
            mean = mean / mean.norm()
            class_embeddings.append(mean)
    return torch.stack(class_embeddings)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--data-root", type=Path, required=True)
    parser.add_argument("--output", type=Path, default=None)
    parser.add_argument("--model", default="ViT-L-14")
    parser.add_argument("--pretrained", default="openai")
    parser.add_argument("--device", default="auto")
    parser.add_argument("--batch-size", type=int, default=16)
    parser.add_argument("--num-workers", type=int, default=4)
    args = parser.parse_args()

    metadata_csv = args.data_root / "metadata.csv"
    output_csv = args.output or (args.data_root / "predictions.csv")

    _, rows = read_metadata(metadata_csv, args.data_root)
    if not rows:
        print(f"No images found under {args.data_root}/images", file=sys.stderr)
        return 1

    device = pick_device(args.device)
    print(f"  Using device: {device}")
    print(f"  Model: {args.model} ({args.pretrained})")
    print(f"  Images: {len(rows)}")

    model, _, preprocess = open_clip.create_model_and_transforms(
        args.model,
        pretrained=args.pretrained,
        device=device,
    )
    model.eval()
    tokenizer = open_clip.get_tokenizer(args.model)

    subject_labels = list(SUBJECT_TAXONOMY.keys())
    style_labels = list(STYLE_TAXONOMY.keys())
    subj_avg = (
        sum(len(n) for n in SUBJECT_TAXONOMY.values())
        * len(SUBJECT_TEMPLATES)
        // len(subject_labels)
    )
    style_avg = (
        sum(len(n) for n in STYLE_TAXONOMY.values())
        * len(STYLE_TEMPLATES)
        // len(style_labels)
    )
    print(
        f"  Prompts: subject {len(subject_labels)} classes × {subj_avg} avg, "
        f"style {len(style_labels)} × {style_avg}",
    )
    subject_features = encode_class_prompts(
        model,
        tokenizer,
        SUBJECT_TAXONOMY,
        SUBJECT_TEMPLATES,
        device,
    )
    style_features = encode_class_prompts(
        model,
        tokenizer,
        STYLE_TAXONOMY,
        STYLE_TEMPLATES,
        device,
    )

    dataset = MagickImageDataset(rows, args.data_root, preprocess)
    loader: DataLoader = DataLoader(
        dataset,
        batch_size=args.batch_size,
        shuffle=False,
        num_workers=args.num_workers,
        pin_memory=(device == "cuda"),
    )

    predictions: list[dict[str, str | float]] = []
    with torch.no_grad():
        for images, indices in loader:
            images = images.to(device, non_blocking=True)
            image_features = model.encode_image(images)
            image_features = image_features / image_features.norm(
                dim=-1,
                keepdim=True,
            )
            subject_scores = (
                (100.0 * image_features @ subject_features.T).softmax(dim=-1).cpu()
            )
            style_scores = (
                (100.0 * image_features @ style_features.T).softmax(dim=-1).cpu()
            )
            for local_idx, row_idx in enumerate(indices.tolist()):
                row = rows[row_idx]
                subject_row = {
                    subject_labels[i]: float(subject_scores[local_idx, i])
                    for i in range(len(subject_labels))
                }
                style_row = {
                    style_labels[i]: float(style_scores[local_idx, i])
                    for i in range(len(style_labels))
                }
                top_subject = max(subject_row, key=lambda k: subject_row[k])
                top_style = max(style_row, key=lambda k: style_row[k])
                predictions.append(
                    {
                        "page_id": row["page_id"],
                        "top_label": top_subject,
                        "top_score": subject_row[top_subject],
                        "top_style": top_style,
                        "top_style_score": style_row[top_style],
                        **{f"score_{k}": v for k, v in subject_row.items()},
                        **{f"score_style_{k}": v for k, v in style_row.items()},
                        "subject": row.get("subject", ""),
                    },
                )
            print(f"  processed {len(predictions)}/{len(rows)}")

    fieldnames = [
        "page_id",
        "top_label",
        "top_score",
        "top_style",
        "top_style_score",
        *[f"score_{k}" for k in subject_labels],
        *[f"score_style_{k}" for k in style_labels],
        "subject",
    ]
    output_csv.parent.mkdir(parents=True, exist_ok=True)
    with output_csv.open("w", encoding="utf-8", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        for pred in predictions:
            writer.writerow(pred)

    subject_counts: dict[str, int] = dict.fromkeys(subject_labels, 0)
    style_counts: dict[str, int] = dict.fromkeys(style_labels, 0)
    for pred in predictions:
        subject_counts[str(pred["top_label"])] += 1
        style_counts[str(pred["top_style"])] += 1
    print("\n  Subject distribution (top-1):")
    for label, count in subject_counts.items():
        print(f"    {label:<14} {count:>5}")
    print("\n  Style distribution (top-1):")
    for label, count in style_counts.items():
        print(f"    {label:<14} {count:>5}")
    print(f"\n  Wrote {len(predictions)} rows → {output_csv}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
