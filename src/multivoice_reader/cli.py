"""mvr: split novels into reading scripts, and read scripts aloud.

mvr split 小说.txt -o 脚本.json       a novel -> a reading script (who says what, and how)
    ... --model qwen3-1.7b           with another of the labelling models
mvr generate 脚本.json -o 目录        a reading script -> one audio file per chapter
mvr voices                           list the voices there are to cast from
mvr design 描述 -o 目录/名字         a voice of your own from a description of it
mvr web                              the same two jobs in the browser, plus the voice library and cloning

The two commands know nothing of each other: split writes a script, generate reads any
script, whoever wrote it. The format is described in script.py.
"""

import argparse
import webbrowser
from pathlib import Path

from .analyze import DEFAULT_MODEL, MODELS
from .casting import GENRES
from .script import AGES, GENDERS, UNKNOWN
from .voices import library

PORT = 8766


def voice_dirs(args: argparse.Namespace) -> list[Path]:
    return [path.expanduser().resolve() for path in args.voices]


def existing(path: Path) -> Path:
    if not path.is_file():
        raise SystemExit(f"找不到文件：{path}")
    return path


def split_command(args: argparse.Namespace) -> None:
    from .split import split_file

    out = args.out.expanduser().resolve()
    try:
        script = split_file(existing(args.novel), out, args.chapters, args.model)
    except ValueError as err:
        raise SystemExit(str(err)) from err
    lines = sum(len(chapter["lines"]) for chapter in script["chapters"])
    print(f"完成：{len(script['chapters'])} 章 {lines} 句，{len(script['characters'])} 个角色，脚本在 {out}")


def generate_command(args: argparse.Namespace) -> None:
    from .generate import generate
    from .script import NARRATOR

    cast = {}
    for pair in args.cast:
        who, _, voice = pair.partition("=")
        if not who.strip() or not voice.strip():
            raise SystemExit(f"--cast 要写成 角色=声音名，看不懂「{pair}」")
        cast[who.strip()] = voice.strip()
    if args.narrator:
        cast[NARRATOR] = args.narrator
    out = args.out.expanduser().resolve()
    try:
        written = generate(
            existing(args.script), out, voice_dirs(args), args.chapters, cast, genre=args.genre
        )
    except ValueError as err:
        raise SystemExit(str(err)) from err
    print(f"完成：{len(written)} 个音频文件在 {out}")


def voices_command(args: argparse.Namespace) -> None:
    for voice in library(voice_dirs(args)).values():
        mine = {"clone": "（复刻的）", "design": "（设计的）"}.get(voice.kind, "")
        print(f"{voice.id:<18}{voice.name}{mine}　{voice.gender}　{voice.age}　{voice.desc[:30]}")


def design_command(args: argparse.Namespace) -> None:
    from .design import design

    out = args.out.expanduser().resolve()
    try:
        voice = design(args.desc, out, args.name, args.gender, args.age, args.text)
    except ValueError as err:
        raise SystemExit(str(err)) from err
    print(f"完成：「{voice.name}」在 {out}，录音是 {voice.ref_audio.name}，可以直接听")
    print(f"朗读时用它：mvr generate 脚本.json -o 输出目录 --voices {out.parent} --narrator {voice.name}")


def web_command(args: argparse.Namespace) -> None:
    from .server import App, serve

    app = App(voice_dirs(args))
    if not app.voices():
        raise SystemExit("声音库是空的。")
    url = f"http://127.0.0.1:{args.port}/"
    print(f"页面：{url}　（按 Ctrl+C 结束）")
    if not args.no_browser:
        webbrowser.open(url)
    serve(app, args.port)


def main() -> None:
    parser = argparse.ArgumentParser(
        prog="mvr", description="把小说拆成朗读脚本，把朗读脚本读出来：分角色、带情绪，全部在本机运行"
    )
    more_voices = argparse.ArgumentParser(add_help=False)
    more_voices.add_argument(
        "--voices", type=Path, action="append", default=[], help="额外的声音目录，可以给多次"
    )
    commands = parser.add_subparsers(dest="command", required=True)

    split = commands.add_parser("split", help="把小说拆成朗读脚本：每句话是谁说的、什么情绪")
    split.add_argument("novel", type=Path, help="小说的 txt 文件")
    split.add_argument("-o", "--out", type=Path, required=True, help="脚本写到哪个文件；已有的话接着往下拆")
    split.add_argument("--chapters", default="", help="只拆这些章，比如 5 或 1-20；默认全部")
    models = "；".join(f"{name}（{about['about']}）" for name, about in MODELS.items())
    split.add_argument(
        "--model", default=DEFAULT_MODEL, choices=list(MODELS), help=f"用哪个模型判断说话人和情绪：{models}"
    )
    split.set_defaults(run=split_command)

    generate = commands.add_parser("generate", parents=[more_voices], help="把朗读脚本读成音频文件，每章一个")
    generate.add_argument("script", type=Path, help="朗读脚本（JSON）")
    generate.add_argument(
        "-o", "--out", type=Path, required=True, help="输出目录；中间结果也在里面，重跑会接着做"
    )
    generate.add_argument("--chapters", default="", help="只读这些章，比如 5 或 1-20；默认全部")
    generate.add_argument("--narrator", default="", help="旁白用哪个声音（名字见 mvr voices）；默认自动选")
    generate.add_argument(
        "--cast", action="append", default=[], metavar="角色=声音", help="指定一个角色的声音，可以给多次"
    )
    genres = "、".join(f"{genre}（{about['name']}）" for genre, about in GENRES.items())
    generate.add_argument(
        "--genre",
        choices=list(GENRES),
        help=f"按哪种题材来读：旁白和自动配的角色用那个题材的声音。{genres}；不给就不分题材",
    )
    generate.set_defaults(run=generate_command)

    voices = commands.add_parser("voices", parents=[more_voices], help="列出可以用的声音")
    voices.set_defaults(run=voices_command)

    design = commands.add_parser("design", help="按一段描述设计一个声音；每次生成的都不一样，可以多做几个挑")
    design.add_argument("desc", help="想要的声音，比如：四十多岁男性，嗓音低沉，语速缓慢，吐字清晰")
    design.add_argument(
        "-o", "--out", type=Path, required=True, help="这个声音的目录；它的上一级目录可以交给 --voices"
    )
    design.add_argument("--name", default="", help="声音的名字；默认用目录名")
    design.add_argument("--gender", default=UNKNOWN, choices=GENDERS, help="性别，只用来显示")
    design.add_argument("--age", default=UNKNOWN, choices=AGES, help="年龄段，只用来显示")
    design.add_argument("--text", default="", help="生成录音时读的话，15 到 80 个字；默认是一段旁白")
    design.set_defaults(run=design_command)

    web = commands.add_parser(
        "web", parents=[more_voices], help="打开网页：拆分、朗读、声音试听、声音设计、声音复刻"
    )
    web.add_argument("--port", type=int, default=PORT)
    web.add_argument("--no-browser", action="store_true", help="不自动打开浏览器")
    web.set_defaults(run=web_command)

    args = parser.parse_args()
    args.run(args)


if __name__ == "__main__":
    main()
