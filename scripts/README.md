# Scripts

These scripts set up model environments, check the prose of a change, and analyze the source
data.
Run commands from the repository root.

## Set up Depth Anything 3

`setup_depth_anything_3.sh` creates the Python 3.12 environment used by the local DA3
estimators. See [Depth Anything 3's own environment](../docs/reference/cli.md#depth-anything-3s-own-environment).

## Check the prose of a change

`check_prose.py` flags the paragraphs of changed Markdown that read as machine-written: any
em dash, offline, and, when `TYPESAFE_API_KEY` is set, those that Jev, TypeSafe's classifier,
scores at 0.6 or more. It sends those paragraphs to api.typesafe.ai, so run it on public text
only. `/bokeh-review` runs it as its prose lens.

```bash
python3 scripts/check_prose.py                  # Markdown changed since origin/main
python3 scripts/check_prose.py docs/STYLE.md    # every paragraph of a file
```

## Analyze the MAGICK filter

`analyze_magick_distribution.py` plots the CLIP keep curves and writes `summary.json` under
`docs/attachments/2026-05-20-magick-distribution/`. See
[Source datasets](../docs/explanation/datasets.md#magick-foregrounds) for the source and filter.

```bash
uv run python scripts/analyze_magick_distribution.py
```
