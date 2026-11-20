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


class Speaker:
    def __init__(self, model: str = MODEL):
        from mlx_audio.tts.utils import load_model

        self.model = load_model(model)

    def say(self, text: str, voice: Voice, emotion: str = NEUTRAL) -> tuple[np.ndarray, int]:
        from mlx_audio.tts.models.bailingmm.bailingmm import ming3_instruction

        results = list(
            self.model.generate(
                text=speakable(text),
                ref_audio=str(voice.ref_audio),
                ref_text=voice.ref_text,
                instruct=ming3_instruction(emotion=emotion) if emotion != NEUTRAL else None,
            )
        )
        return np.concatenate([np.array(r.audio, dtype=np.float32) for r in results]), results[0].sample_rate


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
