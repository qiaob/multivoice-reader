"""Generate audition clips with locally designed voices (Qwen3-TTS VoiceDesign on MLX).

Runs on the macOS host, not in Docker: MLX needs the Apple GPU.

    uv run --no-project --python 3.11 --with mlx-audio python audition/qwen_samples.py
    ... --voices n_m_passion,n_f_expressive   # only these voices

Output: audition/out/qwen/<voice>/<clip>.mp3 and audition/out/qwen/voices.json.
Existing clips are skipped.
"""

import argparse
import json
import time
from pathlib import Path

import numpy as np
from audio_io import save_mp3
from mlx_audio.tts.utils import load_model

ROOT = Path(__file__).parent
MODEL = "mlx-community/Qwen3-TTS-12Hz-1.7B-VoiceDesign-8bit"


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--voices", help="comma-separated voice ids; default: all")
    parser.add_argument("--clips", help="comma-separated clip ids; default: all")
    parser.add_argument("--model", default=MODEL, help="MLX model repo id")
    parser.add_argument("--out-name", default="qwen", help="folder under audition/out")
    args = parser.parse_args()
    out = ROOT / "out" / args.out_name

    clips = json.loads((ROOT / "texts.json").read_text(encoding="utf-8"))
    if args.clips:
        clips = [c for c in clips if c["id"] in args.clips.split(",")]
    voices = json.loads((ROOT / "qwen_voices.json").read_text(encoding="utf-8"))
    wanted = set(args.voices.split(",")) if args.voices else {v["id"] for v in voices}

    out.mkdir(parents=True, exist_ok=True)
    meta = [
        {"id": v["id"], "name": v["name"], "gender": v["gender"], "desc": v["instruct"]}
        for v in voices
        if any((out / v["id"]).glob("*.mp3")) or v["id"] in wanted
    ]
    (out / "voices.json").write_text(
        json.dumps(
            {"engine": f"本地设计音色 · {args.model.split('/')[-1]}", "voices": meta},
            ensure_ascii=False,
            indent=2,
        ),
        encoding="utf-8",
    )

    t0 = time.time()
    model = load_model(args.model)
    print(f"model loaded in {time.time() - t0:.0f}s", flush=True)

    audio_s = wall_s = 0.0
    for voice in voices:
        if voice["id"] not in wanted:
            continue
        for clip in clips:
            path = out / voice["id"] / f"{clip['id']}.mp3"
            if path.exists() and path.stat().st_size > 0:
                continue
            path.parent.mkdir(parents=True, exist_ok=True)
            start = time.time()
            results = list(
                model.generate_voice_design(
                    text=clip["text"],
                    language="Chinese",
                    # A voice made for a kind of story reads in that story's manner.
                    instruct=f"{voice['instruct']}。{voice.get('style') or clip['style']}。",
                )
            )
            audio = np.concatenate([np.array(r.audio) for r in results])
            sample_rate = results[0].sample_rate
            save_mp3(audio, sample_rate, path)
            took, length = time.time() - start, len(audio) / sample_rate
            audio_s, wall_s = audio_s + length, wall_s + took
            print(f"{voice['id']}/{clip['id']}: {length:.1f}s audio in {took:.1f}s", flush=True)

    if wall_s:
        print(f"total: {audio_s:.0f}s audio in {wall_s:.0f}s, speed {audio_s / wall_s:.2f}x realtime")


if __name__ == "__main__":
    main()
