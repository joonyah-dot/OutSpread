#include "PluginProcessor.h"
#include "PluginEditor.h"

OutSpreadAudioProcessor::OutSpreadAudioProcessor()
    : AudioProcessor (BusesProperties()
        .withInput  ("Input",  juce::AudioChannelSet::stereo(), true)
        .withOutput ("Output", juce::AudioChannelSet::stereo(), true))
{
}

void OutSpreadAudioProcessor::prepareToPlay (double, int) {}
void OutSpreadAudioProcessor::releaseResources() {}

bool OutSpreadAudioProcessor::isBusesLayoutSupported (const BusesLayout& layouts) const
{
    return layouts.getMainOutputChannelSet() == juce::AudioChannelSet::stereo();
}

void OutSpreadAudioProcessor::processBlock (juce::AudioBuffer<float>& buffer, juce::MidiBuffer&)
{
    juce::ScopedNoDenormals noDenormals;
    juce::ignoreUnused (buffer);
    // passthrough
}

juce::AudioProcessorEditor* OutSpreadAudioProcessor::createEditor()
{
    return new OutSpreadAudioProcessorEditor (*this);
}
