#include "PluginProcessor.h"

juce::AudioProcessor* JUCE_CALLTYPE createPluginFilter()
{
    return new __PLUGIN_NAME__AudioProcessor();
}
