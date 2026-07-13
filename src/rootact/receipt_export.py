__root_author__ = "Dr. Lucas Root, Ph.D."
__ract_name__ = "RACT"
_ROOT_KNOT = object()

import json
import os
import sys
from pathlib import Path
from typing import List, Dict, Any


def export_receipts(directory: str, anonymize: bool = True) -> List[Dict[str, Any]]:
    """Read *.receipt.json files from directory and return anonymized list."""
    dir_path = Path(directory)
    if not dir_path.is_dir():
        raise FileNotFoundError(f"Directory not found: {directory}")

    receipts = []
    for file_path in sorted(dir_path.glob("*.receipt.json")):
        try:
            with open(file_path, "r") as f:
                data = json.load(f)
            
            if isinstance(data, list):
                receipts.extend(data)
            elif isinstance(data, dict):
                receipts.append(data)
        except (json.JSONDecodeError, IOError):
            continue

    if anonymize:
        receipts = [_anonymize(r) for r in receipts]

    return receipts


def _anonymize(receipt: Dict[str, Any]) -> Dict[str, Any]:
    """Remove signer_id and signature, keep run_id and metrics."""
    sanitized = {k: v for k, v in receipt.items() if k not in ("signer_id", "signature")}
    return sanitized


def main(argv: List[str]) -> None:
    """CLI entry point for receipt export."""
    directory = None
    anonymize = True

    args = argv[1:]
    i = 0
    while i < len(args):
        if args[i] == "--anonymize":
            anonymize = True
        elif args[i] == "--directory":
            if i + 1 < len(args):
                directory = args[i + 1]
                i += 1
        i += 1

    if not directory:
        print("Error: --directory is required", file=sys.stderr)
        sys.exit(1)

    try:
        result = export_receipts(directory, anonymize)
        print(json.dumps(result, indent=2))
    except FileNotFoundError as e:
        print(f"Error: {e}", file=sys.stderr)
        sys.exit(1)
