import os
import sqlite3
import yaml
import json
from typing import Any, Dict, List, Optional
from loguru import logger
from pathlib import Path
from datetime import datetime

# Path to the configuration file
CONFIG_PATH = Path(__file__).resolve().parent.parent / "config.yml"


class VSCDBQuery:
    def __init__(self, db_path: str) -> None:
        """
        Initialize the VSCDBQuery with the path to the SQLite database.

        Args:
            db_path (str): The path to the SQLite database file.
        """
        self.db_path = db_path
        self.config = self._load_config()
        self.table_name = self.config.get("table_name", "ItemTable")
        self.conn = None
        self.cursor = None
        self._initialize_connection()
        logger.info(f"Database path for VSCDBQuery instance: {self.db_path}")

    def _load_config(self):
        """Loads the configuration from the YAML file."""
        try:
            with open(CONFIG_PATH, "r") as f:
                config_data = yaml.safe_load(f)
                # Fallback for keys if not found in config
                return {
                    "aichat_query_key": config_data.get(
                        "aichat_query_key", "composer.composerData"
                    ),
                    "prompts_key": config_data.get("prompts_key", "aiService.prompts"),
                    "generations_key": config_data.get(
                        "generations_key", "aiService.generations"
                    ),
                    "table_name": config_data.get("table_name", "ItemTable"),
                }
        except FileNotFoundError:
            logger.error(f"Configuration file not found at {CONFIG_PATH}")
            return {  # Default values if config file is missing
                "aichat_query_key": "composer.composerData",
                "prompts_key": "aiService.prompts",
                "generations_key": "aiService.generations",
                "table_name": "ItemTable",
            }
        except yaml.YAMLError as e:
            logger.error(f"Error parsing YAML configuration: {e}")
            return {  # Default values on YAML error
                "aichat_query_key": "composer.composerData",
                "prompts_key": "aiService.prompts",
                "generations_key": "aiService.generations",
                "table_name": "ItemTable",
            }
        except Exception as e:
            logger.error(f"Unexpected error loading config: {e}")
            return {  # Default values on general error
                "aichat_query_key": "composer.composerData",
                "prompts_key": "aiService.prompts",
                "generations_key": "aiService.generations",
                "table_name": "ItemTable",
            }

    def _initialize_connection(self):
        """Initializes the database connection and cursor in read-only mode."""
        try:
            # Connect in read-only mode as we are only querying
            self.conn = sqlite3.connect(f"file:{self.db_path}?mode=ro", uri=True)
            self.cursor = self.conn.cursor()
            logger.debug(f"Database connection initialized for {self.db_path}")
        except sqlite3.Error as e:
            logger.error(
                f"Failed to initialize database connection for {self.db_path}: {e}"
            )
            self.conn = None
            self.cursor = None
        except Exception as e:
            logger.error(
                f"Unexpected error initializing database connection for {self.db_path}: {e}"
            )
            self.conn = None
            self.cursor = None

    def close_connection(self):
        """Closes the database connection if it is open."""
        if self.conn:
            try:
                self.conn.close()
                logger.debug(f"Database connection closed for {self.db_path}")
            except sqlite3.Error as e:
                logger.error(
                    f"Error closing database connection for {self.db_path}: {e}"
                )
        self.conn = None
        self.cursor = None

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        self.close_connection()

    def _execute_query(self, query, params=None):
        """Executes a given SQL query and returns the fetched rows."""
        if not self.conn or not self.cursor:
            logger.error("Database connection not initialized or already closed.")
            # Attempt to re-initialize if called after explicit close or if initial init failed
            self._initialize_connection()
            if not self.conn or not self.cursor:  # Still not connected
                return {"error": "DB connection failed to re-initialize"}

        log_params = params
        if (
            params
            and isinstance(params[0], str)
            and "workbench.panel.composerChatViewPane" in params[0]
        ):
            logger.debug(
                f"Executing query: '{query}' with sensitive-like params: ('{params[0]}',)"
            )
        else:
            logger.debug(f"Executing query: '{query}' with params: {log_params}")

        try:
            self.cursor.execute(query, params if params else ())
            rows = self.cursor.fetchall()
            logger.success(
                f"Query '{query}' executed, fetched {len(rows)} rows for params: {log_params}"
            )
            if rows:
                return rows[0]
            return None
        except sqlite3.OperationalError as e:
            if "unable to open database file" in str(e) or "no such table" in str(e):
                logger.error(
                    f"SQLite operational error for {self.db_path}: {e}. DB might be missing, corrupt, or not a valid SQLite file."
                )
            else:
                logger.error(f"SQLite operational error for {self.db_path}: {e}")
            return {"error": str(e), "db_path": str(self.db_path)}
        except sqlite3.Error as e:
            logger.error(f"SQLite error for {self.db_path}: {e}")
            return {"error": str(e), "db_path": str(self.db_path)}
        except Exception as e:
            logger.error(
                f"Unexpected error during query execution for {self.db_path}: {e}"
            )
            return {
                "error": f"Unexpected query error: {str(e)}",
                "db_path": str(self.db_path),
            }

    def get_json_value_for_key(self, key_name):
        """Fetches and parses a JSON value from the ItemTable for a given key."""
        if not self.conn or not self.cursor:
            logger.warning(
                "Attempting to use get_json_value_for_key with no active DB connection. Attempting to re-initialize."
            )
            self._initialize_connection()
            if not self.conn or not self.cursor:  # Still no connection
                return {
                    "error": "Failed to initialize DB connection for get_json_value_for_key",
                    "key_name": key_name,
                }

        logger.debug(
            f"get_json_value_for_key received key_name: '{key_name}' (len: {len(key_name)})"
        )

        query = f"SELECT value FROM {self.table_name} WHERE [key] = ?"
        query_params = (key_name,)
        result_row = self._execute_query(query, query_params)

        if (
            isinstance(result_row, dict) and "error" in result_row
        ):  # Error from _execute_query
            return result_row  # Propagate error

        if result_row and result_row[0] is not None:
            try:
                value_blob = result_row[0]
                if isinstance(value_blob, bytes):
                    value_str = value_blob.decode("utf-8")
                elif isinstance(value_blob, str):
                    value_str = value_blob  # Already a string, use as is
                else:
                    # Should not happen based on SQLite behavior, but good to log
                    logger.error(
                        f"Unexpected type for value_blob for key '{key_name}': {type(value_blob)}. Value: {str(value_blob)[:100]}..."
                    )
                    return {
                        "error": "UnexpectedValueType",
                        "details": f"Expected bytes or str, got {type(value_blob)}",
                        "key_name": key_name,
                    }
                return json.loads(value_str)
            except json.JSONDecodeError as e:
                logger.error(
                    f"JSONDecodeError for key '{key_name}': {e}. Value (raw bytes prefix): {value_blob[:100] if isinstance(value_blob, bytes) else 'Not bytes'}"
                )
                return {
                    "error": "JSONDecodeError",
                    "details": str(e),
                    "key_name": key_name,
                }
            except UnicodeDecodeError as e:
                logger.error(
                    f"UnicodeDecodeError for key '{key_name}': {e}. Value (raw bytes prefix): {value_blob[:100] if isinstance(value_blob, bytes) else 'Not bytes'}"
                )
                return {
                    "error": "UnicodeDecodeError",
                    "details": str(e),
                    "key_name": key_name,
                }
            except Exception as e:
                logger.error(
                    f"Unexpected error processing value for key '{key_name}': {e}. Value (raw bytes prefix): {value_blob[:100] if isinstance(value_blob, bytes) else 'Not bytes'}"
                )
                return {
                    "error": "ValueProcessingError",
                    "details": str(e),
                    "key_name": key_name,
                }
        else:
            logger.warning(
                f"No item found with key '{key_name}' in {self.db_path} using table {self.table_name}."
            )
            return None

    def get_all_chat_sessions_metadata(self):
        """
        Fetches metadata for all chat sessions (composers).
        Returns a list of dicts, each with 'composerId' and 'name', or an error dict.
        """
        if not self.conn or not self.cursor:
            logger.error("Cannot get chat sessions metadata: DB connection not active.")
            return {"error": "DB connection not active for metadata retrieval"}

        metadata_key = self.config.get("aichat_query_key")
        if not metadata_key:
            logger.error(
                "Chat session metadata key (aichat_query_key) not found in config."
            )
            return {"error": "aichat_query_key missing in config"}

        logger.debug(f"Fetching chat session metadata using key: {metadata_key}")
        composer_data_json = self.get_json_value_for_key(metadata_key)

        if not composer_data_json or (
            isinstance(composer_data_json, dict) and "error" in composer_data_json
        ):
            logger.error(
                f"Failed to retrieve or parse composer metadata from {self.db_path} using key {metadata_key}. Error: {composer_data_json.get('error', 'Unknown') if isinstance(composer_data_json, dict) else 'No data'}"
            )
            return composer_data_json

        try:
            sessions = []
            for composer in composer_data_json.get("allComposers", []):
                if composer.get("composerId") and composer.get("name"):
                    sessions.append(
                        {
                            "composerId": composer["composerId"],
                            "name": composer["name"],
                            "lastUpdatedAt": composer.get("lastUpdatedAt"),
                            "createdAt": composer.get("createdAt"),
                        }
                    )
            logger.info(
                f"Found {len(sessions)} chat session metadata entries in {self.db_path}."
            )
            return sessions
        except TypeError as e:
            logger.error(
                f"Unexpected structure in composer metadata for {self.db_path}: {e}. Data: {str(composer_data_json)[:200]}..."
            )
            return {
                "error": f"Unexpected composer metadata structure: {e}",
                "db_path": str(self.db_path),
            }
        except Exception as e:
            logger.error(
                f"Error parsing allComposers from metadata for {self.db_path}: {e}. Data: {str(composer_data_json)[:200]}..."
            )
            return {
                "error": f"Error parsing allComposers from metadata: {e}",
                "db_path": str(self.db_path),
            }

    def get_all_prompts_raw(self) -> Optional[List[Dict[str, Any]]]:
        """Retrieves all raw prompts from aiService.prompts."""
        prompts_key = self.config.get("prompts_key", "aiService.prompts")
        logger.info(f"Fetching all prompts using key: {prompts_key}")
        prompts_json = self.get_json_value_for_key(prompts_key)

        if prompts_json is None:
            logger.warning(f"No prompts data found for key {prompts_key}.")
            return None
        if isinstance(prompts_json, dict) and "error" in prompts_json:
            logger.error(f"Error fetching prompts: {prompts_json['error']}")
            return None
        if isinstance(prompts_json, list):
            logger.success(f"Successfully fetched {len(prompts_json)} raw prompts.")
            return prompts_json
        else:
            logger.warning(
                f"Prompts data for key {prompts_key} is not a list. Found: {type(prompts_json)}"
            )
            return None

    def get_all_generations_raw(self) -> Optional[List[Dict[str, Any]]]:
        """Retrieves all raw generations from aiService.generations."""
        generations_key = self.config.get("generations_key", "aiService.generations")
        logger.info(f"Fetching all generations using key: {generations_key}")
        generations_json = self.get_json_value_for_key(generations_key)

        if generations_json is None:
            logger.warning(f"No generations data found for key {generations_key}.")
            return None
        if isinstance(generations_json, dict) and "error" in generations_json:
            logger.error(f"Error fetching generations: {generations_json['error']}")
            return None
        if isinstance(generations_json, list):
            logger.success(
                f"Successfully fetched {len(generations_json)} raw generations."
            )
            return generations_json
        else:
            logger.warning(
                f"Generations data for key {generations_key} is not a list. Found: {type(generations_json)}"
            )
            return None

    def query_all_chat_data(self):
        """
        Orchestrates fetching all chat data.
        Ensures connection is managed (opened and closed) if not used as context manager.
        """
        opened_connection_locally = False
        if not self.conn or not self.cursor:
            logger.debug("Connection not active in query_all_chat_data, initializing.")
            self._initialize_connection()
            if not self.conn:  # Failed to initialize
                return [
                    {
                        "error": f"Failed to initialize DB connection for {self.db_path}",
                        "db_path": str(self.db_path),
                    }
                ]
            opened_connection_locally = True

        logger.info(f"Starting to query all chat data from {self.db_path}")
        all_sessions_metadata = self.get_all_chat_sessions_metadata()

        if isinstance(all_sessions_metadata, dict) and "error" in all_sessions_metadata:
            logger.error(
                f"Failed to get chat session metadata from {self.db_path}. Error: {all_sessions_metadata['error']}"
            )
            if opened_connection_locally:
                self.close_connection()
            return [
                {
                    "error": f"Metadata fetch failed: {all_sessions_metadata['error']}",
                    "db_path": str(self.db_path),
                }
            ]

        if not all_sessions_metadata:
            logger.info(f"No chat sessions found in {self.db_path} based on metadata.")
            if opened_connection_locally:
                self.close_connection()
            return []

        processed_chats = []
        for session_meta in all_sessions_metadata:
            composer_id = session_meta["composerId"]
            session_details = self.get_chat_session_details(composer_id)

            chat_entry = {
                "composerId": composer_id,
                "name": session_meta["name"],
                "lastUpdatedAt": session_meta.get("lastUpdatedAt"),
                "createdAt": session_meta.get("createdAt"),
                "db_path": str(self.db_path),
                "session_data": None,
                "error": None,
            }

            if isinstance(session_details, dict) and "error" in session_details:
                chat_entry["error"] = (
                    f"Failed to get session details: {session_details['error']}"
                )
                logger.warning(
                    f"Error fetching details for session {composer_id} from {self.db_path}: {session_details['error']}"
                )
            elif (
                session_details is None
            ):  # Explicitly no data found for this session key
                chat_entry["error"] = "No chat session data found for this composerId."
                logger.warning(
                    f"No chat session data found for composerId {composer_id} in {self.db_path} using key workbench.panel.composerChatViewPane.{composer_id}"
                )
            else:  # Successfully fetched session_details
                chat_entry["session_data"] = session_details

            processed_chats.append(chat_entry)

        logger.info(
            f"Finished processing {len(processed_chats)} chat sessions from {self.db_path}."
        )

        if opened_connection_locally:
            self.close_connection()
        return processed_chats


