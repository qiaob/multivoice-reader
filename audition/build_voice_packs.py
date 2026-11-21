"""Turn the designed voices into the reader's built-in voice library.

For every voice in qwen_voices.json that has a generated narration clip, write
src/multivoice_reader/voices/<id>/voice.json and its reference recording. Run after
qwen_samples.py; needs ffmpeg. Stdlib only.

    python audition/build_voice_packs.py [--from qwen_bf16]
"""

import argparse
import json
import subprocess
from pathlib import Path

ROOT = Path(__file__).parent
PACKS = ROOT.parent / "src" / "multivoice_reader" / "voices"
REF_CLIP = "narration"


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--from", dest="source", default="qwen_bf16", help="folder under audition/out")
    args = parser.parse_args()
    clips = json.loads((ROOT / "texts.json").read_text(encoding="utf-8"))
    ref_text = next(c["text"] for c in clips if c["id"] == REF_CLIP)
    made = 0
    for voice in json.loads((ROOT / "qwen_voices.json").read_text(encoding="utf-8")):
        clip = ROOT / "out" / args.source / voice["id"] / f"{REF_CLIP}.mp3"
        if not clip.exists():
            print(f"跳过 {voice['id']}：还没有生成 {clip.name}")
            continue
        folder = PACKS / voice["id"]
        folder.mkdir(parents=True, exist_ok=True)
        subprocess.run(
            [
                "ffmpeg",
                "-y",
                "-loglevel",
                "error",
                "-i",
                str(clip),
                "-ac",
                "1",
                "-ar",
                "24000",
                str(folder / "ref.wav"),
            ],
            check=True,
        )
        config = {key: voice[key] for key in ("name", "gender", "age", "kind")}
        if voice.get("genre"):
            config["genre"] = voice["genre"]
        config |= {"desc": voice["instruct"], "ref_audio": "ref.wav", "ref_text": ref_text}
        (folder / "voice.json").write_text(json.dumps(config, ensure_ascii=False, indent=2), encoding="utf-8")
        made += 1
    print(f"声音库里现在有 {made} 个内置声音：{PACKS}")


if __name__ == "__main__":
    main()
