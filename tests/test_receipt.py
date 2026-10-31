import pytest
from verifile.receipt import parse_receipt_data, _clean_amount_to_num


def test_clean_amount_to_num():
    assert _clean_amount_to_num("Rp37.400") == 37400.0
    assert _clean_amount_to_num("Rp 1.250.000,00") == 1250000.0
    assert _clean_amount_to_num("IDR 50.000") == 50000.0
    assert _clean_amount_to_num("Rp60.000") == 60000.0
    assert _clean_amount_to_num("invalid") is None
    assert _clean_amount_to_num("") is None


def test_parse_clean_receipt():
    lines = [
        {"text": "wondr by BNI"},
        {"text": "Pembayaran QRIS berhasil"},
        {"text": "Rp37.400"},
        {"text": "30 Okt 2026 · 20:59:39 WIB"},
        {"text": "Ref ID: 202610300859170551"},
        {"text": "Penerima"},
        {"text": "QRIS INDOMARET TANGERANG ID"},
        {"text": "Sumber dana"},
        {"text": "RAFFLY EKASYACH MAULANA"},
        {"text": "Detail pembayaran"},
        {"text": "Nominal"},
        {"text": "Rp37.400"},
        {"text": "Total"},
        {"text": "Rp37.400"},
    ]
    res = parse_receipt_data(lines)
    assert res["is_receipt"] is True
    assert res["bank"] == "wondr by BNI"
    assert "QRIS berhasil" in res["transaction_status"]
    assert res["ref_id"] == "202610300859170551"
    assert "INDOMARET" in res["recipient"]
    assert "RAFFLY" in res["sender"]
    assert res["internal_consistency"]["is_consistent"] is True


def test_parse_inconsistent_amount_receipt():
    lines = [
        {"text": "wondr by BNI"},
        {"text": "Pembayaran QRIS berhasil"},
        {"text": "Rp60.000"},  # Header manipulated to 60.000
        {"text": "Ref ID: 123456"},
        {"text": "Nominal"},
        {"text": "Rp37.400"},  # Detail nominal remained 37.400
        {"text": "Total"},
        {"text": "Rp37.400"},
    ]
    res = parse_receipt_data(lines)
    assert res["is_receipt"] is True
    assert res["internal_consistency"]["is_consistent"] is False
    assert "tidak sesuai" in res["internal_consistency"]["reason"]


def test_parse_receipt_with_admin_fee():
    lines = [
        {"text": "Bank BCA"},
        {"text": "Transfer Berhasil"},
        {"text": "Rp52.500"},
        {"text": "Nominal"},
        {"text": "Rp50.000"},
        {"text": "Biaya Admin"},
        {"text": "Rp2.500"},
        {"text": "Total"},
        {"text": "Rp52.500"},
    ]
    res = parse_receipt_data(lines)
    assert res["is_receipt"] is True
    assert res["bank"] == "Bank BCA"
    assert res["internal_consistency"]["is_consistent"] is True


def test_empty_lines():
    res = parse_receipt_data([])
    assert res["status"] == "no_ocr_data"
    assert res["is_receipt"] is False

