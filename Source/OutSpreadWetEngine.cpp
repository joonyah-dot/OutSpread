#include "OutSpreadWetEngine.h"

namespace
{
constexpr std::array<float, 4> diffusionTapMs { 0.0f, 0.67f, 1.41f, 2.89f };
constexpr std::array<float, 4> diffusionTapGains { 0.75f, 0.18f, -0.10f, 0.07f };

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
    maximumPredelaySamples = static_cast<int> (std::ceil (sampleRate * 0.5)) + maximumBlockSize + 1;

    const auto longestDiffusionTapMs = diffusionTapMs.back();
    maximumDiffusionSamples = static_cast<int> (std::ceil ((sampleRate * longestDiffusionTapMs) / 1000.0)) + 1;

    for (size_t index = 0; index < diffusionTapMs.size(); ++index)
    {
        diffusionTapSamples[index] = static_cast<int> (
            std::round ((sampleRate * static_cast<double> (diffusionTapMs[index])) / 1000.0)
        );
    }

    wetBuffer.setSize (outputChannels, maximumBlockSize, false, false, true);
    predelayBuffer.setSize (outputChannels, maximumPredelaySamples, false, false, true);
    diffusionBuffer.setSize (outputChannels, maximumDiffusionSamples, false, false, true);
    wetBuffer.clear();
    predelayBuffer.clear();
    diffusionBuffer.clear();
    predelayWritePosition = 0;
    diffusionWritePosition = 0;
}

void WetEngine::releaseResources()
{
    wetBuffer.setSize (0, 0);
    predelayBuffer.setSize (0, 0);
    diffusionBuffer.setSize (0, 0);
    currentSampleRate = 0.0;
    currentOutputChannels = 0;
    maximumBlockSize = 0;
    maximumPredelaySamples = 0;
    maximumDiffusionSamples = 0;
    predelayWritePosition = 0;
    diffusionWritePosition = 0;
    diffusionTapSamples = { 0, 0, 0, 0 };
}

void WetEngine::reset()
{
    wetBuffer.clear();
    predelayBuffer.clear();
    diffusionBuffer.clear();
    predelayWritePosition = 0;
    diffusionWritePosition = 0;
}

void WetEngine::process (const juce::AudioBuffer<float>& routedInput, const ParameterSnapshot& parameters)
{
    const auto numSamples = routedInput.getNumSamples();
    const auto numInputChannels = routedInput.getNumChannels();
    const auto outputChannels = std::max (currentOutputChannels, numInputChannels);
    const auto predelayBufferLength = predelayBuffer.getNumSamples();
    const auto diffusionBufferLength = diffusionBuffer.getNumSamples();

    if (numSamples <= 0 || numInputChannels <= 0 || predelayBufferLength <= 0 || diffusionBufferLength <= 0)
        return;

    if (wetBuffer.getNumChannels() != outputChannels || wetBuffer.getNumSamples() < numSamples)
        wetBuffer.setSize (outputChannels, std::max (maximumBlockSize, numSamples), false, false, true);

    if (predelayBuffer.getNumChannels() != outputChannels)
        predelayBuffer.setSize (outputChannels, predelayBufferLength, false, false, true);

    if (diffusionBuffer.getNumChannels() != outputChannels)
        diffusionBuffer.setSize (outputChannels, diffusionBufferLength, false, false, true);

    wetBuffer.clear();

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
            static_cast<float> (maximumPredelaySamples - 1),
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
            auto* predelayChannel = predelayBuffer.getWritePointer (channel);
            auto* diffusionChannel = diffusionBuffer.getWritePointer (channel);

            predelayChannel[predelayWritePosition] = inputSample;

            const auto predelayReadPosition = static_cast<float> (predelayWritePosition) - delaySamples;
            const auto predelayedSample = readDelayedSample (predelayChannel, predelayBufferLength, predelayReadPosition);
            diffusionChannel[diffusionWritePosition] = predelayedSample;

            auto diffusedSample = predelayedSample;
            if (delaySamples >= 1.0f)
            {
                diffusedSample = 0.0f;
                for (size_t tapIndex = 0; tapIndex < diffusionTapGains.size(); ++tapIndex)
                {
                    const auto tapReadPosition = static_cast<float> (diffusionWritePosition - diffusionTapSamples[tapIndex]);
                    diffusedSample += diffusionTapGains[tapIndex]
                        * readDelayedSample (diffusionChannel, diffusionBufferLength, tapReadPosition);
                }
            }

            wetBuffer.setSample (channel, sample, diffusedSample * wetGain);
        }

        predelayWritePosition = (predelayWritePosition + 1) % predelayBufferLength;
        diffusionWritePosition = (diffusionWritePosition + 1) % diffusionBufferLength;
    }

    if (parameters.kill)
    {
        predelayBuffer.clear();
        diffusionBuffer.clear();
        predelayWritePosition = 0;
        diffusionWritePosition = 0;
    }

    juce::ignoreUnused (parameters.feedbackNormalizedSmoothed);
    // The shell wet engine now runs routed input through predelay first and then a very short,
    // fixed diffusion stage. This stays intentionally finite and non-regenerative so the shell
    // still does not behave like a full reverberator.
}
} // namespace outspread
