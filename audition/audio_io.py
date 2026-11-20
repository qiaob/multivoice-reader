"""Audio file helpers shared by the audition generators."""

import subprocess
from pathlib import Path

import numpy as np
import soundfile as sf


def save_mp3(audio: np.ndarray, sample_rate: int, path: Path) -> None:
    wav = path.with_suffix(".wav")
    sf.write(wav, audio, sample_rate)
    subprocess.run(
        ["ffmpeg", "-y", "-loglevel", "error", "-i", str(wav), "-b:a", "96k", str(path)],
        check=True,
    )
    wav.unlink()
