#!/usr/bin/env python3
"""Analyze existing captured Blackhole reference artifacts into first-pass summaries."""

from __future__ import annotations

import argparse
import json
import math
import sys
import wave
from array import array
from datetime import datetime
from pathlib import Path
from statistics import fmean, pstdev


DEFAULT_BASELINE_TARGETS = [
    ("attack", "blackhole_attack_probe"),
    ("predelay", "blackhole_predelay_probe"),
    ("width", "blackhole_width_probe"),
    ("gravity", "blackhole_gravity_probe"),
    ("tail", "blackhole_tail_probe"),
    ("tone_eq", "blackhole_tone_eq_probe"),
    ("modulation", "blackhole_modulation_probe"),
    ("freeze_infinite", "blackhole_freeze_infinite_probe"),
]

GROUP_SUMMARY_FILES = {
    "freeze_infinite": "freeze_analysis_summary.json",
}


def load_json(path: Path) -> dict:
    if not path.is_file():
        raise SystemExit(f"error: required JSON file not found: {path}")
    try:
        with path.open("r", encoding="utf-8") as handle:
            payload = json.load(handle)
    except json.JSONDecodeError as exc:
        raise SystemExit(f"error: malformed JSON in {path}: {exc}") from exc
    if not isinstance(payload, dict):
        raise SystemExit(f"error: expected a JSON object in {path}")
    return payload


def write_json(path: Path, payload: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as handle:
        json.dump(payload, handle, indent=2)
        handle.write("\n")


def parse_csv(raw: str | None) -> list[str]:
    if raw is None:
        return []
    return [item.strip() for item in raw.split(",") if item.strip()]


def timestamp_slug() -> str:
    return datetime.now().strftime("%Y%m%d_%H%M%S")


def iso_now() -> str:
    return datetime.now().isoformat(timespec="seconds")


def safe_dbfs(value: float) -> float | None:
    if value <= 0.0:
        return None
    return 20.0 * math.log10(value)


def ms_from_samples(sample_index: int, sample_rate: int) -> float:
    return (sample_index / sample_rate) * 1000.0


def samples_from_ms(sample_rate: int, duration_ms: float) -> int:
    return max(1, int(round(sample_rate * (duration_ms / 1000.0))))


def group_summary_filename(group_name: str) -> str:
    return GROUP_SUMMARY_FILES.get(group_name, f"{group_name}_analysis_summary.json")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=(
            "Analyze existing captured Blackhole reference artifacts into "
            "first-pass descriptive summaries."
        )
    )
    parser.add_argument(
        "--artifacts-root",
        default="artifacts/reference_analysis",
        help="Root directory for timestamped reference-analysis runs.",
    )
    parser.add_argument(
        "--measurements-root",
        default="artifacts/measurements",
        help="Root directory containing prior measurement capture runs.",
    )
    parser.add_argument(
        "--reference-state-manifest",
        default="tests/reference_states/reference_state_manifest.json",
        help="Path to the reusable reference-state manifest JSON.",
    )
    parser.add_argument(
        "--groups",
        help="Optional comma-separated subset of baseline groups to analyze.",
    )
    parser.add_argument(
        "--state-ids",
        help="Optional comma-separated reusable reference-state IDs to analyze.",
    )
    return parser.parse_args()


def validate_state_manifest(path: Path, manifest: dict) -> None:
    state_directory = manifest.get("stateDirectory")
    if not isinstance(state_directory, str) or not state_directory.strip():
        raise SystemExit(
            "error: reference-state manifest must define a non-empty 'stateDirectory'."
        )


def load_reference_states(
    repo_root: Path, manifest_path: Path
) -> tuple[dict[str, dict], list[str]]:
    manifest = load_json(manifest_path)
    validate_state_manifest(manifest_path, manifest)

    state_dir = (repo_root / manifest["stateDirectory"]).resolve()
    if not state_dir.is_dir():
        raise SystemExit(f"error: reference-state directory does not exist: {state_dir}")

    states_by_id: dict[str, dict] = {}
    for state_path in sorted(state_dir.glob("*.json")):
        if state_path.resolve() == manifest_path.resolve():
            continue
        state = load_json(state_path)
        state_id = state.get("id")
        if not isinstance(state_id, str) or not state_id.strip():
            raise SystemExit(
                f"error: reference-state file is missing a usable 'id': {state_path}"
            )
        if state_id in states_by_id:
            raise SystemExit(f"error: duplicate reference-state ID discovered: {state_id}")
        state["stateFilePath"] = str(state_path.resolve().as_posix())
        states_by_id[state_id] = state

    return states_by_id, sorted(states_by_id)


def select_state_ids(
    args: argparse.Namespace, states_by_id: dict[str, dict]
) -> list[tuple[str | None, str]]:
    default_group_to_state = dict(DEFAULT_BASELINE_TARGETS)
    requested_groups = parse_csv(args.groups)
    requested_state_ids = parse_csv(args.state_ids)

    if not requested_groups and not requested_state_ids:
        return list(DEFAULT_BASELINE_TARGETS)

    ordered: list[tuple[str | None, str]] = []
    seen: set[str] = set()

    for group_name in requested_groups:
        if group_name not in default_group_to_state:
            raise SystemExit(
                "error: unknown analysis group '"
                + group_name
                + "'. Expected one of: "
                + ", ".join(group for group, _ in DEFAULT_BASELINE_TARGETS)
            )
        state_id = default_group_to_state[group_name]
        if state_id not in seen:
            ordered.append((group_name, state_id))
            seen.add(state_id)

    for state_id in requested_state_ids:
        if state_id in seen:
            continue
        preferred_group = None
        if state_id in states_by_id:
            target_groups = states_by_id[state_id].get("targetGroups")
            if isinstance(target_groups, list) and target_groups:
                first_group = target_groups[0]
                if isinstance(first_group, str):
                    preferred_group = first_group
        ordered.append((preferred_group, state_id))
        seen.add(state_id)

    return ordered


