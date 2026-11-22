"""Turn the fine-tuned LoRA weights (finetune/adapters, PEFT format) into llama.cpp adapters.

    python3 android/tools/peft_to_gguf.py <adapter folder> <out.gguf> --arch qwen3|qwen35

The phone runs the base model as a GGUF file and puts this adapter on top while labelling
lines, and takes it off to tell a new character's gender and age (as analyze.Analyzer does).

llama.cpp's own convert_lora_to_gguf.py needs PyTorch and the base model's files. Neither is
needed here: the adapters only touch the MLP and the full-attention q/k/v/o projections, which
llama.cpp's converter carries over unchanged for these architectures apart from their names,
so the tensors are renamed and written as they are. Needs numpy and the gguf package that
comes with llama.cpp (tools/fetch_llama_cpp.sh puts it in third_party/).
"""

import argparse
import json
import re
import struct
import sys
from pathlib import Path

import numpy as np

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent / "third_party" / "llama.cpp" / "gguf-py"))
import gguf  # noqa: E402

ARCHS = {"qwen3": gguf.MODEL_ARCH.QWEN3, "qwen35": gguf.MODEL_ARCH.QWEN35}
TOUCHED = re.compile(r"\.(mlp\.(gate|up|down)_proj|self_attn\.[qkvo]_proj)\.lora_[AB]\.weight$")
DTYPES = {"F32": np.float32, "F16": np.float16}


def read_safetensors(path: Path) -> dict[str, np.ndarray]:
    with path.open("rb") as f:
        size = struct.unpack("<Q", f.read(8))[0]
        header = json.loads(f.read(size))
        data = f.read()
    out = {}
    for name, about in header.items():
        if name == "__metadata__":
            continue
        start, end = about["data_offsets"]
        out[name] = np.frombuffer(data[start:end], dtype=DTYPES[about["dtype"]]).reshape(about["shape"])
    return out


def convert(folder: Path, out: Path, arch: str) -> int:
    config = json.loads((folder / "adapter_config.json").read_text())
    if config.get("use_dora") or config.get("use_rslora") or config.get("modules_to_save"):
        raise SystemExit("只支持普通的 LoRA")
    tensors = read_safetensors(folder / "adapter_model.safetensors")
    strange = [name for name in tensors if not TOUCHED.search(name)]
    if strange:
        raise SystemExit(f"这些权重的转换方式没有核对过：{strange[:3]}")
    blocks = 1 + max(int(re.search(r"\.layers\.(\d+)\.", name).group(1)) for name in tensors)
    names = gguf.get_tensor_name_map(ARCHS[arch], blocks)

    writer = gguf.GGUFWriter(str(out), gguf.MODEL_ARCH_NAMES[ARCHS[arch]])
    writer.add_type(gguf.GGUFType.ADAPTER)
    writer.add_string(gguf.Keys.Adapter.TYPE, "lora")
    writer.add_float32(gguf.Keys.Adapter.LORA_ALPHA, float(config["lora_alpha"]))
    writer.add_string(gguf.Keys.General.NAME, f"multivoice-reader labeller ({folder.name})")
    count = 0
    for name in sorted(tensors):
        base = re.sub(r"\.lora_[AB]\.weight$", "", name.replace("base_model.model.", ""))
        mapped = names.get_name(base)
        if mapped is None:
            raise SystemExit(f"不知道 {base} 在 llama.cpp 里叫什么")
        suffix = ".lora_a" if ".lora_A." in name else ".lora_b"
        writer.add_tensor(mapped + ".weight" + suffix, tensors[name].astype(np.float16))
        count += 1
    writer.write_header_to_file()
    writer.write_kv_data_to_file()
    writer.write_tensors_to_file()
    writer.close()
    return count


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    parser.add_argument("adapter", type=Path)
    parser.add_argument("out", type=Path)
    parser.add_argument("--arch", choices=list(ARCHS), required=True)
    args = parser.parse_args()
    args.out.parent.mkdir(parents=True, exist_ok=True)
    count = convert(args.adapter, args.out, args.arch)
    print(f"{args.out}：{count} 个张量")


if __name__ == "__main__":
    main()
