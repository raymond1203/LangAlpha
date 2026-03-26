"""Get output and status of background bash commands."""

from typing import Any, Literal

import structlog
from langchain_core.tools import BaseTool, tool

logger = structlog.get_logger(__name__)


def create_bash_output_tool(sandbox: Any) -> BaseTool:
    """Factory function to create BashOutput tool with injected dependencies.

    Args:
        sandbox: PTCSandbox instance for querying background command output

    Returns:
        Configured BashOutput tool function
    """

    @tool
    async def BashOutput(command_id: str, action: Literal["status", "stop"] = "status") -> str:
        """Get the output/status of a background command, or stop it.

        Use this to check on commands started with run_in_background=True.

        Args:
            command_id: The command_id returned when the background command was started
            action: "status" (default) to check output, or "stop" to terminate the command

        Returns:
            Status and output of the background command, or confirmation of stop
        """
        try:
            if action == "stop":
                stopped = await sandbox.stop_background_command(command_id)
                if stopped:
                    return f"Background command {command_id} stopped."
                return f"No running background command found with id {command_id}."

            result = await sandbox.get_background_command_status(command_id)

            is_running = result["is_running"]
            exit_code = result["exit_code"]
            stdout = result.get("stdout", "")
            stderr = result.get("stderr", "")

            # Format status line
            if is_running:
                status = "RUNNING"
            elif exit_code == 0:
                status = "COMPLETED (success)"
            else:
                status = f"COMPLETED (exit code {exit_code})"

            parts = [f"Status: {status}"]
            if stdout:
                parts.append(f"Output:\n{stdout}")
            if stderr:
                parts.append(f"Errors:\n{stderr}")

            return "\n".join(parts)

        except Exception as e:
            error_msg = f"Failed to get background command output: {e!s}"
            logger.error(error_msg, command_id=command_id, exc_info=True)
            return f"ERROR: {error_msg}"

    return BashOutput
