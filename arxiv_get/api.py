import re
import xml.etree.ElementTree as ET
from datetime import date, timedelta
from urllib.parse import urlencode
from urllib.request import Request

from .http import request_bytes

NS = {"a": "http://www.w3.org/2005/Atom", "o": "http://a9.com/-/spec/opensearch/1.1/",
      "arxiv": "http://arxiv.org/schemas/atom"}


def build_query(day, categories):
    query = "submittedDate:[{0}0000 TO {0}2359]".format(day.strftime("%Y%m%d"))
    if categories:
        if any(not re.fullmatch(r"[A-Za-z][A-Za-z0-9.-]*", c) for c in categories):
            raise ValueError("arXiv 分类格式不正确")
        query += " AND (" + " OR ".join("cat:" + c for c in categories) + ")"
    return query


def parse_feed(raw):
    try:
        root = ET.fromstring(raw)
        if root.tag != "{" + NS["a"] + "}feed":
            raise ValueError("arXiv 响应不是 Atom feed")
        papers = []
        for entry in root.findall("a:entry", NS):
            def field(name):
                return " ".join((entry.findtext("a:" + name, "", NS)).split())
            identifier = field("id")
            if "/api/errors" in identifier:
                raise ValueError("arXiv API 错误：" + field("summary"))
            if "/abs/" not in identifier:
                raise ValueError("arXiv 返回无效论文 ID")
            version_id = identifier.split("/abs/", 1)[1]
            base_id = re.sub(r"v\d+$", "", version_id)
            if not re.fullmatch(r"(?:\d{4}\.\d{4,5}|[A-Za-z0-9.-]+/\d{7})(?:v\d+)?", version_id):
                raise ValueError("arXiv 返回无效论文 ID")
            published, updated = field("published"), field("updated")
            date.fromisoformat(published[:10])
            date.fromisoformat(updated[:10])
            categories = [c.attrib["term"] for c in entry.findall("a:category", NS)]
            primary = entry.find("arxiv:primary_category", NS)
            papers.append({
                "id": base_id, "version_id": version_id, "title": field("title"),
                "abstract": field("summary"), "published": published, "updated": updated,
                "authors": [" ".join((a.findtext("a:name", "", NS)).split()) for a in entry.findall("a:author", NS)],
                "categories": categories,
                "primary_category": primary.attrib["term"] if primary is not None else (categories[0] if categories else None),
                "url": "https://arxiv.org/abs/" + version_id,
                "pdf_url": "https://arxiv.org/pdf/" + version_id,
            })
        total = int(root.findtext("o:totalResults", "", NS))
        return total, papers
    except (ET.ParseError, KeyError) as exc:
        raise ValueError("无法解析 arXiv Atom 响应") from exc


def fetch_papers(start_date, end_date, categories=(), page_size=100):
    if not 1 <= page_size <= 2000:
        raise ValueError("page_size 必须在 1–2000 之间")
    if start_date > end_date:
        raise ValueError("起始日期不能晚于结束日期")
    day = start_date
    while day <= end_date:
        offset, seen = 0, set()
        while True:
            params = {"search_query": build_query(day, categories), "start": offset,
                      "max_results": page_size, "sortBy": "submittedDate", "sortOrder": "ascending"}
            req = Request("https://export.arxiv.org/api/query?" + urlencode(params),
                          headers={"User-Agent": "arxiv-get/0.1 (local research tool)"})
            total, papers = parse_feed(request_bytes(req, interval=3))
            if total > 30000:
                raise RuntimeError("单日结果超过 API 上限，请缩小分类范围")
            if not papers and offset < total:
                raise RuntimeError("arXiv 分页提前返回空结果，已保存数据可继续抓取")
            if papers and all(p["version_id"] in seen for p in papers):
                raise RuntimeError("arXiv 返回重复分页，请稍后重新抓取")
            for paper in papers:
                if paper["version_id"] not in seen and paper["published"][:10] == day.isoformat():
                    yield paper
                seen.add(paper["version_id"])
            offset += len(papers)
            if offset >= total:
                break
        day += timedelta(days=1)
