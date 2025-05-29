#!/usr/bin/env python

import os
import typer
from src.vscdb import VSCDBQuery
from src.export import ChatExporter, MarkdownChatFormatter, MarkdownFileSaver
from rich.console import Console
from rich.markdown import Markdown
from loguru import logger
import json
import yaml
import platform
from pathlib import Path
from datetime import datetime

app = typer.Typer()
console = Console()


# Helper function to get the base workspace path
def get_cursor_workspace_path() -> Path | None:
    config_path = Path("config.yml")
    logger.debug(f"Looking for configuration file at: {config_path}")

    if not config_path.exists():
        logger.error(f"Configuration file not found: {config_path}")
        return None

    try:
        with open(config_path, "r") as f:
            config = yaml.safe_load(f)
    except yaml.YAMLError as e:
        logger.error(f"Error parsing YAML configuration: {e}")
        return None
    except Exception as e:
        logger.error(f"Unexpected error loading config: {e}")
        return None

    os_system = platform.system()
    if os_system == "Darwin":  # macOS
        default_path = Path.home() / config.get(
            "cursor_workspace_path_mac",
            "Library/Application Support/Cursor/User/workspaceStorage",
        )
    elif os_system == "Linux":
        default_path = Path.home() / config.get(
            "cursor_workspace_path_linux", ".config/Cursor/User/workspaceStorage"
        )
    # Add Windows path if needed, or other OS
    else:
        logger.error(f"Unsupported operating system: {os_system}")
        return None

    logger.info(f"Default Cursor workspace path for {os_system}: {default_path}")
    return default_path


# Helper function for discovery from a single DB
def discover_from_db(db_file_path: Path, console: Console, config: dict) -> int:
    discovered_chats_count = 0
    db_identifier = db_file_path.parent.name  # Use parent folder name as DB identifier

    logger.info(f"Processing database: {db_file_path}")
    with VSCDBQuery(str(db_file_path)) as vsc_db:
        chat_sessions = vsc_db.query_all_chat_data()  # New method

        if not chat_sessions:
            logger.warning(f"No chat data found in {db_file_path}")
            console.print(f"[orange3]No chat data found in {db_file_path}[/orange3]")
            return 0

        console.print(
            f"Found [bold green]{len(chat_sessions)}[/bold green] potential chat session(s) metadata in [cyan]{db_file_path}[/cyan]:"
        )

        for session_info in chat_sessions:
            chat_title = session_info.get("name", "Untitled Chat")
            composer_id = session_info.get("composerId", "UnknownID")
            created_at_ms = session_info.get("createdAt")
            updated_at_ms = session_info.get("lastUpdatedAt")
            turns_count = len(session_info.get("turns", []))

            created_str = (
                datetime.fromtimestamp(created_at_ms / 1000).strftime(
                    "%Y-%m-%d %H:%M:%S"
                )
                if created_at_ms
                else "N/A"
            )
            updated_str = (
                datetime.fromtimestamp(updated_at_ms / 1000).strftime(
                    "%Y-%m-%d %H:%M:%S"
                )
                if updated_at_ms
                else "N/A"
            )

            if turns_count > 0:
                discovered_chats_count += 1
                console.print(
                    f"  - [b]Title:[/b] {chat_title} ([b]ID:[/b] {composer_id})"
                )
                console.print(
                    f"    [b]Turns:[/b] {turns_count}, [b]Created:[/b] {created_str}, [b]Updated:[/b] {updated_str}"
                )
            else:
                console.print(
                    f"  - [b]Title:[/b] {chat_title} ([b]ID:[/b] {composer_id}) - [yellow]No conversational turns found (may be empty or non-chat type).[/yellow]"
                )
                logger.info(
                    f"Session '{chat_title}' ({composer_id}) has no turns, skipping detailed display."
                )

    return discovered_chats_count