def read_wave_file(path: Path) -> dict:
    try:
        with wave.open(str(path), "rb") as handle:
            channels = handle.getnchannels()
            sample_width = handle.getsampwidth()
            sample_rate = handle.getframerate()
            frame_count = handle.getnframes()
            raw_frames = handle.readframes(frame_count)
    except wave.Error as exc:
        raise SystemExit(f"error: unreadable WAV file {path}: {exc}") from exc

    if channels <= 0:
        raise SystemExit(f"error: WAV file has invalid channel count: {path}")
    if sample_width not in (1, 2, 3, 4):
        raise SystemExit(
            f"error: unsupported WAV sample width {sample_width} bytes in {path}"
        )

    channel_data = [array("f") for _ in range(channels)]
    if sample_width == 1:
        for index, value in enumerate(raw_frames):
            channel_data[index % channels].append((value - 128) / 128.0)
    elif sample_width == 2:
        pcm = array("h")
        pcm.frombytes(raw_frames)
        if sys.byteorder != "little":
            pcm.byteswap()
        scale = 32768.0
        for index, value in enumerate(pcm):
            channel_data[index % channels].append(value / scale)
    elif sample_width == 3:
        scale = 8388608.0
        view = memoryview(raw_frames)
        sample_index = 0
        for offset in range(0, len(view), 3):
            value = view[offset] | (view[offset + 1] << 8) | (view[offset + 2] << 16)
            if value & 0x800000:
                value -= 0x1000000
            channel_data[sample_index % channels].append(value / scale)
            sample_index += 1
    else:
        pcm = array("i")
        pcm.frombytes(raw_frames)
        if sys.byteorder != "little":
            pcm.byteswap()
        scale = 2147483648.0
        for index, value in enumerate(pcm):
            channel_data[index % channels].append(value / scale)

    return {
        "path": str(path.as_posix()),
        "sampleRate": sample_rate,
        "channels": channels,
        "sampleWidthBytes": sample_width,
        "bitDepth": sample_width * 8,
        "frameCount": frame_count,
        "durationSeconds": frame_count / sample_rate if sample_rate else 0.0,
        "channelData": channel_data,
    }


def mono_mix(channel_data: list[array]) -> array:
    if not channel_data:
        return array("f")
    if len(channel_data) == 1:
        return channel_data[0]

    frame_count = len(channel_data[0])
    mixed = array("f")
    channel_count = float(len(channel_data))
    for sample_index in range(frame_count):
        mixed.append(
            sum(channel[sample_index] for channel in channel_data) / channel_count
        )
    return mixed


def rms(samples: array, start: int = 0, end: int | None = None) -> float:
    actual_end = len(samples) if end is None else min(len(samples), end)
    actual_start = max(0, min(start, actual_end))
    count = actual_end - actual_start
    if count <= 0:
        return 0.0
    accumulator = 0.0
    for index in range(actual_start, actual_end):
        value = samples[index]
        accumulator += value * value
    return math.sqrt(accumulator / count)


def peak_abs(samples: array, start: int = 0, end: int | None = None) -> float:
    actual_end = len(samples) if end is None else min(len(samples), end)
    actual_start = max(0, min(start, actual_end))
    peak = 0.0
    for index in range(actual_start, actual_end):
        value = abs(samples[index])
        if value > peak:
            peak = value
    return peak


def build_rms_windows(samples: array, sample_rate: int, window_ms: float) -> list[dict]:
    window_size = samples_from_ms(sample_rate, window_ms)
    windows: list[dict] = []
    for start in range(0, len(samples), window_size):
        end = min(len(samples), start + window_size)
        if end <= start:
            continue
        window_rms = rms(samples, start, end)
        windows.append(
            {
                "startSample": start,
                "endSample": end,
                "startMs": ms_from_samples(start, sample_rate),
                "endMs": ms_from_samples(end, sample_rate),
                "rms": window_rms,
                "rmsDbfs": safe_dbfs(window_rms),
                "peakAbs": peak_abs(samples, start, end),
            }
        )
    return windows


def detect_onset(windows: list[dict], noise_window_count: int = 4) -> dict:
    if not windows:
        return {
            "onsetFound": False,
            "onsetSample": None,
            "onsetMs": None,
            "noiseFloorRms": 0.0,
            "noiseFloorDbfs": None,
            "peakWindowRms": 0.0,
            "peakWindowDbfs": None,
            "thresholdRms": 0.0,
            "thresholdDbfs": None,
            "peakWindowIndex": None,
        }

    peak_window_index = max(range(len(windows)), key=lambda index: windows[index]["rms"])
    peak_window_rms = windows[peak_window_index]["rms"]
    noise_slice = windows[: max(1, min(noise_window_count, len(windows)))]
    noise_floor_rms = fmean(window["rms"] for window in noise_slice)
    threshold_rms = max(noise_floor_rms * 4.0, peak_window_rms * 0.05, 1e-6)

    for window in windows:
        if window["rms"] >= threshold_rms:
            return {
                "onsetFound": True,
                "onsetSample": window["startSample"],
                "onsetMs": window["startMs"],
                "noiseFloorRms": noise_floor_rms,
                "noiseFloorDbfs": safe_dbfs(noise_floor_rms),
                "peakWindowRms": peak_window_rms,
                "peakWindowDbfs": safe_dbfs(peak_window_rms),
                "thresholdRms": threshold_rms,
                "thresholdDbfs": safe_dbfs(threshold_rms),
                "peakWindowIndex": peak_window_index,
            }

    return {
        "onsetFound": False,
        "onsetSample": None,
        "onsetMs": None,
        "noiseFloorRms": noise_floor_rms,
        "noiseFloorDbfs": safe_dbfs(noise_floor_rms),
        "peakWindowRms": peak_window_rms,
        "peakWindowDbfs": safe_dbfs(peak_window_rms),
        "thresholdRms": threshold_rms,
        "thresholdDbfs": safe_dbfs(threshold_rms),
        "peakWindowIndex": peak_window_index,
    }


def build_envelope_preview(
    windows: list[dict], onset_sample: int | None, limit: int
) -> list[dict]:
    if onset_sample is None:
        selected = windows[:limit]
    else:
        selected = [window for window in windows if window["startSample"] >= onset_sample][:limit]
    return [
        {
            "startMs": round(window["startMs"], 3),
            "endMs": round(window["endMs"], 3),
            "rmsDbfs": round(window["rmsDbfs"], 3) if window["rmsDbfs"] is not None else None,
        }
        for window in selected
    ]


