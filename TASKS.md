# OutSpread Tasks

This file breaks OutSpread into milestone-based work from planning through release hardening. Each milestone is intended to be split into narrow, reviewable Codex tickets.

## Operating Rules

- One ticket should have one focused objective.
- Every ticket must state allowed files and forbidden files before implementation starts.
- Do not mix DSP work, workflow work, GUI work, and cleanup work unless the ticket explicitly requires it.
- Do not do opportunistic refactors, repo restructuring, or naming cleanups unless the ticket explicitly authorizes them.
- Every sound-affecting ticket must produce measurement artifacts under `artifacts/measurements/<timestamp>/` or state clearly why no sound path changed.
- Every sound-affecting ticket must state which case groups were run and which summary files were reviewed.
- Every milestone exit criterion must be objective enough for human review and future automation.
- If parameter semantics, case names, or acceptance logic change, update the planning docs in the same ticket or an immediately paired doc ticket.

## M0 - Governance and Planning

### Goal

Lock the project contract, milestone map, and measurement vocabulary before implementation drifts.

### Concrete Tasks

- Create and maintain `SPEC.md`, `TASKS.md`, and `MEASUREMENT_PLAN.md` as the authoritative planning set.
- Lock the reference language: current shipping Blackhole, black-box match, sound-critical, tone/eq, freeze/infinite, sample-rate/block-size, and cpu/latency.
- Document non-goals and non-drift rules so later tickets cannot justify feature creep.
- Define the operating rules for narrow Codex tickets and artifact-required sound changes.

### Exit Criteria

- The three planning docs exist at repo root and agree with each other.
- The project target is clearly the current shipping Eventide Blackhole behavior, not a generic ambient reverb goal.
- Future tickets can reference the docs directly without inventing new milestone or case-group vocabulary.

## M1 - Reference Capture Harness

### Goal

Create a repeatable scripted path to render the current shipping Blackhole reference and store comparable artifacts.

### Concrete Tasks

- Audit the current harness entrypoints and case manifest shape already present in the repo.
- Define the OutSpread case schema under `tests/cases` so future tickets can add grouped cases without inventing new structure.
- Define generated stimulus handling under `tests/_generated`.
- Define the timestamped artifact layout under `artifacts/measurements/<timestamp>/`.
- Add scripted reference renders for the current shipping Blackhole VST3 at baseline settings.
- Add initial grouped cases for smoke, attack, tail, gravity, size, tone/eq, modulation, width, freeze/infinite, predelay, sample-rate/block-size, and cpu/latency.
- Emit the required rollups: `attack_summary.json`, `tail_summary.json`, `gravity_summary.json`, `width_summary.json`, `modulation_summary.json`, `freeze_summary.json`, `predelay_summary.json`, `sample_rate_summary.json`, `cpu_latency_summary.json`, and `summary.json`.

### Exit Criteria

- One scripted run can render the reference suite at baseline settings.
- Artifacts land in a stable timestamped folder with the required rollup files.
- Case names, group names, and case schema are stable enough to support future automated comparison.

## M2 - Shell Plugin

### Goal

Build a stable OutSpread VST3 shell with the intended routing and parameter surface before deep DSP tuning.

### Concrete Tasks

- Ensure the plugin builds and loads as a VST3 effect in the supported host workflow.
- Implement mono in -> stereo out and stereo in -> stereo out routing.
- Add the sound-critical parameter set defined in `SPEC.md`.
- Add automation-safe parameter updates, smoothing, and state save/restore.
- Add wet/dry handling, basic bypass behavior, and any shell-level predelay plumbing needed for later parity work.
- Add smoke cases that confirm build, load, render, parameter recall, and reset behavior.

### Exit Criteria

- The plugin builds, loads, and renders reliably in the harness and target host workflow.
- Parameters exist, serialize correctly, and survive basic automation and recall tests.
- Smoke cases pass without major clicks, denormals, crashes, or obvious lifecycle bugs.

## M3 - Parameter Law Extraction

### Goal

Measure and lock the control laws of the reference plugin before final DSP tuning.

### Concrete Tasks

- Measure Mix law.
- Measure Size law.
- Measure Gravity law across negative, center, and positive settings.
- Measure Feedback progression.
- Measure Predelay timing law.
- Measure low tone, high tone, and resonance behavior.
- Measure Mod Depth and Mod Rate laws.
- Measure Freeze/Infinite and Kill control semantics where they affect sound or transitions.
- Document the normalized target laws and control semantics to be implemented in OutSpread.

### Exit Criteria

- Parameter sweeps show reference-like transitions across the measured ranges.
- The project has a documented target for each sound-critical control law.
- Parameter semantics are stable enough that later tuning work is not guessing.

