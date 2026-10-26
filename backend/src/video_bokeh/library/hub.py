"""Publish a library and its fixed set on Hugging Face, and fetch both back to disk.

``pack`` writes the files Stage B reads into tar shards of about ``--shard-gb`` each, one
folder per kind under ``library/`` and one split per shard, as ``train-00000.tar`` and
``test-00000.tar``, with ``library/index.json``, the dataset card
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

``pack-sequences`` adds a fixed set that ``scenes.generate --split test`` wrote to a packed
folder: its sequences in shards under ``sequences/``, one sample per sequence, the run's
records beside them and a card that describes it. ``fetch-sequences`` writes it back as
``scenes.generate`` wrote it.

``preview`` draws the preview of a packed folder again, of the items and sequences it is
given, and writes its card again, so a better example costs no packing.

``stage`` hard-links every ``--every``-th shard of each kind, the full index, the preview
and a card that says how much is online into a folder of its own, for a first upload that
is part of the library. The shards it takes are spread over each kind's train shards and
then its test shards, and the fixed set stays out. ``--every 1``,
or uploading the packed folder itself, gives the whole library and a card without the
upload status.

``fetch`` downloads the shards that ``library/index.json`` lists one at a time, unpacks
each into a library root that Stage B and the sequence stream take as they are, as
``foregrounds/<id>/rgb.png`` and so on, without the previews, and deletes it, so the disk
holds the library and one shard at most. A shard that the index lists but the repository
does not hold yet is skipped and reported, so a repository can be uploaded in parts.
``fetch`` marks each shard it has unpacked in ``.fetched/`` by its path in the repository,
so that run again it fetches only what it lacks; a shard packed anew under an old name is
not fetched again unless its mark is deleted:

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
    uv run python -m video_bokeh.library.hub pack-sequences --data-root data/fixed-set \
        --packed data/library-packed
    hf upload-large-folder vdanilov/video-bokeh data/library-packed \
        --repo-type dataset --exclude README.md
    hf upload vdanilov/video-bokeh data/library-packed/README.md README.md \
        --repo-type dataset
    uv run python -m video_bokeh.library.hub fetch --repo vdanilov/video-bokeh \
        --output data/library/da2-large
    uv run python -m video_bokeh.library.hub fetch-sequences --repo vdanilov/video-bokeh \
        --output data/fixed-set

Shards are plain tar: the images are PNG already, so compressing them again saves little.
"""

from __future__ import annotations

import argparse
import csv
import io
import json
import os
import shutil
import tarfile
import tempfile
from collections.abc import Callable
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
from video_bokeh.core._split import TEST, TRAIN, in_split
from video_bokeh.library._preview import depth_preview
from video_bokeh.scenes.generate import _library_estimator

#: The files of an item that Stage B reads, by kind.
READ = {
    FOREGROUNDS: ("rgb.png", "alpha.png", "depth.png", "meta.json"),
    BACKGROUNDS: ("rgb.png", "depth.png"),
}
#: The name each file of an item takes in a shard, after the item's id and a dot.
MEMBER = {
    "rgb.png": "rgb.png",
    "alpha.png": "alpha.png",
    "depth.png": "depth.png",
    "meta.json": "json",
}
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
#: The repository's folder of the fixed set's sequences, its index, and the records of
#: the run that wrote them, which sit beside the index.
SEQUENCES = "sequences"
SEQUENCE_INDEX = f"{SEQUENCES}/index.json"
RECORDS = ("objects.csv", "run.json", "manifest.csv")
#: The streams a packed sequence holds, each a folder of one file per frame.
STREAMS = (
    "all_in_focus",
    "alpha",
    "disparity",
    "bokeh",
    "flow",
    "flow_back",
    "occlusion",
)
#: What ``bokeh/`` holds beside its frames, and the member it is packed as.
FOCUS = "focus.json"
#: The extensions of a stream's frames.
FRAME_TYPES = ("png", "tif")
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

