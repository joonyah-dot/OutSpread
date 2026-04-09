#!/usr/bin/env python3
"""Run repeatable smoke verification for the current OutSpread shell."""

from __future__ import annotations

import argparse
import hashlib
import json
import struct
import subprocess
import sys
import wave
from datetime import datetime
from pathlib import Path


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=(
            "Render and verify the current OutSpread shell without claiming "
            "Blackhole parity."
        )
    )
    parser.add_argument(
        "--plugin",
        default="build/OutSpread_artefacts/Debug/VST3/OutSpread.vst3",
        help="Path to the OutSpread VST3 plugin under test.",
    )
    parser.add_argument(
        "--harness",
        default="build/tools/vst3_harness/vst3_harness_artefacts/Release/vst3_harness.exe",
        help="Path to the vst3_harness executable.",
    )
    parser.add_argument(
        "--verifier",
        default="build/OutSpreadShellVerifier_artefacts/Debug/OutSpreadShellVerifier.exe",
        help="Path to the OutSpreadShellVerifier helper executable.",
    )
    parser.add_argument(
        "--cases-root",
        default="tests/cases/smoke/shell",
        help="Directory containing shell smoke case JSON files.",
    )
    parser.add_argument(
        "--artifacts-root",
        default="artifacts/shell_verification",
        help="Root directory for timestamped shell verification artifacts.",
    )
    parser.add_argument(
        "--case-id",
        action="append",
        help="Optional shell case ID filter. May be repeated or comma-separated.",
    )
    return parser.parse_args()


def parse_csv_args(values: list[str] | None) -> list[str]:
    if not values:
        return []
    items: list[str] = []
    for raw in values:
        items.extend(part.strip() for part in raw.split(",") if part.strip())
    return items


def load_json(path: Path) -> dict:
    with path.open("r", encoding="utf-8") as handle:
        value = json.load(handle)
    if not isinstance(value, dict):
        raise SystemExit(f"error: expected JSON object in {path}")
    return value


def write_json(path: Path, payload: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as handle:
        json.dump(payload, handle, indent=2)
        handle.write("\n")


def timestamp_slug() -> str:
    return datetime.now().strftime("%Y%m%d_%H%M%S")


def iso_now() -> str:
    return datetime.now().isoformat(timespec="seconds")


def resolve_path(repo_root: Path, raw_path: str) -> Path:
    path = Path(raw_path).expanduser()
    return path.resolve() if path.is_absolute() else (repo_root / path).resolve()


def require_file(path: Path, description: str) -> Path:
    if not path.is_file() and not path.is_dir():
        raise SystemExit(f"error: {description} not found: {path}")
    return path


def load_stimulus_index(repo_root: Path) -> dict[str, dict]:
    manifest = load_json(repo_root / "tests/_generated/stimuli/stimuli_manifest.json")
    files = manifest.get("files")
    if not isinstance(files, list):
        raise SystemExit("error: stimuli manifest is missing a usable 'files' list")

    index: dict[str, dict] = {}
    for entry in files:
        if not isinstance(entry, dict):
            continue
        stimulus_id = entry.get("id")
        if isinstance(stimulus_id, str):
            index[stimulus_id] = entry
    return index


def load_shell_cases(cases_root: Path, requested_ids: list[str]) -> list[dict]:
    if not cases_root.is_dir():
        raise SystemExit(f"error: shell smoke case directory not found: {cases_root}")

    case_paths = sorted(cases_root.glob("*.json"))
    if not case_paths:
        raise SystemExit(f"error: no shell smoke case JSON files found under {cases_root}")

    requested = set(requested_ids)
    found_requested: set[str] = set()
    cases: list[dict] = []
    for case_path in case_paths:
        case_data = load_json(case_path)
        if case_data.get("caseKind") != "shell_verification":
            raise SystemExit(f"error: shell smoke case {case_path} must set caseKind to 'shell_verification'")

        case_id = case_data.get("id")
        if not isinstance(case_id, str) or not case_id:
            raise SystemExit(f"error: shell smoke case {case_path} is missing a usable 'id'")

        if requested and case_id not in requested:
            continue

        found_requested.add(case_id)
        cases.append(case_data)

    if requested:
        missing = sorted(requested - found_requested)
        if missing:
            raise SystemExit(
                "error: requested shell smoke case ID(s) not found: " + ", ".join(missing)
            )
    return cases


def resolve_case_input(repo_root: Path, case_data: dict, stimuli_by_id: dict[str, dict]) -> Path:
    input_spec = case_data.get("input")
    if not isinstance(input_spec, dict) or "stimulusId" not in input_spec:
        raise SystemExit(
            f"error: shell smoke case {case_data.get('id')} must define input.stimulusId"
        )

    stimulus_id = input_spec["stimulusId"]
    if stimulus_id not in stimuli_by_id:
        raise SystemExit(
            f"error: shell smoke case {case_data.get('id')} references unknown stimulusId '{stimulus_id}'"
        )

    stimulus_path = Path(stimuli_by_id[stimulus_id]["filePath"])
    if not stimulus_path.is_absolute():
        stimulus_path = (repo_root / stimulus_path).resolve()
    if not stimulus_path.is_file():
        raise SystemExit(f"error: stimulus file not found: {stimulus_path}")
    return stimulus_path


def run_command(command: list[str], cwd: Path, stdout_path: Path, stderr_path: Path) -> dict:
    stdout_path.parent.mkdir(parents=True, exist_ok=True)
    stderr_path.parent.mkdir(parents=True, exist_ok=True)

    with stdout_path.open("w", encoding="utf-8") as stdout_handle, stderr_path.open(
        "w", encoding="utf-8"
    ) as stderr_handle:
        completed = subprocess.run(
            command,
            cwd=str(cwd),
            stdout=stdout_handle,
            stderr=stderr_handle,
            check=False,
        )

    return {
        "command": command,
        "cwd": str(cwd.as_posix()),
        "exitCode": completed.returncode,
        "stdoutPath": str(stdout_path.as_posix()),
        "stderrPath": str(stderr_path.as_posix()),
    }


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(65536), b""):
            digest.update(chunk)
    return digest.hexdigest()


