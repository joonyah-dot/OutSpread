#include "PluginEditor.h"

__PLUGIN_NAME__AudioProcessorEditor::__PLUGIN_NAME__AudioProcessorEditor (__PLUGIN_NAME__AudioProcessor& p)
    : AudioProcessorEditor (&p), processor (p)
{
    setSize (420, 260);
}

void __PLUGIN_NAME__AudioProcessorEditor::paint (juce::Graphics& g)
{
    g.fillAll (juce::Colours::black);
    g.setColour (juce::Colours::white);
    g.setFont (20.0f);
    g.drawFittedText ("__PLUGIN_NAME__", getLocalBounds(), juce::Justification::centred, 1);
}

void __PLUGIN_NAME__AudioProcessorEditor::resized() {}
