juce_add_console_app(
    vst3_harness
    PRODUCT_NAME "vst3_harness"
)

target_sources(
    vst3_harness
    PRIVATE
    src/main.cpp
)

target_compile_features(
    vst3_harness
    PRIVATE cxx_std_17
)

target_compile_definitions(
    vst3_harness
    PRIVATE
    JUCE_PLUGINHOST_VST3=1
    JUCE_PLUGINHOST_VST=0
    JUCE_PLUGINHOST_AU=0
    JUCE_PLUGINHOST_LV2=0
    JUCE_USE_CURL=0
    JUCE_WEB_BROWSER=0
)

target_link_libraries(
    vst3_harness
    PRIVATE
    juce::juce_core
    juce::juce_events
    juce::juce_audio_basics
    juce::juce_audio_formats
    juce::juce_audio_processors
    juce::juce_gui_basics
    juce::juce_recommended_config_flags
    juce::juce_recommended_lto_flags
    juce::juce_recommended_warning_flags
)
