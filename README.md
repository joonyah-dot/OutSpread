# OutSpread

JUCE + CMake + VS Code template project.

## First-time after cloning
`git submodule update --init --recursive`

## Build + Install (Debug)
VS Code: Terminal → Run Task → **Build VST3 (Debug) + Install**

Or terminal:
`cmake --build build --config Debug --target OutSpread_VST3`

## Notes
- Default VST3 install path: `C:\Program Files\Common Files\VST3\`
- Copy step may require running VS Code as Administrator.
