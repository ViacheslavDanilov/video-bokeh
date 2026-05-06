"""Analyze CLIP predictions on the full MAGICK set.

Reads ``backend/data/magick/predictions.csv`` and produces:

* Per-class (subject) and per-style top-1 distribution at multiple confidence
  thresholds.
* "Keep curves" along both axes:
    - subject keep = {person, animal, plant, food, object}
    - subject exclude = {text, effect}
    - style keep = {photo, render}
    - style exclude = {illustration, drawing, painting, cartoon}
* Joint subject × style heatmap at the working threshold and a 2D survival
  map over (subject_thr, style_thr).
* Score histograms for both axes.

All plots land under ``vault/attachments/2026-05-20-magick-distribution/``
so they can be referenced from the matching report. A JSON sidecar
``summary.json`` mirrors every numeric table for the report writer.
"""

from __future__ import annotations

import csv
import json
from collections import Counter
from pathlib import Path

import matplotlib.pyplot as plt
import numpy as np

ROOT = Path(__file__).resolve().parent.parent
PREDICTIONS = ROOT / "backend" / "data" / "magick" / "predictions.csv"
ATTACH_DIR = ROOT / "vault" / "attachments" / "2026-05-20-magick-distribution"
ATTACH_DIR.mkdir(parents=True, exist_ok=True)

SUBJECT_CLASSES = ["person", "animal", "plant", "food", "object", "text", "effect"]
KEEP_SUBJECTS = {"person", "animal", "plant", "food", "object"}
EXCLUDE_SUBJECTS = {"text", "effect"}
STYLE_CLASSES = ["photo", "illustration", "drawing", "painting", "render", "cartoon"]
KEEP_STYLES = {"photo", "render"}
EXCLUDE_STYLES = {"illustration", "drawing", "painting", "cartoon"}

THRESHOLDS = np.round(np.arange(0.0, 1.0001, 0.05), 2)
WORKING_SUBJ_THR = 0.50
WORKING_STYLE_THR = 0.50


def load_rows() -> list[dict]:
    with PREDICTIONS.open(newline="") as fh:
        return list(csv.DictReader(fh))


def _f(row: dict, key: str) -> float:
    return float(row[key])


def class_counts_at(
    rows: list[dict],
    thr: float,
    axis: str = "subject",
) -> dict[str, int]:
    score_key, label_key, classes = (
        ("top_subject_score", "top_subject", SUBJECT_CLASSES)
        if axis == "subject"
        else ("top_style_score", "top_style", STYLE_CLASSES)
    )
    counts: Counter[str] = Counter()
    for r in rows:
        if _f(r, score_key) >= thr:
            counts[r[label_key]] += 1
    return {c: counts.get(c, 0) for c in classes}


def joint_table(rows: list[dict], subj_thr: float, style_thr: float) -> dict:
    table: dict[str, dict[str, int]] = {
        c: dict.fromkeys(STYLE_CLASSES, 0) for c in SUBJECT_CLASSES
    }
    for r in rows:
        if (
            _f(r, "top_subject_score") < subj_thr
            or _f(r, "top_style_score") < style_thr
        ):
            continue
        table[r["top_subject"]][r["top_style"]] += 1
    return table


def keep_curve_subject(rows: list[dict]) -> dict:
    keep, exclude = [], []
    for thr in THRESHOLDS:
        k = sum(
            1
            for r in rows
            if r["top_subject"] in KEEP_SUBJECTS and _f(r, "top_subject_score") >= thr
        )
        e = sum(
            1
            for r in rows
            if r["top_subject"] in EXCLUDE_SUBJECTS
            and _f(r, "top_subject_score") >= thr
        )
        keep.append(k)
        exclude.append(e)
    return {"thresholds": THRESHOLDS.tolist(), "keep": keep, "exclude": exclude}


def keep_curve_style(rows: list[dict]) -> dict:
    keep, exclude = [], []
    for thr in THRESHOLDS:
        k = sum(
            1
            for r in rows
            if r["top_style"] in KEEP_STYLES and _f(r, "top_style_score") >= thr
        )
        e = sum(
            1
            for r in rows
            if r["top_style"] in EXCLUDE_STYLES and _f(r, "top_style_score") >= thr
        )
        keep.append(k)
        exclude.append(e)
    return {"thresholds": THRESHOLDS.tolist(), "keep": keep, "exclude": exclude}


