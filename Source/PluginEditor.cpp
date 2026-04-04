#include "PluginEditor.h"

OutSpreadAudioProcessorEditor::OutSpreadAudioProcessorEditor (OutSpreadAudioProcessor& p)
    : AudioProcessorEditor (&p), processor (p)
{
    setSize (420, 260);
}

void OutSpreadAudioProcessorEditor::paint (juce::Graphics& g)
{
    g.fillAll (juce::Colours::black);
    g.setColour (juce::Colours::white);
    g.setFont (20.0f);
    g.drawFittedText ("OutSpread", getLocalBounds(), juce::Justification::centred, 1);
}

void OutSpreadAudioProcessorEditor::resized() {}
