#pragma once
#include <JuceHeader.h>
#include "PluginProcessor.h"

class __PLUGIN_NAME__AudioProcessorEditor : public juce::AudioProcessorEditor
{
public:
    explicit __PLUGIN_NAME__AudioProcessorEditor (__PLUGIN_NAME__AudioProcessor&);
    ~__PLUGIN_NAME__AudioProcessorEditor() override = default;

    void paint (juce::Graphics&) override;
    void resized() override;

private:
    __PLUGIN_NAME__AudioProcessor& processor;
    JUCE_DECLARE_NON_COPYABLE_WITH_LEAK_DETECTOR (__PLUGIN_NAME__AudioProcessorEditor)
};
