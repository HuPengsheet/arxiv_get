"""The user's screening interests, managed separately from paper metadata."""
import csv
from pathlib import Path


def read_keyword_table(path):
    rows, seen = [], set()
    with Path(path).open(encoding="utf-8-sig", newline="") as source:
        reader = csv.DictReader(source)
        if not reader.fieldnames or not {"keyword", "enabled"}.issubset(reader.fieldnames):
            raise ValueError("关键词表需要 keyword 和 enabled 列，可选 note 备注列")
        for line, row in enumerate(reader, start=2):
            keyword = (row.get("keyword") or "").strip()
            enabled = (row.get("enabled") or "").strip()
            if not keyword:
                raise ValueError("关键词表第 {} 行：keyword 不能为空".format(line))
            if enabled not in ("0", "1"):
                raise ValueError("关键词表第 {} 行：enabled 必须是 1（启用）或 0（停用）".format(line))
            if keyword in seen:
                raise ValueError("关键词表包含重复关键词：" + keyword)
            seen.add(keyword)
            rows.append({"keyword": keyword, "enabled": enabled == "1",
                         "note": (row.get("note") or "").strip()})
    return rows
