"""Turn a LoRA trained by train_torch.py into one that MLX loads, so it can be used on a Mac.

    uv run --no-project --python 3.11 --with mlx-lm python finetune/peft_to_mlx.py \\
        runs/qwen3-1.7b/step-02000 finetune/adapter --base mlx-community/Qwen3-1.7B-4bit

The numbers are the same; the two libraries only name and lay them out differently. Stored as
16-bit floats, which halves the file.
"""

import argparse
import json
import re
from pathlib import Path

import mlx.core as mx

NAME = re.compile(r"base_model\.model\.(model\.layers\.\d+\.(.+))\.lora_([AB])\.weight")


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("peft", type=Path, help="train_torch.py 存下的某一步的目录")
    parser.add_argument("out", type=Path)
    parser.add_argument("--base", required=True, help="在 Mac 上配合使用的底座模型")
    args = parser.parse_args()

    config = json.loads((args.peft / "adapter_config.json").read_text(encoding="utf-8"))
    weights, modules = {}, set()
    for name, value in mx.load(str(args.peft / "adapter_model.safetensors")).items():
        layer, module, part = NAME.fullmatch(name).groups()
        modules.add(module)
        # PyTorch keeps a linear layer's weight as (out, in); MLX multiplies from the other side.
        weights[f"{layer}.lora_{part.lower()}"] = value.T.astype(mx.float16)
    args.out.mkdir(parents=True, exist_ok=True)
    mx.save_safetensors(str(args.out / "adapters.safetensors"), weights)
    (args.out / "adapter_config.json").write_text(
        json.dumps(
            {
                "model": args.base,
                "trained_on": config["base_model_name_or_path"],
                "fine_tune_type": "lora",
                "num_layers": -1,
                "lora_parameters": {
                    "rank": config["r"],
                    "scale": config["lora_alpha"] / config["r"],
                    "dropout": 0.0,
                    "keys": sorted(modules),
                },
            },
            ensure_ascii=False,
            indent=2,
        )
        + "\n",
        encoding="utf-8",
    )
    print(f"wrote {len(weights)} tensors for {len(modules)} kinds of layer to {args.out}")


if __name__ == "__main__":
    main()
