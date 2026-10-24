"""Publish a library on Hugging Face, and fetch it back into the layout Stage B reads.

``pack`` writes the files Stage B reads into tar shards of about ``--shard-gb`` each, one
folder per kind, with ``index.json`` and the dataset card ``README.md``. A shard holds whole
items, so an item is never split. Stage A's inspection files, ``depth_raw.png`` and
``depth_input.png``, stay out. ``fetch`` downloads a dataset repository of such shards and
unpacks them into a library root that Stage B and the sequence stream take as they are:

    uv run python -m video_bokeh.library.hub pack --library-root data/library/da2-large \
        --output data/library-packed
    hf upload-large-folder <user>/<repo> data/library-packed --repo-type dataset
    uv run python -m video_bokeh.library.hub fetch --repo <user>/<repo> \
        --output data/library/da2-large

Shards are plain tar: the images are PNG already, so compressing them again saves little.
"""

from __future__ import annotations

import argparse
import json
import tarfile
from pathlib import Path
from typing import Any

from video_bokeh.core._library import (
    BACKGROUNDS,
    FOREGROUNDS,
    list_backgrounds,
    list_foregrounds,
)

#: The files of an item that Stage B reads, by kind.
READ = {
    FOREGROUNDS: ("rgb.png", "alpha.png", "depth.png", "meta.json"),
    BACKGROUNDS: ("rgb.png", "depth.png"),
}
SHARD_BYTES = 2 * 10**9

CARD = """---
license: cc-by-nc-4.0
pretty_name: Video bokeh library
tags:
- depth
- bokeh
- matting
- video
---

# Video bokeh library

The library that video-bokeh's Stage A builds once, and from which Stage B composes
training video for depth-aware bokeh: {foregrounds} foregrounds and {backgrounds} backgrounds,
each with the disparity estimated by Depth Anything V2 Large.

- `foregrounds/<id>/`: `rgb.png` (RGBA), `alpha.png`, `depth.png` (16-bit disparity) and
  `meta.json`.
- `backgrounds/<id>/`: `rgb.png` and `depth.png` (16-bit disparity).

The files come in tar shards of about {shard_gb} GB under `foregrounds/` and `backgrounds/`;
`index.json` lists them. The code at https://github.com/ViacheslavDanilov/video-bokeh fetches
and unpacks them into the layout Stage B reads, and generates sequences from it:

```bash
cd backend
uv sync --no-dev --extra loader
uv run python -m video_bokeh.library.hub fetch --repo {repo} --output data/library/da2-large
uv run python -m video_bokeh.loader.example --library-root data/library/da2-large
```

## Sources and license

This library is derived from two datasets, whose images it holds resized and cropped, and
from the output of one model:

- Foregrounds from MAGICK (Burgert et al., CVPR 2024), CC BY-NC 4.0.
- Backgrounds from BG-20k (Li et al., IJCV 2021), released under the MIT license on the
  condition that it is cited; its photographs stay under their owners' Unsplash or Pexels
  licenses.
- Disparity from Depth Anything V2 Large (Yang et al., NeurIPS 2024), whose weights are
  CC BY-NC 4.0.

The library is for non-commercial research only, under CC BY-NC 4.0. Please cite MAGICK,
BG-20k and Depth Anything V2 with it:

```bibtex
@inproceedings{{burgert2024magick,
  author    = {{Burgert, Ryan D. and Price, Brian L. and Kuen, Jason and Li, Yijun and Ryoo, Michael S.}},
  title     = {{MAGICK: A Large-scale Captioned Dataset from Matting Generated Images using Chroma Keying}},
  booktitle = {{Proceedings of the IEEE/CVF Conference on Computer Vision and Pattern Recognition (CVPR)}},
  year      = {{2024}},
  pages     = {{22595--22604}}
}}
@article{{li2022bridging,
  author  = {{Li, Jizhizi and Zhang, Jing and Maybank, Stephen J. and Tao, Dacheng}},
  title   = {{Bridging Composite and Real: Towards End-to-End Deep Image Matting}},
  journal = {{International Journal of Computer Vision}},
  volume  = {{130}},
  number  = {{2}},
  pages   = {{246--266}},
  year    = {{2022}},
  doi     = {{10.1007/s11263-021-01541-0}}
}}
@inproceedings{{yang2024depthanythingv2,
  author    = {{Yang, Lihe and Kang, Bingyi and Huang, Zilong and Zhao, Zhen and Xu, Xiaogang and Feng, Jiashi and Zhao, Hengshuang}},
  title     = {{Depth Anything V2}},
  booktitle = {{Advances in Neural Information Processing Systems}},
  volume    = {{37}},
  pages     = {{21875--21911}},
  year      = {{2024}}
}}
```
"""


