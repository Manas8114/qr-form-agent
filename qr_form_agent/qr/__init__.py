"""QR decoding package with multi-barcode detection and fallback preprocessors."""

from qr_form_agent.qr.decoder import QRItem, QRScanResult, decode_qr_codes

__all__ = ["QRItem", "QRScanResult", "decode_qr_codes"]
