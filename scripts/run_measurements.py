#!/usr/bin/env python3
"""Manifest-driven measurement runner for OutSpread M1 reference capture work."""

from __future__ import annotations

import argparse
import json
import re
import subprocess
import sys
from collections import Counter
from datetime import datetime
from pathlib import Path


CASE_ID_PATTERN = re.compile(r"^[a-z0-9_]+$")


def load_json(path: Path) -> dict:
    if not path.is_file():
        raise SystemExit(f"error: required JSON file not found: {path}")
    try:
        with path.open("r", encoding="utf-8") as handle:
            value = json.load(handle)
    except json.JSONDecodeError as exc:
        raise SystemExit(f"error: malformed JSON in {path}: {exc}") from exc

    if not isinstance(value, dict):
        raise SystemExit(f"error: expected a JSON object in {path}")
    return value


def write_json(path: Path, payload: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as handle:
        json.dump(payload, handle, indent=2)
        handle.write("\n")


def write_text(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")


def parse_csv_arg(raw: str | None) -> list[str]:
    if raw is None:
        return []
    return [item.strip() for item in raw.split(",") if item.strip()]


def parse_multi_csv_args(raw_values: list[str] | None) -> list[str]:
    if not raw_values:
        return []
    items: list[str] = []
    for raw in raw_values:
        items.extend(parse_csv_arg(raw))
    return items


def normalize_notes(value: object, context: str) -> list[str]:
    if value is None:
        return []
    if isinstance(value, str):
        return [value]
    if isinstance(value, list) and all(isinstance(item, str) for item in value):
        return value
    raise SystemExit(f"error: {context} must be a string or a list of strings.")


def timestamp_slug() -> str:
    return datetime.now().strftime("%Y%m%d_%H%M%S")


def iso_now() -> str:
    return datetime.now().isoformat(timespec="seconds")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=(
            "Plan or execute manifest-driven OutSpread reference capture runs. "
            "Planning mode is the default."
        )
    )
    parser.add_argument(
        "--mode",
        choices=("plan", "scaffold"),
        default="plan",
        help=argparse.SUPPRESS,
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
        help="Comma-separated case groups to include. Defaults to all groups if omitted.",
    )
    parser.add_argument(
        "--all-groups",
        action="store_true",
        help="Run all declared groups explicitly.",
    )
    parser.add_argument(
        "--case-id",
        action="append",
        help="Optional case ID filter. May be repeated or provided as comma-separated values.",
    )
    parser.add_argument(
        "--plugin-under-test",
        help="Optional plugin-under-test identifier or path.",
    )
    parser.add_argument(
        "--reference-plugin",
        help="Path to the reference VST3 plugin bundle to plan or execute against.",
    )
    parser.add_argument(
        "--harness",
        help="Path to the render harness executable, such as vst3_harness.exe.",
    )
    parser.add_argument(
        "--execute-reference",
        action="store_true",
        help="Actually run reference capture commands instead of planning only.",
    )
    parser.add_argument(
        "--keep-going",
        action="store_true",
        help="Continue executing later cases after a case fails.",
    )
    return parser.parse_args()


def resolve_execution_mode(args: argparse.Namespace) -> str:
    if args.execute_reference:
        return "execute_reference"
    if args.mode in ("plan", "scaffold"):
        return "planning"
    raise SystemExit(f"error: unsupported mode: {args.mode}")


def default_group_summary_file(group_name: str) -> str:
    mapping = {
        "freeze_infinite": "freeze_summary.json",
        "sample_rate_block_size": "sample_rate_summary.json",
        "cpu_latency": "cpu_latency_summary.json",
    }
    return mapping.get(group_name, f"{group_name}_summary.json")


def load_manifest(repo_root: Path, manifest_arg: str) -> tuple[Path, dict]:
    manifest_path = (repo_root / manifest_arg).resolve()
    manifest = load_json(manifest_path)

    if "groups" not in manifest or not isinstance(manifest["groups"], list):
        raise SystemExit("error: manifest must define a 'groups' list.")
    if "baselineDefaults" not in manifest or not isinstance(
        manifest["baselineDefaults"], dict
    ):
        raise SystemExit("error: manifest must define 'baselineDefaults'.")

    group_names = [item.get("name") for item in manifest["groups"]]
    if any(not isinstance(name, str) or not name for name in group_names):
        raise SystemExit("error: each manifest group must have a non-empty string name.")
    if len(group_names) != len(set(group_names)):
        raise SystemExit("error: duplicate group names found in the manifest.")

    if "groupSummaryFiles" not in manifest:
        manifest["groupSummaryFiles"] = {
            name: default_group_summary_file(name) for name in group_names
        }

    if "expectedTopLevelSummaryFiles" not in manifest:
        manifest["expectedTopLevelSummaryFiles"] = ["summary.json"]

    return manifest_path, manifest


def normalize_groups(manifest: dict, args: argparse.Namespace) -> list[str]:
    available_groups = [item["name"] for item in manifest["groups"]]
    if args.all_groups or args.groups is None:
        return available_groups

    requested_groups = parse_csv_arg(args.groups)
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


def load_stimuli_manifest(repo_root: Path, manifest: dict) -> tuple[Path, dict]:
    stimuli_manifest_arg = manifest.get(
        "stimuliManifestPath", "tests/_generated/stimuli/stimuli_manifest.json"
    )
    stimuli_manifest_path = (repo_root / stimuli_manifest_arg).resolve()
    stimuli_manifest = load_json(stimuli_manifest_path)

    files = stimuli_manifest.get("files")
    if not isinstance(files, list):
        raise SystemExit(
            f"error: stimuli manifest must contain a 'files' list: {stimuli_manifest_path}"
        )
    return stimuli_manifest_path, stimuli_manifest


def build_stimulus_indexes(
    stimuli_manifest: dict,
) -> tuple[dict[str, dict], dict[str, dict]]:
    by_id: dict[str, dict] = {}
    by_file_name: dict[str, dict] = {}
    for entry in stimuli_manifest.get("files", []):
        if not isinstance(entry, dict):
            continue
        stimulus_id = entry.get("id")
        file_name = entry.get("fileName")
        if isinstance(stimulus_id, str):
            by_id[stimulus_id] = entry
        if isinstance(file_name, str):
            by_file_name[file_name] = entry
    return by_id, by_file_name


def load_reference_state_manifest(
    repo_root: Path, manifest: dict
) -> tuple[Path, dict]:
    state_manifest_arg = manifest.get(
        "referenceStateManifestPath", "tests/reference_states/reference_state_manifest.json"
    )
    state_manifest_path = (repo_root / state_manifest_arg).resolve()
    state_manifest = load_json(state_manifest_path)

    if "stateDirectory" not in state_manifest or not isinstance(
        state_manifest["stateDirectory"], str
    ):
        raise SystemExit("error: reference-state manifest must define 'stateDirectory'.")
    if "allowedStatuses" not in state_manifest or not isinstance(
        state_manifest["allowedStatuses"], list
    ):
        raise SystemExit(
            "error: reference-state manifest must define 'allowedStatuses'."
        )
    if "allowedSourceTypes" not in state_manifest or not isinstance(
        state_manifest["allowedSourceTypes"], list
    ):
        raise SystemExit(
            "error: reference-state manifest must define 'allowedSourceTypes'."
        )

    state_manifest.setdefault(
        "referenceLockFields",
        [
            "pluginVersion",
            "platform",
            "hostOrRenderPath",
            "baselineSampleRate",
            "baselineBlockSize",
        ],
    )
    state_manifest.setdefault(
        "stateFields",
        {
            "required": [
                "id",
                "status",
                "description",
                "targetGroups",
                "sourceType",
                "referenceLock",
                "paramsByName",
                "notes",
            ],
            "optional": ["paramsByIndex"],
        },
    )

    return state_manifest_path, state_manifest


def discover_reference_state_files(
    repo_root: Path, state_manifest_path: Path, state_manifest: dict
) -> list[Path]:
    state_dir = (repo_root / state_manifest["stateDirectory"]).resolve()
    if not state_dir.is_dir():
        raise SystemExit(
            f"error: reference-state directory does not exist: {state_dir}"
        )

    return sorted(
        path
        for path in state_dir.glob("*.json")
        if path.resolve() != state_manifest_path.resolve()
    )


def normalize_reference_state_record(state_path: Path, state_data: dict) -> dict:
    return {
        "id": state_data["id"],
        "status": state_data["status"],
        "description": state_data["description"],
        "targetGroups": state_data["targetGroups"],
        "sourceType": state_data["sourceType"],
        "referenceLock": state_data["referenceLock"],
        "paramsByName": state_data.get("paramsByName", {}),
        "paramsByIndex": state_data.get("paramsByIndex", {}),
        "notes": normalize_notes(
            state_data["notes"], f"reference-state file {state_path} field 'notes'"
        ),
        "stateFilePath": str(state_path.resolve().as_posix()),
    }


def validate_reference_state_object(
    state_path: Path,
    state_data: dict,
    state_manifest: dict,
    available_groups: set[str],
) -> None:
    required_fields = state_manifest["stateFields"]["required"]
    missing_fields = [field for field in required_fields if field not in state_data]
    if missing_fields:
        raise SystemExit(
            f"error: reference-state file {state_path} is missing required field(s): "
            + ", ".join(missing_fields)
        )

    state_id = state_data.get("id")
    if not isinstance(state_id, str) or not CASE_ID_PATTERN.match(state_id):
        raise SystemExit(
            f"error: reference-state file {state_path} must define a lowercase snake_case 'id'."
        )

    status = state_data.get("status")
    if status not in state_manifest["allowedStatuses"]:
        raise SystemExit(
            f"error: reference-state file {state_path} has invalid status '{status}'."
        )

    description = state_data.get("description")
    if not isinstance(description, str) or not description.strip():
        raise SystemExit(
            f"error: reference-state file {state_path} must define a non-empty 'description'."
        )

    target_groups = state_data.get("targetGroups")
    if not isinstance(target_groups, list) or not target_groups:
        raise SystemExit(
            f"error: reference-state file {state_path} must define a non-empty 'targetGroups' list."
        )
    if any(not isinstance(group, str) or group not in available_groups for group in target_groups):
        raise SystemExit(
            f"error: reference-state file {state_path} contains unknown group names in 'targetGroups'."
        )

    source_type = state_data.get("sourceType")
    if source_type not in state_manifest["allowedSourceTypes"]:
        raise SystemExit(
            f"error: reference-state file {state_path} has invalid sourceType '{source_type}'."
        )

    reference_lock = state_data.get("referenceLock")
    if not isinstance(reference_lock, dict):
        raise SystemExit(
            f"error: reference-state file {state_path} must define 'referenceLock' as an object."
        )
    for field_name in state_manifest["referenceLockFields"]:
        if field_name not in reference_lock:
            raise SystemExit(
                f"error: reference-state file {state_path} is missing referenceLock field '{field_name}'."
            )

    for numeric_field in ("baselineSampleRate", "baselineBlockSize"):
        value = reference_lock.get(numeric_field)
        if value is not None and (not isinstance(value, int) or value <= 0):
            raise SystemExit(
                f"error: reference-state file {state_path} field '{numeric_field}' must be null or a positive integer."
            )

    if not isinstance(state_data.get("paramsByName"), dict):
        raise SystemExit(
            f"error: reference-state file {state_path} field 'paramsByName' must be an object."
        )

    if "paramsByIndex" in state_data and not isinstance(state_data["paramsByIndex"], dict):
        raise SystemExit(
            f"error: reference-state file {state_path} field 'paramsByIndex' must be an object."
        )

    normalize_notes(
        state_data.get("notes"),
        f"reference-state file {state_path} field 'notes'",
    )


def load_reference_states(
    repo_root: Path,
    state_manifest_path: Path,
    state_manifest: dict,
    available_groups: set[str],
) -> tuple[dict[str, dict], list[str]]:
    discovered_files = discover_reference_state_files(
        repo_root, state_manifest_path, state_manifest
    )
    states_by_id: dict[str, dict] = {}
    for state_path in discovered_files:
        state_data = load_json(state_path)
        validate_reference_state_object(
            state_path, state_data, state_manifest, available_groups
        )
        state_id = state_data["id"]
        if state_id in states_by_id:
            raise SystemExit(f"error: duplicate reference-state ID discovered: {state_id}")
        states_by_id[state_id] = normalize_reference_state_record(state_path, state_data)

    return states_by_id, sorted(states_by_id)


def resolve_stimulus_entry(entry: dict, requested_input: object) -> dict:
    file_path = entry.get("filePath")
    if not isinstance(file_path, str) or not file_path:
        raise SystemExit(
            f"error: stimulus entry is missing a usable filePath for request {requested_input!r}"
        )
    path = Path(file_path)
    if not path.is_file():
        raise SystemExit(f"error: referenced stimulus file does not exist: {path}")

    resolved = {
        "requestedInput": requested_input,
        "source": "stimuli_manifest",
        "stimulusId": entry.get("id"),
        "fileName": entry.get("fileName"),
        "resolvedPath": str(path.as_posix()),
        "sampleRate": entry.get("sampleRate"),
        "channelCount": entry.get("channelCount"),
        "durationSeconds": entry.get("durationSeconds"),
        "method": entry.get("method"),
    }
    if "seed" in entry:
        resolved["seed"] = entry["seed"]
    return resolved


def resolve_input_reference(
    repo_root: Path,
    requested_input: object,
    stimuli_by_id: dict[str, dict],
    stimuli_by_file_name: dict[str, dict],
) -> dict:
    if isinstance(requested_input, str):
        if requested_input in stimuli_by_id:
            return resolve_stimulus_entry(stimuli_by_id[requested_input], requested_input)
        if requested_input in stimuli_by_file_name:
            return resolve_stimulus_entry(
                stimuli_by_file_name[requested_input], requested_input
            )

        candidate = Path(requested_input)
        candidate = candidate if candidate.is_absolute() else (repo_root / candidate)
        candidate = candidate.resolve()
        if candidate.is_file():
            return {
                "requestedInput": requested_input,
                "source": "path",
                "resolvedPath": str(candidate.as_posix()),
            }
        raise SystemExit(
            f"error: could not resolve case input {requested_input!r} to a known stimulus or file path."
        )

    if isinstance(requested_input, dict):
        if "stimulusId" in requested_input:
            stimulus_id = requested_input["stimulusId"]
            if not isinstance(stimulus_id, str) or stimulus_id not in stimuli_by_id:
                raise SystemExit(
                    f"error: unknown stimulusId in case input: {requested_input!r}"
                )
            return resolve_stimulus_entry(stimuli_by_id[stimulus_id], requested_input)

        if "fileName" in requested_input:
            file_name = requested_input["fileName"]
            if not isinstance(file_name, str) or file_name not in stimuli_by_file_name:
                raise SystemExit(
                    f"error: unknown stimulus fileName in case input: {requested_input!r}"
                )
            return resolve_stimulus_entry(
                stimuli_by_file_name[file_name], requested_input
            )

        if "path" in requested_input:
            path_value = requested_input["path"]
            if not isinstance(path_value, str) or not path_value:
                raise SystemExit(f"error: invalid path-based case input: {requested_input!r}")
            candidate = Path(path_value)
            candidate = candidate if candidate.is_absolute() else (repo_root / candidate)
            candidate = candidate.resolve()
            if not candidate.is_file():
                raise SystemExit(f"error: referenced case input path does not exist: {candidate}")
            return {
                "requestedInput": requested_input,
                "source": "path",
                "resolvedPath": str(candidate.as_posix()),
            }

    raise SystemExit(
        "error: case input must be a stimulus ID string, file name string, "
        "or an object with stimulusId, fileName, or path."
    )


def discover_case_files(
    repo_root: Path, selected_groups: list[str], manifest: dict
) -> dict[str, list[Path]]:
    discovered: dict[str, list[Path]] = {}
    group_definitions = {item["name"]: item for item in manifest["groups"]}
    for group_name in selected_groups:
        group_dir = (repo_root / group_definitions[group_name]["directory"]).resolve()
        if not group_dir.exists():
            discovered[group_name] = []
            continue
        if not group_dir.is_dir():
            raise SystemExit(f"error: group directory is not a directory: {group_dir}")
        discovered[group_name] = sorted(group_dir.glob("*.json"))
    return discovered


def validate_case_object(
    case_path: Path, case_data: dict, group_name: str, manifest: dict
) -> None:
    required_fields = manifest.get("caseFields", {}).get("required", [])
    missing_fields = [field for field in required_fields if field not in case_data]
    if missing_fields:
        raise SystemExit(
            f"error: case file {case_path} is missing required field(s): {', '.join(missing_fields)}"
        )

    case_id = case_data.get("id")
    if not isinstance(case_id, str) or not CASE_ID_PATTERN.match(case_id):
        raise SystemExit(
            f"error: case file {case_path} must define a lowercase snake_case 'id'."
        )

    case_group = case_data.get("group")
    if case_group != group_name:
        raise SystemExit(
            f"error: case file {case_path} declares group '{case_group}' but lives under '{group_name}'."
        )

    if not isinstance(case_data.get("input"), (str, dict)):
        raise SystemExit(
            f"error: case file {case_path} must define 'input' as a string or object."
        )

    reference_state_id = case_data.get("referenceStateId")
    if not isinstance(reference_state_id, str) or not CASE_ID_PATTERN.match(
        reference_state_id
    ):
        raise SystemExit(
            f"error: case file {case_path} must define a lowercase snake_case 'referenceStateId'."
        )

    for field_name in ("paramsByName", "paramsByIndex"):
        if field_name in case_data and not isinstance(case_data[field_name], dict):
            raise SystemExit(
                f"error: case file {case_path} field '{field_name}' must be a JSON object."
            )


def load_declared_cases(
    repo_root: Path,
    manifest: dict,
    selected_groups: list[str],
    requested_case_ids: list[str],
    stimuli_by_id: dict[str, dict],
    stimuli_by_file_name: dict[str, dict],
    reference_states_by_id: dict[str, dict],
) -> tuple[dict[str, list[dict]], list[str]]:
    discovered_paths = discover_case_files(repo_root, selected_groups, manifest)
    requested_case_id_set = set(requested_case_ids)
    discovered_cases: dict[str, list[dict]] = {group: [] for group in selected_groups}
    all_case_ids: set[str] = set()
    matched_requested_case_ids: set[str] = set()

    for group_name in selected_groups:
        for case_path in discovered_paths[group_name]:
            case_data = load_json(case_path)
            validate_case_object(case_path, case_data, group_name, manifest)

            case_id = case_data["id"]
            if case_id in all_case_ids:
                raise SystemExit(f"error: duplicate case ID discovered: {case_id}")
            all_case_ids.add(case_id)

            if requested_case_id_set and case_id not in requested_case_id_set:
                continue

            reference_state_id = case_data["referenceStateId"]
            if reference_state_id not in reference_states_by_id:
                raise SystemExit(
                    f"error: case file {case_path} references unknown referenceStateId '{reference_state_id}'."
                )

            resolved_input = resolve_input_reference(
                repo_root,
                case_data["input"],
                stimuli_by_id,
                stimuli_by_file_name,
            )

            discovered_cases[group_name].append(
                {
                    "caseFilePath": str(case_path.resolve().as_posix()),
                    "caseData": case_data,
                    "resolvedInput": resolved_input,
                    "resolvedReferenceState": reference_states_by_id[reference_state_id],
                }
            )
            matched_requested_case_ids.add(case_id)

    if requested_case_id_set:
        missing_case_ids = sorted(requested_case_id_set - matched_requested_case_ids)
        if missing_case_ids:
            raise SystemExit(
                "error: requested case ID(s) not found in the selected groups: "
                + ", ".join(missing_case_ids)
            )

    discovered_case_ids = sorted(
        case_record["caseData"]["id"]
        for group_cases in discovered_cases.values()
        for case_record in group_cases
    )
    return discovered_cases, discovered_case_ids


def resolve_cli_path(repo_root: Path, raw_path: str) -> Path:
    candidate = Path(raw_path).expanduser()
    return (
        candidate.resolve()
        if candidate.is_absolute()
        else (repo_root / candidate).resolve()
    )


def resolve_reference_plugin(repo_root: Path, raw_path: str | None) -> dict | None:
    if raw_path is None:
        return None
    path = resolve_cli_path(repo_root, raw_path)
    if not path.exists():
        raise SystemExit(f"error: reference plugin path does not exist: {path}")
    if path.suffix.lower() != ".vst3":
        raise SystemExit(
            f"error: reference plugin path must point to a .vst3 bundle or file: {path}"
        )
    if not (path.is_dir() or path.is_file()):
        raise SystemExit(
            f"error: reference plugin path is not a usable file or directory: {path}"
        )
    return {
        "input": raw_path,
        "resolvedPath": str(path.as_posix()),
        "name": path.name,
        "pathType": "directory" if path.is_dir() else "file",
        "format": "vst3",
    }


def resolve_harness(repo_root: Path, raw_path: str | None) -> dict | None:
    if raw_path is None:
        return None
    path = resolve_cli_path(repo_root, raw_path)
    if not path.exists():
        raise SystemExit(f"error: harness path does not exist: {path}")
    if not path.is_file():
        raise SystemExit(f"error: harness path must point to a file: {path}")
    return {
        "input": raw_path,
        "resolvedPath": str(path.as_posix()),
        "name": path.name,
        "toolKind": "vst3_harness"
        if "harness" in path.name.lower()
        else "external_render_tool",
    }


def validate_execution_prerequisites(
    execution_mode: str,
    reference_plugin: dict | None,
    harness: dict | None,
) -> None:
    if execution_mode != "execute_reference":
        return
    if reference_plugin is None:
        raise SystemExit(
            "error: --execute-reference requires --reference-plugin with a valid .vst3 path."
        )
    if harness is None:
        raise SystemExit(
            "error: --execute-reference requires --harness with a valid harness executable path."
        )


def build_expected_artifacts(run_dir: Path, case_id: str) -> dict:
    case_dir = run_dir / "cases" / case_id
    reference_dir = case_dir / "reference"
    return {
        "caseDirectory": str(case_dir.as_posix()),
        "casePlanPath": str((case_dir / "case_plan.json").as_posix()),
        "referenceCapturePath": str((case_dir / "reference_capture.json").as_posix()),
        "referenceCasePath": str((case_dir / "reference_case.json").as_posix()),
        "referenceDirectory": str(reference_dir.as_posix()),
        "referenceWetPath": str((reference_dir / "wet.wav").as_posix()),
        "referenceMetricsPath": str((reference_dir / "metrics.json").as_posix()),
        "renderStdoutPath": str((reference_dir / "render_stdout.txt").as_posix()),
        "renderStderrPath": str((reference_dir / "render_stderr.txt").as_posix()),
        "analyzeStdoutPath": str((reference_dir / "analyze_stdout.txt").as_posix()),
        "analyzeStderrPath": str((reference_dir / "analyze_stderr.txt").as_posix()),
    }


def resolve_case_settings(
    baseline_defaults: dict,
    case_data: dict,
    plugin_under_test: str | None,
) -> dict:
    resolved = dict(baseline_defaults)
    for key in baseline_defaults:
        if key in case_data:
            resolved[key] = case_data[key]

    resolved["pluginUnderTest"] = plugin_under_test
    return resolved


def validate_resolved_settings(case_id: str, settings: dict) -> None:
    int_fields = {
        "sampleRate": 1,
        "blockSize": 1,
        "channels": 1,
        "warmupMs": 0,
    }
    for field_name, minimum in int_fields.items():
        value = settings.get(field_name)
        if not isinstance(value, int) or value < minimum:
            comparator = "non-negative" if minimum == 0 else "positive"
            raise SystemExit(
                f"error: case '{case_id}' resolved field '{field_name}' must be a {comparator} integer."
            )

    render_seconds = settings.get("renderSeconds")
    if not isinstance(render_seconds, (int, float)) or render_seconds <= 0:
        raise SystemExit(
            f"error: case '{case_id}' resolved field 'renderSeconds' must be a positive number."
        )


def resolve_parameter_assignment(case_data: dict, reference_state: dict) -> dict:
    state_by_name = dict(reference_state.get("paramsByName", {}))
    state_by_index = dict(reference_state.get("paramsByIndex", {}))
    case_by_name = dict(case_data.get("paramsByName", {}))
    case_by_index = dict(case_data.get("paramsByIndex", {}))

    merged_by_name = dict(state_by_name)
    merged_by_name.update(case_by_name)

    merged_by_index = dict(state_by_index)
    merged_by_index.update(case_by_index)

    has_state_params = bool(state_by_name or state_by_index)
    has_case_params = bool(case_by_name or case_by_index)
    if has_state_params and has_case_params:
        source = "merged_reference_state_and_case_override"
    elif has_state_params:
        source = "reference_state"
    elif has_case_params:
        source = "case_override"
    else:
        source = "none"

    return {
        "source": source,
        "referenceStateHasParameters": has_state_params,
        "caseHasParameters": has_case_params,
        "paramsByName": merged_by_name,
        "paramsByIndex": merged_by_index,
    }


def build_harness_case_payload(settings: dict, parameters: dict) -> dict:
    payload: dict[str, object] = {
        "warmupMs": settings["warmupMs"],
        "renderSeconds": settings["renderSeconds"],
        "paramsByName": parameters["paramsByName"],
    }
    if parameters["paramsByIndex"]:
        payload["paramsByIndex"] = parameters["paramsByIndex"]
    return payload


def command_entry(
    name: str,
    executable: str | None,
    args: list[str],
    stdout_path: str,
    stderr_path: str,
    expected_output_paths: list[str],
    missing_prerequisites: list[str],
) -> dict:
    argv = [executable if executable is not None else "<missing_executable>"] + args
    return {
        "name": name,
        "argv": argv,
        "stdoutPath": stdout_path,
        "stderrPath": stderr_path,
        "expectedOutputPaths": expected_output_paths,
        "runnable": not missing_prerequisites,
        "missingPrerequisites": missing_prerequisites,
    }


def build_reference_render_plan(
    case_id: str,
    resolved_input: dict,
    settings: dict,
    reference_plugin: dict | None,
    harness: dict | None,
    expected_artifacts: dict,
) -> dict:
    missing_prerequisites: list[str] = []
    if harness is None:
        missing_prerequisites.append("harness")
    if reference_plugin is None:
        missing_prerequisites.append("reference_plugin")

    harness_path = harness["resolvedPath"] if harness else None
    plugin_path = reference_plugin["resolvedPath"] if reference_plugin else None

    render_args = [
        "render",
        "--plugin",
        plugin_path if plugin_path is not None else "<reference_plugin_required>",
        "--in",
        resolved_input["resolvedPath"],
        "--outdir",
        expected_artifacts["referenceDirectory"],
        "--sr",
        str(settings["sampleRate"]),
        "--bs",
        str(settings["blockSize"]),
        "--ch",
        str(settings["channels"]),
        "--case",
        expected_artifacts["referenceCasePath"],
    ]
    analyze_args = [
        "analyze",
        "--dry",
        resolved_input["resolvedPath"],
        "--wet",
        expected_artifacts["referenceWetPath"],
        "--outdir",
        expected_artifacts["referenceDirectory"],
        "--auto-align",
        "--null",
    ]

    commands = [
        command_entry(
            name="render",
            executable=harness_path,
            args=render_args,
            stdout_path=expected_artifacts["renderStdoutPath"],
            stderr_path=expected_artifacts["renderStderrPath"],
            expected_output_paths=[expected_artifacts["referenceWetPath"]],
            missing_prerequisites=missing_prerequisites,
        ),
        command_entry(
            name="analyze",
            executable=harness_path,
            args=analyze_args,
            stdout_path=expected_artifacts["analyzeStdoutPath"],
            stderr_path=expected_artifacts["analyzeStderrPath"],
            expected_output_paths=[expected_artifacts["referenceMetricsPath"]],
            missing_prerequisites=missing_prerequisites,
        ),
    ]

    return {
        "runner": "vst3_harness",
        "referenceCaseId": case_id,
        "referencePluginPath": plugin_path,
        "harnessPath": harness_path,
        "runnable": not missing_prerequisites,
        "missingPrerequisites": missing_prerequisites,
        "commands": commands,
    }


def build_case_record(
    run_dir: Path,
    group_name: str,
    case_record: dict,
    baseline_defaults: dict,
    plugin_under_test: str | None,
    reference_plugin: dict | None,
    harness: dict | None,
    execution_mode: str,
) -> dict:
    case_data = case_record["caseData"]
    case_id = case_data["id"]
    expected_artifacts = build_expected_artifacts(run_dir, case_id)
    settings = resolve_case_settings(
        baseline_defaults,
        case_data,
        plugin_under_test,
    )
    validate_resolved_settings(case_id, settings)
    parameters = resolve_parameter_assignment(
        case_data,
        case_record["resolvedReferenceState"],
    )
    reference_render_plan = build_reference_render_plan(
        case_id,
        case_record["resolvedInput"],
        settings,
        reference_plugin,
        harness,
        expected_artifacts,
    )

    notes = normalize_notes(
        case_data.get("notes"),
        f"case file {case_record['caseFilePath']} field 'notes'",
    )
    if case_record["resolvedReferenceState"]["status"] != "captured":
        notes.append(
            "This case is linked to a reference state that is not yet marked captured."
        )

    return {
        "schemaVersion": 1,
        "caseId": case_id,
        "group": group_name,
        "caseFilePath": case_record["caseFilePath"],
        "analysisProfile": case_data.get("analysisProfile", group_name),
        "expectedDeterminism": case_data.get("expectedDeterminism"),
        "scaffoldOnly": bool(case_data.get("scaffoldOnly", True)),
        "resolvedInput": case_record["resolvedInput"],
        "resolvedSettings": settings,
        "resolvedParameters": parameters,
        "referenceStateId": case_data["referenceStateId"],
        "referenceStateStatus": case_record["resolvedReferenceState"]["status"],
        "resolvedReferenceState": case_record["resolvedReferenceState"],
        "resolvedReferencePlugin": reference_plugin,
        "resolvedHarness": harness,
        "expectedArtifacts": expected_artifacts,
        "referenceRenderPlan": reference_render_plan,
        "executionMode": execution_mode,
        "executionStatus": "planned",
        "rendersExecuted": False,
        "executionResult": {
            "attempted": False,
            "startedAt": None,
            "finishedAt": None,
            "steps": [],
            "failureReason": None,
        },
        "notes": notes,
        "harnessCasePayload": build_harness_case_payload(settings, parameters),
    }


def prepare_cases(
    run_dir: Path,
    group_cases: dict[str, list[dict]],
    baseline_defaults: dict,
    plugin_under_test: str | None,
    reference_plugin: dict | None,
    harness: dict | None,
    execution_mode: str,
) -> tuple[dict[str, list[dict]], list[dict]]:
    prepared_by_group: dict[str, list[dict]] = {}
    flat_cases: list[dict] = []
    for group_name, cases in group_cases.items():
        prepared_by_group[group_name] = []
        for case_record in cases:
            prepared = build_case_record(
                run_dir,
                group_name,
                case_record,
                baseline_defaults,
                plugin_under_test,
                reference_plugin,
                harness,
                execution_mode,
            )
            prepared_by_group[group_name].append(prepared)
            flat_cases.append(prepared)
    return prepared_by_group, flat_cases


def build_case_plan_payload(case: dict) -> dict:
    return {
        "schemaVersion": 1,
        "caseId": case["caseId"],
        "group": case["group"],
        "caseFilePath": case["caseFilePath"],
        "analysisProfile": case["analysisProfile"],
        "expectedDeterminism": case["expectedDeterminism"],
        "scaffoldOnly": case["scaffoldOnly"],
        "resolvedInput": case["resolvedInput"],
        "resolvedSettings": case["resolvedSettings"],
        "resolvedParameters": case["resolvedParameters"],
        "referenceStateId": case["referenceStateId"],
        "referenceStateStatus": case["referenceStateStatus"],
        "resolvedReferenceState": case["resolvedReferenceState"],
        "resolvedReferencePlugin": case["resolvedReferencePlugin"],
        "resolvedHarness": case["resolvedHarness"],
        "expectedArtifacts": case["expectedArtifacts"],
        "referenceRenderPlan": case["referenceRenderPlan"],
        "executionMode": case["executionMode"],
        "executionStatus": case["executionStatus"],
        "rendersExecuted": case["rendersExecuted"],
        "executionResult": case["executionResult"],
        "referenceCapturePath": case["expectedArtifacts"]["referenceCapturePath"],
        "notes": case["notes"],
    }


def build_reference_capture_payload(case: dict) -> dict:
    return {
        "schemaVersion": 1,
        "caseId": case["caseId"],
        "group": case["group"],
        "executionMode": case["executionMode"],
        "executionStatus": case["executionStatus"],
        "rendersExecuted": case["rendersExecuted"],
        "resolvedInput": case["resolvedInput"],
        "resolvedSettings": case["resolvedSettings"],
        "resolvedParameters": case["resolvedParameters"],
        "referenceStateId": case["referenceStateId"],
        "referenceStateStatus": case["referenceStateStatus"],
        "resolvedReferenceState": case["resolvedReferenceState"],
        "resolvedReferencePlugin": case["resolvedReferencePlugin"],
        "resolvedHarness": case["resolvedHarness"],
        "referenceRenderPlan": case["referenceRenderPlan"],
        "expectedArtifacts": case["expectedArtifacts"],
        "executionResult": case["executionResult"],
        "notes": case["notes"],
    }


def write_case_artifacts(cases: list[dict]) -> None:
    for case in cases:
        case_dir = Path(case["expectedArtifacts"]["caseDirectory"])
        reference_dir = Path(case["expectedArtifacts"]["referenceDirectory"])
        case_dir.mkdir(parents=True, exist_ok=True)
        reference_dir.mkdir(parents=True, exist_ok=True)

        write_json(
            Path(case["expectedArtifacts"]["referenceCasePath"]),
            case["harnessCasePayload"],
        )
        write_json(
            Path(case["expectedArtifacts"]["casePlanPath"]),
            build_case_plan_payload(case),
        )
        write_json(
            Path(case["expectedArtifacts"]["referenceCapturePath"]),
            build_reference_capture_payload(case),
        )


def run_command(command: dict, repo_root: Path) -> dict:
    stdout_path = Path(command["stdoutPath"])
    stderr_path = Path(command["stderrPath"])
    started_at = iso_now()
    try:
        completed = subprocess.run(
            command["argv"],
            cwd=str(repo_root),
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            check=False,
        )
        stdout_text = completed.stdout or ""
        stderr_text = completed.stderr or ""
        exit_code = completed.returncode
        invocation_error = None
    except OSError as exc:
        stdout_text = ""
        stderr_text = str(exc)
        exit_code = None
        invocation_error = str(exc)

    write_text(stdout_path, stdout_text)
    write_text(stderr_path, stderr_text)

    existing_outputs = [
        path for path in command["expectedOutputPaths"] if Path(path).exists()
    ]
    missing_outputs = [
        path for path in command["expectedOutputPaths"] if not Path(path).exists()
    ]

    if invocation_error is not None:
        status = "failed"
        failure_reason = invocation_error
    elif exit_code != 0:
        status = "failed"
        failure_reason = f"command exited with code {exit_code}"
    elif missing_outputs:
        status = "failed"
        failure_reason = "expected outputs missing after successful command exit"
    else:
        status = "success"
        failure_reason = None

    return {
        "name": command["name"],
        "argv": command["argv"],
        "startedAt": started_at,
        "finishedAt": iso_now(),
        "status": status,
        "exitCode": exit_code,
        "stdoutPath": command["stdoutPath"],
        "stderrPath": command["stderrPath"],
        "actualOutputPaths": existing_outputs,
        "missingExpectedOutputs": missing_outputs,
        "failureReason": failure_reason,
    }


def mark_case_skipped(case: dict, reason: str) -> None:
    case["executionStatus"] = "skipped"
    case["rendersExecuted"] = False
    case["executionResult"] = {
        "attempted": False,
        "startedAt": None,
        "finishedAt": None,
        "steps": [],
        "failureReason": reason,
    }
    case["notes"] = list(case["notes"]) + [reason]


def execute_reference_cases(
    flat_cases: list[dict],
    repo_root: Path,
    keep_going: bool,
) -> bool:
    all_success = True
    stop_index: int | None = None

    for index, case in enumerate(flat_cases):
        case["executionMode"] = "execute_reference"
        case["executionResult"] = {
            "attempted": True,
            "startedAt": iso_now(),
            "finishedAt": None,
            "steps": [],
            "failureReason": None,
        }

        render_plan = case["referenceRenderPlan"]
        if not render_plan["runnable"]:
            missing = ", ".join(render_plan["missingPrerequisites"])
            case["executionStatus"] = "skipped"
            case["executionResult"]["attempted"] = False
            case["executionResult"]["failureReason"] = (
                "execution prerequisites missing: " + missing
            )
            case["executionResult"]["finishedAt"] = iso_now()
            all_success = False
            if not keep_going:
                stop_index = index + 1
                break
            continue

        case["executionStatus"] = "executed_success"
        for step in render_plan["commands"]:
            step_result = run_command(step, repo_root)
            case["executionResult"]["steps"].append(step_result)
            if step["name"] == "render":
                case["rendersExecuted"] = True

            if step_result["status"] != "success":
                case["executionStatus"] = "executed_failed"
                case["executionResult"]["failureReason"] = step_result["failureReason"]
                all_success = False
                break

        case["executionResult"]["finishedAt"] = iso_now()
        if case["executionStatus"] == "executed_failed" and not keep_going:
            stop_index = index + 1
            break

    if stop_index is not None:
        for case in flat_cases[stop_index:]:
            mark_case_skipped(
                case,
                "Case was not attempted because execution stopped after an earlier failure.",
            )

    return all_success


def summarize_reference_state_usage(cases: list[dict], allowed_statuses: list[str]) -> dict:
    used_states: dict[str, dict] = {}
    for case in cases:
        state = case["resolvedReferenceState"]
        used_states[state["id"]] = state

    status_counts = {status: 0 for status in allowed_statuses}
    for state in used_states.values():
        status_counts[state["status"]] += 1

    state_ids = sorted(used_states)
    states_used = [used_states[state_id] for state_id in state_ids]
    return {
        "referenceStateIds": state_ids,
        "referenceStateStatusCounts": status_counts,
        "referenceStates": states_used,
    }


def summarize_execution_statuses(cases: list[dict]) -> dict[str, int]:
    counts = Counter(case["executionStatus"] for case in cases)
    return {
        "planned": counts.get("planned", 0),
        "executed_success": counts.get("executed_success", 0),
        "executed_failed": counts.get("executed_failed", 0),
        "skipped": counts.get("skipped", 0),
    }


def compact_case_summary(case: dict) -> dict:
    return {
        "caseId": case["caseId"],
        "executionStatus": case["executionStatus"],
        "rendersExecuted": case["rendersExecuted"],
        "referenceStateId": case["referenceStateId"],
        "referenceStateStatus": case["referenceStateStatus"],
        "resolvedStimulusPath": case["resolvedInput"]["resolvedPath"],
        "referenceCapturePath": case["expectedArtifacts"]["referenceCapturePath"],
        "casePlanPath": case["expectedArtifacts"]["casePlanPath"],
        "referenceDirectory": case["expectedArtifacts"]["referenceDirectory"],
        "referenceWetPath": case["expectedArtifacts"]["referenceWetPath"],
        "referenceMetricsPath": case["expectedArtifacts"]["referenceMetricsPath"],
    }


def determine_group_status(execution_mode: str, cases: list[dict]) -> str:
    if not cases:
        return "no_declared_cases"
    counts = summarize_execution_statuses(cases)
    if execution_mode == "planning":
        return "planning_ready"
    if counts["executed_failed"] > 0:
        return "reference_capture_failed"
    if counts["skipped"] > 0:
        return "reference_capture_partial"
    if counts["executed_success"] > 0:
        return "reference_capture_executed"
    return "planning_ready"


def build_group_summary(
    group_name: str,
    summary_path: Path,
    cases: list[dict],
    allowed_state_statuses: list[str],
    execution_mode: str,
) -> dict:
    execution_counts = summarize_execution_statuses(cases)
    reference_state_usage = summarize_reference_state_usage(
        cases, allowed_state_statuses
    )

    if not cases:
        notes = [
            "No declared cases were selected for this group in this run.",
            "No plugin renders or reference captures were executed in this run.",
        ]
    elif execution_mode == "planning":
        notes = [
            "This group summary describes planned cases only.",
            "No plugin renders or reference captures were executed in this run.",
        ]
    else:
        notes = [
            "This group summary records reference capture attempts for the selected cases.",
            "Case status values distinguish planned, executed_success, executed_failed, and skipped outcomes.",
        ]

    return {
        "schemaVersion": 1,
        "group": group_name,
        "status": determine_group_status(execution_mode, cases),
        "executionMode": execution_mode,
        "scaffoldOnly": all(case["scaffoldOnly"] for case in cases) if cases else True,
        "rendersExecuted": any(case["rendersExecuted"] for case in cases),
        "summaryPath": str(summary_path.as_posix()),
        "caseCount": len(cases),
        "caseIds": [case["caseId"] for case in cases],
        "referenceStateIds": reference_state_usage["referenceStateIds"],
        "referenceStateStatusCounts": reference_state_usage[
            "referenceStateStatusCounts"
        ],
        "executionStatusCounts": execution_counts,
        "cases": [compact_case_summary(case) for case in cases],
        "notes": notes,
    }


def build_top_level_summaries(
    run_dir: Path,
    manifest: dict,
    selected_groups: list[str],
) -> dict[str, dict]:
    summaries: dict[str, dict] = {}
    group_summary_files = manifest["groupSummaryFiles"]
    for group_name, file_name in group_summary_files.items():
        summaries[file_name] = {
            "path": str((run_dir / file_name).as_posix()),
            "status": "generated" if group_name in selected_groups else "not_requested",
            "group": group_name,
        }

    for file_name in manifest.get("expectedTopLevelSummaryFiles", []):
        if file_name not in summaries:
            summaries[file_name] = {
                "path": str((run_dir / file_name).as_posix()),
                "status": "not_requested",
            }

    summaries["summary.json"] = {
        "path": str((run_dir / "summary.json").as_posix()),
        "status": "generated",
    }
    return summaries


def determine_run_status(execution_mode: str, execution_counts: dict[str, int]) -> str:
    if execution_mode == "planning":
        return "planning_ready"
    if execution_counts["executed_failed"] > 0:
        return "reference_capture_failed"
    if execution_counts["executed_success"] > 0 and execution_counts["skipped"] > 0:
        return "reference_capture_partial"
    if execution_counts["executed_success"] > 0:
        return "reference_capture_executed"
    return "planning_ready"


def main() -> int:
    args = parse_args()
    execution_mode = resolve_execution_mode(args)

    repo_root = Path(__file__).resolve().parent.parent
    manifest_path, manifest = load_manifest(repo_root, args.manifest)
    selected_groups = normalize_groups(manifest, args)
    requested_case_ids = parse_multi_csv_args(args.case_id)

    available_groups = {item["name"] for item in manifest["groups"]}

    stimuli_manifest_path, stimuli_manifest = load_stimuli_manifest(repo_root, manifest)
    stimuli_by_id, stimuli_by_file_name = build_stimulus_indexes(stimuli_manifest)

    reference_state_manifest_path, reference_state_manifest = load_reference_state_manifest(
        repo_root, manifest
    )
    reference_states_by_id, declared_reference_state_ids = load_reference_states(
        repo_root,
        reference_state_manifest_path,
        reference_state_manifest,
        available_groups,
    )

    group_cases, discovered_case_ids = load_declared_cases(
        repo_root,
        manifest,
        selected_groups,
        requested_case_ids,
        stimuli_by_id,
        stimuli_by_file_name,
        reference_states_by_id,
    )

    reference_plugin = resolve_reference_plugin(repo_root, args.reference_plugin)
    harness = resolve_harness(repo_root, args.harness)
    validate_execution_prerequisites(execution_mode, reference_plugin, harness)

    timestamp = timestamp_slug()
    artifacts_root = (repo_root / args.artifacts_root).resolve()
    run_dir = artifacts_root / timestamp
    run_dir.mkdir(parents=True, exist_ok=True)

    prepared_by_group, flat_cases = prepare_cases(
        run_dir,
        group_cases,
        manifest["baselineDefaults"],
        args.plugin_under_test,
        reference_plugin,
        harness,
        execution_mode,
    )

    write_case_artifacts(flat_cases)

    all_success = True
    if execution_mode == "execute_reference":
        all_success = execute_reference_cases(flat_cases, repo_root, args.keep_going)

    write_case_artifacts(flat_cases)

    empty_groups: list[str] = []
    group_summaries: dict[str, dict] = {}
    all_cases: list[dict] = []
    for group_name in selected_groups:
        summary_file_name = manifest["groupSummaryFiles"][group_name]
        summary_path = run_dir / summary_file_name
        planned_cases = prepared_by_group.get(group_name, [])
        all_cases.extend(planned_cases)
        group_summary = build_group_summary(
            group_name,
            summary_path,
            planned_cases,
            reference_state_manifest["allowedStatuses"],
            execution_mode,
        )
        if group_summary["caseCount"] == 0:
            empty_groups.append(group_name)
        write_json(summary_path, group_summary)
        group_summaries[group_name] = {
            "path": str(summary_path.as_posix()),
            "status": "generated",
            "caseCount": group_summary["caseCount"],
            "caseIds": group_summary["caseIds"],
            "referenceStateIds": group_summary["referenceStateIds"],
            "referenceStateStatusCounts": group_summary["referenceStateStatusCounts"],
            "executionStatusCounts": group_summary["executionStatusCounts"],
        }

    top_level_summaries = build_top_level_summaries(run_dir, manifest, selected_groups)
    reference_state_usage = summarize_reference_state_usage(
        all_cases, reference_state_manifest["allowedStatuses"]
    )
    execution_counts = summarize_execution_statuses(all_cases)

    summary_notes: list[str] = []
    if execution_mode == "planning":
        summary_notes.extend(
            [
                "This run planned declared cases and wrote orchestration artifacts only.",
                "No plugin renders or reference captures were executed in this run.",
            ]
        )
    else:
        summary_notes.extend(
            [
                "This run attempted reference capture commands for the selected cases.",
                "Only cases with successful harness execution and expected outputs are marked executed_success.",
            ]
        )
        if execution_counts["executed_failed"] > 0:
            summary_notes.append(
                "At least one case failed during execution. Review per-case reference_capture.json files."
            )
        if execution_counts["skipped"] > 0:
            summary_notes.append(
                "At least one case was skipped because execution prerequisites were missing or a prior failure stopped the run."
            )
    summary_notes.append(
        "Reference states may still be planned or pending_capture scaffolds rather than captured Blackhole targets."
    )

    summary = {
        "schemaVersion": 1,
        "runMode": execution_mode,
        "executionMode": execution_mode,
        "status": determine_run_status(execution_mode, execution_counts),
        "scaffoldOnly": execution_mode == "planning",
        "rendersExecuted": execution_counts["executed_success"]
        + execution_counts["executed_failed"]
        > 0,
        "timestamp": timestamp,
        "summaryPath": str((run_dir / "summary.json").as_posix()),
        "caseManifestPath": str(manifest_path.as_posix()),
        "stimuliManifestPath": str(stimuli_manifest_path.as_posix()),
        "referenceStateManifestPath": str(reference_state_manifest_path.as_posix()),
        "artifactsRoot": str(artifacts_root.as_posix()),
        "runDirectory": str(run_dir.as_posix()),
        "perCaseArtifactsRoot": str((run_dir / "cases").as_posix()),
        "baselineDefaults": manifest["baselineDefaults"],
        "requestedGroups": selected_groups,
        "requestedCaseIds": requested_case_ids,
        "discoveredCaseIds": discovered_case_ids,
        "emptyGroups": empty_groups,
        "pluginUnderTest": args.plugin_under_test,
        "referencePlugin": args.reference_plugin,
        "resolvedReferencePlugin": reference_plugin,
        "resolvedHarness": harness,
        "declaredReferenceStateIds": declared_reference_state_ids,
        "referenceStateIdsUsed": reference_state_usage["referenceStateIds"],
        "referenceStateStatusCounts": reference_state_usage[
            "referenceStateStatusCounts"
        ],
        "referenceStatesUsed": reference_state_usage["referenceStates"],
        "unresolvedReferenceStateIds": [],
        "totalCasesPlanned": len(all_cases),
        "totalCasesExecuted": execution_counts["executed_success"]
        + execution_counts["executed_failed"],
        "totalCasesSucceeded": execution_counts["executed_success"],
        "totalCasesFailed": execution_counts["executed_failed"],
        "totalCasesSkipped": execution_counts["skipped"],
        "planningOnlyCaseIds": [
            case["caseId"] for case in all_cases if case["executionStatus"] == "planned"
        ],
        "groupSummaries": group_summaries,
        "topLevelSummaries": top_level_summaries,
        "notes": summary_notes,
    }

    summary_path = run_dir / "summary.json"
    write_json(summary_path, summary)

    print(f"Created measurement run: {run_dir}")
    print(f"Wrote summary: {summary_path}")
    print(
        "Discovered case IDs: "
        + (", ".join(discovered_case_ids) if discovered_case_ids else "(none)")
    )
    if reference_plugin is not None:
        print(f"Resolved reference plugin: {reference_plugin['resolvedPath']}")
    else:
        print("Resolved reference plugin: (not provided)")
    if harness is not None:
        print(f"Resolved harness: {harness['resolvedPath']}")
    else:
        print("Resolved harness: (not provided)")
    print(
        "Reference states used: "
        + (
            ", ".join(reference_state_usage["referenceStateIds"])
            if reference_state_usage["referenceStateIds"]
            else "(none)"
        )
    )
    if execution_mode == "planning":
        print("No renders were executed.")
    else:
        print(
            "Execution counts: "
            f"success={execution_counts['executed_success']}, "
            f"failed={execution_counts['executed_failed']}, "
            f"skipped={execution_counts['skipped']}"
        )
    return 0 if all_success else 1


if __name__ == "__main__":
    sys.exit(main())
