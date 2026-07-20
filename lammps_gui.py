#!/usr/bin/env python3
"""
LAMMPS Input Script Generator GUI - Complete PyQt6 Version

A graphical user interface for creating LAMMPS input scripts for particle-based deformation simulations.
Supports both local execution and cluster job submission.
This version includes ALL features from the original implementation.
"""

import sys
import os
import json
import glob
import tempfile
import threading
import time
import shutil
from pathlib import Path

# Import PyQt6 components
try:
    from PyQt6.QtWidgets import (QApplication, QMainWindow, QTabWidget, QWidget, QVBoxLayout, 
                                QHBoxLayout, QLabel, QLineEdit, QPushButton, QFileDialog, 
                                QComboBox, QCheckBox, QSpinBox, QDoubleSpinBox, QTextEdit,
                                QGroupBox, QFormLayout, QRadioButton, QButtonGroup, QScrollArea,
                                QSplitter, QMessageBox, QProgressBar, QDialog, QGridLayout,
                                QTableWidget, QTableWidgetItem, QHeaderView, QAbstractItemView,
                                QDialogButtonBox, QToolTip, QFrame, QSizePolicy, QItemDelegate)
    from PyQt6.QtCore import Qt, QSettings, pyqtSignal, QThread, QTimer, QUrl, QSize
    from PyQt6.QtGui import QIcon, QDesktopServices, QCursor, QPalette, QColor
    
    # Handle QRegularExpression vs QRegExp compatibility
    try:
        from PyQt6.QtCore import QRegularExpression
        from PyQt6.QtGui import QRegularExpressionValidator
        HAS_QREGULAREXPRESSION = True
    except ImportError:
        # Fallback to QRegExp for older PyQt6 versions
        from PyQt6.QtCore import QRegExp
        from PyQt6.QtGui import QRegExpValidator
        HAS_QREGULAREXPRESSION = False
    
    # Handle validators
    try:
        from PyQt6.QtGui import QDoubleValidator, QIntValidator
    except ImportError:
        # Create simple validators if not available
        class QDoubleValidator:
            def __init__(self, bottom=None, top=None, decimals=None):
                self.bottom = bottom
                self.top = top
                self.decimals = decimals
        
        class QIntValidator:
            def __init__(self, bottom=None, top=None):
                self.bottom = bottom
                self.top = top
    
except ImportError as e:
    sys.exit(1)

# Import the script generator
try:
    from script_generator import LammpsScriptGenerator
except ImportError as e:
    LammpsScriptGenerator = None

class NumericTableWidgetItem(QTableWidgetItem):
    """Custom table widget item that validates numeric input"""
    
    def __init__(self, value=0.0, is_float=True, min_val=None, max_val=None):
        super().__init__(str(value))
        self.is_float = is_float
        self.min_val = min_val
        self.max_val = max_val
        self.setTextAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
        
    def setData(self, role, value):
        if role == Qt.ItemDataRole.EditRole:
            try:
                if self.is_float:
                    num_value = float(value)
                else:
                    num_value = int(value)
                    
                # Check bounds if specified
                if self.min_val is not None and num_value < self.min_val:
                    return
                if self.max_val is not None and num_value > self.max_val:
                    return
                    
                super().setData(role, str(num_value))
            except (ValueError, TypeError):
                # Invalid input, ignore
                return
        else:
            super().setData(role, value)

