#include "OutSpreadWetEngine.h"

namespace
{
float interpolateLinear (float startValue, float endValue, int index, int numSamples)
{
    if (numSamples <= 1)
        return endValue;

    const auto proportion = static_cast<float> (index) / static_cast<float> (numSamples - 1);
    return startValue + ((endValue - startValue) * proportion);
}
} // namespace

namespace outspread
{
void WetEngine::prepare (double sampleRate, int maximumBlockSize, int outputChannels)
{
    currentSampleRate = sampleRate;
    currentOutputChannels = outputChannels;
    wetBuffer.setSize (outputChannels, maximumBlockSize, false, false, true);
    wetBuffer.clear();
}

void WetEngine::releaseResources()
{
    wetBuffer.setSize (0, 0);
    currentSampleRate = 0.0;
    currentOutputChannels = 0;
}

void WetEngine::reset()
{
    wetBuffer.clear();
}

void WetEngine::process (const juce::AudioBuffer<float>& routedInput, const ParameterSnapshot& parameters)
{
    const auto numSamples = routedInput.getNumSamples();
    const auto numInputChannels = routedInput.getNumChannels();
    const auto outputChannels = std::max (currentOutputChannels, numInputChannels);

    wetBuffer.setSize (outputChannels, numSamples, false, false, true);
    wetBuffer.clear();

    for (int channel = 0; channel < outputChannels; ++channel)
    {
        const auto sourceChannel = std::min (channel, numInputChannels - 1);
        wetBuffer.copyFrom (channel, 0, routedInput, sourceChannel, 0, numSamples);
    }

    if (parameters.killWetGainStart == 1.0f && parameters.killWetGainEnd == 1.0f)
        return;

    if (parameters.killWetGainStart == 0.0f && parameters.killWetGainEnd == 0.0f)
    {
        wetBuffer.clear();
        return;
    }

    for (int sample = 0; sample < numSamples; ++sample)
    {
        const auto wetGain = interpolateLinear (
            parameters.killWetGainStart,
            parameters.killWetGainEnd,
            sample,
            numSamples
        );

        for (int channel = 0; channel < outputChannels; ++channel)
            wetBuffer.setSample (channel, sample, wetBuffer.getSample (channel, sample) * wetGain);
    }

    juce::ignoreUnused (currentSampleRate, parameters.predelayMsSmoothed, parameters.feedbackNormalizedSmoothed);
    // The shell wet engine still mirrors routed input directly. The smoothed predelay and
    // feedback values are captured here so later algorithm tickets can add real wet-path
    // behavior without rebuilding the parameter plumbing boundary first.
}
} // namespace outspread
