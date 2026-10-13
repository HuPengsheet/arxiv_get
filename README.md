# arXiv 论文抓取与 AI 筛选

按首次提交的 **UTC 日期**抓取论文，用研究关键词进行 AI 语义筛选，保存到 SQLite，生成可以直接打开的 HTML。Python 3.9+，只用标准库，无需安装第三方依赖。

## 快速开始：当前聊天模型筛选

默认研究关键词为 `算子优化`，默认不限分类。可先复制配置再修改：

```bash
cp config.example.json config.json
python3 -m arxiv_get run --date 2026-10-11
```

生成 `output/pending.json`，包含研究关键词、标题、摘要、学科分类、筛选提示和结果格式。把此文件交给当前聊天中的助手筛选，助手可以读取工作区文件并写出 `output/results.json`。然后导入：

```bash
python3 -m arxiv_get import-results --date 2026-10-11 --file output/results.json
```

打开 `output/index.html`。页面支持全文搜索、作者、学科大类、具体分类多选、主分类/交叉分类、提交日期及日期区间、筛选状态、阈值、评分区间、筛选依据、关联研究关键词和排序。具体分类取并集，再与其他条件取交集；点击论文的分类标签可快速筛选，支持一键重置。分类选项数字为库存数量，不受搜索和评分条件影响。页面展示评分、中文理由、作者、学科分类、摘要、原文与 PDF 链接。历史数据未记录主分类时按首个分类处理。默认展示评分 ≥70 的论文；尚未筛选时可切换“全部论文”或“待筛选”。网页离线可用，打开原文链接需要网络。

**聊天模式不会从 Python 自动调用当前聊天模型。** `run` 会抓取、存储、导出待筛选任务和 HTML；在会话完成筛选并导入后，页面才显示真实评分。无人值守运行需要下面的 API 模式。

## 维护自己的筛选关键词表

你的研究关键词单独放在 [keywords.csv](keywords.csv)，用于告诉 AI 你关注哪些方向。每行是一个由你提供的筛选关键词，不从论文中自动提取。

| 列 | 含义 |
| --- | --- |
| `keyword` | 你提供的研究关键词或方向描述 |
| `enabled` | `1` 启用、`0` 停用 |
| `note` | 管理备注，可留空，不参与模型筛选 |

当前表中只有 `算子优化`，处于启用状态。以后直接新增一行即可，例如你确定要增加“算子融合”时：

```csv
keyword,enabled,note
算子优化,1,当前研究方向
算子融合,1,新增研究方向
```

CSV 使用 UTF-8 编码，可用文本编辑器或 Excel/WPS 编辑；关键词和备注包含逗号时需要用双引号包住。`enabled` 支持暂时停用关键词，重复或空关键词会报错。

```bash
# 查看自己的关键词表（包含停用行）
python3 -m arxiv_get keywords

# 用表中启用的关键词重新准备本地论文筛选
python3 -m arxiv_get screen --date 2026-09-09
```

配置的 `keywords_file` 相对配置文件所在目录解析；默认文件为项目根目录的 `keywords.csv`。优先级为 `--keyword` > 配置中旧格式的 `keywords` 数组 > `keywords_file` 表。采用关键词表时请不要同时保留旧的 `keywords` 字段。

新增、删除、停用或修改启用关键词后，需要重新筛选才能得到新方向的评分；仅导出 HTML 不会调用模型。只改备注或停用行不会影响已有评分缓存。

## API 模式：自动筛选

在 `config.json` 中将 `ai.mode` 改为 `api`，将 `ai.model` 设为你的模型 ID，`ai.base_url` 设为支持 Chat Completions 的接口基础地址（含 `/v1`，如服务商需要）。密钥从 `ai.api_key_env` 指定的环境变量读取，不写进配置文件。

```bash
read -rs -p 'API Key: ' ARXIV_AI_API_KEY
export ARXIV_AI_API_KEY
python3 -m arxiv_get run --date 2026-10-11
```

默认请求 `response_format: {"type": "json_object"}`。不支持 JSON mode 的兼容接口可将 `ai.response_format` 改为 `none`，但仍须返回纯 JSON 对象。截断、拒绝、错误格式和无效评分会报错，不会作为不相关结果保存；再次运行可复用之前成功保存的结果。自动 API 筛选会把论文标题、摘要、分类和研究关键词发送给配置的服务商。

## 日期、关键词与本地复用

```bash
# 获取一个日期区间；多个分类取并集，用于限定抓取范围
python3 -m arxiv_get run --start 2026-10-01 --end 2026-10-11 --category cs.LG --category cs.PL

# 仅抓取和生成 HTML
python3 -m arxiv_get fetch --date 2026-10-11

# 更换研究方向，使用已存储论文，不重新抓取
python3 -m arxiv_get screen --keyword 'GPU kernel optimization' --keyword '算子融合'

# 导出当前方向尚未完成的会话筛选任务
python3 -m arxiv_get prepare --date 2026-10-11

# 导出所有已存储日期；不会调用模型
python3 -m arxiv_get export
```

`--keyword`、`--category` 可重复指定，覆盖本次运行的配置。后续导入/导出需要使用相同关键词和配置，建议将长期研究方向写入 `keywords.csv`。不带日期的本地操作处理全部已存储日期；带日期则仅处理该区间。`--force` 在 API 模式中强制重新筛选。

保存全部抓取候选，而不是只保存相关论文，因此可以离线改关键词后重新筛选。论文以不含版本号的 arXiv ID 去重，防止旧版本覆盖新版本；筛选缓存包含论文内容、关键词、模型、接口、模式和提示版本。同一缓存可调整分数阈值而无需重新调用模型。抓取中断时已经保存的论文保留，但再次抓取会从日期区间起点重跑，依靠去重合并。

日期指首次提交日期，不是公告日期或更新日期。近期论文可能尚未被 arXiv 索引，可稍后重跑。API 一般没有独立的作者关键词字段；用户研究关键词由 AI 与标题、摘要和学科分类综合关联。只保存元数据与 PDF 链接，不下载 PDF。

## 配置与验证

配置示例见 `config.example.json`。`categories: []` 表示全分类；模型名称必须与接口支持的 ID 一致。未筛选论文在 HTML 中单独显示，不会得到虚构评分。

```bash
python3 -m unittest discover -s tests -v
python3 -m arxiv_get --help
```

文档依据：[arXiv API 用户手册](https://info.arxiv.org/help/api/user-manual.html)、[OpenAI JSON 输出文档](https://developers.openai.com/api/docs/guides/structured-outputs?api-mode=chat)。arXiv 请求串行执行，至少间隔 3 秒；每个 UTC 日分页抓取，单日超过 30,000 条时要求缩小分类范围。HTTP 临时失败重试 3 次。