def find_first_window_at_or_above(
    windows: list[dict], start_index: int, threshold_rms: float
) -> dict | None:
    for window in windows[start_index:]:
        if window["rms"] >= threshold_rms:
            return window
    return None


def segment_rms_db(samples: array, start: int, end: int) -> float | None:
    return safe_dbfs(rms(samples, start, end))


def energy_centroid_ms(samples: array, sample_rate: int, start: int = 0) -> float | None:
    numerator = 0.0
    denominator = 0.0
    for offset, value in enumerate(samples[start:], start):
        energy = value * value
        numerator += offset * energy
        denominator += energy
    if denominator <= 0.0:
        return None
    return ms_from_samples(int(round(numerator / denominator)), sample_rate)


def lowpass_one_pole(samples: array, sample_rate: int, cutoff_hz: float) -> array:
    if cutoff_hz <= 0.0:
        return array("f", [0.0] * len(samples))
    alpha = math.exp((-2.0 * math.pi * cutoff_hz) / sample_rate)
    output = array("f")
    previous = 0.0
    for sample in samples:
        previous = ((1.0 - alpha) * sample) + (alpha * previous)
        output.append(previous)
    return output


def subtract_signals(a: array, b: array) -> array:
    count = min(len(a), len(b))
    output = array("f")
    for index in range(count):
        output.append(a[index] - b[index])
    return output


def slice_samples(samples: array, start: int, end: int) -> array:
    clipped_end = min(len(samples), end)
    clipped_start = max(0, min(start, clipped_end))
    return array("f", samples[clipped_start:clipped_end])


def summarize_band_proxy(samples: array, sample_rate: int) -> dict:
    low = lowpass_one_pole(samples, sample_rate, 300.0)
    low_mid = lowpass_one_pole(samples, sample_rate, 3000.0)
    mid = subtract_signals(low_mid, low)
    high = subtract_signals(samples, low_mid)

    low_rms = rms(low)
    mid_rms = rms(mid)
    high_rms = rms(high)
    total = low_rms + mid_rms + high_rms

    return {
        "method": "one_pole_filter_bank_proxy",
        "lowBandRmsDbfs": safe_dbfs(low_rms),
        "midBandRmsDbfs": safe_dbfs(mid_rms),
        "highBandRmsDbfs": safe_dbfs(high_rms),
        "lowBandShare": (low_rms / total) if total > 0.0 else None,
        "midBandShare": (mid_rms / total) if total > 0.0 else None,
        "highBandShare": (high_rms / total) if total > 0.0 else None,
        "spectralTiltProxyDb": (
            safe_dbfs(high_rms / low_rms) if low_rms > 0.0 and high_rms > 0.0 else None
        ),
    }


def correlation(left: array, right: array) -> float | None:
    count = min(len(left), len(right))
    if count <= 1:
        return None
    mean_left = fmean(left[:count])
    mean_right = fmean(right[:count])
    numerator = 0.0
    left_energy = 0.0
    right_energy = 0.0
    for index in range(count):
        left_value = left[index] - mean_left
        right_value = right[index] - mean_right
        numerator += left_value * right_value
        left_energy += left_value * left_value
        right_energy += right_value * right_value
    if left_energy <= 0.0 or right_energy <= 0.0:
        return None
    return numerator / math.sqrt(left_energy * right_energy)


