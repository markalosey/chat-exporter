import sqlite3
import argparse
import json


def list_keys(db_path, table_name):
    """Lists all keys from the specified table."""
    try:
        conn = sqlite3.connect(f"file:{db_path}?mode=ro", uri=True)
        cursor = conn.cursor()
        cursor.execute(f"SELECT key FROM {table_name}")
        rows = cursor.fetchall()
        conn.close()

        if not rows:
            print(f"No keys found in table '{table_name}'.")
            return

        print(f"Keys in table '{table_name}':")
        for row in rows:
            print(f"- {row[0]}")

    except sqlite3.Error as e:
        print(f"SQLite error: {e}")
    except Exception as e:
        print(f"An unexpected error occurred: {e}")


def get_value(db_path, table_name, key_name):
    """Fetches and prints the value for a specific key from a specific table."""
    try:
        conn = sqlite3.connect(f"file:{db_path}?mode=ro", uri=True)
        cursor = conn.cursor()
        cursor.execute(f"SELECT value FROM {table_name} WHERE key = ?", (key_name,))
        row = cursor.fetchone()
        conn.close()

        if row is None:
            print(f"No value found for key '{key_name}' in table '{table_name}'.")
            return

        value = row[0]
        print(f"Value for key '{key_name}' in table '{table_name}':")

        if isinstance(value, bytes):
            try:
                # Try to decode as UTF-8 and pretty-print if JSON
                decoded_value = value.decode("utf-8")
                try:
                    parsed_json = json.loads(decoded_value)
                    print(json.dumps(parsed_json, indent=2))
                except json.JSONDecodeError:
                    # Not JSON, print as plain text
                    print(decoded_value)
            except UnicodeDecodeError:
                # Not valid UTF-8, print as BLOB representation
                print(f"BLOB data (first 100 bytes): {value[:100]}")
                if len(value) > 100:
                    print("... (data truncated)")
        else:
            # Should typically be text if not bytes, but handle just in case
            print(value)

    except sqlite3.Error as e:
        print(f"SQLite error: {e}")
    except Exception as e:
        print(f"An unexpected error occurred: {e}")


def main():
    parser = argparse.ArgumentParser(description="Explore SQLite state.vscdb files.")
    parser.add_argument(
        "db_path",
        help="Path to the SQLite database file (e.g., data/workspace_id/state.vscdb)",
    )

    subparsers = parser.add_subparsers(
        dest="command", help="Command to execute", required=True
    )

    # Subparser for listing keys
    parser_list_keys = subparsers.add_parser(
        "list_keys", help="List all keys in a table."
    )
    parser_list_keys.add_argument(
        "table_name",
        choices=["ItemTable", "cursorDiskKV"],
        help="Name of the table to list keys from.",
    )

    # Subparser for getting a value
    parser_get_value = subparsers.add_parser(
        "get_value", help="Get the value for a specific key in a table."
    )
    parser_get_value.add_argument(
        "table_name", choices=["ItemTable", "cursorDiskKV"], help="Name of the table."
    )
    parser_get_value.add_argument(
        "key_name", help="Name of the key to fetch the value for."
    )

    args = parser.parse_args()

    if args.command == "list_keys":
        list_keys(args.db_path, args.table_name)
    elif args.command == "get_value":
        get_value(args.db_path, args.table_name, args.key_name)


if __name__ == "__main__":
    main()
