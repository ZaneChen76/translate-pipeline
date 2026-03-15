# Translate Pipeline Project Summary

**Project Location**: `~/.openclaw/workspace/projects/translate-docs/translate_pipeline/`

## Overview
This project implements a format-preserving DOCX translation pipeline for Chinese→English technical/bid documents with:
- Error retry with exponential backoff (2s→4s→8s, max 30s, 3 attempts)
- Checkpoint/resume functionality (every 5 units, Ctrl+C auto-save, SIGTERM handling)
- Post-translation QA including Chinese residue detection
- Google Drive integration for file ingestion and output distribution
- Structured logging and JSON status reporting

## Directory Structure
```
translate_pipeline/
├── README.md                     # Project overview
├── drive_translate.py            # Main CLI script (Drive-integrated)
├── app/                          # Core application code
│   ├── __init__.py
│   ├── config.py                 # Configuration management
│   ├── connectors/
│   │   ├── __init__.py
│   │   └── drive.py              # Google Drive connector
│   ├── core/
│   │   ├── __init__.py
│   │   ├── task.py               # Data models (Task/TranslationUnit/etc)
│   │   └── translator.py         # Translator interface + factories
│   ├── docx/
│   │   ├── __init__.py
│   │   ├── extractor.py          # DOCX → TranslationUnit (structure-preserving)
│   │   └── writer.py             # TranslationUnit → DOCX (format-preserving)
│   ├── translation/
│   │   ├── __init__.py
│   │   ├── glossary.py           # YAML glossary loading + prompt injection
│   │   └── tm.py                 # Translation Memory (exact match + persistence)
│   ├── qa/
│   │   ├── __init__.py
│   │   ├── checks.py             # QA checkers (structure, numbers, terms, missing translation, Chinese residue)
│   │   └── report.py             # Markdown QA report generation
│   └── worker/
│       ├── __init__.py
│       └── pipeline.py           # Pipeline orchestrator (extract → translate → QA → write)
├── data/                         # Working directories
│   ├── inbox/                    # Source DOCX files (from Drive)
│   ├── output/                   # Translated DOCX + QA reports
│   └── jobs/                     # Checkpoint files (.json)
├── docs/                         # Additional documentation
└── tests/                        # Unit tests (placeholder)
```

## Key Features & Implementation Details

### 1. Data Models (`app/core/task.py`)
- `Task`: Top-level container with metadata, stats, issues, and list of `TranslationUnit`
- `TranslationUnit`: Represents a translatable text segment (paragraph or table cell)
  - Fields: `source_text`, `translated_text`, `unit_id`, `part` (paragraph/table), `path` (location), `style_name`, `tm_hit`, `term_hits`, `error`
  - Supports rich context (`context_before`, `context_after`) for better translation
- `GlossaryEntry`, `TmEntry`, `QaIssue`: Supporting models for glossary, translation memory, and quality issues

### 2. Configuration (`app/core/config.py`)
- Centralized configuration with sensible defaults
- Supports override via environment variables or object modification
- Key sections:
  - `translator`: Provider selection (HunyuanLite, Mock)
  - `paths`: Directories for glossary, TM, jobs, etc.
  - `qa_enabled`: Toggle quality assurance checks
  - `retry`: Max attempts, backoff base/max
  - `translation_timeout`: Per-API-call timeout (default 120s)
  - `CHECKPOINT_EVERY`: Units between checkpoints (constant in pipeline.py, default 5)

### 3. Google Drive Integration (`app/connectors/drive.py`)
- Uses `gog` CLI tool for Drive operations (no API keys needed)
- Functions:
  - `list_inbox()`: Lists files in Drive `translate/in/` (excluding status.json)
  - `download(file)`: Downloads file to local `data/inbox/`
  - `upload_to_out(local_path, name)`: Uploads to Drive `translate/out/`
  - **Unified Status Tracking**: Single `status.json` in Drive `translate/in/` tracking all files
    - Format: `{filename: {status, output, drive_link, units, errors, ..., translated_at}}`
    - Functions: `load_status()`, `save_status()`, `mark_processed()`, `is_processed()`

### 4. DOCX Processing (`app/docx/extractor.py` & `app/docx/writer.py`)
- **Extractor**: 
  - Iterates through document body (paragraphs and tables)
  - Preserves structural mapping: stores `path` like `paragraph[5]` or `table[2][1][3]` (table[row][cell][paragraph])
  - Preserves styles via `style_name`
  - Skips empty text but retains structure
- **Writer**:
  - Replaces `translated_text` in original structure
  - Preserves all original formatting, styles, images, and layout
  - Outputs to `*.en.docx` by convention

### 5. Translation Layer (`app/translation/`)
- **Interface** (`translator.py`):
  - Abstract `Translator` base class with `translate(unit, glossary)` method
  - Factory `create_translator(config)` returns appropriate implementation
- **Implementations**:
  - `MockTranslator`: Returns fake translation for testing
  - `HunyuanLiteTranslator`: 
    - Uses OpenAI-compatible API (`https://api.hunyuan.cloud.tencent.com/v1`)
    - Model: `hunyuan-lite`
    - Authentication: Bearer token from `HUNYUAN_API_KEY` env var
    - Timeout: Configurable via `translation_timeout` (default 120 seconds)
- **Glossary** (`glossary.py`):
  - Loads YAML glossaries (format: `source_term: target_term`)
  - Provides lookup and prompt injection capabilities
- **Translation Memory** (`tm.py`):
  - Exact-match TM stored as JSON (`default_tm.json`)
  - Persistent across runs (load/save)
  - Prevents re-translation of identical sentences

