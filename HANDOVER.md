# 交接文档：translate-pipeline 项目

**移交方**：SystemArchitect  
**接收方**：codingMaster  
**日期**：2026-03-15  
**仓库**：https://github.com/ZaneChen76/translate-pipeline

---

## 一、项目概述

### 目标
为技术文档/标书构建**保格式**中译英 DOCX 翻译流水线。

### 核心特性（已实现）
- DOCX 格式保留：段落、表格、样式、图片结构不丢失
- Hunyuan Lite API 翻译（OpenAI 兼容接口）
- 术语库注入（YAML 格式）+ 翻译记忆（TM，exact match）
- QA 质检：结构/数字/术语/漏译/CJK 残留检测
- Google Drive 集成：`in/` 取件 → 翻译 → `out/` 上传
- 统一状态跟踪：`in/status.json` 单文件管理
- 断点续传：每 5 单元 checkpoint，SIGTERM 安全
- 出错重试：指数退避（2s→4s→8s，上限 30s，3 次）
- 双输出：JSON（机器可读）+ 摘要（人类可读）

### 当前状态
- **已完成**：全栈实现 + 实测验证（3 个文档）
- **已推送**：GitHub 仓库已创建并推送
- **待优化**：图片保留、fuzzy TM、长任务超时处理

---

## 二、项目结构

```
translate-pipeline/
├── PROJECT_SUMMARY.md          # 完整技术文档（必读）
├── README.md                   # 项目概述
├── .gitignore                  # 排除数据/API keys
├── drive_translate.py          # CLI 入口（Drive 集成）
├── app/
│   ├── __init__.py
│   ├── config.py               # ❌ 已废弃（实际用 core/config.py）
│   ├── connectors/
│   │   └── drive.py            # Google Drive connector (gog CLI)
│   ├── core/
│   │   ├── __init__.py         # 数据模型 (Task/TranslationUnit/QaIssue)
│   │   └── config.py           # 配置管理（Config dataclass）
│   ├── docx/
│   │   ├── extractor.py        # DOCX → TranslationUnit (保留结构映射)
│   │   └── writer.py           # TranslationUnit → DOCX (原位替换)
│   ├── translation/
│   │   ├── translator.py       # 抽象接口 + Mock + HunyuanLite
│   │   ├── glossary.py         # 术语库加载 + prompt 注入
│   │   └── tm.py               # 翻译记忆 (exact match + 持久化)
│   ├── qa/
│   │   ├── checks.py           # QA 检查器（5 个）
│   │   └── report.py           # Markdown QA 报告生成
│   └── worker/
│       └── pipeline.py         # 管道编排（核心文件）
├── data/
│   ├── inbox/                  # 源 DOCX (本地缓存)
│   ├── output/                 # 翻译输出 + QA 报告
│   ├── jobs/                   # checkpoint 文件
│   ├── tm/                     # 翻译记忆 (default_tm.json)
│   └── glossary/               # 术语库 (YAML)
└── tests/                      # 单元测试（空）
```

---

## 三、核心模块详解

### 1. 数据模型 (`app/core/__init__.py`)

```python
class Task:
    """顶层容器，包含元数据、统计、问题列表和翻译单元"""
    task_id: str
    source_file_name: str
    source_file_path: str
    units: List[TranslationUnit]
    issues: List[QaIssue]
    stats: dict  # translated, tm_hits, errors, elapsed_seconds 等
    output_file_path: str
    qa_report_path: str
    error: str

class TranslationUnit:
    """单个翻译单元（段落或表格单元格）"""
    unit_id: str           # "para_0", "table_2_cell_1_3"
    part: str              # "paragraph" 或 "table"
    path: str              # 结构路径：para[5], table[2][1][3]
    source_text: str       # 源中文
    translated_text: str   # 译英文
    style_name: str        # 原始样式名
    tm_hit: bool           # 是否命中 TM
    term_hits: list        # 命中的术语
    error: str             # 翻译错误信息

class QaIssue:
    """QA 问题"""
    category: str          # structure/number/term/missing/cjk_residue
    severity: str          # error/warning
    message: str           # 问题描述
    unit_id: str           # 关联单元
```

### 2. 配置 (`app/core/config.py`)