def make_stereo_probe_wav(path: Path, sample_rate: int = 48000, duration_seconds: float = 1.0) -> Path:
    num_frames = int(round(sample_rate * duration_seconds))
    path.parent.mkdir(parents=True, exist_ok=True)

    with wave.open(str(path), "wb") as wav_file:
        wav_file.setnchannels(2)
        wav_file.setsampwidth(2)
        wav_file.setframerate(sample_rate)

        frames = bytearray()
        for frame_index in range(num_frames):
            left = 0.0
            right = 0.0
            if frame_index == 0:
                left = 0.8
            elif frame_index == sample_rate // 8:
                right = -0.55
            elif frame_index == sample_rate // 4:
                left = 0.25
                right = 0.15

            frames.extend(struct.pack("<hh", int(left * 32767.0), int(right * 32767.0)))

        wav_file.writeframes(frames)

    return path


def evaluate_case(case_data: dict, metrics: dict, case_dir: Path, completed_cases: dict[str, dict]) -> dict:
    case_id = case_data["id"]
    shell_verification = case_data.get("shellVerification", {})
    expectation = shell_verification.get("expectation")
    issues: list[str] = []

    if metrics.get("hasNaNOrInfWet"):
        issues.append("wet output contains NaN or Inf")

    if expectation == "near_passthrough":
        if metrics.get("wetPeakDbfs", -160.0) <= -40.0:
            issues.append("default shell output was unexpectedly close to silence")
        if metrics.get("wetPeakDbfs", 0.0) > -0.05:
            issues.append("default shell output peak is too close to clipping")
        if metrics.get("deltaPeakDbfs", 0.0) > -80.0:
            issues.append("default shell null delta peak is larger than expected for the passthrough-oriented shell")
        if metrics.get("deltaRmsDbfs", 0.0) > -120.0:
            issues.append("default shell null delta RMS is larger than expected for the passthrough-oriented shell")

    elif expectation == "matches_case":
        compare_to_case_id = shell_verification.get("compareToCaseId")
        if compare_to_case_id not in completed_cases:
            issues.append(f"comparison case '{compare_to_case_id}' is not available")
        else:
            reference_wet = Path(completed_cases[compare_to_case_id]["wetPath"])
            this_wet = case_dir / "wet.wav"
            if sha256_file(reference_wet) != sha256_file(this_wet):
                issues.append(
                    f"rendered output does not match comparison case '{compare_to_case_id}'"
                )

    elif expectation == "silent_output":
        if metrics.get("wetPeakDbfs", 0.0) > -150.0:
            issues.append("Kill+Mix=100 output was not silent enough")
        if metrics.get("wetRmsDbfs", 0.0) > -150.0:
            issues.append("Kill+Mix=100 RMS was not silent enough")
    else:
        issues.append(f"unsupported shell expectation '{expectation}'")

    return {
        "caseId": case_id,
        "expectation": expectation,
        "passed": not issues,
        "issues": issues,
    }


