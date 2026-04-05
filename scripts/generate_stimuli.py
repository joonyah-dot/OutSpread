#!/usr/bin/env python3
"""Generate deterministic technical stimuli for OutSpread measurement work."""

from __future__ import annotations

import argparse
import json
import math
import random
import struct
import sys
import wave
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path


SCHEMA_VERSION = 2
GENERATOR_VERSION = "outspread-generate-stimuli-v1"
DEFAULT_SAMPLE_RATE = 48000
DEFAULT_CHANNELS = 1
PCM_BIT_DEPTH = 16  # stdlib wave reliably handles PCM16 without extra dependencies.
NOISE_WHITE_SEED = 1337
NOISE_PINK_SEED = 7331
CLICK_SPACING_MS = 250.0
FADE_MS = 10.0
SWEEP_START_HZ = 20.0
SWEEP_END_HZ = 20000.0

IMPULSE_AMPLITUDE = 0.95
CLICK_AMPLITUDE = 0.80
SINE_AMPLITUDE = 0.50
SWEEP_AMPLITUDE = 0.70
NOISE_PEAK_AMPLITUDE = 0.50


@dataclass(frozen=True)
class StimulusSpec:
    stimulus_id: str
    filename: str
    duration_arg: str
    amplitude: float
    description: str


STIMULI = [
    StimulusSpec(
        stimulus_id="impulse",
        filename="impulse.wav",
        duration_arg="duration_silence",
        amplitude=IMPULSE_AMPLITUDE,
        description="Single-sample impulse for timing and IR-style checks.",
    ),
    StimulusSpec(
        stimulus_id="silence",
        filename="silence.wav",
        duration_arg="duration_silence",
        amplitude=0.0,
        description="True silence for noise-floor and stability checks.",
    ),
    StimulusSpec(
        stimulus_id="click_train",
        filename="click_train.wav",
        duration_arg="duration_click_train",
        amplitude=CLICK_AMPLITUDE,
        description="Sparse click train for onset and predelay checks.",
    ),
    StimulusSpec(
        stimulus_id="sine_100hz",
        filename="sine_100hz.wav",
        duration_arg="duration_sines",
        amplitude=SINE_AMPLITUDE,
        description="100 Hz sine tone.",
    ),
    StimulusSpec(
        stimulus_id="sine_1khz",
        filename="sine_1khz.wav",
        duration_arg="duration_sines",
        amplitude=SINE_AMPLITUDE,
        description="1 kHz sine tone.",
    ),
    StimulusSpec(
        stimulus_id="sine_10khz",
        filename="sine_10khz.wav",
        duration_arg="duration_sines",
        amplitude=SINE_AMPLITUDE,
        description="10 kHz sine tone.",
    ),
    StimulusSpec(
        stimulus_id="log_sweep",
        filename="log_sweep.wav",
        duration_arg="duration_sweep",
        amplitude=SWEEP_AMPLITUDE,
        description="Logarithmic sine sweep.",
    ),
    StimulusSpec(
        stimulus_id="white_noise_burst",
        filename="white_noise_burst.wav",
        duration_arg="duration_noise_burst",
        amplitude=NOISE_PEAK_AMPLITUDE,
        description="Deterministic white-noise burst.",
    ),
    StimulusSpec(
        stimulus_id="pink_noise_burst",
        filename="pink_noise_burst.wav",
        duration_arg="duration_noise_burst",
        amplitude=NOISE_PEAK_AMPLITUDE,
        description="Deterministic pink-noise burst.",
    ),
]


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Generate deterministic technical WAV stimuli for OutSpread."
    )
    parser.add_argument(
        "--outdir",
        default="tests/_generated/stimuli",
        help="Output directory for generated stimuli.",
    )
    parser.add_argument(
        "--sr",
        type=int,
        default=DEFAULT_SAMPLE_RATE,
        help="Sample rate in Hz.",
    )
    parser.add_argument(
        "--overwrite",
        action="store_true",
        help="Overwrite existing files. Without this flag, existing files are skipped.",
    )
    parser.add_argument(
        "--duration-silence",
        type=float,
        default=2.0,
        help="Duration in seconds for impulse.wav and silence.wav.",
    )
    parser.add_argument(
        "--duration-sines",
        type=float,
        default=2.0,
        help="Duration in seconds for sine stimuli.",
    )
    parser.add_argument(
        "--duration-sweep",
        type=float,
        default=5.0,
        help="Duration in seconds for the logarithmic sweep.",
    )
    parser.add_argument(
        "--duration-click-train",
        type=float,
        default=2.0,
        help="Duration in seconds for the click train stimulus.",
    )
    parser.add_argument(
        "--duration-noise-burst",
        type=float,
        default=1.0,
        help="Duration in seconds for white and pink noise bursts.",
    )
    parser.add_argument(
        "--white-seed",
        type=int,
        default=NOISE_WHITE_SEED,
        help="Seed for deterministic white-noise generation.",
    )
    parser.add_argument(
        "--pink-seed",
        type=int,
        default=NOISE_PINK_SEED,
        help="Seed for deterministic pink-noise generation.",
    )
    return parser.parse_args()


