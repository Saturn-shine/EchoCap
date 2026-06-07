# PyInstaller hook for av (FFmpeg Python bindings).
#
# CRITICAL: .pyd files load DLLs from their OWN directory (or PATH).
# The FFmpeg DLLs in av.libs/ MUST be placed in av/ alongside the .pyd files,
# NOT in a separate av.libs/ directory.
import glob, os
import av as _av

_av_dir = os.path.dirname(_av.__file__)
_av_libs = os.path.join(os.path.dirname(_av_dir), 'av.libs')

# 1. All .pyd files as binaries → av/
binaries = []
for _fn in sorted(os.listdir(_av_dir)):
    if _fn.endswith('.pyd'):
        binaries.append((os.path.join(_av_dir, _fn), 'av'))

# 2. All FFmpeg DLLs as binaries → av/ (SAME DIR as .pyd, not av.libs!)
if os.path.isdir(_av_libs):
    for _fn in sorted(os.listdir(_av_libs)):
        if _fn.endswith('.dll'):
            binaries.append((os.path.join(_av_libs, _fn), 'av'))

# 3. Register all submodules as hidden imports
from PyInstaller.utils.hooks import collect_submodules
hiddenimports = collect_submodules('av')
