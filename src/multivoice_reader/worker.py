"""The background process that speaks a script.

    python -m multivoice_reader.worker listen <reading folder> [voice folders]
    python -m multivoice_reader.worker whole <reading folder> [voice folders]

"listen" works where the listener is: speak the lines from the one they are on, then get the
next chapters ready, and wait. "whole" speaks every line of the script from first to last and
then ends.
"""

import sys
import time
import traceback
from collections.abc import Callable
from pathlib import Path

from .casting import narrator_voice
from .reading import Reading, audio_key
from .script import NARRATOR
from .tts import ENGINE
from .voices import Voice, library

LOOKAHEAD_CHAPTERS = 2
IDLE_SECONDS = 1.0


def caster(reading: Reading, voices: dict[str, Voice]) -> Callable[[str], str]:
    """speaker -> voice id: the listener's own choice if they made one, else the automatic
    casting, else the narrator's voice."""
    chosen, assigned = reading.cast(), reading.assigned(voices)
    narrator = chosen.get(NARRATOR)
    narrator = narrator if narrator in voices else narrator_voice(voices)

    def voice_of(speaker: str) -> str:
        if chosen.get(speaker) in voices:
            return chosen[speaker]
        return assigned.get(speaker, narrator) if speaker != NARRATOR else narrator

    return voice_of


def segment_audio_key(segment: dict, voice_of: Callable[[str], str]) -> tuple[str, str]:
    voice_id = voice_of(segment["speaker"])
    return voice_id, audio_key(ENGINE, voice_id, segment["emotion"], segment["text"])


def next_job(reading: Reading, voices: dict[str, Voice], failed: set[str]):
    """(chapter, index, segment, voice_id, key) for the next line to speak, or None."""
    target = reading.target()
    voice_of = caster(reading, voices)
    first = min(target["chapter"], len(reading.chapters) - 1)
    last = min(first + LOOKAHEAD_CHAPTERS, len(reading.chapters) - 1)
    for chapter in range(first, last + 1):
        segments = reading.segments(chapter)
        start = min(target["segment"], len(segments) - 1) if chapter == first else 0
        for index in [*range(start, len(segments)), *range(0, start)]:
            voice_id, key = segment_audio_key(segments[index], voice_of)
            if key not in failed and not reading.audio_path(key).exists():
                return (chapter, index, segments[index], voice_id, key)
    return None


def progress(reading: Reading, chapter: int, voices: dict[str, Voice]) -> tuple[int, int]:
    voice_of = caster(reading, voices)
    segments = reading.segments(chapter)
    done = sum(reading.audio_path(segment_audio_key(s, voice_of)[1]).exists() for s in segments)
    return done, len(segments)


def whole_jobs(reading: Reading, voice_dirs: list[Path]):
    """Every line without audio, first chapter to last, as (chapter, segment, voice, key)."""
    for chapter in range(len(reading.chapters)):
        voices = library(voice_dirs)  # looked at again for each chapter: the cast may have changed
        voice_of = caster(reading, voices)
        for segment in reading.segments(chapter):
            voice_id, key = segment_audio_key(segment, voice_of)
            if not reading.audio_path(key).exists():
                yield chapter, segment, voices[voice_id], key


def run(mode: str, reading_dir: Path, voice_dirs: list[Path]) -> None:
    from .tts import Speaker, save_mp3

    reading = Reading(reading_dir)
    speaker = None

    def load() -> None:
        """A model that cannot be loaded ends the process: there is nothing to go on with."""
        nonlocal speaker
        if speaker is None:
            speaker = Speaker()

    def speak(segment: dict, voice: Voice, key: str) -> None:
        audio, rate = speaker.say(segment["text"], voice, segment["emotion"])
        save_mp3(audio, rate, reading.audio_path(key))

    if mode == "whole":
        for chapter, segment, voice, key in whole_jobs(reading, voice_dirs):
            reading.save_status(state="speaking", chapter=chapter)
            load()
            try:
                speak(segment, voice, key)
            except Exception:  # one bad line must not stop the rest
                traceback.print_exc()
        reading.want_whole(False)
        reading.save_status(state="idle")
        return
    failed: set[str] = set()
    while True:
        voices = library(voice_dirs)
        job = next_job(reading, voices, failed)
        if job is None:
            reading.save_status(state="idle")
            time.sleep(IDLE_SECONDS)
            continue
        chapter, _, segment, voice_id, key = job
        done, total = progress(reading, chapter, voices)
        reading.save_status(state="speaking", chapter=chapter, done=done, total=total)
        load()
        try:
            speak(segment, voices[voice_id], key)
        except Exception:  # one bad line must not stop the reading
            traceback.print_exc()
            failed.add(key)


if __name__ == "__main__":
    run(sys.argv[1], Path(sys.argv[2]), [Path(p) for p in sys.argv[3:]])
