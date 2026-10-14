"""Box helpers (pixel xyxy)."""

from __future__ import annotations

import numpy as np


def iou_matrix(a: np.ndarray, b: np.ndarray) -> np.ndarray:
    if len(a) == 0 or len(b) == 0:
        return np.zeros((len(a), len(b)))
    a, b = np.asarray(a, float), np.asarray(b, float)
    x1 = np.maximum(a[:, None, 0], b[None, :, 0])
    y1 = np.maximum(a[:, None, 1], b[None, :, 1])
    x2 = np.minimum(a[:, None, 2], b[None, :, 2])
    y2 = np.minimum(a[:, None, 3], b[None, :, 3])
    inter = np.clip(x2 - x1, 0, None) * np.clip(y2 - y1, 0, None)
    area_a = (a[:, 2] - a[:, 0]) * (a[:, 3] - a[:, 1])
    area_b = (b[:, 2] - b[:, 0]) * (b[:, 3] - b[:, 1])
    return inter / np.maximum(area_a[:, None] + area_b[None, :] - inter, 1e-9)


def inside_fraction(a: np.ndarray, b: np.ndarray) -> np.ndarray:
    """[i, j] = share of box b[j]'s area that lies inside box a[i]."""
    if len(a) == 0 or len(b) == 0:
        return np.zeros((len(a), len(b)))
    a, b = np.asarray(a, float), np.asarray(b, float)
    x1 = np.maximum(a[:, None, 0], b[None, :, 0])
    y1 = np.maximum(a[:, None, 1], b[None, :, 1])
    x2 = np.minimum(a[:, None, 2], b[None, :, 2])
    y2 = np.minimum(a[:, None, 3], b[None, :, 3])
    inter = np.clip(x2 - x1, 0, None) * np.clip(y2 - y1, 0, None)
    area_b = (b[:, 2] - b[:, 0]) * (b[:, 3] - b[:, 1])
    return inter / np.maximum(area_b[None, :], 1e-9)


def nms(boxes: np.ndarray, scores: np.ndarray, iou_thresh: float, inside_thresh: float | None = None) -> list[int]:
    """Greedy class-agnostic non-maximum suppression; returns kept indices.

    With inside_thresh, a lower-scored box that lies mostly inside a kept box
    (for example a vehicle cut in half by a tile edge) is also dropped.
    """
    order = list(np.argsort(-np.asarray(scores)))
    keep: list[int] = []
    while order:
        i = order.pop(0)
        keep.append(int(i))
        if not order:
            break
        ious = iou_matrix(boxes[[i]], boxes[order])[0]
        if inside_thresh is None:
            order = [j for j, v in zip(order, ious) if v <= iou_thresh]
        else:
            inside = inside_fraction(boxes[[i]], boxes[order])[0]
            order = [j for j, v, f in zip(order, ious, inside) if v <= iou_thresh and f <= inside_thresh]
    return keep
