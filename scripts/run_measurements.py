#!/usr/bin/env python3
"""Manifest-driven measurement planning runner for OutSpread M1."""

from __future__ import annotations

import argparse
import json
import re
import sys
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
    if isinstance(value, str):
        return [value]
    if isinstance(value, list) and all(isinstance(item, str) for item in value):
        return value
    raise SystemExit(f"error: {context} must be a string or a list of strings.")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Plan manifest-driven OutSpread measurement runs without rendering audio."
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
        help="Optional reference plugin identifier or path.",
    )
    return parser.parse_args()


def ensure_supported_mode(mode: str) -> None:
    if mode == "scaffold":
        return
    raise SystemExit(
        f"error: mode '{mode}' is not implemented in this ticket. "
        "Use scaffold mode to create planning artifacts without real renders."
    )


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


def build_expected_artifacts(run_dir: Path, case_id: str) -> dict:
    case_dir = run_dir / "cases" / case_id
    return {
        "caseDirectory": str(case_dir.as_posix()),
        "casePlanPath": str((case_dir / "case_plan.json").as_posix()),
        "referenceRenderPath": str((case_dir / "reference_render.wav").as_posix()),
        "pluginRenderPath": str((case_dir / "plugin_render.wav").as_posix()),
        "metricsPath": str((case_dir / "metrics.json").as_posix()),
    }


def resolve_case_settings(
    baseline_defaults: dict,
    case_data: dict,
    plugin_under_test: str | None,
    reference_plugin: str | None,
) -> dict:
    resolved = dict(baseline_defaults)
    for key in baseline_defaults:
        if key in case_data:
            resolved[key] = case_data[key]

    resolved["pluginUnderTest"] = case_data.get("plugin", plugin_under_test)
    resolved["referencePlugin"] = case_data.get("referencePlugin", reference_plugin)
    resolved["paramsByName"] = case_data.get("paramsByName", {})
    resolved["paramsByIndex"] = case_data.get("paramsByIndex", {})
    return resolved


def write_case_plans(
    run_dir: Path,
    group_cases: dict[str, list[dict]],
    baseline_defaults: dict,
    plugin_under_test: str | None,
    reference_plugin: str | None,
) -> dict[str, list[dict]]:
    planned_cases_by_group: dict[str, list[dict]] = {}
    for group_name, cases in group_cases.items():
        planned_cases_by_group[group_name] = []
        for case_record in cases:
            case_data = case_record["caseData"]
            case_id = case_data["id"]
            expected_artifacts = build_expected_artifacts(run_dir, case_id)
            case_dir = Path(expected_artifacts["caseDirectory"])
            case_dir.mkdir(parents=True, exist_ok=True)

            plan = {
                "schemaVersion": 1,
                "status": "planned_only",
                "rendersExecuted": False,
                "scaffoldOnly": bool(case_data.get("scaffoldOnly", True)),
                "caseId": case_id,
                "group": group_name,
                "caseFilePath": case_record["caseFilePath"],
                "resolvedInput": case_record["resolvedInput"],
                "resolvedSettings": resolve_case_settings(
                    baseline_defaults,
                    case_data,
                    plugin_under_test,
                    reference_plugin,
                ),
                "analysisProfile": case_data.get("analysisProfile", group_name),
                "expectedDeterminism": case_data.get("expectedDeterminism"),
                "referenceStateId": case_data.get("referenceStateId"),
                "referenceStateStatus": case_record["resolvedReferenceState"]["status"],
                "resolvedReferenceState": case_record["resolvedReferenceState"],
                "notes": case_data.get("notes"),
                "expectedArtifacts": expected_artifacts,
            }

            case_plan_path = Path(expected_artifacts["casePlanPath"])
            with case_plan_path.open("w", encoding="utf-8") as handle:
                json.dump(plan, handle, indent=2)
                handle.write("\n")

            planned_cases_by_group[group_name].append(plan)
    return planned_cases_by_group


def summarize_reference_state_usage(
    planned_cases: list[dict], allowed_statuses: list[str]
) -> dict:
    used_states: dict[str, dict] = {}
    for case in planned_cases:
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


