#include <JuceHeader.h>

#include "OutSpreadParameters.h"
#include "PluginProcessor.h"

namespace
{
constexpr double kSampleRate = 48000.0;
constexpr int kBlockSize = 64;
constexpr float kFloatTolerance = 0.001f;
constexpr float kSilenceTolerance = 1.0e-6f;

juce::var makeObject()
{
    return juce::var (new juce::DynamicObject());
}

juce::DynamicObject* asObject (juce::var& value)
{
    return value.getDynamicObject();
}

juce::var makeIssue (const juce::String& code, const juce::String& message)
{
    auto issue = makeObject();
    asObject (issue)->setProperty ("code", code);
    asObject (issue)->setProperty ("message", message);
    return issue;
}

bool nearlyEqual (float a, float b, float tolerance = kFloatTolerance)
{
    return std::abs (a - b) <= tolerance;
}

float computePeak (const juce::AudioBuffer<float>& buffer)
{
    float peak = 0.0f;
    for (int channel = 0; channel < buffer.getNumChannels(); ++channel)
        peak = std::max (peak, buffer.getMagnitude (channel, 0, buffer.getNumSamples()));
    return peak;
}

bool setParameterPlainValue (OutSpreadAudioProcessor& processor,
                             const juce::String& parameterId,
                             float plainValue,
                             juce::String& error)
{
    auto* parameter = processor.getValueTreeState().getParameter (parameterId);
    auto* rangedParameter = dynamic_cast<juce::RangedAudioParameter*> (parameter);
    if (rangedParameter == nullptr)
    {
        error = "Missing ranged parameter: " + parameterId;
        return false;
    }

    rangedParameter->setValueNotifyingHost (rangedParameter->convertTo0to1 (plainValue));
    return true;
}

bool setSupportedLayout (OutSpreadAudioProcessor& processor,
                         const juce::AudioChannelSet& input,
                         const juce::AudioChannelSet& output,
                         juce::String& error)
{
    juce::AudioProcessor::BusesLayout layout;
    layout.inputBuses.add (input);
    layout.outputBuses.add (output);

    if (! processor.setBusesLayout (layout))
    {
        error = "Processor rejected supported layout " + input.getDescription()
            + " -> " + output.getDescription();
        return false;
    }

    processor.setRateAndBufferSizeDetails (kSampleRate, kBlockSize);
    processor.prepareToPlay (kSampleRate, kBlockSize);
    return true;
}

juce::var buildLayoutSupportSummary()
{
    auto summary = makeObject();
    juce::Array<juce::var> layoutChecks;

    const struct LayoutExpectation
    {
        const char* label;
        juce::AudioChannelSet input;
        juce::AudioChannelSet output;
        bool expectedSupported;
    } expectations[] {
        { "mono_to_stereo", juce::AudioChannelSet::mono(), juce::AudioChannelSet::stereo(), true },
        { "stereo_to_stereo", juce::AudioChannelSet::stereo(), juce::AudioChannelSet::stereo(), true },
        { "mono_to_mono", juce::AudioChannelSet::mono(), juce::AudioChannelSet::mono(), false },
        { "stereo_to_mono", juce::AudioChannelSet::stereo(), juce::AudioChannelSet::mono(), false },
        { "three_to_stereo", juce::AudioChannelSet::discreteChannels (3), juce::AudioChannelSet::stereo(), false },
    };

    bool allAsExpected = true;
    for (const auto& expectation : expectations)
    {
        OutSpreadAudioProcessor processor;
        juce::AudioProcessor::BusesLayout layout;
        layout.inputBuses.add (expectation.input);
        layout.outputBuses.add (expectation.output);

        const bool supported = processor.isBusesLayoutSupported (layout);
        const bool passed = supported == expectation.expectedSupported;
        allAsExpected &= passed;

        auto item = makeObject();
        asObject (item)->setProperty ("label", expectation.label);
        asObject (item)->setProperty ("input", expectation.input.getDescription());
        asObject (item)->setProperty ("output", expectation.output.getDescription());
        asObject (item)->setProperty ("supported", supported);
        asObject (item)->setProperty ("expectedSupported", expectation.expectedSupported);
        asObject (item)->setProperty ("passed", passed);
        layoutChecks.add (item);
    }

    asObject (summary)->setProperty ("allAsExpected", allAsExpected);
    asObject (summary)->setProperty ("checks", juce::var (layoutChecks));
    return summary;
}

juce::var buildMonoToStereoRoutingSummary (juce::Array<juce::var>& issues)
{
    auto summary = makeObject();
    OutSpreadAudioProcessor processor;
    juce::String error;

    if (! setSupportedLayout (processor, juce::AudioChannelSet::mono(), juce::AudioChannelSet::stereo(), error))
    {
        issues.add (makeIssue ("mono_to_stereo_layout_failed", error));
        asObject (summary)->setProperty ("passed", false);
        asObject (summary)->setProperty ("error", error);
        return summary;
    }

    juce::AudioBuffer<float> buffer (2, kBlockSize);
    buffer.clear();
    for (int sample = 0; sample < kBlockSize; ++sample)
        buffer.setSample (0, sample, sample == 0 ? 1.0f : 0.125f * static_cast<float> (sample));

    juce::AudioBuffer<float> inputCopy (buffer);
    juce::MidiBuffer midi;
    processor.processBlock (buffer, midi);

    bool leftMatches = true;
    bool rightMatches = true;
    bool outputsMatch = true;

    for (int sample = 0; sample < kBlockSize; ++sample)
    {
        const float expected = inputCopy.getSample (0, sample);
        const float left = buffer.getSample (0, sample);
        const float right = buffer.getSample (1, sample);
        leftMatches &= nearlyEqual (left, expected);
        rightMatches &= nearlyEqual (right, expected);
        outputsMatch &= nearlyEqual (left, right);
    }

    const bool passed = leftMatches && rightMatches && outputsMatch;
    if (! passed)
    {
        issues.add (makeIssue (
            "mono_to_stereo_routing_mismatch",
            "Mono input was not duplicated cleanly to the stereo shell output."
        ));
    }

    asObject (summary)->setProperty ("passed", passed);
    asObject (summary)->setProperty ("leftMatchesInput", leftMatches);
    asObject (summary)->setProperty ("rightMatchesInput", rightMatches);
    asObject (summary)->setProperty ("leftRightMatch", outputsMatch);
    asObject (summary)->setProperty ("firstOutputSampleLeft", buffer.getSample (0, 0));
    asObject (summary)->setProperty ("firstOutputSampleRight", buffer.getSample (1, 0));
    asObject (summary)->setProperty ("notes", "Direct processor verification path used because the current harness configures symmetric channel layouts only.");
    return summary;
}

juce::var buildStereoRoutingSummary (juce::Array<juce::var>& issues)
{
    auto summary = makeObject();
    OutSpreadAudioProcessor processor;
    juce::String error;

    if (! setSupportedLayout (processor, juce::AudioChannelSet::stereo(), juce::AudioChannelSet::stereo(), error))
    {
        issues.add (makeIssue ("stereo_to_stereo_layout_failed", error));
        asObject (summary)->setProperty ("passed", false);
        asObject (summary)->setProperty ("error", error);
        return summary;
    }

    juce::AudioBuffer<float> buffer (2, kBlockSize);
    buffer.clear();
    for (int sample = 0; sample < kBlockSize; ++sample)
    {
        buffer.setSample (0, sample, sample == 0 ? 0.75f : 0.01f * static_cast<float> (sample));
        buffer.setSample (1, sample, sample == 1 ? -0.5f : -0.015f * static_cast<float> (sample));
    }

    juce::AudioBuffer<float> inputCopy (buffer);
    juce::MidiBuffer midi;
    processor.processBlock (buffer, midi);

    bool leftMatches = true;
    bool rightMatches = true;
    for (int sample = 0; sample < kBlockSize; ++sample)
    {
        leftMatches &= nearlyEqual (buffer.getSample (0, sample), inputCopy.getSample (0, sample));
        rightMatches &= nearlyEqual (buffer.getSample (1, sample), inputCopy.getSample (1, sample));
    }

    const bool passed = leftMatches && rightMatches;
    if (! passed)
    {
        issues.add (makeIssue (
            "stereo_to_stereo_routing_mismatch",
            "Stereo input was not preserved channel-for-channel through the shell."
        ));
    }

    asObject (summary)->setProperty ("passed", passed);
    asObject (summary)->setProperty ("leftMatchesInput", leftMatches);
    asObject (summary)->setProperty ("rightMatchesInput", rightMatches);
    return summary;
}

juce::var buildLayoutCheckResult()
{
    auto result = makeObject();
    juce::Array<juce::var> issues;

    const auto layoutSupport = buildLayoutSupportSummary();
    const auto monoToStereo = buildMonoToStereoRoutingSummary (issues);
    const auto stereoToStereo = buildStereoRoutingSummary (issues);

    const bool passed = static_cast<bool> (layoutSupport.getProperty ("allAsExpected", false))
        && static_cast<bool> (monoToStereo.getProperty ("passed", false))
        && static_cast<bool> (stereoToStereo.getProperty ("passed", false))
        && issues.isEmpty();

    asObject (result)->setProperty ("schemaVersion", 1);
    asObject (result)->setProperty ("mode", "layout-check");
    asObject (result)->setProperty ("passed", passed);
    asObject (result)->setProperty ("layoutSupport", layoutSupport);
    asObject (result)->setProperty ("monoToStereoRouting", monoToStereo);
    asObject (result)->setProperty ("stereoToStereoRouting", stereoToStereo);
    asObject (result)->setProperty ("issues", juce::var (issues));
    return result;
}

juce::var buildStateRoundtripResult()
{
    auto result = makeObject();
    juce::Array<juce::var> issues;

    struct FloatTarget
    {
        const char* id;
        float value;
    };

    static constexpr FloatTarget floatTargets[] {
        { outspread::parameter_ids::mix, 100.0f },
        { outspread::parameter_ids::size, 82.5f },
        { outspread::parameter_ids::gravity, -37.0f },
        { outspread::parameter_ids::feedback, 61.0f },
        { outspread::parameter_ids::predelay, 123.0f },
        { outspread::parameter_ids::lowTone, -25.0f },
        { outspread::parameter_ids::highTone, 40.0f },
        { outspread::parameter_ids::resonance, 33.0f },
        { outspread::parameter_ids::modDepth, 27.0f },
        { outspread::parameter_ids::modRate, 3.25f },
    };

    static constexpr FloatTarget boolTargets[] {
        { outspread::parameter_ids::freezeInfinite, 1.0f },
        { outspread::parameter_ids::kill, 1.0f },
    };

    OutSpreadAudioProcessor sourceProcessor;
    sourceProcessor.setRateAndBufferSizeDetails (kSampleRate, kBlockSize);
    sourceProcessor.prepareToPlay (kSampleRate, kBlockSize);

    juce::String error;
    for (const auto& target : floatTargets)
    {
        if (! setParameterPlainValue (sourceProcessor, target.id, target.value, error))
        {
            issues.add (makeIssue ("set_parameter_failed", error));
        }
    }
    for (const auto& target : boolTargets)
    {
        if (! setParameterPlainValue (sourceProcessor, target.id, target.value, error))
        {
            issues.add (makeIssue ("set_parameter_failed", error));
        }
    }

    const auto sourceSnapshot = sourceProcessor.getParameterSnapshot();
    juce::MemoryBlock stateBlock;
    sourceProcessor.getStateInformation (stateBlock);

    OutSpreadAudioProcessor restoredProcessor;
    restoredProcessor.setRateAndBufferSizeDetails (kSampleRate, kBlockSize);
    restoredProcessor.prepareToPlay (kSampleRate, kBlockSize);
    restoredProcessor.setStateInformation (stateBlock.getData(), static_cast<int> (stateBlock.getSize()));

    const auto restoredSnapshot = restoredProcessor.getParameterSnapshot();
    juce::Array<juce::var> parameterMatches;
    bool allParametersMatch = issues.isEmpty();

    const auto addFloatMatch = [&parameterMatches, &allParametersMatch] (const juce::String& id, float expected, float restored)
    {
        const bool passed = nearlyEqual (expected, restored, 0.05f);
        allParametersMatch &= passed;

        auto match = makeObject();
        asObject (match)->setProperty ("parameterId", id);
        asObject (match)->setProperty ("expected", expected);
        asObject (match)->setProperty ("restored", restored);
        asObject (match)->setProperty ("passed", passed);
        parameterMatches.add (match);
    };

    addFloatMatch ("mix", 100.0f, restoredSnapshot.mix);
    addFloatMatch ("size", 82.5f, restoredSnapshot.size);
    addFloatMatch ("gravity", -37.0f, restoredSnapshot.gravity);
    addFloatMatch ("feedback", 61.0f, restoredSnapshot.feedback);
    addFloatMatch ("predelay", 123.0f, restoredSnapshot.predelayMs);
    addFloatMatch ("low_tone", -25.0f, restoredSnapshot.lowTone);
    addFloatMatch ("high_tone", 40.0f, restoredSnapshot.highTone);
    addFloatMatch ("resonance", 33.0f, restoredSnapshot.resonance);
    addFloatMatch ("mod_depth", 27.0f, restoredSnapshot.modDepth);
    addFloatMatch ("mod_rate", 3.25f, restoredSnapshot.modRateHz);

    const auto addBoolMatch = [&parameterMatches, &allParametersMatch] (const juce::String& id, bool expected, bool restored)
    {
        const bool passed = expected == restored;
        allParametersMatch &= passed;

        auto match = makeObject();
        asObject (match)->setProperty ("parameterId", id);
        asObject (match)->setProperty ("expected", expected);
        asObject (match)->setProperty ("restored", restored);
        asObject (match)->setProperty ("passed", passed);
        parameterMatches.add (match);
    };

    addBoolMatch ("freeze_infinite", true, restoredSnapshot.freezeInfinite);
    addBoolMatch ("kill", true, restoredSnapshot.kill);

    juce::AudioBuffer<float> probeBuffer (2, kBlockSize);
    probeBuffer.clear();
    for (int sample = 0; sample < kBlockSize; ++sample)
    {
        probeBuffer.setSample (0, sample, sample == 0 ? 0.75f : 0.2f);
        probeBuffer.setSample (1, sample, sample == 1 ? -0.5f : -0.1f);
    }

    juce::MidiBuffer midi;
    restoredProcessor.processBlock (probeBuffer, midi);

    const float outputPeak = computePeak (probeBuffer);
    const bool postRestoreSilence = outputPeak <= kSilenceTolerance;
    if (! postRestoreSilence)
    {
        issues.add (makeIssue (
            "post_restore_processing_mismatch",
            "Restored Mix=100 and Kill=On state did not mute the shell wet-path output as expected."
        ));
    }

    const bool passed = allParametersMatch && postRestoreSilence && issues.isEmpty();
    auto restoredSnapshotObject = makeObject();
    asObject (restoredSnapshotObject)->setProperty ("mix", restoredSnapshot.mix);
    asObject (restoredSnapshotObject)->setProperty ("size", restoredSnapshot.size);
    asObject (restoredSnapshotObject)->setProperty ("gravity", restoredSnapshot.gravity);
    asObject (restoredSnapshotObject)->setProperty ("feedback", restoredSnapshot.feedback);
    asObject (restoredSnapshotObject)->setProperty ("predelayMs", restoredSnapshot.predelayMs);
    asObject (restoredSnapshotObject)->setProperty ("lowTone", restoredSnapshot.lowTone);
    asObject (restoredSnapshotObject)->setProperty ("highTone", restoredSnapshot.highTone);
    asObject (restoredSnapshotObject)->setProperty ("resonance", restoredSnapshot.resonance);
    asObject (restoredSnapshotObject)->setProperty ("modDepth", restoredSnapshot.modDepth);
    asObject (restoredSnapshotObject)->setProperty ("modRateHz", restoredSnapshot.modRateHz);
    asObject (restoredSnapshotObject)->setProperty ("freezeInfinite", restoredSnapshot.freezeInfinite);
    asObject (restoredSnapshotObject)->setProperty ("kill", restoredSnapshot.kill);

    asObject (result)->setProperty ("schemaVersion", 1);
    asObject (result)->setProperty ("mode", "state-roundtrip");
    asObject (result)->setProperty ("passed", passed);
    asObject (result)->setProperty ("stateBytes", static_cast<int> (stateBlock.getSize()));
    asObject (result)->setProperty ("parameterMatches", juce::var (parameterMatches));
    asObject (result)->setProperty ("allParametersMatch", allParametersMatch);
    asObject (result)->setProperty ("restoredSnapshot", restoredSnapshotObject);
    asObject (result)->setProperty ("postRestoreOutputPeak", outputPeak);
    asObject (result)->setProperty ("postRestoreSilence", postRestoreSilence);
    asObject (result)->setProperty ("issues", juce::var (issues));
    return result;
}

bool writeResult (const juce::File& outputFile, const juce::var& result, juce::String& error)
{
    outputFile.getParentDirectory().createDirectory();
    if (! outputFile.replaceWithText (juce::JSON::toString (result, true)))
    {
        error = "Could not write JSON output to " + outputFile.getFullPathName();
        return false;
    }
    return true;
}

juce::String getArgumentValue (const juce::StringArray& args, const juce::String& optionName)
{
    const auto optionIndex = args.indexOf (optionName);
    if (optionIndex < 0 || optionIndex + 1 >= args.size())
        return {};
    return args[optionIndex + 1];
}

void printUsage()
{
    std::cout
        << "Usage: OutSpreadShellVerifier --mode <layout-check|state-roundtrip> [--out <json-path>]\n";
}

class ShellVerifierApplication final : public juce::JUCEApplication
{
public:
    const juce::String getApplicationName() override { return "OutSpreadShellVerifier"; }
    const juce::String getApplicationVersion() override { return "0.1.0"; }
    bool moreThanOneInstanceAllowed() override { return true; }

