#!/usr/bin/env python

import asyncio
import json
import os
import platform
import sqlite3
import sys
from pathlib import Path
from typing import Any, Dict, List, Optional, Union

from fastapi import FastAPI  # type: ignore
from loguru import logger  # Added
from pydantic import BaseModel

from fastmcp import FastMCP, ToolContext

# Ensure src directory is in Python path
# This assumes mcp_server.py is in the root of the cursor-chat-export project
sys.path.append(str(Path(__file__).parent / "src"))
try:
    from vscdb import VSCDBQuery
    from chat import get_cursor_workspace_path
except ImportError as e:
    print(f"Error importing VSCDBQuery or get_cursor_workspace_path: {e}")
    print("Ensure that src/vscdb.py and chat.py are accessible and in the PYTHONPATH.")
    sys.exit(1)

# Initialize Loguru logger
logger.remove()  # Remove default handler
logger.add(sys.stderr, level="DEBUG")  # Add new handler to stderr with DEBUG level

mcp_server_app = FastMCP(
    title="Cursor Chat Exporter MCP Server",
    description="MCP Server for discovering, listing, and exporting Cursor chat sessions from SQLite databases.",
    version="0.1.0",
)


# --- Helper Functions (Consider moving to a utils.py if they grow) ---
def get_db_path(db_identifier: str, base_path_str: Optional[str] = None) -> Path:
    """
    Constructs the full path to a state.vscdb file given a db_identifier (parent directory name)
    and an optional base_path_str.
    """
    logger.debug(
        f"Getting DB path for identifier: {db_identifier}, base_path: {base_path_str}"
    )
    if base_path_str:
        base_path = Path(base_path_str)
    else:
        # Fallback to the data directory within the project if no explicit base_path
        # This is useful if databases have been copied into the project's data/ folder
        project_root = Path(__file__).parent
        base_path = project_root / "data"
        if (
            not base_path.exists()
        ):  # If data dir doesn't exist, try Cursor's default workspaceStorage
            try:
                base_path = Path(get_cursor_workspace_path(use_config_file=True))
            except Exception as e:
                logger.error(f"Failed to get default Cursor workspace path: {e}")
                # As a last resort, use a placeholder or raise an error appropriately
                # For now, let's assume 'data/' should exist or be created if using this fallback logic
                # Or, indicate that the path resolution failed.
                # This part needs robust handling depending on expected use cases.
                # Defaulting to project_root / "data" as initially intended for copied DBs
                base_path = project_root / "data"

    db_file_path = base_path / db_identifier / "state.vscdb"
    logger.info(f"Constructed DB file path: {db_file_path}")
    return db_file_path


# --- MCP Tools ---


@mcp_server_app.tool()
async def discover_databases(
    ctx: ToolContext, base_path_str: Optional[str] = None
) -> List[str]:
    """
    Discovers all state.vscdb database files and returns their parent directory names as identifiers.
    Args:
        base_path_str: Optional path to search in. Defaults to standard Cursor workspace storage
                       or the project's 'data/' directory if databases are copied there.
    Returns:
        A list of database identifiers (parent directory names).
    """
    logger.info(f"Discovering databases in base path: {base_path_str}")
    if base_path_str:
        search_path = Path(base_path_str)
    else:
        # Default to project's data directory first
        project_data_path = Path(__file__).parent / "data"
        if project_data_path.exists() and any(project_data_path.iterdir()):
            search_path = project_data_path
            logger.debug(f"Using project data directory: {search_path}")
        else:
            try:
                search_path = Path(get_cursor_workspace_path(use_config_file=True))
                logger.debug(f"Using Cursor workspace path from config: {search_path}")
            except Exception as e:
                logger.error(
                    f"Failed to get configured Cursor workspace path: {e}. Trying project's data/ directory."
                )
                # Fallback to project data path even if empty, discover will return empty list
                search_path = Path(__file__).parent / "data"

    if not search_path.exists():
        logger.warning(f"Search path {search_path} does not exist.")
        return []

    db_identifiers: List[str] = []
    # Look for state.vscdb in immediate subdirectories of search_path
    # This matches the structure like /workspaceStorage/<identifier>/state.vscdb
    # or /data/<identifier>/state.vscdb
    for item in search_path.iterdir():
        if item.is_dir():
            if (item / "state.vscdb").exists():
                db_identifiers.append(item.name)
                logger.debug(f"Found database in directory: {item.name}")

    if not db_identifiers:
        logger.info(
            f"No databases found in {search_path} or its direct subdirectories."
        )
    else:
        logger.success(f"Discovered databases: {db_identifiers}")
    return db_identifiers