## M4 - Algorithm Prototype Bake-Off

### Goal

Compare candidate internal architectures and select the one that best matches the reference.

### Concrete Tasks

- Build at least two credible prototype cores behind the same external parameter surface.
- Run each prototype against the same attack, tail, gravity, size, tone/eq, modulation, width, and freeze/infinite cases.
- Compare bloom timing, density, tone evolution, spatial field, modulation feel, and long-tail behavior using the measurement artifacts.
- Record the reasons for selecting a shipping direction and isolate or retire non-selected prototypes.

### Exit Criteria

- One architecture is clearly selected for shipping work.
- The selection is justified by measurement and listening evidence, not preference alone.
- The project is no longer architecture-shopping on the critical path.

## M5 - Core Parity Tuning

### Goal

Tune the selected architecture until it matches the reference across the core case matrix.

### Concrete Tasks

- Tune attack and bloom timing.
- Tune tail decay contour, density build, and tone evolution.
- Tune Size behavior and its interaction with feedback.
- Tune Gravity behavior across the full bipolar range.
- Tune tone/eq behavior, including low tone, high tone, and resonance.
- Tune predelay interaction with the onset of the wet field.
- Use the attack, tail, gravity, size, tone/eq, and predelay summaries as the main review surface.
- Require artifact bundles for every sound-affecting tuning ticket.

### Exit Criteria

- Core cases no longer sound or measure like the wrong class of reverb.
- Remaining differences are secondary polish issues rather than structural mismatch.
- The main summary files show progress toward threshold-level parity instead of broad misses.

## M6 - Freeze/Infinite Stability Parity

### Goal

Match the current shipping Freeze/Infinite behavior without instability or hidden divergence.

### Concrete Tasks

- Implement or refine Freeze/Infinite behavior against the current shipping Blackhole target.
- Run long-render cases that measure sustain, drift, clipping, and failure states.
- Measure new-input handling while Freeze/Infinite is engaged.
- Measure transition behavior when entering and leaving the mode.
- Confirm that the target remains the current shipping behavior, not a presumed legacy infinite mode.

### Exit Criteria

- Long renders remain stable with no runaway behavior, NaN, or Inf failures.
- `freeze_summary.json` shows behavior in the same class as the reference.
- Freeze/Infinite no longer behaves like a placeholder approximation.

## M7 - Stereo Image and Modulation Polish

### Goal

Refine stereo image and motion until OutSpread feels convincingly Blackhole-like in width and movement.

### Concrete Tasks

- Tune mono-to-stereo spread and stereo decorrelation.
- Tune center stability and mono compatibility.
- Tune side-energy growth and image persistence over the tail.
- Tune modulation rate and depth feel using the modulation case group.
- Remove chorus-like artifacts that sit on top of the tail instead of living inside it.
- Confirm behavior on transient, pluck, pad, and stereo source material.

### Exit Criteria

- `width_summary.json` and `modulation_summary.json` are in-family with the reference.
- The image feels expansive but stable, and modulation feels integrated rather than pasted on.
- Width and movement hold up on both mono and stereo sources.

## M8 - Workflow/Product Feature Completion

### Goal

Add the non-core features required for a usable v1 product without breaking sound parity.

### Concrete Tasks

- Finalize parameter text and units.
- Implement clean Kill behavior.
- Implement preset save/restore and practical preset workflow.
- Implement any chosen performance macro, morph, alternate-state, or mix-lock equivalents.
- Refine the GUI enough for practical use while keeping it visually independent from the reference product.
- Create default settings and factory presets that represent the shipping sound.
- Re-run core sound cases after every workflow feature that can affect audio behavior.

### Exit Criteria

- The plugin is usable as a real product rather than only a DSP test shell.
- Workflow features do not regress the sound-critical summaries.
- The product surface is complete enough for external evaluation.

## M9 - Release Hardening

### Goal

Prove that the plugin is stable, recall-safe, and practical in real session use.

### Concrete Tasks

- Run the full sample-rate/block-size matrix at 44.1, 48, 88.2, and 96 kHz.
- Run the full sample-rate/block-size matrix at 64, 128, 256, 512, and 1024 samples.
- Test offline rendering, automation stress, preset recall, and multiple-instance sessions.
- Measure and document cpu/latency behavior.
- Run long soak sessions with aggressive parameter movement and long tails.
- Run final listening comparisons and blind or near-blind A/B checks on the core case matrix.

### Exit Criteria

- No major stability, recall, or host integration issues remain.
- Sample-rate/block-size and cpu/latency results are documented and acceptable for release.
- Final listening and measurement review support a credible v1 release decision.