def per_class_curve(rows: list[dict], axis: str) -> dict:
    score_key, label_key, classes = (
        ("top_subject_score", "top_subject", SUBJECT_CLASSES)
        if axis == "subject"
        else ("top_style_score", "top_style", STYLE_CLASSES)
    )
    out: dict[str, list[int]] = {c: [] for c in classes}
    for thr in THRESHOLDS:
        for c in classes:
            out[c].append(
                sum(1 for r in rows if r[label_key] == c and _f(r, score_key) >= thr),
            )
    return {"thresholds": THRESHOLDS.tolist(), "counts": out}


def joint_keep_count(rows: list[dict], subj_thr: float, style_thr: float) -> int:
    return sum(
        1
        for r in rows
        if r["top_subject"] in KEEP_SUBJECTS
        and r["top_style"] in KEEP_STYLES
        and _f(r, "top_subject_score") >= subj_thr
        and _f(r, "top_style_score") >= style_thr
    )


def joint_keep_breakdown(
    rows: list[dict],
    subj_thr: float,
    style_thr: float,
) -> dict[str, dict[str, int]]:
    out = {c: dict.fromkeys(KEEP_STYLES, 0) for c in KEEP_SUBJECTS}
    for r in rows:
        if (
            r["top_subject"] in KEEP_SUBJECTS
            and r["top_style"] in KEEP_STYLES
            and _f(r, "top_subject_score") >= subj_thr
            and _f(r, "top_style_score") >= style_thr
        ):
            out[r["top_subject"]][r["top_style"]] += 1
    return out


def survival_grid(rows: list[dict], step: float = 0.10) -> dict:
    grid_thr = np.round(np.arange(0.0, 1.0001, step), 2)
    grid = np.zeros((len(grid_thr), len(grid_thr)), dtype=int)
    for i, t_subj in enumerate(grid_thr):
        for j, t_style in enumerate(grid_thr):
            grid[i, j] = joint_keep_count(rows, float(t_subj), float(t_style))
    return {"thresholds": grid_thr.tolist(), "grid": grid.tolist()}


# ── plots ──────────────────────────────────────────────────────────────────────


def histogram(rows: list[dict], score_key: str, fname: str, title: str) -> None:
    scores = np.array([_f(r, score_key) for r in rows])
    fig, ax = plt.subplots(figsize=(8, 4.5))
    ax.hist(scores, bins=40, color="#3b7cb6", alpha=0.85, edgecolor="white")
    ax.axvline(
        WORKING_SUBJ_THR,
        ls="--",
        color="crimson",
        label=f"thr = {WORKING_SUBJ_THR}",
    )
    ax.set_title(title)
    ax.set_xlabel(f"{score_key} (softmax max)")
    ax.set_ylabel("# foregrounds")
    ax.set_xlim(0, 1)
    ax.legend()
    fig.tight_layout()
    fig.savefig(ATTACH_DIR / fname, dpi=140)
    plt.close(fig)


def stacked_keep_plot(
    curve: dict,
    fname: str,
    title: str,
    xlabel: str,
    total: int,
) -> None:
    thr = np.array(curve["thresholds"])
    keep = np.array(curve["keep"])
    exclude = np.array(curve["exclude"])
    fig, ax = plt.subplots(figsize=(8, 4.8))
    ax.fill_between(thr, 0, keep, color="#2ca02c", alpha=0.8, label="keep")
    ax.fill_between(
        thr,
        keep,
        keep + exclude,
        color="#d62728",
        alpha=0.65,
        label="exclude",
    )
    ax.axhline(total, ls=":", color="grey", label=f"total = {total}")
    ax.axvline(
        WORKING_SUBJ_THR,
        ls="--",
        color="black",
        alpha=0.6,
        label=f"working thr = {WORKING_SUBJ_THR}",
    )
    ax.set_xlabel(xlabel)
    ax.set_ylabel("# foregrounds with score ≥ thr")
    ax.set_title(title)
    ax.set_xlim(0, 1)
    ax.set_ylim(0, total * 1.05)
    ax.legend(loc="upper right")
    fig.tight_layout()
    fig.savefig(ATTACH_DIR / fname, dpi=140)
    plt.close(fig)


