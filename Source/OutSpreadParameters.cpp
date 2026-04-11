#include "OutSpreadParameters.h"

namespace
{
std::unique_ptr<juce::RangedAudioParameter> createFloatParameter (
    const juce::String& parameterId,
    const juce::String& name,
    juce::NormalisableRange<float> range,
    float defaultValue)
{
    return std::make_unique<juce::AudioParameterFloat> (
        juce::ParameterID { parameterId, 1 },
        name,
        range,
        defaultValue
    );
}

float interpolateSmoothingTarget (
    juce::SmoothedValue<float, juce::ValueSmoothingTypes::Linear>& smoothedValue,
    float targetValue,
    int numSamples)
{
    smoothedValue.setTargetValue (targetValue);
    if (numSamples <= 0)
        return smoothedValue.getCurrentValue();
    return smoothedValue.skip (numSamples);
}
} // namespace

namespace outspread
{
juce::AudioProcessorValueTreeState::ParameterLayout createParameterLayout()
{
    juce::AudioProcessorValueTreeState::ParameterLayout layout;

    layout.add (createFloatParameter (parameter_ids::mix, "Mix", { 0.0f, 100.0f, 0.01f }, 0.0f));
    layout.add (createFloatParameter (parameter_ids::size, "Size", { 0.0f, 100.0f, 0.01f }, 50.0f));
    layout.add (createFloatParameter (parameter_ids::gravity, "Gravity", { -100.0f, 100.0f, 0.01f }, 0.0f));
    layout.add (createFloatParameter (parameter_ids::feedback, "Feedback", { 0.0f, 100.0f, 0.01f }, 50.0f));
    layout.add (createFloatParameter (parameter_ids::predelay, "Predelay", { 0.0f, 500.0f, 0.01f }, 0.0f));
    layout.add (createFloatParameter (parameter_ids::lowTone, "Low Tone", { -100.0f, 100.0f, 0.01f }, 0.0f));
    layout.add (createFloatParameter (parameter_ids::highTone, "High Tone", { -100.0f, 100.0f, 0.01f }, 0.0f));
    layout.add (createFloatParameter (parameter_ids::resonance, "Resonance", { 0.0f, 100.0f, 0.01f }, 0.0f));
    layout.add (createFloatParameter (parameter_ids::modDepth, "Mod Depth", { 0.0f, 100.0f, 0.01f }, 0.0f));
    layout.add (createFloatParameter (parameter_ids::modRate, "Mod Rate", { 0.05f, 10.0f, 0.01f }, 1.0f));
    layout.add (std::make_unique<juce::AudioParameterBool> (
        juce::ParameterID { parameter_ids::freezeInfinite, 1 },
        "Freeze / Infinite",
        false
    ));
    layout.add (std::make_unique<juce::AudioParameterBool> (
        juce::ParameterID { parameter_ids::kill, 1 },
        "Kill",
        false
    ));

    return layout;
}

ParameterState::ParameterState (juce::AudioProcessorValueTreeState& stateToBind)
    : state (stateToBind)
{
    mixParameter = state.getRawParameterValue (parameter_ids::mix);
    sizeParameter = state.getRawParameterValue (parameter_ids::size);
    gravityParameter = state.getRawParameterValue (parameter_ids::gravity);
    feedbackParameter = state.getRawParameterValue (parameter_ids::feedback);
    predelayParameter = state.getRawParameterValue (parameter_ids::predelay);
    lowToneParameter = state.getRawParameterValue (parameter_ids::lowTone);
    highToneParameter = state.getRawParameterValue (parameter_ids::highTone);
    resonanceParameter = state.getRawParameterValue (parameter_ids::resonance);
    modDepthParameter = state.getRawParameterValue (parameter_ids::modDepth);
    modRateParameter = state.getRawParameterValue (parameter_ids::modRate);
    freezeInfiniteParameter = state.getRawParameterValue (parameter_ids::freezeInfinite);
    killParameter = state.getRawParameterValue (parameter_ids::kill);
}

void ParameterState::prepare (double sampleRate)
{
    mixWetSmoothed.reset (sampleRate, 0.02);
    killWetGainSmoothed.reset (sampleRate, 0.002);
    predelayMsSmoothed.reset (sampleRate, 0.02);
    feedbackSmoothed.reset (sampleRate, 0.02);
    reset();
}

void ParameterState::reset()
{
    const auto snapshot = readCurrentValues();
    mixWetSmoothed.setCurrentAndTargetValue (juce::jlimit (0.0f, 1.0f, snapshot.mix / 100.0f));
    killWetGainSmoothed.setCurrentAndTargetValue (snapshot.kill ? 0.0f : 1.0f);
    predelayMsSmoothed.setCurrentAndTargetValue (juce::jlimit (0.0f, 500.0f, snapshot.predelayMs));
    feedbackSmoothed.setCurrentAndTargetValue (juce::jlimit (0.0f, 1.0f, snapshot.feedback / 100.0f));
}

ParameterSnapshot ParameterState::readCurrentValues() const noexcept
{
    ParameterSnapshot snapshot;
    snapshot.mix = loadValue (mixParameter, snapshot.mix);
    snapshot.size = loadValue (sizeParameter, snapshot.size);
    snapshot.gravity = loadValue (gravityParameter, snapshot.gravity);
    snapshot.feedback = loadValue (feedbackParameter, snapshot.feedback);
    snapshot.predelayMs = loadValue (predelayParameter, snapshot.predelayMs);
    snapshot.lowTone = loadValue (lowToneParameter, snapshot.lowTone);
    snapshot.highTone = loadValue (highToneParameter, snapshot.highTone);
    snapshot.resonance = loadValue (resonanceParameter, snapshot.resonance);
    snapshot.modDepth = loadValue (modDepthParameter, snapshot.modDepth);
    snapshot.modRateHz = loadValue (modRateParameter, snapshot.modRateHz);
    snapshot.freezeInfinite = loadValue (freezeInfiniteParameter, 0.0f) >= 0.5f;
    snapshot.kill = loadValue (killParameter, 0.0f) >= 0.5f;
    return snapshot;
}

ParameterSnapshot ParameterState::capture (int numSamples) noexcept
{
    auto snapshot = readCurrentValues();

    snapshot.mixWetStart = mixWetSmoothed.getCurrentValue();
    snapshot.mixWetEnd = interpolateSmoothingTarget (
        mixWetSmoothed,
        juce::jlimit (0.0f, 1.0f, snapshot.mix / 100.0f),
        numSamples
    );
    snapshot.mixDryStart = 1.0f - snapshot.mixWetStart;
    snapshot.mixDryEnd = 1.0f - snapshot.mixWetEnd;

    snapshot.killWetGainStart = killWetGainSmoothed.getCurrentValue();
    snapshot.killWetGainEnd = interpolateSmoothingTarget (
        killWetGainSmoothed,
        snapshot.kill ? 0.0f : 1.0f,
        numSamples
    );

    snapshot.predelayMsStart = predelayMsSmoothed.getCurrentValue();
    snapshot.predelayMsEnd = interpolateSmoothingTarget (
        predelayMsSmoothed,
        juce::jlimit (0.0f, 500.0f, snapshot.predelayMs),
        numSamples
    );
    snapshot.feedbackNormalizedStart = feedbackSmoothed.getCurrentValue();
    snapshot.feedbackNormalizedEnd = interpolateSmoothingTarget (
        feedbackSmoothed,
        juce::jlimit (0.0f, 1.0f, snapshot.feedback / 100.0f),
        numSamples
    );
    snapshot.feedbackNormalizedSmoothed = snapshot.feedbackNormalizedEnd;

    return snapshot;
}

float ParameterState::loadValue (const std::atomic<float>* parameter, float fallback) noexcept
{
    return parameter != nullptr ? parameter->load() : fallback;
}
} // namespace outspread
