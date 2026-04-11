#include "OutSpreadWetEngine.h"

namespace
{
constexpr std::array<float, 4> diffusionTapMs { 0.0f, 0.67f, 1.41f, 2.89f };
constexpr std::array<float, 4> diffusionTapGains { 0.75f, 0.18f, -0.10f, 0.07f };
constexpr float localRecirculationDelayMs = 4.5f;
constexpr float minimumSizeTimeScale = 0.65f;
constexpr float maximumSizeTimeScale = 1.35f;
constexpr float minimumLocalRecirculationGain = 0.12f;
constexpr float maximumLocalRecirculationGain = 0.38f;
constexpr std::array<float, 4> secondaryDiffusionTapMs { 0.0f, 0.91f, 1.87f, 3.73f };
constexpr std::array<float, 4> secondaryDiffusionTapGains { 0.58f, -0.16f, 0.09f, 0.05f };
constexpr std::array<float, 2> secondaryLocalRecirculationDelayMs { 5.3f, 6.1f };
constexpr float minimumSecondaryLocalRecirculationGain = 0.08f;
constexpr float maximumSecondaryLocalRecirculationGain = 0.28f;
constexpr float secondaryBranchMix = 0.35f;
constexpr std::array<float, 2> primaryCrossCouplingDelayMs { 2.6f, 3.2f };
constexpr std::array<float, 2> secondaryCrossCouplingDelayMs { 3.4f, 2.4f };
constexpr float minimumPrimaryCrossCouplingGain = 0.03f;
constexpr float maximumPrimaryCrossCouplingGain = 0.13f;
constexpr float minimumSecondaryCrossCouplingGain = 0.02f;
constexpr float maximumSecondaryCrossCouplingGain = 0.10f;

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

float mapFeedbackGain (float normalizedFeedback, float minimumGain, float maximumGain)
{
    return juce::jmap (juce::jlimit (0.0f, 1.0f, normalizedFeedback), minimumGain, maximumGain);
}

float mapSizeTimeScale (float normalizedSize)
{
    return juce::jmap (
        juce::jlimit (0.0f, 1.0f, normalizedSize),
        minimumSizeTimeScale,
        maximumSizeTimeScale
    );
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

    const auto longestDiffusionTapMs = diffusionTapMs.back() * maximumSizeTimeScale;
    maximumDiffusionSamples = static_cast<int> (std::ceil ((sampleRate * longestDiffusionTapMs) / 1000.0)) + 1;
    maximumLocalRecirculationSamples = static_cast<int> (
        std::ceil ((sampleRate * (localRecirculationDelayMs * maximumSizeTimeScale)) / 1000.0)
    ) + 1;
    localRecirculationDelaySamples = static_cast<int> (
        std::round ((sampleRate * static_cast<double> (localRecirculationDelayMs)) / 1000.0)
    );
    const auto longestSecondaryDiffusionTapMs = secondaryDiffusionTapMs.back() * maximumSizeTimeScale;
    maximumSecondaryDiffusionSamples = static_cast<int> (
        std::ceil ((sampleRate * longestSecondaryDiffusionTapMs) / 1000.0)
    ) + 1;
    const auto longestSecondaryLocalRecirculationDelayMs = std::max (
        secondaryLocalRecirculationDelayMs[0],
        secondaryLocalRecirculationDelayMs[1]
    ) * maximumSizeTimeScale;
    maximumSecondaryLocalRecirculationSamples = static_cast<int> (
        std::ceil ((sampleRate * longestSecondaryLocalRecirculationDelayMs) / 1000.0)
    ) + 1;

    for (size_t index = 0; index < diffusionTapMs.size(); ++index)
    {
        diffusionTapSamples[index] = static_cast<int> (
            std::round ((sampleRate * static_cast<double> (diffusionTapMs[index])) / 1000.0)
        );
        secondaryDiffusionTapSamples[index] = static_cast<int> (
            std::round ((sampleRate * static_cast<double> (secondaryDiffusionTapMs[index])) / 1000.0)
        );
    }

    for (size_t index = 0; index < secondaryLocalRecirculationDelayMs.size(); ++index)
    {
        secondaryLocalRecirculationDelaySamples[index] = static_cast<int> (
            std::round ((sampleRate * static_cast<double> (secondaryLocalRecirculationDelayMs[index])) / 1000.0)
        );
        primaryCrossCouplingDelaySamples[index] = static_cast<int> (
            std::round ((sampleRate * static_cast<double> (primaryCrossCouplingDelayMs[index])) / 1000.0)
        );
        secondaryCrossCouplingDelaySamples[index] = static_cast<int> (
            std::round ((sampleRate * static_cast<double> (secondaryCrossCouplingDelayMs[index])) / 1000.0)
        );
    }

    wetBuffer.setSize (outputChannels, maximumBlockSize, false, false, true);
    predelayBuffer.setSize (outputChannels, maximumPredelaySamples, false, false, true);
    diffusionBuffer.setSize (outputChannels, maximumDiffusionSamples, false, false, true);
    localRecirculationBuffer.setSize (outputChannels, maximumLocalRecirculationSamples, false, false, true);
    secondaryDiffusionBuffer.setSize (outputChannels, maximumSecondaryDiffusionSamples, false, false, true);
    secondaryLocalRecirculationBuffer.setSize (outputChannels, maximumSecondaryLocalRecirculationSamples, false, false, true);
    wetBuffer.clear();
    predelayBuffer.clear();
    diffusionBuffer.clear();
    localRecirculationBuffer.clear();
    secondaryDiffusionBuffer.clear();
    secondaryLocalRecirculationBuffer.clear();
    predelayWritePosition = 0;
    diffusionWritePosition = 0;
    localRecirculationWritePosition = 0;
    secondaryDiffusionWritePosition = 0;
    secondaryLocalRecirculationWritePosition = 0;
}

void WetEngine::releaseResources()
{
    wetBuffer.setSize (0, 0);
    predelayBuffer.setSize (0, 0);
    diffusionBuffer.setSize (0, 0);
    localRecirculationBuffer.setSize (0, 0);
    secondaryDiffusionBuffer.setSize (0, 0);
    secondaryLocalRecirculationBuffer.setSize (0, 0);
    currentSampleRate = 0.0;
    currentOutputChannels = 0;
    maximumBlockSize = 0;
    maximumPredelaySamples = 0;
    maximumDiffusionSamples = 0;
    maximumLocalRecirculationSamples = 0;
    maximumSecondaryDiffusionSamples = 0;
    maximumSecondaryLocalRecirculationSamples = 0;
    predelayWritePosition = 0;
    diffusionWritePosition = 0;
    localRecirculationWritePosition = 0;
    secondaryDiffusionWritePosition = 0;
    secondaryLocalRecirculationWritePosition = 0;
    localRecirculationDelaySamples = 0;
    diffusionTapSamples = { 0, 0, 0, 0 };
    secondaryDiffusionTapSamples = { 0, 0, 0, 0 };
    secondaryLocalRecirculationDelaySamples = { 0, 0 };
    primaryCrossCouplingDelaySamples = { 0, 0 };
    secondaryCrossCouplingDelaySamples = { 0, 0 };
}

void WetEngine::reset()
{
    wetBuffer.clear();
    predelayBuffer.clear();
    diffusionBuffer.clear();
    localRecirculationBuffer.clear();
    secondaryDiffusionBuffer.clear();
    secondaryLocalRecirculationBuffer.clear();
    predelayWritePosition = 0;
    diffusionWritePosition = 0;
    localRecirculationWritePosition = 0;
    secondaryDiffusionWritePosition = 0;
    secondaryLocalRecirculationWritePosition = 0;
}

void WetEngine::process (const juce::AudioBuffer<float>& routedInput, const ParameterSnapshot& parameters)
{
    const auto numSamples = routedInput.getNumSamples();
    const auto numInputChannels = routedInput.getNumChannels();
    const auto outputChannels = std::max (currentOutputChannels, numInputChannels);
    const auto predelayBufferLength = predelayBuffer.getNumSamples();
    const auto diffusionBufferLength = diffusionBuffer.getNumSamples();
    const auto localRecirculationBufferLength = localRecirculationBuffer.getNumSamples();
    const auto secondaryDiffusionBufferLength = secondaryDiffusionBuffer.getNumSamples();
    const auto secondaryLocalRecirculationBufferLength = secondaryLocalRecirculationBuffer.getNumSamples();

    if (numSamples <= 0 || numInputChannels <= 0
        || predelayBufferLength <= 0 || diffusionBufferLength <= 0 || localRecirculationBufferLength <= 0
        || secondaryDiffusionBufferLength <= 0 || secondaryLocalRecirculationBufferLength <= 0)
        return;

    if (wetBuffer.getNumChannels() != outputChannels || wetBuffer.getNumSamples() < numSamples)
        wetBuffer.setSize (outputChannels, std::max (maximumBlockSize, numSamples), false, false, true);

    if (predelayBuffer.getNumChannels() != outputChannels)
        predelayBuffer.setSize (outputChannels, predelayBufferLength, false, false, true);

    if (diffusionBuffer.getNumChannels() != outputChannels)
        diffusionBuffer.setSize (outputChannels, diffusionBufferLength, false, false, true);

    if (localRecirculationBuffer.getNumChannels() != outputChannels)
        localRecirculationBuffer.setSize (outputChannels, localRecirculationBufferLength, false, false, true);

    if (secondaryDiffusionBuffer.getNumChannels() != outputChannels)
        secondaryDiffusionBuffer.setSize (outputChannels, secondaryDiffusionBufferLength, false, false, true);

    if (secondaryLocalRecirculationBuffer.getNumChannels() != outputChannels)
        secondaryLocalRecirculationBuffer.setSize (outputChannels, secondaryLocalRecirculationBufferLength, false, false, true);

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
        const auto normalizedFeedback = interpolateLinear (
            parameters.feedbackNormalizedStart,
            parameters.feedbackNormalizedEnd,
            sample,
            numSamples
        );
        const auto normalizedSize = interpolateLinear (
            parameters.sizeNormalizedStart,
            parameters.sizeNormalizedEnd,
            sample,
            numSamples
        );
        const auto sizeTimeScale = mapSizeTimeScale (normalizedSize);
        const auto primaryRecirculationGain = mapFeedbackGain (
            normalizedFeedback,
            minimumLocalRecirculationGain,
            maximumLocalRecirculationGain
        );
        const auto secondaryRecirculationGain = mapFeedbackGain (
            normalizedFeedback,
            minimumSecondaryLocalRecirculationGain,
            maximumSecondaryLocalRecirculationGain
        );
        const auto primaryCouplingGain = mapFeedbackGain (
            normalizedFeedback,
            minimumPrimaryCrossCouplingGain,
            maximumPrimaryCrossCouplingGain
        );
        const auto secondaryCouplingGain = mapFeedbackGain (
            normalizedFeedback,
            minimumSecondaryCrossCouplingGain,
            maximumSecondaryCrossCouplingGain
        );

        for (int channel = 0; channel < outputChannels; ++channel)
        {
            const auto sourceChannel = std::min (channel, numInputChannels - 1);
            const auto inputSample = routedInput.getSample (sourceChannel, sample);
            auto* predelayChannel = predelayBuffer.getWritePointer (channel);
            auto* diffusionChannel = diffusionBuffer.getWritePointer (channel);
            auto* localRecirculationChannel = localRecirculationBuffer.getWritePointer (channel);
            auto* secondaryDiffusionChannel = secondaryDiffusionBuffer.getWritePointer (channel);
            auto* secondaryLocalRecirculationChannel = secondaryLocalRecirculationBuffer.getWritePointer (channel);

            predelayChannel[predelayWritePosition] = inputSample;

            const auto predelayReadPosition = static_cast<float> (predelayWritePosition) - delaySamples;
            const auto predelayedSample = readDelayedSample (predelayChannel, predelayBufferLength, predelayReadPosition);
            diffusionChannel[diffusionWritePosition] = predelayedSample;
            secondaryDiffusionChannel[secondaryDiffusionWritePosition] = predelayedSample;

            auto diffusedSample = predelayedSample;
            auto secondaryDiffusedSample = predelayedSample;
            if (delaySamples >= 1.0f)
            {
                diffusedSample = 0.0f;
                for (size_t tapIndex = 0; tapIndex < diffusionTapGains.size(); ++tapIndex)
                {
                    const auto scaledTapSamples = static_cast<float> (diffusionTapSamples[tapIndex]) * sizeTimeScale;
                    const auto tapReadPosition = static_cast<float> (diffusionWritePosition) - scaledTapSamples;
                    diffusedSample += diffusionTapGains[tapIndex]
                        * readDelayedSample (diffusionChannel, diffusionBufferLength, tapReadPosition);
                }

                secondaryDiffusedSample = 0.0f;
                for (size_t tapIndex = 0; tapIndex < secondaryDiffusionTapGains.size(); ++tapIndex)
                {
                    const auto scaledSecondaryTapSamples =
                        static_cast<float> (secondaryDiffusionTapSamples[tapIndex]) * sizeTimeScale;
                    const auto secondaryTapReadPosition =
                        static_cast<float> (secondaryDiffusionWritePosition) - scaledSecondaryTapSamples;
                    secondaryDiffusedSample += secondaryDiffusionTapGains[tapIndex]
                        * readDelayedSample (
                            secondaryDiffusionChannel,
                            secondaryDiffusionBufferLength,
                            secondaryTapReadPosition
                        );
                }
            }

            auto primaryBranchSample = diffusedSample;
            if (delaySamples >= 1.0f && localRecirculationDelaySamples > 0)
            {
                const auto scaledPrimaryRecirculationDelaySamples =
                    static_cast<float> (localRecirculationDelaySamples) * sizeTimeScale;
                const auto localRecirculationReadPosition =
                    static_cast<float> (localRecirculationWritePosition) - scaledPrimaryRecirculationDelaySamples;
                const auto localRecirculationSample = readDelayedSample (
                    localRecirculationChannel,
                    localRecirculationBufferLength,
                    localRecirculationReadPosition
                );
                primaryBranchSample += localRecirculationSample * primaryRecirculationGain;
            }

            auto secondaryBranchSample = secondaryDiffusedSample;
            if (delaySamples >= 1.0f)
            {
                const auto secondaryDelayIndex = std::min (channel, static_cast<int> (secondaryLocalRecirculationDelaySamples.size()) - 1);
                const auto secondaryRecirculationDelaySamples =
                    static_cast<float> (secondaryLocalRecirculationDelaySamples[secondaryDelayIndex]) * sizeTimeScale;
                if (secondaryRecirculationDelaySamples > 0.0f)
                {
                    const auto secondaryLocalRecirculationReadPosition =
                        static_cast<float> (secondaryLocalRecirculationWritePosition) - secondaryRecirculationDelaySamples;
                    const auto secondaryLocalRecirculationSample = readDelayedSample (
                        secondaryLocalRecirculationChannel,
                        secondaryLocalRecirculationBufferLength,
                        secondaryLocalRecirculationReadPosition
                    );
                    secondaryBranchSample += secondaryLocalRecirculationSample * secondaryRecirculationGain;
                }
            }

            if (delaySamples >= 1.0f)
            {
                const auto couplingDelayIndex = std::min (channel, static_cast<int> (primaryCrossCouplingDelaySamples.size()) - 1);
                const auto primaryCouplingDelaySamples =
                    static_cast<float> (primaryCrossCouplingDelaySamples[couplingDelayIndex]) * sizeTimeScale;
                const auto secondaryCouplingDelaySamplesForBranch =
                    static_cast<float> (secondaryCrossCouplingDelaySamples[couplingDelayIndex]) * sizeTimeScale;

                if (primaryCouplingDelaySamples > 0.0f)
                {
                    const auto primaryCouplingReadPosition =
                        static_cast<float> (secondaryLocalRecirculationWritePosition) - primaryCouplingDelaySamples;
                    const auto coupledFromSecondary = readDelayedSample (
                        secondaryLocalRecirculationChannel,
                        secondaryLocalRecirculationBufferLength,
                        primaryCouplingReadPosition
                    );
                    primaryBranchSample += coupledFromSecondary * primaryCouplingGain;
                }

                if (secondaryCouplingDelaySamplesForBranch > 0.0f)
                {
                    const auto secondaryCouplingReadPosition =
                        static_cast<float> (localRecirculationWritePosition) - secondaryCouplingDelaySamplesForBranch;
                    const auto coupledFromPrimary = readDelayedSample (
                        localRecirculationChannel,
                        localRecirculationBufferLength,
                        secondaryCouplingReadPosition
                    );
                    secondaryBranchSample += coupledFromPrimary * secondaryCouplingGain;
                }
            }

            localRecirculationChannel[localRecirculationWritePosition] = primaryBranchSample;
            secondaryLocalRecirculationChannel[secondaryLocalRecirculationWritePosition] = secondaryBranchSample;

            auto wetSample = primaryBranchSample;
            if (delaySamples >= 1.0f)
                wetSample += secondaryBranchSample * secondaryBranchMix;

            wetBuffer.setSample (channel, sample, wetSample * wetGain);
        }

        predelayWritePosition = (predelayWritePosition + 1) % predelayBufferLength;
        diffusionWritePosition = (diffusionWritePosition + 1) % diffusionBufferLength;
        localRecirculationWritePosition = (localRecirculationWritePosition + 1) % localRecirculationBufferLength;
        secondaryDiffusionWritePosition = (secondaryDiffusionWritePosition + 1) % secondaryDiffusionBufferLength;
        secondaryLocalRecirculationWritePosition =
            (secondaryLocalRecirculationWritePosition + 1) % secondaryLocalRecirculationBufferLength;
    }

    if (parameters.kill)
    {
        predelayBuffer.clear();
        diffusionBuffer.clear();
        localRecirculationBuffer.clear();
        secondaryDiffusionBuffer.clear();
        secondaryLocalRecirculationBuffer.clear();
        predelayWritePosition = 0;
        diffusionWritePosition = 0;
        localRecirculationWritePosition = 0;
        secondaryDiffusionWritePosition = 0;
        secondaryLocalRecirculationWritePosition = 0;
    }

    // The shell wet engine now runs routed input through predelay and then a tiny two-branch early
    // structure with bounded size-scaled short timings plus bounded feedback-driven local
    // recirculation and cross-coupling. The public Size control only stretches these short internal
    // spacings inside conservative limits so the shell can move between tighter and looser early
    // structure without behaving like a full reverberator.
}
} // namespace outspread
