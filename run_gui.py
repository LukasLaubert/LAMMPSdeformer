#!/usr/bin/env python3
"""
LAMMPS Input Script Generator Launcher - Clean PyQt6 Version
"""

import sys
import os

# Add the current directory to the Python path
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

# Import and run the main application
from lammps_gui_clean import main

if __name__ == "__main__":
    main()