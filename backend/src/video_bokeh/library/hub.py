"""Publish a library on Hugging Face, and fetch it back into the layout Stage B reads.

``pack`` writes the files Stage B reads into tar shards of about ``--shard-gb`` each, one
folder per kind under ``library/``, with ``library/index.json``, the dataset card
``README.md`` and its preview, the figure ``assets/preview.jpg`` and the video
``assets/preview.mp4``. The repository keeps the library under ``library/`` so that the
generated sequences can sit beside it. A shard holds whole items, so an item is never
split. Stage A's inspection files, ``depth_raw.png`` and ``depth_input.png``, stay out.
The shards follow WebDataset's layout: an item's files share its id, as ``<id>.rgb.png``,
``<id>.alpha.png``, ``<id>.depth.png`` and ``<id>.json``, so the Hub's viewer, the
``datasets`` library and the ``webdataset`` library read an item as one sample. Each item
also carries ``<id>.depth_preview.jpg``, its disparity in color, for the viewer alone.
The card describes a library built with Depth Anything V2 Large, so ``pack`` takes no
other. Its text is ``hub_card.md`` beside this file, with ``$name`` where ``card`` puts a
number.

``preview`` draws the preview of a packed folder again, of the items and sequences it is
given, and writes its card again, so a better example costs no packing.

``stage`` hard-links every ``--every``-th shard of each kind, the full index, the preview
and a card that says how much is online into a folder of its own, for a first upload that
is part of the library. The shards it takes are spread over the sorted ids. ``--every 1``,
or uploading the packed folder itself, gives the whole library and a card without the
upload status.

``fetch`` downloads the shards that ``library/index.json`` lists one at a time, unpacks
each into a library root that Stage B and the sequence stream take as they are, as
``foregrounds/<id>/rgb.png`` and so on, without the previews, and deletes it, so the disk holds the library and one shard at most. A shard that the index
lists but the repository does not hold yet is skipped and reported, so a repository can be
uploaded in parts. ``fetch`` marks each shard it has unpacked in ``.fetched/`` by its file
name, so that run again it fetches only what it lacks; a shard packed anew under an old
name is not fetched again unless its mark is deleted:

    uv run python -m video_bokeh.library.hub pack --library-root data/library/da2-large \
        --output data/library-packed
    uv run python -m video_bokeh.library.hub preview --library-root data/library/da2-large \
        --packed data/library-packed --foregrounds 6M__6MV7SSxmwd 0S__0SUuLNXyEz \
        3n__3nqLIHRgfa 1b__1bGRKnW1f3 --backgrounds train__h_a415d5e8 train__h_a7671d5b \
        testval__h_ea29ed84 --seeds 1005 1033 1050
    uv run python -m video_bokeh.library.hub stage --packed data/library-packed \
        --output data/library-staged --every 5
    hf upload-large-folder vdanilov/video-bokeh data/library-staged \
        --repo-type dataset --exclude README.md
    hf upload vdanilov/video-bokeh data/library-staged/README.md README.md \
        --repo-type dataset
    hf upload-large-folder vdanilov/video-bokeh data/library-packed \
        --repo-type dataset --exclude README.md
    hf upload vdanilov/video-bokeh data/library-packed/README.md README.md \
        --repo-type dataset
    uv run python -m video_bokeh.library.hub fetch --repo vdanilov/video-bokeh \
        --output data/library/da2-large

Shards are plain tar: the images are PNG already, so compressing them again saves little.
"""

from __future__ import annotations

import argparse
import io
import json
import os
import shutil
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
from video_bokeh.library._preview import depth_preview
from video_bokeh.scenes.generate import _library_estimator

