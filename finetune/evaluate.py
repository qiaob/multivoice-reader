"""Score a model on finetune/data/test.jsonl: how often it names the right speaker and emotion.

    uv run --no-project --python 3.11 --with mlx-lm python finetune/evaluate.py --adapter finetune/adapter
    ... --limit 100                                   # fewer examples, quicker

Runs on MLX on a Mac and on PyTorch elsewhere; see backends.py.
"""

import argparse
import json
import time
from pathlib import Path

from backends import BASE, load_generator

from multivoice_reader.analyze import _first_json

ROOT = Path(__file__).parent


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--model", default=BASE)
    parser.add_argument("--adapter", help="LoRA 权重目录；不给就评测原始模型")
    parser.add_argument("--limit", type=int, default=200)
    args = parser.parse_args()
    generate = load_generator(args.model, args.adapter)
    rows = [json.loads(line) for line in (ROOT / "data" / "test.jsonl").open(encoding="utf-8")][: args.limit]
    lines = speaker_ok = emotion_ok = whole_ok = 0
    started = time.time()
    golds = [json.loads(row["messages"][1]["content"]) for row in rows]
    answers = generate([row["messages"][0]["content"] for row in rows], 40 * max(map(len, golds)) + 40)
    for gold, answer in zip(golds, answers, strict=True):
        found = {x.get("id"): x for x in _first_json(answer, "[", "]") or [] if isinstance(x, dict)}
        right = 0
        for item in gold:
            got = found.get(item["id"], {})
            lines += 1
            speaker_ok += got.get("speaker") == item["speaker"]
            emotion_ok += got.get("emotion") == item["emotion"]
            right += got.get("speaker") == item["speaker"] and got.get("emotion") == item["emotion"]
        whole_ok += right == len(gold)
    took = time.time() - started
    print(f"model: {args.model}  adapter: {args.adapter or '(none)'}")
    print(f"examples: {len(rows)}  lines: {lines}  time: {took:.0f}s ({took / len(rows):.2f}s per example)")
    print(f"speaker accuracy: {speaker_ok / lines:.1%}")
    print(f"emotion accuracy: {emotion_ok / lines:.1%}")
    print(f"examples entirely right: {whole_ok / len(rows):.1%}")


if __name__ == "__main__":
    main()
