#include "PluginProcessor.h"
#include "PluginEditor.h"

__PLUGIN_NAME__AudioProcessor::__PLUGIN_NAME__AudioProcessor()
    : AudioProcessor (BusesProperties()
        .withInput  ("Input",  juce::AudioChannelSet::stereo(), true)
        .withOutput ("Output", juce::AudioChannelSet::stereo(), true))
{
}

void __PLUGIN_NAME__AudioProcessor::prepareToPlay (double, int) {}
void __PLUGIN_NAME__AudioProcessor::releaseResources() {}

bool __PLUGIN_NAME__AudioProcessor::isBusesLayoutSupported (const BusesLayout& layouts) const
{
    return layouts.getMainOutputChannelSet() == juce::AudioChannelSet::stereo();
}

void __PLUGIN_NAME__AudioProcessor::processBlock (juce::AudioBuffer<float>& buffer, juce::MidiBuffer&)
{
    juce::ScopedNoDenormals noDenormals;
    juce::ignoreUnused (buffer);
    // passthrough
}

juce::AudioProcessorEditor* __PLUGIN_NAME__AudioProcessor::createEditor()
{
    return new __PLUGIN_NAME__AudioProcessorEditor (*this);
}