def _items(library_root: Path, kind: str) -> list[str]:
    return (
        list_foregrounds(library_root)
        if kind == FOREGROUNDS
        else list_backgrounds(library_root)
    )


def pack(
    library_root: Path,
    output: Path,
    shard_bytes: int = SHARD_BYTES,
    repo: str = "<user>/<repo>",
) -> dict[str, dict[str, Any]]:
    """Write the library's shards, index and card into ``output``; return the index."""
    for kind in (FOREGROUNDS, BACKGROUNDS):
        if not (library_root / kind).is_dir():
            raise SystemExit(f"no {kind}/ in {library_root}: not a library")
    index: dict[str, dict[str, Any]] = {}
    for kind in (FOREGROUNDS, BACKGROUNDS):
        (output / kind).mkdir(parents=True, exist_ok=True)
        ids = _items(library_root, kind)
        shards: list[str] = []
        tar: tarfile.TarFile | None = None
        size = 0
        for asset_id in ids:
            files = [library_root / kind / asset_id / name for name in READ[kind]]
            files = [f for f in files if f.is_file()]
            if tar is None or size >= shard_bytes:
                if tar is not None:
                    tar.close()
                name = f"{kind}/{kind}-{len(shards):05d}.tar"
                shards.append(name)
                tar = tarfile.open(output / name, "w")
                size = 0
            for f in files:
                tar.add(f, arcname=f"{kind}/{asset_id}/{f.name}")
                size += f.stat().st_size
        if tar is not None:
            tar.close()
        index[kind] = {"items": len(ids), "shards": shards}
    (output / "index.json").write_text(
        json.dumps(index, indent=1) + "\n", encoding="utf-8"
    )
    card = CARD.format(
        foregrounds=index[FOREGROUNDS]["items"],
        backgrounds=index[BACKGROUNDS]["items"],
        shard_gb=round(shard_bytes / 10**9, 1),
        repo=repo,
    )
    (output / "README.md").write_text(card, encoding="utf-8")
    return index


def unpack(packed: Path, library_root: Path) -> Path:
    """Unpack every shard that ``packed/index.json`` lists into ``library_root``."""
    index = json.loads((packed / "index.json").read_text(encoding="utf-8"))
    library_root.mkdir(parents=True, exist_ok=True)
    for kind in (FOREGROUNDS, BACKGROUNDS):
        for name in index[kind]["shards"]:
            with tarfile.open(packed / name) as tar:
                tar.extractall(library_root, filter="data")
    return library_root


def fetch(repo: str, library_root: Path, revision: str | None = None) -> Path:
    """Download a packed library from the Hugging Face dataset ``repo`` and unpack it."""
    from huggingface_hub import snapshot_download

    packed = Path(
        snapshot_download(repo_id=repo, repo_type="dataset", revision=revision),
    )
    return unpack(packed, library_root)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest="command", required=True)
    packing = commands.add_parser(
        "pack", help="write a library's shards, index and card"
    )
    packing.add_argument("--library-root", type=Path, required=True)
    packing.add_argument("--output", type=Path, required=True)
    packing.add_argument("--shard-gb", type=float, default=SHARD_BYTES / 10**9)
    packing.add_argument(
        "--repo", default="<user>/<repo>", help="named in the card's commands"
    )
    fetching = commands.add_parser(
        "fetch", help="download a packed library and unpack it"
    )
    fetching.add_argument(
        "--repo", required=True, help="a Hugging Face dataset repository"
    )
    fetching.add_argument(
        "--output", type=Path, required=True, help="the library root to write"
    )
    fetching.add_argument("--revision", default=None)
    args = parser.parse_args(argv)
    if args.command == "pack":
        index = pack(
            args.library_root, args.output, int(args.shard_gb * 10**9), args.repo
        )
        for kind, entry in index.items():
            print(f"{kind}: {entry['items']} items in {len(entry['shards'])} shards")
    else:
        root = fetch(args.repo, args.output, args.revision)
        print(f"Library in {root}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
