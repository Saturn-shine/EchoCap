# PyInstaller hook for tokenizers (Cython .pyd extension)
import os
import tokenizers as _tk

_tk_dir = os.path.dirname(_tk.__file__)

binaries = []
# Collect .pyd files in the tokenizers package
for _fn in sorted(os.listdir(_tk_dir)):
    if _fn.endswith('.pyd'):
        binaries.append((os.path.join(_tk_dir, _fn), 'tokenizers'))

# Also check for a tokenizers.libs directory
_tk_libs = os.path.join(os.path.dirname(_tk_dir), 'tokenizers.libs')
if os.path.isdir(_tk_libs):
    for _fn in sorted(os.listdir(_tk_libs)):
        if _fn.endswith('.dll'):
            binaries.append((os.path.join(_tk_libs, _fn), 'tokenizers'))

from PyInstaller.utils.hooks import collect_submodules
hiddenimports = collect_submodules('tokenizers')
