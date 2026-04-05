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
