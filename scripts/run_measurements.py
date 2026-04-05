#!/usr/bin/env python3
"""OutSpread measurement runner scaffold for M1."""

from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime
from pathlib import Path


def load_manifest(path: Path) -> dict:
    if not path.is_file():
        raise FileNotFoundError(f"Case manifest not found: {path}")
    with path.open("r", encoding="utf-8") as handle:
        return json.load(handle)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Create OutSpread measurement scaffold artifacts."
    )
    parser.add_argument(
        "--mode",
        default="scaffold",
        help="Execution mode. Only 'scaffold' is implemented in this ticket.",
    )
    parser.add_argument(
        "--manifest",
        default="tests/cases/case_manifest.json",
        help="Path to the case manifest JSON.",
    )
    parser.add_argument(
        "--artifacts-root",
        default="artifacts/measurements",
        help="Root directory for timestamped measurement runs.",
    )
    parser.add_argument(
        "--groups",
        nargs="*",
        help="Optional subset of case groups to scaffold. Defaults to all groups in the manifest.",
    )
    parser.add_argument(
        "--plugin-under-test",
        help="Optional plugin-under-test identifier or path.",
    )
    parser.add_argument(
        "--reference-plugin",
        help="Optional reference plugin identifier or path.",
    )
    return parser.parse_args()


def ensure_supported_mode(mode: str) -> None:
    if mode == "scaffold":
        return
    raise SystemExit(
        f"error: mode '{mode}' is not implemented in this ticket. "
        "Use --mode scaffold to create measurement scaffolding without renders."
    )


def normalize_groups(manifest: dict, requested_groups: list[str] | None) -> list[str]:
    available_groups = [item["name"] for item in manifest["groups"]]
    if not requested_groups:
        return available_groups

    unknown = sorted(set(requested_groups) - set(available_groups))
    if unknown:
        raise SystemExit(
            "error: unknown case group(s): "
            + ", ".join(unknown)
            + ". Available groups: "
            + ", ".join(available_groups)
        )
    return requested_groups


def build_summary_paths(run_dir: Path, summary_files: list[str]) -> dict:
    summaries = {}
    for name in summary_files:
        summaries[name] = {
            "path": str((run_dir / name).as_posix()),
            "status": "generated" if name == "summary.json" else "not_generated_in_scaffold",
        }
    return summaries


def create_group_directories(cases_root: Path, groups: list[str]) -> None:
    for group in groups:
        (cases_root / group).mkdir(parents=True, exist_ok=True)


def main() -> int:
    args = parse_args()
    ensure_supported_mode(args.mode)

    repo_root = Path(__file__).resolve().parent.parent
    manifest_path = (repo_root / args.manifest).resolve()
    artifacts_root = (repo_root / args.artifacts_root).resolve()

    manifest = load_manifest(manifest_path)
    groups = normalize_groups(manifest, args.groups)

    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    run_dir = artifacts_root / timestamp
    cases_root = run_dir / "cases"

    cases_root.mkdir(parents=True, exist_ok=True)
    create_group_directories(cases_root, groups)

    summary_path = run_dir / "summary.json"
    top_level_summaries = build_summary_paths(
        run_dir, manifest["expectedTopLevelSummaryFiles"]
    )

    summary = {
        "schemaVersion": 1,
        "runMode": args.mode,
        "status": "scaffold_created",
        "scaffoldOnly": True,
        "rendersExecuted": False,
        "timestamp": timestamp,
        "summaryPath": str(summary_path.as_posix()),
        "caseManifestPath": str(manifest_path.as_posix()),
        "artifactsRoot": str(artifacts_root.as_posix()),
        "runDirectory": str(run_dir.as_posix()),
        "perCaseArtifactsRoot": str(cases_root.as_posix()),
        "groupsRequested": groups,
        "baselineDefaults": manifest["baselineDefaults"],
        "pluginUnderTest": args.plugin_under_test,
        "referencePlugin": args.reference_plugin,
        "topLevelSummaries": top_level_summaries,
        "notes": [
            "Scaffold mode created directory structure and summary metadata only.",
            "No plugin renders or reference captures were executed in this run.",
        ],
    }

    with summary_path.open("w", encoding="utf-8") as handle:
        json.dump(summary, handle, indent=2)
        handle.write("\n")

    print(f"Created scaffold measurement run: {run_dir}")
    print(f"Wrote summary: {summary_path}")
    print("No renders were executed.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