    void initialise (const juce::String&) override
    {
        const auto args = juce::JUCEApplicationBase::getCommandLineParameterArray();
        const auto mode = getArgumentValue (args, "--mode");
        const auto outputPath = getArgumentValue (args, "--out");

        if (mode.isEmpty())
        {
            printUsage();
            setApplicationReturnValue (1);
            quit();
            return;
        }

        juce::var result;
        if (mode == "layout-check")
        {
            result = buildLayoutCheckResult();
        }
        else if (mode == "state-roundtrip")
        {
            result = buildStateRoundtripResult();
        }
        else
        {
            std::cerr << "error: unsupported mode '" << mode << "'\n";
            printUsage();
            setApplicationReturnValue (1);
            quit();
            return;
        }

        if (! outputPath.isEmpty())
        {
            juce::String error;
            if (! writeResult (juce::File (outputPath), result, error))
            {
                std::cerr << error << "\n";
                setApplicationReturnValue (1);
                quit();
                return;
            }
        }
        else
        {
            std::cout << juce::JSON::toString (result, true) << "\n";
        }

        setApplicationReturnValue (static_cast<bool> (result.getProperty ("passed", false)) ? 0 : 1);
        quit();
    }

    void shutdown() override {}
    void systemRequestedQuit() override { quit(); }
    void anotherInstanceStarted (const juce::String&) override {}
};
} // namespace

START_JUCE_APPLICATION (ShellVerifierApplication)
