#!/usr/bin/env python3
from setuptools import setup, find_packages
import os

# Read requirements
with open('requirements.txt', 'r') as f:
    requirements = [line.strip() for line in f.readlines() if not line.startswith('#')]

# Read README for the long description
with open('README.md', 'r') as f:
    long_description = f.read()

setup(
    name="mcp-xcode-diagnostics",
    version="1.0.0",
    description="MCP plugin for extracting and viewing Xcode build errors and warnings",
    long_description=long_description,
    long_description_content_type="text/markdown",
    author="Mike R. Manzano",
    author_email="mike@clicketyclacks.co",
    url="https://github.com/leftspin/mcp-xcode-diagnostics",
    py_modules=["xcode_diagnostics"],  # Simple module, not a package
    install_requires=requirements,
    classifiers=[
        "Programming Language :: Python :: 3",
        "License :: OSI Approved :: MIT License",
        "Operating System :: MacOS :: MacOS X",
        "Development Status :: 4 - Beta",
        "Intended Audience :: Developers",
        "Topic :: Software Development :: Build Tools",
    ],
    python_requires=">=3.6",
    # Include non-Python files
    package_data={
        "": ["plugin.json", "manifest.json"],
    },
)