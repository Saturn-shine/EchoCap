"""
Streaming speech pipeline: incremental ASR + translation with low latency.

Core design:
  - VAD detects speech start
  - Every ~400 ms of new speech, run ASR on ALL accumulated audio (growing window)
  - Display full result each time -> visual effect of words "appearing" as spoken
  - 250 ms silence -> final flush, reset
  - Max segment 2.5 s -> force flush to prevent long buffering
"""

import logging
import queue
import numpy as np
import threading
import time
import webrtcvad
from datetime import datetime

from paths import TRANSCRIPTS_PATH

logger = logging.getLogger(__name__)


def save_transcript(en, zh, path=None):
    if path is None:
        path = TRANSCRIPTS_PATH
    ts = datetime.now().strftime("%H:%M:%S")
    zh_part = f"  |  {zh}" if zh else ""
    try:
        with open(path, "a", encoding="utf-8") as f:
            f.write(f"[{ts}] {en}{zh_part}\n")
    except Exception:
        pass


class StreamingPipeline:
    """Incrementally processes speech audio and emits results to the UI.

    Runs its own background thread. Call start() / stop().
    """

    def __init__(self, asr_engine, translator, overlay_window, *,
                 sample_rate=16000, chunk_ms=20, vad_mode=1,
                 process_interval_s=0.4, silence_timeout_s=0.7,
                 max_segment_s=4.0, min_speech_s=0.5, device=None,
                 text_queue=None):
        self.asr = asr_engine
        self.translator = translator
        self.window = overlay_window

        self.sample_rate = sample_rate
        self.chunk_ms = chunk_ms
        self.chunk_samples = int(sample_rate * chunk_ms / 1000)

        self.process_interval_s = process_interval_s
        self.silence_timeout_s = silence_timeout_s
        self.max_segment_s = max_segment_s
        self.min_speech_s = min_speech_s
        self._audio_device = device
        self._text_queue = text_queue

        self._vad = webrtcvad.Vad(vad_mode)
        self._audio_queue = queue.Queue(maxsize=200)
        self._running = False
        self._paused = False
        self._thread = None
        self._capture = None

    # ------------------------------------------------------------------
    # Lifecycle
    # ------------------------------------------------------------------

    def start(self):
        """Launch audio capture and processing thread."""
        import sounddevice as sd

        self._running = True
        self._thread = threading.Thread(target=self._run, daemon=True)
        self._thread.start()

        self._capture = sd.InputStream(
            samplerate=self.sample_rate,
            channels=1,
            device=self._audio_device,
            callback=self._audio_callback,
            blocksize=self.chunk_samples,
            dtype='float32',
            latency='low',
        )
        self._capture.start()
        logger.info("Streaming started (%dHz, %dms chunks, process every %.1fs)",
                     self.sample_rate, self.chunk_ms, self.process_interval_s)

    def stop(self):
        self._running = False
        if self._capture:
            self._capture.stop()
            self._capture.close()
            self._capture = None
        logger.info("Pipeline stopped.")

    def set_paused(self, paused):
        self._paused = paused

    # ------------------------------------------------------------------
    # Audio callback
    # ------------------------------------------------------------------

    def _audio_callback(self, indata, frames, time_info, status):
        if status:
            logger.warning("Audio callback status: %s", status)
        chunk = indata[:, 0].copy()
        self._audio_queue.put(chunk)
        # VU meter RMS
        rms = float(np.sqrt(np.mean(chunk.astype(np.float64) ** 2)))
        if rms < 1e-9:
            self._current_rms = 0.0
        else:
            db = 20.0 * np.log10(rms)
            self._current_rms = max(0.0, min(1.0, (db + 60.0) / 60.0))

    @property
    def current_rms(self) -> float:
        return getattr(self, '_current_rms', 0.0)

    # ------------------------------------------------------------------
    # Processing loop
    # ------------------------------------------------------------------

    def _run(self):
        """Background thread: consume audio chunks, drive incremental ASR."""
        logger.debug("Processing thread started.")

        speech_audio = []          # list of float32 chunks since speech start
        in_speech = False
        silence_frames = 0
        last_process_time = 0.0
        silence_threshold_frames = int(self.silence_timeout_s * 1000 / self.chunk_ms)
        min_speech_frames = int(self.min_speech_s * 1000 / self.chunk_ms)
        max_frames = int(self.max_segment_s * 1000 / self.chunk_ms)

        while self._running:
            try:
                chunk = self._audio_queue.get(timeout=0.05)
            except queue.Empty:
                continue

            if self._paused:
                continue

            is_speech = self._vad.is_speech(
                (chunk * 32767).astype(np.int16).tobytes(), self.sample_rate
            )

            now = time.perf_counter()

            if is_speech and not in_speech:
                # ---- speech START ----
                in_speech = True
                speech_audio = [chunk]
                silence_frames = 0
                last_process_time = now

            elif is_speech and in_speech:
                # ---- speech CONTINUES ----
                speech_audio.append(chunk)
                silence_frames = 0

                elapsed = now - last_process_time
                total_s = len(speech_audio) * self.chunk_ms / 1000

                # Process incrementally every process_interval_s
                if elapsed >= self.process_interval_s and total_s >= self.min_speech_s:
                    self._process(np.concatenate(speech_audio), final=False)
                    last_process_time = now

                # Force flush if segment too long
                if len(speech_audio) >= max_frames:
                    self._process(np.concatenate(speech_audio), final=True)
                    # Keep last bit for overlap/context
                    overlap_frames = int(0.3 * 1000 / self.chunk_ms)  # 300ms overlap
                    speech_audio = speech_audio[-overlap_frames:] if overlap_frames < len(speech_audio) else []
                    last_process_time = now

            elif not is_speech and in_speech:
                # ---- potential silence after speech ----
                silence_frames += 1
                speech_audio.append(chunk)

                if silence_frames >= silence_threshold_frames:
                    # ---- speech END ----
                    total_s = len(speech_audio) * self.chunk_ms / 1000
                    if total_s >= self.min_speech_s:
                        self._process(np.concatenate(speech_audio), final=True)
                    in_speech = False
                    speech_audio = []
                    silence_frames = 0

        logger.debug("Processing thread stopped.")

    # ------------------------------------------------------------------
    # ASR + translate + display
    # ------------------------------------------------------------------

    def _process(self, audio: np.ndarray, *, final: bool):
        """Run ASR on the audio segment, translate, and push to UI."""
        if len(audio) < self.chunk_samples * 2:
            return

        audio = np.asarray(audio, dtype=np.float32).ravel()

        try:
            t0 = time.perf_counter()
            en = self.asr.transcribe(audio)
            t1 = time.perf_counter()
            asr_ms = (t1 - t0) * 1000
        except Exception as e:
            logger.error("ASR error: %s", e, exc_info=True)
            return

        if not en or not en.strip():
            return

        dur_s = len(audio) / self.sample_rate
        logger.debug("ASR %.0fms (audio=%.1fs%s) %s",
                      asr_ms, dur_s, " FINAL" if final else "", en)

        # Show English immediately (no waiting for translation)
        if self._text_queue:
            self._text_queue.put((en, ""))

        # Translate
        zh = ""
        try:
            zh = self.translator.translate(en)
        except Exception as e:
            logger.error("Translation error: %s", e, exc_info=True)

        if zh:
            tr_ms = (time.perf_counter() - t1) * 1000
            logger.debug("TL %.0fms %s", tr_ms, zh)

        # Update with translation (Chinese appears ~50-100ms after English)
        if self._text_queue:
            self._text_queue.put((en, zh))

        save_transcript(en, zh)
