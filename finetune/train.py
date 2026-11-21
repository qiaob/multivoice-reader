"""Fine-tune a very small language model on finetune/data (LoRA, on this Mac).

    uv run --no-project --python 3.11 --with mlx-lm python finetune/train.py
    ... --iters 200            # a short run, to see the speed first
    ... --resume some.safetensors   # carry on from saved weights

Two examples per step is what fits in 16 GB: four ran out of memory. A step takes about five
seconds on an M3, so a full run is several hours.

Only the answer is trained on (the prompt is masked out). Output: finetune/adapter/.
On an NVIDIA card use train_torch.py instead; it is far quicker, and it is what the adapters
in finetune/adapters/ were trained with.
"""

import argparse
import json
import os
import subprocess
import sys
from pathlib import Path

from backends import BASE
from mlx_lm import load

from multivoice_reader.analyze import chat_prompt

ROOT = Path(__file__).parent


def check_template(base: str) -> None:
    """Training goes through the tokenizer's chat template; so does reading a book. If the two
    render the prompt differently, the model is trained on one thing and asked another."""
    _, tokenizer = load(base)
    row = json.loads((ROOT / "data" / "valid.jsonl").open(encoding="utf-8").readline())
    trained_on = tokenizer.apply_chat_template(row["messages"], tokenize=False)
    asked_with = chat_prompt(tokenizer, row["messages"][0]["content"])
    if not trained_on.startswith(asked_with):
        at = len(asked_with)
        raise SystemExit(
            "聊天模板不一致，训练和推理看到的提示不同。\n"
            f"推理时的结尾：{asked_with[-60:]!r}\n训练时对应位置：{trained_on[at - 60 : at]!r}"
        )


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--base", default=BASE)
    parser.add_argument("--iters", type=int, default=2000)
    parser.add_argument("--batch-size", type=int, default=2)
    parser.add_argument("--learning-rate", type=float, default=1e-4)
    parser.add_argument("--resume", type=Path, help="接着这份 LoRA 权重继续训练")
    args = parser.parse_args()
    check_template(args.base)
    options = {
        "--model": args.base,
        "--data": ROOT / "data",
        "--adapter-path": ROOT / "adapter",
        "--iters": args.iters,
        "--batch-size": args.batch_size,
        "--learning-rate": args.learning_rate,
        "--num-layers": -1,  # every layer
        "--max-seq-length": 1100,  # the longest example is 1060 tokens; shorter cuts off answers
        "--steps-per-report": 50,
        "--steps-per-eval": 500,
        "--val-batches": 25,
        "--save-every": 500,
    }
    command = [sys.executable, "-m", "mlx_lm", "lora", "--train", "--mask-prompt"]
    command += [str(part) for pair in options.items() for part in pair]
    if args.resume:
        command += ["--resume-adapter-file", str(args.resume)]
    subprocess.run(command, check=True, env={**os.environ, "PYTHONUNBUFFERED": "1"})


if __name__ == "__main__":
    main()
