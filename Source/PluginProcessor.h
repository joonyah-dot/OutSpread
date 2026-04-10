#pragma once
#include <JuceHeader.h>

#include "OutSpreadParameters.h"
#include "OutSpreadWetEngine.h"

class OutSpreadAudioProcessor : public juce::AudioProcessor
{
public:
    using ParameterSnapshot = outspread::ParameterSnapshot;

    OutSpreadAudioProcessor();
    ~OutSpreadAudioProcessor() override = default;

    void prepareToPlay (double sampleRate, int samplesPerBlock) override;
    void releaseResources() override;
    bool isBusesLayoutSupported (const BusesLayout& layouts) const override;
    void processBlock (juce::AudioBuffer<float>&, juce::MidiBuffer&) override;

    juce::AudioProcessorEditor* createEditor() override;
    bool hasEditor() const override { return true; }

    const juce::String getName() const override { return "OutSpread"; }
    bool acceptsMidi() const override { return false; }
    bool producesMidi() const override { return false; }
    bool isMidiEffect() const override { return false; }
    double getTailLengthSeconds() const override { return 0.0; }

    int getNumPrograms() override { return 1; }
    int getCurrentProgram() override { return 0; }
    void setCurrentProgram (int) override {}
    const juce::String getProgramName (int) override { return {}; }
    void changeProgramName (int, const juce::String&) override {}

    void getStateInformation (juce::MemoryBlock&) override;
    void setStateInformation (const void*, int) override;

    juce::AudioProcessorValueTreeState& getValueTreeState() noexcept { return parameters; }
    const juce::AudioProcessorValueTreeState& getValueTreeState() const noexcept { return parameters; }
    ParameterSnapshot getParameterSnapshot() const noexcept;

private:
    void prepareRoutedInput (juce::AudioBuffer<float>& buffer, int numSamples);
    void applyDryWetMix (juce::AudioBuffer<float>& buffer, const ParameterSnapshot& snapshot);

    juce::AudioProcessorValueTreeState parameters;
    outspread::ParameterState parameterState;
    outspread::WetEngine wetEngine;

    juce::AudioBuffer<float> routedInputBuffer;

    JUCE_DECLARE_NON_COPYABLE_WITH_LEAK_DETECTOR (OutSpreadAudioProcessor)
};