*Sequences the generator composed from both splits of the library, at 1024 × 1024. Top:
the frames all in focus, their disparity and each object's matte in its own color. Bottom:
their bokeh, the forward optical flow, colored by direction and speed, and in cyan what the
next frame hides.*
""")

#: What the card says while the repository holds part of the library.
STATUS = Template("""
## Upload status

**The upload is not finished.** $online of $shards shards are online, holding
$online_fg of the $foregrounds foregrounds and $online_bg of the $backgrounds backgrounds.
`fetch` downloads what is online and reports the shards it could not find yet. Run it
again later, and it downloads only those.
""")


#: The card's subset of the fixed set's sequences, in its front matter.
SEQUENCES_CONFIG = f"""- config_name: {SEQUENCES}
  data_files:
  - split: test
    path: "{SEQUENCES}/test-*.tar"
"""

#: What the card says of the fixed set, when the repository holds one.
FIXED_SET = Template("""
## Fixed set

**`sequences/` holds $sequences sequences that the generator wrote once from the test split,**
for evaluation: none of their objects or backgrounds is in the train split. Each has $frames
frames at $size × $size and $objects, and its bokeh is rendered at `k = $strength`.
`fetch-sequences` needs $seq_gb GB of disk, plus room for one shard of at most $seq_largest GB:

```bash
uv run python -m video_bokeh.library.hub fetch-sequences --repo $repo \\
  --output data/fixed-set
```

```text
data/fixed-set/
├── manifest.csv, objects.csv, run.json
└── sequences/<id>/
    ├── all_in_focus/, disparity/, alpha/, bokeh/ (with focus.json)
    └── flow/, flow_back/, occlusion/
```

| File | Frames | Mode | Type | Values |
|---|---|---|---|---|
| `all_in_focus/<frame>.png` | all | RGB | uint8 | the frame with nothing blurred |
| `disparity/<frame>.png` | all | I;16 | uint16 | disparity in [0, 1] times 65535, larger closer, on one axis for every sequence, the background under 0.05 |
| `alpha/<frame>.tif` | all | a page per object | uint8 | each object's soft matte, 0 to 255 |
| `bokeh/<frame>.png` | all | RGB | uint8 | the frame as the layered renderer blurred it |
| `flow/<frame>.png` | all but the last | RGB | uint16 | the optical flow to the next frame, KITTI-encoded |
| `flow_back/<frame>.png` | all but the first | RGB | uint16 | the optical flow to the previous frame, KITTI-encoded |
| `occlusion/<frame>.png` | all but the last | L | uint8 | 255 where the next frame does not show the surface |

- **The flow is exact.** Every layer moves by a known transform, so the flow follows the
  front-most surface at each pixel. KITTI's encoding stores red `u · 64 + 2¹⁵`, green
  `v · 64 + 2¹⁵` and blue 1 where valid, so read it with a 16-bit reader such as the code's
  `read_flow_png`. The occlusion mask belongs to the forward flow; the backward flow has none.
- **`bokeh/focus.json`** names the object in focus by its alpha page, or `null`, gives each
  frame's in-focus disparity as `zf`, and records the renderer and its settings.
- **The run's records sit beside the shards.** `manifest.csv` gives each sequence's seed,
  object count and background, `objects.csv` each object's foreground and trajectory, and
  `run.json` the settings. With them, and code whose sampling has not changed since,
  `scenes.generate` writes the same sequences again with `--layers`, and `render.run`
  renders their bokeh from those layers at another strength or focus.
- **A shard holds one sample per sequence,** its files named `<id>.<stream>.<frame>`, with
  `<id>.focus.json` and `<id>.json`, the sequence's rows of the records.

