# multivoice-reader

把小说读给你听：自动分出旁白和每个角色，给他们配上不同的声音，按台词的情绪来读。
分析、选角、合成语音全部在你自己的电脑上完成，不调用任何云端接口。

目前只支持 Apple Silicon 的 Mac（模型通过 MLX 运行）。项目还在早期，接口和文件格式都可能变。

## 用起来

需要 [uv](https://docs.astral.sh/uv/) 和 ffmpeg（`brew install ffmpeg`）。

```bash
git clone https://github.com/qiaob/multivoice-reader.git
cd multivoice-reader
uv run mvr read 小说.txt
```

第一次运行会下载两个模型，共约 8.4 GB。之后浏览器会打开朗读页面：

- 左边是章节目录，中间是正文，右边是每个角色用的声音。
- 点「播放」开始读。正文里已经合成好的句子是深色的，还没好的是浅色的，点任何一句可以从那里读起。
- 觉得哪个角色的声音不合适，在右边换一个，这个角色的台词会重新合成。

合成速度和播放速度差不多，所以是边合成边读：读到还没合成的句子会停下来等。
它总是优先合成你正在听的位置，并提前准备后面两章。

## 它是怎么工作的

```
小说.txt ─切章切句─> 旁白和对白 ─语言模型─> 每句是谁说的、什么情绪 ─选角─> 逐句合成 ─> 边读边听
```

1. **切章切句**：按「第 X 章」切章，按引号把正文分成旁白和对白。纯规则。
2. **分析**：一个本地小语言模型判断每句对白是谁说的、带什么情绪，并记下新角色的性别和年龄段。它只打标签，不改写原文。
3. **选角**：按性别和年龄段，从声音库里给每个角色挑一个还没人用的声音。
4. **合成**：语音模型用这个声音的参考录音来读这句话，并带上情绪。

每本书的分析结果和音频都存在 `~/.multivoice-reader/books/` 下，关掉再打开会从上次的位置继续，不会重做。

语言模型会判断错。说话人标错时，那句话会用错声音，但文字不会错。

## 声音

一个声音就是「一段参考录音加上录音里说的话」。声音库有两个来源：

- **内置的声音**：`src/multivoice_reader/voices/` 里的原创音色，按文字描述生成，不是任何真人的声音。
- **你自己的声音**：用「声音复刻」页从一段录音做出来，导出成 `.voice.zip`，再加入声音库：

  ```bash
  uv run mvr voices add 我的声音.voice.zip
  uv run mvr voices          # 查看声音库
  ```

只复刻你自己的声音，或已获得本人同意的声音。

## 声音试听和声音复刻

`audition/` 目录下是另一套工具，用来试听、比较和复刻声音，目前是独立运行的：

```bash
uv run --no-project --with mlx-audio python audition/serve.py     # http://127.0.0.1:8765/
```

## 用到的模型

| 用途 | 模型 |
|---|---|
| 合成语音（复刻加情绪） | Ming-3.0-tts-0.5B |
| 判断说话人和情绪 | Qwen3.5-9B（4bit 量化） |
| 设计内置音色 | Qwen3-TTS VoiceDesign |
| 复刻时分离人声、去噪、识别原话 | Mel-Band-RoFormer、DeepFilterNet、Qwen3-ASR |

## 开发

```bash
docker run --rm -v "$PWD":/work -w /work python:3.11-slim \
  sh -c "pip install -q ruff pytest numpy && ruff check src tests && python -m pytest -q tests"
```

测试只覆盖不需要模型的部分：切章切句、数字读法、选角、书的存取。

## 许可

MIT。请只朗读你有权使用的文本。