#: The files of an item that Stage B reads, by kind.
READ = {
    FOREGROUNDS: ("rgb.png", "alpha.png", "depth.png", "meta.json"),
    BACKGROUNDS: ("rgb.png", "depth.png"),
}
#: The name each file of an item takes in a shard, after the item's id and a dot.
MEMBER = {"rgb.png": "rgb.png", "alpha.png": "alpha.png", "depth.png": "depth.png"}
MEMBER["meta.json"] = "json"
#: The file each member name stands for, which ``fetch`` writes back.
FILE = {member: name for name, member in MEMBER.items()}
#: The member that draws an item's disparity in color for the Hub's viewer.
DEPTH_PREVIEW = "depth_preview.jpg"
SHARD_BYTES = 2 * 10**9
#: The depth estimator the card names.
ESTIMATOR = "da2-large"
#: Where fetch marks the shards it has unpacked, under the library root.
FETCHED = ".fetched"
#: The repository the card's commands name, and its folder that holds the library.
REPO = "vdanilov/video-bokeh"
LIBRARY = "library"
#: The index of the library's shards, whose file names are relative to ``LIBRARY``.
INDEX = f"{LIBRARY}/index.json"
#: The card's figure and video, relative to the packed folder and to the card.
PREVIEW = "assets/preview.jpg"
VIDEO = "assets/preview.mp4"
#: The card's figure and video with their captions, when ``pack`` drew them. The video
#: plays from the repository, because the Hub's card takes no relative video path.
FIGURE = Template(f"""
![Four foregrounds and three backgrounds]({PREVIEW})

*Foregrounds and backgrounds of the library. A foreground's color is drawn over a
checkerboard and its disparity inside the matte, gray where the matte is under 0.04.
Disparity is drawn in the Spectral colormap, near red and far violet.*

<video src="https://huggingface.co/datasets/$repo/resolve/main/{VIDEO}" controls autoplay
loop muted playsinline width="100%"></video>

*Sequences that Stage B generated from this library at 1024 × 1024. Top: the frames all
in focus, their disparity and each object's matte in its own color. Bottom: their bokeh,
the forward optical flow, colored by direction and speed, and in cyan what the next frame
hides.*
""")

