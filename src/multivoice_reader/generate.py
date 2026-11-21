"""Speak a reading script into audio files, one per chapter, without the page.

    mvr generate 脚本.json -o 输出目录
    ... --chapters 1-20          # only these chapters
    ... --narrator 声音名         # who reads the narration
    ... --cast 张三=声音名        # a character's voice; can be given more than once
    ... --voices 目录             # more voices to cast from; can be given more than once

Characters not named with --cast get a voice that fits their gender and age. Everything it
writes is in the output folder: the chapters as "001 章名.mp3", and under work/ the script,
who has which voice, and each line's audio. Run it again with the same folder and it goes on
from where it stopped.
"""

import re
import subprocess
import tempfile
from collections.abc import Callable
from pathlib import Path

from .casting import GENRES
from .reading import Reading
from .script import NARRATOR, chapter_range, load
from .voices import library
from .worker import caster, segment_audio_key


def file_name(number: int, title: str) -> str:
    """A chapter's file name: its number, then as much of its title as a file name can hold."""
    clean = re.sub(r'[\\/:*?"<>|\x00-\x1f\s]+', " ", title).strip(" .")[:60].strip()
    return f"{number:03d} {clean}.mp3" if clean else f"{number:03d}.mp3"


def join(parts: list[Path], target: Path) -> None:
    """One mp3 from many of the same kind, without encoding them again."""
    with tempfile.TemporaryDirectory() as folder:
        index = Path(folder) / "parts.txt"
        index.write_text("".join(f"file '{p.resolve().as_posix()}'\n" for p in parts), encoding="utf-8")
        tmp = target.with_name(target.name + ".part.mp3")
        # Joining mp3s makes ffmpeg complain about timestamps on every seam, though the result
        # is right; what it says is only worth showing when it fails.
        done = subprocess.run(
            ["ffmpeg", "-y", "-loglevel", "error", "-f", "concat", "-safe", "0", "-i", str(index)]
            + ["-c", "copy", str(tmp)],
            capture_output=True,
            text=True,
        )
        if done.returncode:
            raise RuntimeError(f"ffmpeg 没能合并音频：{done.stderr.strip()[-400:]}")
        tmp.replace(target)


def generate(
    script: Path,
    out: Path,
    voice_dirs: list[Path] = (),
    chapters: str = "",
    cast: dict[str, str] | None = None,
    tell: Callable[[str], None] = print,
    genre: str | None = None,
) -> list[Path]:
    """Write the chapters' audio into `out` and return the files; ValueError says what was wrong.
    `cast` maps a character (or 旁白) to the name of the voice to use. `genre` is the kind of
    story to read it as (casting.GENRES); None keeps what an earlier run into `out` used."""
    voices = library(list(voice_dirs))
    if not voices:
        raise ValueError("没有可用的声音")
    reading = Reading.create(load(script), folder=out / "work")
    wanted = chapter_range(chapters, len(reading.chapters)) if chapters else range(len(reading.chapters))
    chosen = reading.cast()
    for who, name in (cast or {}).items():
        found = [v.id for v in voices.values() if name in (v.id, v.name)]
        if not found:
            raise ValueError(f"没有叫「{name}」的声音，用 mvr voices 查看有哪些")
        if who != NARRATOR and who not in reading.script["characters"]:
            raise ValueError(f"脚本里没有叫「{who}」的角色")
        chosen[who] = found[0]
    reading.save_cast(chosen)
    if genre is not None and genre != reading.genre():
        if genre and genre not in GENRES:
            raise ValueError(f"没有「{genre}」这个题材，可以用的有：{'、'.join(GENRES)}")
        reading.save_genre(genre)
    voice_of = caster(reading, voices)
    tell(f"《{reading.title}》共 {len(reading.chapters)} 章，这次处理 {len(wanted)} 章，输出到 {out}")
    tell(f"  旁白：{voices[voice_of(NARRATOR)].name}")
    for who in list(reading.characters())[:12]:
        tell(f"  {who}：{voices[voice_of(who)].name}")

    speaker = None
    for k in wanted:
        target = out / file_name(k + 1, reading.chapters[k])
        if target.exists():
            continue
        segments = reading.segments(k)
        parts = []
        for index, segment in enumerate(segments, 1):
            voice_id, key = segment_audio_key(segment, voice_of)
            path = reading.audio_path(key)
            if not path.exists():
                if speaker is None:
                    from .tts import Speaker, save_mp3

                    speaker = Speaker()
                tell(f"合成 {reading.chapters[k]}：{index}/{len(segments)}")
                try:
                    save_mp3(*speaker.say(segment["text"], voices[voice_id], segment["emotion"]), path)
                except Exception as err:  # one bad line must not stop the rest
                    tell(f"  这一句没有合成出来，跳过：{err}")
                    continue
            parts.append(path)
        if parts:
            join(parts, target)
            tell(f"写好了：{target.name}")
    return [path for k in wanted if (path := out / file_name(k + 1, reading.chapters[k])).exists()]