@mcp_server_app.tool()
async def list_sessions(ctx: ToolContext, db_identifier: str) -> List[Dict[str, Any]]:
    """
    Lists all chat session metadata from a specified database identifier.
    Args:
        db_identifier: The identifier (parent directory name) of the database.
    Returns:
        A list of session metadata dictionaries.
    """
    logger.info(f"Listing sessions for database identifier: {db_identifier}")
    db_file_path = get_db_path(db_identifier)

    if not db_file_path.exists():
        logger.error(f"Database file not found: {db_file_path}")
        return [{"error": "Database file not found", "path": str(db_file_path)}]

    try:
        query_instance = VSCDBQuery(
            str(db_file_path.parent)
        )  # VSCDBQuery expects the directory
        sessions_metadata = query_instance.get_all_chat_sessions_metadata()
        if not sessions_metadata:
            logger.info(f"No session metadata found in {db_file_path}")
            return []
        logger.success(
            f"Successfully listed {len(sessions_metadata)} sessions from {db_identifier}"
        )
        return sessions_metadata
    except Exception as e:
        logger.error(f"Error listing sessions from {db_identifier}: {e}")
        return [{"error": str(e)}]


@mcp_server_app.tool()
async def export_chat_session(
    ctx: ToolContext, db_identifier: str, session_id: str
) -> Dict[str, Any]:
    """
    Exports a single chat session's data (including turns).
    Args:
        db_identifier: The identifier (parent directory name) of the database.
        session_id: The composerId of the session to export.
    Returns:
        A dictionary containing the session data, or None if not found/error.
    """
    logger.info(
        f"Exporting session_id: {session_id} from db_identifier: {db_identifier}"
    )
    db_file_path = get_db_path(db_identifier)

    if not db_file_path.exists():
        logger.error(f"Database file not found for export: {db_file_path}")
        return {"error": "Database file not found", "path": str(db_file_path)}

    try:
        query_instance = VSCDBQuery(
            str(db_file_path.parent)
        )  # VSCDBQuery expects the directory

        # Get all data (metadata, prompts, generations)
        all_data = query_instance.query_all_chat_data()

        # Find the specific session by session_id from the composer_data part
        target_session_metadata = None
        if all_data.get("composer_data"):
            for session_meta in all_data["composer_data"].get("allComposers", []):
                if session_meta.get("composerId") == session_id:
                    target_session_metadata = session_meta
                    break

        if not target_session_metadata:
            logger.warning(
                f"Session ID {session_id} not found in metadata of {db_identifier}."
            )
            return {"error": f"Session ID {session_id} not found in composer metadata."}

        # Reconstruct turns for this specific session
        # The logic in VSCDBQuery.query_all_chat_data already correlates prompts and generations
        # and stores them under 'turns_reconstructed' for each session if the heuristic is applied.
        # Here we need to find the reconstructed session.

        reconstructed_session_with_turns = None
        for session_details in all_data.get("sessions_with_reconstructed_turns", []):
            if session_details.get("metadata", {}).get("composerId") == session_id:
                reconstructed_session_with_turns = session_details
                break

        if reconstructed_session_with_turns:
            logger.success(
                f"Successfully exported session {session_id} from {db_identifier}"
            )
            return reconstructed_session_with_turns
        else:
            # Fallback if turns were not reconstructed or session not found in reconstructed list.
            # This might happen if the heuristic in query_all_chat_data didn't match,
            # or if the session had no prompts/generations.
            # Return just the metadata in this case.
            logger.warning(
                f"Could not find reconstructed turns for session {session_id} in {db_identifier}. Returning metadata only."
            )
            return {
                "metadata": target_session_metadata,
                "turns": [],
                "warning": "Turns could not be reconstructed or were not found.",
            }

    except Exception as e:
        logger.error(f"Error exporting session {session_id} from {db_identifier}: {e}")
        return {"error": str(e)}


# Example of how to run if you were running this file directly (for testing)
if __name__ == "__main__":
    # This part is for direct execution testing, not for when Cursor runs it.
    # Cursor will use the `command` specified in mcp.json.
    logger.info("Starting FastMCP server for Cursor Chat Exporter...")
    # Note: When FastMCP is run like this for stdio, it typically expects
    # to communicate over stdin/stdout. For local testing of the FastAPI app
    # over HTTP (e.g., for web browser or curl), you'd run it with uvicorn.
    # e.g.: uvicorn mcp_server:mcp_server_app --reload --port 8000
    # However, for Cursor's stdio transport, direct execution might not behave as expected
    # without a proper MCP client sending messages.

    # The FastMCP constructor itself doesn't run the server for stdio.
    # The server loop (mcp_server_app.run_stdio() or similar) is handled by FastMCP's
    # own mechanisms when launched as a command by an MCP client (like Cursor).
    # For simple direct run test:
    print(
        "MCP Server defined. To run for HTTP testing: uvicorn mcp_server:mcp_server_app --reload"
    )
    print("Cursor will launch this via 'command' using stdio.")
    # To simulate a basic stdio run if FastMCP supported an easy direct call:
    # asyncio.run(mcp_server_app.run_stdio()) # This is hypothetical
    # For now, just confirm it can be imported and FastMCP object created.
    logger.info("FastMCP server object created. Ready to be launched by an MCP client.")
