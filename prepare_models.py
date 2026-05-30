"""
Prepare model directories for bundling into the installer.

Copies only the necessary files (no flax, no readme, no cache files)
from the user's local model directories to dist/models/.

Run before packaging with Inno Setup.
"""

import os
import shutil
import sys

# Source paths — edit these to match your local setup
WHISPER_SRC = "C:/whisper-models/small"
OPUS_SRC = "C:/Users/saturnshine/.cache/modelscope/hub/models/Helsinki-NLP/opus-mt-en-zh"

# Which files to KEEP per model
WHISPER_KEEP = {
    "model.bin",
    "config.json",
    "tokenizer.json",
    "vocabulary.txt",
}

OPUS_KEEP = {
    "pytorch_model.bin",
    "config.json",
    "tokenizer_config.json",
    "vocab.json",
    "source.spm",
    "target.spm",
    "generation_config.json",
}


def prepare(src, keep, dest_name):
    """Copy only *keep* files from *src* to *dest_name* under dist/models/."""
    base = os.path.abspath(os.path.join(os.path.dirname(__file__), "dist", "models"))
    dest = os.path.join(base, dest_name)
    os.makedirs(dest, exist_ok=True)

    if not os.path.isdir(src):
        print(f"  ERROR: source not found: {src}")
        print(f"  Skipping {dest_name} — installer will be incomplete!")
        return

    copied = 0
    skipped = []
    total_size = 0

    for name in os.listdir(src):
        sp = os.path.join(src, name)
        if not os.path.isfile(sp):
            continue
        if name in keep:
            dp = os.path.join(dest, name)
            shutil.copy2(sp, dp)
            sz = os.path.getsize(dp)
            total_size += sz
            copied += 1
            print(f"  {name} ({sz / 1024 / 1024:.1f} MB)")
        else:
            skipped.append(name)

    if skipped:
        print(f"  Skipped: {', '.join(skipped)}")
    print(f"  → {dest_name}: {copied} files, {total_size / 1024 / 1024:.0f} MB")


if __name__ == "__main__":
    print("Preparing models for installer...")
    print()
    print("[whisper-small]")
    prepare(WHISPER_SRC, WHISPER_KEEP, "whisper-small")
    print()
    print("[opus-mt-en-zh]")
    prepare(OPUS_SRC, OPUS_KEEP, "opus-mt-en-zh")
    print()
    print("Done. Models ready in dist/models/")
