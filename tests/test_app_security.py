import os
import time
from pathlib import Path

from app import REPORTS_DIR, _cleanup_old_reports, _format_verdict_card, _generate_multi_overview


def test_reports_dir_is_restricted():
    assert REPORTS_DIR.exists()
    assert oct(REPORTS_DIR.stat().st_mode & 0o777) == oct(0o700)


def test_cleanup_old_reports():
    test_file = REPORTS_DIR / 'verifile-report-test-old.json'
    test_file.write_text('{"test": true}', encoding='utf-8')
    # Set mtime to 3600 seconds ago
    old_time = time.time() - 3600
    os.utime(test_file, (old_time, old_time))

    _cleanup_old_reports(max_age_seconds=60)
    assert not test_file.exists()


def test_xss_prevention_in_verdict_card_and_overview():
    import html
    payload = "<script>alert('xss')</script>"
    fake_report = {
        'file': {'name': payload, 'type_detected': 'png', 'bytes': 100, 'sha256': 'abc'},
        'verdict_title': payload,
        'verdict_category': 'MANIPULASI_TERDETEKSI',
        'risk_level': 'TINGGI',
        'forensics': {'summary': payload, 'findings': []},
        'receipt_data': {
            'is_receipt': True,
            'bank': payload,
            'transaction_status': payload,
            'amounts': {'header': payload, 'nominal': payload, 'total': payload},
            'date_time': payload,
            'ref_id': payload,
            'recipient': payload,
            'sender': payload,
            'internal_consistency': {'is_consistent': False, 'reason': payload},
        }
    }

    card_html = _format_verdict_card(fake_report)
    assert "<script>" not in card_html
    assert html.escape(payload) in card_html

    overview_html = _generate_multi_overview([fake_report, fake_report])
    assert "<script>" not in overview_html
    assert html.escape(payload) in overview_html



