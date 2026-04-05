# OutSpread Measurement Plan

## Purpose

This document defines how OutSpread will be measured against the current shipping Eventide Blackhole reference.

OutSpread is a black-box match project. The measurement workflow exists to prevent subjective drift and to make progress reviewable, repeatable, and comparable over time.

Static IR comparison alone is insufficient because the target is time-varying and modulation-dependent. Attack shape, tail evolution, stereo behavior, modulation, and Freeze/Infinite stability all matter.

## Measurement Principles

### Reference First

All sound comparisons are made against the current shipping Eventide Blackhole plugin.

### Same Inputs, Same Settings

Reference and OutSpread renders must use the same source material, sample rate, block size, channel configuration, nominal parameter values, warmup rules, and render length rules.

### Time-Varying Behavior Matters

The workflow must capture at least:

- attack and bloom timing
- tail envelope and density evolution
- spectral evolution over time
- stereo image evolution
- modulation-dependent movement
- Freeze/Infinite behavior
- stability during long renders

### Artifacts Over Memory

Meaningful comparisons must emit saved artifacts. Listening is required, but listening without stored render evidence is not enough for sound-affecting decisions.

### Stable Vocabulary

Case-group names, summary-file names, and acceptance logic must stay stable across tickets unless this document is updated.

## Reference Lock

The project starts from the current shipping Blackhole target, but baseline capture must lock that target to an explicit recorded reference.

The first baseline reference pass must record:

- Blackhole plugin version under test: `<record exact product version string from the captured reference build>`
- platform and OS used for capture: `<record exact OS, version, and architecture>`
- host or render path assumptions: `<record exact host name and version, or the exact harness render path used>`
- baseline workflow assumptions: 48 kHz, 256 sample blocks, stereo render path, and the default warmup/render rules in this document unless a case records an explicit override

Once baseline captures exist, the project must not silently drift to a newer "current shipping" Blackhole target. Any change to the locked reference version, platform, or render-path assumptions must update this section and must be accompanied by a documented re-baseline note in the same change.

## Intended Repo Structure

The measurement workflow should converge on the following layout:

```text
tests/
  cases/
    smoke/
    attack/
    tail/
    gravity/
    size/
    tone_eq/
    modulation/
    width/
    freeze_infinite/
    predelay/
    sample_rate_block_size/
    cpu_latency/
  _generated/
    stimuli/
artifacts/
  measurements/
    <timestamp>/
      summary.json
      attack_summary.json
      tail_summary.json
      gravity_summary.json
      width_summary.json
      modulation_summary.json
      freeze_summary.json
      predelay_summary.json
      sample_rate_summary.json
      cpu_latency_summary.json
      cases/
        <case_id>/
```

This is the intended scripted workflow shape for future tickets. It does not imply that every script or directory already exists today.

## Case Manifest Shape

Future case files under `tests/cases` should stay compatible with the current harness direction. At minimum, each case should define:

- plugin under test
- sampleRate
- blockSize
- channels
- input
- warmupMs
- renderSeconds
- parameter assignment data

`paramsByName` is the default source of truth and should be used unless the harness or a compatibility need requires index-based assignment. `paramsByIndex` is optional and should only appear when that compatibility need is real. Do not duplicate the same parameter definitions in both fields by default.

If the runner supports metadata fields such as `id`, `group`, `notes`, or `expectedOutputs`, those fields should remain additive and should not break the base shape above.

## Standard Render Settings

Unless a case overrides them, the baseline scripted render settings are:

- sample rate: 48 kHz
- block size: 256
- channels: 2
- warmup: 50 ms
- render length: 2.0 seconds

Case-group overrides should remain fixed and explicit in the manifest. Initial group-level defaults are:

- smoke: 2 to 4 seconds
- attack: 4 to 8 seconds
- tail: 15 to 45 seconds
- gravity: 8 to 20 seconds
- size: 8 to 20 seconds
- tone/eq: 8 to 20 seconds
- modulation: 12 to 30 seconds
- width: 6 to 12 seconds
- freeze/infinite: 60 to 120 seconds
- predelay: 4 to 8 seconds
- sample-rate/block-size: match the base case duration for the behavior under test
- cpu/latency: enough duration to smooth short-term timing noise

Expanded validation must include:

- 44.1 kHz
- 48 kHz
- 88.2 kHz
- 96 kHz
- 64 sample blocks
- 128 sample blocks
- 256 sample blocks
- 512 sample blocks
- 1024 sample blocks

## Determinism Expectations

Repeated renders do not all need the same acceptance method.