```python
@dataclass
class Config:
    # 路径
    data_dir: Path = "data/"
    glossary_dir: Optional[Path] = None  # 默认 data/glossary
    tm_dir: Optional[Path] = None        # 默认 data/tm
    output_dir: Optional[Path] = None    # 默认 data/output
    jobs_dir: Optional[Path] = None      # 默认 data/jobs

    # 翻译
    translator: str = "hunyuan"          # "mock" 或 "hunyuan"
    hunyuan_api_key: str = ""            # 从环境变量 HUNYUAN_API_KEY 读取
    hunyuan_base_url: str = "https://api.hunyuan.cloud.tencent.com/v1"
    hunyuan_model: str = "hunyuan-lite"
    temperature: float = 0.3
    top_p: float = 0.9
    translation_timeout: int = 120       # 单次 API 调用超时（秒）

    # QA
    qa_enabled: bool = True
```

**环境变量**：
- `HUNYUAN_API_KEY`：腾讯混元 API 密钥
- `GDRIVE_IN_FOLDER`：Drive `in/` 文件夹 ID（默认 `1aXjL-HvfOkrSn7ABcK-0M62ifZA2Ap3r`）
- `GDRIVE_OUT_FOLDER`：Drive `out/` 文件夹 ID（默认 `1VKAot0kBw7jTWQbUWvKSBSrBqnfkLUtL`）

### 3. Drive Connector (`app/connectors/drive.py`)

使用 `gog` CLI 工具操作 Google Drive（非 API SDK）。

**核心方法**：
```python
class DriveConnector:
    def list_inbox(self) -> List[DriveFile]
    def download(self, drive_file: DriveFile) -> Optional[str]
    def upload_to_out(self, local_path: str, name: str = "") -> Optional[DriveFile]
    def get_next_untranslated(self) -> Optional[tuple[DriveFile, str]]
    
    # 状态跟踪
    def load_status(self) -> dict                    # 从 in/status.json 加载
    def save_status(self, status: dict) -> bool      # 保存到 in/status.json
    def mark_processed(self, filename: str, record: dict) -> bool
    def is_processed(self, filename: str) -> bool
```

**状态文件格式** (`in/status.json`)：
```json
{
  "tdra05.docx": {
    "status": "success",
    "output": "tdra05.en.docx",
    "drive_link": "https://docs.google.com/...",
    "units": 604,
    "errors": 82,
    "warnings": 23,
    "cjk_residue": 26,
    "tm_hits": 112,
    "elapsed_seconds": 135.5,
    "translated_at": "2026-03-15T17:44:14+0800"
  }
}
```

### 4. 翻译层 (`app/translation/translator.py`)

**接口**：
```python
class Translator(ABC):
    @abstractmethod
    def translate(self, unit: TranslationUnit, glossary: Optional[dict] = None) -> str
    @abstractmethod
    def name(self) -> str
```

**实现**：
- `MockTranslator`：测试用，返回 `[EN] {source}`
- `HunyuanLiteTranslator`：腾讯混元 Lite，OpenAI 兼容 API

**关键代码**：
```python
# HunyuanLiteTranslator 初始化
self.client = OpenAI(
    api_key=config.hunyuan_api_key,
    base_url=config.hunyuan_base_url,
    timeout=config.translation_timeout,  # 120 秒超时
)

# 翻译调用
resp = self.client.chat.completions.create(
    model=self.model,
    messages=[
        {"role": "system", "content": system_prompt},
        {"role": "user", "content": unit.source_text},
    ],
    temperature=self.temperature,
    top_p=self.top_p,
)
```

### 5. 管道编排 (`app/worker/pipeline.py`) — **核心文件**

**主流程**：
```python
def run(self, input_path, output_path, qa_report_path="", glossary_path="", resume=True) -> Task:
    # 1. 安装 SIGTERM 信号处理器
    # 2. 加载 checkpoint（如果存在且匹配）
    # 3. 加载术语库 + TM
    # 4. 初始化翻译器
    # 5. 提取 DOCX → TranslationUnits（如果未恢复）
    # 6. 翻译（带重试 + checkpoint）
    # 7. QA 质检
    # 8. 写入输出 DOCX
    # 9. 扫描输出 DOCX 的 CJK 残留
    # 10. 生成 QA 报告
    # 11. 清理 checkpoint
    # 12. 返回 Task
```

**信号处理**（关键代码）：
```python
# 模块级常量
CHECKPOINT_EVERY = 5  # 每 5 单元 checkpoint

# 信号处理器（修复了 scoping bug）
_current_task = [None]  # 可变容器，闭包捕获引用

def sigterm_handler(signum, frame):
    t = _current_task[0]
    if t and self._checkpoint_path:
        self._save_checkpoint(t)
    raise KeyboardInterrupt("SIGTERM received")

signal.signal(signal.SIGTERM, sigterm_handler)
```