def build_group_summary(
    group_name: str,
    summary_path: Path,
    planned_cases: list[dict],
    allowed_state_statuses: list[str],
) -> dict:
    if planned_cases:
        status = "planning_ready"
        notes = [
            "This group summary describes planned cases only.",
            "No plugin renders or reference captures were executed in this run.",
        ]
    else:
        status = "no_declared_cases"
        notes = [
            "No declared cases were selected for this group in this run.",
            "No plugin renders or reference captures were executed in this run.",
        ]

    reference_state_usage = summarize_reference_state_usage(
        planned_cases, allowed_state_statuses
    )

    return {
        "schemaVersion": 1,
        "group": group_name,
        "status": status,
        "scaffoldOnly": True,
        "rendersExecuted": False,
        "summaryPath": str(summary_path.as_posix()),
        "caseCount": len(planned_cases),
        "caseIds": [case["caseId"] for case in planned_cases],
        "referenceStateIds": reference_state_usage["referenceStateIds"],
        "referenceStateStatusCounts": reference_state_usage[
            "referenceStateStatusCounts"
        ],
        "cases": planned_cases,
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


def main() -> int:
    args = parse_args()
    ensure_supported_mode(args.mode)

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

    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    artifacts_root = (repo_root / args.artifacts_root).resolve()
    run_dir = artifacts_root / timestamp
    run_dir.mkdir(parents=True, exist_ok=True)

    planned_cases_by_group = write_case_plans(
        run_dir,
        group_cases,
        manifest["baselineDefaults"],
        args.plugin_under_test,
        args.reference_plugin,
    )

    empty_groups: list[str] = []
    group_summaries: dict[str, dict] = {}
    all_planned_cases: list[dict] = []
    for group_name in selected_groups:
        summary_file_name = manifest["groupSummaryFiles"][group_name]
        summary_path = run_dir / summary_file_name
        planned_cases = planned_cases_by_group.get(group_name, [])
        all_planned_cases.extend(planned_cases)
        group_summary = build_group_summary(
            group_name,
            summary_path,
            planned_cases,
            reference_state_manifest["allowedStatuses"],
        )
        if group_summary["caseCount"] == 0:
            empty_groups.append(group_name)
        with summary_path.open("w", encoding="utf-8") as handle:
            json.dump(group_summary, handle, indent=2)
            handle.write("\n")
        group_summaries[group_name] = {
            "path": str(summary_path.as_posix()),
            "status": "generated",
            "caseCount": group_summary["caseCount"],
            "caseIds": group_summary["caseIds"],
            "referenceStateIds": group_summary["referenceStateIds"],
            "referenceStateStatusCounts": group_summary["referenceStateStatusCounts"],
        }

    top_level_summaries = build_top_level_summaries(run_dir, manifest, selected_groups)
    reference_state_usage = summarize_reference_state_usage(
        all_planned_cases, reference_state_manifest["allowedStatuses"]
    )

    summary = {
        "schemaVersion": 1,
        "runMode": args.mode,
        "status": "planning_ready",
        "scaffoldOnly": True,
        "rendersExecuted": False,
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
        "declaredReferenceStateIds": declared_reference_state_ids,
        "referenceStateIdsUsed": reference_state_usage["referenceStateIds"],
        "referenceStateStatusCounts": reference_state_usage[
            "referenceStateStatusCounts"
        ],
        "referenceStatesUsed": reference_state_usage["referenceStates"],
        "unresolvedReferenceStateIds": [],
        "groupSummaries": group_summaries,
        "topLevelSummaries": top_level_summaries,
        "notes": [
            "This run planned declared cases and wrote orchestration artifacts only.",
            "No plugin renders or reference captures were executed in this ticket.",
            "Reference states may still be planned or pending_capture scaffolds rather than captured Blackhole targets.",
        ],
    }

    summary_path = run_dir / "summary.json"
    with summary_path.open("w", encoding="utf-8") as handle:
        json.dump(summary, handle, indent=2)
        handle.write("\n")

    print(f"Created measurement planning run: {run_dir}")
    print(f"Wrote summary: {summary_path}")
    print(
        "Discovered case IDs: "
        + (", ".join(discovered_case_ids) if discovered_case_ids else "(none)")
    )
    print(
        "Reference states used: "
        + (
            ", ".join(reference_state_usage["referenceStateIds"])
            if reference_state_usage["referenceStateIds"]
            else "(none)"
        )
    )
    print("No renders were executed.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
