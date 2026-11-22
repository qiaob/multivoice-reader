# Android 版（开发中）

目标：把拆分和朗读都搬到手机上，模型在手机本地运行，不需要电脑或服务器。
开发时对着的机器是 vivo X300 Pro（天玑 9500，16 GB 内存）。

MLX 只能在苹果的芯片上跑，所以手机上的模型要换一种跑法；规则部分改写成 Kotlin。

| 部分 | 电脑版 | 手机版 | 状态 |
|---|---|---|---|
| 切章切句、数字读法、朗读脚本、选角、拆分时问模型的话和读回答 | Python | `core/`，纯 Kotlin | 完成，和 Python 逐条对照 |
| 判断说话人和情绪 | Qwen3.5-4B / Qwen3-1.7B 加微调权重，mlx-lm | llama.cpp：底座用现成的 GGUF，微调权重转成 GGUF 的 LoRA 适配器打进 app | 完成，待真机测试 |
| 合成语音 | Ming-3.0-tts-0.5B，mlx-audio | 拆成语言模型、DiT、Aggregator、音频 VAE 四块导出 ONNX，生成循环用 Kotlin 写 | 没开始，最大的风险 |
| 声音设计、复刻 | 好几个大模型 | 第一版不做 | — |
| 界面 | 网页 | `app/`：书架、导入 txt、后台拆分、看拆分结果、导出朗读脚本、下载模型 | 拆分部分完成，朗读部分没开始 |

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

## app

现在能做的：导入 txt 小说（可以一次选多本），在手机上拆分（锁屏也接着拆），看每章拆出来的说话人和情绪，
导出朗读脚本（电脑版可以直接读）。还不能朗读：语音合成还没搬过来。

用之前先在「模型」页下载底座模型：

| 模型 | 底座文件 | 大小 | 来源 |
|---|---|---|---|
| Qwen3-1.7B 微调版 | `Qwen3-1.7B-Q8_0.gguf`（Qwen 官方） | 1.8 GB | 魔搭 / Hugging Face |
| Qwen3.5-4B 微调版 | `Qwen3.5-4B-Q4_K_M.gguf`（unsloth） | 2.7 GB | 魔搭 / Hugging Face |

两个下载地址都没在这里验证过（这个开发环境连不上这两个网站）。下不了的话，可以填别的地址，
或者在电脑上下好传到手机，再用「从手机里的文件导入」。底座必须是同一个模型（同样的层数和尺寸），
量化方式不限；对不上时加载微调权重会报错。

「用一段示例试一下」拿 `docs/samples/night-rain.json` 那一段原创文字跑一遍，显示判断结果和速度，
还会检查模型文件自带的聊天模板是不是 Qwen3 那种（训练时提示是按它排的）。

微调权重是构建时从 `finetune/adapters/` 转出来的（`tools/peft_to_gguf.py`，只用 numpy，不需要 PyTorch）。
llama.cpp 的源码来自 PyPI 上 llama-cpp-python 的源码包（`tools/fetch_llama_cpp.sh`，版本固定），
不需要访问 GitHub；因此没有开 KleidiAI 加速（它的源码要从 GitHub 下载）。

编译 APK 需要 JDK 17+、Python 3 和 numpy、Android SDK（platform 35、build-tools 35、NDK 27.2.12479018、CMake 3.22.1）：

```bash
cd android
echo "sdk.dir=/path/to/android-sdk" > local.properties
./gradlew :app:assembleRelease     # app/build/outputs/apk/release/app-release.apk
```

只打 arm64 手机的包。release 包暂时用 debug 签名，可以直接安装。
