# Xcode Diagnostics MCP Plugin

An MCP (Model Control Protocol) plugin for extracting and viewing errors and warnings from Xcode build logs.

## Overview

This plugin implements the Model Control Protocol (MCP) specification to provide Xcode diagnostics functionality to any compatible AI assistants. It connects to Xcode's build system to extract, parse, and display diagnostics (errors and warnings) from your Swift projects. It helps AI assistants quickly identify issues in your code without having to manually search through build logs. 

Note that since this works at the log level, Xcode must have already attempted a build before you run this tool. 

## Prerequisites

- macOS operating system
- Xcode installed
- Python 3.6+

## Installation

### Installing from PyPI

The simplest way to install the Xcode Diagnostics MCP plugin:

```bash
pip install mcp-xcode-diagnostics
```

### Installing from GitHub

You can install directly from GitHub:

```bash
pip install git+https://github.com/leftspin/mcp-xcode-diagnostics.git
```

### Installing from source

To install from source:

1. Clone or download this repository
2. Install the plugin using pip:
   ```bash
   cd mcp-xcode-diagnostics
   pip install .
   ```

The plugin can now be used with any MCP-compatible client.

## Features

- Lists all Xcode projects that have build logs in DerivedData
- Extracts errors and warnings from the latest build log of a specific project
- Parses complex diagnostics, including associated notes and fix-it suggestions
- Provides detailed information about each issue, including file paths, line numbers, and error messages
- Optimized for capturing Swift concurrency-related warnings

## Supported Diagnostic Types

The plugin can detect and display various types of Xcode diagnostics including:

### Errors
- Syntax errors (e.g., "expected '{'" or "expected expression")
- Type errors (e.g., "cannot convert value of type X to expected argument type Y")
- Unresolved identifiers and missing imports
- Protocol conformance errors
- Generic parameter inference failures
- Access control violations

### Warnings
- Unused variables, constants, and results
- Implicit conversions that may lose precision
- Redundant code or unnecessary expressions
- Deprecation warnings
- String interpolation issues
- Swift concurrency warnings, including:
  - Non-isolated global shared mutable state warnings
  - Main actor isolation warnings
  - Protocol conformance concurrency warnings
  - Actor isolation violations
  - Swift 6 language mode compatibility warnings

### Notes and Fix-it Suggestions
- Associated notes that provide additional context for errors and warnings
- Fix-it suggestions that propose code changes to resolve issues
- Code snippets showing the problematic code

## Limitations

- Binary/serialized formats in runtime logs may not be fully parsed
- Some highly specialized diagnostic formats may not be recognized
- Very large build logs may be truncated
- Project-specific custom diagnostics might not be properly categorized

## MCP Tools

The plugin provides two main MCP tools:

### get_xcode_projects
Lists all Xcode projects with build logs in the DerivedData directory.

**Parameters**: None

### get_project_diagnostics
Gets diagnostic information from the latest build log of a specific project.

**Parameters**:
- `project_dir_name`: Directory name of the project in DerivedData (e.g., 'ProjectName-hash')
- `include_warnings`: Whether to include warnings in addition to errors (default: True)

## Debug Information

For debugging purposes, the plugin saves raw log output to:
- `/tmp/xcode-mcp-debug.log` - Main application logs
- `/tmp/xcode-diagnostic-raw.log` - Raw output from Xcode activity logs

## Example Output

```json
{
  "success": true,
  "log_file": "/path/to/build.xcactivitylog",
  "timestamp": "2025-03-11T12:34:56.789",
  "errors": [
    {
      "type": "error",
      "message": "use of unresolved identifier 'NonExistentType'",
      "file_path": "/path/to/MyFile.swift",
      "line_number": 42,
      "column": 15,
      "code": "    let x: NonExistentType = value",
      "notes": []
    }
  ],
  "warnings": [
    {
      "type": "warning",
      "message": "static property 'sharedInstance' is not concurrency-safe because it is nonisolated global shared mutable state; this is an error in the Swift 6 language mode",
      "file_path": "/path/to/SharedManager.swift",
      "line_number": 10,
      "column": 16,
      "code": "    static var sharedInstance: SharedManager?",
      "notes": [
        {
          "type": "note",
          "message": "convert 'sharedInstance' to a 'let' constant to make 'Sendable' shared state immutable",
          "file_path": "/path/to/SharedManager.swift",
          "line_number": 10,
          "column": 16
        }
      ]
    }
  ],
  "error_count": 1,
  "warning_count": 1
}
```

## Testing

The plugin includes a test suite to verify parsing functionality:

```bash
# Run all tests
python -m unittest test_xcode_diagnostics.py
```

## License

This project is available under the MIT License.
