"""
Xcode Diagnostics MCP Plugin
----------------------------
Extracts and parses Xcode build errors and warnings from DerivedData logs.
"""

__version__ = "1.0.0"

from .xcode_diagnostics import (
    XcodeDiagnostics,
    DiagnosticIssue,
    get_xcode_projects,
    get_project_diagnostics
)

__all__ = [
    'XcodeDiagnostics',
    'DiagnosticIssue',
    'get_xcode_projects',
    'get_project_diagnostics'
]