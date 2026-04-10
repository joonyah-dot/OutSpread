#pragma once

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
    juce::AudioBuffer<float> delayBuffer;
    double currentSampleRate = 0.0;
    int currentOutputChannels = 0;
    int maximumBlockSize = 0;
    int maximumDelaySamples = 0;
    int writePosition = 0;
};
} // namespace outspread
