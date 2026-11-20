"""The background process that prepares a book for listening.

It works where the listener is: analyse the chapter they opened, speak its lines from the
one they are on, then get the next chapters ready. Run as `python -m multivoice_reader.worker`.
"""

import sys
import time
import traceback
from collections import Counter
from pathlib import Path

from .analyze import NARRATOR
from .book import Book, audio_key
from .casting import narrator_voice, pick_voice
from .text import Segment, split_segments
from .tts import ENGINE
from .voices import Voice, library

LOOKAHEAD_CHAPTERS = 2
IDLE_SECONDS = 1.0


def voice_of(speaker: str, book: Book, voices: dict[str, Voice]) -> str:
    """The reader's own choice if they made one, else the automatic casting, else the narrator."""
    chosen = book.cast().get(speaker)
    if chosen in voices:
        return chosen
    if speaker != NARRATOR:
        assigned = book.characters().get(speaker, {}).get("voice")
        if assigned in voices:
            return assigned
    narrator = book.cast().get(NARRATOR)
    return narrator if narrator in voices else narrator_voice(voices)


def segment_audio_key(segment: dict, book: Book, voices: dict[str, Voice]) -> tuple[str, str]:
    voice_id = voice_of(segment["speaker"], book, voices)
    return voice_id, audio_key(ENGINE, voice_id, segment["emotion"], segment["text"])


def analyse(book: Book, chapter: int, analyzer, voices: dict[str, Voice]) -> None:
    title = Segment("narration", book.chapters[chapter], -1)
    segments = [title, *split_segments(book.paragraphs(chapter))]
    characters = book.characters()
    labels = analyzer.label(segments, list(characters))
    spoken = Counter(label["speaker"] for label in labels if label["speaker"] != NARRATOR)
    new = [name for name in spoken if name not in characters]
    profiles = analyzer.profiles(segments, new)
    in_use = Counter(c["voice"] for c in characters.values())
    in_use[voice_of(NARRATOR, book, voices)] += 1
    for name in new:
        voice_id = pick_voice(profiles[name], voices, in_use)
        in_use[voice_id] += 1
        characters[name] = {**profiles[name], "voice": voice_id, "lines": 0}
    for name, count in spoken.items():
        characters[name]["lines"] += count
    book.save_characters(characters)
    book.save_script(
        chapter,
        [
            {"kind": s.kind, "text": s.text, "para": s.para, **label}
            for s, label in zip(segments, labels, strict=True)
        ],
    )


def next_job(book: Book, voices: dict[str, Voice], failed: set[str]):
    """("analyse", chapter) or ("speak", chapter, index, segment, voice_id, key), or None."""
    target = book.target()
    last = min(target["chapter"] + LOOKAHEAD_CHAPTERS, len(book.chapters) - 1)
    for chapter in range(target["chapter"], last + 1):
        script = book.script(chapter)
        if script is None:
            return ("analyse", chapter)
        start = target["segment"] if chapter == target["chapter"] else 0
        for index in [*range(start, len(script)), *range(0, start)]:
            voice_id, key = segment_audio_key(script[index], book, voices)
            if key not in failed and not book.audio_path(key).exists():
                return ("speak", chapter, index, script[index], voice_id, key)
    return None


def progress(book: Book, chapter: int, voices: dict[str, Voice]) -> tuple[int, int]:
    script = book.script(chapter) or []
    done = sum(book.audio_path(segment_audio_key(s, book, voices)[1]).exists() for s in script)
    return done, len(script)


def release_memory() -> None:
    import gc

    import mlx.core as mx

    gc.collect()
    mx.clear_cache()


def run(book_dir: Path, voice_dirs: list[Path]) -> None:
    from .tts import Speaker, save_mp3

    book = Book(book_dir)
    analyzer = speaker = None
    failed: set[str] = set()
    while True:
        voices = library(voice_dirs)
        job = next_job(book, voices, failed)
        if analyzer is not None and (job is None or job[0] != "analyse"):
            # The language model is the biggest thing in memory and is needed once per chapter;
            # reloading it from disk takes a few seconds.
            analyzer = None
            release_memory()
        try:
            if job is None:
                book.save_status(state="idle")
                time.sleep(IDLE_SECONDS)
            elif job[0] == "analyse":
                book.save_status(state="analysing", chapter=job[1])
                if analyzer is None:
                    from .analyze import Analyzer

                    analyzer = Analyzer()
                analyse(book, job[1], analyzer, voices)
            else:
                _, chapter, index, segment, voice_id, key = job
                done, total = progress(book, chapter, voices)
                book.save_status(state="speaking", chapter=chapter, done=done, total=total)
                if speaker is None:
                    speaker = Speaker()
                audio, rate = speaker.say(segment["text"], voices[voice_id], segment["emotion"])
                save_mp3(audio, rate, book.audio_path(key))
        except Exception:  # one bad line or chapter must not stop the book
            traceback.print_exc()
            if job and job[0] == "speak":
                failed.add(job[5])
            else:
                book.save_status(
                    state="error", message=traceback.format_exc(limit=1).strip().splitlines()[-1]
                )
                time.sleep(5)


if __name__ == "__main__":
    run(Path(sys.argv[1]), [Path(p) for p in sys.argv[2:]])
