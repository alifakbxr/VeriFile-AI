"""Examples:
  Single file JSON: python -m verifile.cli demo/edited_sample.jpg --ai --output report.json
  Batch PDF/Excel:  python -m verifile.cli "demo/TEST DATA" --ai --output batch_report.pdf
                    python -m verifile.cli demo/clean_sample.jpg demo/edited_sample.jpg -o batch.xlsx
"""
import argparse
import json
from pathlib import Path

from verifile.forensics import UnsafeFile, analyze_file


def _is_batch_invocation(files: list[str], output: str | None, force_batch: bool) -> bool:
    if force_batch or len(files) > 1:
        return True
    if Path(files[0]).is_dir():
        return True
    if output and Path(output).suffix.lower() in {'.pdf', '.xlsx', '.csv'}:
        return True
    return False


def main():
    p = argparse.ArgumentParser(description='Local file & batch forensic triage (NOT proof of fraud)')
    p.add_argument('files', nargs='+', help='One or more files or folders to analyze')
    p.add_argument('--reference', '-r', help='Optional same-resolution original image (single-file mode only)')
    p.add_argument('--ai', action='store_true', help='Run Gemma 4 / Gemini API fallback multimodal review')
    p.add_argument('--ai-max-files', type=int, default=10,
                   help='Max files to send to AI in batch mode (default: 10, protects API quota)')
    p.add_argument('--ai-delay', type=float, default=1.5,
                   help='Seconds to pause between batch AI requests (default: 1.5)')
    p.add_argument('--batch', action='store_true', help='Force batch report schema even for a single file')
    p.add_argument('--output', '-o', help='Output path (.pdf, .xlsx, .csv, or .json)')
    p.add_argument('--exiftool', action='store_true', help='Optional deep embedded metadata scan (requires ExifTool)')
    args = p.parse_args()

    if _is_batch_invocation(args.files, args.output, args.batch):
        if args.reference:
            p.error('--reference is only supported when analyzing a single target image.')
        from verifile.batch import (
            analyze_batch,
            export_batch_csv,
            export_batch_excel,
            export_batch_json,
            export_batch_pdf,
        )
        try:
            batch_result, thumbs = analyze_batch(
                args.files,
                use_ai=args.ai,
                use_exiftool=args.exiftool,
                ai_max_files=args.ai_max_files,
                ai_delay_seconds=args.ai_delay,
            )
        except (UnsafeFile, OSError, ValueError) as exc:
            p.error(str(exc))

        if not args.output:
            print(json.dumps(batch_result, indent=2, ensure_ascii=False))
            return

        out_path = Path(args.output)
        ext = out_path.suffix.lower()
        if ext == '.pdf':
            export_batch_pdf(batch_result, out_path, thumbnails=thumbs)
        elif ext == '.xlsx':
            export_batch_excel(batch_result, out_path)
        elif ext == '.csv':
            export_batch_csv(batch_result, out_path)
        elif ext == '.json':
            export_batch_json(batch_result, out_path)
        else:
            p.error('Unsupported batch output extension. Choose .pdf, .xlsx, .csv, or .json.')
        totals = batch_result['totals']
        print(
            f"Batch report saved: {out_path} "
            f"({totals['files_processed']}/{totals['files_total']} processed, "
            f"{totals['needs_review_count']} need review)"
        )
        return

    target = args.files[0]
    try:
        result, pages, _ = analyze_file(target, reference_path=args.reference, use_exiftool=args.exiftool)
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
