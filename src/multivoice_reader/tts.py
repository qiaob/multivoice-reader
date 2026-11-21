"""Speak one line in a given voice and emotion, on this machine.

The model clones the voice's reference recording and takes the emotion as an instruction,
so any voice in the library, including ones the user cloned, can be angry or sad.
"""

import subprocess
from pathlib import Path

import numpy as np

from .text import speakable
from .voices import Voice

MODEL = "mlx-community/Ming-3.0-tts-0.5B-bf16"
ENGINE = "ming3"  # part of every audio file's key: change the engine and audio is made anew
NEUTRAL = "中性"


REF_TAIL_SECONDS = 0.1  # how much silence a reference recording may end with
QUIET = 10 ** (-45 / 20)  # this far below a recording's peak counts as silence
AUDIBLE = 0.02  # a line whose loudest sample is below this has nothing in it


def without_long_tail(audio: np.ndarray, sample_rate: int) -> np.ndarray:
    """The recording, cut shortly after its last sound.

    The model carries on from where the reference ends. After half a second of silence it
    tends to carry on being silent, above all when it is also given an emotion, and the line
    comes out empty.
    """
    frame = sample_rate // 100
    count = len(audio) // frame
    levels = np.abs(audio[: count * frame]).reshape(count, frame).mean(axis=1)
    loud = np.flatnonzero(levels > QUIET * np.abs(audio).max())
    if not len(loud):
        return audio
    return audio[: (loud[-1] + 1) * frame + int(REF_TAIL_SECONDS * sample_rate)]


class Speaker:
    def __init__(self, model: str = MODEL):
        from mlx_audio.tts.utils import load_model

        self.model = load_model(model)
        self.references: dict[Path, object] = {}

    def reference(self, voice: Voice):
        import mlx.core as mx
        from mlx_audio.utils import load_audio

        if voice.ref_audio not in self.references:
            rate = self.model.sample_rate
            audio = np.array(load_audio(str(voice.ref_audio), sample_rate=rate), dtype=np.float32)
            self.references[voice.ref_audio] = mx.array(without_long_tail(audio, rate))
        return self.references[voice.ref_audio]

    def say(self, text: str, voice: Voice, emotion: str = NEUTRAL) -> tuple[np.ndarray, int]:
        from mlx_audio.tts.models.bailingmm.bailingmm import ming3_instruction

        # Now and then the model answers with silence, more often when given an emotion. Try
        # again, and rather than lose the line, say it plainly.
        instruction = ming3_instruction(emotion=emotion) if emotion != NEUTRAL else None
        for instruct in (instruction, instruction, None):
            results = list(
                self.model.generate(
                    text=speakable(text),
                    ref_audio=self.reference(voice),
                    ref_text=voice.ref_text,
                    instruct=instruct,
                )
            )
            audio = np.concatenate([np.array(r.audio, dtype=np.float32) for r in results])
            if np.abs(audio).max() >= AUDIBLE:
                break
        return audio, results[0].sample_rate


def save_mp3(audio: np.ndarray, sample_rate: int, path: Path) -> None:
    """Write through a temporary name so the page never plays half a file."""
    tmp = path.with_suffix(".part.mp3")
    subprocess.run(
        ["ffmpeg", "-y", "-loglevel", "error", "-f", "f32le", "-ar", str(sample_rate), "-ac", "1"]
        + ["-i", "pipe:0", "-b:a", "96k", str(tmp)],
        input=np.ascontiguousarray(audio, dtype=np.float32).tobytes(),
        check=True,
    )
    tmp.replace(path)
