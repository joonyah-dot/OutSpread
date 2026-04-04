#pragma once
#include <JuceHeader.h>
#include "PluginProcessor.h"

class OutSpreadAudioProcessorEditor : public juce::AudioProcessorEditor
{
public:
    explicit OutSpreadAudioProcessorEditor (OutSpreadAudioProcessor&);
    ~OutSpreadAudioProcessorEditor() override = default;

    void paint (juce::Graphics&) override;
    void resized() override;

private:
    OutSpreadAudioProcessor& processor;
    JUCE_DECLARE_NON_COPYABLE_WITH_LEAK_DETECTOR (OutSpreadAudioProcessorEditor)
};
