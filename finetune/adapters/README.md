# 微调好的标注模型：原始权重

任务是判断小说里每句对白是谁说的、带什么情绪。这里是在显卡上用 `../train_torch.py` 训出来的 LoRA 权重原件
（PEFT 格式，32 位浮点），接着训练或者转成别的格式都从它出发。

| 目录 | 底座 | 大小 | 测试集 | 验证集 |
|---|---|---|---|---|
| `qwen3.5-4b/` | `Qwen/Qwen3.5-4B` | 85 MB | 95% / 96% | 98% / 97% |
| `qwen3-1.7b/` | `Qwen/Qwen3-1.7B` | 70 MB | 91% / 93% | 95% / 95% |

成绩是「说话人 / 情绪」，未量化的底座在显卡上测的。两份都是用合成数据 1 万条加真实小说 911 段训 3000 步的最后一步，
每种大小只留了这一份；过程和全部成绩见 `../RESULTS.md`。

在显卡上打分：

```bash
python finetune/evaluate_real.py --set finetune/data/real/valid.jsonl \
    --model Qwen/Qwen3.5-4B --adapter finetune/adapters/qwen3.5-4b
```

程序在 Mac 上用的是转成 MLX 格式的那一份，在 `src/multivoice_reader/models/`（16 位浮点，大小减半）。
它是用 `../peft_to_mlx.py` 从这里转过去的：

```bash
uv run --no-project --python 3.11 --with mlx-lm python finetune/peft_to_mlx.py \
    finetune/adapters/qwen3-1.7b src/multivoice_reader/models/qwen3-1.7b --base mlx-community/Qwen3-1.7B-4bit
uv run --no-project --python 3.11 --with mlx-lm python finetune/peft_to_mlx.py \
    finetune/adapters/qwen3.5-4b src/multivoice_reader/models/qwen3.5-4b --base mlx-community/Qwen3.5-4B-MLX-4bit \
    --layers language_model.model.layers
```

配 4bit 底座在 Mac 上，旧测试集（186 句）的成绩是 97% / 98%（Qwen3.5-4B）和 90% / 96%（Qwen3-1.7B）。
