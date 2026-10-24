"""Publish a library on Hugging Face, and fetch it back into the layout Stage B reads.

``pack`` writes the files Stage B reads into tar shards of about ``--shard-gb`` each, one
folder per kind, with ``index.json``, the dataset card ``README.md`` and its preview figure
``assets/preview.jpg``. A shard holds whole items, so an item is never split. Stage A's
inspection files, ``depth_raw.png`` and ``depth_input.png``, stay out. The card describes a
library built with Depth Anything V2 Large, so ``pack`` takes no other. Its text is
``hub_card.md`` beside this file, with ``$name`` where ``card`` puts a number.

``fetch`` downloads the shards that ``index.json`` lists one at a time, unpacks each into a
library root that Stage B and the sequence stream take as they are, and deletes it, so the
disk holds the library and one shard at most. A shard that the index lists but the
repository does not hold yet is skipped and reported, so a repository can be uploaded in
parts. ``fetch`` marks each shard it has unpacked in ``.fetched/`` by its file name, so that
run again it fetches only what it lacks; a shard packed anew under an old name is not
fetched again unless its mark is deleted:

    uv run python -m video_bokeh.library.hub pack --library-root data/library/da2-large \
        --output data/library-packed
    hf upload-large-folder vdanilov/video-bokeh-library data/library-packed \
        --repo-type dataset
    uv run python -m video_bokeh.library.hub fetch --repo vdanilov/video-bokeh-library \
        --output data/library/da2-large

Shards are plain tar: the images are PNG already, so compressing them again saves little.
"""

from __future__ import annotations

import argparse
import json
import tarfile
import tempfile
from importlib import resources
from pathlib import Path
from string import Template
from typing import Any

from PIL import Image

from video_bokeh.core._library import (
    BACKGROUNDS,
    FOREGROUNDS,
    list_backgrounds,
    list_foregrounds,
)
from video_bokeh.scenes.generate import _library_estimator

