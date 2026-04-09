# OutSpread Reference States

`tests/reference_states` stores reusable Blackhole target-state definitions for future reference capture work.

## Purpose

Cases in `tests/cases` should point to reusable target-state IDs instead of copying the same parameter intent into every case file. This keeps capture intent stable and makes future Blackhole state capture easier to review and reuse.

## Discovery

The runner discovers reference-state files through `reference_state_manifest.json`.

- `reference_state_manifest.json` defines the schema and discovery rules.
- individual state files live in this directory as `*.json`
- the manifest file itself is not treated as a reusable state record

## State Shape

Each reusable state file should define:

- `id`
- `status`
- `description`
- `targetGroups`
- `sourceType`
- `referenceLock`
- `paramsByName`
- optional `paramsByIndex`
- `notes`

Prefer `paramsByName` as the source of truth. Use `paramsByIndex` only when compatibility requires it.

Captured states may also include an optional `capture` object that records the real reference-capture run backing the state, including plugin path, harness path, execution settings, and artifact paths.

## Status Values

Use the status field honestly:

- `planned`: the intended reusable state shape exists, but capture details are still high level
- `pending_capture`: the state intent is defined clearly enough for a future capture ticket, but exact reference values are not recorded yet
- `captured`: the exact Blackhole target state has been captured and documented with the relevant reference-lock details

Current files in this directory may still be planning or pending-capture scaffolds. They do not claim that real Blackhole state capture has already happened.

After Tickets 9, 10, and 11, the narrow baseline states linked to `smoke`, `attack`, `predelay`, `width`, `gravity`, `tail`, `tone_eq`, `modulation`, and `freeze_infinite` may be marked `captured` when they are backed by real Blackhole VST3 artifacts from the current `vst3_harness` workflow. That captured status is still compatible with empty `paramsByName` when normalized parameter extraction has not been recorded yet.

## Reference Lock

Each state file includes a `referenceLock` object with room for:

- plugin version
- platform and OS
- host or render path
- baseline sample rate
- baseline block size

Use null or empty values where exact capture information is not yet known. Do not invent fake version strings, fake hosts, or fake captured parameters.

## Execution Use

When the measurement runner plans or executes reference capture, each case resolves its `referenceStateId` through this directory and merges:

- reusable state parameters from the reference-state file
- any narrow case-local parameter overrides

The runner then writes a harness-ready `reference_case.json` into the per-case artifact folder.

Current state files may still be `planned` or `pending_capture`. Running execution against one of those states does not silently upgrade it to `captured`. The state file should only move to `captured` when a follow-up ticket records the exact Blackhole target values and the relevant reference-lock details honestly.

If a capture attempt is blocked because the installed plugin format does not match the current harness workflow, the linked state files stay `pending_capture`. Blocked execution artifacts should explain the limitation rather than promoting the state.

This also applies when the runner discovers candidate plugins through `--reference-search-root`: a found Blackhole VST2 `.dll` is still a real discovery result, but it remains blocked and does not promote linked states unless the active capture workflow can use that format.

## Reference Analysis

Captured state records can be turned into first-pass descriptive summaries with:

```powershell
py -3 scripts\analyze_reference_captures.py
```

The analysis script resolves source artifacts from each captured state's `capture` metadata first, then falls back to a deterministic scan of `artifacts/measurements/` only if needed. Outputs are written under `artifacts/reference_analysis/<timestamp>/`.

These summaries are intentionally narrower than final law extraction. They describe the current captured Blackhole artifacts with practical proxies such as onset timing, broad spectral balance, stereo relationship, envelope movement, and freeze/infinite drift. If a captured state is missing or its linked artifacts are broken, the analysis output marks that state unavailable instead of inventing results.
