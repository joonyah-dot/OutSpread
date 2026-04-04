#!/usr/bin/env python3
import argparse
import math
import os
import struct
import wave


def write_wav(path: str, channels: int, sample_rate: int, samples):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with wave.open(path, "wb") as wf:
        wf.setnchannels(channels)
        wf.setsampwidth(2)
        wf.setframerate(sample_rate)

        frames = bytearray()
        for frame in samples:
            for sample in frame:
                clamped = max(-1.0, min(1.0, sample))
                frames.extend(struct.pack("<h", int(clamped * 32767.0)))
        wf.writeframes(frames)


def generate_impulse(total_samples: int, channels: int):
    data = []
    for i in range(total_samples):
        amp = 0.9 if i == 0 else 0.0
        data.append([amp] * channels)
    return data


def generate_sine(total_samples: int, channels: int, sample_rate: int, freq_hz: float):
    data = []
    for i in range(total_samples):
        t = i / float(sample_rate)
        s = 0.5 * math.sin(2.0 * math.pi * freq_hz * t)
        data.append([s] * channels)
    return data


def main():
    parser = argparse.ArgumentParser(description="Generate simple test WAV files.")
    parser.add_argument("--outdir", required=True, help="Output directory")
    parser.add_argument("--sr", type=int, default=48000, help="Sample rate")
    parser.add_argument("--seconds", type=float, default=2.0, help="Duration in seconds")
    parser.add_argument("--channels", type=int, default=2, help="Number of channels")
    args = parser.parse_args()

    if args.sr <= 0:
        raise ValueError("Sample rate must be positive.")
    if args.seconds <= 0:
        raise ValueError("Duration must be positive.")
    if args.channels <= 0:
        raise ValueError("Channels must be positive.")

    total_samples = int(round(args.sr * args.seconds))
    outdir = os.path.abspath(args.outdir)
    os.makedirs(outdir, exist_ok=True)

    impulse_path = os.path.join(outdir, "impulse.wav")
    sine_path = os.path.join(outdir, "sine1k.wav")

    write_wav(impulse_path, args.channels, args.sr, generate_impulse(total_samples, args.channels))
    write_wav(sine_path, args.channels, args.sr, generate_sine(total_samples, args.channels, args.sr, 1000.0))

    print(f"Wrote: {impulse_path}")
    print(f"Wrote: {sine_path}")


if __name__ == "__main__":
    main()