Technical and low-variability cases should be meaningfully deterministic when plugin version, platform, host or harness path, sample rate, block size, input, and parameter state are held constant. This includes smoke, predelay, many attack cases, and static tone or routing checks. These cases may use exact or near-exact repeatability checks when that helps detect regressions.

Modulation-heavy or otherwise time-varying cases may not be sample-identical across repeated renders even when the behavior is still correct. This includes modulation cases, some width cases, long-tail Freeze/Infinite cases, and any case where the reference itself is not meaningfully sample-repeatable. For these cases, acceptance should prefer stable proxy metrics, envelope and spectral summaries, stereo statistics, bounded repeatability expectations, and listening review rather than sample-identical null tests.

If a case is expected to be non-deterministic, the case definition or analysis path should say so explicitly.

## Stimulus Set

The workflow should use stable generated or versioned source material. Once a stimulus is chosen for baseline comparison, do not replace it casually.

### Technical Stimuli

- impulse
- silence
- click or sparse transient train
- 100 Hz sine
- 1 kHz sine
- 10 kHz sine
- logarithmic swept sine
- white-noise burst
- pink-noise burst

### Practical Stimuli

- short snare or percussion loop
- plucked guitar or pluck synth
- sustained synth pad
- mono melodic phrase
- stereo music excerpt
- dry vocal phrase or voice-like source if one is approved for the repo

## Case Groups

### Smoke

Basic sanity checks that confirm the plugin renders, loads, resets, and produces valid output.

### Attack

Measures onset softness, bloom timing, predelay onset, and early density build.

### Tail

Measures decay contour, long-tail density, texture, and spectral evolution.

### Gravity

Measures bipolar Gravity behavior, transition through center, and reverse-like behavior on the negative side.

### Size

Measures apparent space scaling, diffusion-length changes, and interaction with feedback and decay.

### Tone/EQ

Measures low tone, high tone, resonance, and tail color changes over time.

### Modulation

Measures modulation rate feel, modulation depth feel, internal movement, and resistance to obvious chorus artifacts.

### Width

Measures mono in -> stereo spread, decorrelation, center stability, left/right correlation, and side-energy behavior.

### Freeze/Infinite

Measures entry behavior, sustain behavior, exit behavior, long-run stability, and new-input handling while latched.

### Predelay

Measures predelay timing accuracy, transient placement, and interaction between predelay and bloom.

### Sample-Rate/Block-Size

Measures behavior consistency across execution conditions and catches broken settings-dependent behavior.

### CPU/Latency

Measures CPU cost, latency reporting, and multiple-instance practicality.

## Case Naming Convention

Case names should be descriptive, stable, and readable in artifact folders. Use lowercase snake_case with the case group first.

Examples:

- `attack_default_pad`
- `attack_gravity_neg50_clicks`
- `tail_huge_dark_pad`
- `gravity_center_pluck`
- `gravity_negative_extreme_snare`
- `size_large_pad`
- `tone_eq_dark_pad`
- `modulation_depth_high_pad`
- `width_mono_pluck_default`
- `freeze_infinite_default_pad`
- `predelay_250ms_click`
- `sample_rate_96k_default_pad`
- `cpu_latency_default_pad`

## Metrics

### General Render Sanity

Every case should report:

- sample rate
- block size
- render length
- max absolute sample value
- RMS level
- NaN detection
- Inf detection
- clip detection
- output file paths

### Attack Metrics

- predelay onset location
- time to first meaningful wet energy
- time to 10 percent, 50 percent, and 90 percent of local peak envelope
- early density build
- short-window crest-factor change

### Tail Metrics

- broadband envelope over time
- low-band decay curve
- mid-band decay curve
- high-band decay curve
- early decay slope
- later decay slope
- spectral centroid over time
- density proxy such as spectral flatness over time

### Gravity Metrics

- change in energy-build timing across negative, center, and positive settings
- reverse-like onset behavior on negative settings
- onset contour
- decay asymmetry
- transient smear or pull-back behavior

### Size Metrics

- apparent time-to-density change
- decay scaling across size settings
- band-energy changes across size settings
- interaction between size and feedback on long tails

### Tone/EQ Metrics

- low-band energy shift
- high-band energy shift
- resonance emphasis
- spectral centroid drift
- spectral slope drift
- early-versus-late tonal difference

### Modulation Metrics

- coarse modulation-rate proxy from moving tail features
- modulation-depth proxy from envelope or spectral excursion
- tail spectral movement over time
- deviation from a time-averaged tail
- low-setting and high-setting stability

Perfect recovery of internal LFOs is not required. Stable comparison proxies are enough.

### Width Metrics

- left/right correlation over time
- mid versus side energy ratio
- side-energy build over time
- center retention on mono sources
- mono compatibility check

### Freeze/Infinite Metrics

