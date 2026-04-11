#pragma once

#include <JuceHeader.h>

namespace outspread
{
namespace parameter_ids
{
inline constexpr auto mix = "mix";
inline constexpr auto size = "size";
inline constexpr auto gravity = "gravity";
inline constexpr auto feedback = "feedback";
inline constexpr auto predelay = "predelay";
inline constexpr auto lowTone = "low_tone";
inline constexpr auto highTone = "high_tone";
inline constexpr auto resonance = "resonance";
inline constexpr auto modDepth = "mod_depth";
inline constexpr auto modRate = "mod_rate";
inline constexpr auto freezeInfinite = "freeze_infinite";
inline constexpr auto kill = "kill";
} // namespace parameter_ids

inline constexpr auto stateTreeId = "outspread_state";

struct ParameterSnapshot
{
    float mix = 0.0f;
    float size = 50.0f;
    float gravity = 0.0f;
    float feedback = 50.0f;
    float predelayMs = 0.0f;
    float lowTone = 0.0f;
    float highTone = 0.0f;
    float resonance = 0.0f;
    float modDepth = 0.0f;
    float modRateHz = 1.0f;
    bool freezeInfinite = false;
    bool kill = false;

    float mixWetStart = 0.0f;
    float mixWetEnd = 0.0f;
    float mixDryStart = 1.0f;
    float mixDryEnd = 1.0f;
    float killWetGainStart = 1.0f;
    float killWetGainEnd = 1.0f;
    float predelayMsStart = 0.0f;
    float predelayMsEnd = 0.0f;
    float feedbackNormalizedStart = 0.5f;
    float feedbackNormalizedEnd = 0.5f;
    float feedbackNormalizedSmoothed = 0.5f;
};

juce::AudioProcessorValueTreeState::ParameterLayout createParameterLayout();

class ParameterState
{
public:
    explicit ParameterState (juce::AudioProcessorValueTreeState& stateToBind);

    void prepare (double sampleRate);
    void reset();

    ParameterSnapshot readCurrentValues() const noexcept;
    ParameterSnapshot capture (int numSamples) noexcept;

private:
    static float loadValue (const std::atomic<float>* parameter, float fallback) noexcept;

    juce::AudioProcessorValueTreeState& state;

    std::atomic<float>* mixParameter = nullptr;
    std::atomic<float>* sizeParameter = nullptr;
    std::atomic<float>* gravityParameter = nullptr;
    std::atomic<float>* feedbackParameter = nullptr;
    std::atomic<float>* predelayParameter = nullptr;
    std::atomic<float>* lowToneParameter = nullptr;
    std::atomic<float>* highToneParameter = nullptr;
    std::atomic<float>* resonanceParameter = nullptr;
    std::atomic<float>* modDepthParameter = nullptr;
    std::atomic<float>* modRateParameter = nullptr;
    std::atomic<float>* freezeInfiniteParameter = nullptr;
    std::atomic<float>* killParameter = nullptr;

    juce::SmoothedValue<float, juce::ValueSmoothingTypes::Linear> mixWetSmoothed;
    juce::SmoothedValue<float, juce::ValueSmoothingTypes::Linear> killWetGainSmoothed;
    juce::SmoothedValue<float, juce::ValueSmoothingTypes::Linear> predelayMsSmoothed;
    juce::SmoothedValue<float, juce::ValueSmoothingTypes::Linear> feedbackSmoothed;
};
} // namespace outspread
