#!/usr/bin/env python3
"""Run repeatable smoke verification for the current OutSpread shell."""

from __future__ import annotations

import argparse
import hashlib
import json
import math
import struct
import subprocess
import sys
import wave
from datetime import datetime
from pathlib import Path

DIFFUSION_TAP_MS = (0.0, 0.67, 1.41, 2.89)
DIFFUSION_TAP_GAINS = (0.75, 0.18, -0.10, 0.07)
LOCAL_RECIRCULATION_DELAY_MS = 4.5
LOCAL_RECIRCULATION_GAIN = 0.25
SECONDARY_DIFFUSION_TAP_MS = (0.0, 0.91, 1.87, 3.73)
SECONDARY_DIFFUSION_TAP_GAINS = (0.58, -0.16, 0.09, 0.05)
SECONDARY_LOCAL_RECIRCULATION_DELAY_MS = (5.3, 6.1)
SECONDARY_LOCAL_RECIRCULATION_GAIN = 0.18
SECONDARY_BRANCH_MIX = 0.35


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


def decode_pcm_wave(path: Path) -> tuple[int, list[list[float]]]:
    with wave.open(str(path), "rb") as wav_file:
        channels = wav_file.getnchannels()
        sample_width = wav_file.getsampwidth()
        sample_rate = wav_file.getframerate()
        num_frames = wav_file.getnframes()

        frame_bytes = wav_file.readframes(num_frames)

    samples = [[0.0 for _ in range(num_frames)] for _ in range(channels)]
    for frame_index in range(num_frames):
        frame_offset = frame_index * channels * sample_width
        for channel in range(channels):
            sample_offset = frame_offset + (channel * sample_width)

            if sample_width == 2:
                sample_int = struct.unpack_from("<h", frame_bytes, sample_offset)[0]
                samples[channel][frame_index] = sample_int / 32768.0
            elif sample_width == 3:
                raw = frame_bytes[sample_offset : sample_offset + sample_width]
                sample_int = int.from_bytes(raw, byteorder="little", signed=False)
                if sample_int & 0x800000:
                    sample_int -= 0x1000000
                samples[channel][frame_index] = sample_int / 8388608.0
            elif sample_width == 4:
                sample_int = struct.unpack_from("<i", frame_bytes, sample_offset)[0]
                samples[channel][frame_index] = sample_int / 2147483648.0
            else:
                raise SystemExit(
                    f"error: unsupported PCM sample width {sample_width * 8}-bit at {path}"
                )

    return sample_rate, samples


def find_first_frame_above_threshold(
    samples: list[list[float]], threshold: float = 1.0 / 32768.0
) -> int | None:
    if not samples:
        return None

    frame_count = len(samples[0])
    for frame_index in range(frame_count):
        for channel_samples in samples:
            if abs(channel_samples[frame_index]) >= threshold:
                return frame_index
    return None


def find_last_frame_above_threshold(
    samples: list[list[float]], threshold: float = 1.0 / 32768.0
) -> int | None:
    if not samples:
        return None

    for frame_index in range(len(samples[0]) - 1, -1, -1):
        for channel_samples in samples:
            if abs(channel_samples[frame_index]) >= threshold:
                return frame_index
    return None


def linear_peak(samples: list[float]) -> float:
    return max((abs(sample) for sample in samples), default=0.0)


def linear_rms(samples: list[float]) -> float:
    if not samples:
        return 0.0
    return (sum(sample * sample for sample in samples) / len(samples)) ** 0.5


def dbfs_from_linear(value: float) -> float:
    if value <= 1.0e-12:
        return -160.0
    return 20.0 * math.log10(value)


def compute_stereo_metrics(samples: list[list[float]]) -> dict:
    if len(samples) < 2:
        return {}

    left = samples[0]
    right = samples[1]
    sum_lr = sum(left_sample * right_sample for left_sample, right_sample in zip(left, right))
    sum_ll = sum(sample * sample for sample in left)
    sum_rr = sum(sample * sample for sample in right)
    denominator = math.sqrt(sum_ll * sum_rr)
    correlation = 0.0 if denominator <= 1.0e-12 else sum_lr / denominator

    mid = [(left_sample + right_sample) * 0.5 for left_sample, right_sample in zip(left, right)]
    side = [(left_sample - right_sample) * 0.5 for left_sample, right_sample in zip(left, right)]

    return {
        "leftRightCorrelation": correlation,
        "midPeakDbfs": dbfs_from_linear(linear_peak(mid)),
        "midRmsDbfs": dbfs_from_linear(linear_rms(mid)),
        "sidePeakDbfs": dbfs_from_linear(linear_peak(side)),
        "sideRmsDbfs": dbfs_from_linear(linear_rms(side)),
    }


def compute_window_rms_dbfs(
    samples: list[list[float]],
    start_frame: int,
    length: int,
) -> float | None:
    if not samples or length <= 0:
        return None

    frame_count = len(samples[0])
    if start_frame < 0 or start_frame >= frame_count:
        return None

    end_frame = min(frame_count, start_frame + length)
    if end_frame <= start_frame:
        return None

    window_values: list[float] = []
    for channel_samples in samples:
        window_values.extend(channel_samples[start_frame:end_frame])

    return dbfs_from_linear(linear_rms(window_values))


def compute_energy_centroid_offset(
    samples: list[list[float]],
    onset_frame: int,
    length: int,
) -> float | None:
    if not samples or length <= 0:
        return None

    frame_count = len(samples[0])
    if onset_frame < 0 or onset_frame >= frame_count:
        return None

    end_frame = min(frame_count, onset_frame + length)
    if end_frame <= onset_frame:
        return None

    weighted_sum = 0.0
    energy_sum = 0.0
    for frame_index in range(onset_frame, end_frame):
        frame_energy = 0.0
        for channel_samples in samples:
            sample = channel_samples[frame_index]
            frame_energy += sample * sample

        offset = frame_index - onset_frame
        weighted_sum += frame_energy * offset
        energy_sum += frame_energy

    if energy_sum <= 1.0e-18:
        return None

    return weighted_sum / energy_sum


def write_pcm16_wave(path: Path, sample_rate: int, samples: list[list[float]]) -> None:
    if not samples:
        raise SystemExit("error: cannot write an empty WAV buffer")

    channel_count = len(samples)
    frame_count = len(samples[0])
    for channel_samples in samples:
        if len(channel_samples) != frame_count:
            raise SystemExit("error: WAV channel lengths do not match")

    path.parent.mkdir(parents=True, exist_ok=True)
    with wave.open(str(path), "wb") as wav_file:
        wav_file.setnchannels(channel_count)
        wav_file.setsampwidth(2)
        wav_file.setframerate(sample_rate)

        frames = bytearray()
        for frame_index in range(frame_count):
            for channel in range(channel_count):
                clamped = max(-1.0, min(1.0, samples[channel][frame_index]))
                frames.extend(struct.pack("<h", int(round(clamped * 32767.0))))
        wav_file.writeframes(frames)


