"""
generate_synthetic_gallery.py - Unified 100% Synthetic Mathematical Demo Generator for SciOrigin v8.0.

Generates all 43 publication-ready showcase figures directly in headless OriginPro 2024 (`skip_origin=False`)
across five modular showcase suites — zero external or private data files required:
  - Part 1 (`gallery_part1_characterization.py`): 9 characterization & deconvolution pipelines
  - Part 2 (`gallery_part2_electrochem.py`): 7 electrochemistry, composite 2x2 & operando 2D pipelines
  - Part 3 (`gallery_part3_declarative.py`): 11 dual-theme, statistical, regression & matrix grammar demos
  - Part 4 (`gallery_part4_cross_science.py`): 6 cross-science (bio/omics/pharma/catalysis/ML) grammar demos
  - Part 5 (`gallery_part5_hard_and_noncartesian.py`): 10 clinical survival/ROC, NMR, broken-axis, dual-X, ternary, polar/radar, multi-track & vector-quiver demos

Usage:
    python examples/generate_synthetic_gallery.py
    python examples/generate_synthetic_gallery.py --part 3
    python examples/generate_synthetic_gallery.py --part 4
    python examples/generate_synthetic_gallery.py --part 5
    python examples/generate_synthetic_gallery.py --part all
"""
from __future__ import annotations

import argparse
import importlib
import sys
from pathlib import Path
from typing import List

EXAMPLES_DIR = Path(__file__).resolve().parent
REPO_ROOT = EXAMPLES_DIR.parent
GALLERY_DIR = REPO_ROOT / "assets" / "gallery"

if str(EXAMPLES_DIR) not in sys.path:
    sys.path.insert(0, str(EXAMPLES_DIR))

_PART_SPECS = (
    ("1", "gallery_part1_characterization", "generate_part1"),
    ("2", "gallery_part2_electrochem", "generate_part2"),
    ("3", "gallery_part3_declarative", "generate_part3"),
    ("4", "gallery_part4_cross_science", "generate_part4"),
    ("5", "gallery_part5_hard_and_noncartesian", "generate_part5"),
)


def run_gallery_parts(part: str = "all", gallery_dir: Path = GALLERY_DIR) -> List[Path]:
    """Dynamically import and execute the requested synthetic gallery generation part(s)."""
    gallery_dir = Path(gallery_dir).resolve()
    gallery_dir.mkdir(parents=True, exist_ok=True)
    generated: List[Path] = []

    for part_id, mod_name, fn_name in _PART_SPECS:
        if part not in ("all", part_id):
            continue
        try:
            mod = importlib.import_module(mod_name)
        except ModuleNotFoundError:
            if part != part_id:
                print(f"[Gallery] Skipping missing module {mod_name} ...", flush=True)
                continue
            raise
        gen_fn = getattr(mod, fn_name)
        paths = gen_fn(gallery_dir)
        generated.extend(Path(p) for p in paths)

    print(f"[Gallery] Completed {len(generated)} figure(s) in {gallery_dir}", flush=True)
    return generated


def audit_gallery_nyquist_and_composite_frames(gallery_dir: Path = GALLERY_DIR) -> None:
    """Mechanical pixel-frame guard ensuring EIS Nyquist & 2x2 composite panels never regress to 1:1 square boxes."""
    import numpy as np
    from PIL import Image

    gallery_dir = Path(gallery_dir).resolve()
    for name in ("demo_nyquist_tnr.jpg", "demo_nyquist_arial.jpg", "demo_dual_y_tnr.jpg"):
        img_p = gallery_dir / name
        if not img_p.exists():
            continue
        gray = np.asarray(Image.open(img_p).convert("L"))
        dark = gray < 90
        rows = np.where(dark.mean(axis=1) > 0.35)[0]
        cols = np.where(dark.mean(axis=0) > 0.35)[0]
        if len(rows) < 2 or len(cols) < 2:
            raise AssertionError(f"[FrameGuard] Could not detect closed box frame in {img_p}")
        ratio = float(cols[-1] - cols[0]) / max(float(rows[-1] - rows[0]), 1.0)
        if abs(ratio - (4.0 / 3.0)) > 0.025:
            raise AssertionError(
                f"[FrameGuard] {name} inner frame ratio is {ratio:.4f} (expected 4:3 = 1.3333). "
                "Fix: use standard box_rect_w_in x box_rect_h_in (6.40 x 4.80 in) with 4:3 isometric bounds."
            )

    hero_p = gallery_dir / "demo_hero_composite_2x2.jpg"
    if hero_p.exists():
        gray = np.asarray(Image.open(hero_p).convert("L"))
        h, w = gray.shape
        quads = {
            "a": gray[: h // 2, : w // 2],
            "b": gray[: h // 2, w // 2 :],
            "c": gray[h // 2 :, : w // 2],
            "d": gray[h // 2 :, w // 2 :],
        }
        boxes = {}
        for k, q in quads.items():
            dk = q < 90
            rs = np.where(dk.mean(axis=1) > 0.35)[0]
            cs = np.where(dk.mean(axis=0) > 0.35)[0]
            if len(rs) < 2 or len(cs) < 2:
                raise AssertionError(f"[FrameGuard] Missing closed box border in hero panel ({k}) of {hero_p}")
            boxes[k] = (int(cs[0]), int(cs[-1]), int(rs[0]), int(rs[-1]))
            q_ratio = float(cs[-1] - cs[0]) / max(float(rs[-1] - rs[0]), 1.0)
            if abs(q_ratio - (4.0 / 3.0)) > 0.03:
                raise AssertionError(
                    f"[FrameGuard] Hero composite panel ({k}) ratio is {q_ratio:.4f} (expected 4:3 = 1.3333). "
                    "Fix: ensure build_composite_opju MasterComposite uses c_box_in (4.10 x 3.075 in) for nyquist too."
                )
        if abs(boxes["b"][0] - boxes["d"][0]) > 3 or abs(boxes["b"][1] - boxes["d"][1]) > 3:
            raise AssertionError(
                f"[FrameGuard] Hero panels (b)={boxes['b'][:2]} and (d)={boxes['d'][:2]} horizontal borders misaligned! "
                "Fix: align nyquist panel to c_left_in / rect_c in build_composite_opju."
            )


def main(argv: List[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Generate 100% synthetic SciOrigin v8.0 showcase figures via headless OriginPro 2024."
    )
    parser.add_argument(
        "--part",
        choices=("1", "2", "3", "4", "5", "all"),
        default="all",
        help="Which gallery part to render: 1 (characterization), 2 (electrochem), 3 (declarative), 4 (cross-science), 5 (hard & non-Cartesian), or all.",
    )
    parser.add_argument(
        "--gallery-dir",
        type=Path,
        default=GALLERY_DIR,
        help="Destination directory for rendered gallery JPEG files.",
    )
    parser.add_argument(
        "--verify-only",
        action="store_true",
        help="Run mechanical frame geometry guard on existing gallery JPEGs without launching OriginPro.",
    )
    args = parser.parse_args(argv)
    if not args.verify_only:
        run_gallery_parts(part=args.part, gallery_dir=args.gallery_dir)
    audit_gallery_nyquist_and_composite_frames(args.gallery_dir)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
