"""Score a model on passages from real novels that were labelled by hand.

    uv run --no-project --python 3.11 --with mlx-lm python finetune/evaluate_real.py \\
        --items books/eval/items --gold books/eval/gold.jsonl --adapter finetune/adapter
    ... --model mlx-community/Qwen3.5-9B-MLX-4bit        # the untuned model, full instructions

A speaker counts as right if it is the gold name or one of its accepted alternatives; lines
the labeller could not decide are left out. Prints accuracy overall and per book.
Runs on MLX on a Mac and on PyTorch elsewhere; see backends.py.
"""

import argparse
import json
import re
from collections import defaultdict
from pathlib import Path

from backends import BASE, load_generator

from multivoice_reader.analyze import EMOTIONS, LABEL_PROMPT, _clean_name, _first_json


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--items", type=Path, required=True)
    parser.add_argument("--gold", type=Path, required=True)
    parser.add_argument("--model", default=BASE)
    parser.add_argument("--adapter", help="LoRA 权重目录；不给就按未微调的模型、用完整的说明来问")
    args = parser.parse_args()
    gold = {row["id"]: row["labels"] for row in map(json.loads, args.gold.open(encoding="utf-8"))}
    generate = load_generator(args.model, args.adapter)
    items = [json.loads(path.read_text(encoding="utf-8")) for path in sorted(args.items.glob("*.json"))]
    prompts = [item["prompt"] for item in items]
    if not args.adapter:  # an untuned model needs the rules spelled out
        for i, prompt in enumerate(prompts):
            known, excerpt = re.match(r"已知角色：(.*?)\n\n(.*)\n\n标出", prompt, re.S).groups()
            prompts[i] = LABEL_PROMPT.format(known=known, excerpt=excerpt, emotions="、".join(EMOTIONS))
    answers = generate(prompts, 40 * max(len(item["lines"]) for item in items) + 40)
    per_book = defaultdict(lambda: [0, 0, 0])  # lines, speakers right, emotions right
    for item, answer in zip(items, answers, strict=True):
        found = {x.get("id"): x for x in _first_json(answer, "[", "]") or [] if isinstance(x, dict)}
        for label in gold[item["id"]]:
            if label.get("unsure"):
                continue
            got = found.get(label["id"], {})
            score = per_book[item["book"]]
            score[0] += 1
            score[1] += _clean_name(got.get("speaker")) in [label["speaker"], *label.get("accept", [])]
            score[2] += got.get("emotion") in [label["emotion"], *label.get("emotion_accept", [])]
    print(f"model: {args.model}  adapter: {args.adapter or '(none)'}")
    total = [sum(s[i] for s in per_book.values()) for i in range(3)]
    print(f"{'书':<16}{'句数':>6}{'说话人':>8}{'情绪':>8}")
    for book, (lines, speakers, emotions) in sorted(per_book.items()):
        print(f"{book[:14]:<16}{lines:>6}{speakers / lines:>8.0%}{emotions / lines:>8.0%}")
    print(f"{'合计':<16}{total[0]:>6}{total[1] / total[0]:>8.0%}{total[2] / total[0]:>8.0%}")


if __name__ == "__main__":
    main()