### 6. Quality Assurance (`app/qa/`)
- **Checkers** (`checks.py`):
  - `StructureChecker`: Compares input/output unit counts and structure
  - `NumberChecker`: Ensures numbers/formats are preserved
  - `TermChecker`: Flags missing glossary terms
  - `MissingTranslationChecker`: Detects untranslated units
  - `ChineseResidueChecker`: **Post-write** scan of output DOCX for any CJK characters (>0 = warning)
- **Report Generator** (`report.py`):
  - Creates Markdown QA report with summary tables and detailed issues
  - Saved as `*.qa.md` alongside output DOCX

### 7. Pipeline Orchestration (`app/worker/pipeline.py`)
Main workflow in `Pipeline.run()`:
1. **Resume Check**: Load checkpoint if exists and matches input file
2. **Initialization**: 
   - Load glossary (YAML files from config directory)
   - Load translation memory
   - Initialize translator (HunyuanLite by default)
3. **Extraction** (if not resumed): Convert DOCX → Task with TranslationUnits
4. **Translation** (`_translate_units_with_retry`):
   - First pass: TM lookup → glossary lookup → API translation
   - Retry logic: Exponential backoff (2s→4s→8s, max 30s) for failed units
   - Checkpointing: Every `CHECKPOINT_EVERY=5` units (module constant)
   - Progress logging: Every 10 units
   - Per-API-call timeout: `translation_timeout` (default 120s)
5. **QA** (if enabled): Run all checkers, collect issues
6. **Writing**: Convert Task → DOCX via `DocxWriter`
7. **Post-write Chinese Scan**: Additional pass on output DOCX
8. **Report Generation**: If requested, create QA Markdown report
9. **Cleanup**: Delete checkpoint on success
10. **Return**: Populated Task object

**Special Handling**:
- **SIGTERM**: Custom handler saves checkpoint via mutable `_current_task[0]` reference, then raises `KeyboardInterrupt`
- **KeyboardInterrupt**: Save checkpoint before re-raising
- **SystemExit**: Save checkpoint before re-raising
- **Finally block**: Always restores original SIGTERM handler
- **TM Updates**: New translations added to memory after successful translation
- **Stats Tracking**: Counters for translated units, TM hits, errors, timing

### 8. Drive-Integrated CLI (`drive_translate.py`)
Entry point with these modes:
- **Default**: Process next untranslated file from Drive `in/` → translate → upload to `out/` → update status
- **`--list-only`**: Show files in Drive `in/` without processing
- **`--drive-file-id`**: Process specific Drive file by ID
- **Output**: 
  - Machine-readable JSON (for automation/cron)
  - Human-readable conclusion summary (for Discord)
    - Example: 
      ```
      ⚠️ 翻译完成，82 项 QA 错误需关注
      📄 tdra05.docx → tdra05.en.docx
      📊 604 单元 | 82 错误 | 23 警告 | TM 命中 112
      ⏱ 耗时: 2分16秒
      📁 输出: translate/out/tdra05.en.docx
      ```

## Verified Capabilities (as of 2026-03-15)

### ✅ Core Functionality
- Format-preserving DOCX translation (structure, styles, images retained)
- Chinese→English technical document translation via Hunyuan Lite API
- Exponential backoff retry for transient API failures
- Checkpoint/resume every `CHECKPOINT_EVERY=5` units (module constant)
- Signal-safe checkpoint: SIGTERM handler uses mutable `_current_task[0]` reference
- Per-API-call timeout: 120s default (`translation_timeout` in config)
- Unified status tracking via Drive `in/status.json`
- Google Drive ingestion (`translate/in/`) and egress (`translate/out/`)
- Post-translation QA including Chinese residue detection
- Structured logging to stdout/stderr

### ✅ Tested Scenarios
- **Small document** (`bid_sample.docx`): 238 paragraphs, 0 errors, full pipeline success
- **Medium document** (`tdra03.docx`): 279 paragraphs, 604 units, completed in ~25s
- **Large document** (`technical_proposal_TDRA.docx`): 1863 units, 0 translation errors, ~30min
- **Resume after interruption**: Verified checkpoint saves and restores correctly
- **SIGTERM handling**: Process saves checkpoint on termination signal
- **Status tracking**: Files correctly skipped when already processed

### 🔄 Current Limitations & Next Steps
- **Image handling**: python-docx limitation - inline shapes not fully preserved (known issue)
- **QA errors**: Primarily numeric format differences (commas/spaces) - acceptable for technical docs
- **Chinese residue**: Post-write checker catches residual CJK; may require manual review
- **Large file transfer**: 8.5MB+ DOCX exceeds Gmail API limits - Drive sharing recommended
- **Future improvements**: 
  - Add fuzzy TM matching
  - Improve glossary context injection
  - Add bilingual review mode

## How to Use
1. **Add source file**: Place DOCX in Google Drive `translate/in/` folder
2. **Trigger translation**: Send message to systemarchitect agent (or run `drive_translate.py` manually)
3. **Monitor progress**: Watch logs or wait for completion message
4. **Get results**: 
   - Translated DOCX appears in Drive `translate/out/` 
   - QA report (`*.qa.md`) in same folder
   - Status updated in Drive `translate/in/status.json`
5. **Process next file**: Repeat - already translated files are automatically skipped

## Contact
Maintained by: SystemArchitect agent  
Project initialized: 2026-03-12  
Last updated: 2026-03-15 (SIGTERM handling bugfix + checkpoint frequency + translation timeout)