@app.command()
def discover(
    discovery_path_str: str = typer.Argument(
        None,
        help="Directory to search for state.vscdb files. Defaults to Cursor workspace storage.",
        show_default=False,
    ),
    limit: int = typer.Option(
        10,
        help="Max number of DB files to process. Set to 0 or negative for unlimited.",
    ),
):
    """Discover state.vscdb files and print a summary of contained chat sessions."""
    logger.info("Starting discovery process.")

    # Load config for path defaults and other settings
    config_path_file = Path("config.yml")
    if not config_path_file.exists():
        logger.error(
            f"Configuration file not found: {config_path_file}. Cannot proceed."
        )
        console.print(
            f"[bold red]Error: Configuration file '{config_path_file}' not found.[/bold red]"
        )
        raise typer.Exit(code=1)
    try:
        with open(config_path_file, "r") as f:
            config = yaml.safe_load(f)
    except yaml.YAMLError as e:
        logger.error(f"Error parsing YAML configuration: {e}")
        console.print(
            f"[bold red]Error: Could not parse configuration file '{config_path_file}'. {e}[/bold red]"
        )
        raise typer.Exit(code=1)

    if discovery_path_str:
        discovery_path = Path(discovery_path_str)
        if not discovery_path.is_dir():
            logger.error(
                f"Provided discovery path is not a directory: {discovery_path}"
            )
            console.print(
                f"[bold red]Error: Provided path '{discovery_path}' is not a directory.[/bold red]"
            )
            raise typer.Exit(code=1)
    else:
        discovery_path = get_cursor_workspace_path()
        if not discovery_path:
            # Error already logged by get_cursor_workspace_path
            console.print(
                f"[bold red]Error: Could not determine default Cursor workspace path.[/bold red]"
            )
            raise typer.Exit(code=1)
        logger.info(f"Defaulting to Cursor workspace path: {discovery_path}")

    console.print(
        f"Searching for 'state.vscdb' files in: [blue]{discovery_path}[/blue]"
    )

    # Find all state.vscdb files
    db_files = list(discovery_path.rglob("state.vscdb"))

    if not db_files:
        logger.warning(f"No 'state.vscdb' files found in {discovery_path}.")
        console.print(
            f"[yellow]No 'state.vscdb' files found in {discovery_path}.[/yellow]"
        )
        return

    logger.info(f"Found {len(db_files)} 'state.vscdb' file(s).")
    console.print(
        f"Found {len(db_files)} 'state.vscdb' file(s). Processing up to {limit if limit > 0 else 'all'} of them."
    )

    processed_count = 0
    total_discovered_chats = 0
    for db_file in db_files:
        if limit > 0 and processed_count >= limit:
            logger.info(f"Reached processing limit of {limit} DB files.")
            console.print(f"Reached processing limit of {limit} DB files.")
            break

        total_discovered_chats += discover_from_db(db_file, console, config)
        processed_count += 1
        console.print("---")  # Separator between DBs

    if total_discovered_chats == 0:
        console.print(
            "[bold yellow]No exportable chat sessions with turns were found across the processed databases.[/bold yellow]"
        )
    else:
        console.print(
            f"[bold green]Discovery complete. Found a total of {total_discovered_chats} chat session(s) with turns across {processed_count} database(s).[/bold green]"
        )


