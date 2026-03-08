"""Standardized error and result types for tool implementations."""

from typing import Any, TypedDict


class ToolResult(TypedDict, total=False):
    success: bool
    data: Any
    error: str
    error_code: str


def tool_error(message: str, *, code: str = "tool_error") -> ToolResult:
    return {"success": False, "error": message, "error_code": code}


def tool_success(data: Any) -> ToolResult:
    return {"success": True, "data": data}