def main() -> int:
    args = parse_args()
    repo_root = Path(__file__).resolve().parent.parent

    plugin_path = require_file(resolve_path(repo_root, args.plugin), "plugin path")
    harness_path = require_file(resolve_path(repo_root, args.harness), "harness path")
    verifier_path = require_file(resolve_path(repo_root, args.verifier), "shell verifier path")
    cases_root = resolve_path(repo_root, args.cases_root)
    artifacts_root = resolve_path(repo_root, args.artifacts_root)

    stimuli_by_id = load_stimulus_index(repo_root)
    cases = load_shell_cases(cases_root, parse_csv_args(args.case_id))

    timestamp = timestamp_slug()
    run_dir = artifacts_root / timestamp
    run_dir.mkdir(parents=True, exist_ok=True)

    verifier_dir = run_dir / "verifier"
    layout_json = verifier_dir / "layout_check.json"
    state_json = verifier_dir / "state_roundtrip.json"
    layout_command = [str(verifier_path), "--mode", "layout-check", "--out", str(layout_json)]
    state_command = [str(verifier_path), "--mode", "state-roundtrip", "--out", str(state_json)]

    layout_result = run_command(
        layout_command,
        repo_root,
        verifier_dir / "layout_check.stdout.txt",
        verifier_dir / "layout_check.stderr.txt",
    )
    state_result = run_command(
        state_command,
        repo_root,
        verifier_dir / "state_roundtrip.stdout.txt",
        verifier_dir / "state_roundtrip.stderr.txt",
    )

    layout_summary = load_json(layout_json) if layout_json.is_file() else {"passed": False}
    state_summary = load_json(state_json) if state_json.is_file() else {"passed": False}

    completed_cases: dict[str, dict] = {}
    case_results: list[dict] = []
    overall_passed = layout_result["exitCode"] == 0 and state_result["exitCode"] == 0

    for case_data in cases:
        case_id = case_data["id"]
        case_dir = run_dir / "cases" / case_id
        case_dir.mkdir(parents=True, exist_ok=True)

        input_path = resolve_case_input(repo_root, case_data, stimuli_by_id)
        output_dir = case_dir
        render_command = [
            str(harness_path),
            "render",
            "--plugin",
            str(plugin_path),
            "--in",
            str(input_path),
            "--outdir",
            str(output_dir),
            "--sr",
            "48000",
            "--bs",
            "256",
            "--ch",
            str(case_data.get("channels", 2)),
            "--case",
            str((cases_root / f"{case_id}.json").resolve()),
        ]
        render_result = run_command(
            render_command,
            repo_root,
            case_dir / "render.stdout.txt",
            case_dir / "render.stderr.txt",
        )

        wet_path = case_dir / "wet.wav"
        metrics_path = case_dir / "metrics.json"
        analyze_command = [
            str(harness_path),
            "analyze",
            "--dry",
            str(input_path),
            "--wet",
            str(wet_path),
            "--outdir",
            str(output_dir),
            "--auto-align",
            "--null",
        ]
        analyze_result = {"command": analyze_command, "exitCode": None}
        metrics: dict = {}
        if render_result["exitCode"] == 0 and wet_path.is_file():
            analyze_result = run_command(
                analyze_command,
                repo_root,
                case_dir / "analyze.stdout.txt",
                case_dir / "analyze.stderr.txt",
            )
            if analyze_result["exitCode"] == 0 and metrics_path.is_file():
                metrics = load_json(metrics_path)

        evaluation = evaluate_case(case_data, metrics, case_dir, completed_cases) if metrics else {
            "caseId": case_id,
            "expectation": case_data.get("shellVerification", {}).get("expectation"),
            "passed": False,
            "issues": ["render or analysis did not produce usable metrics"],
        }

        if metrics and evaluation["passed"]:
            completed_cases[case_id] = {
                "wetPath": str(wet_path.resolve().as_posix()),
                "metricsPath": str(metrics_path.resolve().as_posix()),
            }

        case_summary = {
            "caseId": case_id,
            "casePath": str((cases_root / f"{case_id}.json").resolve().as_posix()),
            "inputPath": str(input_path.resolve().as_posix()),
            "wetPath": str(wet_path.resolve().as_posix()),
            "metricsPath": str(metrics_path.resolve().as_posix()),
            "render": render_result,
            "analyze": analyze_result,
            "metrics": metrics,
            "evaluation": evaluation,
            "notes": case_data.get("notes"),
        }
        write_json(case_dir / "summary.json", case_summary)
        case_results.append(case_summary)
        overall_passed &= evaluation["passed"]

    stereo_probe_input = make_stereo_probe_wav(run_dir / "inputs" / "stereo_routing_probe.wav")
    stereo_probe_dir = run_dir / "stereo_routing_probe"
    stereo_probe_render = run_command(
        [
            str(harness_path),
            "render",
            "--plugin",
            str(plugin_path),
            "--in",
            str(stereo_probe_input),
            "--outdir",
            str(stereo_probe_dir),
            "--sr",
            "48000",
            "--bs",
            "256",
            "--ch",
            "2",
            "--case",
            str((cases_root / "outspread_shell_default_smoke.json").resolve()),
        ],
        repo_root,
        stereo_probe_dir / "render.stdout.txt",
        stereo_probe_dir / "render.stderr.txt",
    )
    stereo_probe_analyze = {"exitCode": None}
    stereo_probe_metrics: dict = {}
    stereo_probe_wet = stereo_probe_dir / "wet.wav"
    if stereo_probe_render["exitCode"] == 0 and stereo_probe_wet.is_file():
        stereo_probe_analyze = run_command(
            [
                str(harness_path),
                "analyze",
                "--dry",
                str(stereo_probe_input),
                "--wet",
                str(stereo_probe_wet),
                "--outdir",
                str(stereo_probe_dir),
                "--auto-align",
                "--null",
            ],
            repo_root,
            stereo_probe_dir / "analyze.stdout.txt",
            stereo_probe_dir / "analyze.stderr.txt",
        )
        if stereo_probe_analyze["exitCode"] == 0 and (stereo_probe_dir / "metrics.json").is_file():
            stereo_probe_metrics = load_json(stereo_probe_dir / "metrics.json")

    stereo_probe_passed = (
        stereo_probe_render["exitCode"] == 0
        and stereo_probe_analyze.get("exitCode") == 0
        and stereo_probe_metrics.get("deltaPeakDbfs", 0.0) <= -80.0
        and stereo_probe_metrics.get("deltaRmsDbfs", 0.0) <= -120.0
        and not stereo_probe_metrics.get("hasNaNOrInfWet", True)
    )
    overall_passed &= stereo_probe_passed

    summary = {
        "schemaVersion": 1,
        "generatedAt": iso_now(),
        "runDirectory": str(run_dir.as_posix()),
        "pluginPath": str(plugin_path.as_posix()),
        "harnessPath": str(harness_path.as_posix()),
        "verifierPath": str(verifier_path.as_posix()),
        "casesRoot": str(cases_root.as_posix()),
        "notes": [
            "This is shell verification for the current OutSpread plugin shell, not a Blackhole parity run.",
            "The current shell remains passthrough-oriented: the wet scaffold mirrors routed input until later DSP tickets replace it.",
            "The current harness directly verifies stereo->stereo renders, but mono->stereo is verified through OutSpreadShellVerifier because the harness configures symmetric channel layouts only.",
        ],
        "verifierRuns": {
            "layoutCheck": {
                "command": layout_command,
                "result": layout_result,
                "summaryPath": str(layout_json.as_posix()),
                "passed": layout_summary.get("passed", False),
            },
            "stateRoundtrip": {
                "command": state_command,
                "result": state_result,
                "summaryPath": str(state_json.as_posix()),
                "passed": state_summary.get("passed", False),
            },
        },
        "shellCases": case_results,
        "stereoRoutingHarnessProbe": {
            "inputPath": str(stereo_probe_input.as_posix()),
            "render": stereo_probe_render,
            "analyze": stereo_probe_analyze,
            "metrics": stereo_probe_metrics,
            "passed": stereo_probe_passed,
        },
        "allPassed": overall_passed,
    }

    write_json(run_dir / "summary.json", summary)
    print(f"Created shell verification run: {run_dir}")
    print(f"Wrote summary: {run_dir / 'summary.json'}")
    return 0 if overall_passed else 1


if __name__ == "__main__":
    sys.exit(main())
