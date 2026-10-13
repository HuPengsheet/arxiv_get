"""Exercise the exported offline page in a real browser when Chrome is available."""
import html
import json
import re
import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path

from arxiv_get.ai import fingerprint
from arxiv_get.__main__ import load_config
from arxiv_get.render import export_html
from arxiv_get.store import Store


@unittest.skipUnless(shutil.which("google-chrome"), "Chrome is unavailable")
class BrowserFilterTests(unittest.TestCase):
    def test_combined_filters_sort_and_reset(self):
        config = load_config(None)
        with tempfile.TemporaryDirectory() as tmp:
            store = Store(str(Path(tmp) / "papers.sqlite3"))
            papers = []
            for identifier, day, authors, categories, primary, score, reason in [
                ("A", "09", ["Alice", "Bob"], ["cs.LG", "cs.AR"], "cs.AR", 90, "摘要复核：优化内核"),
                ("B", "10", ["Bob"], ["cs.LG"], "cs.LG", 60, "标题/分类初筛：模型研究"),
                ("C", "09", ["Carol"], ["math.NA"], "math.NA", 20, "数值分析"),
                ("D", "08", ["Dan"], ["cs.AR"], "cs.AR", None, None),
            ]:
                paper = dict(id=identifier, version_id=identifier, title=identifier,
                             abstract="An abstract", authors=authors, categories=categories,
                             primary_category=primary, published="2026-09-" + day + "T12:00:00Z",
                             updated="2026-09-" + day + "T12:00:00Z",
                             url="https://arxiv.org/abs/2609.00001", pdf_url="https://arxiv.org/pdf/2609.00001")
                papers.append(paper)
                store.save(paper)
                if score is not None:
                    store.save_result(identifier, fingerprint(paper, config["keywords"], config["ai"]),
                                      dict(score=score, reason=reason, model="current-chat",
                                           matched_keywords=["算子优化"] if score >= 70 else []))
            target = Path(tmp) / "index.html"
            export_html(store, papers, config["keywords"], config["ai"], target)
            store.close()
            checks = r"""
<script>
const failures=[];let checked=0;
function expect(name,actual,expected){checked++;if(actual!==expected)failures.push(`${name}: ${actual} != ${expected}`)}
function titles(){return [...document.querySelectorAll('#papers h2 a')].map(a=>a.textContent).join('')}
function set(id,value){el(id).value=value;el(id).dispatchEvent(new Event('input',{bubbles:true}))}
function reset(){el('resetFilters').click()}
function category(c){const input=[...document.querySelectorAll('#categories input')].find(x=>x.value===c);if(!input)throw new Error('Missing category '+c);input.click()}
try{
expect('default related',titles(),'A');
set('status','all');expect('all, pending last',titles(),'ABCD');
set('subject','math');expect('subject',titles(),'C');
reset();set('status','all');category('cs.AR');expect('single category',titles(),'AD');
category('cs.LG');expect('category union',titles(),'ABD');
expect('multi category label',el('categorySummary').textContent,'cs.AR、cs.LG');
reset();set('status','all');category('cs.LG');set('categoryScope','primary');expect('explicit primary, not first category',titles(),'B');
reset();set('status','all');set('subject','cs');set('author','bOB');set('scoreMin','65');expect('combined subject author score',titles(),'A');
set('scoreMax','50');expect('invalid score interval',el('filterError').hidden,false);expect('invalid hides results',titles(),'');
reset();set('status','all');set('dateFrom','2026-09-09');set('dateTo','2026-09-09');expect('inclusive date interval',titles(),'AC');
set('dateFrom','2026-09-10');expect('invalid date interval',el('filterError').hidden,false);
reset();set('status','all');set('date','2026-09-10');expect('exact date',titles(),'B');
reset();set('status','all');set('basis','abstract');expect('abstract basis',titles(),'A');
set('basis','title');expect('title basis',titles(),'B');set('basis','unspecified');expect('unspecified basis',titles(),'C');
set('basis','pending');expect('pending basis',titles(),'D');
reset();set('status','pending');expect('pending status',titles(),'D');set('scoreMin','0');expect('scored interval excludes pending',titles(),'');
reset();set('status','rejected');expect('rejected status',titles(),'BC');
reset();set('status','all');set('keyword','算子优化');expect('matched keyword',titles(),'A');
reset();set('status','all');set('sort','scoreAsc');expect('ascending score, pending last',titles(),'CBAD');
set('sort','dateDesc');expect('newest sort',titles(),'BACD');set('sort','dateAsc');expect('oldest sort',titles(),'DCAB');
set('sort','title');expect('title sort',titles(),'ABCD');
set('search','cs.ar');expect('category searchable',titles(),'AD');
reset();set('status','all');el('papers').querySelector('button.tag').click();expect('tag shortcut',titles(),'AB');
reset();expect('reset status',el('status').value,'selected');expect('reset categories',chosenCategories.size,0);expect('reset results',titles(),'A');
el('categoryPanel').open=true;set('categorySearch','体系结构');expect('category search',document.querySelectorAll('#categories input').length,1);
set('categorySearch','no-such-category');expect('empty category search',el('categoryEmpty').hidden,false);
expect('no horizontal overflow',document.documentElement.scrollWidth<=window.innerWidth,true);
}catch(error){failures.push(error.stack)}
const report=document.createElement('pre');report.id='browser-test-report';report.textContent=JSON.stringify({checked,failures});document.body.append(report);
</script>
"""
            target.write_text(target.read_text().replace("</body>", checks + "</body>"), encoding="utf-8")
            for width in (1365, 390):
                completed = subprocess.run([
                    "google-chrome", "--headless", "--no-sandbox", "--disable-gpu",
                    "--no-proxy-server", "--disable-background-networking",
                    "--user-data-dir=" + str(Path(tmp) / ("chrome-" + str(width))),
                    "--window-size={},900".format(width), "--dump-dom", target.as_uri(),
                ], capture_output=True, text=True, timeout=45)
                self.assertEqual(completed.returncode, 0, completed.stderr[-1500:])
                match = re.search(r'<pre id="browser-test-report">(.*?)</pre>', completed.stdout, re.S)
                self.assertIsNotNone(match, completed.stderr[-1500:])
                report = json.loads(html.unescape(match.group(1)))
                self.assertEqual(report["failures"], [], "Viewport {}: {}".format(width, report))
                self.assertGreaterEqual(report["checked"], 30)
