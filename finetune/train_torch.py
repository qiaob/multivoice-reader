"""Fine-tune on an NVIDIA card (PyTorch + PEFT LoRA). Same data and same prompt as train.py.

    python finetune/train_torch.py --out finetune/runs/qwen3-1.7b --grad-checkpoint
    ... --base Qwen/Qwen3-0.6B --iters 500 --batch-size 8

--grad-checkpoint is what makes 1.7B and larger fit in 16 GB of card memory; 0.6B fits without.

Needs torch (a CUDA build), transformers and peft. Only the answer is trained on. Every
--save-every steps the loss on the validation set is printed and the LoRA is saved to
<out>/step-NNNNN, which evaluate.py and evaluate_real.py take as --adapter. To use one on a
Mac, convert it with peft_to_mlx.py. The defaults take about 25 minutes on an RTX 5070 Ti.
"""

import argparse
import json
import math
import random
import time
from pathlib import Path

import torch
from backends import BASE
from peft import LoraConfig, get_peft_model
from transformers import AutoModelForCausalLM, AutoTokenizer

from multivoice_reader.analyze import chat_prompt

ROOT = Path(__file__).parent
END = "<|im_end|>"  # what the chat template closes an answer with
WARMUP_STEPS = 50
VALID_EXAMPLES = 100


def encode(tokenizer, row: dict) -> tuple[list[int], list[int]]:
    """Token ids, and the same with the prompt blanked out so that only the answer is learned.
    The prompt is rendered exactly as it is when reading a book."""
    asked = tokenizer(chat_prompt(tokenizer, row["messages"][0]["content"]), add_special_tokens=False)
    answer = tokenizer(row["messages"][1]["content"] + END, add_special_tokens=False)
    return asked["input_ids"] + answer["input_ids"], [-100] * len(asked["input_ids"]) + answer["input_ids"]


def batch_of(examples: list[tuple[list[int], list[int]]], pad: int) -> dict:
    width = max(len(ids) for ids, _ in examples)
    ids = torch.tensor([i + [pad] * (width - len(i)) for i, _ in examples])
    labels = torch.tensor([t + [-100] * (width - len(t)) for _, t in examples])
    mask = torch.tensor([[1] * len(i) + [0] * (width - len(i)) for i, _ in examples])
    return {"input_ids": ids.cuda(), "labels": labels.cuda(), "attention_mask": mask.cuda()}


def load_split(tokenizer, name: str) -> list[tuple[list[int], list[int]]]:
    rows = map(json.loads, (ROOT / "data" / f"{name}.jsonl").open(encoding="utf-8"))
    return [encode(tokenizer, row) for row in rows]


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--base", default=BASE)
    parser.add_argument("--out", type=Path, required=True)
    parser.add_argument("--iters", type=int, default=2000)
    parser.add_argument("--batch-size", type=int, default=4)
    parser.add_argument("--learning-rate", type=float, default=1e-4)
    parser.add_argument("--rank", type=int, default=16)
    parser.add_argument("--save-every", type=int, default=200)
    parser.add_argument("--grad-checkpoint", action="store_true", help="省显存，慢一些；大模型需要")
    args = parser.parse_args()

    random.seed(0)
    torch.manual_seed(0)
    tokenizer = AutoTokenizer.from_pretrained(args.base)
    rendered = tokenizer.apply_chat_template(
        [{"role": "user", "content": "问"}, {"role": "assistant", "content": "答"}], tokenize=False
    )
    if not rendered.rstrip().endswith("答" + END):
        raise SystemExit(f"这个模型的聊天模板不是用 {END} 结束回答的：{rendered[-40:]!r}")
    train, valid = load_split(tokenizer, "train"), load_split(tokenizer, "valid")[:VALID_EXAMPLES]
    pad = tokenizer.pad_token_id if tokenizer.pad_token_id is not None else tokenizer.eos_token_id

    model = AutoModelForCausalLM.from_pretrained(args.base, dtype=torch.bfloat16, device_map="cuda")
    if args.grad_checkpoint:
        model.gradient_checkpointing_enable(gradient_checkpointing_kwargs={"use_reentrant": False})
    model = get_peft_model(
        model,
        LoraConfig(
            r=args.rank,
            lora_alpha=2 * args.rank,
            lora_dropout=0.05,
            target_modules=["q_proj", "k_proj", "v_proj", "o_proj", "gate_proj", "up_proj", "down_proj"],
            task_type="CAUSAL_LM",
        ),
    )
    model.print_trainable_parameters()
    optimizer = torch.optim.AdamW((p for p in model.parameters() if p.requires_grad), lr=args.learning_rate)
    # Warm up, then ease the rate down to a tenth by the last step.
    schedule = torch.optim.lr_scheduler.LambdaLR(
        optimizer,
        lambda step: (
            min(1.0, (step + 1) / WARMUP_STEPS)
            * (0.55 + 0.45 * math.cos(math.pi * min(1.0, step / args.iters)))
        ),
    )

    decoder = model.get_base_model()

    def loss_of(examples) -> torch.Tensor:
        # Scores over the whole vocabulary are worked out for the answer's tokens only: for
        # every token of the prompt as well they take several times the memory of the model.
        batch = batch_of(examples, pad)
        targets = batch["labels"][:, 1:]
        with torch.autocast("cuda", dtype=torch.bfloat16):
            hidden = decoder.model(input_ids=batch["input_ids"], attention_mask=batch["attention_mask"])[0]
            scores = decoder.lm_head(hidden[:, :-1][targets != -100])
        return torch.nn.functional.cross_entropy(scores.float(), targets[targets != -100])

    order: list[int] = []
    started = time.time()
    running = 0.0
    for step in range(1, args.iters + 1):
        if len(order) < args.batch_size:
            order = random.sample(range(len(train)), len(train))
        picked = [train[order.pop()] for _ in range(args.batch_size)]
        model.train()
        loss = loss_of(picked)
        loss.backward()
        optimizer.step()
        schedule.step()
        optimizer.zero_grad(set_to_none=True)
        running += loss.item()
        if step % 50 == 0:
            print(f"step {step:5d}  train loss {running / 50:.4f}  {time.time() - started:.0f}s", flush=True)
            running = 0.0
        if step % args.save_every == 0 or step == args.iters:
            model.eval()
            with torch.inference_mode():
                losses = [loss_of(valid[i : i + 8]).item() for i in range(0, len(valid), 8)]
            print(f"step {step:5d}  valid loss {sum(losses) / len(losses):.4f}", flush=True)
            model.save_pretrained(args.out / f"step-{step:05d}")
    print(f"peak GPU memory: {torch.cuda.max_memory_allocated() / 2**30:.1f} GB", flush=True)


if __name__ == "__main__":
    main()