def per_class_curve_plot(curve: dict, axis: str, fname: str) -> None:
    keep_set = KEEP_SUBJECTS if axis == "subject" else KEEP_STYLES
    thr = np.array(curve["thresholds"])
    fig, ax = plt.subplots(figsize=(8, 4.8))
    classes = list(curve["counts"].keys())
    palette = plt.cm.tab10.colors
    for i, c in enumerate(classes):
        counts = np.array(curve["counts"][c])
        emphasis = c in keep_set
        ax.plot(
            thr,
            counts,
            label=c,
            color=palette[i % len(palette)],
            lw=2.4 if emphasis else 1.4,
            ls="-" if emphasis else "--",
        )
    ax.axvline(WORKING_SUBJ_THR, ls=":", color="black", alpha=0.6)
    ax.set_xlabel(f"top_{'score' if axis == 'subject' else 'style_score'} threshold")
    ax.set_ylabel("# foregrounds")
    ax.set_yscale("log")
    ax.set_title(f"{axis.capitalize()} class survival vs threshold (log y)")
    ax.set_xlim(0, 1)
    ax.legend(ncol=2)
    fig.tight_layout()
    fig.savefig(ATTACH_DIR / fname, dpi=140)
    plt.close(fig)


def joint_heatmap(table: dict, fname: str, title: str) -> None:
    matrix = np.array([[table[c][s] for s in STYLE_CLASSES] for c in SUBJECT_CLASSES])
    fig, ax = plt.subplots(figsize=(8.5, 5.2))
    im = ax.imshow(matrix, cmap="viridis", aspect="auto")
    ax.set_xticks(range(len(STYLE_CLASSES)), STYLE_CLASSES)
    ax.set_yticks(range(len(SUBJECT_CLASSES)), SUBJECT_CLASSES)
    for i, c in enumerate(SUBJECT_CLASSES):
        for j, s in enumerate(STYLE_CLASSES):
            v = matrix[i, j]
            text_colour = "white" if v < matrix.max() * 0.5 else "black"
            ax.text(
                j,
                i,
                str(v),
                ha="center",
                va="center",
                color=text_colour,
                fontsize=9,
            )
            if c in KEEP_SUBJECTS and s in KEEP_STYLES:
                ax.add_patch(
                    plt.Rectangle(
                        (j - 0.5, i - 0.5),
                        1,
                        1,
                        fill=False,
                        ec="lime",
                        lw=2,
                    ),
                )
    ax.set_title(title)
    fig.colorbar(im, ax=ax, label="# foregrounds")
    fig.tight_layout()
    fig.savefig(ATTACH_DIR / fname, dpi=140)
    plt.close(fig)


def survival_grid_plot(grid_data: dict, fname: str) -> None:
    thr = np.array(grid_data["thresholds"])
    grid = np.array(grid_data["grid"])
    fig, ax = plt.subplots(figsize=(7.5, 5.5))
    im = ax.imshow(grid, cmap="magma", aspect="auto", origin="lower")
    ax.set_xticks(range(len(thr)), [f"{t:.1f}" for t in thr])
    ax.set_yticks(range(len(thr)), [f"{t:.1f}" for t in thr])
    ax.set_xlabel("style threshold (top_style_score ≥)")
    ax.set_ylabel("subject threshold (top_subject_score ≥)")
    ax.set_title("Joint keep-set size — subject ∈ keep × style ∈ {photo, render}")
    for i in range(len(thr)):
        for j in range(len(thr)):
            v = grid[i, j]
            ax.text(
                j,
                i,
                str(v),
                ha="center",
                va="center",
                color="white" if v < grid.max() * 0.5 else "black",
                fontsize=8,
            )
    fig.colorbar(im, ax=ax, label="# foregrounds in keep-set")
    fig.tight_layout()
    fig.savefig(ATTACH_DIR / fname, dpi=140)
    plt.close(fig)


def keep_breakdown_plot(rows: list[dict], fname: str) -> None:
    """Per-class breakdown of the keep-set as the subject threshold varies, style ≥ 0."""
    fig, ax = plt.subplots(figsize=(8.5, 5.0))
    keep_subjs_ordered = ["person", "object", "food", "plant", "animal"]
    palette = plt.cm.Set2.colors
    bottom = np.zeros(len(THRESHOLDS))
    for i, c in enumerate(keep_subjs_ordered):
        counts = np.array(
            [
                sum(
                    1
                    for r in rows
                    if r["top_subject"] == c
                    and r["top_style"] in KEEP_STYLES
                    and _f(r, "top_subject_score") >= float(t)
                )
                for t in THRESHOLDS
            ],
        )
        ax.fill_between(
            THRESHOLDS,
            bottom,
            bottom + counts,
            color=palette[i],
            alpha=0.85,
            label=c,
        )
        bottom = bottom + counts
    ax.axvline(
        WORKING_SUBJ_THR,
        ls="--",
        color="black",
        alpha=0.6,
        label=f"working thr = {WORKING_SUBJ_THR}",
    )
    ax.set_xlim(0, 1)
    ax.set_xlabel(
        "subject top_subject_score threshold (style filtered to {photo, render}, no style threshold)",
    )
    ax.set_ylabel("# foregrounds in keep-set")
    ax.set_title("Per-class composition of the keep-set vs subject threshold")
    ax.legend(loc="upper right")
    fig.tight_layout()
    fig.savefig(ATTACH_DIR / fname, dpi=140)
    plt.close(fig)