class LammpsScriptGenerator(QMainWindow):
    """Main application window for LAMMPS script generation"""
    
    def __init__(self):
        super().__init__()
        self.setWindowTitle("LAMMPS Input Script Generator")
        self.setGeometry(100, 100, 1200, 800)
        
        # Apply modern stylesheet
        self.apply_modern_stylesheet()
        
        # Initialize settings with organization and app name
        self.settings = QSettings("LammpsScriptGenerator", "LammpsInputGenerator")
        
        # Emergency save timer
        self.emergency_save_timer = QTimer()
        self.emergency_save_timer.timeout.connect(self.emergency_save)
        self.emergency_save_timer.start(30000)  # Save every 30 seconds
        
        # Track widget references for focus jumping
        self.widget_references = {}
        
        # Track groupbox documentation links
        self.groupbox_doc_links = {}
        
        # Create main widget and layout
        self.main_widget = QWidget()
        self.setCentralWidget(self.main_widget)
        self.main_layout = QVBoxLayout(self.main_widget)
        
        # Create tab widget
        self.tab_widget = QTabWidget()
        self.main_layout.addWidget(self.tab_widget)
        
        # Create tabs
        self.create_system_tab()
        self.create_deformation_tab()
        self.create_output_tab()
        
        # Create bottom buttons
        self.create_bottom_buttons()
        
        # Load saved settings
        self.load_settings()
        
        # Set up exception handling for crash recovery
        sys.excepthook = self.handle_exception
        
    def handle_exception(self, exc_type, exc_value, exc_traceback):
        """Handle uncaught exceptions and save settings"""
        self.emergency_save()
        
        # Show error message
        try:
            QMessageBox.critical(self, "Application Error", 
                              f"The application encountered an error:\n{exc_type.__name__}: {exc_value}\n\n"
                              f"Your settings have been saved automatically.")
        except Exception:
            pass
        
        # Call original exception handler
        sys.__excepthook__(exc_type, exc_value, exc_traceback)
    
    def emergency_save(self):
        """Emergency save of current settings"""
        try:
            config = self.collect_config()
            emergency_file = os.path.join(tempfile.gettempdir(), "lammps_gui_emergency_save.json")
            with open(emergency_file, 'w') as f:
                json.dump(config, f, indent=2)
        except Exception as e:
            pass
    
    def create_system_tab(self):
        """Create the system configuration tab"""
        self.system_tab = QWidget()
        self.tab_widget.addTab(self.system_tab, "System Configuration")
        
        # Create scroll area
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll_widget = QWidget()
        scroll_layout = QVBoxLayout(scroll_widget)
        scroll.setWidget(scroll_widget)
        
        # Main layout for system tab
        system_layout = QVBoxLayout(self.system_tab)
        system_layout.addWidget(scroll)
        
        # System selection
        system_group = QGroupBox("System Selection")
        system_layout_main = QVBoxLayout()
        
        # Single field for file/directory selection
        selection_layout = QHBoxLayout()
        
        self.system_path_edit = QLineEdit()
        self.system_path_edit.setPlaceholderText("Select data file or directory containing data files")
        self.system_path_edit.setToolTip("Path to a single .data file or directory with multiple .data files")
        
        self.system_path_browse = QPushButton("Browse...")
        self.system_path_browse.clicked.connect(self.browse_system_path)
        self.system_path_browse.setToolTip("Browse for data file or directory")
        
        selection_layout.addWidget(self.system_path_edit)
        selection_layout.addWidget(self.system_path_browse)
        
        system_layout_main.addLayout(selection_layout)
        
        # System type display
        self.system_type_label = QLabel("System Type: Not selected")
        self.system_type_label.setStyleSheet("font-weight: bold;")
        system_layout_main.addWidget(self.system_type_label)
        
        # Update system type when path changes
        self.system_path_edit.textChanged.connect(self.update_system_type)
        
        system_group.setLayout(system_layout_main)
        scroll_layout.addWidget(system_group)
        
        # Potential file selection
        potential_group = QGroupBox("Potential File Selection")
        potential_layout = QFormLayout()
        
        self.use_potential_file = QCheckBox("Use separate potential file")
        self.use_potential_file.stateChanged.connect(self.toggle_potential_file)
        self.use_potential_file.setToolTip("Enable to use a separate potential file instead of inline potentials")
        
        self.potential_path_edit = QLineEdit()
        self.potential_path_edit.setEnabled(False)
        self.potential_path_browse = QPushButton("Browse...")
        self.potential_path_browse.setEnabled(False)
        self.potential_path_browse.clicked.connect(self.browse_potential_file)
        
        # Add tooltips
        self.potential_path_edit.setToolTip("Path to the potential file containing force field parameters")
        self.potential_path_browse.setToolTip("Browse for potential file")
        
        potential_path_layout = QHBoxLayout()
        potential_path_layout.addWidget(self.potential_path_edit)
        potential_path_layout.addWidget(self.potential_path_browse)
        
        potential_label = QLabel("Potential File Path:")
        potential_label.setStyleSheet("color: blue; text-decoration: underline;")
        try:
            potential_label.setCursor(QCursor(Qt.CursorShape.PointingHandCursor))
        except AttributeError:
            # Fallback for PyQt6 or environments where PointingHandCursor is not available
            pass
        potential_label.mousePressEvent = lambda e: self.open_lammps_doc("include")
        potential_label.setToolTip("Click to open LAMMPS include documentation")
        
        potential_layout.addRow(self.use_potential_file)
        potential_layout.addRow(potential_label, potential_path_layout)
        potential_group.setLayout(potential_layout)
        scroll_layout.addWidget(potential_group)
        
        # Basic LAMMPS settings
        basic_group = QGroupBox("Basic LAMMPS Settings")
        basic_layout = QFormLayout()
        
        self.atom_style_combo = QComboBox()
        self.atom_style_combo.addItems(["atomic", "bond", "molecular", "full", "charge", "dipole"])
        self.atom_style_combo.setToolTip("Specify the atom style for the simulation")
        
        atom_style_label = QLabel("Atom Style:")
        atom_style_label.setStyleSheet("color: blue; text-decoration: underline;")
        try:
            atom_style_label.setCursor(QCursor(Qt.CursorShape.PointingHandCursor))
        except AttributeError:
            pass
        atom_style_label.mousePressEvent = lambda e: self.open_lammps_doc("atom_style")
        atom_style_label.setToolTip("Click to open LAMMPS atom_style documentation")
        
        basic_layout.addRow(atom_style_label, self.atom_style_combo)
        basic_group.setLayout(basic_layout)
        scroll_layout.addWidget(basic_group)
        
        # Units selection (moved here from top)
        units_group = QGroupBox("Units Selection")
        units_layout = QHBoxLayout()
        
        units_label = QLabel("Units:")
        units_label.setStyleSheet("color: blue; text-decoration: underline;")
        try:
            units_label.setCursor(QCursor(Qt.CursorShape.PointingHandCursor))
        except AttributeError:
            pass
        units_label.mousePressEvent = lambda e: self.open_lammps_doc("units")
        units_label.setToolTip("Click to open LAMMPS units documentation")
        
        self.units_combo = QComboBox()
        self.units_combo.addItems(["lj", "real", "metal", "si", "cgs", "electron", "micro", "nano"])
        self.units_combo.setCurrentText("metal")
        self.units_combo.setToolTip("Select the unit system for the simulation")
        
        self.timestep_display = QLabel("Timestep unit: ps")
        self.timestep_display.setToolTip("Timestep unit based on selected units system")
        
        # Update timestep display when units change
        self.units_combo.currentTextChanged.connect(self.update_timestep_display)
        
        units_layout.addWidget(units_label)
        units_layout.addWidget(self.units_combo)
        units_layout.addWidget(self.timestep_display)
        units_layout.addStretch()
        
        units_group.setLayout(units_layout)
        scroll_layout.addWidget(units_group)
        
        # Boundary conditions
        boundary_group = QGroupBox("Boundary Conditions")
        boundary_layout = QFormLayout()
        
        self.boundary_x_combo = QComboBox()
        self.boundary_x_combo.addItems(["p", "f", "s", "m"])
        self.boundary_x_combo.setCurrentText("p")
        self.boundary_x_combo.setToolTip("X boundary condition: p=periodic, f=fixed, s=shrink, m=shrink-wrap")
        
        self.boundary_y_combo = QComboBox()
        self.boundary_y_combo.addItems(["p", "f", "s", "m"])
        self.boundary_y_combo.setCurrentText("p")
        self.boundary_y_combo.setToolTip("Y boundary condition: p=periodic, f=fixed, s=shrink, m=shrink-wrap")
        
        self.boundary_z_combo = QComboBox()
        self.boundary_z_combo.addItems(["p", "f", "s", "m"])
        self.boundary_z_combo.setCurrentText("p")
        self.boundary_z_combo.setToolTip("Z boundary condition: p=periodic, f=fixed, s=shrink, m=shrink-wrap")
        
        boundary_label = QLabel("Boundary Conditions:")
        boundary_label.setStyleSheet("color: blue; text-decoration: underline;")
        try:
            boundary_label.setCursor(QCursor(Qt.CursorShape.PointingHandCursor))
        except AttributeError:
            pass
        boundary_label.mousePressEvent = lambda e: self.open_lammps_doc("boundary")
        boundary_label.setToolTip("Click to open LAMMPS boundary documentation")
        
        boundary_layout.addRow("X Boundary:", self.boundary_x_combo)
        boundary_layout.addRow("Y Boundary:", self.boundary_y_combo)
        boundary_layout.addRow("Z Boundary:", self.boundary_z_combo)
        boundary_group.setLayout(boundary_layout)
        scroll_layout.addWidget(boundary_group)
        
        # Ensemble settings
        ensemble_group = QGroupBox("Ensemble Settings")
        ensemble_layout = QFormLayout()
        
        self.ensemble_combo = QComboBox()
        self.ensemble_combo.addItems(["NVT", "NPT"])
        self.ensemble_combo.setCurrentText("NVT")
        self.ensemble_combo.setToolTip("Select the thermodynamic ensemble for the simulation")
        
        self.temp_init = QDoubleSpinBox()
        self.temp_init.setRange(0, 10000)
        self.temp_init.setValue(300.0)
        self.temp_init.setSingleStep(10.0)
        self.temp_init.setToolTip("Initial temperature for the simulation")
        
        self.temp_end = QDoubleSpinBox()
        self.temp_end.setRange(0, 10000)
        self.temp_end.setValue(300.0)
        self.temp_end.setSingleStep(10.0)
        self.temp_end.setToolTip("Final temperature for the simulation")
        
        self.pressure = QDoubleSpinBox()
        self.pressure.setRange(0, 100000)
        self.pressure.setValue(1.0)
        self.pressure.setSingleStep(0.1)
        self.pressure.setEnabled(False)  # Only enabled for NPT
        self.pressure.setToolTip("Target pressure for NPT ensemble")
        
        ensemble_label = QLabel("Ensemble:")
        ensemble_label.setStyleSheet("color: blue; text-decoration: underline;")
        try:
            ensemble_label.setCursor(QCursor(Qt.CursorShape.PointingHandCursor))
        except AttributeError:
            pass
        ensemble_label.mousePressEvent = lambda e: self.open_lammps_doc("fix_nh")
        ensemble_label.setToolTip("Click to open LAMMPS ensemble documentation")
        
        ensemble_layout.addRow(ensemble_label, self.ensemble_combo)
        ensemble_layout.addRow("Initial Temperature:", self.temp_init)
        ensemble_layout.addRow("Final Temperature:", self.temp_end)
        ensemble_layout.addRow("Pressure (NPT only):", self.pressure)
        ensemble_group.setLayout(ensemble_layout)
        scroll_layout.addWidget(ensemble_group)
        
        # Velocity initialization settings
        velocity_group = QGroupBox("Velocity Initialization")
        velocity_layout = QVBoxLayout()
        
        self.enable_velocity = QCheckBox("Enable Velocity Initialization")
        self.enable_velocity.setChecked(True)
        self.enable_velocity.setToolTip("Enable initial velocity generation")
        self.enable_velocity.stateChanged.connect(self.toggle_velocity_settings)
        
        velocity_form_layout = QFormLayout()
        
        self.initial_velocity_seed = QSpinBox()
        self.initial_velocity_seed.setRange(1, 1000000)
        self.initial_velocity_seed.setValue(12345)
        self.initial_velocity_seed.setToolTip("Random seed for initial velocity generation")
        
        self.damping_factor = QDoubleSpinBox()
        self.damping_factor.setRange(0.1, 1000)
        self.damping_factor.setValue(100.0)
        self.damping_factor.setSingleStep(10.0)
        self.damping_factor.setToolTip("Damping factor as multiple of timestep")
        
        velocity_label = QLabel("Velocity Settings:")
        velocity_label.setStyleSheet("color: blue; text-decoration: underline;")
        try:
            velocity_label.setCursor(QCursor(Qt.CursorShape.PointingHandCursor))
        except AttributeError:
            pass
        velocity_label.mousePressEvent = lambda e: self.open_lammps_doc("velocity")
        velocity_label.setToolTip("Click to open LAMMPS velocity documentation")
        
        velocity_form_layout.addRow("Random Seed:", self.initial_velocity_seed)
        velocity_form_layout.addRow("Damping Factor:", self.damping_factor)
        
        velocity_layout.addWidget(self.enable_velocity)
        velocity_layout.addLayout(velocity_form_layout)
        velocity_group.setLayout(velocity_layout)
        scroll_layout.addWidget(velocity_group)
        
        # Neighbor settings
        neighbor_group = QGroupBox("Neighbor Settings")
        neighbor_layout = QFormLayout()
        
        self.neighbor_distance = QDoubleSpinBox()
        self.neighbor_distance.setRange(0, 100)
        self.neighbor_distance.setValue(0.3)
        self.neighbor_distance.setSingleStep(0.1)
        self.neighbor_distance.setToolTip("Cutoff distance for neighbor list building")
        
        self.neigh_modify_every = QSpinBox()
        self.neigh_modify_every.setRange(1, 1000)
        self.neigh_modify_every.setValue(1)
        self.neigh_modify_every.setToolTip("How often to rebuild neighbor list")
        
        self.neigh_modify_delay = QSpinBox()
        self.neigh_modify_delay.setRange(0, 1000)
        self.neigh_modify_delay.setValue(10)
        self.neigh_modify_delay.setToolTip("Delay between neighbor list builds")
        
        self.neigh_modify_check = QCheckBox("Enable neighbor checking")
        self.neigh_modify_check.setChecked(True)
        self.neigh_modify_check.setToolTip("Enable checking for neighbor list rebuilds")
        
        neighbor_label = QLabel("Neighbor Settings:")
        neighbor_label.setStyleSheet("color: blue; text-decoration: underline;")
        try:
            neighbor_label.setCursor(QCursor(Qt.CursorShape.PointingHandCursor))
        except AttributeError:
            pass
        neighbor_label.mousePressEvent = lambda e: self.open_lammps_doc("neighbor")
        neighbor_label.setToolTip("Click to open LAMMPS neighbor documentation")
        
        neighbor_layout.addRow("Neighbor Distance:", self.neighbor_distance)
        neighbor_layout.addRow("Neigh Modify Every:", self.neigh_modify_every)
        neighbor_layout.addRow("Neigh Modify Delay:", self.neigh_modify_delay)
        neighbor_layout.addRow(self.neigh_modify_check)
        neighbor_group.setLayout(neighbor_layout)
        scroll_layout.addWidget(neighbor_group)
        
        # Timestep settings
        timestep_group = QGroupBox("Timestep Settings")
        timestep_layout = QFormLayout()
        
        self.timestep = QDoubleSpinBox()
        self.timestep.setRange(0.0001, 1.0)
        self.timestep.setValue(0.001)
        self.timestep.setSingleStep(0.0001)
        self.timestep.setDecimals(4)
        self.timestep.setToolTip("Integration timestep for the simulation")
        
        timestep_label = QLabel("Timestep:")
        timestep_label.setStyleSheet("color: blue; text-decoration: underline;")
        try:
            timestep_label.setCursor(QCursor(Qt.CursorShape.PointingHandCursor))
        except AttributeError:
            pass
        timestep_label.mousePressEvent = lambda e: self.open_lammps_doc("timestep")
        timestep_label.setToolTip("Click to open LAMMPS timestep documentation")
        
        timestep_layout.addRow(timestep_label, self.timestep)
        timestep_group.setLayout(timestep_layout)
        scroll_layout.addWidget(timestep_group)
        
        # Connect ensemble combo box signal
        self.ensemble_combo.currentTextChanged.connect(self.toggle_ensemble_settings)
        
        # Add stretch to push everything up
        scroll_layout.addStretch()
        
    def toggle_ensemble_settings(self, ensemble):
        """Toggle pressure field based on ensemble selection"""
        self.pressure.setEnabled(ensemble == "NPT")
        
    def toggle_velocity_settings(self, state):
        """Toggle velocity initialization fields based on checkbox state"""
        enabled = state == Qt.CheckState.Checked.value
        self.initial_velocity_seed.setEnabled(enabled)
        self.damping_factor.setEnabled(enabled)
        
    def toggle_bond_breakage_settings(self, state):
        """Toggle bond breakage parameter fields based on checkbox state"""
        enabled = state == Qt.CheckState.Checked.value
        self.nevery.setEnabled(enabled)
        self.bondtype.setEnabled(enabled)
        self.rmax.setEnabled(enabled)
        self.enable_prob.setEnabled(enabled)
        self.toggle_probability_settings(self.enable_prob.checkState())
        
    def toggle_probability_settings(self, state):
        """Toggle probability parameter fields based on checkbox state"""
        enabled = state == Qt.CheckState.Checked.value
        self.prob_fraction.setEnabled(enabled)
        self.prob_seed.setEnabled(enabled)
        
    def update_system_type(self):
        """Update system type display based on selected path"""
        path = self.system_path_edit.text()
        if not path:
            self.system_type_label.setText("System Type: Not selected")
            return
            
        if os.path.isfile(path):
            if path.endswith('.data'):
                self.system_type_label.setText("System Type: Single file")
                # Auto-detect units and atom style from .data file
                self.auto_detect_from_data_file(path)
            else:
                self.system_type_label.setText("System Type: Single file (not .data)")
        elif os.path.isdir(path):
            # Count .data files in directory
            data_files = glob.glob(os.path.join(path, "*.data"))
            count = len(data_files)
            if count > 0:
                self.system_type_label.setText(f"System Type: Multiple files ({count} .data files found)")
                # Auto-detect units and atom style from first .data file
                self.auto_detect_from_data_file(data_files[0])
            else:
                self.system_type_label.setText("System Type: Directory (no .data files found)")
        else:
            self.system_type_label.setText("System Type: Path does not exist")
    
    def auto_detect_from_data_file(self, data_file):
        """Auto-detect units and atom style from .data file"""
        try:
            units = self.read_units_from_data_file(data_file)
            atom_style = self.read_atom_style_from_data_file(data_file)
            
            # Update units combo if found
            if units:
                index = self.units_combo.findText(units.lower())
                if index >= 0:
                    self.units_combo.setCurrentIndex(index)
                    self.update_timestep_display(units)
            
            # Update atom style combo if found
            if atom_style:
                index = self.atom_style_combo.findText(atom_style.lower())
                if index >= 0:
                    self.atom_style_combo.setCurrentIndex(index)
                    
        except Exception as e:
            print(f"Error auto-detecting from data file: {e}")
    
    def read_units_from_data_file(self, data_file):
        """Read units from LAMMPS data file"""
        try:
            with open(data_file, 'r') as f:
                for line in f:
                    if line.strip().startswith("units"):
                        # Extract units value (format: units <value>)
                        parts = line.split()
                        if len(parts) > 1:
                            units = parts[1].strip()
                            return units
        except Exception as e:
            print(f"Error reading units from data file: {e}")
        return None
    
    def read_atom_style_from_data_file(self, data_file):
        """Read atom style from LAMMPS data file"""
        try:
            with open(data_file, 'r') as f:
                for line in f:
                    if line.strip().startswith("atom_style"):
                        # Extract atom style value (format: atom_style <value>)
                        parts = line.split()
                        if len(parts) > 1:
                            atom_style = parts[1].strip()
                            return atom_style
        except Exception as e:
            print(f"Error reading atom style from data file: {e}")
        return None
            
    def update_timestep_display(self, units):
        """Update timestep unit display based on selected units"""
        # Timestep units from LAMMPS documentation as specified by user
        timestep_units = {
            "lj": "τ",
            "real": "fs", 
            "metal": "ps", 
            "si": "s",
            "cgs": "s",
            "electron": "fs",
            "micro": "µs",
            "nano": "ns"
        }
        
        unit = timestep_units.get(units.lower(), "ps")
        self.timestep_display.setText(f"Timestep unit: {unit}")
        
        # Update the actual timestep value (keep default values)
        if units == "lj":
            self.timestep.setValue(0.005)
        elif units == "real":
            self.timestep.setValue(1.0)
        elif units == "metal":
            self.timestep.setValue(0.001)
        elif units == "si":
            self.timestep.setValue(1.0e-8)
        elif units == "cgs":
            self.timestep.setValue(1.0e-8)
        elif units == "electron":
            self.timestep.setValue(0.001)
        elif units == "micro":
            self.timestep.setValue(2.0)
        elif units == "nano":
            self.timestep.setValue(0.00045)
        
    def create_deformation_tab(self):
        """Create the deformation processing tab with table-based approach"""
        self.deformation_tab = QWidget()
        self.tab_widget.addTab(self.deformation_tab, "Deformation Processing")
        
        # Create scroll area
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll_widget = QWidget()
        scroll_layout = QVBoxLayout(scroll_widget)
        scroll.setWidget(scroll_widget)
        
        # Main layout for deformation tab
        deformation_layout = QVBoxLayout(self.deformation_tab)
        deformation_layout.addWidget(scroll)
        
        # Deformation input mode
        input_group = QGroupBox("Deformation Input Mode")
        input_layout = QVBoxLayout()
        
        # Add explanation label
        explanation_label = QLabel("Select which parameter to calculate automatically:")
        explanation_label.setWordWrap(True)
        input_layout.addWidget(explanation_label)
        
        # Radio buttons for calculation mode
        calc_mode_layout = QHBoxLayout()
        
        self.calc_strain_rate = QRadioButton("Calculate Strain Rate")
        self.calc_engineering_strain = QRadioButton("Calculate Engineering Strain")
        self.calc_steps = QRadioButton("Calculate Steps")
        self.calc_engineering_strain.setChecked(True)  # Default to calculating engineering strain
        
        self.calc_strain_rate.setToolTip("Input Engineering Strain and Steps, calculate Strain Rate")
        self.calc_engineering_strain.setToolTip("Input Strain Rate and Steps, calculate Engineering Strain")
        self.calc_steps.setToolTip("Input Strain Rate and Engineering Strain, calculate Steps")
        
        calc_mode_layout.addWidget(self.calc_strain_rate)
        calc_mode_layout.addWidget(self.calc_engineering_strain)
        calc_mode_layout.addWidget(self.calc_steps)
        
        input_layout.addLayout(calc_mode_layout)
        
        # Add formula explanation
        formula_label = QLabel("Formula: Strain Rate = Engineering Strain / Steps")
        formula_label.setStyleSheet("font-style: italic; color: gray;")
        formula_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        input_layout.addWidget(formula_label)
        
        input_group.setLayout(input_layout)
        scroll_layout.addWidget(input_group)
        
        # Connect signals
        self.calc_strain_rate.toggled.connect(self.update_deformation_table_headers)
        self.calc_engineering_strain.toggled.connect(self.update_deformation_table_headers)
        self.calc_steps.toggled.connect(self.update_deformation_table_headers)
        
        # Deformation studies table
        studies_group = QGroupBox("Deformation Studies")
        studies_layout = QVBoxLayout()
        
        # Add documentation link for fix deform
        fix_deform_label = QLabel("Deformation Methods Documentation:")
        fix_deform_label.setStyleSheet("color: blue; text-decoration: underline; font-size: 10px;")
        try:
            fix_deform_label.setCursor(QCursor(Qt.CursorShape.PointingHandCursor))
        except AttributeError:
            pass
        fix_deform_label.mousePressEvent = lambda e: self.open_lammps_doc("fix_deform")
        fix_deform_label.setToolTip("Click to open LAMMPS fix deform documentation")
        studies_layout.addWidget(fix_deform_label)
        
        self.studies_table = QTableWidget()
        self.update_deformation_table_headers()
        self.studies_table.horizontalHeader().setStretchLastSection(True)
        self.studies_table.setMaximumHeight(300)
        self.studies_table.setToolTip("Table of deformation studies to process")
        
        # Connect cellChanged signal for auto-calculation
        self.studies_table.cellChanged.connect(self.on_table_cell_changed)
        
        # Add sample data
        self.studies_table.setRowCount(2)
        self.add_sample_study_data(0, "study1", "fix_deform", "0.001", "0.1", "100", "x", "final", "100")
        self.add_sample_study_data(1, "study2", "wall_movement", "0.0001", "0.2", "2000", "y", "positive", "200")
        
        studies_buttons_layout = QHBoxLayout()
        
        self.add_study_button = QPushButton("Add Study")
        self.add_study_button.clicked.connect(self.add_deformation_study)
        self.add_study_button.setToolTip("Add a new deformation study")
        
        self.remove_study_button = QPushButton("Remove Study")
        self.remove_study_button.clicked.connect(self.remove_deformation_study)
        self.remove_study_button.setToolTip("Remove selected deformation study")
        
        studies_buttons_layout.addWidget(self.add_study_button)
        studies_buttons_layout.addWidget(self.remove_study_button)
        studies_buttons_layout.addStretch()
        
        studies_layout.addWidget(self.studies_table)
        studies_layout.addLayout(studies_buttons_layout)
        studies_group.setLayout(studies_layout)
        scroll_layout.addWidget(studies_group)
        
        # Multi-system processing settings
        # Wall settings for wall movement
        wall_settings_group = QGroupBox("Wall Settings (for Wall Movement)")
        wall_settings_layout = QFormLayout()
        
        self.wall_thickness = QDoubleSpinBox()
        self.wall_thickness.setRange(0.1, 50.0)
        self.wall_thickness.setValue(5.0)
        self.wall_thickness.setSingleStep(1.0)
        self.wall_thickness.setDecimals(1)
        self.wall_thickness.setToolTip("Wall thickness as percentage of box size in deformation direction")
        
        wall_settings_label = QLabel("Wall Thickness (%):")
        wall_settings_label.setStyleSheet("color: blue; text-decoration: underline;")
        try:
            wall_settings_label.setCursor(QCursor(Qt.CursorShape.PointingHandCursor))
        except AttributeError:
            pass
        wall_settings_label.mousePressEvent = lambda e: self.open_lammps_doc("fix_wall")
        wall_settings_label.setToolTip("Click to open LAMMPS fix_wall documentation")
        
        wall_settings_layout.addRow(wall_settings_label, self.wall_thickness)
        wall_settings_group.setLayout(wall_settings_layout)
        scroll_layout.addWidget(wall_settings_group)
        
        # Bond breakage settings
        bond_breakage_group = QGroupBox("Bond Breakage Settings")
        bond_breakage_layout = QVBoxLayout()
        
        self.enable_bond_breakage = QCheckBox("Enable Bond Breakage")
        self.enable_bond_breakage.setToolTip("Enable bond breakage during deformation simulation")
        self.enable_bond_breakage.stateChanged.connect(self.toggle_bond_breakage_settings)
        
        bond_breakage_form_layout = QFormLayout()
        
        # Nevery parameter
        self.nevery = QSpinBox()
        self.nevery.setRange(1, 1000000)
        self.nevery.setValue(1)
        self.nevery.setEnabled(False)
        self.nevery.setToolTip("Attempt bond breaking every this many steps")
        
        # Bond type
        self.bondtype = QSpinBox()
        self.bondtype.setRange(1, 100)
        self.bondtype.setValue(1)
        self.bondtype.setEnabled(False)
        self.bondtype.setToolTip("Type of bonds to break (integer or type label)")
        
        # Rmax parameter
        self.rmax = QDoubleSpinBox()
        self.rmax.setRange(0, 1000)
        self.rmax.setValue(1.5)
        self.rmax.setSingleStep(0.1)
        self.rmax.setEnabled(False)
        self.rmax.setToolTip("Bond longer than Rmax can break (distance units)")
        
        # Probability options
        self.enable_prob = QCheckBox("Enable Probability")
        self.enable_prob.setChecked(False)
        self.enable_prob.setEnabled(False)
        self.enable_prob.setToolTip("Enable probabilistic bond breakage")
        self.enable_prob.stateChanged.connect(self.toggle_probability_settings)
        
        self.prob_fraction = QDoubleSpinBox()
        self.prob_fraction.setRange(0, 1)
        self.prob_fraction.setValue(0.1)
        self.prob_fraction.setSingleStep(0.01)
        self.prob_fraction.setEnabled(False)
        self.prob_fraction.setToolTip("Break a bond with this probability if otherwise eligible")
        
        self.prob_seed = QSpinBox()
        self.prob_seed.setRange(1, 1000000)
        self.prob_seed.setValue(12345)
        self.prob_seed.setEnabled(False)
        self.prob_seed.setToolTip("Random number seed (positive integer)")
        
        bond_breakage_form_layout.addRow("Nevery:", self.nevery)
        bond_breakage_form_layout.addRow("Bond Type:", self.bondtype)
        bond_breakage_form_layout.addRow("Rmax:", self.rmax)
        bond_breakage_form_layout.addRow(self.enable_prob)
        bond_breakage_form_layout.addRow("Probability:", self.prob_fraction)
        bond_breakage_form_layout.addRow("Seed:", self.prob_seed)
        
        bond_breakage_layout.addWidget(self.enable_bond_breakage)
        bond_breakage_layout.addLayout(bond_breakage_form_layout)
        bond_breakage_group.setLayout(bond_breakage_layout)
        scroll_layout.addWidget(bond_breakage_group)
        
        # Add stretch to push everything up
        scroll_layout.addStretch()
        
    def update_deformation_table_headers(self):
        """Update table headers and column states based on calculation mode"""
        # Always show all three columns
        headers = ["Name", "Method", "Strain Rate", "Engineering Strain", "Steps", "Axis", "Style", "Thermo Freq"]
        
        self.studies_table.setColumnCount(len(headers))
        self.studies_table.setHorizontalHeaderLabels(headers)
        
        # Determine which column should be read-only based on calculation mode
        if self.calc_strain_rate.isChecked():
            readonly_col = 2  # Strain Rate column
        elif self.calc_engineering_strain.isChecked():
            readonly_col = 3  # Engineering Strain column
        else:  # calc_steps.isChecked()
            readonly_col = 4  # Steps column
        
        # Update all rows to reflect the read-only column
        for row in range(self.studies_table.rowCount()):
            self.update_row_readonly_state(row, readonly_col)
    
    def update_row_readonly_state(self, row, readonly_col):
        """Update the read-only state of columns in a specific row"""
        # Strain Rate column (index 2)
        strain_rate_item = self.studies_table.item(row, 2)
        if strain_rate_item:
            if readonly_col == 2:
                strain_rate_item.setFlags(strain_rate_item.flags() & ~Qt.ItemFlag.ItemIsEditable)
                strain_rate_item.setForeground(QColor(128, 128, 128))  # Grey text
            else:
                strain_rate_item.setFlags(strain_rate_item.flags() | Qt.ItemFlag.ItemIsEditable)
                strain_rate_item.setForeground(QColor(0, 0, 0))  # Black text
        
        # Engineering Strain column (index 3)
        eng_strain_item = self.studies_table.item(row, 3)
        if eng_strain_item:
            if readonly_col == 3:
                eng_strain_item.setFlags(eng_strain_item.flags() & ~Qt.ItemFlag.ItemIsEditable)
                eng_strain_item.setForeground(QColor(128, 128, 128))  # Grey text
            else:
                eng_strain_item.setFlags(eng_strain_item.flags() | Qt.ItemFlag.ItemIsEditable)
                eng_strain_item.setForeground(QColor(0, 0, 0))  # Black text
        
        # Steps column (index 4)
        steps_item = self.studies_table.item(row, 4)
        if steps_item:
            if readonly_col == 4:
                steps_item.setFlags(steps_item.flags() & ~Qt.ItemFlag.ItemIsEditable)
                steps_item.setForeground(QColor(128, 128, 128))  # Grey text
            else:
                steps_item.setFlags(steps_item.flags() | Qt.ItemFlag.ItemIsEditable)
                steps_item.setForeground(QColor(0, 0, 0))  # Black text
    
    def calculate_deformation_parameter(self, row, changed_col):
        """Calculate the automatically determined parameter when values change"""
        try:
            # Get current values
            strain_rate_item = self.studies_table.item(row, 2)
            eng_strain_item = self.studies_table.item(row, 3)
            steps_item = self.studies_table.item(row, 4)
            
            if not all([strain_rate_item, eng_strain_item, steps_item]):
                return
            
            strain_rate = float(strain_rate_item.text())
            eng_strain = float(eng_strain_item.text())
            steps = int(steps_item.text())
            
            # Determine which parameter to calculate based on mode
            if self.calc_strain_rate.isChecked():
                # Calculate strain rate: strain_rate = engineering_strain / steps
                if steps > 0:
                    calculated_rate = eng_strain / steps
                    strain_rate_item.setText(f"{calculated_rate:.6f}")
            elif self.calc_engineering_strain.isChecked():
                # Calculate engineering strain: engineering_strain = strain_rate * steps
                calculated_strain = strain_rate * steps
                eng_strain_item.setText(f"{calculated_strain:.6f}")
            else:  # calc_steps.isChecked()
                # Calculate steps: steps = engineering_strain / strain_rate
                if strain_rate > 0:
                    calculated_steps = int(round(eng_strain / strain_rate))
                    if calculated_steps < 1:
                        calculated_steps = 1
                    steps_item.setText(str(calculated_steps))
                    
        except (ValueError, TypeError):
            # Invalid input, ignore calculation
            pass
        
    def add_sample_study_data(self, row, name, method, strain_rate, eng_strain, steps, axis, style_dir, thermo_freq):
        """Add sample study data to table with dropdowns for non-numeric fields"""
        # Name column (text)
        self.studies_table.setItem(row, 0, QTableWidgetItem(name))
        
        # Method column (dropdown)
        method_combo = QComboBox()
        method_combo.addItems(["fix_deform", "wall_movement"])
        method_combo.setCurrentText(method)
        method_combo.currentTextChanged.connect(lambda text, r=row: self.on_method_changed(r, text))
        self.studies_table.setCellWidget(row, 1, method_combo)
        
        # Strain Rate column (numeric - float)
        strain_rate_item = NumericTableWidgetItem(strain_rate, is_float=True, min_val=0.0, max_val=10.0)
        strain_rate_item.setData(Qt.ItemDataRole.UserRole, "strain_rate")
        self.studies_table.setItem(row, 2, strain_rate_item)
        
        # Engineering Strain column (numeric - float)
        eng_strain_item = NumericTableWidgetItem(eng_strain, is_float=True, min_val=0.0, max_val=10.0)
        eng_strain_item.setData(Qt.ItemDataRole.UserRole, "eng_strain")
        self.studies_table.setItem(row, 3, eng_strain_item)
        
        # Steps column (numeric - integer)
        steps_item = NumericTableWidgetItem(steps, is_float=False, min_val=1, max_val=1000000)
        steps_item.setData(Qt.ItemDataRole.UserRole, "steps")
        self.studies_table.setItem(row, 4, steps_item)
        
        # Axis column (dropdown)
        axis_combo = QComboBox()
        axis_combo.addItems(["x", "y", "z"])
        axis_combo.setCurrentText(axis)
        self.studies_table.setCellWidget(row, 5, axis_combo)
        
        # Style column (dropdown - context-aware based on method)
        style_combo = QComboBox()
        self.update_style_options(style_combo, method)
        style_combo.setCurrentText(style_dir)
        self.studies_table.setCellWidget(row, 6, style_combo)
        
        # Thermo Freq column (numeric - integer)
        thermo_item = NumericTableWidgetItem(thermo_freq, is_float=False, min_val=1, max_val=10000)
        self.studies_table.setItem(row, 7, thermo_item)
        
        # Update read-only state for this row
        if self.calc_strain_rate.isChecked():
            readonly_col = 2
        elif self.calc_engineering_strain.isChecked():
            readonly_col = 3
        else:
            readonly_col = 4
        self.update_row_readonly_state(row, readonly_col)
        
        # Perform initial calculation
        self.calculate_deformation_parameter(row, -1)
    
    def on_table_cell_changed(self, row, column):
        """Handle table cell changes and trigger auto-calculation for deformation parameters"""
        # Only handle changes in strain rate (2), engineering strain (3), or steps (4) columns
        if column in [2, 3, 4]:
            self.calculate_deformation_parameter(row, column)
        
    def update_style_options(self, style_combo, method):
        """Update style dropdown options based on method"""
        style_combo.clear()
        if method == "fix_deform":
            style_combo.addItems(["final", "linear", "volume"])
            style_combo.setToolTip("Deformation style for fix_deform")
        elif method == "wall_movement":
            style_combo.addItems(["positive", "negative", "symmetric"])
            style_combo.setToolTip("Wall movement direction")
        else:
            style_combo.addItems(["unknown"])
            
    def on_method_changed(self, row, new_method):
        """Handle method change and update style options"""
        style_combo = self.studies_table.cellWidget(row, 6)
        if style_combo:
            current_style = style_combo.currentText()
            self.update_style_options(style_combo, new_method)
            # Try to maintain current style if it exists in new options
            index = style_combo.findText(current_style)
            if index >= 0:
                style_combo.setCurrentIndex(index)
            else:
                style_combo.setCurrentIndex(0)
        
    def add_deformation_study(self):
        """Add a new deformation study to the table"""
        row_count = self.studies_table.rowCount()
        self.studies_table.setRowCount(row_count + 1)
        
        # Copy settings from the row above if available
        if row_count > 0:
            # Get values from previous row
            name_item = self.studies_table.item(row_count - 1, 0)
            method_combo = self.studies_table.cellWidget(row_count - 1, 1)
            strain_rate_item = self.studies_table.item(row_count - 1, 2)
            eng_strain_item = self.studies_table.item(row_count - 1, 3)
            steps_item = self.studies_table.item(row_count - 1, 4)
            axis_combo = self.studies_table.cellWidget(row_count - 1, 5)
            style_combo = self.studies_table.cellWidget(row_count - 1, 6)
            thermo_item = self.studies_table.item(row_count - 1, 7)
            
            name = name_item.text() if name_item else f"study{row_count + 1}"
            method = method_combo.currentText() if method_combo else "fix_deform"
            strain_rate = strain_rate_item.text() if strain_rate_item else "0.001"
            eng_strain = eng_strain_item.text() if eng_strain_item else "0.1"
            steps = steps_item.text() if steps_item else "100"
            axis = axis_combo.currentText() if axis_combo else "x"
            style = style_combo.currentText() if style_combo else "final"
            thermo = thermo_item.text() if thermo_item else "100"
            
            self.add_sample_study_data(row_count, name, method, strain_rate, eng_strain, steps, axis, style, thermo)
        else:
            # Set default values
            self.add_sample_study_data(row_count, f"study{row_count + 1}", "fix_deform", "0.001", "0.1", "100", "x", "final", "100")
        
    def remove_deformation_study(self):
        """Remove selected deformation study from the table"""
        current_row = self.studies_table.currentRow()
        if current_row >= 0:
            self.studies_table.removeRow(current_row)
        else:
            QMessageBox.warning(self, "Warning", "Please select a study to remove.")
            
    def create_output_tab(self):
        """Create the output options tab"""
        self.output_tab = QWidget()
        self.tab_widget.addTab(self.output_tab, "Output Options")
        
        # Create scroll area
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll_widget = QWidget()
        scroll_layout = QVBoxLayout(scroll_widget)
        scroll.setWidget(scroll_widget)
        
        # Main layout for output tab
        output_layout = QVBoxLayout(self.output_tab)
        output_layout.addWidget(scroll)
        
        # Output path settings
        path_group = QGroupBox("Output Path Settings")
        path_layout = QFormLayout()
        
        self.output_path_edit = QLineEdit()
        self.output_path_browse = QPushButton("Browse...")
        self.output_path_browse.clicked.connect(self.browse_output_path)
        
        # Add tooltips
        self.output_path_edit.setToolTip("Directory where output files will be saved")
        self.output_path_browse.setToolTip("Browse for output directory")
        
        # Add to widget references for focus jumping
        self.widget_references['output_path'] = self.output_path_edit
        
        output_path_layout = QHBoxLayout()
        output_path_layout.addWidget(self.output_path_edit)
        output_path_layout.addWidget(self.output_path_browse)
        
        path_layout.addRow("Output Path:", output_path_layout)
        path_group.setLayout(path_layout)
        scroll_layout.addWidget(path_group)
        
        # Trajectory output settings
        traj_group = QGroupBox("Trajectory Output Settings (LAMMPS dump Documentation)")
        traj_group.setStyleSheet("QGroupBox::title { color: blue; text-decoration: underline; }")
        # Make the group box title clickable
        traj_group.installEventFilter(self)
        self.groupbox_doc_links["traj_group"] = "dump"
        
        traj_layout = QVBoxLayout()
        
        self.enable_trajectory = QCheckBox("Enable Trajectory Output")
        self.enable_trajectory.setChecked(True)
        self.enable_trajectory.setToolTip("Enable trajectory file output")
        self.enable_trajectory.stateChanged.connect(self.toggle_trajectory_settings)
        
        traj_form_layout = QFormLayout()
        
        self.traj_format = QComboBox()
        self.traj_format.addItems(["lammpstrj", "xyz", "dcd"])
        self.traj_format.setToolTip("Format for trajectory files")
        
        self.trj_output_items = QTextEdit()
        self.trj_output_items.setPlainText("id type x y z fx fy fz")
        self.trj_output_items.setMaximumHeight(100)
        self.trj_output_items.setToolTip("Items to include in trajectory output")
        
        traj_form_layout.addRow("Trajectory Format:", self.traj_format)
        traj_form_layout.addRow("Output Items:", self.trj_output_items)
        
        traj_layout.addWidget(self.enable_trajectory)
        traj_layout.addLayout(traj_form_layout)
        traj_group.setLayout(traj_layout)
        scroll_layout.addWidget(traj_group)
        
        # Thermo output settings
        thermo_group = QGroupBox("Thermo Output Settings (LAMMPS thermo_style Documentation)")
        thermo_group.setStyleSheet("QGroupBox::title { color: blue; text-decoration: underline; }")
        thermo_group.installEventFilter(self)
        self.groupbox_doc_links["thermo_group"] = "thermo_style"
        
        thermo_layout = QVBoxLayout()
        
        self.enable_thermo = QCheckBox("Enable Thermo Output")
        self.enable_thermo.setChecked(True)
        self.enable_thermo.setToolTip("Enable thermodynamic output")
        self.enable_thermo.stateChanged.connect(self.toggle_thermo_settings)
        
        thermo_form_layout = QFormLayout()
        
        self.thermo_style = QTextEdit()
        self.thermo_style.setPlainText("step etotal pe ke epair ebond evdwl ecoul elong temp press pxx pyy pzz pxy pxz pyz lx ly lz density")
        self.thermo_style.setMaximumHeight(100)
        self.thermo_style.setToolTip("Thermo style specification")
        
        thermo_form_layout.addRow("Thermo Style:", self.thermo_style)
        
        thermo_layout.addWidget(self.enable_thermo)
        thermo_layout.addLayout(thermo_form_layout)
        thermo_group.setLayout(thermo_layout)
        scroll_layout.addWidget(thermo_group)
        
        # Stress calculations
        stress_group = QGroupBox("Stress Calculations (LAMMPS compute stress/atom Documentation)")
        stress_group.setStyleSheet("QGroupBox::title { color: blue; text-decoration: underline; }")
        stress_group.installEventFilter(self)
        self.groupbox_doc_links["stress_group"] = "compute_stress_atom"
        
        stress_layout = QVBoxLayout()
        
        self.enable_stress = QCheckBox("Enable Stress Calculations")
        self.enable_stress.setChecked(True)
        self.enable_stress.setToolTip("Enable stress tensor calculations")
        self.enable_stress.stateChanged.connect(self.toggle_stress_settings)
        
        stress_layout.addWidget(self.enable_stress)
        stress_group.setLayout(stress_layout)
        scroll_layout.addWidget(stress_group)
        
        # Custom computes
        custom_computes_group = QGroupBox("Custom Computes (LAMMPS compute Documentation)")
        custom_computes_group.setStyleSheet("QGroupBox::title { color: blue; text-decoration: underline; }")
        custom_computes_group.installEventFilter(self)
        self.groupbox_doc_links["custom_computes_group"] = "compute"
        custom_computes_layout = QVBoxLayout()
        
        self.enable_custom_computes = QCheckBox("Enable Custom Computes")
        self.enable_custom_computes.setChecked(False)
        self.enable_custom_computes.setToolTip("Enable custom compute commands")
        self.enable_custom_computes.stateChanged.connect(self.toggle_custom_computes)
        
        self.custom_computes_text = QTextEdit()
        self.custom_computes_text.setPlaceholderText("Enter custom compute commands here...")
        self.custom_computes_text.setMaximumHeight(100)
        self.custom_computes_text.setEnabled(False)
        self.custom_computes_text.setToolTip("Custom LAMMPS compute commands")
        
        custom_computes_layout.addWidget(self.enable_custom_computes)
        custom_computes_layout.addWidget(self.custom_computes_text)
        custom_computes_group.setLayout(custom_computes_layout)
        scroll_layout.addWidget(custom_computes_group)
        
        # Custom dumps
        custom_dumps_group = QGroupBox("Custom Dumps (LAMMPS dump Documentation)")
        custom_dumps_group.setStyleSheet("QGroupBox::title { color: blue; text-decoration: underline; }")
        custom_dumps_group.installEventFilter(self)
        self.groupbox_doc_links["custom_dumps_group"] = "dump"
        
        custom_dumps_layout = QVBoxLayout()
        
        self.enable_custom_dumps = QCheckBox("Enable Custom Dumps")
        self.enable_custom_dumps.setChecked(False)
        self.enable_custom_dumps.setToolTip("Enable custom dump commands")
        self.enable_custom_dumps.stateChanged.connect(self.toggle_custom_dumps)
        
        self.custom_dumps_text = QTextEdit()
        self.custom_dumps_text.setPlaceholderText("Enter custom dump commands here...")
        self.custom_dumps_text.setMaximumHeight(100)
        self.custom_dumps_text.setEnabled(False)
        self.custom_dumps_text.setToolTip("Custom LAMMPS dump commands")
        
        custom_dumps_layout.addWidget(self.enable_custom_dumps)
        custom_dumps_layout.addWidget(self.custom_dumps_text)
        custom_dumps_group.setLayout(custom_dumps_layout)
        scroll_layout.addWidget(custom_dumps_group)
        
        # Add stretch to push everything up
        scroll_layout.addStretch()
        
    def toggle_custom_computes(self, state):
        """Toggle custom computes text box based on checkbox state"""
        enabled = state == Qt.CheckState.Checked.value
        self.custom_computes_text.setEnabled(enabled)
        
    def toggle_custom_dumps(self, state):
        """Toggle custom dumps text box based on checkbox state"""
        enabled = state == Qt.CheckState.Checked.value
        self.custom_dumps_text.setEnabled(enabled)
        
    def create_bottom_buttons(self):
        """Create the bottom buttons"""
        button_layout = QHBoxLayout()
        
        # Generate button
        self.generate_button = QPushButton("Generate Scripts")
        self.generate_button.clicked.connect(self.generate_scripts)
        self.generate_button.setToolTip("Generate LAMMPS input scripts")
        
        # Save configuration button
        self.save_config_button = QPushButton("Save Configuration")
        self.save_config_button.clicked.connect(self.save_configuration)
        self.save_config_button.setToolTip("Save current configuration to file")
        
        # Load configuration button
        self.load_config_button = QPushButton("Load Configuration")
        self.load_config_button.clicked.connect(self.load_configuration)
        self.load_config_button.setToolTip("Load configuration from file")
        
        # Exit button
        self.exit_button = QPushButton("Exit")
        self.exit_button.clicked.connect(self.close)
        self.exit_button.setToolTip("Exit the application")
        
        button_layout.addWidget(self.generate_button)
        button_layout.addWidget(self.save_config_button)
        button_layout.addWidget(self.load_config_button)
        button_layout.addWidget(self.exit_button)
        
        self.main_layout.addLayout(button_layout)
        
    def browse_system_path(self):
        """Browse for system path (file or directory)"""
        # Let user choose between file and directory
        dialog = QDialog(self)
        dialog.setWindowTitle("Select System")
        dialog.setMinimumSize(300, 120)
        dialog.setWindowFlags(dialog.windowFlags() & ~Qt.WindowType.WindowContextHelpButtonHint)  # Remove help button
        
        layout = QVBoxLayout()
        
        label = QLabel("Select data file or directory containing data files:")
        layout.addWidget(label)
        
        button_layout = QHBoxLayout()
        
        file_button = QPushButton("Select File")
        dir_button = QPushButton("Select Directory")
        
        button_layout.addWidget(file_button)
        button_layout.addWidget(dir_button)
        
        layout.addLayout(button_layout)
        dialog.setLayout(layout)
        
        selected_path = None
        select_file = False
        
        def select_file_path():
            nonlocal selected_path, select_file
            file_path, _ = QFileDialog.getOpenFileName(dialog, "Select Data File", "", "Data Files (*.data);;All Files (*)")
            if file_path:
                selected_path = file_path
                select_file = True
                dialog.accept()
                
        def select_dir_path():
            nonlocal selected_path, select_file
            dir_path = QFileDialog.getExistingDirectory(dialog, "Select Directory")
            if dir_path:
                selected_path = dir_path
                select_file = False
                dialog.accept()
                
        file_button.clicked.connect(select_file_path)
        dir_button.clicked.connect(select_dir_path)
        
        if dialog.exec() == QDialog.DialogCode.Accepted and selected_path:
            self.system_path_edit.setText(selected_path)
    
    def browse_potential_file(self):
        """Browse for potential file"""
        file_path, _ = QFileDialog.getOpenFileName(self, "Select Potential File", "", "Potential files (*.pot *.potential);;All files (*)")
        if file_path:
            self.potential_path_edit.setText(file_path)
    
    def browse_output_path(self):
        """Browse for output path"""
        dir_path = QFileDialog.getExistingDirectory(self, "Select Output Directory")
        if dir_path:
            self.output_path_edit.setText(dir_path)
    
    def toggle_potential_file(self, state):
        """Toggle potential file settings"""
        enabled = state == Qt.CheckState.Checked.value
        self.potential_path_edit.setEnabled(enabled)
        self.potential_path_browse.setEnabled(enabled)
    
    def open_lammps_doc(self, command):
        """Open LAMMPS documentation for a specific command"""
        url = QUrl(f"https://docs.lammps.org/{command}.html")
        QDesktopServices.openUrl(url)
    
    def eventFilter(self, obj, event):
        """Event filter to handle clicks on groupbox titles"""
        if event.type() == event.Type.MouseButtonPress and event.button() == Qt.MouseButton.LeftButton:
            for widget, doc_command in self.groupbox_doc_links.items():
                if obj == getattr(self, widget, None):
                    self.open_lammps_doc(doc_command)
                    return True
        return super().eventFilter(obj, event)
    
    def toggle_trajectory_settings(self, state):
        """Toggle trajectory settings based on checkbox state"""
        enabled = state == Qt.CheckState.Checked.value
        self.traj_format.setEnabled(enabled)
        self.trj_output_items.setEnabled(enabled)
    
    def toggle_thermo_settings(self, state):
        """Toggle thermo settings based on checkbox state"""
        enabled = state == Qt.CheckState.Checked.value
        self.thermo_style.setEnabled(enabled)
    
    def toggle_stress_settings(self, state):
        """Toggle stress settings based on checkbox state"""
        enabled = state == Qt.CheckState.Checked.value
        # Stress calculations don't have additional settings currently, but added for consistency
    
    def toggle_custom_computes(self, state):
        """Toggle custom computes settings based on checkbox state"""
        enabled = state == Qt.CheckState.Checked.value
        self.custom_computes_text.setEnabled(enabled)
    
    def toggle_custom_dumps(self, state):
        """Toggle custom dumps settings based on checkbox state"""
        enabled = state == Qt.CheckState.Checked.value
        self.custom_dumps_text.setEnabled(enabled)
    
    def show_generated_files_dialog(self, result):
        """Show dialog with generated file structure"""
        dialog = QDialog(self)
        dialog.setWindowTitle("Generated Scripts")
        dialog.setMinimumSize(600, 400)
        dialog.setWindowFlags(dialog.windowFlags() & ~Qt.WindowType.WindowContextHelpButtonHint)
        
        layout = QVBoxLayout()
        
        # Title
        title_label = QLabel("Scripts Generated Successfully!")
        title_label.setStyleSheet("font-size: 16px; font-weight: bold; color: green;")
        title_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        layout.addWidget(title_label)
        
        # Message
        message_label = QLabel(result["message"])
        message_label.setWordWrap(True)
        layout.addWidget(message_label)
        
        # File structure
        files_label = QLabel("Generated File Structure:")
        files_label.setStyleSheet("font-weight: bold;")
        layout.addWidget(files_label)
        
        # Create text area for file structure
        file_structure_text = QTextEdit()
        file_structure_text.setReadOnly(True)
        file_structure_text.setMaximumHeight(200)
        
        # Generate file structure text
        structure_text = self.generate_file_structure_text(result.get("files", []))
        file_structure_text.setPlainText(structure_text)
        
        layout.addWidget(file_structure_text)
        
        # Instructions
        instructions_label = QLabel("Instructions:")
        instructions_label.setStyleSheet("font-weight: bold;")
        layout.addWidget(instructions_label)
        
        instructions_text = QTextEdit()
        instructions_text.setReadOnly(True)
        instructions_text.setMaximumHeight(100)
        instructions_text.setPlainText(
            "• run_all.sh: Local execution script. Run with: bash run_all.sh\n"
            "• lammps_simulation.job: Cluster job submission script. Submit with: sbatch lammps_simulation.job\n"
            "• All .in files are located in their respective study/system folders\n"
            "• Data files are copied to the input_files folder for easy access"
        )
        layout.addWidget(instructions_text)
        
        # Buttons
        button_box = QDialogButtonBox(QDialogButtonBox.StandardButton.Ok)
        button_box.accepted.connect(dialog.accept)
        layout.addWidget(button_box)
        
        dialog.setLayout(layout)
        dialog.exec()
    
    def generate_file_structure_text(self, files):
        """Generate text representation of file structure"""
        if not files:
            return "No files generated."
        
        # Get unique directories
        directories = set()
        for file_path in files:
            directories.add(os.path.dirname(file_path))
        
        structure_lines = ["Generated Files:"]
        
        # Add files by directory
        for directory in sorted(directories):
            dir_files = [f for f in files if os.path.dirname(f) == directory]
            if dir_files:
                structure_lines.append(f"\n{directory}/")
                for file_path in sorted(dir_files):
                    filename = os.path.basename(file_path)
                    structure_lines.append(f"  └── {filename}")
        
        return "\n".join(structure_lines)
    
    def apply_modern_stylesheet(self):
        """Apply modern stylesheet to the application"""
        stylesheet = """
        QMainWindow {
            background-color: #f5f5f5;
        }
        
        QTabWidget::pane {
            border: 1px solid #c0c0c0;
            background-color: #ffffff;
            border-radius: 4px;
        }
        
        QTabWidget::tab-bar {
            left: 5px;
        }
        
        QTabBar::tab {
            background-color: #e0e0e0;
            border: 1px solid #c0c0c0;
            border-bottom: none;
            border-top-left-radius: 4px;
            border-top-right-radius: 4px;
            padding: 8px 16px;
            margin-right: 2px;
        }
        
        QTabBar::tab:selected {
            background-color: #ffffff;
            border-bottom: 2px solid #007acc;
        }
        
        QTabBar::tab:hover {
            background-color: #f0f0f0;
        }
        
        QGroupBox {
            font-weight: bold;
            border: 2px solid #cccccc;
            border-radius: 6px;
            margin-top: 12px;
            padding-top: 10px;
            background-color: #fafafa;
        }
        
        QGroupBox::title {
            subcontrol-origin: margin;
            left: 10px;
            padding: 0 5px 0 5px;
        }
        
        QPushButton {
            background-color: #007acc;
            color: white;
            border: none;
            border-radius: 4px;
            padding: 8px 16px;
            font-weight: bold;
        }
        
        QPushButton:hover {
            background-color: #005a9e;
        }
        
        QPushButton:pressed {
            background-color: #004080;
        }
        
        QPushButton:disabled {
            background-color: #cccccc;
            color: #666666;
        }
        
        QLineEdit, QTextEdit, QComboBox, QSpinBox, QDoubleSpinBox {
            border: 1px solid #cccccc;
            border-radius: 4px;
            padding: 4px;
            background-color: white;
        }
        
        QLineEdit:focus, QTextEdit:focus, QComboBox:focus, QSpinBox:focus, QDoubleSpinBox:focus {
            border: 2px solid #007acc;
        }
        
        QCheckBox {
            spacing: 8px;
        }
        
        QCheckBox::indicator {
            width: 18px;
            height: 18px;
            border: 2px solid #cccccc;
            border-radius: 3px;
            background-color: white;
        }
        
        QCheckBox::indicator:checked {
            background-color: #007acc;
            border-color: #007acc;
        }
        
        QCheckBox::indicator:hover {
            border-color: #007acc;
        }
        
        QTableWidget {
            border: 1px solid #cccccc;
            border-radius: 4px;
            background-color: white;
            gridline-color: #e0e0e0;
        }
        
        QTableWidget::item {
            padding: 4px;
        }
        
        QTableWidget::item:selected {
            background-color: #007acc;
            color: white;
        }
        
        QHeaderView::section {
            background-color: #f0f0f0;
            padding: 4px;
            border: 1px solid #cccccc;
            font-weight: bold;
        }
        
        QScrollArea {
            border: none;
        }
        
        QLabel {
            color: #333333;
        }
        
        QToolTip {
            background-color: #ffffe1;
            border: 1px solid #cccccc;
            padding: 4px;
            border-radius: 3px;
        }
        """
        self.setStyleSheet(stylesheet)
    
    def collect_config(self):
        """Collect configuration from all GUI elements"""
        config = {
            "system": {
                "system_path": self.system_path_edit.text(),
                "use_potential_file": self.use_potential_file.isChecked(),
                "potential_file": self.potential_path_edit.text(),
                "atom_style": self.atom_style_combo.currentText(),
                "units": self.units_combo.currentText(),
                "boundary_x": self.boundary_x_combo.currentText(),
                "boundary_y": self.boundary_y_combo.currentText(),
                "boundary_z": self.boundary_z_combo.currentText(),
                "ensemble": self.ensemble_combo.currentText(),
                "temp_init": self.temp_init.value(),
                "temp_end": self.temp_end.value(),
                "pressure": self.pressure.value(),
                "enable_velocity": self.enable_velocity.isChecked(),
                "initial_velocity_seed": self.initial_velocity_seed.value(),
                "damping_factor": self.damping_factor.value(),
                "neighbor_distance": self.neighbor_distance.value(),
                "neigh_modify_every": self.neigh_modify_every.value(),
                "neigh_modify_delay": self.neigh_modify_delay.value(),
                "neigh_modify_check": self.neigh_modify_check.isChecked(),
                "timestep": self.timestep.value()
            },
            "deformation": {
                "wall_thickness": self.wall_thickness.value(),
                "enable_bond_breakage": self.enable_bond_breakage.isChecked(),
                "nevery": self.nevery.value(),
                "bondtype": self.bondtype.value(),
                "rmax": self.rmax.value(),
                "enable_prob": self.enable_prob.isChecked(),
                "prob_fraction": self.prob_fraction.value(),
                "prob_seed": self.prob_seed.value()
            },
            "output": {
                "output_path": self.output_path_edit.text(),
                "enable_trajectory": self.enable_trajectory.isChecked(),
                "traj_format": self.traj_format.currentText(),
                "trj_output_items": self.trj_output_items.toPlainText(),
                "enable_thermo": self.enable_thermo.isChecked(),
                "thermo_style": self.thermo_style.toPlainText(),
                "enable_stress": self.enable_stress.isChecked(),
                "enable_custom_computes": self.enable_custom_computes.isChecked(),
                "custom_computes": self.custom_computes_text.toPlainText(),
                "enable_custom_dumps": self.enable_custom_dumps.isChecked(),
                "custom_dumps": self.custom_dumps_text.toPlainText()
            },
            "cluster": {
                "execution_mode": self.execution_mode_combo.currentText(),
                "lammps_command": self.lammps_command_edit.text(),
                "threads": self.threads_spin.value(),
                "cluster_partition": self.cluster_partition.text(),
                "cluster_nodes": self.cluster_nodes.value(),
                "cluster_ntasks": self.cluster_ntasks.value(),
                "cluster_time": self.cluster_time.text(),
                "cluster_mail": self.cluster_mail.text(),
                "cluster_mail_type": self.cluster_mail_type.currentText(),
                "auto_submit": self.auto_submit.isChecked(),
                "show_command": self.show_command.isChecked(),
                "save_scripts_only": self.save_scripts_only.isChecked()
            },
            "multistudy": {
                "deform_studies": []
            }
        }
        
        # Collect deformation studies
        for row in range(self.studies_table.rowCount()):
            study = {
                "name": self.studies_table.item(row, 0).text(),
                "method": self.studies_table.cellWidget(row, 1).currentText(),
                "strain_rate": float(self.studies_table.item(row, 2).text()),
                "engineering_strain": float(self.studies_table.item(row, 3).text()),
                "steps": int(self.studies_table.item(row, 4).text()),
                "axis": self.studies_table.cellWidget(row, 5).currentText(),
                "style_dir": self.studies_table.cellWidget(row, 6).currentText(),
                "thermo_freq": int(self.studies_table.item(row, 7).text())
            }
            config["multistudy"]["deform_studies"].append(study)
        
        return config
    
    def load_settings(self):
        """Load settings from QSettings"""
        try:
            # System settings
            system_path = self.settings.value("system/system_path", "")
            if system_path:
                self.system_path_edit.setText(system_path)
            
            self.use_potential_file.setChecked(self.settings.value("system/use_potential_file", False, type=bool))
            potential_file = self.settings.value("system/potential_file", "")
            if potential_file:
                self.potential_path_edit.setText(potential_file)
            
            self.atom_style_combo.setCurrentText(self.settings.value("system/atom_style", "atomic"))
            self.units_combo.setCurrentText(self.settings.value("system/units", "metal"))
            self.boundary_x_combo.setCurrentText(self.settings.value("system/boundary_x", "p"))
            self.boundary_y_combo.setCurrentText(self.settings.value("system/boundary_y", "p"))
            self.boundary_z_combo.setCurrentText(self.settings.value("system/boundary_z", "p"))
            self.ensemble_combo.setCurrentText(self.settings.value("system/ensemble", "NVT"))
            self.temp_init.setValue(self.settings.value("system/temp_init", 300.0, type=float))
            self.temp_end.setValue(self.settings.value("system/temp_end", 300.0, type=float))
            self.pressure.setValue(self.settings.value("system/pressure", 1.0, type=float))
            self.enable_velocity.setChecked(self.settings.value("system/enable_velocity", True, type=bool))
            self.initial_velocity_seed.setValue(self.settings.value("system/initial_velocity_seed", 12345, type=int))
            self.damping_factor.setValue(self.settings.value("system/damping_factor", 100.0, type=float))
            self.neighbor_distance.setValue(self.settings.value("system/neighbor_distance", 0.3, type=float))
            self.neigh_modify_every.setValue(self.settings.value("system/neigh_modify_every", 1, type=int))
            self.neigh_modify_delay.setValue(self.settings.value("system/neigh_modify_delay", 10, type=int))
            self.neigh_modify_check.setChecked(self.settings.value("system/neigh_modify_check", True, type=bool))
            self.timestep.setValue(self.settings.value("system/timestep", 0.001, type=float))
            
            # Deformation settings
            self.wall_thickness.setValue(self.settings.value("deformation/wall_thickness", 5.0, type=float))
            self.enable_bond_breakage.setChecked(self.settings.value("deformation/enable_bond_breakage", False, type=bool))
            self.nevery.setValue(self.settings.value("deformation/nevery", 1, type=int))
            self.bondtype.setValue(self.settings.value("deformation/bondtype", 1, type=int))
            self.rmax.setValue(self.settings.value("deformation/rmax", 1.5, type=float))
            self.enable_prob.setChecked(self.settings.value("deformation/enable_prob", False, type=bool))
            self.prob_fraction.setValue(self.settings.value("deformation/prob_fraction", 0.1, type=float))
            self.prob_seed.setValue(self.settings.value("deformation/prob_seed", 12345, type=int))
            
            # Output settings
            self.output_path_edit.setText(self.settings.value("output/output_path", ""))
            self.enable_trajectory.setChecked(self.settings.value("output/enable_trajectory", True, type=bool))
            self.traj_format.setCurrentText(self.settings.value("output/traj_format", "lammpstrj"))
            self.trj_output_items.setPlainText(self.settings.value("output/trj_output_items", "id type x y z fx fy fz"))
            self.enable_thermo.setChecked(self.settings.value("output/enable_thermo", True, type=bool))
            self.thermo_style.setPlainText(self.settings.value("output/thermo_style", "step etotal pe ke epair ebond evdwl ecoul elong temp press pxx pyy pzz pxy pxz pyz lx ly lz density"))
            self.enable_stress.setChecked(self.settings.value("output/enable_stress", True, type=bool))
            self.enable_custom_computes.setChecked(self.settings.value("output/enable_custom_computes", False, type=bool))
            self.custom_computes_text.setPlainText(self.settings.value("output/custom_computes", ""))
            self.enable_custom_dumps.setChecked(self.settings.value("output/enable_custom_dumps", False, type=bool))
            self.custom_dumps_text.setPlainText(self.settings.value("output/custom_dumps", ""))
            
            # Cluster settings
            self.execution_mode_combo.setCurrentText(self.settings.value("cluster/execution_mode", "local"))
            self.lammps_command_edit.setText(self.settings.value("cluster/lammps_command", "lmp"))
            self.threads_spin.setValue(self.settings.value("cluster/threads", 4, type=int))
            self.cluster_partition.setText(self.settings.value("cluster/cluster_partition", "singlenode"))
            self.cluster_nodes.setValue(self.settings.value("cluster/cluster_nodes", 1, type=int))
            self.cluster_ntasks.setValue(self.settings.value("cluster/cluster_ntasks", 72, type=int))
            self.cluster_time.setText(self.settings.value("cluster/cluster_time", "24:00:00"))
            self.cluster_mail.setText(self.settings.value("cluster/cluster_mail", ""))
            self.cluster_mail_type.setCurrentText(self.settings.value("cluster/cluster_mail_type", "ALL"))
            self.auto_submit.setChecked(self.settings.value("cluster/auto_submit", False, type=bool))
            self.show_command.setChecked(self.settings.value("cluster/show_command", True, type=bool))
            self.save_scripts_only.setChecked(self.settings.value("cluster/save_scripts_only", False, type=bool))
            
            # Multi-study settings
            
            # Load deformation studies
            studies_data = self.settings.value("multistudy/deform_studies")
            if studies_data:
                try:
                    studies = json.loads(studies_data)
                    self.studies_table.setRowCount(len(studies))
                    for i, study in enumerate(studies):
                        self.add_sample_study_data(
                            i, study.get("name", f"study{i+1}"),
                            study.get("method", "fix_deform"),
                            str(study.get("strain_rate", 0.001)),
                            str(study.get("engineering_strain", 0.1)),
                            str(study.get("steps", 100)),
                            study.get("axis", "x"),
                            study.get("style_dir", "final"),
                            str(study.get("thermo_freq", 100))
                        )
                except Exception as e:
                    print(f"Error loading deformation studies: {e}")
            
        except Exception as e:
            print(f"Error loading settings: {e}")
    
    def save_settings(self):
        """Save settings to QSettings"""
        try:
            config = self.collect_config()
            
            # Save system settings
            for key, value in config["system"].items():
                self.settings.setValue(f"system/{key}", value)
            
            # Save deformation settings
            for key, value in config["deformation"].items():
                self.settings.setValue(f"deformation/{key}", value)
            
            # Save output settings
            for key, value in config["output"].items():
                self.settings.setValue(f"output/{key}", value)
            
            # Save cluster settings
            for key, value in config["cluster"].items():
                self.settings.setValue(f"cluster/{key}", value)
            
            # Save multi-study settings
            for key, value in config["multistudy"].items():
                if key == "deform_studies":
                    self.settings.setValue(f"multistudy/{key}", json.dumps(value))
                else:
                    self.settings.setValue(f"multistudy/{key}", value)
            
        except Exception as e:
            print(f"Error saving settings: {e}")
    
    def generate_scripts(self):
        """Generate LAMMPS scripts based on current configuration"""
        try:
            # Collect configuration
            config = self.collect_config()
            
            # Validate configuration
            if not config["system"]["system_path"]:
                QMessageBox.warning(self, "Warning", "Please select a system path.")
                return
            
            if not config["multistudy"]["deform_studies"]:
                QMessageBox.warning(self, "Warning", "Please define at least one deformation study.")
                return
            
            # Generate scripts
            if LammpsScriptGenerator:
                generator = LammpsScriptGenerator(config)
                result = generator.generate_all_scripts()
                
                if result["success"]:
                    self.show_generated_files_dialog(result)
                else:
                    QMessageBox.critical(self, "Error", result["message"])
            else:
                QMessageBox.critical(self, "Error", "Script generator not available.")
                
        except Exception as e:
            QMessageBox.critical(self, "Error", f"Error generating scripts: {str(e)}")
    
    def show_generated_scripts(self, files):
        """Show dialog with generated scripts and commands"""
        dialog = QDialog(self)
        dialog.setWindowTitle("Generated Scripts")
        dialog.setMinimumSize(600, 400)
        
        layout = QVBoxLayout()
        
        # Create text area to show file list
        text_area = QTextEdit()
        text_area.setReadOnly(True)
        
        file_list = "Generated Files:\n\n"
        for file_path in files:
            file_list += f"- {file_path}\n"
        
        text_area.setPlainText(file_list)
        layout.addWidget(text_area)
        
        # Add buttons
        button_layout = QHBoxLayout()
        
        copy_button = QPushButton("Copy to Clipboard")
        copy_button.clicked.connect(lambda: QApplication.clipboard().setText(file_list))
        
        close_button = QPushButton("Close")
        close_button.clicked.connect(dialog.accept)
        
        button_layout.addWidget(copy_button)
        button_layout.addWidget(close_button)
        
        layout.addLayout(button_layout)
        dialog.setLayout(layout)
        dialog.exec()
    
    def save_configuration(self):
        """Save current configuration to file"""
        try:
            file_path, _ = QFileDialog.getSaveFileName(self, "Save Configuration", "", "JSON Files (*.json);;All Files (*)")
            if file_path:
                config = self.collect_config()
                with open(file_path, 'w') as f:
                    json.dump(config, f, indent=2)
                QMessageBox.information(self, "Success", f"Configuration saved to {file_path}")
        except Exception as e:
            QMessageBox.critical(self, "Error", f"Error saving configuration: {str(e)}")
    
    def load_configuration(self):
        """Load configuration from file"""
        try:
            file_path, _ = QFileDialog.getOpenFileName(self, "Load Configuration", "", "JSON Files (*.json);;All Files (*)")
            if file_path:
                with open(file_path, 'r') as f:
                    config = json.load(f)
                
                # Apply configuration to GUI
                self.apply_config(config)
                QMessageBox.information(self, "Success", f"Configuration loaded from {file_path}")
        except Exception as e:
            QMessageBox.critical(self, "Error", f"Error loading configuration: {str(e)}")
    
    def apply_config(self, config):
        """Apply configuration to GUI elements"""
        try:
            # System configuration
            if "system" in config:
                system = config["system"]
                self.system_path_edit.setText(system.get("system_path", ""))
                self.use_potential_file.setChecked(system.get("use_potential_file", False))
                self.potential_path_edit.setText(system.get("potential_file", ""))
                self.atom_style_combo.setCurrentText(system.get("atom_style", "atomic"))
                self.units_combo.setCurrentText(system.get("units", "metal"))
                self.boundary_x_combo.setCurrentText(system.get("boundary_x", "p"))
                self.boundary_y_combo.setCurrentText(system.get("boundary_y", "p"))
                self.boundary_z_combo.setCurrentText(system.get("boundary_z", "p"))
                self.ensemble_combo.setCurrentText(system.get("ensemble", "NVT"))
                self.temp_init.setValue(system.get("temp_init", 300.0))
                self.temp_end.setValue(system.get("temp_end", 300.0))
                self.pressure.setValue(system.get("pressure", 1.0))
                self.enable_velocity.setChecked(system.get("enable_velocity", True))
                self.initial_velocity_seed.setValue(system.get("initial_velocity_seed", 12345))
                self.damping_factor.setValue(system.get("damping_factor", 100.0))
                self.neighbor_distance.setValue(system.get("neighbor_distance", 0.3))
                self.neigh_modify_every.setValue(system.get("neigh_modify_every", 1))
                self.neigh_modify_delay.setValue(system.get("neigh_modify_delay", 10))
                self.neigh_modify_check.setChecked(system.get("neigh_modify_check", True))
                self.timestep.setValue(system.get("timestep", 0.001))
            
            # Deformation configuration
            if "deformation" in config:
                deformation = config["deformation"]
                self.wall_thickness.setValue(deformation.get("wall_thickness", 5.0))
                self.enable_bond_breakage.setChecked(deformation.get("enable_bond_breakage", False))
                self.nevery.setValue(deformation.get("nevery", 1))
                self.bondtype.setValue(deformation.get("bondtype", 1))
                self.rmax.setValue(deformation.get("rmax", 1.5))
                self.enable_prob.setChecked(deformation.get("enable_prob", False))
                self.prob_fraction.setValue(deformation.get("prob_fraction", 0.1))
                self.prob_seed.setValue(deformation.get("prob_seed", 12345))
            
            # Output configuration
            if "output" in config:
                output = config["output"]
                self.output_path_edit.setText(output.get("output_path", ""))
                self.enable_trajectory.setChecked(output.get("enable_trajectory", True))
                self.traj_format.setCurrentText(output.get("traj_format", "lammpstrj"))
                self.trj_output_items.setPlainText(output.get("trj_output_items", "id type x y z fx fy fz"))
                self.enable_thermo.setChecked(output.get("enable_thermo", True))
                self.thermo_style.setPlainText(output.get("thermo_style", "step etotal pe ke epair ebond evdwl ecoul elong temp press pxx pyy pzz pxy pxz pyz lx ly lz density"))
                self.enable_stress.setChecked(output.get("enable_stress", True))
                self.enable_custom_computes.setChecked(output.get("enable_custom_computes", False))
                self.custom_computes_text.setPlainText(output.get("custom_computes", ""))
                self.enable_custom_dumps.setChecked(output.get("enable_custom_dumps", False))
                self.custom_dumps_text.setPlainText(output.get("custom_dumps", ""))
            
            # Cluster configuration
            if "cluster" in config:
                cluster = config["cluster"]
                self.execution_mode_combo.setCurrentText(cluster.get("execution_mode", "local"))
                self.lammps_command_edit.setText(cluster.get("lammps_command", "lmp"))
                self.threads_spin.setValue(cluster.get("threads", 4))
                self.cluster_partition.setText(cluster.get("cluster_partition", "singlenode"))
                self.cluster_nodes.setValue(cluster.get("cluster_nodes", 1))
                self.cluster_ntasks.setValue(cluster.get("cluster_ntasks", 72))
                self.cluster_time.setText(cluster.get("cluster_time", "24:00:00"))
                self.cluster_mail.setText(cluster.get("cluster_mail", ""))
                self.cluster_mail_type.setCurrentText(cluster.get("cluster_mail_type", "ALL"))
                self.auto_submit.setChecked(cluster.get("auto_submit", False))
                self.show_command.setChecked(cluster.get("show_command", True))
                self.save_scripts_only.setChecked(cluster.get("save_scripts_only", False))
            
            # Multi-study configuration
            if "multistudy" in config:
                multistudy = config["multistudy"]
                
                # Load deformation studies
                studies = multistudy.get("deform_studies", [])
                self.studies_table.setRowCount(len(studies))
                for i, study in enumerate(studies):
                    self.add_sample_study_data(
                        i, study.get("name", f"study{i+1}"),
                        study.get("method", "fix_deform"),
                        str(study.get("strain_rate", 0.001)),
                        str(study.get("engineering_strain", 0.1)),
                        str(study.get("steps", 100)),
                        study.get("axis", "x"),
                        study.get("style_dir", "final"),
                        str(study.get("thermo_freq", 100))
                    )
            
        except Exception as e:
            print(f"Error applying configuration: {e}")

def main():
    """Main function to run the application"""
    app = QApplication(sys.argv)
    app.setStyle('Fusion')
    
    # Create and show the main window
    window = LammpsScriptGenerator()
    window.show()
    
    # Run the application
    sys.exit(app.exec())

if __name__ == "__main__":
    main()