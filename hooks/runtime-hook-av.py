# Runtime hook: pre-import av before the frozen importer tries.
# av's Cython .pyd files use delvewheel DLL patching which PyInstaller
# cannot replicate. If av fails, inject a minimal stub so that
# faster_whisper.audio (which only uses av for reading audio FILES)
# doesn't crash EchoCap — we feed raw PCM from sounddevice, never files.
try:
    import av
except Exception:
    import sys as _sys
    import types as _types
    _stub = _types.ModuleType('av')
    _stub.__dict__.update({
        'AudioFrame': type('AudioFrame', (), {}),
        'AudioFormat': type('AudioFormat', (), {}),
        'AudioLayout': type('AudioLayout', (), {}),
        'AudioResampler': type('AudioResampler', (), {}),
        'CodecContext': type('CodecContext', (), {}),
        'VideoFrame': type('VideoFrame', (), {}),
        'open': lambda *a, **kw: None,
        'time_base': 1,
        'library_versions': {},
        'ffmpeg_version_info': '',
        '__version__': 'stub',
        '__file__': __file__,
    })
    _sys.modules['av'] = _stub
    _sys.modules['av._core'] = _types.ModuleType('av._core')
    _sys.modules['av.audio'] = _types.ModuleType('av.audio')
    _sys.modules['av.audio.frame'] = _types.ModuleType('av.audio.frame')
    _sys.modules['av.audio.format'] = _types.ModuleType('av.audio.format')
    _sys.modules['av.audio.layout'] = _types.ModuleType('av.audio.layout')
    _sys.modules['av.audio.resampler'] = _types.ModuleType('av.audio.resampler')
    _sys.modules['av.container'] = _types.ModuleType('av.container')
    _sys.modules['av.codec'] = _types.ModuleType('av.codec')
    _sys.modules['av.codec.context'] = _types.ModuleType('av.codec.context')
    _sys.modules['av.filter'] = _types.ModuleType('av.filter')
    _sys.modules['av.format'] = _types.ModuleType('av.format')
    _sys.modules['av.packet'] = _types.ModuleType('av.packet')
    _sys.modules['av.stream'] = _types.ModuleType('av.stream')
    _sys.modules['av.subtitles'] = _types.ModuleType('av.subtitles')
    _sys.modules['av.video'] = _types.ModuleType('av.video')
    _sys.modules['av.video.frame'] = _types.ModuleType('av.video.frame')
    _sys.modules['av.sidedata'] = _types.ModuleType('av.sidedata')
    _sys.modules['av.error'] = _types.ModuleType('av.error')
    _sys.modules['av.utils'] = _types.ModuleType('av.utils')
    _sys.modules['av.datasets'] = _types.ModuleType('av.datasets')
    _sys.modules['av.option'] = _types.ModuleType('av.option')
    _sys.modules['av.dictionary'] = _types.ModuleType('av.dictionary')
    _sys.modules['av.logging'] = _types.ModuleType('av.logging')
    _sys.modules['av.bitstream'] = _types.ModuleType('av.bitstream')
    _sys.modules['av.descriptor'] = _types.ModuleType('av.descriptor')
    _sys.modules['av.opaque'] = _types.ModuleType('av.opaque')
    _sys.modules['av.plane'] = _types.ModuleType('av.plane')
    _sys.modules['av.index'] = _types.ModuleType('av.index')
    _sys.modules['av.buffer'] = _types.ModuleType('av.buffer')
    _sys.modules['av.frame'] = _types.ModuleType('av.frame')
    _sys.modules['av.device'] = _types.ModuleType('av.device')
