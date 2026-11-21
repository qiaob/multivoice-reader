import pytest

from multivoice_reader.book import Book


@pytest.fixture
def book(tmp_path, monkeypatch):
    monkeypatch.setenv("MVR_HOME", str(tmp_path / "home"))
    source = tmp_path / "我的小说 作者：某人.txt"
    source.write_text("简介\n第1章 开端\n第一段。\n“你好。”\n第2章 后来\n第二段。\n", encoding="utf-8")
    return Book.create(source)


def test_create_and_reopen(book):
    assert book.title == "我的小说" and book.chapters == ["第1章 开端", "第2章 后来"]
    assert book.paragraphs(0) == ["第一段。", "“你好。”"]
    assert book.lines(0) is None and book.done() == [False, False]
    book.save_lines(
        0, [{"kind": "narration", "text": "第一段。", "para": 0, "speaker": "旁白", "emotion": "中性"}]
    )
    again = Book.all()[0]
    assert again.id == book.id and again.lines(0)[0]["text"] == "第一段。" and again.done() == [True, False]


def test_the_script_holds_what_has_been_split_and_nothing_about_voices(book):
    with pytest.raises(ValueError):
        book.script()
    book.save_lines(
        1,
        [
            {"kind": "narration", "text": "第二段。", "para": 0, "speaker": "旁白", "emotion": "中性"},
            {"kind": "dialogue", "text": "走吧。", "para": 0, "speaker": "张三", "emotion": "愤怒"},
        ],
    )
    book.save_characters({"张三": {"gender": "男", "age": "青年", "lines": 1, "voice": "m_youth"}})
    script = book.script()
    assert [c["title"] for c in script["chapters"]] == ["第2章 后来"]
    assert script["characters"] == {"张三": {"gender": "男", "age": "青年"}}
    assert script["chapters"][0]["lines"][1] == {
        "text": "走吧。",
        "speaker": "张三",
        "emotion": "愤怒",
        "para": 0,
    }


def test_how_far_to_split_is_remembered(book):
    assert book.until() == 0
    book.save_until(2)
    assert Book(book.dir).until() == 2


def test_the_model_asked_for_is_kept_when_splitting_is_stopped(book):
    assert book.model() == ""
    book.save_until(2, "qwen3-1.7b")
    book.save_until(0)
    assert Book(book.dir).model() == "qwen3-1.7b" and Book(book.dir).until() == 0
