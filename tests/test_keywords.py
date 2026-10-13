import json
import tempfile
import unittest
from pathlib import Path

from arxiv_get.__main__ import load_config
from arxiv_get.ai import fingerprint
from arxiv_get.keywords import read_keyword_table


class KeywordTableTests(unittest.TestCase):
    def test_enabled_rows_and_cache_stability(self):
        with tempfile.TemporaryDirectory() as tmp:
            config = Path(tmp) / "config.json"
            config.write_text(json.dumps({"keywords_file": "interests.csv"}))
            table = Path(tmp) / "interests.csv"
            table.write_text("keyword,enabled,note\n算子优化,1,备注\n算子融合,0,暂不启用\n", encoding="utf-8-sig")
            before = load_config(config)
            self.assertEqual(before["keywords"], ["算子优化"])
            self.assertFalse(before["keyword_table"][1]["enabled"])
            table.write_text("keyword,enabled,note\n算子优化,1,修改备注\n访存优化,0,修改停用关键词\n")
            after = load_config(config)
            self.assertEqual(fingerprint({}, before["keywords"], before["ai"]),
                             fingerprint({}, after["keywords"], after["ai"]))
            table.write_text("keyword,enabled,note\n算子优化,1,备注\n算子融合,1,新启用\n")
            enabled = load_config(config)
            self.assertEqual(enabled["keywords"], ["算子优化", "算子融合"])
            self.assertNotEqual(fingerprint({}, before["keywords"], before["ai"]),
                                fingerprint({}, enabled["keywords"], enabled["ai"]))

    def test_overrides_do_not_require_table(self):
        with tempfile.TemporaryDirectory() as tmp:
            config = Path(tmp) / "config.json"
            config.write_text(json.dumps({"keywords_file": "missing.csv", "keywords": ["用户方向"]}))
            self.assertEqual(load_config(config)["keywords"], ["用户方向"])
            self.assertEqual(load_config(config, ["临时方向"])["keywords"], ["临时方向"])
            config.write_text(json.dumps({"keywords_file": "missing.csv"}))
            self.assertEqual(load_config(config, ["临时方向"])["keywords"], ["临时方向"])

    def test_reject_invalid_table(self):
        with tempfile.TemporaryDirectory() as tmp:
            table = Path(tmp) / "keywords.csv"
            for content in ["term,enabled\n算子优化,1\n", "keyword,enabled\n,1\n",
                            "keyword,enabled\n算子优化,true\n", "keyword,enabled\n算子优化,1\n算子优化,0\n"]:
                table.write_text(content)
                with self.assertRaises(ValueError):
                    read_keyword_table(table)
