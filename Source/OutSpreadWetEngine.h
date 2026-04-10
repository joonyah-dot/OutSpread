#pragma once

#include <array>

#include <JuceHeader.h>

#include "OutSpreadParameters.h"

namespace outspread
{
class WetEngine
{
public:
    void prepare (double sampleRate, int maximumBlockSize, int outputChannels);
    void releaseResources();
    void reset();

    void process (const juce::AudioBuffer<float>& routedInput, const ParameterSnapshot& parameters);

    const juce::AudioBuffer<float>& getWetBuffer() const noexcept { return wetBuffer; }

private:
    juce::AudioBuffer<float> wetBuffer;
    juce::AudioBuffer<float> predelayBuffer;
    juce::AudioBuffer<float> diffusionBuffer;
    double currentSampleRate = 0.0;
    int currentOutputChannels = 0;
    int maximumBlockSize = 0;
    int maximumPredelaySamples = 0;
    int maximumDiffusionSamples = 0;
    int predelayWritePosition = 0;
    int diffusionWritePosition = 0;
    std::array<int, 4> diffusionTapSamples { 0, 0, 0, 0 };
};
} // namespace outspread
