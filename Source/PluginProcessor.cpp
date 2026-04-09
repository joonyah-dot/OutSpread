#include "PluginProcessor.h"
#include "PluginEditor.h"

namespace
{
constexpr auto stateTreeId = "outspread_state";
constexpr auto mixId = "mix";
constexpr auto sizeId = "size";
constexpr auto gravityId = "gravity";
constexpr auto feedbackId = "feedback";
constexpr auto predelayId = "predelay";
constexpr auto lowToneId = "low_tone";
constexpr auto highToneId = "high_tone";
constexpr auto resonanceId = "resonance";
constexpr auto modDepthId = "mod_depth";
constexpr auto modRateId = "mod_rate";
constexpr auto freezeInfiniteId = "freeze_infinite";
constexpr auto killId = "kill";
} // namespace

OutSpreadAudioProcessor::OutSpreadAudioProcessor()
    : AudioProcessor (BusesProperties()
        .withInput ("Input", juce::AudioChannelSet::stereo(), true)
        .withOutput ("Output", juce::AudioChannelSet::stereo(), true)),
      parameters (*this, nullptr, stateTreeId, createParameterLayout())
{
    initializeParameterPointers();
}

void OutSpreadAudioProcessor::prepareToPlay (double sampleRate, int samplesPerBlock)
{
    routedInputBuffer.setSize (2, samplesPerBlock, false, false, true);
    wetBuffer.setSize (2, samplesPerBlock, false, false, true);
    mixSmoothed.reset (sampleRate, 0.02);
    mixSmoothed.setCurrentAndTargetValue (juce::jlimit (0.0f, 1.0f, getParameterSnapshot().mix / 100.0f));
}

void OutSpreadAudioProcessor::releaseResources()
{
    routedInputBuffer.setSize (0, 0);
    wetBuffer.setSize (0, 0);
}

bool OutSpreadAudioProcessor::isBusesLayoutSupported (const BusesLayout& layouts) const
{
    const auto& mainInput = layouts.getMainInputChannelSet();
    const auto& mainOutput = layouts.getMainOutputChannelSet();

    if (mainOutput != juce::AudioChannelSet::stereo())
        return false;

    return mainInput == juce::AudioChannelSet::mono()
        || mainInput == juce::AudioChannelSet::stereo();
}

void OutSpreadAudioProcessor::processBlock (juce::AudioBuffer<float>& buffer, juce::MidiBuffer& midiMessages)
{
    juce::ScopedNoDenormals noDenormals;
    juce::ignoreUnused (midiMessages);

    const auto totalNumInputChannels = getTotalNumInputChannels();
    const auto totalNumOutputChannels = getTotalNumOutputChannels();
    const auto numSamples = buffer.getNumSamples();

    if (numSamples == 0)
        return;

    for (auto channel = totalNumInputChannels; channel < totalNumOutputChannels; ++channel)
        buffer.clear (channel, 0, numSamples);

    routedInputBuffer.setSize (2, numSamples, false, false, true);
    wetBuffer.setSize (2, numSamples, false, false, true);

    prepareRoutedInput (buffer, numSamples);
    populateWetBufferFromShellInput();

    const auto snapshot = getParameterSnapshot();
    mixSmoothed.setTargetValue (juce::jlimit (0.0f, 1.0f, snapshot.mix / 100.0f));

    if (snapshot.kill)
        wetBuffer.clear();

    for (auto sample = 0; sample < numSamples; ++sample)
    {
        const auto wetMix = mixSmoothed.getNextValue();
        const auto dryMix = 1.0f - wetMix;

        for (auto channel = 0; channel < 2; ++channel)
        {
            const auto drySample = routedInputBuffer.getSample (channel, sample);
            const auto wetSample = wetBuffer.getSample (channel, sample);
            buffer.setSample (channel, sample, (drySample * dryMix) + (wetSample * wetMix));
        }
    }
}

juce::AudioProcessorEditor* OutSpreadAudioProcessor::createEditor()
{
    return new OutSpreadAudioProcessorEditor (*this);
}

void OutSpreadAudioProcessor::getStateInformation (juce::MemoryBlock& destinationData)
{
    if (auto stateXml = parameters.copyState().createXml())
        copyXmlToBinary (*stateXml, destinationData);
}

void OutSpreadAudioProcessor::setStateInformation (const void* data, int sizeInBytes)
{
    if (auto stateXml = getXmlFromBinary (data, sizeInBytes))
    {
        if (stateXml->hasTagName (parameters.state.getType()))
            parameters.replaceState (juce::ValueTree::fromXml (*stateXml));
    }

    mixSmoothed.setCurrentAndTargetValue (juce::jlimit (0.0f, 1.0f, getParameterSnapshot().mix / 100.0f));
}

