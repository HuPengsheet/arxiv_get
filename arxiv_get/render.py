import html
import json
import re
from pathlib import Path


def export_html(store, papers, keywords, config, output):
    from .ai import fingerprint
    rows = []
    for paper in papers:
        result = store.result(paper["id"], fingerprint(paper, keywords, config))
        primary = paper.get("primary_category") or next(iter(paper["categories"]), None)
        rows.append(dict(paper, primary_category=primary, screening=result))
    data = json.dumps(rows, ensure_ascii=False).replace("<", "\\u003c").replace(">", "\\u003e").replace("&", "\\u0026")
    template = Path(__file__).with_name("template.html").read_text(encoding="utf-8")
    replacements = {"__KEYWORDS__": html.escape(" · ".join(keywords)),
                    "__THRESHOLD__": str(config.get("threshold", 70)), "__DATA__": data}
    page = re.sub(r"__KEYWORDS__|__THRESHOLD__|__DATA__", lambda m: replacements[m.group()], template)
    path = Path(output)
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(page, encoding="utf-8")
    temporary.replace(path)
    return len(rows)
