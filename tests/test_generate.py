from multivoice_reader.generate import file_name


def test_file_names_keep_the_title_but_nothing_a_file_name_cannot_hold():
    assert file_name(7, "第七章 夜/雨: 归人?") == "007 第七章 夜 雨 归人.mp3"
    assert file_name(12, "///") == "012.mp3"
    assert len(file_name(1, "长" * 200)) <= 68
