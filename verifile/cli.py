"""Example: python -m verifile.cli demo/edited_sample.jpg --ai --output report.json"""
import argparse
import json
from pathlib import Path

from verifile.forensics import UnsafeFile, analyze_file


def main():
    p = argparse.ArgumentParser(description='Local file forensic triage (NOT proof of fraud)')
    p.add_argument('file')
    p.add_argument('--reference', '-r', help='Optional same-resolution original image of the same transaction')
    p.add_argument('--ai', action='store_true', help='Run Gemma 4 / Gemini API fallback multimodal review')
    p.add_argument('--output', '-o', help='Write JSON to file')
    p.add_argument('--exiftool', action='store_true', help='Optional deep embedded metadata scan (requires ExifTool)')
    args = p.parse_args()
    try:
        result, pages, _ = analyze_file(args.file, reference_path=args.reference, use_exiftool=args.exiftool)
    except (UnsafeFile, OSError, ValueError) as exc:
        p.error(str(exc))
    if args.ai:
        from verifile.gemma import Gemma4Reviewer
        from verifile.overlay import amount_crops
        crops = []
        if pages and result['forensics'].get('overlay_diagnostics'):
            candidates = result['forensics']['overlay_diagnostics'][0].get('amount_candidates', [])
            crops = amount_crops(pages[0], candidates)
        try:
            result['gemma4'] = Gemma4Reviewer().review(result, pages[:1] + crops[:2] if crops else pages[:3])
        except Exception as exc:
            result['gemma4'] = {'status': 'error', 'analysis': {'error': f'{type(exc).__name__}: {exc}'[:800]}}
    content = json.dumps(result, indent=2, ensure_ascii=False)
    if args.output:
        Path(args.output).write_text(content, encoding='utf-8')
        print(f'Report saved: {args.output}')
    else:
        print(content)


if __name__ == '__main__':
    main()