**翻译循环**（关键逻辑）：
```python
for i, unit in enumerate(task.units):
    # 跳过空单元
    # 跳过已翻译（续传）
    # TM 查找（命中则跳过）
    # 术语库查找
    # API 翻译（带重试）
    # 添加到 TM
    
    # 每 10 单元记录进度
    if (i + 1) % 10 == 0 or i == total - 1:
        log.info(f"  Progress: {i+1}/{total} ({translated} ok, {tm_hits} tm, {errors} err)")
    
    # 每 CHECKPOINT_EVERY 单元保存 checkpoint
    if (i + 1) % CHECKPOINT_EVERY == 0:
        self._save_checkpoint(task)
```

**异常处理**：
```python
try:
    # 主流程
except KeyboardInterrupt:
    # Ctrl+C 或 SIGTERM → 保存 checkpoint
except SystemExit:
    # 系统退出 → 保存 checkpoint
except Exception as e:
    # 其他错误 → 保存 checkpoint
finally:
    signal.signal(signal.SIGTERM, original_sigterm)  # 恢复原始 handler
```

### 6. CLI 入口 (`drive_translate.py`)

**使用方式**：
```bash
# 处理 Drive in/ 中下一个未翻译文件
python3 drive_translate.py

# 列出 Drive in/ 中的文件
python3 drive_translate.py --list-only

# 处理特定 Drive 文件
python3 drive_translate.py --drive-file-id <id> --drive-file-name <name>

# 禁用 QA
python3 drive_translate.py --no-qa
```

**输出格式**：
```
{
  "source": "tdra05.docx",
  "status": "success",
  "output": "tdra05.en.docx",
  "units": 604,
  ...
}

─── 结论 ───
✅ 翻译完成，质量合格
📄 tdra05.docx → tdra05.en.docx
📊 604 单元 | 0 错误 | 23 警告 | TM 命中 112
⏱ 耗时: 2分16秒
📁 输出: translate/out/tdra05.en.docx
```

---

## 四、已知问题与限制

### 高优先级
1. **exec 超时无法避免**：OpenClaw exec 会话有硬时限（~10-12 分钟）
   - 长文档（>600 单元）需要多次运行 + checkpoint 续传
   - 当前方案：checkpoint 每 5 单元，SIGTERM 安全
   - **替代方案**：cron 驱动（每 5 分钟检查 Drive in/），Zane 暂时否决

2. **图片保留不完整**：python-docx 的 inline shapes 读取有局限
   - 图片在翻译后可能丢失
   - 需要增强 `docx/extractor.py` 和 `docx/writer.py`

### 中优先级
3. **TM 仅 exact match**：不支持 fuzzy 匹配
   - 相似句子无法复用已有翻译
   - 需要实现 fuzzy matching（如 Levenshtein distance）

4. **CJK 残留需手动修复**：Hunyuan Lite 对中英混排有保留中文倾向
   - Post-write checker 能检测，但需要自动修复机制
   - 当前：26 个段落有 CJK 残留

5. **无并发控制**：同一文件可能被多次触发翻译
   - `--drive-file-id` 模式无互斥锁
   - 需要添加文件锁或状态检查

### 低优先级
6. **`app/config.py` 已废弃**：实际使用 `app/core/config.py`
   - 应删除废弃文件
   - 避免混淆

7. **TM 文件未排除**：`data/tm/default_tm.json` 可能包含敏感内容
   - 已在 .gitignore 中排除
   - 但本地文件可能泄露

---

## 五、环境依赖

### Python 依赖
```bash
pip install openai python-docx pyyaml
```

### 外部工具
- `gog` CLI：Google Drive 操作（已安装在系统）
  - 命令：`gog drive ls/download/upload/delete/rename`
  - 认证：OAuth，无需 API key

### API
- 腾讯混元 Lite API
  - 基础 URL：`https://api.hunyuan.cloud.tencent.com/v1`
  - 模型：`hunyuan-lite`
  - 认证：Bearer token（`HUNYUAN_API_KEY` 环境变量）

---

## 六、后续开发建议

### 立即行动
1. **删除废弃文件**：`app/config.py`（实际用 `app/core/config.py`）
2. **添加单元测试**：`tests/` 目录为空，需要补充
3. **验证大文档续传**：1863 单元的 `technical_proposal_TDRA.docx`

### 短期优化
4. **实现 fuzzy TM**：相似度匹配（阈值 0.85+）
5. **自动修复 CJK 残留**：检测到残留时自动调用 API 重翻
6. **图片保留增强**：处理 python-docx inline shapes 限制

### 中期规划
7. **cron 驱动方案**：如果用户反馈需要更及时响应
8. **并发控制**：文件锁防止重复翻译
9. **批量处理**：支持一次处理多个文件

