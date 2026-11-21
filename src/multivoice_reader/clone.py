"""Make a voice for the library from a recording, on this machine.

    mvr clone 录音.m4a --name 我的声音
    ... --text "录音里说的原话"   # skip speech recognition of the recording
    ... --no-cleanup              # use the recording exactly as it is

The recording is cleaned first, so that what gets cloned is only the voice: the voice is
separated from music and sound effects (Mel-Band-RoFormer), then steady background noise is
reduced if there is still enough of it to matter (DeepFilterNet). The new voice then reads a
few sample lines with the model the reader speaks with, so what you hear is what you will get.

The page server runs this as `python -m multivoice_reader.clone`: the models are big, and a
process that ends gives all of their memory back.
Only clone your own voice or one you have permission to use.
"""

import argparse
import json
import subprocess
from collections.abc import Callable
from pathlib import Path

from .voices import REF_MAX_SECONDS, SAMPLES, Voice, home, load_voice, voice_id_of

ASR_MODEL = "mlx-community/Qwen3-ASR-0.6B-8bit"
SEPARATION_MODEL = "mlx-community/mel-roformer-kim-vocal-2-mlx"
DENOISE_MODEL = "mlx-community/DeepFilterNet-mlx"
REF_SAMPLE_RATE = 48000  # what the denoiser expects
CLEAN_ENOUGH_DB = 30  # speech this far above the background needs no denoising
MAX_ATTENUATION_DB = 12  # the denoiser may not turn anything down further than this


def extract_reference(source: Path, ref: Path) -> None:
    """Any audio or video file -> mono wav, capped in length."""
    command = ["ffmpeg", "-y", "-loglevel", "error", "-i", str(source), "-vn", "-t", str(REF_MAX_SECONDS)]
    done = subprocess.run(
        [*command, "-ac", "1", "-ar", str(REF_SAMPLE_RATE), str(ref)],
        capture_output=True,
        text=True,
        check=False,
    )
    if done.returncode != 0 or not ref.is_file() or ref.stat().st_size < 1000:
        raise ValueError("这个文件里没有读到声音")


def isolate_voice(raw: Path, voice: Path) -> None:
    """Separate the voice from music and sound effects."""
    import mlx.core as mx
    import numpy as np
    import soundfile as sf
    from mlx_audio.sts.models.mel_roformer import MelRoFormer
    from scipy.signal import resample_poly

    model = MelRoFormer.from_pretrained(SEPARATION_MODEL)
    audio, rate = sf.read(raw, dtype="float32")
    # The separator works on 44.1 kHz stereo, in fixed-size chunks.
    mix = resample_poly(audio, model.config.sample_rate, rate).astype(np.float32)
    chunk = model.config.chunk_size
    hop = chunk // 2
    # Half-overlapping Hann windows sum to one, so chunks cross-fade without seams; the
    # padding gives every real sample two windows.
    padded = np.zeros(hop * (-(-len(mix) // hop) + 2), dtype=np.float32)
    padded[hop : hop + len(mix)] = mix
    window = (0.5 - 0.5 * np.cos(2 * np.pi * np.arange(chunk) / chunk)).astype(np.float32)
    out = np.zeros_like(padded)
    for start in range(0, len(padded) - chunk + 1, hop):
        piece = padded[start : start + chunk]
        vocals = model(mx.array(np.stack([piece, piece])[None]))
        out[start : start + chunk] += window * np.array(vocals, dtype=np.float32)[0].mean(axis=0)
    isolated = resample_poly(out[hop : hop + len(mix)], rate, model.config.sample_rate)
    sf.write(voice, isolated[: len(audio)].astype(np.float32), rate)


def speech_to_noise_db(audio, sample_rate: int) -> float:
    """Gap between the loud (speech) and quiet (background) quarter-second windows."""
    import numpy as np

    window = sample_rate // 4
    frames = audio[: len(audio) // window * window].reshape(-1, window)
    levels = 20 * np.log10(np.sqrt((frames**2).mean(axis=1)) + 1e-9)
    return float(np.percentile(levels, 90) - np.percentile(levels, 10))


def denoise(raw: Path, clean: Path) -> bool:
    """Remove background noise from the reference; False if it was clean enough already."""
    import soundfile as sf

    audio, rate = sf.read(raw, dtype="float32")
    if speech_to_noise_db(audio, rate) >= CLEAN_ENOUGH_DB:
        return False
    from mlx_audio.sts.models.deepfilternet import DeepFilterNetModel

    DeepFilterNetModel.from_pretrained(DENOISE_MODEL).enhance_file(str(raw), str(clean))
    # The denoiser can mute quiet syllables outright, which makes the level pump and ruins
    # the clone. Mixing some of the original back caps how far anything is turned down.
    cleaned, _ = sf.read(clean, dtype="float32")
    n = min(len(audio), len(cleaned))
    keep = 10 ** (-MAX_ATTENUATION_DB / 20)
    sf.write(clean, cleaned[:n] * (1 - keep) + audio[:n] * keep, rate)
    return True


def transcribe(ref: Path) -> str:
    from mlx_audio.stt import load as load_asr

    text = load_asr(ASR_MODEL).generate(str(ref)).text.strip()
    if not text:
        raise ValueError("没能识别出录音里的话，请把原话填上")
    return text


def clone(
    audio: Path, name: str, text: str = "", cleanup: bool = True, tell: Callable[[str], None] = print
) -> Voice:
    """Add a voice called `name` to the user's library; ValueError says what was wrong with the input."""
    voice_id = voice_id_of(name)
    if not voice_id:
        raise ValueError("名字里需要至少一个字母、数字或汉字")
    if not audio.is_file():
        raise ValueError(f"找不到录音文件：{audio}")
    folder = home() / "voices" / voice_id
    folder.mkdir(parents=True, exist_ok=True)
    raw, ref = folder / "ref_raw.wav", folder / "ref.wav"
    extract_reference(audio, raw)
    if cleanup:
        tell("正在把人声从背景里分出来")
        isolate_voice(raw, ref)
        note = "已分离人声并去噪" if denoise(ref, ref) else "已分离人声"
    else:
        ref.unlink(missing_ok=True)
        ref, note = raw, "未做处理"
    if not text:
        tell("正在识别录音里说的话")
        text = transcribe(ref)
    config = {"name": name, "kind": "clone", "desc": note, "ref_audio": ref.name, "ref_text": text}
    (folder / "voice.json").write_text(json.dumps(config, ensure_ascii=False, indent=2), encoding="utf-8")
    voice = load_voice(folder, own=True)

    from .tts import Speaker, save_mp3

    speaker = Speaker()
    voice.sample("x").parent.mkdir(exist_ok=True)
    for sample_id, label, emotion, line in SAMPLES:
        tell(f"正在用新声音试读：{label}")
        save_mp3(*speaker.say(line, voice, emotion), voice.sample(sample_id))
    return voice


def main() -> None:
    parser = argparse.ArgumentParser(description="从一段录音复刻声音")
    parser.add_argument("audio", type=Path)
    parser.add_argument("--name", required=True)
    parser.add_argument("--text", default="")
    parser.add_argument("--no-cleanup", action="store_true")
    args = parser.parse_args()
    try:
        clone(args.audio, args.name, args.text, not args.no_cleanup, lambda line: print(line, flush=True))
    except ValueError as err:
        raise SystemExit(str(err)) from err


if __name__ == "__main__":
    main()
