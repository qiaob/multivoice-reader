"""Draw passages from novels to be labelled, skipping the ones already in the sets.

    PYTHONPATH=src python finetune/labelling/sample_passages.py 小说1.txt 小说2.txt \\
        --out new/items --per-book 30 --prefix v --used finetune/data/real/train.jsonl

Writes one JSON file per passage: what the model sees, the numbered lines, and the wider text
around it for the labeller. The output holds text from the books.
"""

import argparse
import json
import random
from pathlib import Path

from multivoice_reader.analyze import SHORT_LABEL_PROMPT, label_batches, label_request
from multivoice_reader.text import read_text, split_chapters, split_segments

CONTEXT_PARAGRAPHS = 40
MAX_PROMPT = 2500  # longer than anything the reader asks, and too much card memory to train on


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("books", nargs="+", type=Path)
    parser.add_argument("--used", type=Path, nargs="*", default=[], help="已有的数据集文件，里面的片段不再抽")
    parser.add_argument("--out", type=Path, required=True)
    parser.add_argument("--per-book", type=int, default=30)
    parser.add_argument("--prefix", default="u")
    args = parser.parse_args()
    args.out.mkdir(parents=True, exist_ok=True)
    used = {json.loads(line)["prompt"] for path in args.used for line in path.open(encoding="utf-8")}
    rng = random.Random(20261123)
    count = 0
    for number, path in enumerate(args.books, 1):
        found = []
        for chapter in split_chapters(read_text(path)):
            segments = split_segments(chapter.paragraphs)
            for batch in label_batches(segments):
                if len(batch) < 6:
                    continue
                prompt, numbers = label_request(segments, batch, [], SHORT_LABEL_PROMPT)
                if prompt in used or len(prompt) > MAX_PROMPT:
                    continue
                found.append((chapter, segments, batch, prompt, numbers))
        rng.shuffle(found)
        for taken, (chapter, segments, batch, prompt, numbers) in enumerate(found[: args.per_book], 1):
            first = max(0, segments[batch[0]].para - CONTEXT_PARAGRAPHS)
            last = segments[batch[-1]].para + 6
            item = {
                "id": f"{args.prefix}{number:02d}-{taken:03d}",
                "book": path.stem,
                "chapter": chapter.title,
                "prompt": prompt,
                "lines": [{"id": n, "text": segments[i].text} for i, n in numbers.items()],
                "wider_text": "\n".join(chapter.paragraphs[first : last + 1]),
            }
            (args.out / f"{item['id']}.json").write_text(
                json.dumps(item, ensure_ascii=False, indent=1), encoding="utf-8"
            )
            count += 1
    print(f"{count} groups written")


if __name__ == "__main__":
    main()
