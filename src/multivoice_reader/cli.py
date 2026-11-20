"""mvr: read a novel aloud.

mvr read 小说.txt        analyse it, cast the voices, open the reader in the browser
mvr read                 reopen the reader (pick a book on the page)
mvr voices               list the voices in the library
mvr voices add 包.zip     add an exported voice pack to the library
"""

import argparse
import webbrowser
from pathlib import Path

from .book import Book
from .server import App, serve
from .voices import import_pack, library

PORT = 8766


def main() -> None:
    parser = argparse.ArgumentParser(
        prog="mvr", description="小说朗读：自动分角色、选声音、带情绪，全部在本机运行"
    )
    commands = parser.add_subparsers(dest="command", required=True)
    read = commands.add_parser("read", help="朗读一本小说")
    read.add_argument("book", nargs="?", type=Path, help="小说的 txt 文件；不给就在网页里选")
    read.add_argument("--port", type=int, default=PORT)
    read.add_argument("--voices", type=Path, action="append", default=[], help="额外的声音目录，可以给多次")
    read.add_argument("--no-browser", action="store_true", help="不自动打开浏览器")
    voices = commands.add_parser("voices", help="查看或添加声音")
    voices.add_argument("action", nargs="?", choices=["add"])
    voices.add_argument("pack", nargs="?", type=Path, help="导出的声音包（.voice.zip）")
    args = parser.parse_args()

    if args.command == "voices":
        if args.action == "add":
            if not args.pack or not args.pack.is_file():
                raise SystemExit("用法：mvr voices add 声音包.voice.zip")
            try:
                voice = import_pack(args.pack)
            except (ValueError, KeyError, OSError) as err:
                raise SystemExit(f"没能添加：{err}") from err
            print(f"已添加声音：{voice.name}")
            return
        for voice in library().values():
            print(f"{voice.id:<18}{voice.name}　{voice.gender}　{voice.age}　{voice.desc[:30]}")
        return

    app = App([path.expanduser().resolve() for path in args.voices])
    if not app.voices():
        raise SystemExit("声音库是空的。先用 mvr voices add 添加一个声音包。")
    if args.book:
        if not args.book.is_file():
            raise SystemExit(f"找不到文件：{args.book}")
        try:
            book = Book.create(args.book)
        except ValueError as err:
            raise SystemExit(str(err)) from err
        print(f"《{book.title}》共 {len(book.chapters)} 章")
        app.open(book)
    url = f"http://127.0.0.1:{args.port}/"
    print(f"朗读页面：{url}　（按 Ctrl+C 结束）")
    if not args.no_browser:
        webbrowser.open(url)
    serve(app, args.port)


if __name__ == "__main__":
    main()
