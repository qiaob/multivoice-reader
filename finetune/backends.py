"""Run a model on whichever machine this is: MLX on a Mac, PyTorch on an NVIDIA card elsewhere.

The two take different model names: MLX wants a converted one (mlx-community/...), PyTorch the
original (Qwen/...). A LoRA trained on one side only loads on that side.
"""

import sys
from collections.abc import Callable

from multivoice_reader.analyze import chat_prompt

ON_MAC = sys.platform == "darwin"
# Qwen3.5 would be the newer small model, but most of its layers are linear attention, which MLX
# trains with a per-token loop: over 20 GB for a 1000-token example. Qwen3 is plain attention.
BASE = "mlx-community/Qwen3-0.6B-4bit" if ON_MAC else "Qwen/Qwen3-0.6B"


TORCH_BATCH = 8


def load_generator(model: str, adapter: str | None = None) -> Callable[[list[str], int], list[str]]:
    """A function (prompts, max_tokens) -> the model's answer to each, decoded greedily."""
    if ON_MAC:
        from mlx_lm import generate, load

        net, tokenizer = load(model, adapter_path=adapter)
        return lambda prompts, max_tokens: [
            generate(net, tokenizer, prompt=chat_prompt(tokenizer, p), max_tokens=max_tokens, verbose=False)
            for p in prompts
        ]

    import torch
    from transformers import AutoModelForCausalLM, AutoTokenizer

    tokenizer = AutoTokenizer.from_pretrained(model, padding_side="left")
    net = AutoModelForCausalLM.from_pretrained(model, dtype=torch.bfloat16, device_map="cuda")
    if adapter:
        from peft import PeftModel

        net = PeftModel.from_pretrained(net, adapter).merge_and_unload()
    net.eval()

    def answers(prompts: list[str], max_tokens: int) -> list[str]:
        found = []
        # Token by token the card sits mostly idle; several prompts at once cost about the same.
        for start in range(0, len(prompts), TORCH_BATCH):
            texts = [chat_prompt(tokenizer, p) for p in prompts[start : start + TORCH_BATCH]]
            asked = tokenizer(texts, return_tensors="pt", padding=True, add_special_tokens=False).to(
                net.device
            )
            with torch.inference_mode():
                out = net.generate(**asked, max_new_tokens=max_tokens, do_sample=False)
            found += tokenizer.batch_decode(out[:, asked["input_ids"].shape[1] :], skip_special_tokens=True)
        return found

    return answers
