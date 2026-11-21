"""Make a voice from a description of it, on this machine.

    mvr design "四十多岁男性，嗓音低沉，语速缓慢，吐字清晰" -o 声音/低沉男声

A voice-design model reads a sample text in a voice that fits the description, and that
recording is the voice: to read with it is to clone the recording (tts.py). The built-in
voices were made this way. It has nothing to do with cloning a recording of a person
(clone.py). The same description gives a different voice every time, so make several and keep
the one that sounds right.

The page server runs this as `python -m multivoice_reader.design`.
"""

import argparse
import json
import shutil
from collections.abc import Callable
from pathlib import Path

from .voices import REF_MAX_SECONDS, SAMPLES, UNKNOWN, Voice, home, load_voice, voice_id_of

MODEL = "mlx-community/Qwen3-TTS-12Hz-1.7B-VoiceDesign-bf16"
SAMPLE_TEXT = SAMPLES[0][3]
# The recording is what gets cloned, and cloning wants some seconds of speech but not too many.
MIN_TEXT_CHARS, MAX_TEXT_CHARS = 15, 80


def design(
    desc: str,
    folder: Path,
    name: str = "",
    gender: str = UNKNOWN,
    age: str = UNKNOWN,
    text: str = "",
    tell: Callable[[str], None] = print,
) -> Voice:
    """Write a voice that fits `desc` into `folder`; ValueError says what was wrong with the input."""
    desc, text = desc.strip(), text.strip() or SAMPLE_TEXT
    if not desc:
        raise ValueError("请描述一下想要的声音，比如：四十多岁男性，嗓音低沉，语速缓慢")
    if not MIN_TEXT_CHARS <= len(text) <= MAX_TEXT_CHARS:
        raise ValueError(f"试读的话要在 {MIN_TEXT_CHARS} 到 {MAX_TEXT_CHARS} 个字之间")
    import numpy as np
    import soundfile as sf
    from mlx_audio.tts.utils import load_model

    tell("正在加载声音设计模型，第一次要下载 4.2 GB")
    model = load_model(MODEL)
    tell("正在生成声音")
    results = list(model.generate_voice_design(text=text, language="Chinese", instruct=desc))
    audio = np.concatenate([np.array(r.audio, dtype=np.float32) for r in results])
    folder.mkdir(parents=True, exist_ok=True)
    sf.write(folder / "ref.wav", audio, results[0].sample_rate)
    seconds = len(audio) / results[0].sample_rate
    if seconds > REF_MAX_SECONDS:  # reading keeps the recording in mind with every line it speaks
        tell(f"这段录音有 {seconds:.0f} 秒，偏长。试读的话短一些，让录音在 {REF_MAX_SECONDS} 秒以内更稳妥")
    config = {"name": name.strip() or folder.name, "kind": "design", "gender": gender, "age": age}
    config |= {"desc": desc, "ref_audio": "ref.wav", "ref_text": text}
    (folder / "voice.json").write_text(json.dumps(config, ensure_ascii=False, indent=2), encoding="utf-8")
    return load_voice(folder)


# ---- the design page: what was made is a draft until the listener keeps it ----
def drafts() -> list[Voice]:
    """Designed voices not kept yet, the newest first."""
    folders = sorted((home() / "designs").glob("*/"), key=lambda p: p.stat().st_mtime, reverse=True)
    return [voice for folder in folders if (voice := load_voice(folder))]


def draft(draft_id: str) -> Voice:
    """The draft with this id; LookupError if there is none. The id may come from a URL, so
    it has to be the name of a folder that is there, not a path to somewhere else."""
    found = [voice for voice in drafts() if voice.id == draft_id]
    if not found:
        raise LookupError("没有这个设计")
    return found[0]


def keep(draft_id: str, name: str) -> Voice:
    """Move a draft into the user's voices under `name`, where reading can use it."""
    voice = draft(draft_id)
    voice_id = voice_id_of(name)
    if not voice_id:
        raise ValueError("名字里需要至少一个字母、数字或汉字")
    target = home() / "voices" / voice_id
    if target.exists():
        raise ValueError(f"已经有一个叫「{name}」的声音了，换个名字")
    config_file = voice.ref_audio.parent / "voice.json"
    config = json.loads(config_file.read_text(encoding="utf-8")) | {"name": name.strip()}
    config_file.write_text(json.dumps(config, ensure_ascii=False, indent=2), encoding="utf-8")
    target.parent.mkdir(parents=True, exist_ok=True)
    shutil.move(voice.ref_audio.parent, target)
    return load_voice(target, own=True)


def discard(draft_id: str) -> None:
    shutil.rmtree(draft(draft_id).ref_audio.parent)


def main() -> None:
    parser = argparse.ArgumentParser(description="按一段描述设计声音")
    parser.add_argument("desc")
    parser.add_argument("--out", type=Path, required=True)
    parser.add_argument("--name", default="")
    parser.add_argument("--gender", default=UNKNOWN)
    parser.add_argument("--age", default=UNKNOWN)
    parser.add_argument("--text", default="")
    args = parser.parse_args()
    try:
        design(
            args.desc,
            args.out,
            args.name,
            args.gender,
            args.age,
            args.text,
            lambda line: print(line, flush=True),
        )
    except ValueError as err:
        raise SystemExit(str(err)) from err


if __name__ == "__main__":
    main()
