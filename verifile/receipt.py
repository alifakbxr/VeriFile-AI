"""Parsing and internal consistency verification for Indonesian transfer receipts / e-wallet screenshots."""
from __future__ import annotations

import re
from typing import Any

BANK_PATTERNS = [
    (r"wondr\s+by\s+BNI", "wondr by BNI"),
    (r"\bBNI\b|Bank\s+Negara\s+Indonesia", "Bank BNI"),
    (r"\bBCA\b|myBCA|BCA\s*mobile|KlikBCA", "Bank BCA"),
    (r"\bLivin\b|Mandiri", "Bank Mandiri (Livin)"),
    (r"\bBRImo\b|\bBRI\b|Bank\s+Rakyat\s+Indonesia", "Bank BRI (BRImo)"),
    (r"\bBSI\b|Bank\s+Syariah\s+Indonesia", "Bank Syariah Indonesia (BSI)"),
    (r"\bJago\b|Bank\s+Jago", "Bank Jago"),
    (r"\bCIMB\b|OCTO\s*Mobile", "CIMB Niaga (OCTO)"),
    (r"\bPermata\b|PermataMobile", "PermataBank"),
    (r"\bJenius\b|\bBTPN\b", "Jenius (BTPN)"),
    (r"\bSeaBank\b", "SeaBank"),
    (r"\bAllo\s*Bank\b", "Allo Bank"),
    (r"\bDANA\b", "DANA"),
    (r"\bGoPay\b", "GoPay"),
    (r"\bOVO\b", "OVO"),
    (r"\bShopeePay\b", "ShopeePay"),
    (r"\bLinkAja\b", "LinkAja"),
    (r"\bFlip\b", "Flip"),
    (r"\bQRIS\b", "QRIS"),
]

STATUS_KEYWORDS = ["berhasil", "sukses", "success", "terkirim", "berhasil ditransfer", "pembayaran berhasil"]


def _clean_amount_to_num(val_str: str) -> float | None:
    if not val_str:
        return None
    # Strip Rp, IDR, spaces
    clean = re.sub(r"[^\d.,]", "", val_str).strip()
    if not clean:
        return None
    # Indonesian format: 37.400,00 or 37.400
    if "," in clean and "." in clean:
        clean = clean.replace(".", "").replace(",", ".")
    elif "." in clean:
        parts = clean.split(".")
        if len(parts) > 1 and len(parts[-1]) == 3:
            clean = clean.replace(".", "")
        else:
            clean = clean.replace(".", "")
    elif "," in clean:
        parts = clean.split(",")
        if len(parts) > 1 and len(parts[-1]) == 3:
            clean = clean.replace(",", "")
        else:
            clean = clean.replace(",", ".")
    try:
        return float(clean)
    except ValueError:
        return None