def autocorrelation_proxy(values: list[float], window_ms: float) -> dict:
    if len(values) < 8:
        return {
            "method": "windowed_envelope_autocorrelation_proxy",
            "dominantMovementPeriodMs": None,
            "dominantMovementCorrelation": None,
        }

    start = values[0]
    end = values[-1]
    detrended = [
        value - (start + ((end - start) * index / max(1, len(values) - 1)))
        for index, value in enumerate(values)
    ]
    min_lag = 2
    max_lag = max(min_lag, min(len(values) // 2, int(round(5000.0 / window_ms))))
    best_lag = None
    best_correlation = None

    for lag in range(min_lag, max_lag + 1):
        left = detrended[:-lag]
        right = detrended[lag:]
        if len(left) < 2:
            continue
        mean_left = fmean(left)
        mean_right = fmean(right)
        numerator = 0.0
        left_energy = 0.0
        right_energy = 0.0
        for left_value, right_value in zip(left, right):
            centered_left = left_value - mean_left
            centered_right = right_value - mean_right
            numerator += centered_left * centered_right
            left_energy += centered_left * centered_left
            right_energy += centered_right * centered_right
        if left_energy <= 0.0 or right_energy <= 0.0:
            continue
        score = numerator / math.sqrt(left_energy * right_energy)
        if best_correlation is None or score > best_correlation:
            best_correlation = score
            best_lag = lag

    return {
        "method": "windowed_envelope_autocorrelation_proxy",
        "dominantMovementPeriodMs": (best_lag * window_ms) if best_lag is not None else None,
        "dominantMovementCorrelation": best_correlation,
    }


def resolve_case_from_capture_metadata(
    state_id: str, state: dict, preferred_group: str | None
) -> tuple[dict | None, list[str]]:
    capture = state.get("capture")
    if not isinstance(capture, dict):
        return None, [f"State {state_id} has no capture object to resolve artifacts from."]

    captured_cases = capture.get("capturedCases")
    if not isinstance(captured_cases, list):
        return None, [f"State {state_id} capture object has no usable capturedCases list."]

    successful = [
        case
        for case in captured_cases
        if isinstance(case, dict) and case.get("executionStatus") == "executed_success"
    ]
    if not successful:
        return None, [f"State {state_id} capture object has no successful captured cases."]

    if preferred_group is not None:
        matching_group = [
            case for case in successful if case.get("group") == preferred_group
        ]
        if matching_group:
            return matching_group[0], []

    return successful[0], []


def discover_case_from_measurements_root(
    measurements_root: Path, state_id: str, preferred_group: str | None
) -> tuple[dict | None, list[str]]:
    issues: list[str] = []
    if not measurements_root.is_dir():
        return None, [f"Measurements root does not exist: {measurements_root}"]

    discovered: list[Path] = []
    for capture_path in sorted(
        measurements_root.glob("*/cases/*/reference_capture.json"), reverse=True
    ):
        try:
            capture_data = load_json(capture_path)
        except SystemExit as exc:
            issues.append(str(exc))
            continue
        if capture_data.get("referenceStateId") != state_id:
            continue
        if capture_data.get("executionStatus") != "executed_success":
            continue
        if preferred_group is not None and capture_data.get("group") != preferred_group:
            continue
        discovered.append(capture_path)

    if not discovered:
        issues.append(
            f"No successful reference_capture.json artifact was found for state {state_id} under {measurements_root}."
        )
        return None, issues

    capture_path = discovered[0]
    capture_data = load_json(capture_path)
    expected = capture_data.get("expectedArtifacts", {})
    return {
        "caseId": capture_data.get("caseId"),
        "group": capture_data.get("group"),
        "referenceCapturePath": str(capture_path.as_posix()),
        "referenceWetPath": expected.get("referenceWetPath"),
        "referenceMetricsPath": expected.get("referenceMetricsPath"),
        "casePlanPath": expected.get("casePlanPath"),
        "referenceDirectory": expected.get("referenceDirectory"),
    }, issues


def resolve_artifact_source(
    state_id: str, state: dict, preferred_group: str | None, measurements_root: Path
) -> tuple[dict | None, list[str], str]:
    metadata_case, metadata_issues = resolve_case_from_capture_metadata(
        state_id, state, preferred_group
    )
    if metadata_case is not None:
        return metadata_case, metadata_issues, "state_capture_metadata"

    scanned_case, scan_issues = discover_case_from_measurements_root(
        measurements_root, state_id, preferred_group
    )
    return scanned_case, metadata_issues + scan_issues, "measurements_root_scan"


def ensure_path(candidate: object, description: str) -> Path:
    if not isinstance(candidate, str) or not candidate.strip():
        raise SystemExit(f"error: missing {description}")
    path = Path(candidate)
    if not path.is_file():
        raise SystemExit(f"error: expected {description} file does not exist: {path}")
    return path


def normalize_artifact_paths(reference_capture: dict, case_record: dict) -> dict:
    expected = reference_capture.get("expectedArtifacts", {})
    return {
        "referenceCapturePath": case_record.get("referenceCapturePath")
        or expected.get("referenceCapturePath"),
        "casePlanPath": case_record.get("casePlanPath") or expected.get("casePlanPath"),
        "referenceDirectory": case_record.get("referenceDirectory")
        or expected.get("referenceDirectory"),
        "referenceWetPath": case_record.get("referenceWetPath")
        or expected.get("referenceWetPath"),
        "referenceMetricsPath": case_record.get("referenceMetricsPath")
        or expected.get("referenceMetricsPath"),
        "renderStdoutPath": case_record.get("renderStdoutPath")
        or expected.get("renderStdoutPath"),
        "renderStderrPath": case_record.get("renderStderrPath")
        or expected.get("renderStderrPath"),
        "analyzeStdoutPath": case_record.get("analyzeStdoutPath")
        or expected.get("analyzeStdoutPath"),
        "analyzeStderrPath": case_record.get("analyzeStderrPath")
        or expected.get("analyzeStderrPath"),
    }


def analyze_attack_group(
    wet_mono: array, dry_mono: array, wet_info: dict, dry_info: dict, harness_metrics: dict
) -> tuple[dict, list[str], str]:
    wet_windows = build_rms_windows(wet_mono, wet_info["sampleRate"], 5.0)
    dry_windows = build_rms_windows(dry_mono, dry_info["sampleRate"], 5.0)
    wet_onset = detect_onset(wet_windows)
    dry_onset = detect_onset(dry_windows)

    onset_index = 0
    if wet_onset["onsetSample"] is not None:
        onset_index = next(
            (
                index
                for index, window in enumerate(wet_windows)
                if window["startSample"] == wet_onset["onsetSample"]
            ),
            0,
        )

    peak_window = (
        wet_windows[wet_onset["peakWindowIndex"]]
        if wet_onset["peakWindowIndex"] is not None
        else None
    )
    peak_rms = peak_window["rms"] if peak_window is not None else 0.0
    half_window = find_first_window_at_or_above(wet_windows, onset_index, peak_rms * 0.5)
    ninety_window = find_first_window_at_or_above(wet_windows, onset_index, peak_rms * 0.9)

    metrics = {
        "wetOnsetMs": wet_onset["onsetMs"],
        "dryOnsetMs": dry_onset["onsetMs"],
        "wetPeakMs": peak_window["startMs"] if peak_window is not None else None,
        "riseTo50PercentMs": (
            half_window["startMs"] - wet_onset["onsetMs"]
            if half_window is not None and wet_onset["onsetMs"] is not None
            else None
        ),
        "riseTo90PercentMs": (
            ninety_window["startMs"] - wet_onset["onsetMs"]
            if ninety_window is not None and wet_onset["onsetMs"] is not None
            else None
        ),
        "shortWindowEnvelopeDbfs": build_envelope_preview(
            wet_windows, wet_onset["onsetSample"], 10
        ),
        "wetPeakDbfs": harness_metrics.get("wetPeakDbfs"),
        "wetRmsDbfs": harness_metrics.get("wetRmsDbfs"),
    }
    caveats = [
        "Attack timing is measured from short RMS windows on the captured wet output.",
        "Rise metrics are descriptive proxies rather than final law-extraction values.",
    ]
    interpretation = (
        f"Wet energy first crosses the onset threshold at about {metrics['wetOnsetMs']:.2f} ms "
        f"and reaches its peak window around {metrics['wetPeakMs']:.2f} ms."
        if metrics["wetOnsetMs"] is not None and metrics["wetPeakMs"] is not None
        else "Wet onset timing could not be resolved from the current capture."
    )
    return metrics, caveats, interpretation


def analyze_predelay_group(
    wet_mono: array, dry_mono: array, wet_info: dict, dry_info: dict, harness_metrics: dict
) -> tuple[dict, list[str], str]:
    wet_windows = build_rms_windows(wet_mono, wet_info["sampleRate"], 5.0)
    dry_windows = build_rms_windows(dry_mono, dry_info["sampleRate"], 5.0)
    wet_onset = detect_onset(wet_windows)
    dry_onset = detect_onset(dry_windows)
    wet_peak_index = wet_onset["peakWindowIndex"]
    dry_peak_index = dry_onset["peakWindowIndex"]
    wet_peak_ms = wet_windows[wet_peak_index]["startMs"] if wet_peak_index is not None else None
    dry_peak_ms = dry_windows[dry_peak_index]["startMs"] if dry_peak_index is not None else None

    metrics = {
        "dryOnsetMs": dry_onset["onsetMs"],
        "wetOnsetMs": wet_onset["onsetMs"],
        "measuredWetOnsetDelayMs": (
            wet_onset["onsetMs"] - dry_onset["onsetMs"]
            if wet_onset["onsetMs"] is not None and dry_onset["onsetMs"] is not None
            else None
        ),
        "dryPeakMs": dry_peak_ms,
        "wetPeakMs": wet_peak_ms,
        "peakGapMs": (
            wet_peak_ms - dry_peak_ms
            if wet_peak_ms is not None and dry_peak_ms is not None
            else None
        ),
        "harnessDetectedLatencySamples": harness_metrics.get("detectedLatencySamples"),
        "shortWindowEnvelopeDbfs": build_envelope_preview(
            wet_windows, wet_onset["onsetSample"], 10
        ),
    }
    caveats = [
        "Predelay timing is measured from dry and wet onset thresholds on the captured audio.",
        "The harness latency figure is included as a coarse cross-check rather than a final timing authority.",
    ]
    interpretation = (
        f"The wet field begins about {metrics['measuredWetOnsetDelayMs']:.2f} ms after the dry transient."
        if metrics["measuredWetOnsetDelayMs"] is not None
        else "Predelay timing could not be measured from the current artifacts."
    )
    return metrics, caveats, interpretation


def analyze_width_group(
    wet_channels: list[array], wet_info: dict
) -> tuple[dict, list[str], str]:
    metrics = {
        "outputChannels": wet_info["channels"],
        "outputShape": "stereo" if wet_info["channels"] >= 2 else "mono",
        "leftRightCorrelation": None,
        "midRmsDbfs": None,
        "sideRmsDbfs": None,
        "sideMinusMidDb": None,
        "leftRightBalanceDb": None,
    }
    caveats = ["Width metrics are first-pass output-shape proxies only."]

    if wet_info["channels"] < 2:
        caveats.append(
            "The current width capture artifact is mono, so stereo spread proxies are unavailable for this state."
        )
        interpretation = (
            "The resolved width artifact is mono output, so this pass can only report that stereo spread metrics are unavailable."
        )
        return metrics, caveats, interpretation

    left = wet_channels[0]
    right = wet_channels[1]
    count = min(len(left), len(right))
    mid = array("f")
    side = array("f")
    for index in range(count):
        mid.append((left[index] + right[index]) * 0.5)
        side.append((left[index] - right[index]) * 0.5)

    left_rms = rms(left)
    right_rms = rms(right)
    mid_rms = rms(mid)
    side_rms = rms(side)
    metrics.update(
        {
            "leftRightCorrelation": correlation(left, right),
            "midRmsDbfs": safe_dbfs(mid_rms),
            "sideRmsDbfs": safe_dbfs(side_rms),
            "sideMinusMidDb": (
                safe_dbfs(side_rms / mid_rms) if mid_rms > 0.0 and side_rms > 0.0 else None
            ),
            "leftRightBalanceDb": (
                safe_dbfs(left_rms / right_rms)
                if left_rms > 0.0 and right_rms > 0.0
                else None
            ),
        }
    )
    interpretation = (
        f"Stereo width proxy shows left/right correlation {metrics['leftRightCorrelation']:.3f} "
        f"with side-minus-mid balance {metrics['sideMinusMidDb']:.2f} dB."
        if metrics["leftRightCorrelation"] is not None and metrics["sideMinusMidDb"] is not None
        else "Stereo width proxies were only partially available from the current artifact."
    )
    return metrics, caveats, interpretation


def analyze_gravity_group(
    wet_mono: array, wet_info: dict
) -> tuple[dict, list[str], str]:
    wet_windows = build_rms_windows(wet_mono, wet_info["sampleRate"], 25.0)
    onset = detect_onset(wet_windows)
    onset_sample = onset["onsetSample"] or 0
    onset_ms = onset["onsetMs"] or 0.0
    early_start = onset_sample
    early_end = min(len(wet_mono), early_start + samples_from_ms(wet_info["sampleRate"], 500.0))
    late_start = min(len(wet_mono), early_start + samples_from_ms(wet_info["sampleRate"], 1500.0))
    late_end = min(len(wet_mono), late_start + samples_from_ms(wet_info["sampleRate"], 3000.0))
    peak_window = (
        wet_windows[onset["peakWindowIndex"]]
        if onset["peakWindowIndex"] is not None
        else None
    )
    early_db = segment_rms_db(wet_mono, early_start, early_end)
    late_db = segment_rms_db(wet_mono, late_start, late_end)

    metrics = {
        "wetOnsetMs": onset["onsetMs"],
        "peakWindowMs": peak_window["startMs"] if peak_window is not None else None,
        "peakAfterOnsetMs": (
            peak_window["startMs"] - onset_ms if peak_window is not None else None
        ),
        "energyCentroidMs": energy_centroid_ms(wet_mono, wet_info["sampleRate"], onset_sample),
        "earlyEnergyDbfs": early_db,
        "lateEnergyDbfs": late_db,
        "lateMinusEarlyDb": (
            late_db - early_db if early_db is not None and late_db is not None else None
        ),
        "earlyEnvelopeDbfs": build_envelope_preview(wet_windows, onset_sample, 12),
    }
    caveats = [
        "Gravity behavior here is summarized with time-distribution proxies rather than true parameter-law extraction.",
        "Peak timing and energy centroid are useful for later pull-back or reverse-like comparisons, but they are not final acceptance metrics.",
    ]
    interpretation = (
        f"Gravity proxy peaks about {metrics['peakAfterOnsetMs']:.2f} ms after wet onset, "
        f"with late-minus-early energy {metrics['lateMinusEarlyDb']:.2f} dB."
        if metrics["peakAfterOnsetMs"] is not None and metrics["lateMinusEarlyDb"] is not None
        else "Gravity time-distribution metrics could not be resolved cleanly from the current capture."
    )
    return metrics, caveats, interpretation


def analyze_tail_group(
    wet_mono: array, wet_info: dict
) -> tuple[dict, list[str], str]:
    wet_windows = build_rms_windows(wet_mono, wet_info["sampleRate"], 100.0)
    onset = detect_onset(wet_windows)
    onset_sample = onset["onsetSample"] or 0
    short_start = onset_sample
    short_end = min(len(wet_mono), short_start + samples_from_ms(wet_info["sampleRate"], 500.0))
    medium_start = short_end
    medium_end = min(len(wet_mono), medium_start + samples_from_ms(wet_info["sampleRate"], 1500.0))
    late_start = min(len(wet_mono), onset_sample + samples_from_ms(wet_info["sampleRate"], 2000.0))
    late_end = min(len(wet_mono), onset_sample + samples_from_ms(wet_info["sampleRate"], 5000.0))

    short_db = segment_rms_db(wet_mono, short_start, short_end)
    medium_db = segment_rms_db(wet_mono, medium_start, medium_end)
    late_db = segment_rms_db(wet_mono, late_start, late_end)

    decay_slope = None
    if short_db is not None and late_db is not None and late_end > short_start:
        seconds = (late_end - short_start) / wet_info["sampleRate"]
        if seconds > 0.0:
            decay_slope = (late_db - short_db) / seconds

    metrics = {
        "wetOnsetMs": onset["onsetMs"],
        "shortWindowRmsDbfs": short_db,
        "mediumWindowRmsDbfs": medium_db,
        "lateWindowRmsDbfs": late_db,
        "decaySlopeDbPerSecond": decay_slope,
        "tailEnvelopePreviewDbfs": build_envelope_preview(wet_windows, onset_sample, 15),
    }
    caveats = [
        "Tail windows are broad descriptive slices rather than final decay-model metrics."
    ]
    interpretation = (
        f"Tail level moves from {short_db:.2f} dBFS in the short window to {late_db:.2f} dBFS in the late window."
        if short_db is not None and late_db is not None
        else "Tail decay windows could not be summarized from the current capture."
    )
    return metrics, caveats, interpretation


def analyze_tone_eq_group(
    wet_mono: array, wet_info: dict
) -> tuple[dict, list[str], str]:
    wet_windows = build_rms_windows(wet_mono, wet_info["sampleRate"], 10.0)
    onset = detect_onset(wet_windows)
    onset_sample = onset["onsetSample"] or 0
    segment_end = min(len(wet_mono), onset_sample + samples_from_ms(wet_info["sampleRate"], 3000.0))
    analysis_segment = slice_samples(wet_mono, onset_sample, segment_end)
    band_summary = summarize_band_proxy(analysis_segment, wet_info["sampleRate"])

    metrics = {
        "analysisSegmentSeconds": len(analysis_segment) / wet_info["sampleRate"],
        "bandEnergyProxy": band_summary,
    }
    caveats = [
        "Tone shaping is summarized with a simple low/mid/high filter-bank proxy over the captured wet output.",
        "These band balances are descriptive only and are not final extracted EQ or resonance laws.",
    ]
    high_share = band_summary["highBandShare"]
    low_share = band_summary["lowBandShare"]
    if high_share is not None and low_share is not None:
        emphasis = "high-weighted" if high_share > low_share else "low-weighted"
        interpretation = (
            f"The tone proxy reads as {emphasis}, with spectral tilt proxy "
            f"{band_summary['spectralTiltProxyDb']:.2f} dB."
            if band_summary["spectralTiltProxyDb"] is not None
            else f"The tone proxy reads as {emphasis}."
        )
    else:
        interpretation = "Tone-weighting proxies were unavailable from the current capture."
    return metrics, caveats, interpretation


def analyze_modulation_group(
    wet_mono: array, wet_info: dict
) -> tuple[dict, list[str], str]:
    wet_windows = build_rms_windows(wet_mono, wet_info["sampleRate"], 100.0)
    onset = detect_onset(wet_windows)
    onset_sample = onset["onsetSample"] or 0
    envelope_windows = [
        window for window in wet_windows if window["startSample"] >= onset_sample
    ]
    envelope_db = [
        window["rmsDbfs"] for window in envelope_windows if window["rmsDbfs"] is not None
    ]
    movement_proxy = autocorrelation_proxy(envelope_db, 100.0)

    metrics = {
        "windowCount": len(envelope_db),
        "windowedRmsMeanDbfs": fmean(envelope_db) if envelope_db else None,
        "windowedRmsStdDevDb": pstdev(envelope_db) if len(envelope_db) > 1 else None,
        "windowedRmsRangeDb": (
            max(envelope_db) - min(envelope_db) if len(envelope_db) > 1 else None
        ),
        "movementProxy": movement_proxy,
    }
    caveats = [
        "Modulation behavior is summarized with windowed RMS movement proxies rather than a final modulation-rate extraction.",
        "The dominant movement period is an autocorrelation estimate on the wet envelope, not a direct parameter readout.",
    ]
    interpretation = (
        f"Envelope movement spans about {metrics['windowedRmsRangeDb']:.2f} dB with a rough dominant period of "
        f"{movement_proxy['dominantMovementPeriodMs']:.1f} ms."
        if metrics["windowedRmsRangeDb"] is not None
        and movement_proxy["dominantMovementPeriodMs"] is not None
        else "Only coarse modulation proxies were available from the current capture."
    )
    return metrics, caveats, interpretation


def analyze_freeze_group(
    wet_mono: array, wet_info: dict
) -> tuple[dict, list[str], str]:
    wet_windows = build_rms_windows(wet_mono, wet_info["sampleRate"], 1000.0)
    onset = detect_onset(wet_windows, noise_window_count=1)
    onset_sample = onset["onsetSample"] or 0
    sustain_start = min(len(wet_mono), onset_sample + samples_from_ms(wet_info["sampleRate"], 5000.0))
    sustain_windows = [
        window for window in wet_windows if window["startSample"] >= sustain_start
    ]
    sustain_db = [
        window["rmsDbfs"] for window in sustain_windows if window["rmsDbfs"] is not None
    ]
    first_db = sustain_db[0] if sustain_db else None
    last_db = sustain_db[-1] if sustain_db else None
    drift_db = (last_db - first_db) if first_db is not None and last_db is not None else None
    stability_std = pstdev(sustain_db) if len(sustain_db) > 1 else None

    metrics = {
        "analysisWindowStartMs": ms_from_samples(sustain_start, wet_info["sampleRate"]),
        "sustainWindowCount": len(sustain_db),
        "firstSustainWindowDbfs": first_db,
        "lastSustainWindowDbfs": last_db,
        "sustainDriftDb": drift_db,
        "sustainStdDevDb": stability_std,
        "sustainWindowPreviewDbfs": [
            {
                "startMs": round(window["startMs"], 3),
                "endMs": round(window["endMs"], 3),
                "rmsDbfs": round(window["rmsDbfs"], 3)
                if window["rmsDbfs"] is not None
                else None,
            }
            for window in sustain_windows[:10]
        ],
    }
    caveats = [
        "Freeze/infinite stability is summarized over late 1-second windows after the initial onset and buildup.",
        "These drift and variance values are first-pass sustain proxies rather than final acceptance thresholds.",
    ]
    if drift_db is not None and stability_std is not None:
        descriptor = (
            "appears fairly stable"
            if abs(drift_db) < 3.0 and stability_std < 2.0
            else "shows noticeable drift or movement"
        )
        interpretation = (
            f"Late sustain {descriptor}, with {drift_db:.2f} dB drift and {stability_std:.2f} dB window-to-window deviation."
        )
    else:
        interpretation = "Late sustain stability could not be summarized from the current capture."
    return metrics, caveats, interpretation


def analyze_group(
    group_name: str,
    wet_info: dict,
    dry_info: dict,
    harness_metrics: dict,
) -> tuple[dict, list[str], str]:
    wet_mono = mono_mix(wet_info["channelData"])
    dry_mono = mono_mix(dry_info["channelData"])

    if group_name == "attack":
        return analyze_attack_group(wet_mono, dry_mono, wet_info, dry_info, harness_metrics)
    if group_name == "predelay":
        return analyze_predelay_group(wet_mono, dry_mono, wet_info, dry_info, harness_metrics)
    if group_name == "width":
        return analyze_width_group(wet_info["channelData"], wet_info)
    if group_name == "gravity":
        return analyze_gravity_group(wet_mono, wet_info)
    if group_name == "tail":
        return analyze_tail_group(wet_mono, wet_info)
    if group_name == "tone_eq":
        return analyze_tone_eq_group(wet_mono, wet_info)
    if group_name == "modulation":
        return analyze_modulation_group(wet_mono, wet_info)
    if group_name == "freeze_infinite":
        return analyze_freeze_group(wet_mono, wet_info)
    raise SystemExit(f"error: unsupported analysis group: {group_name}")


def analyze_state(
    measurements_root: Path,
    state_id: str,
    preferred_group: str | None,
    state: dict | None,
    state_analysis_path: Path,
) -> dict:
    if state is None:
        result = {
            "schemaVersion": 1,
            "stateId": state_id,
            "group": preferred_group,
            "status": "unavailable",
            "reason": "Requested state ID was not found in tests/reference_states.",
        }
        write_json(state_analysis_path, result)
        return result

    group_name = preferred_group
    target_groups = state.get("targetGroups")
    if group_name is None:
        if isinstance(target_groups, list) and target_groups and isinstance(target_groups[0], str):
            group_name = target_groups[0]
        else:
            group_name = "unknown"

    result: dict = {
        "schemaVersion": 1,
        "stateId": state_id,
        "group": group_name,
        "stateStatus": state.get("status"),
        "stateFilePath": state.get("stateFilePath"),
        "status": "unavailable",
        "sourceSelectionMethod": None,
        "sourceSelectionIssues": [],
        "resolvedArtifacts": {},
        "caveats": [],
        "interpretation": None,
    }

    if state.get("status") != "captured":
        result["reason"] = (
            f"State {state_id} is not captured; current status is {state.get('status')!r}."
        )
        write_json(state_analysis_path, result)
        return result

    case_record, selection_issues, selection_method = resolve_artifact_source(
        state_id, state, group_name, measurements_root
    )
    result["sourceSelectionMethod"] = selection_method
    result["sourceSelectionIssues"] = selection_issues

    if case_record is None:
        result["reason"] = "No successful capture artifact could be resolved for this state."
        write_json(state_analysis_path, result)
        return result

    reference_capture_path = ensure_path(
        case_record.get("referenceCapturePath"),
        f"reference capture artifact for state {state_id}",
    )
    reference_capture = load_json(reference_capture_path)
    wet_path = ensure_path(
        case_record.get("referenceWetPath")
        or reference_capture.get("expectedArtifacts", {}).get("referenceWetPath"),
        f"reference wet WAV for state {state_id}",
    )
    metrics_path = ensure_path(
        case_record.get("referenceMetricsPath")
        or reference_capture.get("expectedArtifacts", {}).get("referenceMetricsPath"),
        f"reference metrics JSON for state {state_id}",
    )
    harness_metrics = load_json(metrics_path)

    resolved_input = reference_capture.get("resolvedInput")
    if not isinstance(resolved_input, dict):
        raise SystemExit(
            f"error: reference capture artifact is missing resolvedInput for state {state_id}: {reference_capture_path}"
        )
    dry_path = ensure_path(
        resolved_input.get("resolvedPath"),
        f"resolved input WAV for state {state_id}",
    )

    wet_info = read_wave_file(wet_path)
    dry_info = read_wave_file(dry_path)
    metrics, caveats, interpretation = analyze_group(
        group_name, wet_info, dry_info, harness_metrics
    )

    result.update(
        {
            "status": "analyzed",
            "caseId": reference_capture.get("caseId"),
            "sourceSelection": {
                "method": selection_method,
                "selectionIssues": selection_issues,
                "referenceCapturePath": str(reference_capture_path.as_posix()),
                "referenceWetPath": str(wet_path.as_posix()),
                "referenceMetricsPath": str(metrics_path.as_posix()),
                "dryInputPath": str(dry_path.as_posix()),
                "selectionReason": (
                    "Selected the first successful captured case recorded in the reusable state metadata."
                    if selection_method == "state_capture_metadata"
                    else "Fell back to the latest successful reference_capture.json artifact discovered under artifacts/measurements."
                ),
            },
            "resolvedArtifacts": normalize_artifact_paths(reference_capture, case_record),
            "referenceCapture": {
                "executionStatus": reference_capture.get("executionStatus"),
                "executionMode": reference_capture.get("executionMode"),
                "referenceStateId": reference_capture.get("referenceStateId"),
            },
            "resolvedInput": resolved_input,
            "harnessMetrics": harness_metrics,
            "wetWave": {key: value for key, value in wet_info.items() if key != "channelData"},
            "dryWave": {key: value for key, value in dry_info.items() if key != "channelData"},
            "keyMetrics": metrics,
            "caveats": caveats,
            "interpretation": interpretation,
        }
    )

    write_json(state_analysis_path, result)
    return result


def build_group_summary(
    group_name: str, summary_path: Path, state_results: list[dict]
) -> dict:
    analyzed = [result for result in state_results if result["status"] == "analyzed"]
    unavailable = [result for result in state_results if result["status"] != "analyzed"]
    return {
        "schemaVersion": 1,
        "group": group_name,
        "status": "analyzed" if unavailable == [] and analyzed else "partial_or_unavailable",
        "analysisKind": "initial_reference_capture_summary",
        "summaryPath": str(summary_path.as_posix()),
        "analyzedStateIds": [result["stateId"] for result in analyzed],
        "unavailableStateIds": [result["stateId"] for result in unavailable],
        "sourceArtifactPaths": [
            {
                "stateId": result["stateId"],
                "referenceCapturePath": result["sourceSelection"]["referenceCapturePath"],
                "referenceWetPath": result["sourceSelection"]["referenceWetPath"],
                "referenceMetricsPath": result["sourceSelection"]["referenceMetricsPath"],
                "dryInputPath": result["sourceSelection"]["dryInputPath"],
            }
            for result in analyzed
        ],
        "states": state_results,
        "notes": [
            "These are first-pass descriptive summaries of existing Blackhole reference captures.",
            "Proxy metrics in this file are intended to guide later matching work, not to replace final parameter-law extraction or acceptance thresholds.",
        ],
    }


def main() -> int:
    args = parse_args()
    repo_root = Path(__file__).resolve().parent.parent
    measurements_root = (repo_root / args.measurements_root).resolve()
    state_manifest_path = (repo_root / args.reference_state_manifest).resolve()

    states_by_id, declared_state_ids = load_reference_states(repo_root, state_manifest_path)
    selected_targets = select_state_ids(args, states_by_id)

    timestamp = timestamp_slug()
    artifacts_root = (repo_root / args.artifacts_root).resolve()
    run_dir = artifacts_root / timestamp
    run_dir.mkdir(parents=True, exist_ok=True)
    states_dir = run_dir / "states"
    states_dir.mkdir(parents=True, exist_ok=True)

    group_results: dict[str, list[dict]] = {}
    analyzed_state_ids: list[str] = []
    unavailable_state_ids: list[str] = []

    for preferred_group, state_id in selected_targets:
        state = states_by_id.get(state_id)
        group_name = preferred_group
        if group_name is None and state is not None:
            target_groups = state.get("targetGroups")
            if isinstance(target_groups, list) and target_groups and isinstance(target_groups[0], str):
                group_name = target_groups[0]
        if group_name is None:
            group_name = "unknown"

        state_analysis_path = states_dir / f"{state_id}.json"
        result = analyze_state(
            measurements_root,
            state_id,
            group_name,
            state,
            state_analysis_path,
        )
        result["stateAnalysisPath"] = str(state_analysis_path.as_posix())
        if result["status"] == "analyzed":
            analyzed_state_ids.append(state_id)
        else:
            unavailable_state_ids.append(state_id)
            write_json(state_analysis_path, result)
        group_results.setdefault(group_name, []).append(result)

    group_summary_paths: dict[str, dict] = {}
    for group_name, results in group_results.items():
        summary_path = run_dir / group_summary_filename(group_name)
        summary = build_group_summary(group_name, summary_path, results)
        write_json(summary_path, summary)
        group_summary_paths[group_name] = {
            "path": str(summary_path.as_posix()),
            "status": summary["status"],
            "analyzedStateIds": summary["analyzedStateIds"],
            "unavailableStateIds": summary["unavailableStateIds"],
        }

    summary = {
        "schemaVersion": 1,
        "analysisKind": "initial_reference_capture_summary",
        "timestamp": timestamp,
        "generatedAt": iso_now(),
        "summaryPath": str((run_dir / "summary.json").as_posix()),
        "artifactsRoot": str(artifacts_root.as_posix()),
        "runDirectory": str(run_dir.as_posix()),
        "measurementsRoot": str(measurements_root.as_posix()),
        "referenceStateManifestPath": str(state_manifest_path.as_posix()),
        "requestedGroups": parse_csv(args.groups),
        "requestedStateIds": parse_csv(args.state_ids),
        "selectedTargets": [
            {"group": group_name, "stateId": state_id}
            for group_name, state_id in selected_targets
        ],
        "declaredReferenceStateIds": declared_state_ids,
        "foundReferenceStateIds": sorted(states_by_id),
        "successfullyAnalyzedStateIds": analyzed_state_ids,
        "unavailableOrFailedStateIds": unavailable_state_ids,
        "groupSummaries": group_summary_paths,
        "notes": [
            "This is an initial reference-analysis pass over existing Blackhole capture artifacts.",
            "The summaries emphasize reviewable onset, envelope, stereo, spectral, movement, and sustain proxies rather than final control-law extraction.",
            "Missing or broken captured-state links are reported as unavailable instead of being filled in with invented analysis.",
        ],
    }

    summary_path = run_dir / "summary.json"
    write_json(summary_path, summary)

    print(f"Created reference-analysis run: {run_dir}")
    print(f"Wrote summary: {summary_path}")
    print(
        "Successfully analyzed states: "
        + (", ".join(analyzed_state_ids) if analyzed_state_ids else "(none)")
    )
    print(
        "Unavailable or failed states: "
        + (", ".join(unavailable_state_ids) if unavailable_state_ids else "(none)")
    )
    return 0 if not unavailable_state_ids else 1


if __name__ == "__main__":
    sys.exit(main())