# Example usage (optional, for testing)
if __name__ == "__main__":
    # This example assumes you have a database at the specified path
    # and config.yml is correctly set up in the parent directory.
    # Replace with an actual path to one of your .vscdb files.
    example_db_path = (
        Path.home()
        / "Library/Application Support/Cursor/User/workspaceStorage/your_workspace_id_here/state.vscdb"
    )

    # Check if the example path is just a placeholder
    if "your_workspace_id_here" in str(example_db_path):
        print(
            "Please replace 'your_workspace_id_here' with an actual workspace ID in the example_db_path variable to run this example."
        )
    else:
        if example_db_path.exists():
            query_tool = VSCDBQuery(example_db_path)
            all_data = query_tool.query_all_chat_data()

            if all_data:
                print(f"Found data for {len(all_data)} sessions/entries.")
                for i, chat_info in enumerate(all_data):
                    print(f"--- Chat Session {i + 1} ---")
                    print(f"  Name: {chat_info.get('name')}")
                    print(f"  Composer ID: {chat_info.get('composerId')}")
                    print(f"  DB Path: {chat_info.get('db_path')}")
                    if chat_info.get("error"):
                        print(f"  Error: {chat_info.get('error')}")
                    elif (
                        chat_info.get("session_data")
                        and "turns" in chat_info["session_data"]
                    ):
                        turns = chat_info["session_data"]["turns"]
                        print(f"  Number of turns: {len(turns)}")
                        if turns:
                            print(
                                f"    First turn request: {turns[0].get('request')[:100]}..."
                            )  # Print first 100 chars
                    else:
                        print("  No session data or turns found.")
            else:
                print(f"No chat data retrieved from {example_db_path}.")

        else:
            print(f"Example database path not found: {example_db_path}")
