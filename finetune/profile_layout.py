"""Measure how novels lay out dialogue, so the synthetic data can be checked against real books.

Prints numbers only, never text. Give it txt files, folders of chapter files, or the synthetic
dataset itself, and compare the rows.

    PYTHONPATH=src python finetune/profile_layout.py 小说.txt 另一本/ finetune/data/train.jsonl

Columns
    章        chapters found (0 means no headings were recognised)
    段长      median paragraph length in characters
    对白%     share of characters that are inside speech quotes
    独占      share of speech quotes that are a whole paragraph on their own
    句首      ... that open a paragraph and are followed by narration ("……"他说。)
    句尾      ... that close a paragraph after narration (他说："……")
    其他      ... in the middle of a paragraph, or several in one
    上有冒号  of the quotes that stand alone: the paragraph above ends with a colon
    接对白    of the quotes that stand alone: the paragraph above is another lone quote
    连3+      of the quotes that stand alone: in a run of three or more
    「」      share of speech quotes written with corner brackets
    直引号    share of speech quotes written with straight double quotes
"""

import json
import re
import statistics
import sys
from pathlib import Path

from multivoice_reader.text import QUOTED, _is_speech, quoted_text, read_text, split_chapters

MAX_CHARS = 300_000  # enough of a book to see its habits


def paragraphs_of(path: Path) -> tuple[int, list[str]]:
    if path.suffix == ".jsonl":  # the synthetic dataset: one excerpt per example
        paragraphs: list[str] = []
        examples = 0
        for line in path.open(encoding="utf-8"):
            excerpt = json.loads(line)["messages"][0]["content"].split("\n\n")[1]
            paragraphs.extend(re.sub(r"【\d+】", "", excerpt).split("\n"))
            paragraphs.append("")  # examples are not consecutive text
            examples += 1
            if sum(map(len, paragraphs)) > MAX_CHARS:
                break
        return examples, paragraphs
    if path.is_dir():
        files = sorted(p for p in path.rglob("*") if p.suffix in (".txt", ".md") and p.is_file())
        text = "\n".join(read_text(p) for p in files)
    else:
        text = read_text(path)
    chapters = split_chapters(text[: MAX_CHARS * 2])
    if chapters and not chapters[0].title.startswith("第 "):
        found = len(chapters)
    else:
        found = 0
    paragraphs = []
    for chapter in chapters:
        paragraphs.extend(chapter.paragraphs)
        paragraphs.append("")
        if sum(map(len, paragraphs)) > MAX_CHARS:
            break
    return found, paragraphs


def profile(paragraphs: list[str]) -> dict:
    total_chars = sum(map(len, paragraphs)) or 1
    speech_chars = corner = straight = 0
    place = {"lone": 0, "lead": 0, "tail": 0, "other": 0}
    lone_flags = []  # per paragraph: is it exactly one speech quote
    for para in paragraphs:
        quotes = [m for m in QUOTED.finditer(para) if _is_speech(quoted_text(m))]
        lone_flags.append(len(quotes) == 1 and quotes[0].span() == (0, len(para)))
        for match in quotes:
            speech_chars += len(match.group(0))
            corner += match.group(0).startswith("「")
            straight += match.group(0).startswith('"')
            if len(quotes) == 1 and match.span() == (0, len(para)):
                place["lone"] += 1
            elif len(quotes) == 1 and match.start() == 0:
                place["lead"] += 1
            elif len(quotes) == 1 and match.end() == len(para):
                place["tail"] += 1
            else:
                place["other"] += 1
    quotes_total = sum(place.values()) or 1
    lone_total = place["lone"] or 1
    colon_above = quote_above = in_long_run = run = 0
    runs = []
    for index, lone in enumerate(lone_flags):
        if lone:
            above = paragraphs[index - 1] if index else ""
            colon_above += above.endswith(("：", ":"))
            quote_above += index > 0 and lone_flags[index - 1]
            run += 1
        elif run:
            runs.append(run)
            run = 0
    if run:
        runs.append(run)
    in_long_run = sum(r for r in runs if r >= 3)
    lengths = [len(p) for p in paragraphs if p]
    return {
        "段长": statistics.median(lengths) if lengths else 0,
        "对白%": speech_chars / total_chars,
        "独占": place["lone"] / quotes_total,
        "句首": place["lead"] / quotes_total,
        "句尾": place["tail"] / quotes_total,
        "其他": place["other"] / quotes_total,
        "上有冒号": colon_above / lone_total,
        "接对白": quote_above / lone_total,
        "连3+": in_long_run / lone_total,
        "「」": corner / quotes_total,
        "直引号": straight / quotes_total,
    }


def main() -> None:
    rows = []
    for arg in sys.argv[1:]:
        path = Path(arg)
        chapters, paragraphs = paragraphs_of(path)
        rows.append((path.stem[:14] if path.is_file() else path.name[:14], chapters, profile(paragraphs)))
    if not rows:
        raise SystemExit(__doc__)
    columns = list(rows[0][2])
    print(f"{'书':<16}{'章':>5}" + "".join(f"{c:>8}" for c in columns))
    for name, chapters, stats in rows:
        cells = "".join(f"{stats[c]:>8.0f}" if c == "段长" else f"{stats[c]:>8.0%}" for c in columns)
        print(f"{name:<16}{chapters:>5}{cells}")


if __name__ == "__main__":
    main()
