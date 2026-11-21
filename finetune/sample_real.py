"""Draw passages from real novels for a hand-labelled evaluation set.

For each book given, takes a few groups of dialogue lines exactly as the reader would ask
about them, and writes one file per group with the excerpt the model sees plus the wider
text around it, so a person can decide who really speaks each line.

    PYTHONPATH=src python finetune/sample_real.py --out books/eval/items 小说.txt 另一本/ ...

The output contains text from the books, so keep it out of the repository unless the book
is yours to publish. Stdlib only.
"""

import argparse
import json
import random
from pathlib import Path

from multivoice_reader.analyze import SHORT_LABEL_PROMPT, label_batches, label_request
from multivoice_reader.text import read_text, split_chapters, split_segments

GROUPS_PER_BOOK = 2
CONTEXT_PARAGRAPHS = 40  # how much of the chapter around the excerpt the labeller gets to read


def book_text(path: Path) -> str:
    if path.is_dir():
        files = sorted(p for p in path.rglob("*") if p.suffix in (".txt", ".md") and p.is_file())
        return "\n".join(read_text(p) for p in files)
    return read_text(path)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("books", nargs="+", type=Path)
    parser.add_argument("--out", type=Path, required=True)
    args = parser.parse_args()
    args.out.mkdir(parents=True, exist_ok=True)
    rng = random.Random(20261121)
    count = 0
    for path in args.books:
        name = path.stem if path.is_file() else path.name
        chapters = [c for c in split_chapters(book_text(path)) if len(c.paragraphs) > 30]
        picked = rng.sample(chapters[: len(chapters) * 2 // 3] or chapters, GROUPS_PER_BOOK)
        for chapter in picked:
            segments = split_segments(chapter.paragraphs)
            batches = [b for b in label_batches(segments) if len(b) >= 6]
            if not batches:
                continue
            batch = rng.choice(batches)
            prompt, numbers = label_request(segments, batch, [], SHORT_LABEL_PROMPT)
            first = max(0, segments[batch[0]].para - CONTEXT_PARAGRAPHS)
            last = segments[batch[-1]].para + 6
            count += 1
            item = {
                "id": f"{count:03d}",
                "book": name,
                "chapter": chapter.title,
                "prompt": prompt,
                "lines": [{"id": n, "text": segments[i].text} for i, n in numbers.items()],
                "wider_text": "\n".join(chapter.paragraphs[first : last + 1]),
            }
            (args.out / f"{count:03d}.json").write_text(
                json.dumps(item, ensure_ascii=False, indent=1), encoding="utf-8"
            )
    print(f"{count} groups written to {args.out}")


if __name__ == "__main__":
    main()
