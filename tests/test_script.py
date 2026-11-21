import json

import pytest

from multivoice_reader.script import chapter_range, compact, dumps, load, normalize


def test_a_line_needs_only_its_text():
    script = normalize({"chapters": [{"lines": [{"text": " 夜色渐深。 "}]}]})
    assert script["title"] == "未命名" and script["chapters"][0]["title"] == "第 1 段"
    assert script["chapters"][0]["lines"] == [
        {"text": "夜色渐深。", "speaker": "旁白", "emotion": "中性", "para": 0}
    ]
    assert script["characters"] == {}


def test_characters_are_those_who_speak_with_what_is_known_of_them():
    script = normalize(
        {
            "title": "书",
            "characters": {"张三": {"gender": "男", "age": "青年", "voice": "x"}, "没出场": {"gender": "女"}},
            "chapters": [
                {
                    "title": "一",
                    "lines": [
                        {"speaker": "张三", "emotion": "愤怒", "text": "走！"},
                        {"speaker": "李四", "emotion": "狂喜", "text": "好。"},
                    ],
                }
            ],
        }
    )
    assert script["characters"] == {
        "张三": {"gender": "男", "age": "青年"},
        "李四": {"gender": "未知", "age": "未知"},
    }
    assert [line["emotion"] for line in script["chapters"][0]["lines"]] == ["愤怒", "中性"]


@pytest.mark.parametrize(
    "bad",
    [
        [],
        {},
        {"chapters": []},
        {"chapters": [{"title": "一"}]},
        {"chapters": [{"lines": [{"speaker": "张三"}]}]},
        {"chapters": [{"lines": [{"text": "  "}]}]},
        {"format": "something-else", "chapters": [{"lines": [{"text": "好"}]}]},
        {"version": 99, "chapters": [{"lines": [{"text": "好"}]}]},
    ],
)
def test_what_is_not_a_script_is_refused(bad):
    with pytest.raises(ValueError):
        normalize(bad)


def test_a_written_script_leaves_out_what_goes_without_saying_and_reads_back_the_same(tmp_path):
    script = normalize(
        {
            "title": "书",
            "chapters": [
                {
                    "title": "一",
                    "lines": [{"text": "他说：", "para": 0}, {"speaker": "张三", "text": "好。", "para": 0}],
                }
            ],
        }
    )
    assert compact(script)["chapters"][0]["lines"] == [
        {"text": "他说："},
        {"speaker": "张三", "para": 0, "text": "好。"},
    ]
    path = tmp_path / "书.json"
    path.write_text(dumps(script), encoding="utf-8")
    assert load(path) == script
    assert json.loads(path.read_text(encoding="utf-8"))["format"] == "multivoice-reader.script"


def test_a_file_that_is_not_json_is_refused(tmp_path):
    path = tmp_path / "x.json"
    path.write_text("第一章\n正文", encoding="utf-8")
    with pytest.raises(ValueError):
        load(path)


@pytest.mark.parametrize(
    ("spec", "chapters"),
    [("5", [4]), ("3-5", [2, 3, 4]), ("9-", [8, 9]), ("-2", [0, 1]), (" 1 - 2 ", [0, 1])],
)
def test_chapter_ranges_count_from_one_and_include_both_ends(spec, chapters):
    assert list(chapter_range(spec, 10)) == chapters


@pytest.mark.parametrize("spec", ["0", "11", "5-3", "a-b", "-", "", "1-2-3"])
def test_chapter_ranges_that_make_no_sense_are_refused(spec):
    with pytest.raises(ValueError):
        chapter_range(spec, 10)
