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


def test_straight_quotes_and_double_corner_brackets_are_dialogue():
    segs = split_segments(['他抬头："你怎么还在这儿？"她没有回答。', "『走吧。』"])
    assert [(s.kind, s.text) for s in segs] == [
        ("narration", "他抬头："),
        ("dialogue", "你怎么还在这儿？"),
        ("narration", "她没有回答。"),
        ("dialogue", "走吧。"),
    ]


def test_heading_with_colon_and_no_space():
    chapters = split_chapters("第1章：迁徙\n第一段。\n第二章、归来\n第二段。\n")
    assert [c.title for c in chapters] == ["第1章：迁徙", "第二章、归来"]


def test_repeated_watermark_lines_are_dropped():
    body = "\n".join(f"第{i}章 标题\n本站推荐各位书友阅读这本书\n这是第{i}章的正文。" for i in range(1, 15))
    chapters = split_chapters(body)
    assert len(chapters) == 14 and all(len(c.paragraphs) == 1 for c in chapters)


def test_story_before_the_first_recognised_heading_is_kept():
    early = "\n".join(f"这是没有被认出标题的前几章里的第{i}段正文，讲了很多事情。" for i in range(400))
    chapters = split_chapters(early + "\n第181章 后来\n最后一段。\n")
    assert chapters[0].title == "开头 第 1 段" and chapters[-1].title == "第181章 后来"
    assert sum(len(c.paragraphs) for c in chapters) == 401


def test_a_paragraph_wholly_in_brackets_is_the_system_speaking():
    segments = split_segments(
        ["【叮！获得能力：仙师天眼】", "张云一愣。", "【新书启航，求收藏求推荐】", "他说【系统】真好用。"]
    )
    assert [(s.kind, s.para) for s in segments] == [
        ("system", 0),
        ("narration", 1),
        ("narration", 2),
        ("narration", 3),
    ]
    assert segments[0].text == "【叮！获得能力：仙师天眼】"
