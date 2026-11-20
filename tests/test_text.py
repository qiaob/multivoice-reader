from multivoice_reader.text import split_chapters, split_segments


def test_chapters_with_volume_prefix_and_blurb():
    text = "书名\n简介一行\n\n卷一 第1章 开端\n  第一段。\n第二段。\n第2章 这家伙是谁？\n第三段。\n"
    chapters = split_chapters(text)
    assert [c.title for c in chapters] == ["卷一 第1章 开端", "第2章 这家伙是谁？"]
    assert chapters[0].paragraphs == ["第一段。", "第二段。"]


def test_heading_is_not_matched_inside_prose():
    chapters = split_chapters(
        "第一章 起\n他翻到第3章，忽然想起了很多年前的那个下午，于是放下书走到窗边看了很久很久的雨。\n"
    )
    assert len(chapters) == 1 and len(chapters[0].paragraphs) == 1


def test_text_without_headings_is_cut_by_size():
    chapters = split_chapters("\n".join(["这是一段没有章节标题的文字。" * 20] * 30))
    assert len(chapters) > 1 and chapters[0].title == "第 1 段"


def test_dialogue_and_narration_keep_order():
    segs = split_segments(["张三推门进来，冷冷地说：“你怎么还在这儿？”李四没有抬头。"])
    assert [(s.kind, s.text) for s in segs] == [
        ("narration", "张三推门进来，冷冷地说："),
        ("dialogue", "你怎么还在这儿？"),
        ("narration", "李四没有抬头。"),
    ]


def test_quoted_term_stays_in_narration():
    segs = split_segments(["他得到了一种叫“返还体”的体质。"])
    assert [(s.kind, s.text) for s in segs] == [("narration", "他得到了一种叫“返还体”的体质。")]


def test_corner_quotes_and_long_narration_is_chunked():
    segs = split_segments(["「走吧。」" + "风从山口吹来，带着雪的味道。" * 10])
    assert segs[0].kind == "dialogue" and segs[0].text == "走吧。"
    assert all(len(s.text) <= 70 for s in segs[1:]) and len(segs) > 2


def test_numbers_are_spelled_out():
    from multivoice_reader.text import speakable

    assert speakable("第1章") == "第一章"
    assert speakable("第12章 第105章 第3253章") == "第十二章 第一百零五章 第三千二百五十三章"
    assert speakable("涨了3.5%，共20000人，1010次") == "涨了百分之三点五，共二万人，一千零一十次"
    assert speakable("2024年的10个徒弟") == "二零二四年的十个徒弟"
    assert speakable("一共100000001块") == "一共一亿零一块"
