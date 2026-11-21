"""Turn the labelled passages from real novels into training rows, alone or mixed with the synthetic set.

    python finetune/mix_real.py --out finetune/data/train_mixed.jsonl             # synthetic + real x5
    python finetune/mix_real.py --out finetune/data/train_real.jsonl --repeat 0   # real only

The result is what train_torch.py takes as --train. Stdlib only.
"""

import argparse
import json
from pathlib import Path

ROOT = Path(__file__).parent
# Far longer than anything the reader asks about at once, and too much card memory to train on.
MAX_PROMPT_CHARS = 2500


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--out", type=Path, required=True)
    parser.add_argument(
        "--repeat", type=int, default=5, help="真实片段重复几次再和合成数据混在一起；0 表示只要真实片段"
    )
    args = parser.parse_args()

    real = []
    for line in (ROOT / "data" / "real" / "train.jsonl").open(encoding="utf-8"):
        row = json.loads(line)
        if len(row["prompt"]) > MAX_PROMPT_CHARS:
            continue
        answer = [{"id": x["id"], "speaker": x["speaker"], "emotion": x["emotion"]} for x in row["labels"]]
        messages = [
            {"role": "user", "content": row["prompt"]},
            {"role": "assistant", "content": json.dumps(answer, ensure_ascii=False)},
        ]
        real.append(json.dumps({"messages": messages}, ensure_ascii=False) + "\n")
    synthetic = []
    if args.repeat:
        synthetic = (ROOT / "data" / "train.jsonl").read_text(encoding="utf-8").splitlines(keepends=True)
    args.out.write_text("".join(synthetic + real * max(args.repeat, 1)), encoding="utf-8")
    print(f"{len(synthetic)} synthetic + {len(real)} real x {max(args.repeat, 1)} -> {args.out}")


if __name__ == "__main__":
    main()
