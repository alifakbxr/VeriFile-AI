"""Optional PhotoHolmes CLI wrapper; not part of the core/validated MVP pipeline.

PhotoHolmes upstream methods can be restricted by their own licenses (TruFor
noncommercial) and may require additional model weights or GPU resources.
"""
from __future__ import annotations

import argparse
import shutil
import subprocess
from pathlib import Path


def main():
    parser = argparse.ArgumentParser(description='Run optional PhotoHolmes backend on one image.')
    parser.add_argument('image', type=Path)
    parser.add_argument('--method', choices=['zero', 'dq', 'splicebuster', 'noisesniffer'], default='zero')
    parser.add_argument('--output-folder', type=Path, default=Path('photoholmes_results'))
    args = parser.parse_args()
    if not args.image.is_file() or args.image.suffix.lower() not in {'.jpg','.jpeg','.png','.webp'}:
        parser.error('Provide a local JPG, PNG or WebP image.')
    cmd = shutil.which('photoholmes')
    if cmd is None:
        parser.error('PhotoHolmes not installed. See docs/EXPERIMENTAL_BACKENDS.md for setup/license check.')
    args.output_folder.mkdir(parents=True,exist_ok=True)
    # No shell expansion, never interpret uploaded file data as command text.
    subprocess.run([cmd,'run',args.method,'--output-folder',str(args.output_folder.resolve()),
                    str(args.image.resolve())],check=True, timeout=600)
    print('Output:',args.output_folder.resolve())
    print('Exploratory forensic result, not a validated fraud score.')


if __name__=='__main__':
    main()
