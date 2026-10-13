import argparse
import json
import sys
from datetime import date, datetime, timezone
from pathlib import Path

from .ai import PROMPT, Screener, fingerprint, validate_result
from .api import fetch_papers
from .keywords import read_keyword_table
from .render import export_html
from .store import Store


def load_config(path, keyword_override=None):
    project = Path(__file__).parent.parent
    defaults = json.loads(project.joinpath("config.example.json").read_text(encoding="utf-8"))
    extra = {}
    if path:
        extra = json.loads(Path(path).read_text(encoding="utf-8"))
        defaults["ai"].update(extra.pop("ai", {}))
        defaults.update(extra)
    # CLI and legacy inline keywords take precedence over the managed table.
    if keyword_override is not None:
        defaults["keywords"] = keyword_override
    if keyword_override is not None or "keywords" in extra:
        defaults["keyword_table"] = [
            {"keyword": keyword, "enabled": True, "note": "本次直接指定的筛选关键词"}
            for keyword in defaults["keywords"]
        ] if isinstance(defaults["keywords"], list) else []
    else:
        base = Path(path).resolve().parent if path and "keywords_file" in extra else project
        table = read_keyword_table(base / defaults["keywords_file"])
        defaults["keyword_table"] = table
        defaults["keywords"] = [row["keyword"] for row in table if row["enabled"]]
    return defaults


def prepare(store, papers, config, path):
    keywords, ai = config["keywords"], config["ai"]
    tasks = []
    for p in papers:
        key = fingerprint(p, keywords, ai)
        if not store.result(p["id"], key):
            tasks.append({"id": p["id"], "fingerprint": key, "title": p["title"],
                          "abstract": p["abstract"], "categories": p["categories"]})
    target = Path(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(json.dumps({"instructions": PROMPT, "keywords": keywords, "papers": tasks,
        "result_format": {"results": [{"id": "论文ID", "fingerprint": "原样复制待筛选指纹",
        "score": 0, "reason": "中文理由", "matched_keywords": []}]}}, ensure_ascii=False, indent=2), encoding="utf-8")
    print("待当前会话筛选：{} 篇，任务文件：{}".format(len(tasks), path))


def import_results(store, papers, config, path):
    if config["ai"].get("mode") != "chat":
        raise ValueError("当前会话结果导入需要 ai.mode=chat")
    available = {p["id"]: p for p in papers}
    raw = json.loads(Path(path).read_text(encoding="utf-8"))
    if not isinstance(raw, dict) or not isinstance(raw.get("results"), list):
        raise ValueError("导入文件应包含 results 数组")
    validated, seen = [], set()
    for r in raw["results"]:
        if not isinstance(r, dict) or r.get("id") not in available or r["id"] in seen:
            raise ValueError("导入结果有重复或未知论文 ID")
        p = available[r["id"]]
        key = fingerprint(p, config["keywords"], config["ai"])
        if r.get("fingerprint") != key:
            raise ValueError("论文或研究关键词已变更，请重新导出待筛选任务")
        result = validate_result(r, config["keywords"])
        result.update({"model": config["ai"]["model"], "screened_at": datetime.now(timezone.utc).isoformat()})
        validated.append((p["id"], key, result))
        seen.add(p["id"])
    # Validate the whole batch before committing any imported result.
    with store.db:
        for pid, key, result in validated:
            store.db.execute("INSERT OR REPLACE INTO screenings VALUES (?, ?, ?)",
                             (pid, key, json.dumps(result, ensure_ascii=False)))
    print("已导入 {} 篇筛选结果".format(len(validated)))


def main(argv=None):
    parser = argparse.ArgumentParser(description="arXiv 日期抓取 → AI 语义筛选 → SQLite → HTML")
    parser.add_argument("command", choices=["run", "fetch", "screen", "prepare", "import-results", "export", "keywords"])
    parser.add_argument("--config", default="config.json" if Path("config.json").exists() else None)
    parser.add_argument("--date", type=date.fromisoformat, help="首次提交日期（UTC）")
    parser.add_argument("--start", type=date.fromisoformat)
    parser.add_argument("--end", type=date.fromisoformat)
    parser.add_argument("--keyword", action="append", help="可重复指定，替换配置中的关键词")
    parser.add_argument("--category", action="append", help="可重复指定，替换配置中的分类")
    parser.add_argument("--file", default="output/pending.json", help="待筛选任务或导入结果文件")
    parser.add_argument("--force", action="store_true", help="重新调用 API 筛选已缓存结果")
    args = parser.parse_args(argv)
    store = None
    try:
        cfg = load_config(args.config, keyword_override=args.keyword)
        if args.category is not None:
            cfg["categories"] = args.category
        for field in ("keywords", "categories"):
            if not isinstance(cfg[field], list) or any(not isinstance(v, str) or not v.strip() for v in cfg[field]):
                raise ValueError(field + " 必须是非空字符串组成的数组")
        if args.command == "keywords":
            print("筛选关键词\t启用\t备注")
            for row in cfg["keyword_table"]:
                print("{}\t{}\t{}".format(row["keyword"], "是" if row["enabled"] else "否", row["note"]))
            return 0
        if not cfg["keywords"]:
            raise ValueError("请设置研究关键词")
        if type(cfg["ai"].get("threshold")) is not int or not 0 <= cfg["ai"]["threshold"] <= 100:
            raise ValueError("ai.threshold 必须是 0–100 的整数")
        if cfg["ai"].get("mode") not in ("chat", "api"):
            raise ValueError("ai.mode 必须是 chat 或 api")
        if args.date and (args.start or args.end):
            raise ValueError("--date 与 --start/--end 不能同时使用")
        start, end = (args.date, args.date) if args.date else (args.start, args.end)
        if bool(start) != bool(end) or (start and start > end):
            raise ValueError("请提供有效的起止日期")
        if args.command in ("run", "fetch") and not start:
            raise ValueError("抓取需要 --date 或 --start/--end")
        store = Store(cfg["database"])
        if args.command in ("run", "fetch"):
            count = 0
            for paper in fetch_papers(start, end, cfg["categories"], cfg["page_size"]):
                store.save(paper)
                count += 1
                if count % 100 == 0:
                    print("已保存 {} 篇".format(count), flush=True)
            print("本次抓取并保存 {} 篇（按论文 ID 去重）".format(count))
        papers = store.papers(start.isoformat() if start else None, end.isoformat() if end else None, cfg["categories"])
        if args.command == "prepare" or (args.command in ("run", "screen") and cfg["ai"]["mode"] == "chat"):
            prepare(store, papers, cfg, args.file)
        elif args.command in ("run", "screen"):
            screener = None
            for p in papers:
                key = fingerprint(p, cfg["keywords"], cfg["ai"])
                if not args.force and store.result(p["id"], key):
                    continue
                if screener is None:
                    screener = Screener(cfg["ai"], cfg["keywords"])
                result = screener.screen(p)
                store.save_result(p["id"], key, result)
                print("{}：{} 分".format(p["id"], result["score"]), flush=True)
        elif args.command == "import-results":
            import_results(store, papers, cfg, args.file)
        export_html(store, papers, cfg["keywords"], cfg["ai"], cfg["output"])
        print("HTML：{}（{} 篇）".format(cfg["output"], len(papers)))
        return 0
    except (ValueError, RuntimeError, OSError, KeyError, TypeError) as exc:
        print("错误：{}".format(exc), file=sys.stderr)
        return 1
    finally:
        if store is not None:
            store.close()


if __name__ == "__main__":
    sys.exit(main())
