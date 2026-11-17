"""How a stored layer image is oriented relative to the canonical top view.

A slicer stores each layer as the printer's panel reads it, which can be the top view flipped or
turned. The eight possibilities are the symmetries of the square (the dihedral group D4). Each is
named by what it does to the canonical image to give the stored one:

==================  ==================================================
``identity``        unchanged
``rotate_90``       turned 90° counter-clockwise (as displayed)
``rotate_180``      turned 180°
``rotate_270``      turned 90° clockwise
``mirror_x``        mirrored along X (columns reversed)
``mirror_y``        mirrored along Y (rows reversed)
``transpose``       rows become columns
``antitranspose``   transposed across the other diagonal
==================  ==================================================
"""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

import numpy as np
from numpy.typing import NDArray

ORIENTATIONS: tuple[str, ...] = (
    "identity",
    "rotate_90",
    "rotate_180",
    "rotate_270",
    "mirror_x",
    "mirror_y",
    "transpose",
    "antitranspose",
)

_INVERSE = {name: name for name in ORIENTATIONS} | {
    "rotate_90": "rotate_270",
    "rotate_270": "rotate_90",
}

_ARRAY_TRANSFORMS: dict[str, Callable[[NDArray[Any]], NDArray[Any]]] = {
    "identity": lambda a: a,
    "rotate_90": lambda a: np.rot90(a, 1),
    "rotate_180": lambda a: np.rot90(a, 2),
    "rotate_270": lambda a: np.rot90(a, 3),
    "mirror_x": lambda a: a[:, ::-1],
    "mirror_y": lambda a: a[::-1, :],
    "transpose": lambda a: a.T,
    "antitranspose": lambda a: np.rot90(a, 2).T,
}

# Minimum lead of the best orientation's overlap over the second best for a confident answer.
# Distinct orientations of a chiral model differ by far more (tens of percent); symmetric models
# tie, and centring noise moves overlaps by well under 0.05.
AMBIGUITY_MARGIN = 0.05


def inverse(name: str) -> str:
    """The orientation that undoes ``name``."""
    return _INVERSE[name]


def apply(image: NDArray[Any], name: str) -> NDArray[Any]:
    """``image`` transformed by orientation ``name`` (a view when possible)."""
    return _ARRAY_TRANSFORMS[name](image)


def map_point(row: float, col: float, shape: tuple[int, int], name: str) -> tuple[float, float]:
    """Where continuous pixel coordinates ``(row, col)`` of an image of ``shape`` go under ``name``.

    Coordinates are continuous: pixel ``(i, j)`` spans ``[i, i + 1) × [j, j + 1)``.
    """
    rows, cols = shape
    if name == "identity":
        return row, col
    if name == "rotate_90":
        return cols - col, row
    if name == "rotate_180":
        return rows - row, cols - col
    if name == "rotate_270":
        return col, rows - row
    if name == "mirror_x":
        return row, cols - col
    if name == "mirror_y":
        return rows - row, col
    if name == "transpose":
        return col, row
    if name == "antitranspose":
        return cols - col, rows - row
    raise KeyError(name)


def transformed_shape(shape: tuple[int, int], name: str) -> tuple[int, int]:
    rows, cols = shape
    return (
        (cols, rows)
        if name in {"rotate_90", "rotate_270", "transpose", "antitranspose"}
        else (rows, cols)
    )


def crop_to_content(mask: NDArray[np.bool_]) -> NDArray[np.bool_]:
    """The smallest sub-array holding every true pixel (empty when there is none)."""
    rows = np.flatnonzero(mask.any(axis=1))
    cols = np.flatnonzero(mask.any(axis=0))
    if len(rows) == 0:
        return mask[:0, :0]
    return mask[rows[0] : rows[-1] + 1, cols[0] : cols[-1] + 1]


def aligned_iou(a: NDArray[np.bool_], b: NDArray[np.bool_]) -> float:
    """Intersection over union of two masks after moving ``b`` so the centroids coincide (to the
    nearest pixel). Zero when either is empty."""
    if not a.any() or not b.any():
        return 0.0
    ca = np.argwhere(a).mean(axis=0)
    cb = np.argwhere(b).mean(axis=0)
    shift = np.rint(ca - cb).astype(int)
    top = min(0, shift[0])
    left = min(0, shift[1])
    height = max(a.shape[0], b.shape[0] + shift[0]) - top
    width = max(a.shape[1], b.shape[1] + shift[1]) - left
    canvas_a = np.zeros((height, width), dtype=bool)
    canvas_b = np.zeros((height, width), dtype=bool)
    canvas_a[-top : -top + a.shape[0], -left : -left + a.shape[1]] = a
    canvas_b[
        shift[0] - top : shift[0] - top + b.shape[0], shift[1] - left : shift[1] - left + b.shape[1]
    ] = b
    union = np.count_nonzero(canvas_a | canvas_b)
    return float(np.count_nonzero(canvas_a & canvas_b) / union)


def estimate(
    reference_silhouette: NDArray[np.bool_], stored_silhouette: NDArray[np.bool_]
) -> dict[str, Any]:
    """The orientation that turns the reference silhouette into the stored one.

    Both are union-of-layers masks. Every orientation of the cropped reference is compared with
    the cropped stored silhouette by :func:`aligned_iou`. The answer is ``ambiguous`` when the best
    leads the second best by less than :data:`AMBIGUITY_MARGIN` (a symmetric model).
    """
    reference = crop_to_content(reference_silhouette)
    stored = crop_to_content(stored_silhouette)
    scores = {name: aligned_iou(stored, apply(reference, name)) for name in ORIENTATIONS}
    ranked = sorted(ORIENTATIONS, key=lambda name: (-scores[name], ORIENTATIONS.index(name)))
    best, second = ranked[0], ranked[1]
    margin = scores[best] - scores[second]
    return {
        "best": best,
        "iou": scores[best],
        "margin": margin,
        "ambiguous": margin < AMBIGUITY_MARGIN,
        "scores": scores,
    }