- energy drift over fixed intervals
- max sample magnitude over time
- NaN detection
- Inf detection
- clip detection
- transition artifacts when entering or leaving the mode
- behavior when new input arrives while latched

### Predelay Metrics

- measured wet onset delay
- deviation from the target predelay
- interaction between predelay and bloom timing

### Sample-Rate/Block-Size Metrics

- pass or fail at each rate and block size
- drift in the relevant group metrics compared with the baseline case
- any settings that change behavior class or break rendering

### CPU/Latency Metrics

- average processing time per block
- peak processing time per block where practical
- relative CPU cost across key settings
- reported latency
- multiple-instance stress observations

## Artifact Outputs

Every measurement run should write a timestamped folder under `artifacts/measurements/<timestamp>/`.

Required top-level summary files:

- `attack_summary.json`
- `tail_summary.json`
- `gravity_summary.json`
- `width_summary.json`
- `modulation_summary.json`
- `freeze_summary.json`
- `predelay_summary.json`
- `sample_rate_summary.json`
- `cpu_latency_summary.json`
- `summary.json`

Expected per-case artifacts:

- input reference path
- rendered reference WAV
- rendered OutSpread WAV
- case metrics JSON
- selected CSV exports where numeric curves matter
- selected PNG plots where shape comparison matters

`summary.json` should report:

- run timestamp
- plugin under test
- reference plugin identifier
- case groups executed
- baseline settings
- pass/fail summary
- paths to each group summary file

## Historical Comparability

Once baseline captures exist, historical comparability becomes part of the measurement contract.

- default stimuli must not be silently changed
- core case names must not be silently changed
- required summary file names must not be silently changed
- any necessary change to stimuli, core case names, or summary-file names must include a migration note or comparability note explaining how old and new runs should be compared

This rule reinforces the maintenance rules below. It does not replace them.

## Initial Acceptance Thresholds

These are initial gates for development. They should be tightened only after a real reference baseline exists and this document is updated.

### Smoke

- render completes
- no NaN or Inf output
- no obvious unintended clipping

### Predelay

- measured predelay within 1 ms of the reference on technical click cases

### Attack

- first-wet-energy timing and 10/50/90 percent rise metrics within 15 percent of the reference on core attack cases

### Tail

- no sustained greater-than-3 dB divergence in low, mid, or high decay envelopes over matched analysis windows
- early and later decay slopes within 15 percent of the reference on core tail cases

### Gravity

- negative, center, and positive settings remain in the same behavior class as the reference
- major gravity timing and contour proxies within 20 percent on core gravity cases

### Size

- size-dependent density and decay behavior remain within 20 percent of the reference on core size cases
- no discontinuities or control-law jumps that are absent in the reference

### Tone/EQ

- low-band and high-band energy shifts within 2 dB of the reference on matched windows
- resonance emphasis lands in the same band and behavior class as the reference

### Width

- left/right correlation delta no greater than 0.10 on core width cases
- mid/side energy ratio within 1.5 dB on mono-source width cases

### Modulation

- modulation-rate and modulation-depth proxies within 20 percent on core modulation cases
- no obvious chorus-like mismatch in listening review

### Freeze/Infinite

- no runaway instability
- no NaN, Inf, or uncontrolled clipping
- energy drift after the initial settle period stays within 1 dB per 60 seconds on steady-state freeze/infinite cases

### Sample-Rate/Block-Size

- no broken renders or major behavior-class changes across the supported matrix

### CPU/Latency

- latency reporting is correct and stable
- CPU behavior is documented and practical for normal multi-instance use

## Development Sequence

Measurement work should be implemented in this order:

### Phase A - Infrastructure

- lock case schema
- generate stimuli
- build the scripted runner
- lock artifact folder layout
- emit `summary.json`

### Phase B - Core Analyses

- predelay detection
- attack analysis
- tail analysis
- width analysis

### Phase C - Signature Analyses

- gravity analysis
- size analysis
- tone/eq analysis
- modulation analysis
- freeze/infinite analysis

### Phase D - Validation Expansion

- sample-rate/block-size sweeps
- cpu/latency reporting
- listening-support workflow
- final threshold review

## Listening Confirmation

Measurements are necessary but not sufficient. Core listening review must include transient material, plucks, pads, mono-source width checks, long tails, and Freeze/Infinite cases.

If the metrics look close but blind or near-blind A/B still reveals an obvious mismatch, the change does not pass.

## Maintenance Rules

- do not silently change case definitions
- do not silently change stimuli after baseline capture
- do not delete historical artifacts needed for comparison
- do not change summary-file names without updating this document
- do not change acceptance logic without updating this document
- do not merge major sound-affecting work without a measurement run
