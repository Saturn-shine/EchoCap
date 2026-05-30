"""
Speech recognition engine using faster-whisper.
Loads the model once at startup, with automatic compute_type and device fallback.
"""

import logging
import numpy as np

logger = logging.getLogger(__name__)

COMPUTE_TYPE_FALLBACKS = ["int8_float16", "float16", "int8", "auto"]
DEVICE_FALLBACKS = ["cuda", "cpu"]


class ASREngine:
    """Wraps faster-whisper for low-latency English speech recognition."""

    def __init__(self, model_size="tiny", device="cuda", compute_type="float16"):
        self.model_size = model_size
        self.device = device
        self.compute_type = compute_type
        self._model = None
        self._loaded = False

    # ------------------------------------------------------------------
    # Model loading with automatic fallback
    # ------------------------------------------------------------------

    def load(self):
        """Load and warm-up the Whisper model.

        Tries compute_types in order: configured -> float16 -> int8 -> auto.
        Then devices: configured -> cpu.
        On each attempt runs a warm-up inference to catch runtime errors
        (e.g. cuBLAS incompatibility) that only surface during actual work.
        """
        from faster_whisper import WhisperModel

        compute_types = self._build_chain(self.compute_type, COMPUTE_TYPE_FALLBACKS)
        devices = self._build_chain(self.device, DEVICE_FALLBACKS)
        last_error = None

        for device in devices:
            for ct in compute_types:
                logger.info("Trying: device=%s, compute_type=%s ...", device, ct)
                try:
                    model = WhisperModel(
                        self.model_size, device=device, compute_type=ct
                    )
                except Exception as e:
                    logger.warning("Init failed: %s", e)
                    last_error = e
                    continue

                # Warm-up: a short inference to catch runtime errors like
                # cuBLAS_STATUS_NOT_SUPPORTED that only trigger during encode.
                if not self._warm_up(model, device, ct):
                    continue

                self._model = model
                self.device = device
                self.compute_type = ct
                self._loaded = True
                logger.info("Model ready on %s (%s).", device, ct)
                return

        raise RuntimeError(
            f"Failed to load ASR model. Last error: {last_error}"
        )

    def _warm_up(self, model, device, ct):
        """Run short inference with random audio to verify the model works.

        Uses low-amplitude noise (not silence) so the encoder path is exercised,
        which catches missing CUDA libraries that only surface during real work.
        """
        import numpy as np
        rng = np.random.RandomState(42)
        dummy = (rng.randn(32000).astype(np.float32) * 0.005)
        for i in range(2):
            try:
                list(model.transcribe(
                    dummy, beam_size=1, best_of=1, language="en",
                    vad_filter=False, without_timestamps=True,
                    condition_on_previous_text=False,
                ))
            except Exception as e:
                logger.warning("Warm-up trial %d failed: %s", i + 1, e)
                return False
        logger.debug("Warm-up OK (2/2)")
        return True

    @staticmethod
    def _build_chain(preferred, fallback_list):
        chain = []
        if preferred in fallback_list:
            idx = fallback_list.index(preferred)
            chain = fallback_list[idx:]
        else:
            chain = [preferred] + fallback_list
        return chain

    # ------------------------------------------------------------------
    # Transcription
    # ------------------------------------------------------------------

    def transcribe(self, audio: np.ndarray) -> str:
        """Transcribe a float32 numpy audio array to English text."""
        if not self._loaded:
            raise RuntimeError("Model not loaded. Call load() first.")
        if audio is None or len(audio) < 160:
            return ""

        audio = np.asarray(audio, dtype=np.float32).ravel()

        segments, _info = self._model.transcribe(
            audio,
            beam_size=1,
            best_of=1,
            language="en",
            vad_filter=False,
            without_timestamps=True,
            condition_on_previous_text=False,
        )

        texts = []
        for seg in segments:
            text = seg.text.strip()
            if text:
                texts.append(text)

        return " ".join(texts)