#: The files of an item that Stage B reads, by kind.
READ = {
    FOREGROUNDS: ("rgb.png", "alpha.png", "depth.png", "meta.json"),
    BACKGROUNDS: ("rgb.png", "depth.png"),
}
SHARD_BYTES = 2 * 10**9
#: The depth estimator the card names.
ESTIMATOR = "da2-large"
#: Where fetch marks the shards it has unpacked, under the library root.
FETCHED = ".fetched"
#: The repository the card's commands name.
REPO = "vdanilov/video-bokeh-library"
#: The card's figure, relative to the packed folder and to the card.
PREVIEW = "assets/preview.jpg"
#: The card's figure and its caption, when ``pack`` drew one.
FIGURE = f"""
![Two foregrounds, three backgrounds and one generated frame]({PREVIEW})

*Top: two foregrounds, each as `rgb.png` over a checkerboard, `alpha.png` and `depth.png`.
Middle: three backgrounds, `rgb.png` and `depth.png`. Bottom: one frame that Stage B
generated from this library, all-in-focus, disparity and bokeh. Disparity is drawn in the
Spectral colormap, near red and far violet. The items are spread evenly over the sorted ids.*
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
    repo: str = REPO,
    preview: bool = True,
) -> dict[str, dict[str, Any]]:
    """Write the library's shards, index, card and preview into ``output``; return the index.

    The index lists, per kind, the item count, the side of an item's images and each shard
    with the items and bytes it holds. The preview needs torch; ``preview=False`` leaves it
    out, and the card then shows no figure.
    """
    for kind in (FOREGROUNDS, BACKGROUNDS):
        if not (library_root / kind).is_dir():
            raise SystemExit(f"no {kind}/ in {library_root}: not a library")
    if (estimator := _library_estimator(library_root)) != ESTIMATOR:
        raise SystemExit(f"the card describes a {ESTIMATOR} library, not {estimator}")
    if output.exists() and any(output.iterdir()):
        raise SystemExit(f"{output} is not empty: pack writes into an empty folder")
    index: dict[str, dict[str, Any]] = {}
    for kind in (FOREGROUNDS, BACKGROUNDS):
        (output / kind).mkdir(parents=True, exist_ok=True)
        ids = _items(library_root, kind)
        shards: list[dict[str, Any]] = []
        tar: tarfile.TarFile | None = None
        size = 0
        for asset_id in ids:
            files = [library_root / kind / asset_id / name for name in READ[kind]]
            files = [f for f in files if f.is_file()]
            if tar is None or size >= shard_bytes:
                if tar is not None:
                    tar.close()
                name = f"{kind}/{kind}-{len(shards):05d}.tar"
                shards.append({"file": name, "items": 0})
                tar = tarfile.open(output / name, "w")
                size = 0
            for f in files:
                tar.add(f, arcname=f"{kind}/{asset_id}/{f.name}")
                size += f.stat().st_size
            shards[-1]["items"] += 1
        if tar is not None:
            tar.close()
        for shard in shards:
            shard["bytes"] = (output / shard["file"]).stat().st_size
        side = 0
        if ids:
            with Image.open(library_root / kind / ids[0] / "rgb.png") as image:
                side = image.width
        index[kind] = {"items": len(ids), "side": side, "shards": shards}
    (output / "index.json").write_text(
        json.dumps(index, indent=1) + "\n", encoding="utf-8"
    )
    if preview:
        from video_bokeh.library._preview import write_preview

        write_preview(library_root, output / PREVIEW)
    (output / "README.md").write_text(card(index, repo, preview), encoding="utf-8")
    return index


def _gb(n_bytes: int) -> str:
    return f"{n_bytes / 10**9:,.1f}"


def card(
    index: dict[str, dict[str, Any]],
    repo: str = REPO,
    preview: bool = False,
) -> str:
    """The dataset card for the shards that ``index`` lists.

    With ``preview``, the card shows the figure at ``PREVIEW``.
    """
    shards = {kind: index[kind]["shards"] for kind in (FOREGROUNDS, BACKGROUNDS)}
    every = [s for kind in shards for s in shards[kind]]
    return _template().substitute(
        repo=repo,
        preview=FIGURE if preview else "",
        assets=f"\n{PREVIEW}" if preview else "",
        foregrounds=f"{index[FOREGROUNDS]['items']:,}",
        backgrounds=f"{index[BACKGROUNDS]['items']:,}",
        fg_side=index[FOREGROUNDS]["side"],
        bg_side=index[BACKGROUNDS]["side"],
        fg_shards=len(shards[FOREGROUNDS]),
        bg_shards=len(shards[BACKGROUNDS]),
        shards=len(every),
        fg_gb=_gb(sum(s["bytes"] for s in shards[FOREGROUNDS])),
        bg_gb=_gb(sum(s["bytes"] for s in shards[BACKGROUNDS])),
        total_gb=_gb(sum(s["bytes"] for s in every)),
        largest_gb=_gb(max((s["bytes"] for s in every), default=0)),
        fg_last=Path(shards[FOREGROUNDS][-1]["file"]).name
        if shards[FOREGROUNDS]
        else "",
        bg_last=Path(shards[BACKGROUNDS][-1]["file"]).name
        if shards[BACKGROUNDS]
        else "",
    )


def _template() -> Template:
    return Template(
        resources.files("video_bokeh.library")
        .joinpath("hub_card.md")
        .read_text(encoding="utf-8")
    )


def fetch(repo: str, library_root: Path, revision: str | None = None) -> list[str]:
    """Download the shards of the Hugging Face dataset ``repo`` and unpack them one by one.

    A shard already marked in ``library_root/.fetched`` is skipped. Return the shards that
    the index lists and the repository does not hold yet.
    """
    from huggingface_hub import hf_hub_download
    from huggingface_hub.errors import EntryNotFoundError

    def download(name: str, folder: str) -> Path:
        return Path(
            hf_hub_download(
                repo_id=repo,
                filename=name,
                repo_type="dataset",
                revision=revision,
                local_dir=folder,
            ),
        )

    fetched = library_root / FETCHED
    fetched.mkdir(parents=True, exist_ok=True)
    missing: list[str] = []
    with tempfile.TemporaryDirectory(dir=library_root) as folder:
        index = json.loads(download("index.json", folder).read_text(encoding="utf-8"))
        for kind in (FOREGROUNDS, BACKGROUNDS):
            for shard in index[kind]["shards"]:
                done = fetched / f"{Path(shard['file']).name}.done"
                if done.exists():
                    continue
                try:
                    path = download(shard["file"], folder)
                except EntryNotFoundError:
                    missing.append(shard["file"])
                    continue
                with tarfile.open(path) as tar:
                    tar.extractall(library_root, filter="data")
                path.unlink()
                done.touch()
    return missing


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest="command", required=True)
    packing = commands.add_parser(
        "pack", help="write a library's shards, index, card and preview"
    )
    packing.add_argument("--library-root", type=Path, required=True)
    packing.add_argument("--output", type=Path, required=True)
    packing.add_argument("--shard-gb", type=float, default=SHARD_BYTES / 10**9)
    packing.add_argument("--repo", default=REPO, help="named in the card's commands")
    packing.add_argument(
        "--no-preview",
        action="store_true",
        help="draw no preview figure, which needs torch",
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
            args.library_root,
            args.output,
            int(args.shard_gb * 10**9),
            args.repo,
            preview=not args.no_preview,
        )
        for kind, entry in index.items():
            print(f"{kind}: {entry['items']} items in {len(entry['shards'])} shards")
    else:
        missing = fetch(args.repo, args.output, args.revision)
        print(f"Library in {args.output}")
        if missing:
            print(
                f"{len(missing)} shards are not in the repository yet; fetch again later"
            )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