def build_pure_predelay_reference(
    input_path: Path,
    output_path: Path,
    output_channels: int,
    delay_samples: int,
) -> Path:
    sample_rate, input_samples = decode_pcm_wave(input_path)
    input_channels = len(input_samples)
    frame_count = len(input_samples[0]) if input_samples else 0

    reference_samples = [[0.0 for _ in range(frame_count)] for _ in range(output_channels)]
    for channel in range(output_channels):
        source_channel = min(channel, input_channels - 1)
        source = input_samples[source_channel]
        target = reference_samples[channel]

        for frame_index in range(delay_samples, frame_count):
            target[frame_index] = source[frame_index - delay_samples]

    write_pcm16_wave(output_path, sample_rate, reference_samples)
    return output_path


def build_predelay_diffusion_reference(
    input_path: Path,
    output_path: Path,
    output_channels: int,
    delay_samples: int,
) -> Path:
    sample_rate, input_samples = decode_pcm_wave(input_path)
    input_channels = len(input_samples)
    frame_count = len(input_samples[0]) if input_samples else 0
    diffusion_tap_samples = [
        int(round((sample_rate * tap_ms) / 1000.0)) for tap_ms in DIFFUSION_TAP_MS
    ]

    reference_samples = [[0.0 for _ in range(frame_count)] for _ in range(output_channels)]
    for channel in range(output_channels):
        source_channel = min(channel, input_channels - 1)
        source = input_samples[source_channel]
        target = reference_samples[channel]

        for frame_index in range(frame_count):
            predelayed_index = frame_index - delay_samples
            if predelayed_index < 0:
                continue

            sample_value = 0.0
            for tap_samples, tap_gain in zip(diffusion_tap_samples, DIFFUSION_TAP_GAINS):
                tap_index = predelayed_index - tap_samples
                if tap_index >= 0:
                    sample_value += source[tap_index] * tap_gain
            target[frame_index] = sample_value

    write_pcm16_wave(output_path, sample_rate, reference_samples)
    return output_path


def build_single_branch_reference(
    input_path: Path,
    output_path: Path,
    output_channels: int,
    delay_samples: int,
) -> Path:
    sample_rate, input_samples = decode_pcm_wave(input_path)
    input_channels = len(input_samples)
    frame_count = len(input_samples[0]) if input_samples else 0
    diffusion_tap_samples = [
        int(round((sample_rate * tap_ms) / 1000.0)) for tap_ms in DIFFUSION_TAP_MS
    ]
    local_recirculation_delay_samples = int(round((sample_rate * LOCAL_RECIRCULATION_DELAY_MS) / 1000.0))

    reference_samples = [[0.0 for _ in range(frame_count)] for _ in range(output_channels)]
    for channel in range(output_channels):
        source_channel = min(channel, input_channels - 1)
        source = input_samples[source_channel]
        target = reference_samples[channel]

        for frame_index in range(frame_count):
            predelayed_index = frame_index - delay_samples
            if predelayed_index < 0:
                continue

            diffused_sample = 0.0
            for tap_samples, tap_gain in zip(diffusion_tap_samples, DIFFUSION_TAP_GAINS):
                tap_index = predelayed_index - tap_samples
                if tap_index >= 0:
                    diffused_sample += source[tap_index] * tap_gain

            wet_sample = diffused_sample
            recirculation_index = frame_index - local_recirculation_delay_samples
            if recirculation_index >= 0:
                wet_sample += target[recirculation_index] * LOCAL_RECIRCULATION_GAIN

            target[frame_index] = wet_sample

    write_pcm16_wave(output_path, sample_rate, reference_samples)
    return output_path


def build_uncoupled_two_branch_reference(
    input_path: Path,
    output_path: Path,
    output_channels: int,
    delay_samples: int,
) -> Path:
    sample_rate, input_samples = decode_pcm_wave(input_path)
    input_channels = len(input_samples)
    frame_count = len(input_samples[0]) if input_samples else 0
    primary_diffusion_tap_samples = [
        int(round((sample_rate * tap_ms) / 1000.0)) for tap_ms in DIFFUSION_TAP_MS
    ]
    secondary_diffusion_tap_samples = [
        int(round((sample_rate * tap_ms) / 1000.0)) for tap_ms in SECONDARY_DIFFUSION_TAP_MS
    ]
    primary_local_recirculation_delay_samples = int(
        round((sample_rate * LOCAL_RECIRCULATION_DELAY_MS) / 1000.0)
    )
    secondary_local_recirculation_delay_samples = [
        int(round((sample_rate * tap_ms) / 1000.0))
        for tap_ms in SECONDARY_LOCAL_RECIRCULATION_DELAY_MS
    ]

    reference_samples = [[0.0 for _ in range(frame_count)] for _ in range(output_channels)]
    primary_branch_samples = [[0.0 for _ in range(frame_count)] for _ in range(output_channels)]
    secondary_branch_samples = [[0.0 for _ in range(frame_count)] for _ in range(output_channels)]

    for channel in range(output_channels):
        source_channel = min(channel, input_channels - 1)
        source = input_samples[source_channel]
        output_target = reference_samples[channel]
        primary_target = primary_branch_samples[channel]
        secondary_target = secondary_branch_samples[channel]
        secondary_delay = secondary_local_recirculation_delay_samples[
            min(channel, len(secondary_local_recirculation_delay_samples) - 1)
        ]

        for frame_index in range(frame_count):
            predelayed_index = frame_index - delay_samples
            if predelayed_index < 0:
                continue

            primary_diffused_sample = 0.0
            for tap_samples, tap_gain in zip(primary_diffusion_tap_samples, DIFFUSION_TAP_GAINS):
                tap_index = predelayed_index - tap_samples
                if tap_index >= 0:
                    primary_diffused_sample += source[tap_index] * tap_gain

            primary_wet_sample = primary_diffused_sample
            primary_recirculation_index = frame_index - primary_local_recirculation_delay_samples
            if primary_recirculation_index >= 0:
                primary_wet_sample += primary_target[primary_recirculation_index] * LOCAL_RECIRCULATION_GAIN
            primary_target[frame_index] = primary_wet_sample

            secondary_diffused_sample = 0.0
            for tap_samples, tap_gain in zip(secondary_diffusion_tap_samples, SECONDARY_DIFFUSION_TAP_GAINS):
                tap_index = predelayed_index - tap_samples
                if tap_index >= 0:
                    secondary_diffused_sample += source[tap_index] * tap_gain

            secondary_wet_sample = secondary_diffused_sample
            secondary_recirculation_index = frame_index - secondary_delay
            if secondary_recirculation_index >= 0:
                secondary_wet_sample += secondary_target[secondary_recirculation_index] * SECONDARY_LOCAL_RECIRCULATION_GAIN
            secondary_target[frame_index] = secondary_wet_sample

            output_target[frame_index] = primary_wet_sample + (secondary_wet_sample * SECONDARY_BRANCH_MIX)

    write_pcm16_wave(output_path, sample_rate, reference_samples)
    return output_path


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


