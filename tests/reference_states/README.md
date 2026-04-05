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

## Status Values

Use the status field honestly:

- `planned`: the intended reusable state shape exists, but capture details are still high level
- `pending_capture`: the state intent is defined clearly enough for a future capture ticket, but exact reference values are not recorded yet
- `captured`: the exact Blackhole target state has been captured and documented with the relevant reference-lock details

Current files in this directory may still be planning or pending-capture scaffolds. They do not claim that real Blackhole state capture has already happened.

## Reference Lock

Each state file includes a `referenceLock` object with room for:

- plugin version
- platform and OS
- host or render path
- baseline sample rate
- baseline block size

Use null or empty values where exact capture information is not yet known. Do not invent fake version strings, fake hosts, or fake captured parameters.
