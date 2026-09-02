import argparse
from pathlib import Path
import sys

# Ensure project root is in sys.path
PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from cloud.database import DatabaseManager


def main():
    parser = argparse.ArgumentParser(description="Reset Smart Grid Experiment Database")
    parser.add_argument("--all", action="store_true", help="Clear all database tables")
    parser.add_argument("--exp-id", type=str, default=None, help="Clear specific experiment ID")
    args = parser.parse_args()

    db = DatabaseManager()
    if args.exp_id:
        db.clear_experiment(args.exp_id)
        print(f"[RESET] Cleared experiment {args.exp_id} successfully.")
    else:
        db.reset_all_data()
        print("[RESET] All database tables cleared while preserving schema.")


if __name__ == "__main__":
    main()
