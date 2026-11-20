"""Clone a voice from a reference recording, fully local (Qwen3-TTS Base on MLX).

Runs on the macOS host, not in Docker: MLX needs the Apple GPU.

    uv run --no-project --python 3.11 --with mlx-audio python audition/clone_voice.py me.m4a --name 我的声音
    ... --text "录音里说的原话"   # skip speech recognition of the recording
    ... --no-cleanup              # use the recording exactly as it is

The recording is cleaned before cloning, so that what gets cloned is only the voice:
the voice is separated from music and sound effects (Mel-Band-RoFormer), then steady
background noise is reduced if there is still enough of it to matter (DeepFilterNet).
Output: audition/out/clone/<name>/ref_raw.wav (as recorded), ref.wav (cleaned),
voice.json and one mp3 per audition clip.
Only clone your own voice or one you have permission to use.
"""

import argparse
import json
import re
import subprocess
from pathlib import Path

import build_page
import numpy as np
import soundfile as sf
from audio_io import save_mp3
from mlx_audio.stt import load as load_asr
from mlx_audio.tts.utils import load_model

ROOT = Path(__file__).parent
OUT = ROOT / "out" / "clone"
TTS_MODEL = "mlx-community/Qwen3-TTS-12Hz-1.7B-Base-bf16"
ASR_MODEL = "mlx-community/Qwen3-ASR-0.6B-8bit"
SEPARATION_MODEL = "mlx-community/mel-roformer-kim-vocal-2-mlx"
DENOISE_MODEL = "mlx-community/DeepFilterNet-mlx"
REF_SAMPLE_RATE = 48000  # what the denoiser expects
CLEAN_ENOUGH_DB = 30  # speech this far above the background needs no denoising
MAX_ATTENUATION_DB = 12  # the denoiser may not turn anything down further than this


def extract_reference(source: Path, ref: Path) -> None:
    """Any audio/video file -> mono wav, capped in length."""
    subprocess.run(
        [
            "ffmpeg",
            "-y",
            "-loglevel",
            "error",
            "-i",
            str(source),
            "-vn",
            "-t",
            str(build_page.REF_MAX_SECONDS),
            "-ac",
            "1",
            "-ar",
            str(REF_SAMPLE_RATE),
            str(ref),
        ],
        check=True,
    )


def isolate_voice(raw: Path, voice: Path) -> None:
    """Separate the voice from music and sound effects."""
    import mlx.core as mx
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


def speech_to_noise_db(audio: np.ndarray, sample_rate: int) -> float:
    """Gap between the loud (speech) and quiet (background) quarter-second windows."""
    window = sample_rate // 4
    frames = audio[: len(audio) // window * window].reshape(-1, window)
    levels = 20 * np.log10(np.sqrt((frames**2).mean(axis=1)) + 1e-9)
    return float(np.percentile(levels, 90) - np.percentile(levels, 10))


def denoise(raw: Path, clean: Path) -> bool:
    """Remove background noise from the reference; False if it was clean enough already."""
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
    text = load_asr(ASR_MODEL).generate(str(ref)).text.strip()
    if not text:
        raise SystemExit("没能识别出录音里的话，请用 --text 提供参考文本")
    return text


def register(voice_id: str, name: str, desc: str, refs: list[dict]) -> None:
    index = OUT / "voices.json"
    voices = json.loads(index.read_text(encoding="utf-8"))["voices"] if index.exists() else []
    voices = [v for v in voices if v["id"] != voice_id]
    voices.append({"id": voice_id, "name": name, "gender": "—", "desc": desc, "refs": refs})
    index.write_text(
        json.dumps({"engine": "复刻音色", "voices": voices}, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )


def main() -> None:
    parser = argparse.ArgumentParser(description="从一段录音复刻声音")
    parser.add_argument("audio", type=Path, help="参考录音，3 到 20 秒的清晰人声最好")
    parser.add_argument("--name", required=True, help="给这个声音起的名字")
    parser.add_argument("--text", help="录音里说的原话；不填则自动识别")
    parser.add_argument("--no-cleanup", action="store_true", help="原样使用录音，不去背景音也不去噪")
    args = parser.parse_args()

    voice_id = re.sub(r"[^\w-]+", "_", args.name).strip("_")
    if not voice_id:
        raise SystemExit("名字里需要至少一个字母、数字或汉字")
    if not args.audio.is_file():
        raise SystemExit(f"找不到录音文件：{args.audio}")

    voice_dir = OUT / voice_id
    voice_dir.mkdir(parents=True, exist_ok=True)
    raw, ref = voice_dir / "ref_raw.wav", voice_dir / "ref.wav"
    extract_reference(args.audio, raw)
    refs = [{"label": "原始录音", "src": f"clone/{voice_id}/{raw.name}"}]
    if args.no_cleanup:
        ref.unlink(missing_ok=True)
        ref = raw
        cleanup = "未做处理"
    else:
        isolate_voice(raw, ref)
        cleanup = "已分离人声并去噪" if denoise(ref, ref) else "已分离人声"
        refs.append({"label": "处理后", "src": f"clone/{voice_id}/{ref.name}"})
        print(cleanup, flush=True)
    ref_text = args.text or transcribe(ref)
    print(f"参考文本：{ref_text}", flush=True)
    (voice_dir / "voice.json").write_text(
        json.dumps(
            {"name": args.name, "ref_audio": ref.name, "ref_text": ref_text, "tts_model": TTS_MODEL},
            ensure_ascii=False,
            indent=2,
        ),
        encoding="utf-8",
    )

    model = load_model(TTS_MODEL)
    clips = json.loads((ROOT / "texts.json").read_text(encoding="utf-8"))
    for clip in clips:
        results = list(model.generate(text=clip["text"], ref_audio=str(ref), ref_text=ref_text))
        audio = np.concatenate([np.array(r.audio) for r in results])
        save_mp3(audio, results[0].sample_rate, voice_dir / f"{clip['id']}.mp3")
        print(f"{voice_id}/{clip['id']} 完成", flush=True)

    register(voice_id, args.name, f"{cleanup}。参考文本：{ref_text[:40]}", refs)
    build_page.main()


if __name__ == "__main__":
    main()
