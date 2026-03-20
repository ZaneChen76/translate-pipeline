# TranslatePipeline - 技术文档/标书中译英保真翻译系统

一个面向技术文档/标书的高保真中译英 DOCX 翻译系统。

## 核心能力

- 中文 `.docx` → 英文 `.docx`（保真结构与排版）
- 段落/单元格级翻译，保留标题层级、表格、图片、编号
- 术语库约束 + 翻译记忆（TM）复用
- 自动 QA：结构对齐、数字一致性、术语一致性、漏译检测
- 可替换翻译引擎（默认混元 Lite）

## 快速开始

```bash
# 安装依赖
pip install python-docx openai pyyaml

# 运行翻译
python -m app.main translate \
  --input sample.docx \
  --output sample.en.docx \
  --qa-report sample.qa.md

# 使用术语库
python -m app.main translate \
  --input sample.docx \
  --output sample.en.docx \
  --glossary data/glossary/tdra.yaml

# 指定翻译模型
python -m app.main translate \
  --input sample.docx \
  --output sample.en.docx \
  --translator mock    # 或 hunyuan (默认)

# 生成质检可视化仪表盘（单源多译文对比）
python -m app.main quality-report \
  --source data/inbox/tdra03.docx \
  --targets "data/output/tdra03.en.*.docx" \
  --report data/output/tdra03.quality.dashboard.md \
  --image data/output/tdra03.quality.dashboard.png
```

## 项目结构

```
translate_pipeline/
├─ app/
│  ├─ core/          # 数据模型、任务管理、存储
│  ├─ docx/          # DOCX 解析、抽取、回写
│  ├─ translation/   # 翻译接口、术语库、TM
│  ├─ qa/            # 自动质检
│  ├─ connectors/    # Discord/Telegram 接入（Phase 2）
│  ├─ worker/        # 任务流水线
│  └─ main.py        # CLI 入口
├─ data/
│  ├─ inbox/         # 输入文件
│  ├─ jobs/          # 任务中间产物
│  ├─ output/        # 输出文件
│  ├─ glossary/      # 术语库
│  └─ tm/            # 翻译记忆
├─ tests/
└─ README.md
```

## 翻译引擎

| 引擎 | 参数 | 说明 |
|------|------|------|
| `mock` | `--translator mock` | 测试用，返回原文 |
| `hunyuan` | `--translator hunyuan` | 腾讯混元 Lite（默认） |

环境变量：
- `HUNYUAN_API_KEY` — 腾讯云 API Key（sk-...）

## 术语库格式

```yaml
terms:
  - source: 发送方标识
    target: Sender ID
  - source: 移动网络运营商
    target: Mobile Network Operator
    note: 缩写 MNO
```

## QA 报告

QA 报告包含以下检查：
- **结构对齐**：段落数/表格数是否一致
- **数字一致性**：数值、百分比、日期、金额
- **术语一致性**：同一术语是否统一译法
- **漏译检测**：疑似未翻译段落

## 当前支持范围

### ✅ MVP 已支持
- `.docx` 输入
- 正文段落 + 表格单元格翻译
- 标题样式保留
- 图片/表格结构保留
- 术语库约束
- 翻译记忆 exact match
- QA 四项检查 + Markdown 报告
- CLI 运行

### ⏳ Phase 2
- 页眉页脚
- 脚注/尾注
- 文本框
- Discord/Telegram 接入
- Google Drive 接入
- 批量任务队列
- 人工审校界面

## 实现说明

- 翻译单元 = 段落 或 表格单元格（不按 run 拆分）
- 回写方式：原位替换 `paragraph.text`，尽量保留 run 结构
- 目录不直接修改，输出后在 Word 中 `Ctrl+A, F9` 刷新
- 模型严格约束 prompt：不增不减、术语优先、仅输出译文
