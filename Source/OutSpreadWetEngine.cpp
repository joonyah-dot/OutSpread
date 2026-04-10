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

float wrapReadPosition (float position, int delayBufferLength)
{
    while (position < 0.0f)
        position += static_cast<float> (delayBufferLength);

    while (position >= static_cast<float> (delayBufferLength))
        position -= static_cast<float> (delayBufferLength);

    return position;
}

float readDelayedSample (const float* delayChannelData, int delayBufferLength, float readPosition)
{
    const auto wrappedPosition = wrapReadPosition (readPosition, delayBufferLength);
    const auto indexA = static_cast<int> (std::floor (wrappedPosition));
    const auto indexB = (indexA + 1) % delayBufferLength;
    const auto fraction = wrappedPosition - static_cast<float> (indexA);

    return juce::jmap (fraction, delayChannelData[indexA], delayChannelData[indexB]);
}
} // namespace

namespace outspread
{
void WetEngine::prepare (double sampleRate, int maximumBlockSizeToPrepare, int outputChannels)
{
    currentSampleRate = sampleRate;
    currentOutputChannels = outputChannels;
    maximumBlockSize = maximumBlockSizeToPrepare;

    // Match the current Predelay parameter range and leave one extra block of slack so
    // ordinary processing can stay allocation-free after prepare().
    maximumDelaySamples = static_cast<int> (std::ceil ((sampleRate * 0.5))) + maximumBlockSize + 1;
    wetBuffer.setSize (outputChannels, maximumBlockSize, false, false, true);
    delayBuffer.setSize (outputChannels, maximumDelaySamples, false, false, true);
    wetBuffer.clear();
    delayBuffer.clear();
    writePosition = 0;
}

void WetEngine::releaseResources()
{
    wetBuffer.setSize (0, 0);
    delayBuffer.setSize (0, 0);
    currentSampleRate = 0.0;
    currentOutputChannels = 0;
    maximumBlockSize = 0;
    maximumDelaySamples = 0;
    writePosition = 0;
}

void WetEngine::reset()
{
    wetBuffer.clear();
    delayBuffer.clear();
    writePosition = 0;
}

void WetEngine::process (const juce::AudioBuffer<float>& routedInput, const ParameterSnapshot& parameters)
{
    const auto numSamples = routedInput.getNumSamples();
    const auto numInputChannels = routedInput.getNumChannels();
    const auto outputChannels = std::max (currentOutputChannels, numInputChannels);
    const auto delayBufferLength = delayBuffer.getNumSamples();

    if (numSamples <= 0 || numInputChannels <= 0 || delayBufferLength <= 0)
        return;

    if (wetBuffer.getNumChannels() != outputChannels || wetBuffer.getNumSamples() < numSamples)
        wetBuffer.setSize (outputChannels, std::max (maximumBlockSize, numSamples), false, false, true);

    if (delayBuffer.getNumChannels() != outputChannels)
        delayBuffer.setSize (outputChannels, delayBufferLength, false, false, true);

    wetBuffer.clear();

    if (parameters.killWetGainStart == 1.0f && parameters.killWetGainEnd == 1.0f)
    {
        // Continue on: the wet path still needs predelay processing even when the wet gain
        // stays fully open.
    }

    for (int sample = 0; sample < numSamples; ++sample)
    {
        const auto predelayMs = interpolateLinear (
            parameters.predelayMsStart,
            parameters.predelayMsEnd,
            sample,
            numSamples
        );
        const auto delaySamples = juce::jlimit (
            0.0f,
            static_cast<float> (maximumDelaySamples - 1),
            predelayMs * static_cast<float> (currentSampleRate / 1000.0)
        );
        const auto wetGain = interpolateLinear (
            parameters.killWetGainStart,
            parameters.killWetGainEnd,
            sample,
            numSamples
        );

        for (int channel = 0; channel < outputChannels; ++channel)
        {
            const auto sourceChannel = std::min (channel, numInputChannels - 1);
            const auto inputSample = routedInput.getSample (sourceChannel, sample);
            auto* delayChannel = delayBuffer.getWritePointer (channel);

            delayChannel[writePosition] = inputSample;

            const auto readPosition = static_cast<float> (writePosition) - delaySamples;
            const auto delayedSample = readDelayedSample (delayChannel, delayBufferLength, readPosition);
            wetBuffer.setSample (channel, sample, delayedSample * wetGain);
        }

        writePosition = (writePosition + 1) % delayBufferLength;
    }

    if (parameters.kill)
    {
        delayBuffer.clear();
        writePosition = 0;
    }

    juce::ignoreUnused (parameters.feedbackNormalizedSmoothed);
    // The shell wet engine now provides a real predelayed wet path, but it is still only a
    // delayed copy of the routed input rather than a reverb topology.
}
} // namespace outspread