### 长期考虑
10. **多模型支持**：除 Hunyuan Lite 外支持其他模型
11. **双语对照输出**：生成中英对照文档
12. **人工审核流程**：翻译后人工校对机制

---

## 七、开发工作流

### 本地开发
```bash
cd ~/.openclaw/workspace/projects/translate-docs/translate_pipeline

# 设置环境变量
export HUNYUAN_API_KEY="sk-..."

# 测试翻译
python3 drive_translate.py --list-only
python3 drive_translate.py --drive-file-id <id> --drive-file-name test.docx
```

### Git 工作流
```bash
# 当前已有 main 分支
git status
git add .
git commit -m "feat: description"
git push origin main
```

### 调试技巧
- 日志级别：修改 `app/core/config.py` 中 `setup_logging(verbose=True)`
- checkpoint 位置：`data/jobs/{filename}_checkpoint.json`
- 手动清除 TM：删除 `data/tm/default_tm.json`
- 手动清除 checkpoint：删除 `data/jobs/*.json`

---

## 七.5、OpenClaw Agent 调用方式

### ⚠️ 重要：必须使用 Subagent 模式

当从 OpenClaw agent 触发翻译时，**不要在主 session 直接执行**，必须使用 `sessions_spawn`：

```python
sessions_spawn(
    task="""你是翻译执行器。任务：翻译 Drive translate/in/ 中下一个未翻译的文件。

步骤：
1. 用 exec background=true 运行：
   cd ~/.openclaw/workspace/projects/translate-docs/translate_pipeline && HUNYUAN_API_KEY="HUNYUAN_API_KEY_REMOVED" python3 drive_translate.py

2. 用 process poll 轮询等待完成（timeout 1800000ms）

3. 读取输出，返回完整结果摘要""",
    mode="run",
    runTimeoutSeconds=2400,  # 40 分钟
    label="translate-doc",
)
```

### 为什么必须用 Subagent

| 方案 | 主 agent 阻塞 | exec 超时风险 | 用户体验 |
|------|--------------|--------------|---------|
| 直接 exec | ✅ 阻塞 30 分钟 | ❌ 10 分钟被杀 | ❌ 无法交互 |
| subagent + background exec | ✅ 立即解放 | ✅ 进程独立运行 | ✅ 可继续操作 |

**关键发现**（2026-03-15 实测）：
- subagent 的 `runTimeoutSeconds` 超时只关闭回报通道
- `background exec` 进程继续独立运行不受影响
- 翻译结果通过 `status.json` + Drive 持久化，可随时查询

### Timeout 设置

```
runTimeoutSeconds=2400      # subagent 存活 40 分钟
process poll timeout=1800000 # 翻译进程最长 30 分钟
```

**覆盖范围**：
- 小文档（600 单元）：~10 分钟
- 大文档（1863 单元）：~30 分钟
- buffer：10 分钟给 QA + 上传

### 触发后响应模板

```
🚀 翻译任务已启动
📋 文件: {filename}
⏱ 预计: {estimated_time}
📁 输出: translate/out/{filename}.en.docx

完成后自动回报结果，你可以继续其他操作。
```

---

## 八、关键设计决策记录

1. **使用 gog CLI 而非 Google API SDK**：避免 API 密钥管理，复用现有 OAuth 认证
2. **单一状态文件而非多文件**：`in/status.json` 优于 `out/*.status.json`，更简洁
3. **可变容器 `_current_task[0]`**：解决 Python 闭包变量作用域问题
4. **checkpoint 每 5 单元**：权衡性能和安全性，5 单元约 15 秒工作量
5. **SIGTERM 转 KeyboardInterrupt**：复用现有异常处理逻辑，减少重复代码
6. **双输出格式**：JSON 供自动化消费，摘要供人工阅读
7. **Subagent 模式调用**：主 agent spawn 独立 session 执行翻译，不阻塞主 session
8. **`mode="run"` 而非 `mode="session"`**：翻译是批处理无多轮交互，持久化浪费资源

---

## 九、联系与资源

- **GitHub**：https://github.com/ZaneChen76/translate-pipeline
- **技术文档**：`PROJECT_SUMMARY.md`（仓库内完整文档）
- **Zane**：zanechen@gmail.com（项目所有者）
- **Drive 结构**：`translate/in/` + `translate/out/`
- **Gog 工具**：已安装在系统，OAuth 已配置

---

**祝编码愉快！有问题随时联系 Zane 或查阅 PROJECT_SUMMARY.md。**
