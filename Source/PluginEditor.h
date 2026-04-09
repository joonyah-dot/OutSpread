#pragma once
#include <JuceHeader.h>
#include "PluginProcessor.h"

class OutSpreadAudioProcessorEditor : public juce::GenericAudioProcessorEditor
{
public:
    explicit OutSpreadAudioProcessorEditor (OutSpreadAudioProcessor&);
    ~OutSpreadAudioProcessorEditor() override = default;

private:
    JUCE_DECLARE_NON_COPYABLE_WITH_LEAK_DETECTOR (OutSpreadAudioProcessorEditor)
};