@app.command()
def export(
    output_dir_str: str = typer.Option(
        "exported_chats", help="Directory to save exported chats."
    ),
    db_path_str: str = typer.Argument(
        None,
        help="Specific state.vscdb file to export from. If not provided, searches default path.",
        show_default=False,
    ),
    discovery_path_str: str = typer.Option(
        None,
        help="Directory to search for state.vscdb files if specific db_path is not given. Defaults to Cursor workspace storage.",
        show_default=False,
    ),
    limit_db: int = typer.Option(
        0,  # Default to 0 (unlimited) for export, as user might want all from a specific path
        help="Max number of DB files to process when discovery_path is used. 0 for unlimited.",
    ),
    format_type: str = typer.Option(
        "md", help="Export format ('md' for Markdown, 'json')."
    ),
):
    """Export chat history to Markdown or JSON files."""
    logger.info(
        f"Starting export process. Format: {format_type}, Output directory: {output_dir_str}"
    )

    output_dir = Path(output_dir_str)
    output_dir.mkdir(parents=True, exist_ok=True)
    logger.info(f"Ensured output directory exists: {output_dir}")

    # Initialize exporter components based on format
    if format_type.lower() == "md":
        formatter = MarkdownChatFormatter()
    elif format_type.lower() == "json":
        # Simple JSON structure for now
        formatter = None  # JSON will be handled directly
    else:
        logger.error(f"Unsupported format: {format_type}")
        console.print(
            f"[bold red]Error: Unsupported format '{format_type}'. Choose 'md' or 'json'.[/bold red]"
        )
        raise typer.Exit(code=1)

    file_saver = MarkdownFileSaver(
        output_dir
    )  # Re-evaluate if this name is okay for JSON too

    # Determine which DBs to process
    db_files_to_process = []
    if db_path_str:
        specific_db_path = Path(db_path_str)
        if not specific_db_path.is_file() or specific_db_path.name != "state.vscdb":
            logger.error(
                f"Invalid specific DB path: {specific_db_path}. Must be a 'state.vscdb' file."
            )
            console.print(
                f"[bold red]Error: Path '{specific_db_path}' is not a valid 'state.vscdb' file.[/bold red]"
            )
            raise typer.Exit(code=1)
        db_files_to_process.append(specific_db_path)
        logger.info(f"Exporting from specific database: {specific_db_path}")
    else:
        # Use discovery_path_str or default path
        if discovery_path_str:
            search_path = Path(discovery_path_str)
            if not search_path.is_dir():
                logger.error(
                    f"Provided discovery path for export is not a directory: {search_path}"
                )
                console.print(
                    f"[bold red]Error: Provided discovery path '{search_path}' is not a directory.[/bold red]"
                )
                raise typer.Exit(code=1)
        else:
            search_path = get_cursor_workspace_path()
            if not search_path:
                console.print(
                    f"[bold red]Error: Could not determine default Cursor workspace path for export.[/bold red]"
                )
                raise typer.Exit(code=1)

        logger.info(f"Searching for databases to export in: {search_path}")
        found_dbs = list(search_path.rglob("state.vscdb"))
        if not found_dbs:
            logger.warning(f"No 'state.vscdb' files found in {search_path} for export.")
            console.print(
                f"[yellow]No 'state.vscdb' files found in {search_path} to export.[/yellow]"
            )
            return

        if limit_db > 0 and len(found_dbs) > limit_db:
            db_files_to_process = found_dbs[:limit_db]
            logger.info(
                f"Processing first {limit_db} of {len(found_dbs)} found databases for export."
            )
        else:
            db_files_to_process = found_dbs
            logger.info(f"Processing all {len(found_dbs)} found databases for export.")

    total_exported_sessions = 0
    total_processed_dbs = 0

    for db_file in db_files_to_process:
        console.print(f"Processing database for export: [blue]{db_file}[/blue]")
        total_processed_dbs += 1
        db_identifier = db_file.parent.name  # Use parent folder name as DB identifier

        with VSCDBQuery(str(db_file)) as vsc_db:
            all_chat_sessions = vsc_db.query_all_chat_data()

            if not all_chat_sessions:
                logger.info(f"No chat data found in {db_file} to export.")
                console.print(
                    f"  [yellow]No chat data found in {db_file} to export.[/yellow]"
                )
                continue

            exported_from_this_db = 0
            for session_data in all_chat_sessions:
                chat_title = session_data.get("name", "Untitled Chat")
                composer_id = session_data.get("composerId", "UnknownID")
                turns = session_data.get("turns", [])

                created_at_ms = session_data.get("createdAt")
                created_at_dt = (
                    datetime.fromtimestamp(created_at_ms / 1000)
                    if created_at_ms
                    else datetime.now()
                )

                if not turns:
                    logger.info(
                        f"Session '{chat_title}' ({composer_id}) in {db_file} has no turns. Skipping export for this session."
                    )
                    console.print(
                        f"  Skipping session '{chat_title}' (ID: {composer_id}) - No turns."
                    )
                    continue

                # Prepare data for formatter/saver
                # The 'turns' structure from query_all_chat_data is now:
                # [{"request": "...", "response": "...", "timestamp": ms, "generationUUID": "..."}]

                export_data = {
                    "title": chat_title,
                    "composer_id": composer_id,  # For potential use in filename or content
                    "db_identifier": db_identifier,  # For unique filenames if titles clash
                    "created_at": created_at_dt.strftime("%Y-%m-%d %H:%M:%S"),
                    "turns": turns,
                }

                try:
                    if format_type.lower() == "md":
                        # Markdown formatter expects a list of turns, where each turn is a dict
                        # with 'request' and 'response'. Our new structure matches.
                        formatted_content = formatter.format(export_data)
                        file_saver.save(
                            content=formatted_content,
                            base_filename=chat_title,  # MarkdownFileSaver handles sanitization
                            identifier1=db_identifier,
                            identifier2=composer_id,
                            timestamp=created_at_dt,
                            extension="md",
                        )
                    elif format_type.lower() == "json":
                        # For JSON, we'll just dump the export_data dict
                        # MarkdownFileSaver can still be used for consistent naming, just change extension
                        json_content = json.dumps(export_data, indent=2)
                        file_saver.save(
                            content=json_content,
                            base_filename=chat_title,
                            identifier1=db_identifier,
                            identifier2=composer_id,
                            timestamp=created_at_dt,
                            extension="json",
                        )

                    logger.info(
                        f"Successfully exported session '{chat_title}' (ID: {composer_id}) from {db_file}"
                    )
                    console.print(f"  Exported: '{chat_title}' (ID: {composer_id})")
                    exported_from_this_db += 1
                    total_exported_sessions += 1

                except Exception as e:
                    logger.error(
                        f"Failed to export session '{chat_title}' (ID: {composer_id}) from {db_file}: {e}"
                    )
                    console.print(
                        f"  [red]Error exporting session '{chat_title}': {e}[/red]"
                    )

            if exported_from_this_db == 0:
                console.print(
                    f"  [yellow]No sessions with turns were exported from {db_file}.[/yellow]"
                )

    if total_exported_sessions > 0:
        console.print(
            f"[bold green]Export complete. {total_exported_sessions} chat session(s) exported from {total_processed_dbs} database(s) to '{output_dir}'.[/bold green]"
        )
    else:
        console.print(
            f"[bold yellow]Export finished. No chat sessions with turns were found to export from the processed {total_processed_dbs} database(s).[/bold yellow]"
        )


