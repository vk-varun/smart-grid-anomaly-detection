import argparse
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
