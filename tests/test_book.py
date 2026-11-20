from multivoice_reader.book import Book, audio_key


def test_create_and_reopen(tmp_path, monkeypatch):
    monkeypatch.setenv("MVR_HOME", str(tmp_path / "home"))
    source = tmp_path / "我的小说 作者：某人.txt"
    source.write_text("简介\n第1章 开端\n第一段。\n“你好。”\n第2章 后来\n第二段。\n", encoding="utf-8")
    book = Book.create(source)
    assert book.title == "我的小说" and book.chapters == ["第1章 开端", "第2章 后来"]
    assert book.paragraphs(0) == ["第一段。", "“你好。”"]
    assert book.script(0) is None
    book.save_script(0, [{"kind": "narration", "text": "第一段。", "speaker": "旁白", "emotion": "中性"}])
    book.save_cast({"张三": "m_youth"})
    again = Book.all()[0]
    assert (
        again.id == book.id
        and again.script(0)[0]["text"] == "第一段。"
        and again.cast() == {"张三": "m_youth"}
    )


def test_audio_key_changes_with_voice_and_emotion():
    base = audio_key("ming", "v1", "中性", "你好")
    assert base == audio_key("ming", "v1", "中性", "你好")
    assert len({base, audio_key("ming", "v2", "中性", "你好"), audio_key("ming", "v1", "愤怒", "你好")}) == 3
