#!/usr/bin/env python3
"""
LAMMPS Input Script Generator Launcher - PyQt6 Version

A simple launcher for the LAMMPS Input Script Generator GUI application.
"""

import sys
import os

# Add the current directory to the Python path
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

# Import and run the main application
from lammps_gui import main

if __name__ == "__main__":
    main()