#!/usr/bin/env python3
"""Classify MAGICK dataset images into coarse categories using OpenCLIP.

Reads `<data_root>/metadata.csv`, loads each image from
`<data_root>/images/<pp>/<page_id>.png`, encodes it with an OpenCLIP model,
and scores it against a fixed taxonomy of prompts. Writes a sibling
`predictions.csv` (page_id, top_label, top_score, per-class scores, subject)
without touching the authoritative metadata.

Taxonomy (edit `TAXONOMY` / `TEMPLATES` to tweak):
    person   — humans, portraits, body parts
    animal   — any living creature (mammal, bird, insect, reptile, fish)
    plant    — flowers, leaves, trees, bark, botanical subjects
    food     — cooked or raw edibles (fruit, meat, baked goods, drinks)
    object   — inanimate man-made items (containers, tools, furniture, clothing, electronics)
    text     — letters, logos, stamps, banners, typography
    effect   — water splashes, smoke, fire, bubbles, particle FX

Each class has multiple noun phrasings × multiple photo templates; the text
embeddings are averaged per class (prompt ensembling), which typically yields
+3–5 pp over a single prompt string.

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

TAXONOMY: dict[str, list[str]] = {
    "person": ["a person", "a human", "a portrait of a person", "people"],
    "animal": [
        "an animal",
        "a mammal",
        "a bird",
        "a fish",
        "an insect",
        "a reptile",
    ],
    "plant": ["a plant", "a flower", "a tree", "a leaf", "tree bark"],
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

TEMPLATES: list[str] = [
    "a photo of {}",
    "a picture of {}",
    "an image of {}",
    "a photograph of {}",
    "a close-up photo of {}",
    "a cropped photo of {}",
    "a studio photo of {}",
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
    parser.add_argument(
        "--single-prompt",
        action="store_true",
        help="Disable prompt ensembling (use first noun × 'a photograph of {}').",
    )
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

    labels = list(TAXONOMY.keys())
    if args.single_prompt:
        effective_taxonomy = {k: [v[0]] for k, v in TAXONOMY.items()}
        effective_templates = ["a photograph of {}"]
        print("  Prompt mode: single (no ensembling)")
    else:
        effective_taxonomy = TAXONOMY
        effective_templates = TEMPLATES
        avg = sum(len(n) for n in TAXONOMY.values()) * len(TEMPLATES) // len(labels)
        print(f"  Prompt mode: ensemble ({len(labels)} classes × {avg} avg prompts)")
    text_features = encode_class_prompts(
        model,
        tokenizer,
        effective_taxonomy,
        effective_templates,
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
            logits = 100.0 * image_features @ text_features.T
            scores = logits.softmax(dim=-1).cpu()
            for local_idx, row_idx in enumerate(indices.tolist()):
                row = rows[row_idx]
                row_scores = {
                    labels[i]: float(scores[local_idx, i]) for i in range(len(labels))
                }
                top_label = max(row_scores, key=lambda k: row_scores[k])
                predictions.append(
                    {
                        "page_id": row["page_id"],
                        "top_label": top_label,
                        "top_score": row_scores[top_label],
                        **{f"score_{k}": v for k, v in row_scores.items()},
                        "subject": row.get("subject", ""),
                    },
                )
            print(f"  processed {len(predictions)}/{len(rows)}")

    fieldnames = [
        "page_id",
        "top_label",
        "top_score",
        *[f"score_{k}" for k in labels],
        "subject",
    ]
    output_csv.parent.mkdir(parents=True, exist_ok=True)
    with output_csv.open("w", encoding="utf-8", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        for pred in predictions:
            writer.writerow(pred)

    counts: dict[str, int] = dict.fromkeys(labels, 0)
    for pred in predictions:
        counts[str(pred["top_label"])] += 1
    print("\n  Label distribution (top-1):")
    for label, count in counts.items():
        print(f"    {label:<8} {count:>5}")
    print(f"\n  Wrote {len(predictions)} rows → {output_csv}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