def evaluate_case(
    case_data: dict,
    metrics: dict,
    case_dir: Path,
    completed_cases: dict[str, dict],
    extra_analysis: dict | None,
) -> dict:
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
    elif expectation == "predelay_latency":
        expected_latency = shell_verification.get("expectedLatencySamples")
        tolerance = shell_verification.get("latencyToleranceSamples", 8)
        measured_onset = None if not isinstance(extra_analysis, dict) else extra_analysis.get("wetOnsetSamples")

        if not isinstance(expected_latency, int):
            issues.append("predelay latency expectation is missing expectedLatencySamples")
        elif not isinstance(measured_onset, int):
            issues.append("predelay latency verification is missing wetOnsetSamples")
        else:
            if abs(measured_onset - expected_latency) > tolerance:
                issues.append(
                    f"measured wet onset {measured_onset} samples did not match expected {expected_latency} +/- {tolerance}"
                )
        if metrics.get("wetPeakDbfs", -160.0) <= -40.0:
            issues.append("predelay wet output was unexpectedly close to silence")
    elif expectation == "predelay_diffusion":
        expected_latency = shell_verification.get("expectedLatencySamples")
        tolerance = shell_verification.get("latencyToleranceSamples", 8)
        minimum_delta_peak = shell_verification.get("minimumPurePredelayDeltaPeakDbfs", -80.0)
        measured_onset = None if not isinstance(extra_analysis, dict) else extra_analysis.get("wetOnsetSamples")

        if not isinstance(expected_latency, int):
            issues.append("predelay diffusion expectation is missing expectedLatencySamples")
        elif not isinstance(measured_onset, int):
            issues.append("predelay diffusion verification is missing wetOnsetSamples")
        else:
            if abs(measured_onset - expected_latency) > tolerance:
                issues.append(
                    f"measured wet onset {measured_onset} samples did not match expected {expected_latency} +/- {tolerance}"
                )

        if metrics.get("wetPeakDbfs", -160.0) <= -40.0:
            issues.append("predelay diffusion wet output was unexpectedly close to silence")

        if not isinstance(extra_analysis, dict):
            issues.append("predelay diffusion comparison did not run")
        else:
            comparison_metrics = extra_analysis.get("comparisonMetrics", {})
            delta_peak = comparison_metrics.get("deltaPeakDbfs")
            if not isinstance(delta_peak, (int, float)):
                issues.append("pure predelay comparison metrics are missing deltaPeakDbfs")
            elif delta_peak <= minimum_delta_peak:
                issues.append(
                    f"diffused wet path stayed too close to a pure predelay copy (deltaPeakDbfs={delta_peak})"
                )
    elif expectation == "predelay_recirculation":
        expected_latency = shell_verification.get("expectedLatencySamples")
        tolerance = shell_verification.get("latencyToleranceSamples", 8)
        minimum_delta_peak = shell_verification.get("minimumDiffusionOnlyDeltaPeakDbfs", -80.0)
        minimum_extra_persistence = shell_verification.get("minimumExtraPersistenceSamples", 128)
        maximum_persistence = shell_verification.get("maximumPersistenceSamples", 2048)
        measured_onset = None if not isinstance(extra_analysis, dict) else extra_analysis.get("wetOnsetSamples")
        measured_last = None if not isinstance(extra_analysis, dict) else extra_analysis.get("wetLastAboveThresholdSamples")

        if not isinstance(expected_latency, int):
            issues.append("predelay recirculation expectation is missing expectedLatencySamples")
        elif not isinstance(measured_onset, int):
            issues.append("predelay recirculation verification is missing wetOnsetSamples")
        elif abs(measured_onset - expected_latency) > tolerance:
            issues.append(
                f"measured wet onset {measured_onset} samples did not match expected {expected_latency} +/- {tolerance}"
            )

        if not isinstance(measured_last, int) or not isinstance(measured_onset, int) or measured_last <= measured_onset:
            issues.append("predelay recirculation wet output did not show a usable post-onset persistence window")

        if not isinstance(extra_analysis, dict):
            issues.append("predelay recirculation comparison did not run")
        else:
            comparison_metrics = extra_analysis.get("comparisonMetrics", {})
            delta_peak = comparison_metrics.get("deltaPeakDbfs")
            if not isinstance(delta_peak, (int, float)):
                issues.append("diffusion-only comparison metrics are missing deltaPeakDbfs")
            elif delta_peak <= minimum_delta_peak:
                issues.append(
                    f"recirculating wet path stayed too close to the diffusion-only reference (deltaPeakDbfs={delta_peak})"
                )

            extra_persistence = extra_analysis.get("extraPersistenceSamples")
            if not isinstance(extra_persistence, int):
                issues.append("predelay recirculation verification is missing extraPersistenceSamples")
            elif extra_persistence < minimum_extra_persistence:
                issues.append(
                    f"recirculating wet path only extended persistence by {extra_persistence} samples"
                )

            persistence_samples = extra_analysis.get("wetPersistenceSamples")
            if not isinstance(persistence_samples, int):
                issues.append("predelay recirculation verification is missing wetPersistenceSamples")
            elif persistence_samples > maximum_persistence:
                issues.append(
                    f"recirculating wet path persisted for {persistence_samples} samples, which is longer than expected for this shell stage"
                )
    elif expectation == "predelay_coupled_dual_branch":
        expected_latency = shell_verification.get("expectedLatencySamples")
        tolerance = shell_verification.get("latencyToleranceSamples", 8)
        minimum_delta_peak = shell_verification.get("minimumUncoupledDeltaPeakDbfs", -80.0)
        minimum_extra_persistence = shell_verification.get("minimumExtraPersistenceSamples")
        maximum_persistence = shell_verification.get("maximumPersistenceSamples", 2600)
        maximum_correlation = shell_verification.get("maximumLeftRightCorrelation", 0.9999)
        minimum_side_rms_dbfs = shell_verification.get("minimumSideRmsDbfs", -110.0)
        measured_onset = None if not isinstance(extra_analysis, dict) else extra_analysis.get("wetOnsetSamples")
        measured_last = None if not isinstance(extra_analysis, dict) else extra_analysis.get("wetLastAboveThresholdSamples")

        if not isinstance(expected_latency, int):
            issues.append("predelay coupled dual-branch expectation is missing expectedLatencySamples")
        elif not isinstance(measured_onset, int):
            issues.append("predelay coupled dual-branch verification is missing wetOnsetSamples")
        elif abs(measured_onset - expected_latency) > tolerance:
            issues.append(
                f"measured wet onset {measured_onset} samples did not match expected {expected_latency} +/- {tolerance}"
            )

        if not isinstance(measured_last, int) or not isinstance(measured_onset, int) or measured_last <= measured_onset:
            issues.append("predelay coupled dual-branch wet output did not show a usable post-onset persistence window")

        if not isinstance(extra_analysis, dict):
            issues.append("predelay coupled dual-branch comparison did not run")
        else:
            comparison_metrics = extra_analysis.get("comparisonMetrics", {})
            delta_peak = comparison_metrics.get("deltaPeakDbfs")
            if not isinstance(delta_peak, (int, float)):
                issues.append("uncoupled dual-branch comparison metrics are missing deltaPeakDbfs")
            elif delta_peak <= minimum_delta_peak:
                issues.append(
                    f"coupled wet path stayed too close to the uncoupled dual-branch reference (deltaPeakDbfs={delta_peak})"
                )

            extra_persistence = extra_analysis.get("extraPersistenceSamples")
            if minimum_extra_persistence is not None:
                if not isinstance(extra_persistence, int):
                    issues.append("predelay coupled dual-branch verification is missing extraPersistenceSamples")
                elif extra_persistence < minimum_extra_persistence:
                    issues.append(
                        f"coupled wet path only extended persistence by {extra_persistence} samples"
                    )

            persistence_samples = extra_analysis.get("wetPersistenceSamples")
            if not isinstance(persistence_samples, int):
                issues.append("predelay coupled dual-branch verification is missing wetPersistenceSamples")
            elif persistence_samples > maximum_persistence:
                issues.append(
                    f"coupled wet path persisted for {persistence_samples} samples, which is longer than expected for this shell stage"
                )

            stereo_metrics = extra_analysis.get("stereoMetrics", {})
            left_right_correlation = stereo_metrics.get("leftRightCorrelation")
            if not isinstance(left_right_correlation, (int, float)):
                issues.append("predelay coupled dual-branch verification is missing leftRightCorrelation")
            elif left_right_correlation > maximum_correlation:
                issues.append(
                    f"coupled wet path stayed too correlated between left and right ({left_right_correlation})"
                )

            side_rms_dbfs = stereo_metrics.get("sideRmsDbfs")
            if not isinstance(side_rms_dbfs, (int, float)):
                issues.append("predelay coupled dual-branch verification is missing sideRmsDbfs")
            elif side_rms_dbfs < minimum_side_rms_dbfs:
                issues.append(
                    f"coupled wet path side RMS {side_rms_dbfs} dBFS was lower than expected"
                )
    elif expectation == "predelay_feedback_decay_low":
        expected_latency = shell_verification.get("expectedLatencySamples")
        tolerance = shell_verification.get("latencyToleranceSamples", 8)
        maximum_persistence = shell_verification.get("maximumPersistenceSamples", 2400)
        measured_onset = None if not isinstance(extra_analysis, dict) else extra_analysis.get("wetOnsetSamples")
        measured_last = None if not isinstance(extra_analysis, dict) else extra_analysis.get("wetLastAboveThresholdSamples")

        if not isinstance(expected_latency, int):
            issues.append("predelay feedback low expectation is missing expectedLatencySamples")
        elif not isinstance(measured_onset, int):
            issues.append("predelay feedback low verification is missing wetOnsetSamples")
        elif abs(measured_onset - expected_latency) > tolerance:
            issues.append(
                f"measured wet onset {measured_onset} samples did not match expected {expected_latency} +/- {tolerance}"
            )

        if not isinstance(measured_last, int) or not isinstance(measured_onset, int) or measured_last <= measured_onset:
            issues.append("predelay feedback low wet output did not show a usable post-onset persistence window")

        if not isinstance(extra_analysis, dict):
            issues.append("predelay feedback low verification did not run")
        else:
            persistence_samples = extra_analysis.get("wetPersistenceSamples")
            if not isinstance(persistence_samples, int):
                issues.append("predelay feedback low verification is missing wetPersistenceSamples")
            elif persistence_samples > maximum_persistence:
                issues.append(
                    f"low-feedback wet path persisted for {persistence_samples} samples, which is longer than expected for this shell stage"
                )
    elif expectation == "predelay_feedback_decay_high":
        expected_latency = shell_verification.get("expectedLatencySamples")
        tolerance = shell_verification.get("latencyToleranceSamples", 8)
        compare_to_case_id = shell_verification.get("compareToCaseId")
        minimum_delta_peak = shell_verification.get("minimumLowFeedbackDeltaPeakDbfs", -24.0)
        minimum_extra_persistence = shell_verification.get("minimumExtraPersistenceSamples", 128)
        minimum_late_window_rms_delta_db = shell_verification.get("minimumLateWindowRmsDeltaDb", 1.5)
        maximum_persistence = shell_verification.get("maximumPersistenceSamples", 3200)
        measured_onset = None if not isinstance(extra_analysis, dict) else extra_analysis.get("wetOnsetSamples")
        measured_last = None if not isinstance(extra_analysis, dict) else extra_analysis.get("wetLastAboveThresholdSamples")

        if not isinstance(expected_latency, int):
            issues.append("predelay feedback high expectation is missing expectedLatencySamples")
        elif not isinstance(measured_onset, int):
            issues.append("predelay feedback high verification is missing wetOnsetSamples")
        elif abs(measured_onset - expected_latency) > tolerance:
            issues.append(
                f"measured wet onset {measured_onset} samples did not match expected {expected_latency} +/- {tolerance}"
            )

        if not isinstance(measured_last, int) or not isinstance(measured_onset, int) or measured_last <= measured_onset:
            issues.append("predelay feedback high wet output did not show a usable post-onset persistence window")

        if compare_to_case_id not in completed_cases:
            issues.append(f"comparison case '{compare_to_case_id}' is not available")
        elif not isinstance(extra_analysis, dict):
            issues.append("predelay feedback high comparison did not run")
        else:
            comparison_metrics = extra_analysis.get("comparisonMetrics", {})
            delta_peak = comparison_metrics.get("deltaPeakDbfs")
            if not isinstance(delta_peak, (int, float)):
                issues.append("low-feedback comparison metrics are missing deltaPeakDbfs")
            elif delta_peak <= minimum_delta_peak:
                issues.append(
                    f"high-feedback wet path stayed too close to the low-feedback reference (deltaPeakDbfs={delta_peak})"
                )

            extra_persistence = extra_analysis.get("extraPersistenceSamples")
            if not isinstance(extra_persistence, int):
                issues.append("predelay feedback high verification is missing extraPersistenceSamples")
            elif extra_persistence < minimum_extra_persistence:
                issues.append(
                    f"high-feedback wet path only extended persistence by {extra_persistence} samples"
                )

            persistence_samples = extra_analysis.get("wetPersistenceSamples")
            if not isinstance(persistence_samples, int):
                issues.append("predelay feedback high verification is missing wetPersistenceSamples")
            elif persistence_samples > maximum_persistence:
                issues.append(
                    f"high-feedback wet path persisted for {persistence_samples} samples, which is longer than expected for this shell stage"
                )

            late_window_rms_delta_db = extra_analysis.get("lateWindowRmsDeltaDb")
            if not isinstance(late_window_rms_delta_db, (int, float)):
                issues.append("predelay feedback high verification is missing lateWindowRmsDeltaDb")
            elif late_window_rms_delta_db < minimum_late_window_rms_delta_db:
                issues.append(
                    f"high-feedback late-window RMS only increased by {late_window_rms_delta_db} dB"
                )
    elif expectation == "predelay_size_small":
        expected_latency = shell_verification.get("expectedLatencySamples")
        tolerance = shell_verification.get("latencyToleranceSamples", 8)
        maximum_persistence = shell_verification.get("maximumPersistenceSamples", 2200)
        measured_onset = None if not isinstance(extra_analysis, dict) else extra_analysis.get("wetOnsetSamples")
        measured_last = None if not isinstance(extra_analysis, dict) else extra_analysis.get("wetLastAboveThresholdSamples")

        if not isinstance(expected_latency, int):
            issues.append("predelay size small expectation is missing expectedLatencySamples")
        elif not isinstance(measured_onset, int):
            issues.append("predelay size small verification is missing wetOnsetSamples")
        elif abs(measured_onset - expected_latency) > tolerance:
            issues.append(
                f"measured wet onset {measured_onset} samples did not match expected {expected_latency} +/- {tolerance}"
            )

        if not isinstance(measured_last, int) or not isinstance(measured_onset, int) or measured_last <= measured_onset:
            issues.append("predelay size small wet output did not show a usable post-onset persistence window")

        if not isinstance(extra_analysis, dict):
            issues.append("predelay size small verification did not run")
        else:
            persistence_samples = extra_analysis.get("wetPersistenceSamples")
            if not isinstance(persistence_samples, int):
                issues.append("predelay size small verification is missing wetPersistenceSamples")
            elif persistence_samples > maximum_persistence:
                issues.append(
                    f"small-size wet path persisted for {persistence_samples} samples, which is longer than expected for this shell stage"
                )

            centroid_offset = extra_analysis.get("postOnsetCentroidOffsetSamples")
            if not isinstance(centroid_offset, (int, float)):
                issues.append("predelay size small verification is missing postOnsetCentroidOffsetSamples")
    elif expectation == "predelay_size_large":
        expected_latency = shell_verification.get("expectedLatencySamples")
        tolerance = shell_verification.get("latencyToleranceSamples", 8)
        compare_to_case_id = shell_verification.get("compareToCaseId")
        minimum_delta_peak = shell_verification.get("minimumSmallSizeDeltaPeakDbfs", -12.0)
        minimum_extra_persistence = shell_verification.get("minimumExtraPersistenceSamples", 64)
        minimum_centroid_delta = shell_verification.get("minimumCentroidDeltaSamples", 80.0)
        maximum_persistence = shell_verification.get("maximumPersistenceSamples", 3000)
        measured_onset = None if not isinstance(extra_analysis, dict) else extra_analysis.get("wetOnsetSamples")
        measured_last = None if not isinstance(extra_analysis, dict) else extra_analysis.get("wetLastAboveThresholdSamples")

        if not isinstance(expected_latency, int):
            issues.append("predelay size large expectation is missing expectedLatencySamples")
        elif not isinstance(measured_onset, int):
            issues.append("predelay size large verification is missing wetOnsetSamples")
        elif abs(measured_onset - expected_latency) > tolerance:
            issues.append(
                f"measured wet onset {measured_onset} samples did not match expected {expected_latency} +/- {tolerance}"
            )

        if not isinstance(measured_last, int) or not isinstance(measured_onset, int) or measured_last <= measured_onset:
            issues.append("predelay size large wet output did not show a usable post-onset persistence window")

        if compare_to_case_id not in completed_cases:
            issues.append(f"comparison case '{compare_to_case_id}' is not available")
        elif not isinstance(extra_analysis, dict):
            issues.append("predelay size large comparison did not run")
        else:
            comparison_metrics = extra_analysis.get("comparisonMetrics", {})
            delta_peak = comparison_metrics.get("deltaPeakDbfs")
            if not isinstance(delta_peak, (int, float)):
                issues.append("small-size comparison metrics are missing deltaPeakDbfs")
            elif delta_peak <= minimum_delta_peak:
                issues.append(
                    f"large-size wet path stayed too close to the small-size reference (deltaPeakDbfs={delta_peak})"
                )

            extra_persistence = extra_analysis.get("extraPersistenceSamples")
            if not isinstance(extra_persistence, int):
                issues.append("predelay size large verification is missing extraPersistenceSamples")
            elif extra_persistence < minimum_extra_persistence:
                issues.append(
                    f"large-size wet path only extended persistence by {extra_persistence} samples"
                )

            persistence_samples = extra_analysis.get("wetPersistenceSamples")
            if not isinstance(persistence_samples, int):
                issues.append("predelay size large verification is missing wetPersistenceSamples")
            elif persistence_samples > maximum_persistence:
                issues.append(
                    f"large-size wet path persisted for {persistence_samples} samples, which is longer than expected for this shell stage"
                )

            centroid_delta = extra_analysis.get("centroidDeltaSamples")
            if not isinstance(centroid_delta, (int, float)):
                issues.append("predelay size large verification is missing centroidDeltaSamples")
            elif centroid_delta < minimum_centroid_delta:
                issues.append(
                    f"large-size energy centroid only moved later by {centroid_delta} samples"
                )
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

        extra_analysis: dict | None = None
        expectation = case_data.get("shellVerification", {}).get("expectation")
        if metrics and expectation in {
            "predelay_latency",
            "predelay_diffusion",
            "predelay_recirculation",
            "predelay_dual_branch",
            "predelay_coupled_dual_branch",
            "predelay_feedback_decay_low",
            "predelay_feedback_decay_high",
            "predelay_size_small",
            "predelay_size_large",
        }:
            _, wet_samples = decode_pcm_wave(wet_path)
            wet_onset_samples = find_first_frame_above_threshold(wet_samples)
            wet_last_samples = find_last_frame_above_threshold(wet_samples)

            extra_analysis = {
                "wetOnsetSamples": wet_onset_samples,
                "wetLastAboveThresholdSamples": wet_last_samples,
                "wetOnsetThresholdLinear": 1.0 / 32768.0,
            }

            if expectation == "predelay_diffusion":
                expected_latency = case_data["shellVerification"].get("expectedLatencySamples")
                if not isinstance(expected_latency, int):
                    raise SystemExit(
                        f"error: predelay diffusion shell case {case_id} is missing expectedLatencySamples"
                    )

                pure_reference_dir = case_dir / "pure_predelay_reference"
                pure_reference_path = build_pure_predelay_reference(
                    input_path,
                    pure_reference_dir / "pure_predelay_reference.wav",
                    int(case_data.get("channels", 2)),
                    expected_latency,
                )
                comparison_dir = case_dir / "pure_predelay_comparison"
                comparison_command = [
                    str(harness_path),
                    "analyze",
                    "--dry",
                    str(pure_reference_path),
                    "--wet",
                    str(wet_path),
                    "--outdir",
                    str(comparison_dir),
                    "--auto-align",
                    "--null",
                ]
                comparison_result = run_command(
                    comparison_command,
                    repo_root,
                    comparison_dir / "analyze.stdout.txt",
                    comparison_dir / "analyze.stderr.txt",
                )
                comparison_metrics = {}
                comparison_metrics_path = comparison_dir / "metrics.json"
                if comparison_result["exitCode"] == 0 and comparison_metrics_path.is_file():
                    comparison_metrics = load_json(comparison_metrics_path)

                extra_analysis.update(
                    {
                        "purePredelayReferencePath": str(pure_reference_path.resolve().as_posix()),
                        "comparisonResult": comparison_result,
                        "comparisonMetricsPath": str(comparison_metrics_path.resolve().as_posix()),
                        "comparisonMetrics": comparison_metrics,
                    }
                )
            elif expectation == "predelay_recirculation":
                expected_latency = case_data["shellVerification"].get("expectedLatencySamples")
                if not isinstance(expected_latency, int):
                    raise SystemExit(
                        f"error: predelay recirculation shell case {case_id} is missing expectedLatencySamples"
                    )

                diffusion_reference_dir = case_dir / "diffusion_only_reference"
                diffusion_reference_path = build_predelay_diffusion_reference(
                    input_path,
                    diffusion_reference_dir / "diffusion_only_reference.wav",
                    int(case_data.get("channels", 2)),
                    expected_latency,
                )
                _, diffusion_reference_samples = decode_pcm_wave(diffusion_reference_path)
                diffusion_last_samples = find_last_frame_above_threshold(diffusion_reference_samples)
                extra_persistence = None
                persistence_samples = None
                if isinstance(wet_last_samples, int) and isinstance(diffusion_last_samples, int):
                    extra_persistence = wet_last_samples - diffusion_last_samples
                if isinstance(wet_last_samples, int) and isinstance(wet_onset_samples, int):
                    persistence_samples = wet_last_samples - wet_onset_samples

                comparison_dir = case_dir / "diffusion_only_comparison"
                comparison_command = [
                    str(harness_path),
                    "analyze",
                    "--dry",
                    str(diffusion_reference_path),
                    "--wet",
                    str(wet_path),
                    "--outdir",
                    str(comparison_dir),
                    "--auto-align",
                    "--null",
                ]
                comparison_result = run_command(
                    comparison_command,
                    repo_root,
                    comparison_dir / "analyze.stdout.txt",
                    comparison_dir / "analyze.stderr.txt",
                )
                comparison_metrics = {}
                comparison_metrics_path = comparison_dir / "metrics.json"
                if comparison_result["exitCode"] == 0 and comparison_metrics_path.is_file():
                    comparison_metrics = load_json(comparison_metrics_path)

                extra_analysis.update(
                    {
                        "diffusionOnlyReferencePath": str(diffusion_reference_path.resolve().as_posix()),
                        "diffusionOnlyLastAboveThresholdSamples": diffusion_last_samples,
                        "extraPersistenceSamples": extra_persistence,
                        "wetPersistenceSamples": persistence_samples,
                        "comparisonResult": comparison_result,
                        "comparisonMetricsPath": str(comparison_metrics_path.resolve().as_posix()),
                        "comparisonMetrics": comparison_metrics,
                    }
                )
            elif expectation == "predelay_dual_branch":
                expected_latency = case_data["shellVerification"].get("expectedLatencySamples")
                if not isinstance(expected_latency, int):
                    raise SystemExit(
                        f"error: predelay dual-branch shell case {case_id} is missing expectedLatencySamples"
                    )

                single_branch_reference_dir = case_dir / "single_branch_reference"
                single_branch_reference_path = build_single_branch_reference(
                    input_path,
                    single_branch_reference_dir / "single_branch_reference.wav",
                    int(case_data.get("channels", 2)),
                    expected_latency,
                )
                _, single_branch_reference_samples = decode_pcm_wave(single_branch_reference_path)
                single_branch_last_samples = find_last_frame_above_threshold(single_branch_reference_samples)
                extra_persistence = None
                persistence_samples = None
                if isinstance(wet_last_samples, int) and isinstance(single_branch_last_samples, int):
                    extra_persistence = wet_last_samples - single_branch_last_samples
                if isinstance(wet_last_samples, int) and isinstance(wet_onset_samples, int):
                    persistence_samples = wet_last_samples - wet_onset_samples

                comparison_dir = case_dir / "single_branch_comparison"
                comparison_command = [
                    str(harness_path),
                    "analyze",
                    "--dry",
                    str(single_branch_reference_path),
                    "--wet",
                    str(wet_path),
                    "--outdir",
                    str(comparison_dir),
                    "--auto-align",
                    "--null",
                ]
                comparison_result = run_command(
                    comparison_command,
                    repo_root,
                    comparison_dir / "analyze.stdout.txt",
                    comparison_dir / "analyze.stderr.txt",
                )
                comparison_metrics = {}
                comparison_metrics_path = comparison_dir / "metrics.json"
                if comparison_result["exitCode"] == 0 and comparison_metrics_path.is_file():
                    comparison_metrics = load_json(comparison_metrics_path)

                extra_analysis.update(
                    {
                        "singleBranchReferencePath": str(single_branch_reference_path.resolve().as_posix()),
                        "singleBranchLastAboveThresholdSamples": single_branch_last_samples,
                        "extraPersistenceSamples": extra_persistence,
                        "wetPersistenceSamples": persistence_samples,
                        "stereoMetrics": compute_stereo_metrics(wet_samples),
                        "comparisonResult": comparison_result,
                        "comparisonMetricsPath": str(comparison_metrics_path.resolve().as_posix()),
                        "comparisonMetrics": comparison_metrics,
                    }
                )
            elif expectation == "predelay_coupled_dual_branch":
                expected_latency = case_data["shellVerification"].get("expectedLatencySamples")
                if not isinstance(expected_latency, int):
                    raise SystemExit(
                        f"error: predelay coupled dual-branch shell case {case_id} is missing expectedLatencySamples"
                    )

                uncoupled_reference_dir = case_dir / "uncoupled_dual_branch_reference"
                uncoupled_reference_path = build_uncoupled_two_branch_reference(
                    input_path,
                    uncoupled_reference_dir / "uncoupled_dual_branch_reference.wav",
                    int(case_data.get("channels", 2)),
                    expected_latency,
                )
                _, uncoupled_reference_samples = decode_pcm_wave(uncoupled_reference_path)
                uncoupled_last_samples = find_last_frame_above_threshold(uncoupled_reference_samples)
                extra_persistence = None
                persistence_samples = None
                if isinstance(wet_last_samples, int) and isinstance(uncoupled_last_samples, int):
                    extra_persistence = wet_last_samples - uncoupled_last_samples
                if isinstance(wet_last_samples, int) and isinstance(wet_onset_samples, int):
                    persistence_samples = wet_last_samples - wet_onset_samples

                comparison_dir = case_dir / "uncoupled_dual_branch_comparison"
                comparison_command = [
                    str(harness_path),
                    "analyze",
                    "--dry",
                    str(uncoupled_reference_path),
                    "--wet",
                    str(wet_path),
                    "--outdir",
                    str(comparison_dir),
                    "--auto-align",
                    "--null",
                ]
                comparison_result = run_command(
                    comparison_command,
                    repo_root,
                    comparison_dir / "analyze.stdout.txt",
                    comparison_dir / "analyze.stderr.txt",
                )
                comparison_metrics = {}
                comparison_metrics_path = comparison_dir / "metrics.json"
                if comparison_result["exitCode"] == 0 and comparison_metrics_path.is_file():
                    comparison_metrics = load_json(comparison_metrics_path)

                extra_analysis.update(
                    {
                        "uncoupledDualBranchReferencePath": str(uncoupled_reference_path.resolve().as_posix()),
                        "uncoupledDualBranchLastAboveThresholdSamples": uncoupled_last_samples,
                        "extraPersistenceSamples": extra_persistence,
                        "wetPersistenceSamples": persistence_samples,
                        "stereoMetrics": compute_stereo_metrics(wet_samples),
                        "comparisonResult": comparison_result,
                        "comparisonMetricsPath": str(comparison_metrics_path.resolve().as_posix()),
                        "comparisonMetrics": comparison_metrics,
                    }
                )
            elif expectation == "predelay_feedback_decay_low":
                persistence_samples = None
                if isinstance(wet_last_samples, int) and isinstance(wet_onset_samples, int):
                    persistence_samples = wet_last_samples - wet_onset_samples

                extra_analysis.update(
                    {
                        "wetPersistenceSamples": persistence_samples,
                        "stereoMetrics": compute_stereo_metrics(wet_samples),
                    }
                )
            elif expectation == "predelay_feedback_decay_high":
                compare_to_case_id = case_data["shellVerification"].get("compareToCaseId")
                if not isinstance(compare_to_case_id, str) or not compare_to_case_id:
                    raise SystemExit(
                        f"error: predelay feedback high shell case {case_id} is missing compareToCaseId"
                    )
                if compare_to_case_id not in completed_cases:
                    raise SystemExit(
                        f"error: predelay feedback high shell case {case_id} requires completed comparison case '{compare_to_case_id}'"
                    )

                low_feedback_entry = completed_cases[compare_to_case_id]
                low_feedback_wet_path = Path(low_feedback_entry["wetPath"])
                _, low_feedback_samples = decode_pcm_wave(low_feedback_wet_path)
                low_feedback_last_samples = find_last_frame_above_threshold(low_feedback_samples)
                low_feedback_onset_samples = find_first_frame_above_threshold(low_feedback_samples)
                extra_persistence = None
                persistence_samples = None
                if isinstance(wet_last_samples, int) and isinstance(low_feedback_last_samples, int):
                    extra_persistence = wet_last_samples - low_feedback_last_samples
                if isinstance(wet_last_samples, int) and isinstance(wet_onset_samples, int):
                    persistence_samples = wet_last_samples - wet_onset_samples

                late_window_start = None
                low_feedback_late_window_rms_dbfs = None
                high_feedback_late_window_rms_dbfs = None
                late_window_rms_delta_db = None
                if isinstance(wet_onset_samples, int):
                    late_window_start = wet_onset_samples + 1024
                    high_feedback_late_window_rms_dbfs = compute_window_rms_dbfs(
                        wet_samples,
                        late_window_start,
                        1024,
                    )
                if isinstance(low_feedback_onset_samples, int):
                    low_feedback_window_start = low_feedback_onset_samples + 1024
                    low_feedback_late_window_rms_dbfs = compute_window_rms_dbfs(
                        low_feedback_samples,
                        low_feedback_window_start,
                        1024,
                    )
                if isinstance(high_feedback_late_window_rms_dbfs, (int, float)) and isinstance(low_feedback_late_window_rms_dbfs, (int, float)):
                    late_window_rms_delta_db = high_feedback_late_window_rms_dbfs - low_feedback_late_window_rms_dbfs

                comparison_dir = case_dir / "low_feedback_comparison"
                comparison_command = [
                    str(harness_path),
                    "analyze",
                    "--dry",
                    str(low_feedback_wet_path),
                    "--wet",
                    str(wet_path),
                    "--outdir",
                    str(comparison_dir),
                    "--auto-align",
                    "--null",
                ]
                comparison_result = run_command(
                    comparison_command,
                    repo_root,
                    comparison_dir / "analyze.stdout.txt",
                    comparison_dir / "analyze.stderr.txt",
                )
                comparison_metrics = {}
                comparison_metrics_path = comparison_dir / "metrics.json"
                if comparison_result["exitCode"] == 0 and comparison_metrics_path.is_file():
                    comparison_metrics = load_json(comparison_metrics_path)

                extra_analysis.update(
                    {
                        "lowFeedbackWetPath": str(low_feedback_wet_path.resolve().as_posix()),
                        "lowFeedbackOnsetSamples": low_feedback_onset_samples,
                        "lowFeedbackLastAboveThresholdSamples": low_feedback_last_samples,
                        "extraPersistenceSamples": extra_persistence,
                        "wetPersistenceSamples": persistence_samples,
                        "lateWindowStartSamples": late_window_start,
                        "lowFeedbackLateWindowRmsDbfs": low_feedback_late_window_rms_dbfs,
                        "highFeedbackLateWindowRmsDbfs": high_feedback_late_window_rms_dbfs,
                        "lateWindowRmsDeltaDb": late_window_rms_delta_db,
                        "stereoMetrics": compute_stereo_metrics(wet_samples),
                        "comparisonResult": comparison_result,
                        "comparisonMetricsPath": str(comparison_metrics_path.resolve().as_posix()),
                        "comparisonMetrics": comparison_metrics,
                    }
                )
            elif expectation == "predelay_size_small":
                persistence_samples = None
                centroid_offset = None
                if isinstance(wet_last_samples, int) and isinstance(wet_onset_samples, int):
                    persistence_samples = wet_last_samples - wet_onset_samples
                    centroid_offset = compute_energy_centroid_offset(
                        wet_samples,
                        wet_onset_samples,
                        2048,
                    )

                extra_analysis.update(
                    {
                        "wetPersistenceSamples": persistence_samples,
                        "postOnsetCentroidOffsetSamples": centroid_offset,
                        "stereoMetrics": compute_stereo_metrics(wet_samples),
                    }
                )
            elif expectation == "predelay_size_large":
                compare_to_case_id = case_data["shellVerification"].get("compareToCaseId")
                if not isinstance(compare_to_case_id, str) or not compare_to_case_id:
                    raise SystemExit(
                        f"error: predelay size large shell case {case_id} is missing compareToCaseId"
                    )
                if compare_to_case_id not in completed_cases:
                    raise SystemExit(
                        f"error: predelay size large shell case {case_id} requires completed comparison case '{compare_to_case_id}'"
                    )

                small_size_entry = completed_cases[compare_to_case_id]
                small_size_wet_path = Path(small_size_entry["wetPath"])
                _, small_size_samples = decode_pcm_wave(small_size_wet_path)
                small_size_last_samples = find_last_frame_above_threshold(small_size_samples)
                small_size_onset_samples = find_first_frame_above_threshold(small_size_samples)
                extra_persistence = None
                persistence_samples = None
                centroid_delta = None
                post_onset_centroid_offset = None
                small_size_centroid_offset = None

                if isinstance(wet_last_samples, int) and isinstance(small_size_last_samples, int):
                    extra_persistence = wet_last_samples - small_size_last_samples
                if isinstance(wet_last_samples, int) and isinstance(wet_onset_samples, int):
                    persistence_samples = wet_last_samples - wet_onset_samples
                    post_onset_centroid_offset = compute_energy_centroid_offset(
                        wet_samples,
                        wet_onset_samples,
                        2048,
                    )
                if isinstance(small_size_onset_samples, int):
                    small_size_centroid_offset = compute_energy_centroid_offset(
                        small_size_samples,
                        small_size_onset_samples,
                        2048,
                    )
                if isinstance(post_onset_centroid_offset, (int, float)) and isinstance(small_size_centroid_offset, (int, float)):
                    centroid_delta = post_onset_centroid_offset - small_size_centroid_offset

                comparison_dir = case_dir / "small_size_comparison"
                comparison_command = [
                    str(harness_path),
                    "analyze",
                    "--dry",
                    str(small_size_wet_path),
                    "--wet",
                    str(wet_path),
                    "--outdir",
                    str(comparison_dir),
                    "--auto-align",
                    "--null",
                ]
                comparison_result = run_command(
                    comparison_command,
                    repo_root,
                    comparison_dir / "analyze.stdout.txt",
                    comparison_dir / "analyze.stderr.txt",
                )
                comparison_metrics = {}
                comparison_metrics_path = comparison_dir / "metrics.json"
                if comparison_result["exitCode"] == 0 and comparison_metrics_path.is_file():
                    comparison_metrics = load_json(comparison_metrics_path)

                extra_analysis.update(
                    {
                        "smallSizeWetPath": str(small_size_wet_path.resolve().as_posix()),
                        "smallSizeOnsetSamples": small_size_onset_samples,
                        "smallSizeLastAboveThresholdSamples": small_size_last_samples,
                        "smallSizeCentroidOffsetSamples": small_size_centroid_offset,
                        "extraPersistenceSamples": extra_persistence,
                        "wetPersistenceSamples": persistence_samples,
                        "postOnsetCentroidOffsetSamples": post_onset_centroid_offset,
                        "centroidDeltaSamples": centroid_delta,
                        "stereoMetrics": compute_stereo_metrics(wet_samples),
                        "comparisonResult": comparison_result,
                        "comparisonMetricsPath": str(comparison_metrics_path.resolve().as_posix()),
                        "comparisonMetrics": comparison_metrics,
                    }
                )

        evaluation = evaluate_case(case_data, metrics, case_dir, completed_cases, extra_analysis) if metrics else {
            "caseId": case_id,
            "expectation": case_data.get("shellVerification", {}).get("expectation"),
            "passed": False,
            "issues": ["render or analysis did not produce usable metrics"],
        }

        if metrics and evaluation["passed"]:
            completed_cases[case_id] = {
                "wetPath": str(wet_path.resolve().as_posix()),
                "metricsPath": str(metrics_path.resolve().as_posix()),
                "metrics": metrics,
                "extraAnalysis": extra_analysis,
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
            "extraAnalysis": extra_analysis,
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
            "The current shell remains conservative: the wet path now runs through predelay and then a tiny coupled two-branch early structure with bounded size-scaled short timings and bounded feedback-driven short decay.",
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
