"""Collect untrusted embedded date metadata separately from observed filesystem times.

A date tag is evidence of what *the file claims*, not a trusted forensic clock.
"""
from __future__ import annotations

import re
import struct
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any
import defusedxml.ElementTree as ET

MAX_XMP_BYTES = 256 * 1024


def parse_timestamp(raw: Any) -> tuple[str | None, bool]:
    """ISO-8601 normalized timestamp and whether an explicit timezone was supplied."""
    if raw is None:
        return None, False
    value = str(raw).strip().strip('\x00')
    if not value:
        return None, False
    # ISO, W3C-DTF, EXIF and PNG text conventions. Reject incomplete and zeroed dates.
    # EXIF: 2026:10:31 10:15:00, optionally with an offset.
    exif = re.fullmatch(r'(\d{4}):(\d\d):(\d\d)[ T](\d\d):(\d\d):(\d\d)(Z|[+-]\d\d:?\d\d)?', value)
    if exif:
        y, mo, d, h, mi, s, offset = exif.groups()
        value = f'{y}-{mo}-{d}T{h}:{mi}:{s}{offset or ""}'
    # PDF: D:20261031091500+07'00' or D:20261031091500Z.
    elif value.startswith('D:'):
        match = re.fullmatch(r"D:(\d{4})(\d\d)(\d\d)(\d\d)(\d\d)(\d\d)(Z|[+-]\d\d'?\d\d'?)?", value)
        if not match:
            return None, False
        y, mo, d, h, mi, s, offset = match.groups()
        offset = (offset or '').replace("'", '')
        value = f'{y}-{mo}-{d}T{h}:{mi}:{s}{offset}'
    value = value.replace(' ', 'T', 1)
    if value.endswith('Z'):
        value = value[:-1] + '+00:00'
    # Avoid accepting arbitrary strings or date-only fields as precise timestamps.
    if not re.fullmatch(r'\d{4}-\d\d-\d\dT\d\d:\d\d:\d\d(?:\.\d+)?(?:[+-]\d\d:?\d\d)?', value):
        return None, False
    try:
        parsed = datetime.fromisoformat(value)
        return parsed.isoformat(), parsed.tzinfo is not None
    except ValueError:
        return None, False


def add_stamp(items: list[dict], event: str, source: str, raw: Any, *, offset: str | None = None) -> None:
    if raw is None or str(raw).strip() in {'', 'none', 'None'}:
        return
    text = str(raw).strip()[:120]
    parsed_input = text
    if offset and not re.search(r'(?:Z|[+-]\d\d:?\d\d)$', text):
        parsed_input = text + offset
    normalized, tz_known = parse_timestamp(parsed_input)
    items.append({'event': event, 'source': source, 'raw': text,
                  'normalized_iso': normalized,
                  'timezone': 'explicit' if tz_known else 'unspecified',
                  'trust': 'editable_embedded_metadata'})


def extract_xmp(data: bytes | str | None, prefix: str = 'xmp') -> tuple[list[dict], dict]:
    """Safely read select values from bounded XMP XML; no arbitrary private XMP keys."""
    stamps: list[dict] = []
    other: dict = {}
    if not data:
        return stamps, other
    if isinstance(data, str):
        data = data.encode('utf-8', errors='replace')
    if len(data) > MAX_XMP_BYTES or b'<!DOCTYPE' in data.upper() or b'<!ENTITY' in data.upper():
        return stamps, {'xmp_status': 'ignored_oversized_or_dtd'}
    try:
        root = ET.fromstring(data)
    except ET.ParseError:
        return stamps, {'xmp_status': 'invalid_xml'}
    date_names = {'CreateDate': 'created', 'ModifyDate': 'modified',
                  'MetadataDate': 'metadata_updated', 'DateCreated': 'captured'}
    seen: set[tuple] = set()
    for element in root.iter():
        for key, value in [(element.tag, element.text)] + list(element.attrib.items()):
            local = key.rsplit('}', 1)[-1].split(':')[-1]
            if local in date_names and value and (local, value) not in seen:
                seen.add((local, value))
                add_stamp(stamps, date_names[local], f'{prefix}.{local}', value)
            elif local in {'CreatorTool', 'Author'} and value and local not in other:
                other[local] = str(value)[:180]
    return stamps[:25], other