@app.command()
def config_path():
    """Prints the default Cursor workspace path based on OS and config.yml."""
    path = get_cursor_workspace_path()
    if path:
        console.print(f"Default Cursor Workspace Path: [green]{path}[/green]")
    else:
        console.print(
            "[red]Could not determine default path. Check config.yml and OS support.[/red]"
        )


if __name__ == "__main__":
    # Setup logger
    # Remove default Rich-based handler from Typer/Click if it's added
    # logger.remove() # This might remove Typer's default console output for errors too soon

    # Configure Loguru
    # Basic configuration, can be enhanced
    LOG_LEVEL = os.environ.get("LOG_LEVEL", "INFO")
    logger.add(
        lambda msg: console.print(msg, end=""),  # Using Rich console for log output
        level=LOG_LEVEL,
        format="<green>{time:YYYY-MM-DD HH:mm:ss.SSS}</green> | <level>{level: <8}</level> | <cyan>{name}</cyan>:<cyan>{function}</cyan>:<cyan>{line}</cyan> - <level>{message}</level>",
        colorize=True,  # Loguru handles colors for its own formatting
    )
    logger.info(f"Logger initialized with level: {LOG_LEVEL}")

    try:
        app()
    except Exception as e:
        logger.opt(exception=True).critical(f"Unhandled exception in application: {e}")
        # console.print(f"[bold red]An critical error occurred: {e}[/bold red]")
        # typer.Exit(code=1) # Typer usually handles this
