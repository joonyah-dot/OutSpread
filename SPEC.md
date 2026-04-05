# OutSpread Specification

## Project Position

OutSpread is an independent VST3 reverb project. Its v1 target is a faithful black-box match of the current shipping Eventide Blackhole plugin behavior.

OutSpread must be an original implementation. The project must not copy or derive from Eventide source code, binaries, assets, presets, branding, UI layouts, or trade dress. The target is measured and audible behavior, not internal implementation or presentation.

## Reference Target

The reference product is the current shipping native Eventide Blackhole plugin used in the project measurement workflow.

The reference standard is the current shipping behavior, including current Freeze/Infinite behavior. OutSpread does not target a presumed legacy infinite mode, forum description, or memory of older releases. When assumptions disagree with the current shipping Blackhole result, the current shipping Blackhole result wins.

The exact baseline reference version, platform, render path assumptions, and baseline capture settings must be recorded in the Reference Lock section of `MEASUREMENT_PLAN.md`. Once baseline captures exist, the project stays locked to that documented baseline until the reference lock is deliberately updated.

## Primary Goal

The primary goal of OutSpread v1 is to reproduce the sound, control feel, and edge-case behavior of the current shipping Blackhole plugin closely enough that structured A/B comparison is difficult on the core measurement and listening set.

This goal includes:

- soft attack and bloom rather than immediate dense onset
- very large apparent space without collapsing into generic smear
- long tail density and tone evolution that stay in the Blackhole class
- bipolar Gravity behavior, including the negative-side reverse-like response
- Blackhole-like size and feedback interaction
- modulation that feels embedded in the tank rather than layered on top
- Freeze/Infinite behavior that matches the current shipping target

## Non-Goals

The following are out of scope for v1 unless added later as explicit post-parity work:

- shimmer or pitch-shifted reverb
- saturation, analog color, or drive stages
- convolution mode
- realistic room, plate, or spring simulation modes
- alternate "improved" voicings in the main signal path
- unrelated ambient effects beyond the Blackhole target
- copying the reference product's branding, presets, or visual presentation
- major GUI styling work before sound parity is established

## Product Scope

OutSpread v1 ships as a VST3 effect plugin.

OutSpread v1 must support:

- mono in -> stereo out
- stereo in -> stereo out
- automation
- state save and restore
- session recall
- sample-rate changes
- offline rendering
- stable bypass behavior
- deterministic behavior for identical renders where the reference is deterministic

Primary development is Windows-first, but portability must not become an excuse for drifting from the target.

## Sound-Critical Feature Set

The following control domains are sound-critical and must exist as functional equivalents before v1 can be considered complete:

- Mix
- Size
- Gravity
- Feedback
- Predelay
- Low tone
- High tone
- Resonance
- Mod Depth
- Mod Rate
- Freeze/Infinite
- Kill

Parameter names may differ for product reasons, but parameter behavior must remain reference-matched.

Kill intent for planning purposes is explicit even if final product naming changes. Kill is a wet-path control: it stops new signal from feeding the reverb tank and forces existing wet energy to clear or mute as quickly as the design allows, while leaving the dry path behavior unchanged. In mixed operation, dry signal must continue. In 100 percent wet operation, Kill should behave as an immediate reverb stop rather than a global output mute.

## Sound-Critical Behaviors

The following behaviors are sound-critical and must be matched, not approximated loosely:

- attack and bloom timing
- tail decay contour, density build, and spectral evolution
- predelay timing and its interaction with bloom
- Size scaling and feedback interaction
- bipolar Gravity response across negative, center, and positive settings
- low tone, high tone, and resonance behavior over the life of the tail
- stereo spread from mono material, with stable center behavior
- modulation rate, depth, and movement character
- Freeze/Infinite entry, sustain, exit, and new-input handling
- stability under long renders, high feedback, automation, and host condition changes

## Workflow and Product Features

Workflow and product features matter, but they are secondary to sound parity. They must not justify sound drift or delay sound-critical milestones.

These features are expected after core parity is established:

- parameter text and units
- preset workflow
- mix-lock equivalent if the product includes it
- macro or performance control equivalents if the product includes them
- alternate-state or hot-switch equivalents if the product includes them
- practical production GUI
- polished defaults and factory presets

## Architecture Constraints

The DSP architecture is implementation-defined, but it must be chosen by measured and audible similarity to the reference rather than by elegance, novelty, or theoretical preference.

High-level architecture constraints:

- original DSP only; no copied Eventide implementation details
- architecture may use diffusion, recirculating allpass, FDN, or hybrid approaches if they serve parity
- parameter semantics must be stable enough for repeatable measurement and tuning
- the design must support future scripted measurement runs using `tests/cases`, generated stimuli, and timestamped artifacts
- the core must stay stable under high feedback, long tails, Freeze/Infinite, automation sweeps, sample-rate changes, and block-size changes
- CPU use must be practical for real sessions, but obvious sonic mismatch is a higher priority than early micro-optimization

## Non-Drift Rules

The project must not drift from the following rules:

1. Reference first. The current shipping Blackhole plugin is the source of truth.
2. Sound-critical work comes before workflow features, and workflow features come before cosmetics.
3. No feature creep. Do not add unrelated modes or effects to v1.
4. No hidden redesign. Do not replace the target with a "better" interpretation.
5. No IP copying. Do not copy Eventide code, assets, presets, branding, UI art, or trade dress.
6. Parameter semantics do not change casually once measured and documented.
7. Every sound-affecting change requires measurement artifacts and reviewable summaries.
8. Every Codex ticket must be narrow, explicit about allowed and forbidden files, and reviewable in isolation.
9. Acceptance logic and thresholds do not change silently; doc updates are required when they move.

## Project Phases

OutSpread is expected to progress through these phases:

- M0: governance and planning
- M1: reference capture harness
- M2: shell plugin
- M3: parameter law extraction
- M4: algorithm prototype bake-off
- M5: core parity tuning
- M6: freeze/infinite stability parity
- M7: stereo image and modulation polish
- M8: workflow/product feature completion
- M9: release hardening

Detailed milestone tasks and exit criteria live in `TASKS.md`.

## Definition of Done

OutSpread v1 is done only when all of the following are true:

- the measurement workflow is implemented, repeatable, and anchored to the current shipping Blackhole reference
- the core case groups in `MEASUREMENT_PLAN.md` meet their initial acceptance thresholds or have documented, review-approved exceptions
- attack, tail, gravity, size, tone/eq, modulation, width, predelay, and freeze/infinite behavior are in the same class as the reference in both measurements and listening
- the plugin is stable in normal host use, offline rendering, and long-run stress cases
- parameter behavior feels reference-matched across the usable range
- blind or near-blind A/B comparison is difficult on the core evaluation set
- workflow and product features needed for a real v1 release are complete without regressing sound parity
- the repo contains the documentation and measurement artifacts needed to maintain parity over time

## Acceptance Standard

The acceptance standard for OutSpread is not "sounds good."

The acceptance standard is black-box parity with the current shipping Blackhole target, supported by both measurement evidence and listening evidence.