def extract_png_time(data: bytes) -> str | None:
    """PNG tIME is last-modification time in UTC, not necessarily capture time."""
    if not data.startswith(b'\x89PNG\r\n\x1a\n'):
        return None
    offset = 8
    # Scan bounded PNG chunks, with no decompression or file reads beyond data.
    while offset + 12 <= len(data):
        size = struct.unpack('>I', data[offset:offset+4])[0]
        chunk = data[offset+4:offset+8]
        if size > len(data) - offset - 12:
            break
        if chunk == b'tIME' and size == 7:
            y, m, d, h, minute, second = struct.unpack('>HBBBBB', data[offset+8:offset+15])
            try:
                return datetime(y, m, d, h, minute, second, tzinfo=timezone.utc).isoformat()
            except ValueError:
                return None
        offset += 12 + size
        if chunk == b'IEND':
            break
    return None


def select_timeline(stamps: list[dict]) -> tuple[dict, list[dict]]:
    """Pick representative timestamps, preserving all sources and conflicts."""
    source_priority = {
        'exif.DateTimeOriginal': 0, 'png.Creation Time': 0,
        'docx.core.created': 0, 'pdf.info.creationDate': 0,
        'exif.DateTimeDigitized': 1, 'xmp.CreateDate': 2,
        'pdf.xmp.CreateDate': 2, 'exif.DateTime': 0,
        'png.tIME': 0, 'docx.core.modified': 0, 'pdf.info.modDate': 0,
        'xmp.ModifyDate': 2, 'pdf.xmp.ModifyDate': 2,
    }
    usable = [s for s in stamps if s['normalized_iso']]
    def pick(event):
        candidates = [s for s in usable if s['event'] == event]
        return min(candidates, key=lambda s: source_priority.get(s['source'], 9)) if candidates else None
    creation = pick('created') or pick('captured')
    modified = pick('modified')
    findings: list[dict] = []
    status = 'insufficient_embedded_timestamps'
    if creation and modified:
        if creation['timezone'] != modified['timezone']:
            status = 'timezone_not_comparable'
        else:
            a = datetime.fromisoformat(creation['normalized_iso'])
            b = datetime.fromisoformat(modified['normalized_iso'])
            seconds = (b-a).total_seconds()
            if seconds < -120:
                status = 'metadata_timestamp_order_conflict'
                findings.append({'code':'metadata_timestamp_order_conflict',
                                 'title':'Urutan tanggal metadata tidak konsisten',
                                 'detail': 'Waktu perubahan lebih awal dari waktu pembuatan yang tercatat. '
                                           'Perbedaan jam perangkat atau metadata yang dapat diedit mungkin menjadi penyebab.',
                                 'severity':'review', 'source':'timeline'})
            elif seconds >= 0:
                status = 'modification_on_or_after_creation_recorded'
            else:
                status = 'close_clock_difference'
    elif creation or modified:
        status = 'partial_embedded_timestamps'
    if not stamps:
        findings.append({'code':'embedded_timestamps_missing', 'title':'Tanggal internal tidak tersedia',
                         'detail':'File tidak menyimpan timestamp yang didukung; ini lazim pada screenshot/ekspor dan bukan bukti pemalsuan.',
                         'severity':'info', 'source':'timeline'})
    summary = {'created': creation, 'modified': modified, 'chronology': status,
               'note': 'Ini adalah klaim dari metadata internal, bukan waktu yang terverifikasi. '
                       'Perubahan setelah pembuatan dapat sepenuhnya normal.'}
    return summary, findings


def observed_filesystem_times(path: Path) -> dict:
    """Filesystem times of local path only; upload/copy may reset them."""
    st = path.stat()
    birth = getattr(st, 'st_birthtime', None)
    return {
        'observed_modified_utc': datetime.fromtimestamp(st.st_mtime, timezone.utc).isoformat(),
        'observed_created_utc': datetime.fromtimestamp(birth, timezone.utc).isoformat() if birth is not None else None,
        'observed_inode_change_utc': datetime.fromtimestamp(st.st_ctime, timezone.utc).isoformat(),
        'creation_available': birth is not None,
        'trust': 'current_runtime_filesystem_only',
        'warning': 'Waktu filesystem merefleksikan file di mesin analisis. Upload/salin/unduh '
                   'dapat mengubahnya; inode change time bukan tanggal pembuatan.'
    }
