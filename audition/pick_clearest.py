"""Of several takes of each designed voice, keep the one that is easiest to understand.

A take is judged the way it will be used: the reader's speech model reads a few lines in that
voice, a speech recogniser writes down what it hears, and the take whose lines come back
closest to the text wins. Takes that are equally clear are told apart by pace, for a voice
that is meant to be slow or fast ("pace" in qwen_voices.json), and then by how well the
recording itself is understood. Run after qwen_samples.py has made each take into its own folder,
and before build_voice_packs.py. Runs on the macOS host; needs ffmpeg.

    uv run python audition/pick_clearest.py --takes genre_a,genre_b --out-name genre_best \\
        --voices sus_n_m,sys_n_m

Output: audition/out/<out-name>/<voice>/narration.mp3, a copy of the winning take.
"""

import argparse
import difflib
import json
import re
import shutil
import subprocess
import tempfile
from pathlib import Path

import soundfile as sf

from multivoice_reader.tts import Speaker
from multivoice_reader.voices import Voice

ROOT = Path(__file__).parent
ASR_MODEL = "mlx-community/Qwen3-ASR-0.6B-8bit"
# (emotion, text): everyday lines, names, numbers, and two with feeling.
LINES = [
    ("中性", "他抬头看了一眼墙上的挂钟，已经是凌晨三点十七分。"),
    ("中性", "资质：中等，拥有中品灵根。"),
    ("中性", "张云蹙眉，尝试着伸手抓向其中一道光团。"),
    ("中性", "这件事，除了你和我，不能再让第三个人知道。"),
    ("愤怒", "你到底还要骗我多久？"),
    ("悲伤", "对不起，我来晚了。"),
]


def spoken(text: str) -> str:
    """Only the characters that are said: a recogniser punctuates as it pleases."""
    return re.sub(r"[^一-鿿]", "", text)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--takes", required=True, help="folders under audition/out, comma-separated")
    parser.add_argument("--out-name", required=True, help="folder under audition/out for the winners")
    parser.add_argument("--voices", required=True, help="comma-separated voice ids")
    args = parser.parse_args()
    takes, wanted = args.takes.split(","), args.voices.split(",")
    known = {v["id"]: v for v in json.loads((ROOT / "qwen_voices.json").read_text(encoding="utf-8"))}
    clips = json.loads((ROOT / "texts.json").read_text(encoding="utf-8"))
    ref_text = next(c["text"] for c in clips if c["id"] == "narration")

    with tempfile.TemporaryDirectory() as folder:
        work = Path(folder)
        speaker = Speaker()
        seconds: dict[tuple[str, str], float] = {}  # how long each take's lines came out
        for voice_id in wanted:
            for take in takes:
                ref = work / f"{voice_id}.{take}.ref.wav"
                source = ROOT / "out" / take / voice_id / "narration.mp3"
                subprocess.run(
                    [
                        "ffmpeg",
                        "-y",
                        "-loglevel",
                        "error",
                        "-i",
                        str(source),
                        "-ac",
                        "1",
                        "-ar",
                        "24000",
                        str(ref),
                    ],
                    check=True,
                )
                about = known[voice_id]
                voice = Voice(
                    voice_id, about["name"], about["gender"], about["age"], about["kind"], "", ref, ref_text
                )
                for number, (emotion, text) in enumerate(LINES):
                    audio, rate = speaker.say(text, voice, emotion)
                    sf.write(work / f"{voice_id}.{take}.{number}.wav", audio, rate)
                    seconds[voice_id, take] = seconds.get((voice_id, take), 0.0) + len(audio) / rate
                print(f"spoke {voice_id} / {take}", flush=True)
        del speaker  # the two models do not fit in memory together

        from mlx_audio.stt import load as load_asr

        asr = load_asr(ASR_MODEL)

        def closeness(path: Path, text: str) -> float:
            heard = spoken(asr.generate(str(path)).text)
            return difflib.SequenceMatcher(None, heard, spoken(text)).ratio()

        said = sum(len(spoken(text)) for _, text in LINES)
        for voice_id in wanted:
            pace = {"slow": -1, "fast": 1}.get(known[voice_id].get("pace"), 0)
            scores = {}
            for take in takes:
                lines = [
                    closeness(work / f"{voice_id}.{take}.{n}.wav", text) for n, (_, text) in enumerate(LINES)
                ]
                recording = closeness(work / f"{voice_id}.{take}.ref.wav", ref_text)
                rate = said / seconds[voice_id, take]  # characters a second, pauses included
                scores[take] = (round(sum(lines) / len(lines), 2), pace * rate, recording)
                print(
                    f"{voice_id:<12}{take:<10} lines {sum(lines) / len(lines):.3f}  worst {min(lines):.2f}  "
                    f"recording {recording:.3f}  reads at {rate:.1f} 字/秒",
                    flush=True,
                )
            best = max(takes, key=lambda take: scores[take])
            target = ROOT / "out" / args.out_name / voice_id / "narration.mp3"
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(ROOT / "out" / best / voice_id / "narration.mp3", target)
            print(f"{voice_id:<12}-> {best}", flush=True)


if __name__ == "__main__":
    main()
