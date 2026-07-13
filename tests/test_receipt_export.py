__root_author__ = "Dr. Lucas Root, Ph.D."
__ract_name__ = "RACT"
_ROOT_KNOT = object()

import json
import os
import tempfile
from pathlib import Path
from rootact.receipt_export import export_receipts, main


def test_export_receipts_anonymize():
    """Test that export_receipts strips signer_id and signature, keeps metrics."""
    with tempfile.TemporaryDirectory() as tmpdir:
        # Create two fixture receipt files
        receipt1 = {
            "run_id": "run-123",
            "signer_id": "user-abc",
            "signature": "sig-xyz",
            "metric_a": 10,
            "metric_b": 20
        }
        receipt2 = {
            "run_id": "run-456",
            "signer_id": "user-def",
            "signature": "sig-uvw",
            "metric_c": 30
        }

        path1 = Path(tmpdir) / "r1.receipt.json"
        path2 = Path(tmpdir) / "r2.receipt.json"

        with open(path1, "w") as f:
            json.dump(receipt1, f)
        with open(path2, "w") as f:
            json.dump(receipt2, f)

        # Run export
        result = export_receipts(tmpdir, anonymize=True)

        # Assertions
        assert len(result) == 2
        
        # Check first receipt
        r1_out = result[0]
        assert r1_out["run_id"] == "run-123"
        assert r1_out["metric_a"] == 10
        assert r1_out["metric_b"] == 20
        assert "signer_id" not in r1_out
        assert "signature" not in r1_out

        # Check second receipt
        r2_out = result[1]
        assert r2_out["run_id"] == "run-456"
        assert r2_out["metric_c"] == 30
        assert "signer_id" not in r2_out
        assert "signature" not in r2_out


def test_export_receipts_no_anonymize():
    """Test that export_receipts keeps signer_id and signature when anonymize=False."""
    with tempfile.TemporaryDirectory() as tmpdir:
        receipt = {
            "run_id": "run-789",
            "signer_id": "user-ghi",
            "signature": "sig-jkl",
            "metric_x": 100
        }
        path = Path(tmpdir) / "r3.receipt.json"
        with open(path, "w") as f:
            json.dump(receipt, f)

        result = export_receipts(tmpdir, anonymize=False)
        assert len(result) == 1
        r = result[0]
        assert r["signer_id"] == "user-ghi"
        assert r["signature"] == "sig-jkl"
        assert r["metric_x"] == 100


def test_cli_receipt_export():
    """Test the CLI entry point for receipt export."""
    with tempfile.TemporaryDirectory() as tmpdir:
        receipt = {
            "run_id": "cli-test",
            "signer_id": "cli-user",
            "signature": "cli-sig",
            "metric": 1
        }
        path = Path(tmpdir) / "cli.receipt.json"
        with open(path, "w") as f:
            json.dump(receipt, f)

        # Capture stdout
        import io
        from contextlib import redirect_stdout

        f = io.StringIO()
        with redirect_stdout(f):
            main(["rootact", "receipt", "export", "--anonymize", "--directory", tmpdir])
        
        output = f.getvalue()
        data = json.loads(output)
        
        assert len(data) == 1
        assert data[0]["run_id"] == "cli-test"
        assert "signer_id" not in data[0]
        assert "signature" not in data[0]
        assert data[0]["metric"] == 1