def validate_args(args: argparse.Namespace) -> None:
    if args.sr <= 0:
        raise SystemExit("error: --sr must be positive.")

    for name in (
        "duration_silence",
        "duration_sines",
        "duration_sweep",
        "duration_click_train",
        "duration_noise_burst",
    ):
        value = getattr(args, name)
        if value <= 0.0:
            raise SystemExit(f"error: --{name.replace('_', '-')} must be positive.")


def seconds_to_samples(duration_seconds: float, sample_rate: int) -> int:
    return int(round(duration_seconds * sample_rate))


def apply_fade(samples: list[float], fade_samples: int) -> list[float]:
    if fade_samples <= 0 or not samples:
        return samples

    fade_samples = min(fade_samples, len(samples) // 2)
    if fade_samples == 0:
        return samples

    for index in range(fade_samples):
        phase = (index + 1) / fade_samples
        gain = math.sin(0.5 * math.pi * phase) ** 2
        samples[index] *= gain
        samples[-(index + 1)] *= gain
    return samples


def peak_normalize(samples: list[float], target_peak: float) -> list[float]:
    if target_peak <= 0.0:
        return samples
    peak = max((abs(sample) for sample in samples), default=0.0)
    if peak == 0.0:
        return samples
    scale = target_peak / peak
    return [sample * scale for sample in samples]


def write_pcm16_wav(path: Path, channels: int, sample_rate: int, samples: list[float]) -> float:
    peak_after_quantization = 0.0
    with wave.open(str(path), "wb") as wav_file:
        wav_file.setnchannels(channels)
        wav_file.setsampwidth(2)
        wav_file.setframerate(sample_rate)

        frames = bytearray()
        for sample in samples:
            clamped = max(-1.0, min(1.0, sample))
            peak_after_quantization = max(peak_after_quantization, abs(clamped))
            quantized = int(round(clamped * 32767.0))
            frames.extend(struct.pack("<h", quantized))
        wav_file.writeframes(frames)
    return peak_after_quantization


def generate_impulse(total_samples: int, amplitude: float) -> list[float]:
    samples = [0.0] * total_samples
    if total_samples > 0:
        samples[0] = amplitude
    return samples


def generate_silence(total_samples: int) -> list[float]:
    return [0.0] * total_samples


def generate_click_train(total_samples: int, amplitude: float, sample_rate: int) -> list[float]:
    interval_samples = max(1, int(round(sample_rate * CLICK_SPACING_MS / 1000.0)))
    samples = [0.0] * total_samples
    for index in range(0, total_samples, interval_samples):
        samples[index] = amplitude
    return samples


def generate_sine(total_samples: int, amplitude: float, sample_rate: int, frequency_hz: float) -> list[float]:
    samples = [
        amplitude * math.sin(2.0 * math.pi * frequency_hz * n / sample_rate)
        for n in range(total_samples)
    ]
    return apply_fade(samples, int(round(sample_rate * FADE_MS / 1000.0)))


def generate_log_sweep(total_samples: int, amplitude: float, sample_rate: int) -> list[float]:
    duration_seconds = total_samples / float(sample_rate)
    ratio = SWEEP_END_HZ / SWEEP_START_HZ
    log_ratio = math.log(ratio)
    scale = 2.0 * math.pi * SWEEP_START_HZ * duration_seconds / log_ratio

    samples = []
    for n in range(total_samples):
        t = n / float(sample_rate)
        phase = scale * (math.exp((t / duration_seconds) * log_ratio) - 1.0)
        samples.append(amplitude * math.sin(phase))
    return apply_fade(samples, int(round(sample_rate * FADE_MS / 1000.0)))


def generate_white_noise(total_samples: int, target_peak: float, seed: int, sample_rate: int) -> list[float]:
    rng = random.Random(seed)
    samples = [rng.uniform(-1.0, 1.0) for _ in range(total_samples)]
    samples = apply_fade(samples, int(round(sample_rate * FADE_MS / 1000.0)))
    return peak_normalize(samples, target_peak)


def generate_pink_noise(total_samples: int, target_peak: float, seed: int, sample_rate: int) -> list[float]:
    rng = random.Random(seed)
    b0 = b1 = b2 = b3 = b4 = b5 = b6 = 0.0
    samples = []
    for _ in range(total_samples):
        white = rng.uniform(-1.0, 1.0)
        b0 = 0.99886 * b0 + white * 0.0555179
        b1 = 0.99332 * b1 + white * 0.0750759
        b2 = 0.96900 * b2 + white * 0.1538520
        b3 = 0.86650 * b3 + white * 0.3104856
        b4 = 0.55000 * b4 + white * 0.5329522
        b5 = -0.7616 * b5 - white * 0.0168980
        pink = b0 + b1 + b2 + b3 + b4 + b5 + b6 + white * 0.5362
        b6 = white * 0.115926
        samples.append(pink * 0.11)
    samples = apply_fade(samples, int(round(sample_rate * FADE_MS / 1000.0)))
    return peak_normalize(samples, target_peak)


def create_manifest_entry(
    *,
    stimulus_id: str,
    output_path: Path,
    duration_seconds: float,
    sample_rate: int,
    actual_peak: float,
    status: str,
    amplitude_convention: str,
    generated: bool,
    **extra: object,
) -> dict:
    entry = {
        "id": stimulus_id,
        "filePath": str(output_path.as_posix()),
        "fileName": output_path.name,
        "durationSeconds": duration_seconds,
        "sampleRate": sample_rate,
        "channelCount": DEFAULT_CHANNELS,
        "format": "wav",
        "encoding": "PCM",
        "bitDepth": PCM_BIT_DEPTH,
        "status": status,
        "generated": generated,
        "amplitudeConvention": amplitude_convention,
        "actualPeakAmplitude": round(actual_peak, 6),
    }
    entry.update(extra)
    return entry


def generate_stimulus(
    spec: StimulusSpec, args: argparse.Namespace, outdir: Path, sample_rate: int
) -> dict:
    duration_seconds = getattr(args, spec.duration_arg)
    total_samples = seconds_to_samples(duration_seconds, sample_rate)
    output_path = outdir / spec.filename
    amplitude_convention = f"peak amplitude target {spec.amplitude:.3f}"

    if spec.stimulus_id == "impulse":
        samples = generate_impulse(total_samples, spec.amplitude)
        metadata = {
            "peakAmplitudeTarget": spec.amplitude,
            "method": "single_sample_impulse",
            "impulseSampleIndex": 0,
        }
    elif spec.stimulus_id == "silence":
        samples = generate_silence(total_samples)
        metadata = {
            "peakAmplitudeTarget": 0.0,
            "method": "true_silence",
        }
        amplitude_convention = "all samples are exactly zero"
    elif spec.stimulus_id == "click_train":
        samples = generate_click_train(total_samples, spec.amplitude, sample_rate)
        metadata = {
            "peakAmplitudeTarget": spec.amplitude,
            "method": "single_sample_clicks",
            "clickSpacingMs": CLICK_SPACING_MS,
            "firstClickSampleIndex": 0,
        }
    elif spec.stimulus_id == "sine_100hz":
        samples = generate_sine(total_samples, spec.amplitude, sample_rate, 100.0)
        metadata = {
            "peakAmplitudeTarget": spec.amplitude,
            "frequencyHz": 100.0,
            "method": "windowed_sine",
            "fadeMs": FADE_MS,
        }
    elif spec.stimulus_id == "sine_1khz":
        samples = generate_sine(total_samples, spec.amplitude, sample_rate, 1000.0)
        metadata = {
            "peakAmplitudeTarget": spec.amplitude,
            "frequencyHz": 1000.0,
            "method": "windowed_sine",
            "fadeMs": FADE_MS,
        }
    elif spec.stimulus_id == "sine_10khz":
        samples = generate_sine(total_samples, spec.amplitude, sample_rate, 10000.0)
        metadata = {
            "peakAmplitudeTarget": spec.amplitude,
            "frequencyHz": 10000.0,
            "method": "windowed_sine",
            "fadeMs": FADE_MS,
        }
    elif spec.stimulus_id == "log_sweep":
        samples = generate_log_sweep(total_samples, spec.amplitude, sample_rate)
        metadata = {
            "peakAmplitudeTarget": spec.amplitude,
            "frequencyStartHz": SWEEP_START_HZ,
            "frequencyEndHz": SWEEP_END_HZ,
            "method": "windowed_log_sine_sweep",
            "fadeMs": FADE_MS,
        }
    elif spec.stimulus_id == "white_noise_burst":
        samples = generate_white_noise(total_samples, spec.amplitude, args.white_seed, sample_rate)
        metadata = {
            "peakAmplitudeTarget": spec.amplitude,
            "seed": args.white_seed,
            "method": "uniform_white_noise_peak_normalized",
            "fadeMs": FADE_MS,
        }
    elif spec.stimulus_id == "pink_noise_burst":
        samples = generate_pink_noise(total_samples, spec.amplitude, args.pink_seed, sample_rate)
        metadata = {
            "peakAmplitudeTarget": spec.amplitude,
            "seed": args.pink_seed,
            "method": "paul_kellet_style_filter_peak_normalized",
            "fadeMs": FADE_MS,
        }
    else:
        raise RuntimeError(f"Unhandled stimulus ID: {spec.stimulus_id}")

    actual_peak = max((abs(sample) for sample in samples), default=0.0)
    if output_path.exists() and not args.overwrite:
        return create_manifest_entry(
            stimulus_id=spec.stimulus_id,
            output_path=output_path,
            duration_seconds=duration_seconds,
            sample_rate=sample_rate,
            actual_peak=actual_peak,
            status="skipped_existing",
            amplitude_convention=amplitude_convention,
            generated=False,
            **metadata,
        )

    actual_peak = write_pcm16_wav(output_path, DEFAULT_CHANNELS, sample_rate, samples)
    return create_manifest_entry(
        stimulus_id=spec.stimulus_id,
        output_path=output_path,
        duration_seconds=duration_seconds,
        sample_rate=sample_rate,
        actual_peak=actual_peak,
        status="generated",
        amplitude_convention=amplitude_convention,
        generated=True,
        **metadata,
    )


def main() -> int:
    args = parse_args()
    validate_args(args)

    repo_root = Path(__file__).resolve().parent.parent
    outdir = (repo_root / args.outdir).resolve()
    outdir.mkdir(parents=True, exist_ok=True)

    scaffold_note = outdir / "SCAFFOLD_NOTE.txt"
    if scaffold_note.exists():
        scaffold_note.unlink()

    manifest_entries = []
    generated_count = 0
    skipped_count = 0

    for spec in STIMULI:
        entry = generate_stimulus(spec, args, outdir, args.sr)
        manifest_entries.append(entry)
        if entry["generated"]:
            generated_count += 1
            print(f"generated: {entry['filePath']}")
        else:
            skipped_count += 1
            print(f"skipped:   {entry['filePath']}")

    manifest = {
        "schemaVersion": SCHEMA_VERSION,
        "generatorVersion": GENERATOR_VERSION,
        "generatedAt": datetime.now().isoformat(timespec="seconds"),
        "outputDirectory": str(outdir.as_posix()),
        "sampleRate": args.sr,
        "channelCount": DEFAULT_CHANNELS,
        "format": "wav",
        "encoding": "PCM",
        "bitDepth": PCM_BIT_DEPTH,
        "overwrite": args.overwrite,
        "defaults": {
            "durationSilenceSeconds": args.duration_silence,
            "durationSinesSeconds": args.duration_sines,
            "durationSweepSeconds": args.duration_sweep,
            "durationClickTrainSeconds": args.duration_click_train,
            "durationNoiseBurstSeconds": args.duration_noise_burst,
            "clickSpacingMs": CLICK_SPACING_MS,
            "fadeMs": FADE_MS,
            "sweepRangeHz": [SWEEP_START_HZ, SWEEP_END_HZ],
            "whiteNoiseSeed": args.white_seed,
            "pinkNoiseSeed": args.pink_seed,
        },
        "outputFiles": [entry["fileName"] for entry in manifest_entries],
        "newlyGeneratedFiles": [
            entry["fileName"] for entry in manifest_entries if entry["status"] == "generated"
        ],
        "skippedExistingFiles": [
            entry["fileName"]
            for entry in manifest_entries
            if entry["status"] == "skipped_existing"
        ],
        "newlyGeneratedCount": generated_count,
        "skippedExistingCount": skipped_count,
        "files": manifest_entries,
    }

    manifest_path = outdir / "stimuli_manifest.json"
    with manifest_path.open("w", encoding="utf-8") as handle:
        json.dump(manifest, handle, indent=2)
        handle.write("\n")

    print(f"wrote manifest: {manifest_path}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
