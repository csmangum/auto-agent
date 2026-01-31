"""CLI entry point for the claim agent."""

import json
import sys
from pathlib import Path

# Ensure src is on path when run as script
if __name__ == "__main__" and str(Path(__file__).resolve().parent.parent) not in sys.path:
    sys.path.insert(0, str(Path(__file__).resolve().parent.parent))


def main() -> None:
    """Run the claim agent on a JSON claim file."""
    if len(sys.argv) < 2:
        print("Usage: python -m claim_agent.main <claim.json>", file=sys.stderr)
        print("   or: claim-agent <claim.json>", file=sys.stderr)
        sys.exit(1)

    path = Path(sys.argv[1])
    if not path.exists():
        print(f"Error: File not found: {path}", file=sys.stderr)
        sys.exit(1)

    try:
        with open(path, encoding="utf-8") as f:
            claim_data = json.load(f)
    except json.JSONDecodeError as e:
        print(f"Error: Invalid JSON in {path}: {e}", file=sys.stderr)
        sys.exit(1)

    from claim_agent.crews.main_crew import run_claim_workflow

    result = run_claim_workflow(claim_data)
    print(json.dumps(result, indent=2))


if __name__ == "__main__":
    main()
