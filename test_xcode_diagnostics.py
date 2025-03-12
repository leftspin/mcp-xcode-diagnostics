#!/usr/bin/env python3
"""
Test suite for the Xcode Diagnostics MCP Plugin
"""

import unittest
import os
import tempfile
import json
import shutil
from unittest.mock import patch, MagicMock
from pathlib import Path

# Make sure we can import the module
import sys
sys.path.append(os.path.dirname(os.path.abspath(__file__)))

from xcode_diagnostics import (
    XcodeDiagnostics, 
    DiagnosticIssue,
    get_xcode_projects,
    get_project_diagnostics
)


class TestXcodeDiagnostics(unittest.TestCase):
    """Test cases for XcodeDiagnostics class and functions"""
    
    def setUp(self):
        # Create a temporary directory structure that mimics DerivedData
        self.temp_dir = tempfile.mkdtemp()
        self.derived_data_path = os.path.join(self.temp_dir, "DerivedData")
        os.makedirs(self.derived_data_path)
        
        # Create mock project structures
        self.project1_path = os.path.join(self.derived_data_path, "TestProject1-abc123")
        self.project2_path = os.path.join(self.derived_data_path, "TestProject2-def456")
        
        os.makedirs(os.path.join(self.project1_path, "Logs", "Build"))
        os.makedirs(os.path.join(self.project2_path, "Logs", "Build"))
        
        # Create mock log files
        self.log1_path = os.path.join(self.project1_path, "Logs", "Build", "log1.xcactivitylog")
        self.log2_path = os.path.join(self.project2_path, "Logs", "Build", "log2.xcactivitylog")
        
        # Touch the files
        Path(self.log1_path).touch()
        Path(self.log2_path).touch()
        
    def tearDown(self):
        # Clean up the temporary directory
        shutil.rmtree(self.temp_dir)
    
    @patch('xcode_diagnostics.XcodeDiagnostics')
    def test_get_xcode_projects(self, mock_diagnostics):
        """Test that get_xcode_projects returns properly formatted JSON"""
        # Setup mock
        mock_instance = mock_diagnostics.return_value
        mock_instance.list_xcode_projects.return_value = [
            {"project_name": "TestProject1", "directory_name": "TestProject1-abc123"}
        ]
        
        # Call the function
        result = get_xcode_projects()
        
        # Check result
        result_dict = json.loads(result)
        self.assertIn("projects", result_dict)
        self.assertEqual(len(result_dict["projects"]), 1)
        self.assertEqual(result_dict["projects"][0]["project_name"], "TestProject1")
    
    @patch('xcode_diagnostics.XcodeDiagnostics')
    def test_get_project_diagnostics(self, mock_diagnostics):
        """Test that get_project_diagnostics returns properly formatted JSON"""
        # Setup mock
        mock_instance = mock_diagnostics.return_value
        mock_instance.extract_diagnostics.return_value = {
            "success": True,
            "errors": [{"type": "error", "message": "Test error"}],
            "warnings": [{"type": "warning", "message": "Test warning"}],
            "error_count": 1,
            "warning_count": 1
        }
        
        # Call the function
        result = get_project_diagnostics("TestProject1-abc123")
        
        # Check result
        result_dict = json.loads(result)
        self.assertTrue(result_dict["success"])
        self.assertEqual(len(result_dict["errors"]), 1)
        self.assertEqual(len(result_dict["warnings"]), 1)
        self.assertEqual(result_dict["error_count"], 1)
    
    # The test_get_most_recent_project_diagnostics method has been removed
    # as that functionality is no longer needed
    
    @patch('subprocess.check_output')
    def test_parse_log_file(self, mock_subprocess):
        """Test parsing of log file content with realistic Xcode error and warning formats"""
        # Create an instance with our test directory
        diagnostics = XcodeDiagnostics()
        diagnostics.derived_data_path = self.derived_data_path
        
        # Mock a realistic Xcode build log with errors and warnings
        mock_output = """
SwiftCompile normal arm64 /Users/developer/MyProject/Sources/App/AppDelegate.swift
    cd /Users/developer/MyProject
    /Applications/Xcode.app/Contents/Developer/Toolchains/XcodeDefault.xctoolchain/usr/bin/swift -frontend -c -primary-file
    
/Users/developer/MyProject/Sources/App/AppDelegate.swift:25:18: error: use of unresolved identifier 'AppConfiguration'
        let config = AppConfiguration()
                     ^~~~~~~~~~~~~~~~
/Users/developer/MyProject/Sources/App/AppDelegate.swift:25:18: note: did you mean 'URLSessionConfiguration'?
        let config = AppConfiguration()
                     ^~~~~~~~~~~~~~~~
                     URLSessionConfiguration
/Users/developer/MyProject/Sources/App/ViewController.swift:42:10: warning: result of call to 'loadView()' is unused
        self.loadView()
        ^~~~~~~~~~~~
/Users/developer/MyProject/Sources/App/ViewController.swift:48:27: warning: string interpolation produces a debug description for an optional value; did you mean to make this explicit?
        print("User name: \\(user.name)")
                          ^~~~~~~~~~~
/Users/developer/MyProject/Sources/App/ViewController.swift:53:14: error: value of type 'UIView' has no member 'setText'
        myView.setText("Hello World")
        ~~~~~~ ^~~~~~~
/Users/developer/MyProject/Sources/Services/NetworkManager.swift:112:40: warning: initialization of immutable value 'response' was never used
        let data = responseData, let response = httpResponse {
                                       ^~~~~~~~
/Users/developer/MyProject/Sources/Services/NetworkManager.swift:122:22: error: cannot convert value of type 'String' to expected argument type 'URL'
        let task = session.dataTask(with: "https://api.example.com")
                                         ^~~~~~~~~~~~~~~~~~~~~~~~~~~
        """
        mock_subprocess.return_value = mock_output
        
        # Call the parse method
        issues = diagnostics._parse_log_file(self.log1_path, include_warnings=True)
        
        # Verify results
        self.assertEqual(len(issues), 6, "Should find 3 errors and 3 warnings")
        
        # Count errors and warnings
        errors = [issue for issue in issues if issue.type == "error"]
        warnings = [issue for issue in issues if issue.type == "warning"]
        
        self.assertEqual(len(errors), 3, "Should find 3 errors")
        self.assertEqual(len(warnings), 3, "Should find 3 warnings")
        
        # Check specific error details
        app_config_error = next((e for e in errors if "AppConfiguration" in e.message), None)
        self.assertIsNotNone(app_config_error)
        self.assertEqual(app_config_error.file_path, "/Users/developer/MyProject/Sources/App/AppDelegate.swift")
        self.assertEqual(app_config_error.line_number, 25)
        self.assertEqual(app_config_error.column, 18)
        
        # Check specific warning details
        unused_warning = next((w for w in warnings if "unused" in w.message), None)
        self.assertIsNotNone(unused_warning)
        
        # The unused warning in our mock data is in ViewController.swift for 'loadView()'
        self.assertEqual(unused_warning.file_path, "/Users/developer/MyProject/Sources/App/ViewController.swift")
        self.assertEqual(unused_warning.line_number, 42)
        self.assertEqual(unused_warning.column, 10)
        
        # Test with warnings excluded
        issues_no_warnings = diagnostics._parse_log_file(self.log1_path, include_warnings=False)
        self.assertEqual(len(issues_no_warnings), 3, "Should only find errors when warnings are excluded")
    
    def test_get_latest_build_log(self):
        """Test getting the latest build log file"""
        # Create an instance with our test directory
        diagnostics = XcodeDiagnostics()
        diagnostics.derived_data_path = self.derived_data_path
        
        # Create two log files with different timestamps
        recent_log = os.path.join(self.project1_path, "Logs", "Build", "recent.xcactivitylog")
        older_log = os.path.join(self.project1_path, "Logs", "Build", "older.xcactivitylog")
        
        Path(recent_log).touch()
        Path(older_log).touch()
        
        # Make one file newer than the other
        now = Path(recent_log).stat().st_mtime
        os.utime(older_log, (now - 100, now - 100))
        
        # Get the latest log
        latest_log = diagnostics.get_latest_build_log("TestProject1-abc123")
        
        # Verify it's the recent one
        self.assertEqual(os.path.basename(latest_log), "recent.xcactivitylog")
        
    @patch('subprocess.check_output')
    def test_extract_diagnostics_end_to_end(self, mock_subprocess):
        """Test the entire flow from extracting to formatting diagnostics"""
        # Create an instance with our test directory
        diagnostics = XcodeDiagnostics()
        diagnostics.derived_data_path = self.derived_data_path
        
        # Create a realistic Xcode build log with a mix of errors and warnings
        # This simulates the output from a real build
        mock_output = """
/Users/developer/TestApp/AppDelegate.swift:15:10: error: missing required module 'UIKit'
import UIKit
       ^
/Users/developer/TestApp/ViewController.swift:32:21: warning: implicit conversion loses integer precision: 'Int' to 'Int16'
    let smallValue: Int16 = bigValue
                    ^        ~~~~~~~
/Users/developer/TestApp/Models/User.swift:45:18: error: property 'name' with type 'String' cannot be used in a generic context expecting 'Int'
    return compare(user.name, 42)
                 ^~~~~~~~~~
"""
        mock_subprocess.return_value = mock_output
        
        # Test the complete extraction flow
        result = diagnostics.extract_diagnostics("TestProject1-abc123", include_warnings=True)
        
        # Verify the structure and content of the result
        self.assertTrue(result["success"])
        self.assertEqual(result["error_count"], 2)
        self.assertEqual(result["warning_count"], 1)
        
        # Verify error details are preserved
        errors = result["errors"]
        self.assertEqual(len(errors), 2)
        
        # Check the first error
        self.assertEqual(errors[0]["type"], "error")
        self.assertEqual(errors[0]["file_path"], "/Users/developer/TestApp/AppDelegate.swift")
        self.assertEqual(errors[0]["line_number"], 15)
        self.assertEqual(errors[0]["column"], 10)
        self.assertIn("missing required module", errors[0]["message"])
        
        # Check the warning
        warnings = result["warnings"]
        self.assertEqual(len(warnings), 1)
        self.assertEqual(warnings[0]["type"], "warning")
        self.assertEqual(warnings[0]["file_path"], "/Users/developer/TestApp/ViewController.swift")
        self.assertIn("implicit conversion loses integer precision", warnings[0]["message"])
        
        # Test with warnings excluded
        result_no_warnings = diagnostics.extract_diagnostics("TestProject1-abc123", include_warnings=False)
        self.assertEqual(result_no_warnings["error_count"], 2)
        self.assertEqual(result_no_warnings["warning_count"], 0)
        self.assertEqual(len(result_no_warnings["warnings"]), 0)


    def test_with_sample_file(self):
        """Test using the included sample file to verify parsing with real-world data"""
        # Create an instance with our test directory
        diagnostics = XcodeDiagnostics()
        diagnostics.derived_data_path = self.derived_data_path
        
        # Create a mock log file that we'll read from the test_data directory
        sample_log_path = os.path.join(self.project1_path, "Logs", "Build", "sample.xcactivitylog")
        Path(sample_log_path).touch()
        
        # Get the sample data file path
        script_dir = os.path.dirname(os.path.abspath(__file__))
        sample_data_path = os.path.join(script_dir, "test_data", "sample_xcode_log.txt")
        
        # Use the sample file instead of real subprocess call
        with patch('subprocess.check_output') as mock_subprocess:
            with open(sample_data_path, 'r') as f:
                mock_subprocess.return_value = f.read()
            
            # Test the extraction
            result = diagnostics.extract_diagnostics("TestProject1-abc123", include_warnings=True)
            
            # Verify counts - our sample has exactly 5 errors and 4 warnings
            self.assertEqual(result["error_count"], 5, "Should find 5 errors in the sample data")
            self.assertEqual(result["warning_count"], 4, "Should find 4 warnings in the sample data")
            
            # Double-check that we have the right number of items in the lists too
            self.assertEqual(len(result["errors"]), 5, "Should have 5 error objects in the errors list")
            self.assertEqual(len(result["warnings"]), 4, "Should have 4 warning objects in the warnings list")
            
            # Verify error types and locations
            errors = result["errors"]
            warnings = result["warnings"]
            
            # Check that we found errors in all the expected files
            error_files = {error["file_path"] for error in errors}
            expected_error_files = {
                "/Users/developer/TestApp/AppDelegate.swift",
                "/Users/developer/TestApp/ViewController.swift",
                "/Users/developer/TestApp/Models/User.swift",
                "/Users/developer/TestApp/Services/NetworkManager.swift"
            }
            self.assertTrue(expected_error_files.issubset(error_files), 
                            f"Expected to find errors in {expected_error_files}, but found {error_files}")
            
            # Check for specific error messages
            error_messages = [error["message"] for error in errors]
            self.assertTrue(any("missing required module" in msg for msg in error_messages))
            self.assertTrue(any("setText" in msg for msg in error_messages))
            
            # Check for specific warning types
            warning_messages = [w["message"] for w in warnings]
            self.assertTrue(any("implicit conversion" in msg for msg in warning_messages))
            self.assertTrue(any("unused" in msg for msg in warning_messages))


if __name__ == '__main__':
    unittest.main()