OutSpreadAudioProcessor::ParameterSnapshot OutSpreadAudioProcessor::getParameterSnapshot() const noexcept
{
    auto load = [] (const std::atomic<float>* parameter, float fallback) noexcept
    {
        return parameter != nullptr ? parameter->load() : fallback;
    };

    ParameterSnapshot snapshot;
    snapshot.mix = load (mixParameter, snapshot.mix);
    snapshot.size = load (sizeParameter, snapshot.size);
    snapshot.gravity = load (gravityParameter, snapshot.gravity);
    snapshot.feedback = load (feedbackParameter, snapshot.feedback);
    snapshot.predelayMs = load (predelayParameter, snapshot.predelayMs);
    snapshot.lowTone = load (lowToneParameter, snapshot.lowTone);
    snapshot.highTone = load (highToneParameter, snapshot.highTone);
    snapshot.resonance = load (resonanceParameter, snapshot.resonance);
    snapshot.modDepth = load (modDepthParameter, snapshot.modDepth);
    snapshot.modRateHz = load (modRateParameter, snapshot.modRateHz);
    snapshot.freezeInfinite = load (freezeInfiniteParameter, 0.0f) >= 0.5f;
    snapshot.kill = load (killParameter, 0.0f) >= 0.5f;
    return snapshot;
}

juce::AudioProcessorValueTreeState::ParameterLayout OutSpreadAudioProcessor::createParameterLayout()
{
    juce::AudioProcessorValueTreeState::ParameterLayout layout;

    layout.add (createFloatParameter (mixId, "Mix", { 0.0f, 100.0f, 0.01f }, 0.0f));
    layout.add (createFloatParameter (sizeId, "Size", { 0.0f, 100.0f, 0.01f }, 50.0f));
    layout.add (createFloatParameter (gravityId, "Gravity", { -100.0f, 100.0f, 0.01f }, 0.0f));
    layout.add (createFloatParameter (feedbackId, "Feedback", { 0.0f, 100.0f, 0.01f }, 50.0f));
    layout.add (createFloatParameter (predelayId, "Predelay", { 0.0f, 500.0f, 0.01f }, 0.0f));
    layout.add (createFloatParameter (lowToneId, "Low Tone", { -100.0f, 100.0f, 0.01f }, 0.0f));
    layout.add (createFloatParameter (highToneId, "High Tone", { -100.0f, 100.0f, 0.01f }, 0.0f));
    layout.add (createFloatParameter (resonanceId, "Resonance", { 0.0f, 100.0f, 0.01f }, 0.0f));
    layout.add (createFloatParameter (modDepthId, "Mod Depth", { 0.0f, 100.0f, 0.01f }, 0.0f));
    layout.add (createFloatParameter (modRateId, "Mod Rate", { 0.05f, 10.0f, 0.01f }, 1.0f));
    layout.add (std::make_unique<juce::AudioParameterBool> (juce::ParameterID { freezeInfiniteId, 1 }, "Freeze / Infinite", false));
    layout.add (std::make_unique<juce::AudioParameterBool> (juce::ParameterID { killId, 1 }, "Kill", false));

    return layout;
}

std::unique_ptr<juce::RangedAudioParameter> OutSpreadAudioProcessor::createFloatParameter (
    const juce::String& parameterId,
    const juce::String& name,
    juce::NormalisableRange<float> range,
    float defaultValue)
{
    return std::make_unique<juce::AudioParameterFloat> (juce::ParameterID { parameterId, 1 }, name, range, defaultValue);
}

void OutSpreadAudioProcessor::initializeParameterPointers()
{
    mixParameter = parameters.getRawParameterValue (mixId);
    sizeParameter = parameters.getRawParameterValue (sizeId);
    gravityParameter = parameters.getRawParameterValue (gravityId);
    feedbackParameter = parameters.getRawParameterValue (feedbackId);
    predelayParameter = parameters.getRawParameterValue (predelayId);
    lowToneParameter = parameters.getRawParameterValue (lowToneId);
    highToneParameter = parameters.getRawParameterValue (highToneId);
    resonanceParameter = parameters.getRawParameterValue (resonanceId);
    modDepthParameter = parameters.getRawParameterValue (modDepthId);
    modRateParameter = parameters.getRawParameterValue (modRateId);
    freezeInfiniteParameter = parameters.getRawParameterValue (freezeInfiniteId);
    killParameter = parameters.getRawParameterValue (killId);
}

void OutSpreadAudioProcessor::prepareRoutedInput (juce::AudioBuffer<float>& buffer, int numSamples)
{
    routedInputBuffer.clear();

    const auto inputChannels = getTotalNumInputChannels();
    if (inputChannels <= 0)
        return;

    auto* leftOutput = routedInputBuffer.getWritePointer (0);
    auto* rightOutput = routedInputBuffer.getWritePointer (1);
    const auto* leftInput = buffer.getReadPointer (0);

    juce::FloatVectorOperations::copy (leftOutput, leftInput, numSamples);

    if (inputChannels == 1)
    {
        juce::FloatVectorOperations::copy (rightOutput, leftInput, numSamples);
        return;
    }

    const auto* rightInput = buffer.getReadPointer (1);
    juce::FloatVectorOperations::copy (rightOutput, rightInput, numSamples);
}

void OutSpreadAudioProcessor::populateWetBufferFromShellInput()
{
    wetBuffer.makeCopyOf (routedInputBuffer, true);

    // The shell intentionally mirrors routed input into the wet path so later DSP tickets
    // can replace this population step without first undoing placeholder ambience code.
}
