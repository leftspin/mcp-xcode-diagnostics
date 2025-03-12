#!/usr/bin/env python3
"""
Xcode Diagnostics MCP Plugin
----------------------------
Extracts and parses Xcode build errors and warnings from DerivedData logs.
"""

import os
import glob
import json
import gzip
import re
import subprocess
import sys
import logging
import uuid
from pathlib import Path
from typing import List, Dict, Any, Optional, Union, Callable
from dataclasses import dataclass
from datetime import datetime

# Import MCP SDK
try:
    from mcp.server import Server, StdioServerTransport
    from mcp.types import tool, Tool
    HAS_MCP_SDK = True
except ImportError:
    HAS_MCP_SDK = False
    logging.warning("MCP SDK not installed. To install: pip install 'mcp'")

# Set up logging
logging.basicConfig(
    level=logging.DEBUG,
    filename='/tmp/xcode-mcp-debug.log',
    filemode='a',
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger('xcode-diagnostics-mcp')

@dataclass
class DiagnosticIssue:
    """Represents a single diagnostic issue from Xcode build logs."""
    type: str  # 'error' or 'warning'
    message: str
    file_path: Optional[str] = None
    line_number: Optional[int] = None
    column: Optional[int] = None
    character_range: Optional[str] = None
    code: Optional[str] = None  # Error/warning code if available
    notes: List[Dict[str, Any]] = None  # Associated notes, suggestions, fixes
    
    def __post_init__(self):
        # Initialize notes as empty list if None
        if self.notes is None:
            self.notes = []


class XcodeDiagnostics:
    """Main class for extracting diagnostics from Xcode build logs."""
    
    def __init__(self):
        self.derived_data_path = os.path.expanduser("~/Library/Developer/Xcode/DerivedData")
    
    def list_xcode_projects(self) -> List[Dict[str, Any]]:
        """
        Lists all Xcode projects found in DerivedData directory.
        
        Returns:
            List of dictionaries containing project info
        """
        if not os.path.exists(self.derived_data_path):
            return []
            
        projects = []
        project_dirs = glob.glob(f"{self.derived_data_path}/*")
        
        for project_dir in project_dirs:
            if os.path.isdir(project_dir):
                # Extract project name from directory name
                # Format is typically ProjectName-hash
                dir_name = os.path.basename(project_dir)
                parts = dir_name.split('-', 1)
                
                project_name = parts[0] if len(parts) > 0 else dir_name
                
                # Check if it has Logs/Build directory
                build_logs_dir = os.path.join(project_dir, "Logs", "Build")
                has_build_logs = os.path.exists(build_logs_dir)
                
                # Get latest modification time for the directory
                try:
                    mtime = os.path.getmtime(project_dir)
                    last_modified = datetime.fromtimestamp(mtime).isoformat()
                except:
                    last_modified = None
                
                projects.append({
                    "project_name": project_name,
                    "directory_name": dir_name,
                    "full_path": project_dir,
                    "has_build_logs": has_build_logs,
                    "last_modified": last_modified
                })
        
        # Sort by modification time (most recent first)
        projects.sort(key=lambda x: x.get("last_modified", ""), reverse=True)
        return projects
    
    def get_latest_build_log(self, project_dir_name: str) -> Optional[str]:
        """
        Get the path to the latest build log for a specific project.
        
        Args:
            project_dir_name: Directory name for the project in DerivedData
            
        Returns:
            Path to the latest build log file, or None if not found
        """
        project_path = os.path.join(self.derived_data_path, project_dir_name)
        build_logs_dir = os.path.join(project_path, "Logs", "Build")
        
        if not os.path.exists(build_logs_dir):
            return None
            
        # List all .xcactivitylog files and sort by modification time
        log_files = glob.glob(f"{build_logs_dir}/*.xcactivitylog")
        if not log_files:
            return None
            
        log_files.sort(key=os.path.getmtime, reverse=True)
        return log_files[0]
    
    def extract_diagnostics(self, project_dir_name: str, include_warnings: bool = True) -> Dict[str, Any]:
        """
        Extracts errors and warnings from the latest build log of a project.
        
        Args:
            project_dir_name: Directory name for the project in DerivedData
            include_warnings: Whether to include warnings (not just errors)
            
        Returns:
            Dictionary containing parsed diagnostics information
        """
        log_file = self.get_latest_build_log(project_dir_name)
        if not log_file:
            return {
                "success": False,
                "message": f"No build logs found for project {project_dir_name}",
                "errors": [],
                "warnings": []
            }
        
        # Extract data from gzipped log file
        issues = self._parse_log_file(log_file, include_warnings)
        
        # Enhanced search for concurrency-related warnings
        if include_warnings:
            # Debug log about searching for concurrency warnings
            logger.debug(f"Looking for concurrency-related warnings in log file: {log_file}")
            
            # Search for concurrency-related phrases and patterns in the raw log
            concurrency_terms = [
                "concurrency-safe", "nonisolated global", "Swift 6 language mode", 
                "thread safety", "actor isolation", "sendable"
            ]
            
            # Use grep to search through the decompressed log (this gives us context)
            for term in concurrency_terms:
                try:
                    # Use a more targeted grep approach
                    cmd = f"gunzip -c '{log_file}' | grep -A 3 -B 3 '{term}'"
                    grep_result = subprocess.check_output(cmd, shell=True, encoding='latin-1', stderr=subprocess.DEVNULL)
                    
                    if term in grep_result:
                        logger.debug(f"Found '{term}' in build log using grep")
                        logger.debug(f"Context: {grep_result[:500]}...")  # Log just the first 500 chars
                except Exception as e:
                    logger.debug(f"Error searching for '{term}': {str(e)}")
        
        # Process issues, ensuring notes are serialized correctly
        processed_errors = []
        processed_warnings = []
        
        for issue in issues:
            issue_dict = vars(issue)
            # Ensure notes are correctly processed
            if issue.notes:
                issue_dict["notes"] = issue.notes  # This ensures notes are included
            
            if issue.type == 'error':
                processed_errors.append(issue_dict)
            elif issue.type == 'warning' and include_warnings:
                processed_warnings.append(issue_dict)
        
        # Search for any specific properties that might have concurrency warnings
        concurrency_properties_found = []
        concurrency_warning_lines = []
        
        # Check if the log file is readable
        if os.path.exists(log_file) and os.access(log_file, os.R_OK):
            try:
                # Use subprocess to decompress and search for specific concurrency-related patterns
                search_patterns = ["concurrency-safe", "global shared", "Swift 6", "actor isolation"]
                for pattern in search_patterns:
                    try:
                        cmd = f"gunzip -c '{log_file}' | grep -A 5 -B 5 '{pattern}'"
                        search_result = subprocess.check_output(cmd, shell=True, encoding='latin-1', stderr=subprocess.DEVNULL)
                        if pattern in search_result:
                            concurrency_properties_found.append(pattern)
                            concurrency_warning_lines.extend(search_result.split('\n'))
                            logger.debug(f"Found concurrency pattern '{pattern}' in log")
                    except subprocess.CalledProcessError:
                        # grep returns exit code 1 if no matches, which raises CalledProcessError
                        pass
            except Exception as e:
                logger.debug(f"Error searching for concurrency patterns: {str(e)}")
        
        return {
            "success": True,
            "log_file": log_file,
            "timestamp": datetime.fromtimestamp(os.path.getmtime(log_file)).isoformat(),
            "errors": processed_errors,
            "warnings": processed_warnings,
            "error_count": len(processed_errors),
            "warning_count": len(processed_warnings),
            "debug_info": {
                "concurrency_properties_found": concurrency_properties_found,
                "concurrency_warning_context": concurrency_warning_lines[:20] if concurrency_warning_lines else [],
                "parsing_info": {
                    "patterns_used": [
                        "main_pattern", "alt_pattern", "concurrency_pattern", "backup_concurrency_pattern"
                    ]
                }
            }
        }
    
    def _parse_log_file(self, log_file: str, include_warnings: bool) -> List[DiagnosticIssue]:
        """
        Parses a .xcactivitylog file to extract error and warning information.
        
        Args:
            log_file: Path to the .xcactivitylog file
            include_warnings: Whether to include warnings
            
        Returns:
            List of DiagnosticIssue objects
        """
        issues = []
        
        try:
            # Use subprocess to decompress and search the log file
            cmd = f"gunzip -c '{log_file}' | strings"
            output = subprocess.check_output(cmd, shell=True, encoding='latin-1')
            
            # Additional debugging - save raw output to a file for analysis
            debug_log_file = '/tmp/xcode-diagnostic-raw.log'
            with open(debug_log_file, 'w') as f:
                f.write(output)
            logger.debug(f"Saved raw log output to {debug_log_file}")
            
            # Look for specific warning categories that are commonly missed
            search_terms = ["concurrency-safe", "global shared", "Swift 6", "Expected '{'", "actor isolation"]
            for term in search_terms:
                if term in output:
                    line_indexes = [i for i, line in enumerate(output.split('\n')) if term in line]
                    logger.debug(f"Found search term '{term}' in lines: {line_indexes}")
                    # Extract the surrounding context to help debug the regex
                    for idx in line_indexes:
                        lines = output.split('\n')
                        start = max(0, idx - 5)
                        end = min(len(lines), idx + 5)
                        context = '\n'.join(lines[start:end])
                        logger.debug(f"Context for '{term}' at line {idx}:\n{context}")
            
            # Pattern for concurrency-related warnings in Swift files 
            concurrency_pattern = r'([^:]+\.swift):(\d+):(\d+): (warning): (.+(?:concurrency-safe|global shared|Swift 6|nonisolated).+)'
            # Backup pattern for any type of concurrency warning
            backup_concurrency_pattern = r'([^:]+):(\d+):(\d+): (warning): (.+(?:concurrency|thread safety|isolation|actor).+)'
            
            # Look for missed concurrency-related warnings in the logs
            concurrency_keywords = [
                "concurrency-safe", "nonisolated global", "Swift 6 language mode", 
                "thread safety", "actor isolation", "sendable"
            ]
            
            # Debug logging for concurrency warnings
            for line in output.split('\n'):
                for keyword in concurrency_keywords:
                    if keyword in line and ".swift:" in line:
                        logger.debug(f"Found potential concurrency warning: {line}")
                        # Check if our enhanced regex patterns will catch this
                        if re.search(concurrency_pattern, line) or re.search(backup_concurrency_pattern, line):
                            logger.debug("This will be caught by our regex patterns")
                        else:
                            logger.debug("WARNING: This might be missed by our regex patterns")
            
            # Split the output into lines for processing
            lines = output.split('\n')
            i = 0
            
            # Store the source code context for diagnostic issues
            current_code_context = {}
            
            while i < len(lines):
                line = lines[i]
                
                # Extract errors and warnings using regex
                # Example formats:
                # /path/to/file.swift:10:15: error: use of unresolved identifier 'foo'
                # /path/to/file.swift:20:5: warning: variable declared but never used
                # Also handle other error formats like "Expected '{'"
                main_pattern = r'([^:]+):(\d+):(\d+): (error|warning): ([^\n]+)'
                # Alternative pattern for other error formats like "Expected '{'"
                alt_pattern = r'([^:]+):(\d+): (error|warning): (expected .+)'
                # Pattern for concurrency-related warnings in Swift files (capturing full message)
                concurrency_pattern = r'([^:]+\.swift):(\d+):(\d+): (warning): (.+(?:concurrency-safe|global shared|Swift 6|nonisolated).+)'
                # Backup pattern for any type of concurrency warning that might be formatted differently
                backup_concurrency_pattern = r'([^:]+):(\d+):(\d+): (warning): (.+(?:concurrency|thread safety|isolation|actor).+)'
                
                match = re.search(main_pattern, line)
                if not match:
                    # Try alternative pattern
                    alt_match = re.search(alt_pattern, line)
                    if alt_match:
                        file_path = alt_match.group(1)
                        line_number = int(alt_match.group(2))
                        column = 1  # Default column when not specified
                        issue_type = alt_match.group(3)
                        message = alt_match.group(4).strip()
                        match = True  # Set match to True to indicate we found something
                    else:
                        # Try the concurrency pattern first (more specific for Swift files)
                        concurrency_match = re.search(concurrency_pattern, line)
                        if concurrency_match:
                            file_path = concurrency_match.group(1)
                            line_number = int(concurrency_match.group(2))
                            column = int(concurrency_match.group(3))
                            issue_type = concurrency_match.group(4)
                            message = concurrency_match.group(5).strip()
                            match = True
                            
                            # Add a debug log for this case
                            logger.debug(f"Found Swift concurrency warning: {file_path}:{line_number}")
                            logger.debug(f"Message: {message}")
                            logger.debug(f"Original line: {line}")
                        else:
                            # Try the backup concurrency pattern (for other concurrency issues)
                            backup_match = re.search(backup_concurrency_pattern, line)
                            if backup_match:
                                file_path = backup_match.group(1)
                                line_number = int(backup_match.group(2))
                                column = int(backup_match.group(3))
                                issue_type = backup_match.group(4)
                                message = backup_match.group(5).strip()
                                match = True
                                
                                # Add a debug log for this case
                                logger.debug(f"Found backup concurrency warning: {file_path}:{line_number}")
                                logger.debug(f"Message: {message}")
                                logger.debug(f"Original line: {line}")
                    
                if match:
                    # For standard pattern
                    if match is not True:  # True means we matched the alternative pattern
                        file_path = match.group(1)
                        line_number = int(match.group(2))
                        column = int(match.group(3))
                        issue_type = match.group(4)
                        message = match.group(5).strip()
                    # We already set these variables for the alternative pattern
                    
                    # Skip warnings if not requested
                    if issue_type == 'warning' and not include_warnings:
                        i += 1
                        continue
                    
                    # Create the diagnostic issue
                    diagnostic = DiagnosticIssue(
                        type=issue_type,
                        message=message,
                        file_path=file_path,
                        line_number=line_number,
                        column=column
                    )
                    
                    # Look ahead for any associated notes, code context, and caret lines
                    j = i + 1
                    
                    # Store code context snippet if available
                    if j < len(lines) and not re.search(main_pattern, lines[j]) and not lines[j].strip().startswith('/'):
                        code_line = lines[j].rstrip()
                        diagnostic.code = code_line
                        current_code_context[f"{file_path}:{line_number}"] = code_line
                    context_lines = []
                    while j < len(lines):
                        note_line = lines[j]
                        
                        # Check for a note line - these typically follow the main diagnostic
                        # Example: /path/to/file.swift:11:16: note: convert 'activityIdentifier' to a 'let' constant
                        note_pattern = r'([^:]+):(\d+):(\d+): (note): ([^\n]+)'
                        note_match = re.search(note_pattern, note_line)
                        
                        # Check for a fix-it line - these typically include suggested code changes
                        # Example: static var activityIdentifier
                        #         ~~~ ^
                        #         let
                        fixit_pattern = r'\s*([\^~]+)\s*'
                        fixit_match = re.search(fixit_pattern, note_line)
                        
                        # Check if this is a code context line
                        code_context_pattern = r'^\s+.*$'  # Indented line without file path
                        code_match = re.search(code_context_pattern, note_line) and not fixit_match
                        
                        if note_match:
                            # This is a note line
                            note_file_path = note_match.group(1)
                            note_line_number = int(note_match.group(2))
                            note_column = int(note_match.group(3))
                            note_type = note_match.group(4)
                            note_message = note_match.group(5).strip()
                            
                            note = {
                                "type": note_type,
                                "message": note_message,
                                "file_path": note_file_path,
                                "line_number": note_line_number,
                                "column": note_column,
                                "suggested_fix": None,
                                "code_context": None
                            }
                            
                            # Check for code context for this note
                            context_key = f"{note_file_path}:{note_line_number}"
                            if context_key in current_code_context:
                                note["code_context"] = current_code_context[context_key]
                            
                            # Look ahead for suggested fix
                            if j + 1 < len(lines):
                                next_line = lines[j+1]
                                # Check if next line is a caret line
                                if re.search(fixit_pattern, next_line):
                                    # There's a fix-it indicator line
                                    j += 1
                                    fixit_indicator = next_line
                                    note["fixit_indicator"] = fixit_indicator.rstrip()
                                    
                                    # And possibly a fix-it replacement line
                                    if j + 1 < len(lines) and not re.search(main_pattern, lines[j+1]) and not re.search(note_pattern, lines[j+1]):
                                        j += 1
                                        fixit_replacement = lines[j].strip()
                                        note["suggested_fix"] = fixit_replacement
                            
                            diagnostic.notes.append(note)
                            j += 1
                        elif fixit_match:
                            # This is a caret line (^) indicating the position of the error
                            # If there's no note line before it
                            caret_line = note_line.rstrip()
                            
                            # If we haven't added the code context yet, do it now
                            if not diagnostic.code and j > 0 and not re.search(main_pattern, lines[j-1]) and not re.search(note_pattern, lines[j-1]):
                                diagnostic.code = lines[j-1].rstrip()
                            
                            # Store the caret line
                            diagnostic.character_range = caret_line
                            
                            # Check if the next line is a fix suggestion
                            if j + 1 < len(lines) and not re.search(main_pattern, lines[j+1]) and not re.search(note_pattern, lines[j+1]) and not re.search(fixit_pattern, lines[j+1]):
                                j += 1
                                fix_suggestion = lines[j].strip()
                                # Create an implicit note for the fix suggestion
                                implicit_note = {
                                    "type": "implicit_fix",
                                    "message": "Fix suggestion",
                                    "file_path": file_path,
                                    "line_number": line_number,
                                    "column": column,
                                    "suggested_fix": fix_suggestion,
                                    "fixit_indicator": caret_line
                                }
                                diagnostic.notes.append(implicit_note)
                            
                            j += 1
                        elif code_match:
                            # This is a code context line
                            context_lines.append(note_line.rstrip())
                            # If we don't have code context yet for the main diagnostic, use this
                            if not diagnostic.code:
                                diagnostic.code = note_line.rstrip()
                            j += 1
                        else:
                            # This is not a related line, so we've reached the end of this diagnostic
                            break
                    
                    # Add the diagnostic issue to our list
                    issues.append(diagnostic)
                    i = j  # Move past all the notes we processed
                else:
                    i += 1
        except Exception as e:
            # If there's an error parsing, add a special "meta" error
            logger.exception(f"Error parsing log file: {str(e)}")
            issues.append(DiagnosticIssue(
                type="error",
                message=f"Error parsing log file: {str(e)}",
                file_path=log_file
            ))
        
        return issues


# MCP Protocol Implementation using SDK if available
if HAS_MCP_SDK:
    class XcodeDiagnosticsMcpServer:
        """MCP Server implementation using the official MCP SDK."""
        
        def __init__(self):
            self.xcode = XcodeDiagnostics()
            self.server = Server(
                server_info={"name": "xcode-diagnostics", "version": "1.0.0"},
                capabilities={
                    "tools": {},
                }
            )
            
            # Register tools
            self.setup_tools()
            
        def setup_tools(self):
            """Register all tools with the MCP server."""
            @tool(
                name="get_xcode_projects",
                description="Lists all Xcode projects that have build logs in the DerivedData directory."
            )
            async def get_xcode_projects():
                """Lists all Xcode projects with build logs in DerivedData."""
                projects = self.xcode.list_xcode_projects()
                return {"projects": projects}
            
            @tool(
                name="get_project_diagnostics",
                description="Gets diagnostic information (errors and warnings) from the latest build log of a specific project."
            )
            async def get_project_diagnostics(
                project_dir_name: str, 
                include_warnings: bool = True
            ):
                """
                Gets diagnostic information from a specific project's build log.
                
                Args:
                    project_dir_name: Directory name of the project in DerivedData
                    include_warnings: Whether to include warnings in addition to errors
                """
                return self.xcode.extract_diagnostics(project_dir_name, include_warnings)
            
            # Register the tools with the server
            self.server.tools.register(get_xcode_projects)
            self.server.tools.register(get_project_diagnostics)
        
        async def run(self):
            """Run the MCP server using stdio transport."""
            logger.info("Starting Xcode Diagnostics MCP server with MCP SDK")
            transport = StdioServerTransport()
            await self.server.connect(transport)
            logger.info("MCP server connected and running")

else:
    # Legacy MCP implementation for backward compatibility
    class McpServer:
        """
        Implements the MCP protocol for the Xcode Diagnostics plugin.
        """
        
        def __init__(self):
            self.methods = {
                "initialize": self.initialize,
                "shutdown": self.shutdown,
                "mcp.list_tools": self.list_tools,
                "mcp.call_tool": self.call_tool,
                "tools/list": self.list_tools,  # New method path format
                "tools/call": self.call_tool,   # New method path format
                "prompts/list": self.list_prompts,  # New method path
            }
            self.tools = [
                {
                    "name": "get_xcode_projects",
                    "description": "Lists all Xcode projects that have build logs in the DerivedData directory.",
                    "inputSchema": {
                        "type": "object",
                        "properties": {},
                        "required": []
                    }
                },
                {
                    "name": "get_project_diagnostics",
                    "description": "Gets diagnostic information (errors and warnings) from the latest build log of a specific project.",
                    "inputSchema": {
                        "type": "object",
                        "properties": {
                            "project_dir_name": {
                                "type": "string",
                                "description": "Directory name of the project in DerivedData (e.g. 'ProjectName-hash')"
                            },
                            "include_warnings": {
                                "type": "boolean",
                                "description": "Whether to include warnings in addition to errors",
                                "default": True
                            }
                        },
                        "required": ["project_dir_name"]
                    }
                }
            ]
            self.tool_functions = {
                "get_xcode_projects": self._get_xcode_projects,
                "get_project_diagnostics": self._get_project_diagnostics
            }
        
        def _get_xcode_projects(self, params):
            """Implementation of get_xcode_projects for MCP."""
            diagnostics = XcodeDiagnostics()
            projects = diagnostics.list_xcode_projects()
            return {"projects": projects}
        
        def _get_project_diagnostics(self, params):
            """Implementation of get_project_diagnostics for MCP."""
            project_dir_name = params.get("project_dir_name")
            include_warnings = params.get("include_warnings", True)
            
            diagnostics = XcodeDiagnostics()
            return diagnostics.extract_diagnostics(project_dir_name, include_warnings)
        
        def initialize(self, params):
            """Handle initialize method, required by the MCP protocol."""
            logger.info("Initializing MCP server with params: %s", params)
            capabilities = params.get("capabilities", {})
            client_info = params.get("client_info", {})
            
            # Respond with server information and capabilities
            return {
                "serverInfo": {
                    "name": "xcode-diagnostics",
                    "version": "1.0.0"
                },
                "protocolVersion": "2024-11-05",
                "capabilities": {
                    "tools": {},
                    "resources": {},
                    "prompts": {}
                }
            }
            
        def shutdown(self, params):
            """Handle shutdown method, required by the MCP protocol."""
            logger.info("Shutting down MCP server")
            return {}
            
        def list_tools(self, params):
            """Handle tools/list and mcp.list_tools methods."""
            return {
                "tools": self.tools
            }
            
        def list_prompts(self, params):
            """Handle prompts/list method."""
            # No prompts in this implementation
            return {
                "prompts": []
            }
        
        def call_tool(self, params):
            """Handle mcp.call_tool and tools/call methods."""
            tool_name = params.get("name")
            tool_params = params.get("parameters", {})
            # Also handle new format where arguments might be used instead of parameters
            if not tool_params and "arguments" in params:
                tool_params = params.get("arguments", {})
            
            if tool_name not in self.tool_functions:
                return {
                    "error": {
                        "code": -32601,
                        "message": f"Tool '{tool_name}' not found"
                    }
                }
            
            try:
                result = self.tool_functions[tool_name](tool_params)
                # Format the result according to the latest MCP protocol
                return {
                    "content": [
                        {
                            "type": "text",
                            "text": json.dumps(result)
                        }
                    ]
                }
            except Exception as e:
                logger.exception(f"Error calling tool {tool_name}")
                return {
                    "error": {
                        "code": -32000,
                        "message": f"Tool execution error: {str(e)}"
                    }
                }
        
        def handle_request(self, request):
            """
            Handle a JSON-RPC request and return a response.
            """
            logger.debug(f"Received request: {request}")
            
            request_id = request.get("id")
            method = request.get("method")
            params = request.get("params", {})
            
            # Check for required fields
            if not method:
                return {
                    "jsonrpc": "2.0",
                    "id": request_id,
                    "error": {
                        "code": -32600,
                        "message": "Invalid Request: missing method"
                    }
                }
            
            # Handle method
            if method in self.methods:
                try:
                    result = self.methods[method](params)
                    return {
                        "jsonrpc": "2.0",
                        "id": request_id,
                        "result": result
                    }
                except Exception as e:
                    logger.exception(f"Error handling method {method}")
                    return {
                        "jsonrpc": "2.0",
                        "id": request_id,
                        "error": {
                            "code": -32000,
                            "message": f"Server error: {str(e)}"
                        }
                    }
            else:
                return {
                    "jsonrpc": "2.0",
                    "id": request_id,
                    "error": {
                        "code": -32601,
                        "message": f"Method '{method}' not found"
                    }
                }
        
        def process_line(self, line):
            """
            Process a line of input (JSON-RPC request) and return a response.
            """
            try:
                request = json.loads(line)
                response = self.handle_request(request)
                return json.dumps(response)
            except json.JSONDecodeError:
                logger.error(f"Invalid JSON: {line}")
                return json.dumps({
                    "jsonrpc": "2.0",
                    "id": None,
                    "error": {
                        "code": -32700,
                        "message": "Parse error: invalid JSON"
                    }
                })
        
        def run(self):
            """
            Run the MCP server, reading from stdin and writing to stdout.
            """
            logger.info("Starting Xcode Diagnostics MCP server (legacy implementation)")
            try:
                for line in sys.stdin:
                    line = line.strip()
                    if line:
                        response = self.process_line(line)
                        print(response, flush=True)
                        logger.debug(f"Sent response: {response}")
            except Exception as e:
                logger.exception("Fatal error in MCP server")
                sys.exit(1)


# Function implementations outside the class for testing/debugging
def get_xcode_projects():
    """List all Xcode projects with build logs in DerivedData."""
    diagnostics = XcodeDiagnostics()
    projects = diagnostics.list_xcode_projects()
    return json.dumps({"projects": projects})

def get_project_diagnostics(project_dir_name: str, include_warnings: bool = True):
    """Get diagnostic information from the latest build log of a project."""
    diagnostics = XcodeDiagnostics()
    result = diagnostics.extract_diagnostics(project_dir_name, include_warnings)
    return json.dumps(result)

# When run directly, start the MCP server
if __name__ == "__main__":
    # Check if the --debug flag is passed
    if len(sys.argv) > 1 and sys.argv[1] == "--debug":
        # Run in debug mode - just print projects
        result = get_xcode_projects()
        print(result)
    else:
        # Run as an MCP server
        if HAS_MCP_SDK:
            # Use the MCP SDK implementation
            import asyncio
            server = XcodeDiagnosticsMcpServer()
            asyncio.run(server.run())
        else:
            # Use the legacy implementation
            server = McpServer()
            server.run()
            
    # If we reach here, the server has stopped
    logger.info("MCP server stopped")
    sys.exit(0)