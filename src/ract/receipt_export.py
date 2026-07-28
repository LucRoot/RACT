import json
import sys
from pathlib import Path
from typing import List, Dict, Any


def _to_markdown(receipts: List[Dict[str, Any]]) -> str:
    """Render a list of receipts as a Markdown table."""
    if not receipts:
        return "# Receipt Export\n\nNo receipts found.\n"
    headers = ["run_id", "plan_hash", "diff_hash"]
    lines = ["# Receipt Export", ""]
    lines.append("| " + " | ".join(headers) + " |")
    lines.append("| " + " | ".join("---" for _ in headers) + " |")
    for r in receipts:
        values = [str(r.get(h, "")) for h in headers]
        lines.append("| " + " | ".join(values) + " |")
    return "\n".join(lines) + "\n"


def export_receipts(directory: str, anonymize: bool = True, fmt: str = "json") -> Any:
    """Read *.receipt.json files from directory and return anonymized list.

    fmt: 'json' returns a list of dicts; 'markdown' returns a Markdown string.
    """
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

    if fmt == "markdown":
        return _to_markdown(receipts)
    return receipts


def _anonymize(receipt: Dict[str, Any]) -> Dict[str, Any]:
    """Remove signer_id and signature, keep run_id and metrics."""
    sanitized = {
        k: v for k, v in receipt.items() if k not in ("signer_id", "signature")
    }
    return sanitized


def main(argv: List[str]) -> None:
    """CLI entry point for receipt export."""
    directory = None
    anonymize = True
    fmt = "json"

    args = argv[1:]
    i = 0
    while i < len(args):
        if args[i] == "--anonymize":
            anonymize = True
        elif args[i] == "--directory":
            if i + 1 < len(args):
                directory = args[i + 1]
                i += 1
        elif args[i] == "--markdown":
            fmt = "markdown"
        i += 1

    if not directory:
        print("Error: --directory is required", file=sys.stderr)
        sys.exit(1)

    try:
        result = export_receipts(directory, anonymize, fmt=fmt)
        if fmt == "markdown":
            print(result)
        else:
            print(json.dumps(result, indent=2))
    except FileNotFoundError as e:
        print(f"Error: {e}", file=sys.stderr)
        sys.exit(1)
