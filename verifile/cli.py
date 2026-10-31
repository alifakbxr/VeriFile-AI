"""Example: python -m verifile.cli demo/clean_sample.png --output report.json"""
import argparse
import json
from pathlib import Path

from verifile.forensics import UnsafeFile, analyze_file


def main():
    p = argparse.ArgumentParser(description='Local file forensic triage (NOT proof of fraud)')
    p.add_argument('file')
    p.add_argument('--output', '-o', help='Write JSON to file')
    p.add_argument('--exiftool', action='store_true', help='Optional deep embedded metadata scan (requires ExifTool)')
    args = p.parse_args()
    try:
        result, _, _ = analyze_file(args.file, use_exiftool=args.exiftool)
    except (UnsafeFile, OSError) as exc:
        p.error(str(exc))
    content = json.dumps(result, indent=2, ensure_ascii=False)
    if args.output:
        Path(args.output).write_text(content, encoding='utf-8')
        print(f'Report saved: {args.output}')
    else:
        print(content)


if __name__ == '__main__':
    main()