def parse_receipt_data(ocr_lines: list[dict]) -> dict[str, Any]:
    """Extract structured transaction fields and check internal arithmetic consistency."""
    if not ocr_lines:
        return {
            "status": "no_ocr_data",
            "is_receipt": False,
            "bank": None,
            "transaction_status": None,
            "amounts": {},
            "ref_id": None,
            "date_time": None,
            "recipient": None,
            "sender": None,
            "internal_consistency": {
                "checked": False,
                "is_consistent": True,
                "reason": "Data OCR tidak tersedia untuk verifikasi konsistensi.",
            },
        }

    raw_texts = [str(line.get("text", "")).strip() for line in ocr_lines if line.get("text")]
    full_text = " \n ".join(raw_texts)

    # 1. Bank / Provider
    bank = None
    for pattern, name in BANK_PATTERNS:
        if re.search(pattern, full_text, re.I):
            bank = name
            break

    # 2. Transaction Status
    tx_status = None
    for line in raw_texts:
        if any(kw in line.lower() for kw in STATUS_KEYWORDS):
            tx_status = line
            break

    # 3. Ref ID
    ref_id = None
    for line in raw_texts:
        m = re.search(
            r"(?:Ref\s*(?:ID|No\.?)|No\.\s*Referensi|Transaction\s*ID|RRN|Kode\s*RRN)[:\s]*([A-Za-z0-9]+)",
            line,
            re.I,
        )
        if m:
            ref_id = m.group(1)
            break

    # 4. Date / Time
    date_str = None
    for line in raw_texts:
        if re.search(r"\b(202[0-9])\b", line) and re.search(
            r"(?:jan|feb|mar|apr|mei|jun|jul|agu|sep|okt|nov|des|wib|wita|wit|\:)", line, re.I
        ):
            date_str = line
            break

    # 5. Recipient & Sender
    recipient = None
    sender = None
    for i, line in enumerate(raw_texts):
        if re.search(r"^penerima\b", line, re.I) and i + 1 < len(raw_texts):
            rec_line = raw_texts[i + 1]
            if i + 2 < len(raw_texts) and not any(
                k in raw_texts[i + 2].lower() for k in ["sumber", "rekening", "detail", "nominal", "total"]
            ):
                rec_line += " " + raw_texts[i + 2]
            recipient = rec_line
        if re.search(r"sumber\s*dana|pengirim\b", line, re.I) and i + 1 < len(raw_texts):
            sender = raw_texts[i + 1]

    # 6. Amounts (Header, Nominal, Total, Admin Fee)
    amounts: dict[str, Any] = {}
    for i, line in enumerate(raw_texts):
        # Header amount: usually top lines (line 1-4) with clear currency prefix
        if i in (1, 2, 3, 4) and re.match(r"^(?:Rp|IDR)\s*[0-9.,]+", line, re.I) and "header" not in amounts:
            amounts["header"] = line
        elif re.search(r"^nominal\b", line, re.I):
            m = re.search(r"(?:Rp|IDR)?\s*[0-9.,]+", line, re.I)
            if m and any(char.isdigit() for char in m.group(0)):
                amounts["nominal"] = m.group(0).strip()
            elif i + 1 < len(raw_texts):
                amounts["nominal"] = raw_texts[i + 1]
        elif re.search(r"^total\b", line, re.I):
            m = re.search(r"(?:Rp|IDR)?\s*[0-9.,]+", line, re.I)
            if m and any(char.isdigit() for char in m.group(0)):
                amounts["total"] = m.group(0).strip()
            elif i + 1 < len(raw_texts):
                amounts["total"] = raw_texts[i + 1]
        elif re.search(r"biaya\s*admin|biaya\s*transaksi|fee\b", line, re.I):
            m = re.search(r"(?:Rp|IDR)?\s*[0-9.,]+", line, re.I)
            if m and any(char.isdigit() for char in m.group(0)):
                amounts["admin_fee"] = m.group(0).strip()
            elif i + 1 < len(raw_texts):
                amounts["admin_fee"] = raw_texts[i + 1]

    # Parse numeric amounts
    parsed_nums: dict[str, float] = {}
    for k, v in list(amounts.items()):
        num = _clean_amount_to_num(v)
        if num is not None:
            parsed_nums[k] = num

    # 7. Internal Consistency Check
    is_consistent = True
    inconsistency_reason = "Nominal dan rincian transaksi konsisten secara internal."
    checked = False

    header_num = parsed_nums.get("header")
    nominal_num = parsed_nums.get("nominal")
    total_num = parsed_nums.get("total")
    fee_num = parsed_nums.get("admin_fee", 0.0)

    if header_num is not None and nominal_num is not None:
        checked = True
        # If header differs from nominal and does not match total
        if abs(header_num - nominal_num) > 0.01:
            if total_num is not None and abs(header_num - total_num) < 0.01:
                # Header matches total (e.g. nominal + fee = total == header)
                is_consistent = True
            else:
                is_consistent = False
                inconsistency_reason = (
                    f"Nominal header ({amounts.get('header')}) tidak sesuai dengan rincian nominal ({amounts.get('nominal')})."
                )

    if is_consistent and nominal_num is not None and total_num is not None:
        checked = True
        expected_total = nominal_num + fee_num
        if abs(expected_total - total_num) > 0.01:
            is_consistent = False
            inconsistency_reason = (
                f"Perhitungan total tidak sesuai: Nominal ({amounts.get('nominal')}) + "
                f"Biaya ({amounts.get('admin_fee', '0')}) != Total ({amounts.get('total')})."
            )

    is_receipt = bool(bank or tx_status or ref_id or amounts)

    return {
        "status": "completed",
        "is_receipt": is_receipt,
        "bank": bank or "Tidak teridentifikasi otomatis",
        "transaction_status": tx_status or "Tidak terdeteksi",
        "amounts": amounts,
        "amounts_numeric": parsed_nums,
        "ref_id": ref_id or "Tidak terdeteksi",
        "date_time": date_str or "Tidak terdeteksi",
        "recipient": recipient or "Tidak terdeteksi",
        "sender": sender or "Tidak terdeteksi",
        "internal_consistency": {
            "checked": checked,
            "is_consistent": is_consistent,
            "reason": inconsistency_reason,
        },
    }