# ── main ───────────────────────────────────────────────────────────────────────


def main() -> None:
    rows = load_rows()
    n_total = len(rows)

    histogram(
        rows,
        "top_subject_score",
        "score_hist_subject.png",
        "Subject top_subject_score histogram (full MAGICK)",
    )
    histogram(
        rows,
        "top_style_score",
        "score_hist_style.png",
        "Style top_style_score histogram (full MAGICK)",
    )

    subj_keep = keep_curve_subject(rows)
    style_keep = keep_curve_style(rows)
    stacked_keep_plot(
        subj_keep,
        "keep_vs_threshold_subject.png",
        "MAGICK subject-axis survival (keep = person/animal/plant/food/object)",
        "top_subject_score threshold",
        n_total,
    )
    stacked_keep_plot(
        style_keep,
        "keep_vs_threshold_style.png",
        "MAGICK style-axis survival (keep = photo/render)",
        "top_style_score threshold",
        n_total,
    )

    subj_curve = per_class_curve(rows, "subject")
    style_curve = per_class_curve(rows, "style")
    per_class_curve_plot(subj_curve, "subject", "subject_classes_vs_threshold.png")
    per_class_curve_plot(style_curve, "style", "style_classes_vs_threshold.png")

    keep_breakdown_plot(rows, "keep_set_composition.png")

    joint_050 = joint_table(rows, WORKING_SUBJ_THR, WORKING_STYLE_THR)
    joint_heatmap(
        joint_050,
        "joint_subject_style_thr050.png",
        f"Subject × Style at thr ≥ {WORKING_SUBJ_THR} (green = keep cells)",
    )
    joint_070 = joint_table(rows, 0.70, 0.70)
    joint_heatmap(
        joint_070,
        "joint_subject_style_thr070.png",
        "Subject × Style at thr ≥ 0.70 (green = keep cells)",
    )

    grid = survival_grid(rows, step=0.10)
    survival_grid_plot(grid, "survival_grid.png")

    # convenient at-a-glance keep-set sizes
    keep_set_at_thresholds = {
        f"{t:.2f}": joint_keep_count(rows, float(t), 0.0) for t in THRESHOLDS
    }
    keep_set_at_thresholds_with_style = {
        f"{t:.2f}": joint_keep_count(rows, float(t), float(t)) for t in THRESHOLDS
    }

    summary = {
        "n_total": n_total,
        "policy": {
            "keep_subjects": sorted(KEEP_SUBJECTS),
            "exclude_subjects": sorted(EXCLUDE_SUBJECTS),
            "keep_styles": sorted(KEEP_STYLES),
            "exclude_styles": sorted(EXCLUDE_STYLES),
        },
        "thresholds": THRESHOLDS.tolist(),
        "subject_counts_at_thresholds": {
            f"{t:.2f}": class_counts_at(rows, float(t), "subject") for t in THRESHOLDS
        },
        "style_counts_at_thresholds": {
            f"{t:.2f}": class_counts_at(rows, float(t), "style") for t in THRESHOLDS
        },
        "subject_keep_curve": subj_keep,
        "style_keep_curve": style_keep,
        "subject_per_class_curve": subj_curve,
        "style_per_class_curve": style_curve,
        "joint_thr050": joint_050,
        "joint_thr070": joint_070,
        "joint_thr080": joint_table(rows, 0.80, 0.80),
        "keep_set_subject_only": keep_set_at_thresholds,
        "keep_set_subject_and_style": keep_set_at_thresholds_with_style,
        "keep_breakdown_thr050": joint_keep_breakdown(
            rows,
            WORKING_SUBJ_THR,
            WORKING_STYLE_THR,
        ),
        "keep_breakdown_thr050_no_style_thr": joint_keep_breakdown(
            rows,
            WORKING_SUBJ_THR,
            0.0,
        ),
        "survival_grid": grid,
    }

    (ATTACH_DIR / "summary.json").write_text(json.dumps(summary, indent=2))
    print(json.dumps({"n_total": n_total, "out_dir": str(ATTACH_DIR)}, indent=2))


if __name__ == "__main__":
    main()
