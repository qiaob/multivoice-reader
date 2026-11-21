import json

from multivoice_reader.analyze import ADAPTERS, DEFAULT_MODEL, MODELS, _profile_in


def test_every_fine_tuned_model_has_its_weights_and_they_name_its_base():
    assert DEFAULT_MODEL in MODELS
    for about in MODELS.values():
        if about["adapter"]:
            folder = ADAPTERS / about["adapter"]
            assert (folder / "adapters.safetensors").is_file()
            assert json.loads((folder / "adapter_config.json").read_text())["model"] == about["base"]


def test_a_profile_is_found_in_one_object_or_in_one_per_line():
    whole = '好的：\n{"张三": {"gender": "男", "age": "青年"}, "李四": {"gender": "女", "age": "老年"}}'
    per_line = '{"张三": {"gender": "男", "age": "青年"}}\n{"李四": {"gender": "女", "age": "老年"}}'
    for answer in (whole, per_line):
        assert _profile_in(answer, "李四") == {"gender": "女", "age": "老年"}
    assert _profile_in(whole, "王五") == {} and _profile_in('{"张三": {"gender": 男}}', "张三") == {}
