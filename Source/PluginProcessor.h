#pragma once
#include <JuceHeader.h>

class OutSpreadAudioProcessor : public juce::AudioProcessor
{
public:
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
    };

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
    static juce::AudioProcessorValueTreeState::ParameterLayout createParameterLayout();
    static std::unique_ptr<juce::RangedAudioParameter> createFloatParameter (
        const juce::String& parameterId,
        const juce::String& name,
        juce::NormalisableRange<float> range,
        float defaultValue);

    void initializeParameterPointers();
    void prepareRoutedInput (juce::AudioBuffer<float>& buffer, int numSamples);
    void populateWetBufferFromShellInput();

    juce::AudioProcessorValueTreeState parameters;

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

    juce::AudioBuffer<float> routedInputBuffer;
    juce::AudioBuffer<float> wetBuffer;
    juce::SmoothedValue<float, juce::ValueSmoothingTypes::Linear> mixSmoothed;

    JUCE_DECLARE_NON_COPYABLE_WITH_LEAK_DETECTOR (OutSpreadAudioProcessor)
};
