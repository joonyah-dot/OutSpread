#include "PluginProcessor.h"
#include "PluginEditor.h"

namespace
{
float interpolateLinear (float startValue, float endValue, int index, int numSamples)
{
    if (numSamples <= 1)
        return endValue;

    const auto proportion = static_cast<float> (index) / static_cast<float> (numSamples - 1);
    return startValue + ((endValue - startValue) * proportion);
}
} // namespace

OutSpreadAudioProcessor::OutSpreadAudioProcessor()
    : AudioProcessor (BusesProperties()
        .withInput ("Input", juce::AudioChannelSet::stereo(), true)
        .withOutput ("Output", juce::AudioChannelSet::stereo(), true)),
      parameters (*this, nullptr, outspread::stateTreeId, outspread::createParameterLayout()),
      parameterState (parameters)
{
}

void OutSpreadAudioProcessor::prepareToPlay (double sampleRate, int samplesPerBlock)
{
    routedInputBuffer.setSize (2, samplesPerBlock, false, false, true);
    parameterState.prepare (sampleRate);
    wetEngine.prepare (sampleRate, samplesPerBlock, 2);
}

void OutSpreadAudioProcessor::releaseResources()
{
    routedInputBuffer.setSize (0, 0);
    wetEngine.releaseResources();
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

    if (routedInputBuffer.getNumChannels() != 2 || routedInputBuffer.getNumSamples() < numSamples)
        routedInputBuffer.setSize (2, numSamples, false, false, true);

    prepareRoutedInput (buffer, numSamples);

    const auto snapshot = parameterState.capture (numSamples);
    wetEngine.process (routedInputBuffer, snapshot);
    applyDryWetMix (buffer, snapshot);
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

    parameterState.reset();
    wetEngine.reset();
}

OutSpreadAudioProcessor::ParameterSnapshot OutSpreadAudioProcessor::getParameterSnapshot() const noexcept
{
    return parameterState.readCurrentValues();
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

void OutSpreadAudioProcessor::applyDryWetMix (juce::AudioBuffer<float>& buffer, const ParameterSnapshot& snapshot)
{
    const auto& wetBuffer = wetEngine.getWetBuffer();
    const auto numSamples = buffer.getNumSamples();

    for (int sample = 0; sample < numSamples; ++sample)
    {
        const auto wetMix = interpolateLinear (snapshot.mixWetStart, snapshot.mixWetEnd, sample, numSamples);
        const auto dryMix = 1.0f - wetMix;

        for (int channel = 0; channel < 2; ++channel)
        {
            const auto drySample = routedInputBuffer.getSample (channel, sample);
            const auto wetSample = wetBuffer.getSample (channel, sample);
            buffer.setSample (channel, sample, (drySample * dryMix) + (wetSample * wetMix));
        }
    }
}
