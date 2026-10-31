"""Optional read-only ExifTool adapter for additional embedded time/editor tags.

ExifTool runs ONLY when a user explicitly opts in. It is not required to run the app.
Treat all discovered dates as editable assertions, not independent proof.
"""
from __future__ import annotations

import json
import shutil
import subprocess
from pathlib import Path

from .timeline import add_stamp, select_timeline



def get_exiftool_version(binary: str) -> str | None:
    try:
        completed = subprocess.run([binary, '-ver'], capture_output=True, text=True,
                                   timeout=5, check=False)  # nosec B603
        if completed.returncode == 0:
            return completed.stdout.strip()
    except (subprocess.TimeoutExpired, OSError, ValueError):
        pass
    return None


def enrich_report(report: dict, path: str | Path) -> None:
    """Read a local file via ExifTool; include only non-sensitive forensic tags."""
    binary = shutil.which('exiftool')
    if not binary:
        report['forensics']['exiftool'] = {
            'status': 'not_installed',
            'install': 'Ubuntu/Colab: apt-get install -y libimage-exiftool-perl'
        }
        return
    version = get_exiftool_version(binary)
    # No shell; no write flags; no upload of raw content to third-party services.
    command = [binary, '-j', '-G1', '-s', '-a', '-time:all',
               '-Software', '-CreatorTool', '-Creator', '-Producer', '-Artist', '--', str(path)]
    try:
        completed = subprocess.run(command, capture_output=True, text=True,
                                   timeout=15, check=False)  # nosec B603
        if completed.returncode != 0:
            report['forensics']['exiftool'] = {'status': 'failed',
                                              'detail': 'ExifTool gagal memproses file.'}
            return
        if len(completed.stdout) > 250_000:
            report['forensics']['exiftool'] = {'status': 'output_too_large'}
            return
        records = json.loads(completed.stdout)
        if not isinstance(records, list) or not records or not isinstance(records[0], dict):
            raise ValueError('Unexpected response format')
        metadata = records[0]
        supplemental: list[dict] = []
        editor_tags = {}
        fs_times = {}
        for name, value in metadata.items():
            local_name = name.split(':')[-1]
            # File/system tags belong to the current machine, not embedded metadata.
            if name.startswith(('System:', 'File:')):
                if local_name in {'FileCreateDate','FileModifyDate','FileInodeChangeDate'}:
                    fs_times[local_name] = str(value)[:100]
                continue
            if local_name in {'Software', 'CreatorTool', 'Creator', 'Producer', 'Artist'}:
                editor_tags[name] = str(value)[:180]
            if local_name in {'DateTimeOriginal', 'CreateDate', 'CreationDate', 'DateCreated', 'DateTimeDigitized'}:
                event = 'captured' if local_name in {'DateTimeOriginal', 'DateCreated'} else 'created'
            elif local_name in {'ModifyDate', 'ModDate', 'DateTime', 'FileModified', 'MetadataDate'}:
                event = 'modified' if local_name != 'MetadataDate' else 'metadata_updated'
            else:
                continue
            add_stamp(supplemental, event, 'exiftool.' + name, value)
        timeline = report['forensics']['timeline']
        existing = timeline['timestamps']
        dedup = {(s['event'], s['raw']) for s in existing}
        new_entries = [s for s in supplemental if (s['event'], s['raw']) not in dedup]
        merged = existing + new_entries
        new_summary, new_findings = select_timeline(merged)
        timeline.update(new_summary)
        timeline['timestamps'] = merged
        # Do not duplicate timeline findings.
        old_codes = {f['code'] for f in report['forensics']['findings']}
        report['forensics']['findings'].extend(f for f in new_findings if f['code'] not in old_codes)
        if any(f['severity']=='review' for f in new_findings):
            report['forensics']['summary'] = 'Perlu pemeriksaan lanjutan'
        exiftool_info = {'status': 'completed',
                         'version': version,
                         'supplemental_embedded_time_tags': len(new_entries),
                         'editor_tags': editor_tags,
                         'runtime_filesystem_tags': fs_times,
                         'warning': 'Tag File/System berasal dari mesin saat analisis, bukan verifikasi tanggal asli.'}
        if version:
            try:
                # Flag known legacy versions (< 12.50) vulnerable to upstream CVEs
                major_minor = float('.'.join(version.split('.')[:2]))
                if major_minor < 12.50:
                    exiftool_info['security_advisory'] = f'Versi ExifTool {version} lawas (< 12.50); perbarui untuk mitigasi celah keamanan.'
            except (ValueError, IndexError):
                pass
        report['forensics']['exiftool'] = exiftool_info
    except (subprocess.TimeoutExpired, ValueError, json.JSONDecodeError, OSError):
        report['forensics']['exiftool'] = {'status': 'error',
                                          'detail': 'Scan tambahan tidak selesai; analisis inti tetap tersedia.'}
