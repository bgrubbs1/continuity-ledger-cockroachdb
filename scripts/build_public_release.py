"""Create a deterministic, ignored public-repository candidate tree."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from continuity_ledger.release import build_public_release  # noqa: E402


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--output",
        type=Path,
        default=ROOT / "dist" / "public-repo",
        help="New destination directory (default: dist/public-repo).",
    )
    args = parser.parse_args()
    manifest = build_public_release(ROOT, args.output)
    print(
        json.dumps(
            {
                "status": "pass",
                "output": str(args.output.resolve()),
                "file_count": len(manifest["files"]),
                "manifest": str((args.output / "RELEASE_MANIFEST.json").resolve()),
                "cloud_evidence_claimed": manifest["cloud_evidence_claimed"],
            },
            indent=2,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

