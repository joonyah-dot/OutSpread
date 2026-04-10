cmake_minimum_required(VERSION 3.15)

project(
    OutSpread
    VERSION 0.1.0
)

add_subdirectory(extern/juce)

option(BUILD_VST3_HARNESS "Build VST3 harness CLI" ON)
if(BUILD_VST3_HARNESS)
    add_subdirectory(tools/vst3_harness)
endif()

juce_add_plugin(
    OutSpread
    COMPANY_NAME "KyleAudio"
    IS_SYNTH FALSE
    NEEDS_MIDI_INPUT FALSE
    NEEDS_MIDI_OUTPUT FALSE
    IS_MIDI_EFFECT FALSE
    FORMATS VST3 Standalone
    PRODUCT_NAME "OutSpread"
)

# Generates JuceHeader.h + sets up include paths correctly
juce_generate_juce_header(OutSpread)

# Beginner-safe: avoids VST3/VST2 replacement automation warnings
target_compile_definitions(
    OutSpread
    PRIVATE
    JUCE_VST3_CAN_REPLACE_VST2=0
    JUCE_USE_VST2_SDK=0
)

target_sources(
    OutSpread
    PRIVATE
    Source/OutSpreadParameters.cpp
    Source/OutSpreadParameters.h
    Source/OutSpreadWetEngine.cpp
    Source/OutSpreadWetEngine.h
    Source/PluginProcessor.cpp
    Source/PluginProcessor.h
    Source/PluginEditor.cpp
    Source/PluginEditor.h
    Source/PluginEntry.cpp
)

target_compile_features(
    OutSpread
    PRIVATE cxx_std_17
)

target_link_libraries(
    OutSpread
    PRIVATE
    juce::juce_audio_utils
    juce::juce_dsp
    juce::juce_gui_extra
    juce::juce_recommended_config_flags
    juce::juce_recommended_lto_flags
    juce::juce_recommended_warning_flags
)

juce_add_console_app(
    OutSpreadShellVerifier
    PRODUCT_NAME "OutSpreadShellVerifier"
)

juce_generate_juce_header(OutSpreadShellVerifier)

target_sources(
    OutSpreadShellVerifier
    PRIVATE
    Source/OutSpreadParameters.cpp
    Source/OutSpreadParameters.h
    Source/OutSpreadWetEngine.cpp
    Source/OutSpreadWetEngine.h
    Source/ShellVerifierMain.cpp
    Source/PluginProcessor.cpp
    Source/PluginProcessor.h
    Source/PluginEditor.cpp
    Source/PluginEditor.h
)

target_compile_features(
    OutSpreadShellVerifier
    PRIVATE cxx_std_17
)

target_compile_definitions(
    OutSpreadShellVerifier
    PRIVATE
    JUCE_USE_CURL=0
    JUCE_WEB_BROWSER=0
)

target_link_libraries(
    OutSpreadShellVerifier
    PRIVATE
    juce::juce_audio_utils
    juce::juce_dsp
    juce::juce_gui_extra
    juce::juce_recommended_config_flags
    juce::juce_recommended_lto_flags
    juce::juce_recommended_warning_flags
)
