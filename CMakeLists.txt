cmake_minimum_required(VERSION 3.15)

project(
    __PLUGIN_NAME__
    VERSION 0.1.0
)

add_subdirectory(extern/juce)

option(BUILD_VST3_HARNESS "Build VST3 harness CLI" ON)
if(BUILD_VST3_HARNESS)
    add_subdirectory(tools/vst3_harness)
endif()

juce_add_plugin(
    __PLUGIN_NAME__
    COMPANY_NAME "YourCompanyOrName"
    IS_SYNTH FALSE
    NEEDS_MIDI_INPUT FALSE
    NEEDS_MIDI_OUTPUT FALSE
    IS_MIDI_EFFECT FALSE
    FORMATS VST3 Standalone
    PRODUCT_NAME "__PLUGIN_NAME__"
)

# Generates JuceHeader.h + sets up include paths correctly
juce_generate_juce_header(__PLUGIN_NAME__)

# Beginner-safe: avoids VST3/VST2 replacement automation warnings
target_compile_definitions(
    __PLUGIN_NAME__
    PRIVATE
    JUCE_VST3_CAN_REPLACE_VST2=0
    JUCE_USE_VST2_SDK=0
)

target_sources(
    __PLUGIN_NAME__
    PRIVATE
    Source/PluginProcessor.cpp
    Source/PluginProcessor.h
    Source/PluginEditor.cpp
    Source/PluginEditor.h
    Source/PluginEntry.cpp
)

target_compile_features(
    __PLUGIN_NAME__
    PRIVATE cxx_std_17
)

target_link_libraries(
    __PLUGIN_NAME__
    PRIVATE
    juce::juce_audio_utils
    juce::juce_dsp
    juce::juce_gui_extra
    juce::juce_recommended_config_flags
    juce::juce_recommended_lto_flags
    juce::juce_recommended_warning_flags
)
