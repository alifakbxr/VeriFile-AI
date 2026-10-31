import os
import time
from pathlib import Path

from app import REPORTS_DIR, _cleanup_old_reports


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