#: What the card says while the repository holds part of the library.
STATUS = Template("""
## Upload status

**The upload is not finished.** $online of $shards shards are online, holding
$online_fg of the $foregrounds foregrounds and $online_bg of the $backgrounds backgrounds.
`fetch` downloads what is online and reports the shards it could not find yet. Run it
again later, and it downloads only those.
""")


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
    with the items and bytes it holds. The preview needs torch and imageio's ffmpeg;
    ``preview=False`` leaves it out, and the card then shows none.
    """
    for kind in (FOREGROUNDS, BACKGROUNDS):
        if not (library_root / kind).is_dir():
            raise SystemExit(f"no {kind}/ in {library_root}: not a library")
    if (estimator := _library_estimator(library_root)) != ESTIMATOR:
        raise SystemExit(f"the card describes a {ESTIMATOR} library, not {estimator}")
    if output.exists() and any(output.iterdir()):
        raise SystemExit(f"{output} is not empty: pack writes into an empty folder")
    index: dict[str, dict[str, Any]] = {}
    shards_root = output / LIBRARY
    for kind in (FOREGROUNDS, BACKGROUNDS):
        (shards_root / kind).mkdir(parents=True, exist_ok=True)
        ids = _items(library_root, kind)
        shards: list[dict[str, Any]] = []
        tar: tarfile.TarFile | None = None
        size = 0
        for asset_id in ids:
            if "." in asset_id:
                raise SystemExit(
                    f"{asset_id}: an id with a dot breaks WebDataset's keys"
                )
            files = [library_root / kind / asset_id / name for name in READ[kind]]
            files = [f for f in files if f.is_file()]
            if tar is None or size >= shard_bytes:
                if tar is not None:
                    tar.close()
                name = f"{kind}/{kind}-{len(shards):05d}.tar"
                shards.append({"file": name, "items": 0})
                tar = tarfile.open(shards_root / name, "w")
                size = 0
            for f in files:
                tar.add(f, arcname=f"{asset_id}.{MEMBER[f.name]}")
                size += f.stat().st_size
            colored = depth_preview(library_root, kind, asset_id)
            member = tarfile.TarInfo(f"{asset_id}.{DEPTH_PREVIEW}")
            member.size, member.mtime = len(colored), int(files[0].stat().st_mtime)
            tar.addfile(member, io.BytesIO(colored))
            size += len(colored)
            shards[-1]["items"] += 1
        if tar is not None:
            tar.close()
        for shard in shards:
            shard["bytes"] = (shards_root / shard["file"]).stat().st_size
        side = 0
        if ids:
            with Image.open(library_root / kind / ids[0] / "rgb.png") as image:
                side = image.width
        index[kind] = {"items": len(ids), "side": side, "shards": shards}
    (output / INDEX).write_text(json.dumps(index, indent=1) + "\n", encoding="utf-8")
    if preview:
        _draw(library_root, output)
    (output / "README.md").write_text(card(index, repo, preview), encoding="utf-8")
    return index


def _draw(
    library_root: Path,
    output: Path,
    foregrounds: list[str] | None = None,
    backgrounds: list[str] | None = None,
    seeds: list[int] | None = None,
) -> None:
    from video_bokeh.library._preview import SEEDS, write_preview, write_video

    write_preview(library_root, output / PREVIEW, foregrounds, backgrounds)
    write_video(library_root, output / VIDEO, seeds or SEEDS)


def preview(
    library_root: Path,
    packed: Path,
    repo: str = REPO,
    foregrounds: list[str] | None = None,
    backgrounds: list[str] | None = None,
    seeds: list[int] | None = None,
) -> None:
    """Draw the preview of ``packed`` again from ``library_root``, and write its card again.

    ``foregrounds`` and ``backgrounds`` are item ids, ``seeds`` the video's sequences; each
    left out takes the default ``pack`` takes.
    """
    index = json.loads((packed / INDEX).read_text(encoding="utf-8"))
    _draw(library_root, packed, foregrounds, backgrounds, seeds)
    (packed / "README.md").write_text(card(index, repo, True), encoding="utf-8")


def stage(
    packed: Path,
    output: Path,
    every: int,
    repo: str = REPO,
) -> tuple[int, int]:
    """Hard-link every ``every``-th shard of each kind of ``packed`` into ``output``.

    ``output`` gets the full index, the preview if ``packed`` has one, and a card that
    counts what is online. Return the shards staged and the shards in all.
    """
    if every < 1:
        raise SystemExit(f"--every takes 1 or more, not {every}")
    if output.exists() and any(output.iterdir()):
        raise SystemExit(f"{output} is not empty: stage writes into an empty folder")
    index = json.loads((packed / INDEX).read_text(encoding="utf-8"))
    staged = [
        shard["file"]
        for kind in (FOREGROUNDS, BACKGROUNDS)
        for shard in index[kind]["shards"][::every]
    ]
    has_preview = (packed / PREVIEW).is_file()
    if has_preview and not (packed / VIDEO).is_file():
        # Packed before the video existed: its card would embed a file it lacks.
        raise SystemExit(f"{packed} has no {VIDEO}: run preview on it first")
    shards = [f"{LIBRARY}/{name}" for name in staged]
    for name in [*shards, PREVIEW, VIDEO] if has_preview else shards:
        (output / name).parent.mkdir(parents=True, exist_ok=True)
        try:
            os.link(packed / name, output / name)
        except OSError as error:
            raise SystemExit(
                f"cannot hard-link {packed / name}: {error}. "
                "stage needs its output on the same disk as the packed folder"
            ) from None
    (output / INDEX).parent.mkdir(parents=True, exist_ok=True)
    shutil.copyfile(packed / INDEX, output / INDEX)
    total = sum(len(index[kind]["shards"]) for kind in (FOREGROUNDS, BACKGROUNDS))
    online = set(staged) if len(staged) < total else None
    (output / "README.md").write_text(
        card(index, repo, has_preview, online), encoding="utf-8"
    )
    return len(staged), total


def _gb(n_bytes: int) -> str:
    return f"{n_bytes / 10**9:,.1f}"


def card(
    index: dict[str, dict[str, Any]],
    repo: str = REPO,
    preview: bool = False,
    online: set[str] | None = None,
) -> str:
    """The dataset card for the shards that ``index`` lists.

    With ``preview``, the card shows the figure at ``PREVIEW`` and the video at ``VIDEO``.
    With ``online``, the shard files the repository holds so far, it opens with how much of
    the library they are.
    """
    shards = {kind: index[kind]["shards"] for kind in (FOREGROUNDS, BACKGROUNDS)}
    all_shards = [s for kind in shards for s in shards[kind]]
    status = ""
    if online is not None:
        held = {
            kind: sum(s["items"] for s in shards[kind] if s["file"] in online)
            for kind in shards
        }
        status = STATUS.substitute(
            online=len(online),
            shards=len(all_shards),
            online_fg=f"{held[FOREGROUNDS]:,}",
            online_bg=f"{held[BACKGROUNDS]:,}",
            foregrounds=f"{index[FOREGROUNDS]['items']:,}",
            backgrounds=f"{index[BACKGROUNDS]['items']:,}",
        )
    return _template().substitute(
        repo=repo,
        preview=FIGURE.substitute(repo=repo) if preview else "",
        assets=f"\n{PREVIEW}\n{VIDEO}" if preview else "",
        status=status,
        foregrounds=f"{index[FOREGROUNDS]['items']:,}",
        backgrounds=f"{index[BACKGROUNDS]['items']:,}",
        fg_side=index[FOREGROUNDS]["side"],
        bg_side=index[BACKGROUNDS]["side"],
        fg_shards=len(shards[FOREGROUNDS]),
        bg_shards=len(shards[BACKGROUNDS]),
        shards=len(all_shards),
        fg_gb=_gb(sum(s["bytes"] for s in shards[FOREGROUNDS])),
        bg_gb=_gb(sum(s["bytes"] for s in shards[BACKGROUNDS])),
        total_gb=_gb(sum(s["bytes"] for s in all_shards)),
        largest_gb=_gb(max((s["bytes"] for s in all_shards), default=0)),
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


def _unpack(tar: tarfile.TarFile, kind_root: Path) -> None:
    """Write a shard's items into ``kind_root`` as ``<id>/rgb.png`` and so on.

    The depth previews are skipped. A member that is not a plain file named
    ``<id>.<member>`` is refused, so a shard cannot write outside ``kind_root``.
    """
    for member in tar:
        key, _, suffix = member.name.partition(".")
        if suffix == DEPTH_PREVIEW:
            continue
        if not member.isfile() or not key or "/" in key or suffix not in FILE:
            raise SystemExit(f"unexpected member {member.name!r} in a library shard")
        target = kind_root / key / FILE[suffix]
        target.parent.mkdir(parents=True, exist_ok=True)
        source = tar.extractfile(member)
        assert source is not None  # a plain file always has its bytes
        with source, target.open("wb") as out:
            shutil.copyfileobj(source, out)


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
        index = json.loads(download(INDEX, folder).read_text(encoding="utf-8"))
        for kind in (FOREGROUNDS, BACKGROUNDS):
            for shard in index[kind]["shards"]:
                done = fetched / f"{Path(shard['file']).name}.done"
                if done.exists():
                    continue
                try:
                    path = download(f"{LIBRARY}/{shard['file']}", folder)
                except EntryNotFoundError:
                    missing.append(shard["file"])
                    continue
                with tarfile.open(path) as tar:
                    _unpack(tar, library_root / kind)
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
        help="draw no preview, which needs torch and ffmpeg",
    )
    drawing = commands.add_parser(
        "preview", help="draw a packed library's preview again, and its card"
    )
    drawing.add_argument("--library-root", type=Path, required=True)
    drawing.add_argument("--packed", type=Path, required=True)
    drawing.add_argument("--repo", default=REPO, help="named in the card's commands")
    drawing.add_argument(
        "--foregrounds", nargs="+", help="up to four foreground ids for the figure"
    )
    drawing.add_argument(
        "--backgrounds", nargs="+", help="up to three background ids for the figure"
    )
    drawing.add_argument(
        "--seeds", nargs="+", type=int, help="the sequences the video plays"
    )
    staging = commands.add_parser(
        "stage", help="hard-link part of a packed library into a folder to upload"
    )
    staging.add_argument("--packed", type=Path, required=True)
    staging.add_argument("--output", type=Path, required=True)
    staging.add_argument(
        "--every", type=int, required=True, help="stage every n-th shard of each kind"
    )
    staging.add_argument("--repo", default=REPO, help="named in the card's commands")
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
    elif args.command == "preview":
        preview(
            args.library_root,
            args.packed,
            args.repo,
            args.foregrounds,
            args.backgrounds,
            args.seeds,
        )
        print(f"Preview and card written in {args.packed}")
    elif args.command == "stage":
        staged, total = stage(args.packed, args.output, args.every, args.repo)
        print(f"{staged} of {total} shards staged in {args.output}")
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
