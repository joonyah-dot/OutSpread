#include <juce_audio_formats/juce_audio_formats.h>
#include <juce_audio_processors/juce_audio_processors.h>
#include <juce_gui_basics/juce_gui_basics.h>

#include <algorithm>
#include <cmath>
#include <cstdint>
#include <iostream>
#include <limits>
#include <map>
#include <optional>
#include <string>
#include <vector>

namespace
{
using OptionMap = std::map<std::string, std::string>;

struct AudioData
{
    juce::AudioBuffer<float> buffer;
    double sampleRate = 0.0;
};

struct RenderCase
{
    int warmupMs = 50;
    std::optional<double> renderSeconds;
    std::map<std::string, float> paramsByName;
    std::map<int, float> paramsByIndex;
};

struct LevelMetrics
{
    double peakDbfs = -160.0;
    double rmsDbfs = -160.0;
};

void printUsage()
{
    std::cout
        << "vst3_harness usage:\n"
        << "  vst3_harness --help\n"
        << "  vst3_harness --version\n"
        << "  vst3_harness dump-params --plugin <path_to.vst3>\n"
        << "  vst3_harness render --plugin <path.vst3> --in <dry.wav> --outdir <dir> --sr <hz> --bs <samples> --ch <channels> [--case <case.json>]\n"
        << "  vst3_harness analyze --dry <dry.wav> --wet <wet.wav> --outdir <dir> [--auto-align] [--null]\n";
}

int fail(const juce::String& message)
{
    std::cerr << "Error: " << message << "\n";
    return 1;
}

bool startsWithDashes(const std::string& token)
{
    return token.rfind("--", 0) == 0;
}

bool parseOptions(int argc, char* argv[], int startIndex, OptionMap& options, juce::String& error)
{
    for (int i = startIndex; i < argc; ++i)
    {
        const std::string token(argv[i]);

        if (!startsWithDashes(token))
        {
            error = "Unexpected positional argument: " + juce::String(token);
            return false;
        }

        const auto key = token.substr(2);
        if (key.empty())
        {
            error = "Found empty option name";
            return false;
        }

        std::string value = "true";

        if (i + 1 < argc)
        {
            const std::string next(argv[i + 1]);
            if (!startsWithDashes(next))
            {
                value = next;
                ++i;
            }
        }

        options[key] = value;
    }

    return true;
}

bool parseIntStrict(const std::string& text, int& outValue)
{
    try
    {
        size_t endIndex = 0;
        const long value = std::stol(text, &endIndex, 10);
        if (endIndex != text.size())
            return false;
        if (value < std::numeric_limits<int>::min() || value > std::numeric_limits<int>::max())
            return false;
        outValue = static_cast<int>(value);
        return true;
    }
    catch (...)
    {
        return false;
    }
}

bool getRequiredOption(const OptionMap& options,
                       const char* key,
                       juce::String& outValue,
                       juce::String& error)
{
    const auto it = options.find(key);
    if (it == options.end())
    {
        error = "Missing required option --" + juce::String(key);
        return false;
    }

    outValue = it->second;
    return true;
}

bool getOptionalOption(const OptionMap& options, const char* key, juce::String& outValue)
{
    const auto it = options.find(key);
    if (it == options.end())
        return false;

    outValue = it->second;
    return true;
}

bool getRequiredIntOption(const OptionMap& options,
                          const char* key,
                          int& outValue,
                          juce::String& error)
{
    juce::String rawValue;
    if (!getRequiredOption(options, key, rawValue, error))
        return false;

    int parsed = 0;
    if (!parseIntStrict(rawValue.toStdString(), parsed))
    {
        error = "Invalid integer value for --" + juce::String(key) + ": " + rawValue;
        return false;
    }

    outValue = parsed;
    return true;
}

bool getFlag(const OptionMap& options, const char* key)
{
    return options.find(key) != options.end();
}

juce::File resolvePath(const juce::String& pathText)
{
    if (juce::File::isAbsolutePath(pathText))
        return juce::File(pathText);
    return juce::File::getCurrentWorkingDirectory().getChildFile(pathText);
}

bool ensureDirectory(const juce::File& directory, juce::String& error)
{
    if (directory.exists())
    {
        if (!directory.isDirectory())
        {
            error = "Path exists but is not a directory: " + directory.getFullPathName();
            return false;
        }
        return true;
    }

    if (!directory.createDirectory())
    {
        error = "Failed to create directory: " + directory.getFullPathName();
        return false;
    }

    return true;
}

bool readAudioFile(const juce::File& file, AudioData& out, juce::String& error)
{
    if (!file.existsAsFile())
    {
        error = "File not found: " + file.getFullPathName();
        return false;
    }

    juce::AudioFormatManager formatManager;
    formatManager.registerBasicFormats();

    std::unique_ptr<juce::AudioFormatReader> reader(formatManager.createReaderFor(file));
    if (!reader)
    {
        error = "Unsupported or unreadable audio file: " + file.getFullPathName();
        return false;
    }

    if (reader->lengthInSamples <= 0 || reader->lengthInSamples > std::numeric_limits<int>::max())
    {
        error = "Invalid or too-large audio file: " + file.getFullPathName();
        return false;
    }

    const int numChannels = static_cast<int>(reader->numChannels);
    const int numSamples = static_cast<int>(reader->lengthInSamples);

    if (numChannels <= 0)
    {
        error = "Audio file has no channels: " + file.getFullPathName();
        return false;
    }

    out.buffer.setSize(numChannels, numSamples);
    out.buffer.clear();

    std::vector<float*> writePointers(static_cast<size_t>(numChannels));
    for (int channel = 0; channel < numChannels; ++channel)
        writePointers[static_cast<size_t>(channel)] = out.buffer.getWritePointer(channel);

    if (!reader->read(writePointers.data(), numChannels, 0, numSamples))
    {
        error = "Failed to read audio samples from: " + file.getFullPathName();
        return false;
    }

    out.sampleRate = reader->sampleRate;
    return true;
}

bool writeWavFile(const juce::File& file,
                  const juce::AudioBuffer<float>& buffer,
                  double sampleRate,
                  juce::String& error)
{
    juce::WavAudioFormat wavFormat;
    std::unique_ptr<juce::OutputStream> stream(file.createOutputStream());

    if (!stream)
    {
        error = "Failed to open output file for writing: " + file.getFullPathName();
        return false;
    }

    const auto writerOptions = juce::AudioFormatWriterOptions()
        .withSampleRate(sampleRate)
        .withNumChannels(buffer.getNumChannels())
        .withBitsPerSample(24);

    auto writer = wavFormat.createWriterFor(stream, writerOptions);

    if (!writer)
    {
        error = "Failed to create WAV writer for: " + file.getFullPathName();
        return false;
    }

    if (!writer->writeFromAudioSampleBuffer(buffer, 0, buffer.getNumSamples()))
    {
        error = "Failed while writing WAV data: " + file.getFullPathName();
        return false;
    }

    return true;
}

bool parseNumericVar(const juce::var& value, double& outValue)
{
    if (value.isInt() || value.isInt64() || value.isDouble() || value.isBool())
    {
        outValue = static_cast<double>(value);
        return std::isfinite(outValue);
    }

    return false;
}

bool parseNormalizedValue(const juce::var& value,
                          const juce::String& context,
                          float& outValue,
                          juce::String& error)
{
    double normalized = 0.0;
    if (!parseNumericVar(value, normalized))
    {
        error = context + " must be numeric";
        return false;
    }

    if (normalized < 0.0 || normalized > 1.0)
    {
        error = context + " must be within [0, 1]";
        return false;
    }

    outValue = static_cast<float>(normalized);
    return true;
}

bool parseParamsByNameObject(const juce::var& value,
                             std::map<std::string, float>& outParamsByName,
                             juce::String& error)
{
    auto* paramsObject = value.getDynamicObject();
    if (paramsObject == nullptr)
    {
        error = "paramsByName must be a JSON object of name -> normalized value";
        return false;
    }

    const auto& properties = paramsObject->getProperties();
    for (int i = 0; i < properties.size(); ++i)
    {
        const juce::String parameterName = properties.getName(i).toString();
        const juce::var parameterValue = properties.getValueAt(i);

        float normalized = 0.0f;
        if (!parseNormalizedValue(parameterValue,
                                  "Parameter value for '" + parameterName + "'",
                                  normalized,
                                  error))
        {
            return false;
        }

        outParamsByName[parameterName.toLowerCase().toStdString()] = normalized;
    }

    return true;
}

bool parseParamsByIndexObject(const juce::var& value,
                              std::map<int, float>& outParamsByIndex,
                              juce::String& error)
{
    auto* paramsObject = value.getDynamicObject();
    if (paramsObject == nullptr)
    {
        error = "paramsByIndex must be a JSON object of index -> normalized value";
        return false;
    }

    const auto& properties = paramsObject->getProperties();
    for (int i = 0; i < properties.size(); ++i)
    {
        const juce::String indexText = properties.getName(i).toString();
        const juce::var parameterValue = properties.getValueAt(i);

        int index = 0;
        if (!parseIntStrict(indexText.toStdString(), index) || index < 0)
        {
            error = "Parameter index must be a non-negative integer key, got '" + indexText + "'";
            return false;
        }

        float normalized = 0.0f;
        if (!parseNormalizedValue(parameterValue,
                                  "Parameter value for index " + juce::String(index),
                                  normalized,
                                  error))
        {
            return false;
        }

        outParamsByIndex[index] = normalized;
    }

    return true;
}

bool parseRenderCaseFile(const juce::File& caseFile, RenderCase& renderCase, juce::String& error)
{
    if (!caseFile.existsAsFile())
    {
        error = "Case file not found: " + caseFile.getFullPathName();
        return false;
    }

    juce::var parsedJson;
    const auto parseResult = juce::JSON::parse(caseFile.loadFileAsString(), parsedJson);
    if (parseResult.failed())
    {
        error = "Failed to parse JSON case file: " + parseResult.getErrorMessage();
        return false;
    }

    auto* rootObject = parsedJson.getDynamicObject();
    if (rootObject == nullptr)
    {
        error = "Case file root must be a JSON object";
        return false;
    }

    if (rootObject->hasProperty("warmupMs"))
    {
        double warmup = 0.0;
        if (!parseNumericVar(rootObject->getProperty("warmupMs"), warmup) || warmup < 0.0)
        {
            error = "warmupMs must be a non-negative number";
            return false;
        }
        renderCase.warmupMs = static_cast<int>(std::round(warmup));
    }

    if (rootObject->hasProperty("renderSeconds"))
    {
        double renderSeconds = 0.0;
        if (!parseNumericVar(rootObject->getProperty("renderSeconds"), renderSeconds) || renderSeconds <= 0.0)
        {
            error = "renderSeconds must be a positive number";
            return false;
        }
        renderCase.renderSeconds = renderSeconds;
    }

    if (rootObject->hasProperty("paramsByName")
        && !parseParamsByNameObject(rootObject->getProperty("paramsByName"), renderCase.paramsByName, error))
    {
        return false;
    }

    // Backward-compatibility alias for older case files.
    if (rootObject->hasProperty("params")
        && !parseParamsByNameObject(rootObject->getProperty("params"), renderCase.paramsByName, error))
    {
        return false;
    }

    if (rootObject->hasProperty("paramsByIndex")
        && !parseParamsByIndexObject(rootObject->getProperty("paramsByIndex"), renderCase.paramsByIndex, error))
    {
        return false;
    }

    return true;
}

bool loadVst3Description(juce::AudioPluginFormatManager& manager,
                         const juce::File& pluginPath,
                         juce::PluginDescription& outDescription,
                         juce::String& error)
{
    if (!pluginPath.exists())
    {
        error = "Plugin path does not exist: " + pluginPath.getFullPathName();
        return false;
    }

    auto* format = manager.getFormat(0);
    if (format == nullptr)
    {
        error = "No plugin formats are registered";
        return false;
    }

    juce::StringArray scanCandidates;

    if (pluginPath.isDirectory() && pluginPath.hasFileExtension(".vst3"))
    {
        juce::Array<juce::File> nestedPluginBinaries;
        pluginPath.findChildFiles(nestedPluginBinaries, juce::File::findFiles, true, "*.vst3");
        for (const auto& nestedFile : nestedPluginBinaries)
            scanCandidates.addIfNotAlreadyThere(nestedFile.getFullPathName());
    }

    scanCandidates.addIfNotAlreadyThere(pluginPath.getFullPathName());

    for (const auto& candidate : scanCandidates)
    {
        juce::OwnedArray<juce::PluginDescription> foundTypes;
        format->findAllTypesForFile(foundTypes, candidate);
        if (!foundTypes.isEmpty())
        {
            outDescription = *foundTypes.getFirst();
            return true;
        }
    }

    error = "No VST3 plugin types found in: " + pluginPath.getFullPathName();
    return false;
}

std::unique_ptr<juce::AudioPluginInstance> createVst3Instance(const juce::File& pluginPath,
                                                              double sampleRate,
                                                              int blockSize,
                                                              juce::String& error)
{
    juce::AudioPluginFormatManager formatManager;
    formatManager.addFormat(std::make_unique<juce::VST3PluginFormat>());

    juce::PluginDescription description;
    if (!loadVst3Description(formatManager, pluginPath, description, error))
        return nullptr;

    auto instance = formatManager.createPluginInstance(description, sampleRate, blockSize, error);
    if (instance == nullptr && error.isEmpty())
        error = "Plugin instantiation failed with no additional error detail";

    return instance;
}

juce::AudioChannelSet makeChannelSet(int channels)
{
    if (channels <= 1)
        return juce::AudioChannelSet::mono();
    if (channels == 2)
        return juce::AudioChannelSet::stereo();
    return juce::AudioChannelSet::discreteChannels(channels);
}

bool configurePluginForChannels(juce::AudioPluginInstance& instance,
                                int channels,
                                double sampleRate,
                                int blockSize,
                                juce::String& error)
{
    if (channels <= 0)
    {
        error = "Channel count must be positive";
        return false;
    }

    instance.enableAllBuses();

    juce::AudioProcessor::BusesLayout layout;
    const auto requestedChannels = makeChannelSet(channels);
    layout.inputBuses.add(requestedChannels);
    layout.outputBuses.add(requestedChannels);

    if (!instance.setBusesLayout(layout))
        instance.disableNonMainBuses();

    instance.setRateAndBufferSizeDetails(sampleRate, blockSize);

    if (instance.getTotalNumOutputChannels() <= 0)
    {
        error = "Plugin reports zero output channels";
        return false;
    }

    return true;
}

bool applyParameterMapByName(juce::AudioPluginInstance& instance,
                             const std::map<std::string, float>& parameterValues,
                             juce::String& error)
{
    auto& parameters = instance.getParameters();

    for (const auto& [nameLowercase, normalizedValue] : parameterValues)
    {
        bool found = false;

        for (int i = 0; i < parameters.size(); ++i)
        {
            auto* parameter = parameters.getUnchecked(i);
            if (parameter == nullptr)
                continue;

            const auto parameterName = parameter->getName(256).toLowerCase().toStdString();
            if (parameterName == nameLowercase)
            {
                parameter->setValueNotifyingHost(normalizedValue);
                found = true;
                break;
            }
        }

        if (!found)
        {
            error = "Could not find plugin parameter named: " + juce::String(nameLowercase);
            return false;
        }
    }

    return true;
}

bool applyParameterMapByIndex(juce::AudioPluginInstance& instance,
                              const std::map<int, float>& parameterValues,
                              juce::String& error)
{
    auto& parameters = instance.getParameters();

    for (const auto& [index, normalizedValue] : parameterValues)
    {
        if (index < 0 || index >= parameters.size())
        {
            error = "Parameter index out of range: " + juce::String(index)
                  + " (num parameters: " + juce::String(parameters.size()) + ")";
            return false;
        }

        auto* parameter = parameters.getUnchecked(index);
        if (parameter == nullptr)
        {
            error = "Plugin parameter at index " + juce::String(index) + " is null";
            return false;
        }

        parameter->setValueNotifyingHost(normalizedValue);
    }

    return true;
}

juce::AudioBuffer<float> copyChannels(const juce::AudioBuffer<float>& source, int channels)
{
    const int sourceChannels = source.getNumChannels();
    const int sourceSamples = source.getNumSamples();

    juce::AudioBuffer<float> result(channels, sourceSamples);
    result.clear();

    if (sourceChannels <= 0)
        return result;

    for (int channel = 0; channel < channels; ++channel)
    {
        const int sourceChannel = std::min(channel, sourceChannels - 1);
        result.copyFrom(channel, 0, source, sourceChannel, 0, sourceSamples);
    }

    return result;
}

bool containsNaNOrInf(const juce::AudioBuffer<float>& buffer)
{
    for (int channel = 0; channel < buffer.getNumChannels(); ++channel)
    {
        const float* samples = buffer.getReadPointer(channel);
        for (int i = 0; i < buffer.getNumSamples(); ++i)
        {
            if (!std::isfinite(samples[i]))
                return true;
        }
    }

    return false;
}

LevelMetrics computeLevels(const juce::AudioBuffer<float>& buffer)
{
    LevelMetrics metrics;

    if (buffer.getNumChannels() <= 0 || buffer.getNumSamples() <= 0)
        return metrics;

    double peak = 0.0;
    double sumSquares = 0.0;

    for (int channel = 0; channel < buffer.getNumChannels(); ++channel)
    {
        const float* samples = buffer.getReadPointer(channel);
        for (int i = 0; i < buffer.getNumSamples(); ++i)
        {
            const double value = static_cast<double>(samples[i]);
            peak = std::max(peak, std::abs(value));
            sumSquares += value * value;
        }
    }

    const double count = static_cast<double>(buffer.getNumChannels()) * static_cast<double>(buffer.getNumSamples());
    const double rms = count > 0.0 ? std::sqrt(sumSquares / count) : 0.0;

    metrics.peakDbfs = juce::Decibels::gainToDecibels(static_cast<float>(peak), -160.0f);
    metrics.rmsDbfs = juce::Decibels::gainToDecibels(static_cast<float>(rms), -160.0f);
    return metrics;
}

std::vector<float> makeMonoSum(const juce::AudioBuffer<float>& buffer)
{
    const int channels = buffer.getNumChannels();
    const int numSamples = buffer.getNumSamples();
    std::vector<float> mono(static_cast<size_t>(numSamples), 0.0f);

    if (channels <= 0 || numSamples <= 0)
        return mono;

    const float scale = 1.0f / static_cast<float>(channels);
    for (int channel = 0; channel < channels; ++channel)
    {
        const float* samples = buffer.getReadPointer(channel);
        for (int i = 0; i < numSamples; ++i)
            mono[static_cast<size_t>(i)] += samples[i] * scale;
    }

    return mono;
}

int detectLatencyByCrossCorrelation(const std::vector<float>& dry,
                                    const std::vector<float>& wet,
                                    int maxLagSamples)
{
    int bestLag = 0;
    double bestScore = -1.0;

    const int drySize = static_cast<int>(dry.size());
    const int wetSize = static_cast<int>(wet.size());

    for (int lag = -maxLagSamples; lag <= maxLagSamples; ++lag)
    {
        const int dryStart = lag < 0 ? -lag : 0;
        const int wetStart = lag > 0 ? lag : 0;
        const int overlap = std::min(drySize - dryStart, wetSize - wetStart);

        if (overlap <= 0)
            continue;

        double dot = 0.0;
        double dryEnergy = 0.0;
        double wetEnergy = 0.0;

        for (int i = 0; i < overlap; ++i)
        {
            const double drySample = static_cast<double>(dry[static_cast<size_t>(dryStart + i)]);
            const double wetSample = static_cast<double>(wet[static_cast<size_t>(wetStart + i)]);
            dot += drySample * wetSample;
            dryEnergy += drySample * drySample;
            wetEnergy += wetSample * wetSample;
        }

        if (dryEnergy <= 0.0 || wetEnergy <= 0.0)
            continue;

        const double correlation = dot / std::sqrt(dryEnergy * wetEnergy);
        const double score = std::abs(correlation);

        if (score > bestScore)
        {
            bestScore = score;
            bestLag = lag;
        }
    }

    return bestLag;
}

juce::AudioBuffer<float> shiftAndResize(const juce::AudioBuffer<float>& source,
                                        int channels,
                                        int targetSamples,
                                        int shiftSamples)
{
    juce::AudioBuffer<float> result(channels, targetSamples);
    result.clear();

    for (int channel = 0; channel < channels; ++channel)
    {
        const int sourceChannel = std::min(channel, source.getNumChannels() - 1);
        const float* sourceData = source.getReadPointer(sourceChannel);
        float* destData = result.getWritePointer(channel);
        const int sourceSamples = source.getNumSamples();

        for (int i = 0; i < targetSamples; ++i)
        {
            const int sourceIndex = i - shiftSamples;
            if (sourceIndex >= 0 && sourceIndex < sourceSamples)
                destData[i] = sourceData[sourceIndex];
        }
    }

    return result;
}

double computeCorrelation(const juce::AudioBuffer<float>& a, const juce::AudioBuffer<float>& b)
{
    const auto monoA = makeMonoSum(a);
    const auto monoB = makeMonoSum(b);

    if (monoA.size() != monoB.size() || monoA.empty())
        return 0.0;

    double dot = 0.0;
    double energyA = 0.0;
    double energyB = 0.0;

    for (size_t i = 0; i < monoA.size(); ++i)
    {
        const double x = static_cast<double>(monoA[i]);
        const double y = static_cast<double>(monoB[i]);
        dot += x * y;
        energyA += x * x;
        energyB += y * y;
    }

    if (energyA <= 0.0 || energyB <= 0.0)
        return 0.0;

    return dot / std::sqrt(energyA * energyB);
}

int runDumpParams(const OptionMap& options)
{
    juce::String pluginPathText;
    juce::String error;

    if (!getRequiredOption(options, "plugin", pluginPathText, error))
        return fail(error);

    const juce::File pluginPath = resolvePath(pluginPathText);
    auto instance = createVst3Instance(pluginPath, 48000.0, 256, error);
    if (instance == nullptr)
        return fail(error);

    auto& parameters = instance->getParameters();
    for (int i = 0; i < parameters.size(); ++i)
    {
        auto* parameter = parameters.getUnchecked(i);
        if (parameter == nullptr)
            continue;

        const auto name = parameter->getName(256);
        const auto defaultNormalized = parameter->getDefaultValue();
        std::cout << i << "\t" << name.toStdString() << "\t" << defaultNormalized << "\n";
    }

    return 0;
}

int runRender(const OptionMap& options)
{
    juce::String pluginPathText;
    juce::String inputPathText;
    juce::String outDirText;
    juce::String casePathText;
    juce::String error;
    int sampleRate = 0;
    int blockSize = 0;
    int channels = 0;

    if (!getRequiredOption(options, "plugin", pluginPathText, error)
        || !getRequiredOption(options, "in", inputPathText, error)
        || !getRequiredOption(options, "outdir", outDirText, error)
        || !getRequiredIntOption(options, "sr", sampleRate, error)
        || !getRequiredIntOption(options, "bs", blockSize, error)
        || !getRequiredIntOption(options, "ch", channels, error))
    {
        return fail(error);
    }

    if (sampleRate <= 0 || blockSize <= 0 || channels <= 0)
        return fail("sr, bs, and ch must be positive");

    const juce::File pluginPath = resolvePath(pluginPathText);
    const juce::File inputPath = resolvePath(inputPathText);
    const juce::File outDir = resolvePath(outDirText);

    RenderCase renderCase;
    if (getOptionalOption(options, "case", casePathText))
    {
        const juce::File casePath = resolvePath(casePathText);
        if (!parseRenderCaseFile(casePath, renderCase, error))
            return fail(error);
    }

    AudioData dryAudio;
    if (!readAudioFile(inputPath, dryAudio, error))
        return fail(error);

    if (std::abs(dryAudio.sampleRate - static_cast<double>(sampleRate)) > 1.0e-6)
    {
        return fail("Input WAV sample rate (" + juce::String(dryAudio.sampleRate)
                    + ") does not match --sr (" + juce::String(sampleRate) + ")");
    }

    auto dryBuffer = copyChannels(dryAudio.buffer, channels);

    int renderSamples = dryBuffer.getNumSamples();
    if (renderCase.renderSeconds.has_value())
        renderSamples = static_cast<int>(std::round(renderCase.renderSeconds.value() * static_cast<double>(sampleRate)));

    if (renderSamples <= 0)
        return fail("Render length must be positive");

    auto plugin = createVst3Instance(pluginPath, static_cast<double>(sampleRate), blockSize, error);
    if (plugin == nullptr)
        return fail(error);

    if (!configurePluginForChannels(*plugin, channels, static_cast<double>(sampleRate), blockSize, error))
        return fail(error);

    plugin->setRateAndBufferSizeDetails(static_cast<double>(sampleRate), blockSize);
    plugin->prepareToPlay(static_cast<double>(sampleRate), blockSize);

    if (!applyParameterMapByIndex(*plugin, renderCase.paramsByIndex, error))
        return fail(error);

    if (!applyParameterMapByName(*plugin, renderCase.paramsByName, error))
        return fail(error);

    plugin->reset();

    const int processChannels = std::max({ channels, plugin->getTotalNumInputChannels(), plugin->getTotalNumOutputChannels(), 1 });
    juce::AudioBuffer<float> ioBlock(processChannels, blockSize);
    juce::MidiBuffer midi;

    const int warmupSamples = static_cast<int>(
        std::round(static_cast<double>(sampleRate) * static_cast<double>(renderCase.warmupMs) / 1000.0));

    for (int pos = 0; pos < warmupSamples; pos += blockSize)
    {
        ioBlock.clear();
        plugin->processBlock(ioBlock, midi);
        midi.clear();
    }

    juce::AudioBuffer<float> wetBuffer(channels, renderSamples);
    wetBuffer.clear();

    const int drySamples = dryBuffer.getNumSamples();
    for (int pos = 0; pos < renderSamples; pos += blockSize)
    {
        const int thisBlock = std::min(blockSize, renderSamples - pos);
        ioBlock.clear();

        for (int channel = 0; channel < std::min(channels, ioBlock.getNumChannels()); ++channel)
        {
            const int remainingDry = std::max(0, drySamples - pos);
            const int copyCount = std::min(thisBlock, remainingDry);
            if (copyCount > 0)
            {
                ioBlock.copyFrom(channel, 0, dryBuffer, channel, pos, copyCount);
            }
        }

        plugin->processBlock(ioBlock, midi);
        midi.clear();

        for (int channel = 0; channel < channels; ++channel)
        {
            if (channel < ioBlock.getNumChannels())
                wetBuffer.copyFrom(channel, pos, ioBlock, channel, 0, thisBlock);
        }
    }

    plugin->releaseResources();

    if (!ensureDirectory(outDir, error))
        return fail(error);

    const juce::File wetPath = outDir.getChildFile("wet.wav");
    if (!writeWavFile(wetPath, wetBuffer, static_cast<double>(sampleRate), error))
        return fail(error);

    std::cout << "Wrote: " << wetPath.getFullPathName() << "\n";
    return 0;
}

int runAnalyze(const OptionMap& options)
{
    juce::String dryPathText;
    juce::String wetPathText;
    juce::String outDirText;
    juce::String error;

    if (!getRequiredOption(options, "dry", dryPathText, error)
        || !getRequiredOption(options, "wet", wetPathText, error)
        || !getRequiredOption(options, "outdir", outDirText, error))
    {
        return fail(error);
    }

    const bool autoAlign = getFlag(options, "auto-align");
    const bool doNull = getFlag(options, "null");

    AudioData dryAudio;
    AudioData wetAudio;

    if (!readAudioFile(resolvePath(dryPathText), dryAudio, error))
        return fail(error);

    if (!readAudioFile(resolvePath(wetPathText), wetAudio, error))
        return fail(error);

    if (std::abs(dryAudio.sampleRate - wetAudio.sampleRate) > 1.0e-6)
    {
        return fail("Sample rate mismatch between dry and wet files: "
                    + juce::String(dryAudio.sampleRate) + " vs " + juce::String(wetAudio.sampleRate));
    }

    const int channels = std::min(dryAudio.buffer.getNumChannels(), wetAudio.buffer.getNumChannels());
    if (channels <= 0)
        return fail("Dry/wet audio must each contain at least one channel");

    int detectedLatencySamples = 0;
    if (autoAlign)
    {
        const auto dryMono = makeMonoSum(copyChannels(dryAudio.buffer, channels));
        const auto wetMono = makeMonoSum(copyChannels(wetAudio.buffer, channels));
        detectedLatencySamples = detectLatencyByCrossCorrelation(dryMono, wetMono, 4096);
    }

    const int targetSamples = std::max(dryAudio.buffer.getNumSamples(), wetAudio.buffer.getNumSamples())
                            + std::abs(detectedLatencySamples);

    const auto dryAligned = shiftAndResize(dryAudio.buffer, channels, targetSamples, 0);
    const auto wetAligned = shiftAndResize(wetAudio.buffer, channels, targetSamples, -detectedLatencySamples);
    const auto wetMetrics = computeLevels(wetAligned);
    const double correlation = computeCorrelation(dryAligned, wetAligned);
    const bool hasNaNOrInfWet = containsNaNOrInf(wetAligned);

    bool hasNaNOrInfDelta = false;
    LevelMetrics deltaMetrics;
    juce::AudioBuffer<float> delta;

    if (doNull)
    {
        delta.makeCopyOf(wetAligned);
        for (int channel = 0; channel < delta.getNumChannels(); ++channel)
            delta.addFrom(channel, 0, dryAligned, channel, 0, delta.getNumSamples(), -1.0f);

        deltaMetrics = computeLevels(delta);
        hasNaNOrInfDelta = containsNaNOrInf(delta);
    }

    const juce::File outDir = resolvePath(outDirText);
    if (!ensureDirectory(outDir, error))
        return fail(error);

    if (doNull)
    {
        const juce::File deltaPath = outDir.getChildFile("delta.wav");
        if (!writeWavFile(deltaPath, delta, dryAudio.sampleRate, error))
            return fail(error);
    }

    juce::DynamicObject::Ptr metricsObject = new juce::DynamicObject();
    metricsObject->setProperty("sampleRate", dryAudio.sampleRate);
    metricsObject->setProperty("channels", channels);
    metricsObject->setProperty("numSamples", targetSamples);
    metricsObject->setProperty("detectedLatencySamples", detectedLatencySamples);
    metricsObject->setProperty("wetPeakDbfs", wetMetrics.peakDbfs);
    metricsObject->setProperty("wetRmsDbfs", wetMetrics.rmsDbfs);
    metricsObject->setProperty("correlation", correlation);
    metricsObject->setProperty("hasNaNOrInfWet", hasNaNOrInfWet);
    metricsObject->setProperty("hasNaNOrInfDelta", hasNaNOrInfDelta);

    if (doNull)
    {
        metricsObject->setProperty("deltaPeakDbfs", deltaMetrics.peakDbfs);
        metricsObject->setProperty("deltaRmsDbfs", deltaMetrics.rmsDbfs);
    }

    const juce::File metricsPath = outDir.getChildFile("metrics.json");
    const auto metricsJson = juce::JSON::toString(
        juce::var(metricsObject.get()),
        juce::JSON::FormatOptions().withSpacing(juce::JSON::Spacing::multiLine).withEncoding(juce::JSON::Encoding::ascii));

    if (!metricsPath.replaceWithText(metricsJson))
        return fail("Failed to write metrics JSON: " + metricsPath.getFullPathName());

    if (hasNaNOrInfWet || hasNaNOrInfDelta)
    {
        std::cerr << "Error: NaN/Inf detected in output buffers\n";
        return 2;
    }

    std::cout << "Wrote: " << metricsPath.getFullPathName() << "\n";
    return 0;
}

} // namespace

int main(int argc, char* argv[])
{
    juce::ScopedJuceInitialiser_GUI juceInit;

    if (argc <= 1)
    {
        printUsage();
        return 0;
    }

    const juce::String firstArg(argv[1]);

    if (firstArg == "--help" || firstArg == "-h")
    {
        printUsage();
        return 0;
    }

    if (firstArg == "--version")
    {
        std::cout << "vst3_harness 0.2.0\n";
        return 0;
    }

    OptionMap options;
    juce::String parseError;
    if (!parseOptions(argc, argv, 2, options, parseError))
        return fail(parseError);

    if (firstArg == "dump-params")
        return runDumpParams(options);
    if (firstArg == "render")
        return runRender(options);
    if (firstArg == "analyze")
        return runAnalyze(options);

    return fail("Unknown subcommand: " + firstArg);
}
