# Android 版（开发中）

目标：把拆分和朗读都搬到手机上，模型在手机本地运行，不需要电脑或服务器。
开发时对着的机器是 vivo X300 Pro（天玑 9500，16 GB 内存）。

MLX 只能在苹果的芯片上跑，所以手机上的模型要换一种跑法；规则部分改写成 Kotlin。

| 部分 | 电脑版 | 手机版 | 状态 |
|---|---|---|---|
| 切章切句、数字读法、朗读脚本、选角、拆分时问模型的话和读回答 | Python | `core/`，纯 Kotlin | 完成，和 Python 逐条对照 |
| 判断说话人和情绪 | Qwen3.5-4B / Qwen3-1.7B 加微调权重，mlx-lm | llama.cpp：底座转 GGUF，微调权重转成 GGUF 的 LoRA 适配器 | 没开始 |
| 合成语音 | Ming-3.0-tts-0.5B，mlx-audio | 拆成语言模型、DiT、Aggregator、音频 VAE 四块导出 ONNX，生成循环用 Kotlin 写 | 没开始，最大的风险 |
| 声音设计、复刻 | 好几个大模型 | 第一版不做 | — |
| 界面、后台合成、锁屏播放 | 网页 | `app/` | 没开始 |

微调权重要转成单独的 LoRA 适配器，不要合进底座：判断新角色的性别和年龄时要关掉微调权重
（`Analyzer.profiles` 里的 `tuned = false`），llama.cpp 可以在运行时开关适配器。

## core 和 Python 版保持一致

模型是按 Python 版生成的提示词微调的，手机上问模型的话必须一字不差。
`tools/make_golden.py` 用 Python 版处理一批输入（`finetune/data/real` 里真实小说片段的原文，加上 `tests/` 里的例子），
把结果写进 `core/src/test/resources/golden/`；Kotlin 的测试拿同样的输入跑一遍，逐条比较：

- 50 段小说切出来的每一句、每句的读法；
- 把这些片段当一本书切章，加几种难认的章节标题、水印、换行符；
- 拆分时问模型的 438 次提示词和 max_tokens（模型换成了一个两边写法相同的假模型），以及从回答里读出的说话人、情绪、新角色；
- 由此得到的朗读脚本，写成文件后逐字节相同；
- 内置的 36 个声音在四种题材下给 60 个角色配的声音。

改了 Python 版的这些部分以后：

```bash
PYTHONPATH=src python3 android/tools/make_golden.py   # 重新生成标准答案
cd android && ./gradlew :core:test                   # Kotlin 跟上
```

`tests/test_android_golden.py` 会在标准答案过期时报错，提醒做这一步。

Python 和 Kotlin 在文字上有几处不一样（字数按码位还是按 UTF-16 算、哪些算空白、怎么分行、JSON 解析宽严），
都在 `Py.kt` 和 `PyJsonLoads.kt` 里按 Python 的做法处理了。

## 跑测试

只需要 JDK 17 以上，不需要 Android SDK：

```bash
cd android
./gradlew :core:test
```