The code repository's
[dataset layout](https://github.com/ViacheslavDanilov/video-bokeh/blob/main/docs/reference/dataset-layout.md)
describes every stream in full.
""")

#: What the card's reading section says of the fixed set's subset, when there is one.
SEQUENCES_DATASETS = f"""
**Read the fixed set with `fetch-sequences`, not `datasets`.** Its `{SEQUENCES}` subset has a
row per sequence, but Pillow decodes a flow file as 8-bit color and an alpha file as its
first page alone, and the first row comes only after a few whole sequences.
"""


def _glance(index: dict[str, dict[str, Any]], sequences: dict[str, Any] | None) -> str:
    """The card's table of what the repository holds, with the fixed set when it has one."""
    fg, bg = index[FOREGROUNDS], index[BACKGROUNDS]
    rows = [
        ["", "Foregrounds", "Backgrounds"],
        ["Items", f"{fg['items']:,}", f"{bg['items']:,}"],
        ["Size", f"{fg['side']} × {fg['side']}", f"{bg['side']} × {bg['side']}"],
        [
            "Files",
            "`rgb.png`, `alpha.png`, `depth.png`, `meta.json`",
            "`rgb.png`, `depth.png`",
        ],
        ["Shards", str(len(fg["shards"])), str(len(bg["shards"]))],
        [
            "On disk",
            f"{_gb(sum(s['bytes'] for s in fg['shards']))} GB",
            f"{_gb(sum(s['bytes'] for s in bg['shards']))} GB",
        ],
    ]
    shards = [*fg["shards"], *bg["shards"]]
    if sequences is not None:
        side = sequences["size"]
        extra = [
            "Fixed set",
            f"{sequences['items']:,} sequences",
            f"{sequences['frames']} frames at {side} × {side}",
            f"{len(STREAMS)} streams of per-frame files",
            str(len(sequences["shards"])),
            f"{_gb(sum(s['bytes'] for s in sequences['shards']))} GB",
        ]
        rows = [[*row, cell] for row, cell in zip(rows, extra, strict=True)]
        shards += sequences["shards"]
    lines = [
        "|" + "|".join(f" {cell} " if cell else " " for cell in row) + "|"
        for row in rows
    ]
    lines.insert(1, "|" + "---|" * len(rows[0]))
    total = _gb(sum(s["bytes"] for s in shards))
    return "\n".join(lines) + (
        f"\n\nIn all, {len(shards)} shards hold {total} GB. **`depth.png` holds disparity, "
        "not depth:** larger values are closer. Every disparity map comes from Depth "
        "Anything V2 Large."
    )


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
    dotted = [
        i
        for kind in (FOREGROUNDS, BACKGROUNDS)
        for i in _items(library_root, kind)
        if "." in i
    ]
    if dotted:
        raise SystemExit(f"{dotted[0]}: an id with a dot breaks WebDataset's keys")
    index: dict[str, dict[str, Any]] = {}
    shards_root = output / LIBRARY
    for kind in (FOREGROUNDS, BACKGROUNDS):
        (shards_root / kind).mkdir(parents=True, exist_ok=True)
        ids = _items(library_root, kind)
        shards: list[dict[str, Any]] = []
        for split in (TRAIN, TEST):
            tar: tarfile.TarFile | None = None
            size = n_split = 0
            for asset_id in in_split(ids, kind, split):
                files = [library_root / kind / asset_id / name for name in READ[kind]]
                files = [f for f in files if f.is_file()]
                if tar is None or size >= shard_bytes:
                    if tar is not None:
                        tar.close()
                    name = f"{kind}/{split}-{n_split:05d}.tar"
                    shards.append({"file": name, "split": split, "items": 0})
                    tar = tarfile.open(shards_root / name, "w")
                    size = 0
                    n_split += 1
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
    sequences = packed / SEQUENCE_INDEX
    (packed / "README.md").write_text(
        card(
            index,
            repo,
            True,
            sequences=json.loads(sequences.read_text(encoding="utf-8"))
            if sequences.is_file()
            else None,
        ),
        encoding="utf-8",
    )


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


def _shard_lines(folder: str, shards: list[dict[str, Any]]) -> list[str]:
    """The shard files of ``folder``, one line per split, for the card's layout."""
    lines = []
    for split in (TRAIN, TEST):
        names = [Path(s["file"]).name for s in shards if s["split"] == split]
        if names:
            last = f" … {names[-1]}" if len(names) > 1 else ""
            lines.append(f"{folder}/{names[0]}{last}")
    return lines


def card(
    index: dict[str, dict[str, Any]],
    repo: str = REPO,
    preview: bool = False,
    online: set[str] | None = None,
    sequences: dict[str, Any] | None = None,
) -> str:
    """The dataset card for the shards that ``index`` lists.

    With ``preview``, the card shows the figure at ``PREVIEW`` and the video at ``VIDEO``.
    With ``online``, the shard files the repository holds so far, it opens with how much of
    the library they are. With ``sequences``, the index ``pack_sequences`` writes, it
    describes the fixed set too.
    """
    shards = {kind: index[kind]["shards"] for kind in (FOREGROUNDS, BACKGROUNDS)}
    all_shards = [s for kind in shards for s in shards[kind]]
    counts = {
        (kind, split): sum(s["items"] for s in shards[kind] if s["split"] == split)
        for kind in shards
        for split in (TRAIN, TEST)
    }
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
    layout = [
        line
        for kind in (FOREGROUNDS, BACKGROUNDS)
        for line in _shard_lines(f"{LIBRARY}/{kind}", shards[kind])
    ]
    fixed_set = config = part = reading = ""
    split_use = " The test split is held out for evaluation."
    if sequences is not None:
        seq_shards = sequences["shards"]
        layout += [
            SEQUENCE_INDEX,
            *(f"{SEQUENCES}/{name}" for name in RECORDS),
            *_shard_lines(SEQUENCES, seq_shards),
        ]
        config = SEQUENCES_CONFIG
        part = (
            f"\n- **The fixed set**, under `{SEQUENCES}/`: {sequences['items']:,} "
            "sequences the generator wrote once from the library's test split, for "
            "evaluation."
        )
        split_use = (
            " The test split is held out for evaluation: the fixed set is made of it."
        )
        reading = SEQUENCES_DATASETS
        low, high = sequences["objects"]
        fixed_set = FIXED_SET.substitute(
            repo=repo,
            sequences=f"{sequences['items']:,}",
            frames=sequences["frames"],
            size=sequences["size"],
            strength=f"{sequences['bokeh_strength']:g}",
            objects=f"{low} to {high} objects"
            if low != high
            else f"{low} object{'s' * (low != 1)}",
            seq_gb=_gb(sum(s["bytes"] for s in seq_shards)),
            seq_largest=_gb(max(s["bytes"] for s in seq_shards)),
        )
    return _template().substitute(
        repo=repo,
        preview=FIGURE.substitute(repo=repo) if preview else "",
        assets=f"\n{PREVIEW}\n{VIDEO}" if preview else "",
        status=status,
        sequences_config=config,
        sequences_part=part,
        split_use=split_use,
        sequences_datasets=reading,
        glance=_glance(index, sequences),
        fixed_set=fixed_set,
        layout="\n".join(layout),
        foregrounds=f"{index[FOREGROUNDS]['items']:,}",
        backgrounds=f"{index[BACKGROUNDS]['items']:,}",
        fg_train=f"{counts[FOREGROUNDS, TRAIN]:,}",
        fg_test=f"{counts[FOREGROUNDS, TEST]:,}",
        bg_train=f"{counts[BACKGROUNDS, TRAIN]:,}",
        bg_test=f"{counts[BACKGROUNDS, TEST]:,}",
        fg_side=index[FOREGROUNDS]["side"],
        bg_side=index[BACKGROUNDS]["side"],
        total_gb=_gb(sum(s["bytes"] for s in all_shards)),
        largest_gb=_gb(max((s["bytes"] for s in all_shards), default=0)),
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


def _downloader(repo: str, revision: str | None) -> Callable[[str, str], Path]:
    """Download a file of the dataset ``repo`` into a folder, and return its path there."""
    from huggingface_hub import hf_hub_download

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

    return download


def _mark(fetched: Path, name: str) -> Path:
    """The file that marks the repository's file ``name`` as unpacked."""
    return fetched / f"{name.replace('/', '-')}.done"


def fetch(repo: str, library_root: Path, revision: str | None = None) -> list[str]:
    """Download the shards of the Hugging Face dataset ``repo`` and unpack them one by one.

    A shard already marked in ``library_root/.fetched`` is skipped. Return the shards that
    the index lists and the repository does not hold yet.
    """
    from huggingface_hub.errors import EntryNotFoundError

    download = _downloader(repo, revision)
    fetched = library_root / FETCHED
    fetched.mkdir(parents=True, exist_ok=True)
    missing: list[str] = []
    with tempfile.TemporaryDirectory(dir=library_root) as folder:
        index = json.loads(download(INDEX, folder).read_text(encoding="utf-8"))
        for kind in (FOREGROUNDS, BACKGROUNDS):
            for shard in index[kind]["shards"]:
                name = f"{LIBRARY}/{shard['file']}"
                done = _mark(fetched, name)
                if done.exists():
                    continue
                try:
                    path = download(name, folder)
                except EntryNotFoundError:
                    missing.append(shard["file"])
                    continue
                with tarfile.open(path) as tar:
                    _unpack(tar, library_root / kind)
                path.unlink()
                done.touch()
    return missing


def _sequence_members(seq_dir: Path, seq_id: str) -> list[tuple[str, Path]]:
    """A sequence's files and the names they take in a shard, stream by stream."""
    members = []
    for stream in STREAMS:
        folder = seq_dir / stream
        if not folder.is_dir():
            continue
        for frame in sorted(folder.iterdir()):
            if frame.name == FOCUS and stream == "bokeh":
                members.append((f"{seq_id}.{FOCUS}", frame))
            elif frame.suffix[1:] in FRAME_TYPES:
                members.append((f"{seq_id}.{stream}.{frame.name}", frame))
    return members


def _read_csv(path: Path) -> list[dict[str, str]]:
    with path.open(encoding="utf-8", newline="") as f:
        return list(csv.DictReader(f))


def pack_sequences(
    data_root: Path,
    packed: Path,
    shard_bytes: int = SHARD_BYTES,
    repo: str = REPO,
) -> dict[str, Any]:
    """Write the fixed set that ``scenes.generate`` wrote in ``data_root`` into ``packed``.

    ``packed`` is a library ``pack`` wrote. Its ``sequences/`` gets the shards, the index
    and the run's records, and its card is written again with the fixed set in it. A shard
    holds whole sequences, one sample each: every file of sequence ``0001`` is a member
    ``0001.<stream>.<frame>``, with ``0001.focus.json`` for its bokeh's focus and
    ``0001.json`` for its row of ``manifest.csv`` and its rows of ``objects.csv``.
    """
    if not (packed / INDEX).is_file():
        raise SystemExit(f"no {INDEX} in {packed}: pack the library there first")
    if not (data_root / "manifest.csv").is_file():
        raise SystemExit(f"no manifest.csv in {data_root}: not a finished Stage B run")
    flags = json.loads((data_root / "run.json").read_text(encoding="utf-8"))["flags"]
    split = flags.get("split")
    if split != TEST:
        raise SystemExit(
            f"{data_root} drew its assets from {split or 'every asset'}: the card "
            "describes a fixed set of test assets"
        )
    out = packed / SEQUENCES
    if out.exists() and any(out.iterdir()):
        raise SystemExit(
            f"{out} is not empty: pack_sequences writes into an empty folder"
        )
    rows = _read_csv(data_root / "manifest.csv")
    objects = _read_csv(data_root / "objects.csv")
    if not rows:
        raise SystemExit(f"{data_root} wrote no sequences")
    # Every sequence is checked before a byte is written, so a refused run costs no copy.
    sequences: list[tuple[str, list[tuple[str, Path]]]] = []
    for row in rows:
        seq_id = row["seq_id"]
        if not (data_root / "sequences" / seq_id).is_dir():
            raise SystemExit(
                f"manifest.csv lists sequence {seq_id}, which is not there"
            )
        members = _sequence_members(data_root / "sequences" / seq_id, seq_id)
        sequences.append((seq_id, members))
    layout = [name.partition(".")[2] for name, _ in sequences[0][1]]
    streams = {name.split(".")[0] for name in layout}
    if lacking := [s for s in (*STREAMS, "focus") if s not in streams]:
        raise SystemExit(
            f"{data_root} has no {', '.join(lacking)}: the card describes a fixed set "
            "written with --bokeh --flow --flow-back --occlusion"
        )
    for seq_id, members in sequences[1:]:
        if [name.partition(".")[2] for name, _ in members] != layout:
            raise SystemExit(
                f"sequence {seq_id} holds other files than {rows[0]['seq_id']}: every "
                "sample of a WebDataset subset must hold the same ones"
            )
    out.mkdir(parents=True, exist_ok=True)
    shards: list[dict[str, Any]] = []
    tar: tarfile.TarFile | None = None
    size = 0
    for row, (seq_id, members) in zip(rows, sequences, strict=True):
        if tar is None or size >= shard_bytes:
            if tar is not None:
                tar.close()
            name = f"{TEST}-{len(shards):05d}.tar"
            shards.append({"file": name, "split": TEST, "items": 0})
            tar = tarfile.open(out / name, "w")
            size = 0
        for name, path in members:
            tar.add(path, arcname=name)
            size += path.stat().st_size
        record = json.dumps(
            {**row, "objects": [o for o in objects if o["seq_id"] == seq_id]},
            indent=1,
        ).encode()
        member = tarfile.TarInfo(f"{seq_id}.json")
        member.size = len(record)
        member.mtime = int((data_root / "manifest.csv").stat().st_mtime)
        tar.addfile(member, io.BytesIO(record))
        size += len(record)
        shards[-1]["items"] += 1
    if tar is not None:
        tar.close()
    for shard in shards:
        shard["bytes"] = (out / shard["file"]).stat().st_size
    placed = [int(row["n_objects"]) for row in rows]
    index = {
        "items": len(rows),
        "frames": int(rows[0]["n_frames"]),
        "size": int(rows[0]["size"]),
        "objects": [min(placed), max(placed)],
        "streams": list(STREAMS),
        "bokeh_strength": flags["bokeh_strength"],
        "shards": shards,
    }
    (packed / SEQUENCE_INDEX).write_text(
        json.dumps(index, indent=1) + "\n", encoding="utf-8"
    )
    for record_name in RECORDS:
        shutil.copyfile(data_root / record_name, out / record_name)
    library = json.loads((packed / INDEX).read_text(encoding="utf-8"))
    (packed / "README.md").write_text(
        card(library, repo, (packed / PREVIEW).is_file(), sequences=index),
        encoding="utf-8",
    )
    return index


def _unpack_sequences(tar: tarfile.TarFile, sequences_root: Path) -> None:
    """Write a shard's sequences into ``sequences_root`` as ``<id>/<stream>/<frame>``.

    Each sequence's ``focus.json`` goes back into its ``bokeh/``, and its record is
    skipped, since the run's records are fetched whole. A member that is not a plain file
    named as ``pack_sequences`` names it is refused, so a shard cannot write outside
    ``sequences_root``.
    """
    for member in tar:
        key, _, suffix = member.name.partition(".")
        parts = suffix.split(".")
        if not member.isfile() or not key or "/" in key:
            raise SystemExit(f"unexpected member {member.name!r} in a sequence shard")
        if suffix == "json":
            continue
        if suffix == FOCUS:
            target = sequences_root / key / "bokeh" / FOCUS
        elif (
            len(parts) == 3
            and parts[0] in STREAMS
            and parts[1].isdigit()
            and parts[2] in FRAME_TYPES
        ):
            target = sequences_root / key / parts[0] / f"{parts[1]}.{parts[2]}"
        else:
            raise SystemExit(f"unexpected member {member.name!r} in a sequence shard")
        target.parent.mkdir(parents=True, exist_ok=True)
        source = tar.extractfile(member)
        assert source is not None  # a plain file always has its bytes
        with source, target.open("wb") as out:
            shutil.copyfileobj(source, out)


def fetch_sequences(repo: str, output: Path, revision: str | None = None) -> list[str]:
    """Download the fixed set of ``repo`` into ``output``, as ``scenes.generate`` wrote it.

    The shards are fetched and unpacked one at a time, as ``fetch`` does, and marked in
    ``output/.fetched``. The run's records come last, ``manifest.csv`` after the others,
    and only once every shard is in, so a ``manifest.csv`` marks a whole fixed set as it
    marks a finished run. Return the shards that the index lists and the repository does
    not hold yet.
    """
    from huggingface_hub.errors import EntryNotFoundError

    download = _downloader(repo, revision)
    fetched = output / FETCHED
    fetched.mkdir(parents=True, exist_ok=True)
    missing: list[str] = []
    with tempfile.TemporaryDirectory(dir=output) as folder:
        index = json.loads(download(SEQUENCE_INDEX, folder).read_text(encoding="utf-8"))
        for shard in index["shards"]:
            name = f"{SEQUENCES}/{shard['file']}"
            done = _mark(fetched, name)
            if done.exists():
                continue
            try:
                path = download(name, folder)
            except EntryNotFoundError:
                missing.append(shard["file"])
                continue
            with tarfile.open(path) as tar:
                _unpack_sequences(tar, output / SEQUENCES)
            path.unlink()
            done.touch()
        if not missing:
            for record_name in RECORDS:
                # Moved in whole, so a crash never leaves a partial manifest.csv behind.
                os.replace(
                    download(f"{SEQUENCES}/{record_name}", folder), output / record_name
                )
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
    sequencing = commands.add_parser(
        "pack-sequences",
        help="add a fixed set that scenes.generate wrote to a packed library",
    )
    sequencing.add_argument(
        "--data-root", type=Path, required=True, help="the run scenes.generate wrote"
    )
    sequencing.add_argument(
        "--packed", type=Path, required=True, help="the folder pack wrote"
    )
    sequencing.add_argument("--shard-gb", type=float, default=SHARD_BYTES / 10**9)
    sequencing.add_argument("--repo", default=REPO, help="named in the card's commands")
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
    fetching_sequences = commands.add_parser(
        "fetch-sequences", help="download the fixed set and unpack it"
    )
    fetching_sequences.add_argument(
        "--repo", required=True, help="a Hugging Face dataset repository"
    )
    fetching_sequences.add_argument(
        "--output", type=Path, required=True, help="the folder to write the run into"
    )
    fetching_sequences.add_argument("--revision", default=None)
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
    elif args.command == "pack-sequences":
        index = pack_sequences(
            args.data_root, args.packed, int(args.shard_gb * 10**9), args.repo
        )
        print(f"sequences: {index['items']} items in {len(index['shards'])} shards")
    elif args.command == "fetch-sequences":
        missing = fetch_sequences(args.repo, args.output, args.revision)
        print(f"Fixed set in {args.output}")
        if missing:
            print(
                f"{len(missing)} shards are not in the repository yet; fetch again later"
            )
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
