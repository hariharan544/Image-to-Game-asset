"""Cut multi-view sheets (2x2: front / left / back / right) into one image per view.

Each view is re-centred on its object and every view of a sheet gets the same crop
size, so the object keeps the same scale in all views (what Tripo multi-view expects).
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

import numpy as np
from PIL import Image

IMAGE_EXT = {".png", ".jpg", ".jpeg", ".webp"}
DEFAULT_NAMES = ["front", "left", "back", "right"]


@dataclass
class SheetResult:
    source: Path
    outputs: list[Path] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)


def _background(a: np.ndarray) -> np.ndarray:
    border = np.concatenate([a[0], a[-1], a[:, 0], a[:, -1]])
    return np.median(border, axis=0)


def _bbox(mask: np.ndarray):
    ys, xs = np.nonzero(mask)
    if len(xs) == 0:
        return None
    return xs.min(), ys.min(), xs.max() + 1, ys.max() + 1


def split_sheet(path: Path, out_dir: Path, rows: int = 2, cols: int = 2, names=None,
                margin: float = 0.08, threshold: float = 30.0) -> SheetResult:
    names = list(names or DEFAULT_NAMES)
    res = SheetResult(Path(path))
    if len(names) != rows * cols:
        raise ValueError(f"{rows}x{cols} grid needs {rows * cols} names, got {len(names)}")
    img = Image.open(path).convert("RGB")
    a = np.asarray(img).astype(np.float32)
    bg = _background(a)
    diff = np.abs(a - bg).max(axis=2) > threshold
    h, w = diff.shape
    cells = []
    for r in range(rows):
        for c in range(cols):
            y0, y1 = r * h // rows, (r + 1) * h // rows
            x0, x1 = c * w // cols, (c + 1) * w // cols
            box = _bbox(diff[y0:y1, x0:x1])
            name = names[r * cols + c]
            if box is None or (box[2] - box[0]) * (box[3] - box[1]) < 0.002 * (x1 - x0) * (y1 - y0):
                res.warnings.append(f"{name}: cell is empty - the sheet may not be a {rows}x{cols} grid")
                cells.append(None)
                continue
            bx0, by0, bx1, by1 = box
            if bx0 == 0 or by0 == 0 or bx1 == x1 - x0 or by1 == y1 - y0:
                res.warnings.append(f"{name}: object touches the cell edge (views overlap or are cut off)")
            cells.append((name, x0 + bx0, y0 + by0, x0 + bx1, y0 + by1))
    found = [c for c in cells if c]
    if not found:
        return res
    # one square crop size for the whole sheet -> same scale in every view
    side = int(max(max(x1 - x0, y1 - y0) for _, x0, y0, x1, y1 in found) * (1 + 2 * margin))
    fill = tuple(int(v) for v in bg)
    out_dir.mkdir(parents=True, exist_ok=True)
    stem = Path(path).stem
    for name, x0, y0, x1, y1 in found:
        cx, cy = (x0 + x1) // 2, (y0 + y1) // 2
        canvas = Image.new("RGB", (side, side), fill)
        left, top = cx - side // 2, cy - side // 2
        # the object's bounding box (not the neighbour views) is copied onto a clean background
        piece = img.crop((x0, y0, x1, y1))
        canvas.paste(piece, (x0 - left, y0 - top))
        out = out_dir / f"{stem}_{name}.png"
        canvas.save(out)
        res.outputs.append(out)
    return res


def find_sheets(inputs: list[str]) -> list[Path]:
    found = []
    for i in inputs:
        p = Path(i)
        if p.is_dir():
            found += sorted(f for f in p.iterdir() if f.suffix.lower() in IMAGE_EXT)
        elif p.suffix.lower() in IMAGE_EXT and p.exists():
            found.append(p)
        else:
            raise FileNotFoundError(f"not an image or folder: {i}")
    return found
