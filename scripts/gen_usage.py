#!/usr/bin/env python3
"""Generate USAGE.md from argparse CLI (main + subcommands)."""
from pathlib import Path
import sys
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from app.main import build_parser


def collect_subparsers(parser):
    subs = {}
    for action in parser._actions:
        if action.__class__.__name__ == 'SubParsersAction':
            for cmd, sp in action.choices.items():
                subs[cmd] = sp
    return subs


def generate_usage_md() -> str:
    parser = build_parser()
    out = []
    out.append('# translate-pipeline CLI Usage')
    out.append('')
    out.append('```')
    out.append(parser.format_help())
    out.append('```')
    out.append('')

    subs = collect_subparsers(parser)
    if subs:
        out.append('## Commands')
        out.append('')
        for name, sp in subs.items():
            out.append(f'### {name}')
            out.append('')
            out.append('```')
            out.append(sp.format_help())
            out.append('```')
            out.append('')
    return "\n".join(out)


def main():
    md = generate_usage_md()
    root = Path(__file__).resolve().parents[1]
    (root / 'USAGE.md').write_text(md, encoding='utf-8')
    print('USAGE.md updated')


if __name__ == '__main__':
    main()
