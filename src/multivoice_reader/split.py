"""Split a novel: cut each chapter into narration and dialogue, and have the language model
say who speaks each line and how. The result is a reading script (see script.py); nothing
here knows about voices.

    mvr split 小说.txt -o 脚本.json
    ... --chapters 1-20          # only these chapters
    ... --model qwen3-1.7b       # a smaller, quicker model (see analyze.MODELS)

The page server runs the same work in the background as `python -m multivoice_reader.split`.
"""

import re
import sys
import traceback
from collections import Counter
from collections.abc import Callable
from pathlib import Path

from .book import Book
from .script import NARRATOR, chapter_range, dumps, load, normalize
from .text import read_text, split_chapters, split_segments


def split_chapter(paragraphs: list[str], characters: dict[str, dict], analyzer) -> list[dict]:
    """One chapter's lines, labelled. Characters met for the first time are added to `characters`."""
    segments = split_segments(paragraphs)
    labels = analyzer.label(segments, list(characters))
    spoken = Counter(label["speaker"] for label in labels if label["speaker"] != NARRATOR)
    new = [name for name in spoken if name not in characters]
    profiles = analyzer.profiles(segments, new)
    for name in new:
        characters[name] = {**profiles[name], "lines": 0}
    for name, count in spoken.items():
        characters[name]["lines"] += count
    return [
        {"kind": s.kind, "text": s.text, "para": s.para, **label}
        for s, label in zip(segments, labels, strict=True)
    ]


def split_file(
    source: Path, out: Path, chapters: str = "", model: str = "", tell: Callable[[str], None] = print
) -> dict:
    """Split a novel into the script file `out`, written after every chapter so that a run
    that stops can be picked up again; ValueError says what was wrong with the input.
    `model` is a name from analyze.MODELS, or "" for the usual one."""
    found = split_chapters(read_text(source))
    if not found:
        raise ValueError(f"{source.name} 里没有可以朗读的正文")
    wanted = chapter_range(chapters, len(found)) if chapters else range(len(found))
    title = re.sub(r"\s*作者[:：].*$", "", source.stem).strip() or source.stem
    script = {"title": title, "characters": {}, "chapters": []}
    if out.exists():
        script = load(out)
        titles = [found[k].title for k in wanted]
        if [c["title"] for c in script["chapters"]] != titles[: len(script["chapters"])]:
            raise ValueError(
                f"{out} 已经存在，而且不是这本书这些章节的拆分结果。换一个输出文件，或者先删掉它"
            )
    counts = Counter(line["speaker"] for c in script["chapters"] for line in c["lines"])
    characters = {name: {**about, "lines": counts[name]} for name, about in script["characters"].items()}
    todo = list(wanted)[len(script["chapters"]) :]
    tell(f"《{title}》共 {len(found)} 章，这次拆 {len(wanted)} 章，其中 {len(wanted) - len(todo)} 章已经拆过")
    if todo:
        from .analyze import DEFAULT_MODEL, Analyzer

        analyzer = Analyzer(model or DEFAULT_MODEL)
        for done, k in enumerate(todo, 1):
            tell(f"拆分 {done}/{len(todo)}：{found[k].title}")
            lines = split_chapter(found[k].paragraphs, characters, analyzer)
            script["chapters"].append({"title": found[k].title, "lines": lines})
            script["characters"] = characters
            script = normalize(script)
            tmp = out.with_name(out.name + ".tmp")
            tmp.write_text(dumps(script), encoding="utf-8")
            tmp.replace(out)
    return script


def run(book_dir: Path) -> None:
    """The background process: split the open book's chapters, in order, as far as asked."""
    book = Book(book_dir)
    analyzer = None
    while True:
        done = book.done()
        todo = [k for k in range(min(book.until(), len(done))) if not done[k]]
        if not todo:  # nothing more was asked for: end, and give the model's memory back
            book.save_status(state="idle")
            return
        chapter = todo[0]
        book.save_status(state="splitting", chapter=chapter)
        try:
            if analyzer is None:
                from .analyze import DEFAULT_MODEL, Analyzer

                analyzer = Analyzer(book.model() or DEFAULT_MODEL)
            characters = book.characters()
            lines = split_chapter(book.paragraphs(chapter), characters, analyzer)
            book.save_characters(characters)
            book.save_lines(chapter, lines)
        except Exception:
            traceback.print_exc()
            book.save_status(state="error", message=traceback.format_exc(limit=1).strip().splitlines()[-1])
            return


if __name__ == "__main__":
    run(Path(sys.argv[1]))
