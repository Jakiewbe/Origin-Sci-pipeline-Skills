"""
generate_synthetic_gallery.py - Unified 100% Synthetic Mathematical Demo Generator for SciOrigin v7.0.

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


def main(argv: List[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Generate 100% synthetic SciOrigin v7.0 showcase figures via headless OriginPro 2024."
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
    args = parser.parse_args(argv)
    run_gallery_parts(part=args.part, gallery_dir=args.gallery_dir)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
