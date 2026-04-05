# OutSpread Case Layout

`tests/cases` is the stable home for grouped measurement cases.

## Purpose

The grouped layout keeps measurement vocabulary consistent with `SPEC.md`, `TASKS.md`, and `MEASUREMENT_PLAN.md`. Future tickets should add cases to the existing groups instead of inventing new top-level names.

Current groups:

- `smoke`
- `attack`
- `tail`
- `gravity`
- `size`
- `tone_eq`
- `modulation`
- `width`
- `freeze_infinite`
- `predelay`
- `sample_rate_block_size`
- `cpu_latency`

## Naming Convention

Case files should use lowercase snake_case and start with the group name.

Examples:

- `attack_default_pad.json`
- `gravity_negative_extreme_snare.json`
- `tone_eq_dark_pad.json`
- `freeze_infinite_default_pad.json`

This keeps artifact folders and summary output readable without opening the case file first.

## Case Shape

The baseline workflow shape is defined in `case_manifest.json`.

- Prefer `paramsByName` for parameter assignment.
- Use `paramsByIndex` only when harness compatibility requires it.
- Do not duplicate the same parameter definitions in both fields by default.
- The runner discovers declared case files only from the grouped directories listed in the manifest.
- Root-level files such as `example.json` are not part of the manifest-driven grouped workflow.

Baseline defaults live in the manifest and apply unless a case overrides them. A case should only override defaults when the override is part of the behavior being tested.

## Stimulus References

Grouped cases should reference generated technical stimuli through the generated-stimuli workflow rather than inventing ad hoc input paths.

Preferred form:

```json
{
  "input": {
    "stimulusId": "impulse"
  }
}
```

The runner resolves `stimulusId` values through `tests/_generated/stimuli/stimuli_manifest.json` and fails if the referenced stimulus is missing.

String inputs are also allowed when they clearly identify a generated stimulus ID, generated stimulus file name, or an explicit file path. Do not rely on ambiguous shorthand.

## Reference States

Grouped cases should reference reusable Blackhole target-state definitions through `referenceStateId`.

Preferred form:

```json
{
  "referenceStateId": "blackhole_attack_probe"
}
```

The runner resolves `referenceStateId` values through `tests/reference_states/reference_state_manifest.json` and fails if the referenced state is missing or malformed.

Cases should not duplicate full target parameter blobs by default. Reusable target-state intent belongs in `tests/reference_states/`, while case files describe the input, analysis profile, and any case-specific overrides.

When a run is prepared, the runner merges reusable state parameters with any case-local parameter overrides to create a harness-ready `reference_case.json` next to the per-case artifacts. State parameters are the default source of truth. Case-local parameters are only for narrow overrides.

## Planning And Execution

Planning mode remains the default:

```powershell
py -3 scripts\run_measurements.py --all-groups
```

This resolves grouped cases, stimuli, reusable reference states, and command plans without claiming any capture happened.

Reference execution is explicit:

```powershell
py -3 scripts\run_measurements.py --groups smoke,attack --reference-plugin "C:\Path\To\Blackhole.vst3" --harness "C:\Path\To\vst3_harness.exe" --execute-reference
```

Execution mode requires:

- a valid `--reference-plugin` path that points to a `.vst3`
- a valid `--harness` path for the current render workflow

If those prerequisites are missing or invalid, the runner fails clearly instead of pretending capture happened.

## Per-Case Artifacts

For each resolved case, the runner writes:

- `cases/<case_id>/case_plan.json`
- `cases/<case_id>/reference_capture.json`
- `cases/<case_id>/reference_case.json`
- `cases/<case_id>/reference/`

In planning mode, these files describe the planned command sequence and expected output paths only.

In execution mode, `reference_capture.json` records the command arguments, stdout/stderr paths, exit status, and whether expected outputs such as `wet.wav` and `metrics.json` were actually produced.

## Adding Cases

When adding a new case:

1. Put it in the existing group directory that matches the measurement vocabulary.
2. Reuse the baseline defaults unless the case needs a specific override.
3. Reuse existing reference states instead of redefining the same parameter setup under a new name.
4. Keep case names, summary file names, and group names stable unless the planning docs are updated in the same change.
5. Prefer scaffold or planning-only notes until the real Blackhole reference states are captured and locked.

## Defaults And Overrides

Manifest defaults supply the baseline workflow settings for sample rate, block size, channel count, warmup, and render length.

Per-case overrides should be used only when the behavior under test actually depends on them, such as:

- sample-rate/block-size cases
- long freeze/infinite planning cases
- mono-input width cases

The runner records the resolved settings per case in the timestamped planning artifacts.

## Existing Minimal Example

`example.json` remains in this directory as a simple early harness example. New measurement work should use the grouped directories and manifest-driven vocabulary introduced in this ticket.

Current grouped cases are still scaffold or planning cases. They exercise orchestration, defaults, overrides, and stimulus resolution, but they do not claim that final Blackhole reference states have already been captured.
