#!/usr/bin/env python3
"""
LAMMPS Input Script Generator GUI - PyQt6 Only Version

A graphical user interface for creating LAMMPS input scripts for particle-based deformation simulations.
Supports both local execution and cluster job submission.
This version uses PyQt6 only and is designed to work without additional installations.
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
    from script_generator import LammpsScriptGenerator as ScriptGen
except ImportError as e:
    ScriptGen = None

class NumericTableWidgetItem(QTableWidgetItem):
    """Custom table widget item that validates numeric input"""
    
    def __init__(self, value=0.0, is_float=True, min_val=None, max_val=None):
        super().__init__(str(value))
        self.is_float = is_float
        self.min_val = min_val
        self.max_val = max_val
        self.setTextAlignment(Qt.AlignRight | Qt.AlignVCenter)
        
    def setData(self, role, value):
        if role == Qt.EditRole:
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
        
        # Initialize settings with organization and app name
        self.settings = QSettings("LammpsScriptGenerator", "LammpsInputGenerator")
        
        # Emergency save timer
        self.emergency_save_timer = QTimer()
        self.emergency_save_timer.timeout.connect(self.emergency_save)
        self.emergency_save_timer.start(30000)  # Save every 30 seconds
        
        # Track widget references for focus jumping
        self.widget_references = {}
        
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
        self.create_cluster_tab()
        
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
            potential_label.setCursor(QCursor(Qt.PointingHandCursor))
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
            atom_style_label.setCursor(QCursor(Qt.PointingHandCursor))
        except AttributeError:
            # Fallback for PyQt6 or environments where PointingHandCursor is not available
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
            units_label.setCursor(QCursor(Qt.PointingHandCursor))
        except AttributeError:
            # Fallback for PyQt6 or environments where PointingHandCursor is not available
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
            boundary_label.setCursor(QCursor(Qt.PointingHandCursor))
        except AttributeError:
            # Fallback for PyQt6 or environments where PointingHandCursor is not available
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
            ensemble_label.setCursor(QCursor(Qt.PointingHandCursor))
        except AttributeError:
            # Fallback for PyQt6 or environments where PointingHandCursor is not available
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
        
        # Add documentation link for velocity initialization
        velocity_doc_label = QLabel("Velocity Initialization Documentation:")
        velocity_doc_label.setStyleSheet("color: blue; text-decoration: underline; font-size: 10px;")
        try:
            velocity_doc_label.setCursor(QCursor(Qt.PointingHandCursor))
        except AttributeError:
            # Fallback for PyQt6 or environments where PointingHandCursor is not available
            pass
        velocity_doc_label.mousePressEvent = lambda e: self.open_lammps_doc("velocity")
        velocity_doc_label.setToolTip("Click to open LAMMPS velocity documentation")
        velocity_layout.addWidget(velocity_doc_label)
        
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
        self.damping_factor.setToolTip("Damping factor for velocity initialization")
        
        velocity_form_layout.addRow("Random Seed:", self.initial_velocity_seed)
        velocity_form_layout.addRow("Damping Factor:", self.damping_factor)
        
        velocity_layout.addWidget(self.enable_velocity)
        velocity_layout.addLayout(velocity_form_layout)
        velocity_group.setLayout(velocity_layout)
        scroll_layout.addWidget(velocity_group)
        
        # Connect ensemble change to pressure enable/disable
        self.ensemble_combo.currentTextChanged.connect(self.toggle_pressure_settings)
        
        scroll_layout.addStretch()
    
    def create_deformation_tab(self):
        """Create the deformation configuration tab"""
        self.deformation_tab = QWidget()
        self.tab_widget.addTab(self.deformation_tab, "Deformation Configuration")
        
        # Create scroll area
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll_widget = QWidget()
        scroll_layout = QVBoxLayout(scroll_widget)
        scroll.setWidget(scroll_widget)
        
        # Main layout for deformation tab
        deformation_layout = QVBoxLayout(self.deformation_tab)
        deformation_layout.addWidget(scroll)
        
        # Deformation type selection
        deform_type_group = QGroupBox("Deformation Type")
        deform_type_layout = QVBoxLayout()
        
        self.uniaxial_radio = QRadioButton("Uniaxial Deformation")
        self.uniaxial_radio.setChecked(True)
        self.uniaxial_radio.setToolTip("Apply deformation along a single axis")
        
        self.biaxial_radio = QRadioButton("Biaxial Deformation")
        self.biaxial_radio.setToolTip("Apply deformation along two axes")
        
        self.triaxial_radio = QRadioButton("Triaxial Deformation")
        self.triaxial_radio.setToolTip("Apply deformation along all three axes")
        
        self.shear_radio = QRadioButton("Shear Deformation")
        self.shear_radio.setToolTip("Apply shear deformation")
        
        deform_type_layout.addWidget(self.uniaxial_radio)
        deform_type_layout.addWidget(self.biaxial_radio)
        deform_type_layout.addWidget(self.triaxial_radio)
        deform_type_layout.addWidget(self.shear_radio)
        
        deform_type_group.setLayout(deform_type_layout)
        scroll_layout.addWidget(deform_type_group)
        
        # Deformation parameters
        deform_params_group = QGroupBox("Deformation Parameters")
        deform_params_layout = QFormLayout()
        
        # Deformation rate
        self.deform_rate = QDoubleSpinBox()
        self.deform_rate.setRange(1e-10, 1e10)
        self.deform_rate.setValue(0.001)
        self.deform_rate.setSingleStep(0.0001)
        self.deform_rate.setDecimals(6)
        self.deform_rate.setToolTip("Deformation rate (strain per time unit)")
        
        # Start strain
        self.start_strain = QDoubleSpinBox()
        self.start_strain.setRange(-10, 10)
        self.start_strain.setValue(0.0)
        self.start_strain.setSingleStep(0.01)
        self.start_strain.setToolTip("Starting strain value")
        
        # End strain
        self.end_strain = QDoubleSpinBox()
        self.end_strain.setRange(-10, 10)
        self.end_strain.setValue(1.0)
        self.end_strain.setSingleStep(0.01)
        self.end_strain.setToolTip("Ending strain value")
        
        # Deformation axis (for uniaxial)
        self.deform_axis_combo = QComboBox()
        self.deform_axis_combo.addItems(["x", "y", "z"])
        self.deform_axis_combo.setCurrentText("z")
        self.deform_axis_combo.setToolTip("Axis along which to apply deformation")
        
        # Fix deform documentation link
        deform_doc_label = QLabel("Fix Deform Documentation:")
        deform_doc_label.setStyleSheet("color: blue; text-decoration: underline; font-size: 10px;")
        try:
            deform_doc_label.setCursor(QCursor(Qt.PointingHandCursor))
        except AttributeError:
            # Fallback for PyQt6 or environments where PointingHandCursor is not available
            pass
        deform_doc_label.mousePressEvent = lambda e: self.open_lammps_doc("fix_deform")
        deform_doc_label.setToolTip("Click to open LAMMPS fix deform documentation")
        
        deform_params_layout.addRow(deform_doc_label)
        deform_params_layout.addRow("Deformation Rate:", self.deform_rate)
        deform_params_layout.addRow("Start Strain:", self.start_strain)
        deform_params_layout.addRow("End Strain:", self.end_strain)
        deform_params_layout.addRow("Deformation Axis:", self.deform_axis_combo)
        
        deform_params_group.setLayout(deform_params_layout)
        scroll_layout.addWidget(deform_params_group)
        
        # Wall settings
        wall_group = QGroupBox("Wall Settings")
        wall_layout = QVBoxLayout()
        
        self.use_walls = QCheckBox("Use Walls")
        self.use_walls.setChecked(False)
        self.use_walls.setToolTip("Enable walls to confine the simulation")
        self.use_walls.stateChanged.connect(self.toggle_wall_settings)
        
        wall_params_layout = QFormLayout()
        
        # Wall potential type
        self.wall_potential_combo = QComboBox()
        self.wall_potential_combo.addItems(["lj93", "lj126", "colloid", "harmonic"])
        self.wall_potential_combo.setCurrentText("lj93")
        self.wall_potential_combo.setEnabled(False)
        self.wall_potential_combo.setToolTip("Type of wall potential")
        
        # Wall energy parameters
        self.wall_epsilon = QDoubleSpinBox()
        self.wall_epsilon.setRange(0, 1000)
        self.wall_epsilon.setValue(1.0)
        self.wall_epsilon.setSingleStep(0.1)
        self.wall_epsilon.setEnabled(False)
        self.wall_epsilon.setToolTip("Energy parameter for wall potential")
        
        self.wall_sigma = QDoubleSpinBox()
        self.wall_sigma.setRange(0, 100)
        self.wall_sigma.setValue(1.0)
        self.wall_sigma.setSingleStep(0.1)
        self.wall_sigma.setEnabled(False)
        self.wall_sigma.setToolTip("Size parameter for wall potential")
        
        # Wall cutoff
        self.wall_cutoff = QDoubleSpinBox()
        self.wall_cutoff.setRange(0, 100)
        self.wall_cutoff.setValue(2.5)
        self.wall_cutoff.setSingleStep(0.1)
        self.wall_cutoff.setEnabled(False)
        self.wall_cutoff.setToolTip("Cutoff distance for wall potential")
        
        wall_params_layout.addRow("Wall Potential:", self.wall_potential_combo)
        wall_params_layout.addRow("Wall Epsilon:", self.wall_epsilon)
        wall_params_layout.addRow("Wall Sigma:", self.wall_sigma)
        wall_params_layout.addRow("Wall Cutoff:", self.wall_cutoff)
        
        wall_layout.addWidget(self.use_walls)
        wall_layout.addLayout(wall_params_layout)
        wall_group.setLayout(wall_layout)
        scroll_layout.addWidget(wall_group)
        
        # Bond breakage settings
        bond_break_group = QGroupBox("Bond Breakage Settings")
        bond_break_layout = QVBoxLayout()
        
        self.enable_bond_break = QCheckBox("Enable Bond Breakage")
        self.enable_bond_break.setChecked(False)
        self.enable_bond_break.setToolTip("Enable bond breakage during deformation")
        self.enable_bond_break.stateChanged.connect(self.toggle_bond_break_settings)
        
        bond_break_params_layout = QFormLayout()
        
        # Nevery parameter
        self.bond_break_nevery = QSpinBox()
        self.bond_break_nevery.setRange(1, 1000000)
        self.bond_break_nevery.setValue(1)
        self.bond_break_nevery.setEnabled(False)
        self.bond_break_nevery.setToolTip("Check for bond breakage every this many timesteps")
        
        # Bond type
        self.bond_break_type = QSpinBox()
        self.bond_break_type.setRange(1, 100)
        self.bond_break_type.setValue(1)
        self.bond_break_type.setEnabled(False)
        self.bond_break_type.setToolTip("Type of bonds to check for breakage")
        
        # Rmax parameter
        self.bond_break_rmax = QDoubleSpinBox()
        self.bond_break_rmax.setRange(0, 1000)
        self.bond_break_rmax.setValue(1.5)
        self.bond_break_rmax.setSingleStep(0.1)
        self.bond_break_rmax.setEnabled(False)
        self.bond_break_rmax.setToolTip("Maximum bond length before breakage")
        
        # Probability options
        self.bond_break_prob_group = QButtonGroup(self)
        self.bond_break_prob_fixed = QRadioButton("Fixed Probability")
        self.bond_break_prob_fixed.setChecked(True)
        self.bond_break_prob_fixed.setEnabled(False)
        self.bond_break_prob_fixed.setToolTip("Use fixed probability for bond breakage")
        
        self.bond_break_prob_variable = QRadioButton("Variable Probability")
        self.bond_break_prob_variable.setEnabled(False)
        self.bond_break_prob_variable.setToolTip("Use variable probability based on bond stretch")
        
        self.bond_break_prob_group.addButton(self.bond_break_prob_fixed)
        self.bond_break_prob_group.addButton(self.bond_break_prob_variable)
        
        # Probability value
        self.bond_break_prob_value = QDoubleSpinBox()
        self.bond_break_prob_value.setRange(0, 1)
        self.bond_break_prob_value.setValue(0.1)
        self.bond_break_prob_value.setSingleStep(0.01)
        self.bond_break_prob_value.setEnabled(False)
        self.bond_break_prob_value.setToolTip("Probability of bond breakage")
        
        bond_break_params_layout.addRow("Check Every (timesteps):", self.bond_break_nevery)
        bond_break_params_layout.addRow("Bond Type:", self.bond_break_type)
        bond_break_params_layout.addRow("Max Bond Length:", self.bond_break_rmax)
        bond_break_params_layout.addRow(self.bond_break_prob_fixed)
        bond_break_params_layout.addRow(self.bond_break_prob_variable)
        bond_break_params_layout.addRow("Break Probability:", self.bond_break_prob_value)
        
        bond_break_layout.addWidget(self.enable_bond_break)
        bond_break_layout.addLayout(bond_break_params_layout)
        bond_break_group.setLayout(bond_break_layout)
        scroll_layout.addWidget(bond_break_group)
        
        scroll_layout.addStretch()
    
    def create_output_tab(self):
        """Create the output configuration tab"""
        self.output_tab = QWidget()
        self.tab_widget.addTab(self.output_tab, "Output Configuration")
        
        # Create scroll area
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll_widget = QWidget()
        scroll_layout = QVBoxLayout(scroll_widget)
        scroll.setWidget(scroll_widget)
        
        # Main layout for output tab
        output_layout = QVBoxLayout(self.output_tab)
        output_layout.addWidget(scroll)
        
        # Output directory selection
        output_dir_group = QGroupBox("Output Directory")
        output_dir_layout = QHBoxLayout()
        
        self.output_dir_edit = QLineEdit()
        self.output_dir_edit.setPlaceholderText("Select output directory")
        self.output_dir_edit.setToolTip("Directory where output files will be saved")
        
        self.output_dir_browse = QPushButton("Browse...")
        self.output_dir_browse.clicked.connect(self.browse_output_dir)
        self.output_dir_browse.setToolTip("Browse for output directory")
        
        output_dir_layout.addWidget(self.output_dir_edit)
        output_dir_layout.addWidget(self.output_dir_browse)
        
        output_dir_group.setLayout(output_dir_layout)
        scroll_layout.addWidget(output_dir_group)
        
        # Output file settings
        output_files_group = QGroupBox("Output File Settings")
        output_files_layout = QFormLayout()
        
        # Log file
        self.log_file_edit = QLineEdit()
        self.log_file_edit.setText("log.lammps")
        self.log_file_edit.setToolTip("Name of the log file")
        
        # Data file
        self.data_file_edit = QLineEdit()
        self.data_file_edit.setText("deform.data")
        self.data_file_edit.setToolTip("Name of the data file")
        
        # Dump file
        self.dump_file_edit = QLineEdit()
        self.dump_file_edit.setText("deform.dump")
        self.dump_file_edit.setToolTip("Name of the dump file")
        
        output_files_layout.addRow("Log File:", self.log_file_edit)
        output_files_layout.addRow("Data File:", self.data_file_edit)
        output_files_layout.addRow("Dump File:", self.dump_file_edit)
        
        output_files_group.setLayout(output_files_layout)
        scroll_layout.addWidget(output_files_group)
        
        # Output frequency settings
        output_freq_group = QGroupBox("Output Frequency Settings")
        output_freq_layout = QFormLayout()
        
        # Thermodynamic output frequency
        self.thermo_freq = QSpinBox()
        self.thermo_freq.setRange(1, 1000000)
        self.thermo_freq.setValue(1000)
        self.thermo_freq.setToolTip("Frequency of thermodynamic output")
        
        # Dump frequency
        self.dump_freq = QSpinBox()
        self.dump_freq.setRange(1, 1000000)
        self.dump_freq.setValue(10000)
        self.dump_freq.setToolTip("Frequency of atom dump output")
        
        # Restart frequency
        self.restart_freq = QSpinBox()
        self.restart_freq.setRange(1, 1000000)
        self.restart_freq.setValue(100000)
        self.restart_freq.setToolTip("Frequency of restart file output")
        
        output_freq_layout.addRow("Thermo Frequency:", self.thermo_freq)
        output_freq_layout.addRow("Dump Frequency:", self.dump_freq)
        output_freq_layout.addRow("Restart Frequency:", self.restart_freq)
        
        output_freq_group.setLayout(output_freq_layout)
        scroll_layout.addWidget(output_freq_group)
        
        # Thermodynamic output selection
        thermo_group = QGroupBox("Thermodynamic Output Selection")
        thermo_layout = QVBoxLayout()
        
        # Create table for thermo output selection
        self.thermo_table = QTableWidget()
        self.thermo_table.setColumnCount(2)
        self.thermo_table.setHorizontalHeaderLabels(["Property", "Include"])
        self.thermo_table.horizontalHeader().setStretchLastSection(True)
        self.thermo_table.verticalHeader().setVisible(False)
        self.thermo_table.setAlternatingRowColors(True)
        
        # Thermo properties
        thermo_properties = [
            ("Step", True),
            ("Time", True),
            ("Temp", True),
            ("Press", True),
            ("Volume", True),
            ("Lx", True),
            ("Ly", True),
            ("Lz", True),
            ("E_pair", True),
            ("E_mol", True),
            ("E_total", True),
            ("Atoms", True),
            ("Bonds", True),
            ("Angles", True),
            ("Dihedrals", True),
            ("Impropers", True)
        ]
        
        self.thermo_table.setRowCount(len(thermo_properties))
        for i, (prop, include) in enumerate(thermo_properties):
            # Property name
            prop_item = QTableWidgetItem(prop)
            prop_item.setFlags(prop_item.flags() & ~Qt.ItemFlag.ItemIsEditable)
            self.thermo_table.setItem(i, 0, prop_item)
            
            # Include checkbox
            checkbox = QCheckBox()
            checkbox.setChecked(include)
            self.thermo_table.setCellWidget(i, 1, checkbox)
        
        thermo_layout.addWidget(self.thermo_table)
        thermo_group.setLayout(thermo_layout)
        scroll_layout.addWidget(thermo_group)
        
        scroll_layout.addStretch()
    
    def create_cluster_tab(self):
        """Create the cluster configuration tab"""
        self.cluster_tab = QWidget()
        self.tab_widget.addTab(self.cluster_tab, "Cluster Configuration")
        
        # Create scroll area
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll_widget = QWidget()
        scroll_layout = QVBoxLayout(scroll_widget)
        scroll.setWidget(scroll_widget)
        
        # Main layout for cluster tab
        cluster_layout = QVBoxLayout(self.cluster_tab)
        cluster_layout.addWidget(scroll)
        
        # Cluster execution settings
        cluster_exec_group = QGroupBox("Cluster Execution Settings")
        cluster_exec_layout = QVBoxLayout()
        
        self.use_cluster = QCheckBox("Execute on Cluster")
        self.use_cluster.setChecked(False)
        self.use_cluster.setToolTip("Enable cluster execution instead of local execution")
        self.use_cluster.stateChanged.connect(self.toggle_cluster_settings)
        
        cluster_exec_layout.addWidget(self.use_cluster)
        cluster_exec_group.setLayout(cluster_exec_layout)
        scroll_layout.addWidget(cluster_exec_group)
        
        # Cluster job settings
        cluster_job_group = QGroupBox("Cluster Job Settings")
        cluster_job_layout = QFormLayout()
        
        # Job name
        self.job_name_edit = QLineEdit()
        self.job_name_edit.setText("lammps_deform")
        self.job_name_edit.setEnabled(False)
        self.job_name_edit.setToolTip("Name of the cluster job")
        
        # Queue name
        self.queue_name_edit = QLineEdit()
        self.queue_name_edit.setText("normal")
        self.queue_name_edit.setEnabled(False)
        self.queue_name_edit.setToolTip("Name of the queue to submit the job to")
        
        # Number of nodes
        self.num_nodes = QSpinBox()
        self.num_nodes.setRange(1, 1000)
        self.num_nodes.setValue(1)
        self.num_nodes.setEnabled(False)
        self.num_nodes.setToolTip("Number of nodes to request")
        
        # Number of processors per node
        self.procs_per_node = QSpinBox()
        self.procs_per_node.setRange(1, 128)
        self.procs_per_node.setValue(16)
        self.procs_per_node.setEnabled(False)
        self.procs_per_node.setToolTip("Number of processors per node")
        
        # Wall time
        self.wall_time_edit = QLineEdit()
        self.wall_time_edit.setText("24:00:00")
        self.wall_time_edit.setEnabled(False)
        self.wall_time_edit.setToolTip("Maximum wall time for the job (HH:MM:SS)")
        
        # Memory per node
        self.memory_per_node = QLineEdit()
        self.memory_per_node.setText("4G")
        self.memory_per_node.setEnabled(False)
        self.memory_per_node.setToolTip("Memory per node (e.g., 4G, 4000M)")
        
        cluster_job_layout.addRow("Job Name:", self.job_name_edit)
        cluster_job_layout.addRow("Queue Name:", self.queue_name_edit)
        cluster_job_layout.addRow("Number of Nodes:", self.num_nodes)
        cluster_job_layout.addRow("Processors per Node:", self.procs_per_node)
        cluster_job_layout.addRow("Wall Time:", self.wall_time_edit)
        cluster_job_layout.addRow("Memory per Node:", self.memory_per_node)
        
        cluster_job_group.setLayout(cluster_job_layout)
        scroll_layout.addWidget(cluster_job_group)
        
        # LAMMPS executable path
        lammps_exec_group = QGroupBox("LAMMPS Executable Path")
        lammps_exec_layout = QHBoxLayout()
        
        self.lammps_exec_edit = QLineEdit()
        self.lammps_exec_edit.setText("lmp_mpi")
        self.lammps_exec_edit.setEnabled(False)
        self.lammps_exec_edit.setToolTip("Path to the LAMMPS executable on the cluster")
        
        self.lammps_exec_browse = QPushButton("Browse...")
        self.lammps_exec_browse.setEnabled(False)
        self.lammps_exec_browse.clicked.connect(self.browse_lammps_exec)
        self.lammps_exec_browse.setToolTip("Browse for LAMMPS executable")
        
        lammps_exec_layout.addWidget(self.lammps_exec_edit)
        lammps_exec_layout.addWidget(self.lammps_exec_browse)
        
        lammps_exec_group.setLayout(lammps_exec_layout)
        scroll_layout.addWidget(lammps_exec_group)
        
        # Additional job script commands
        job_script_group = QGroupBox("Additional Job Script Commands")
        job_script_layout = QVBoxLayout()
        
        self.job_script_edit = QTextEdit()
        self.job_script_edit.setPlaceholderText("Enter additional commands for the job script")
        self.job_script_edit.setEnabled(False)
        self.job_script_edit.setToolTip("Additional commands to include in the job script")
        
        job_script_layout.addWidget(self.job_script_edit)
        job_script_group.setLayout(job_script_layout)
        scroll_layout.addWidget(job_script_group)
        
        scroll_layout.addStretch()
    
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
        """Browse for system data file or directory"""
        file_dialog = QFileDialog()
        file_dialog.setFileMode(QFileDialog.AnyFile)
        file_dialog.setNameFilter("Data files (*.data);;All files (*)")
        
        if file_dialog.exec():
            selected_files = file_dialog.selectedFiles()
            if selected_files:
                self.system_path_edit.setText(selected_files[0])
    
    def browse_potential_file(self):
        """Browse for potential file"""
        file_dialog = QFileDialog()
        file_dialog.setFileMode(QFileDialog.ExistingFile)
        file_dialog.setNameFilter("Potential files (*.pot *.potential);;All files (*)")
        
        if file_dialog.exec():
            selected_files = file_dialog.selectedFiles()
            if selected_files:
                self.potential_path_edit.setText(selected_files[0])
    
    def browse_output_dir(self):
        """Browse for output directory"""
        dir_dialog = QFileDialog()
        dir_dialog.setFileMode(QFileDialog.Directory)
        dir_dialog.setOption(QFileDialog.ShowDirsOnly, True)
        
        if dir_dialog.exec():
            selected_dirs = dir_dialog.selectedFiles()
            if selected_dirs:
                self.output_dir_edit.setText(selected_dirs[0])
    
    def browse_lammps_exec(self):
        """Browse for LAMMPS executable"""
        file_dialog = QFileDialog()
        file_dialog.setFileMode(QFileDialog.ExistingFile)
        
        if file_dialog.exec():
            selected_files = file_dialog.selectedFiles()
            if selected_files:
                self.lammps_exec_edit.setText(selected_files[0])
    
    def toggle_potential_file(self, state):
        """Toggle potential file settings"""
        enabled = state == Qt.CheckState.Checked.value
        self.potential_path_edit.setEnabled(enabled)
        self.potential_path_browse.setEnabled(enabled)
    
    def toggle_velocity_settings(self, state):
        """Toggle velocity initialization settings"""
        enabled = state == Qt.CheckState.Checked.value
        self.initial_velocity_seed.setEnabled(enabled)
        self.damping_factor.setEnabled(enabled)
    
    def toggle_pressure_settings(self, ensemble):
        """Toggle pressure settings based on ensemble"""
        enabled = ensemble == "NPT"
        self.pressure.setEnabled(enabled)
    
    def toggle_wall_settings(self, state):
        """Toggle wall settings"""
        enabled = state == Qt.CheckState.Checked.value
        self.wall_potential_combo.setEnabled(enabled)
        self.wall_epsilon.setEnabled(enabled)
        self.wall_sigma.setEnabled(enabled)
        self.wall_cutoff.setEnabled(enabled)
    
    def toggle_bond_break_settings(self, state):
        """Toggle bond breakage settings"""
        enabled = state == Qt.CheckState.Checked.value
        self.bond_break_nevery.setEnabled(enabled)
        self.bond_break_type.setEnabled(enabled)
        self.bond_break_rmax.setEnabled(enabled)
        self.bond_break_prob_fixed.setEnabled(enabled)
        self.bond_break_prob_variable.setEnabled(enabled)
        self.bond_break_prob_value.setEnabled(enabled)
    
    def toggle_cluster_settings(self, state):
        """Toggle cluster settings"""
        enabled = state == Qt.CheckState.Checked.value
        self.job_name_edit.setEnabled(enabled)
        self.queue_name_edit.setEnabled(enabled)
        self.num_nodes.setEnabled(enabled)
        self.procs_per_node.setEnabled(enabled)
        self.wall_time_edit.setEnabled(enabled)
        self.memory_per_node.setEnabled(enabled)
        self.lammps_exec_edit.setEnabled(enabled)
        self.lammps_exec_browse.setEnabled(enabled)
        self.job_script_edit.setEnabled(enabled)
    
    def update_system_type(self, path):
        """Update system type display"""
        if not path:
            self.system_type_label.setText("System Type: Not selected")
            return
        
        if os.path.isfile(path):
            self.system_type_label.setText(f"System Type: Single file ({os.path.basename(path)})")
        elif os.path.isdir(path):
            data_files = glob.glob(os.path.join(path, "*.data"))
            if data_files:
                self.system_type_label.setText(f"System Type: Directory ({len(data_files)} data files)")
            else:
                self.system_type_label.setText("System Type: Directory (no data files found)")
        else:
            self.system_type_label.setText("System Type: Invalid path")
    
    def update_timestep_display(self, units):
        """Update timestep display based on units"""
        timestep_units = {
            "lj": "lj",
            "real": "fs",
            "metal": "ps", 
            "si": "s",
            "cgs": "s",
            "electron": "fs",
            "micro": "μs",
            "nano": "ns"
        }
        self.timestep_display.setText(f"Timestep unit: {timestep_units.get(units, 'unknown')}")
    
    def open_lammps_doc(self, command):
        """Open LAMMPS documentation for the given command"""
        url = f"https://docs.lammps.org/{command}.html"
        QDesktopServices.openUrl(QUrl(url))
    
    def collect_config(self):
        """Collect configuration from all widgets"""
        config = {
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
            "velocity_seed": self.initial_velocity_seed.value(),
            "damping_factor": self.damping_factor.value(),
            "deformation_type": "uniaxial" if self.uniaxial_radio.isChecked() else
                               "biaxial" if self.biaxial_radio.isChecked() else
                               "triaxial" if self.triaxial_radio.isChecked() else
                               "shear",
            "deform_rate": self.deform_rate.value(),
            "start_strain": self.start_strain.value(),
            "end_strain": self.end_strain.value(),
            "deform_axis": self.deform_axis_combo.currentText(),
            "use_walls": self.use_walls.isChecked(),
            "wall_potential": self.wall_potential_combo.currentText(),
            "wall_epsilon": self.wall_epsilon.value(),
            "wall_sigma": self.wall_sigma.value(),
            "wall_cutoff": self.wall_cutoff.value(),
            "enable_bond_break": self.enable_bond_break.isChecked(),
            "bond_break_nevery": self.bond_break_nevery.value(),
            "bond_break_type": self.bond_break_type.value(),
            "bond_break_rmax": self.bond_break_rmax.value(),
            "bond_break_prob_fixed": self.bond_break_prob_fixed.isChecked(),
            "bond_break_prob_value": self.bond_break_prob_value.value(),
            "output_dir": self.output_dir_edit.text(),
            "log_file": self.log_file_edit.text(),
            "data_file": self.data_file_edit.text(),
            "dump_file": self.dump_file_edit.text(),
            "thermo_freq": self.thermo_freq.value(),
            "dump_freq": self.dump_freq.value(),
            "restart_freq": self.restart_freq.value(),
            "use_cluster": self.use_cluster.isChecked(),
            "job_name": self.job_name_edit.text(),
            "queue_name": self.queue_name_edit.text(),
            "num_nodes": self.num_nodes.value(),
            "procs_per_node": self.procs_per_node.value(),
            "wall_time": self.wall_time_edit.text(),
            "memory_per_node": self.memory_per_node.text(),
            "lammps_exec": self.lammps_exec_edit.text(),
            "job_script_commands": self.job_script_edit.toPlainText()
        }
        
        # Collect thermo output selection
        thermo_output = []
        for i in range(self.thermo_table.rowCount()):
            prop_item = self.thermo_table.item(i, 0)
            checkbox = self.thermo_table.cellWidget(i, 1)
            if checkbox and checkbox.isChecked():
                thermo_output.append(prop_item.text())
        config["thermo_output"] = thermo_output
        
        return config
    
    def save_configuration(self):
        """Save configuration to file"""
        file_dialog = QFileDialog()
        file_dialog.setFileMode(QFileDialog.AnyFile)
        file_dialog.setNameFilter("JSON files (*.json);;All files (*)")
        file_dialog.setDefaultSuffix("json")
        
        if file_dialog.exec():
            selected_files = file_dialog.selectedFiles()
            if selected_files:
                config = self.collect_config()
                try:
                    with open(selected_files[0], 'w') as f:
                        json.dump(config, f, indent=2)
                    QMessageBox.information(self, "Success", "Configuration saved successfully!")
                except Exception as e:
                    QMessageBox.critical(self, "Error", f"Failed to save configuration: {e}")
    
    def load_configuration(self):
        """Load configuration from file"""
        file_dialog = QFileDialog()
        file_dialog.setFileMode(QFileDialog.ExistingFile)
        file_dialog.setNameFilter("JSON files (*.json);;All files (*)")
        
        if file_dialog.exec():
            selected_files = file_dialog.selectedFiles()
            if selected_files:
                try:
                    with open(selected_files[0], 'r') as f:
                        config = json.load(f)
                    self.apply_config(config)
                    QMessageBox.information(self, "Success", "Configuration loaded successfully!")
                except Exception as e:
                    QMessageBox.critical(self, "Error", f"Failed to load configuration: {e}")
    
    def apply_config(self, config):
        """Apply configuration to widgets"""
        # System configuration
        self.system_path_edit.setText(config.get("system_path", ""))
        self.use_potential_file.setChecked(config.get("use_potential_file", False))
        self.potential_path_edit.setText(config.get("potential_file", ""))
        self.atom_style_combo.setCurrentText(config.get("atom_style", "atomic"))
        self.units_combo.setCurrentText(config.get("units", "metal"))
        self.boundary_x_combo.setCurrentText(config.get("boundary_x", "p"))
        self.boundary_y_combo.setCurrentText(config.get("boundary_y", "p"))
        self.boundary_z_combo.setCurrentText(config.get("boundary_z", "p"))
        self.ensemble_combo.setCurrentText(config.get("ensemble", "NVT"))
        self.temp_init.setValue(config.get("temp_init", 300.0))
        self.temp_end.setValue(config.get("temp_end", 300.0))
        self.pressure.setValue(config.get("pressure", 1.0))
        self.enable_velocity.setChecked(config.get("enable_velocity", True))
        self.initial_velocity_seed.setValue(config.get("velocity_seed", 12345))
        self.damping_factor.setValue(config.get("damping_factor", 100.0))
        
        # Deformation configuration
        deform_type = config.get("deformation_type", "uniaxial")
        if deform_type == "uniaxial":
            self.uniaxial_radio.setChecked(True)
        elif deform_type == "biaxial":
            self.biaxial_radio.setChecked(True)
        elif deform_type == "triaxial":
            self.triaxial_radio.setChecked(True)
        elif deform_type == "shear":
            self.shear_radio.setChecked(True)
        
        self.deform_rate.setValue(config.get("deform_rate", 0.001))
        self.start_strain.setValue(config.get("start_strain", 0.0))
        self.end_strain.setValue(config.get("end_strain", 1.0))
        self.deform_axis_combo.setCurrentText(config.get("deform_axis", "z"))
        
        # Wall settings
        self.use_walls.setChecked(config.get("use_walls", False))
        self.wall_potential_combo.setCurrentText(config.get("wall_potential", "lj93"))
        self.wall_epsilon.setValue(config.get("wall_epsilon", 1.0))
        self.wall_sigma.setValue(config.get("wall_sigma", 1.0))
        self.wall_cutoff.setValue(config.get("wall_cutoff", 2.5))
        
        # Bond breakage settings
        self.enable_bond_break.setChecked(config.get("enable_bond_break", False))
        self.bond_break_nevery.setValue(config.get("bond_break_nevery", 1))
        self.bond_break_type.setValue(config.get("bond_break_type", 1))
        self.bond_break_rmax.setValue(config.get("bond_break_rmax", 1.5))
        if config.get("bond_break_prob_fixed", True):
            self.bond_break_prob_fixed.setChecked(True)
        else:
            self.bond_break_prob_variable.setChecked(True)
        self.bond_break_prob_value.setValue(config.get("bond_break_prob_value", 0.1))
        
        # Output configuration
        self.output_dir_edit.setText(config.get("output_dir", ""))
        self.log_file_edit.setText(config.get("log_file", "log.lammps"))
        self.data_file_edit.setText(config.get("data_file", "deform.data"))
        self.dump_file_edit.setText(config.get("dump_file", "deform.dump"))
        self.thermo_freq.setValue(config.get("thermo_freq", 1000))
        self.dump_freq.setValue(config.get("dump_freq", 10000))
        self.restart_freq.setValue(config.get("restart_freq", 100000))
        
        # Apply thermo output selection
        thermo_output = config.get("thermo_output", [])
        for i in range(self.thermo_table.rowCount()):
            prop_item = self.thermo_table.item(i, 0)
            checkbox = self.thermo_table.cellWidget(i, 1)
            if checkbox and prop_item:
                checkbox.setChecked(prop_item.text() in thermo_output)
        
        # Cluster configuration
        self.use_cluster.setChecked(config.get("use_cluster", False))
        self.job_name_edit.setText(config.get("job_name", "lammps_deform"))
        self.queue_name_edit.setText(config.get("queue_name", "normal"))
        self.num_nodes.setValue(config.get("num_nodes", 1))
        self.procs_per_node.setValue(config.get("procs_per_node", 16))
        self.wall_time_edit.setText(config.get("wall_time", "24:00:00"))
        self.memory_per_node.setText(config.get("memory_per_node", "4G"))
        self.lammps_exec_edit.setText(config.get("lammps_exec", "lmp_mpi"))
        self.job_script_edit.setText(config.get("job_script_commands", ""))
    
    def generate_scripts(self):
        """Generate LAMMPS scripts"""
        config = self.collect_config()
        
        # Validate configuration
        if not config["system_path"]:
            QMessageBox.warning(self, "Warning", "Please select a system data file or directory")
            return
        
        if not os.path.exists(config["system_path"]):
            QMessageBox.warning(self, "Warning", "System path does not exist")
            return
        
        if config["use_potential_file"] and not config["potential_file"]:
            QMessageBox.warning(self, "Warning", "Please select a potential file")
            return
        
        if not config["output_dir"]:
            QMessageBox.warning(self, "Warning", "Please select an output directory")
            return
        
        # Create output directory if it doesn't exist
        os.makedirs(config["output_dir"], exist_ok=True)
        
        try:
            # Generate scripts
            if ScriptGen is not None:
                generator = ScriptGen(config)
                generator.generate_scripts()
                QMessageBox.information(self, "Success", 
                                      f"Scripts generated successfully in:\n{config['output_dir']}")
            else:
                QMessageBox.warning(self, "Warning", 
                                  "Script generator not available. Please check script_generator.py")
        except Exception as e:
            QMessageBox.critical(self, "Error", f"Failed to generate scripts: {e}")
    
    def load_settings(self):
        """Load saved settings"""
        # Load system path
        system_path = self.settings.value("system_path", "")
        self.system_path_edit.setText(system_path)
        
        # Load potential file settings
        self.use_potential_file.setChecked(self.settings.value("use_potential_file", False, type=bool))
        potential_file = self.settings.value("potential_file", "")
        self.potential_path_edit.setText(potential_file)
        
        # Load basic settings
        self.atom_style_combo.setCurrentText(self.settings.value("atom_style", "atomic"))
        self.units_combo.setCurrentText(self.settings.value("units", "metal"))
        self.boundary_x_combo.setCurrentText(self.settings.value("boundary_x", "p"))
        self.boundary_y_combo.setCurrentText(self.settings.value("boundary_y", "p"))
        self.boundary_z_combo.setCurrentText(self.settings.value("boundary_z", "p"))
        self.ensemble_combo.setCurrentText(self.settings.value("ensemble", "NVT"))
        self.temp_init.setValue(self.settings.value("temp_init", 300.0, type=float))
        self.temp_end.setValue(self.settings.value("temp_end", 300.0, type=float))
        self.pressure.setValue(self.settings.value("pressure", 1.0, type=float))
        
        # Load velocity settings
        self.enable_velocity.setChecked(self.settings.value("enable_velocity", True, type=bool))
        self.initial_velocity_seed.setValue(self.settings.value("velocity_seed", 12345, type=int))
        self.damping_factor.setValue(self.settings.value("damping_factor", 100.0, type=float))
        
        # Load deformation settings
        deform_type = self.settings.value("deformation_type", "uniaxial")
        if deform_type == "uniaxial":
            self.uniaxial_radio.setChecked(True)
        elif deform_type == "biaxial":
            self.biaxial_radio.setChecked(True)
        elif deform_type == "triaxial":
            self.triaxial_radio.setChecked(True)
        elif deform_type == "shear":
            self.shear_radio.setChecked(True)
        
        self.deform_rate.setValue(self.settings.value("deform_rate", 0.001, type=float))
        self.start_strain.setValue(self.settings.value("start_strain", 0.0, type=float))
        self.end_strain.setValue(self.settings.value("end_strain", 1.0, type=float))
        self.deform_axis_combo.setCurrentText(self.settings.value("deform_axis", "z"))
        
        # Load wall settings
        self.use_walls.setChecked(self.settings.value("use_walls", False, type=bool))
        self.wall_potential_combo.setCurrentText(self.settings.value("wall_potential", "lj93"))
        self.wall_epsilon.setValue(self.settings.value("wall_epsilon", 1.0, type=float))
        self.wall_sigma.setValue(self.settings.value("wall_sigma", 1.0, type=float))
        self.wall_cutoff.setValue(self.settings.value("wall_cutoff", 2.5, type=float))
        
        # Load bond breakage settings
        self.enable_bond_break.setChecked(self.settings.value("enable_bond_break", False, type=bool))
        self.bond_break_nevery.setValue(self.settings.value("bond_break_nevery", 1, type=int))
        self.bond_break_type.setValue(self.settings.value("bond_break_type", 1, type=int))
        self.bond_break_rmax.setValue(self.settings.value("bond_break_rmax", 1.5, type=float))
        if self.settings.value("bond_break_prob_fixed", True, type=bool):
            self.bond_break_prob_fixed.setChecked(True)
        else:
            self.bond_break_prob_variable.setChecked(True)
        self.bond_break_prob_value.setValue(self.settings.value("bond_break_prob_value", 0.1, type=float))
        
        # Load output settings
        self.output_dir_edit.setText(self.settings.value("output_dir", ""))
        self.log_file_edit.setText(self.settings.value("log_file", "log.lammps"))
        self.data_file_edit.setText(self.settings.value("data_file", "deform.data"))
        self.dump_file_edit.setText(self.settings.value("dump_file", "deform.dump"))
        self.thermo_freq.setValue(self.settings.value("thermo_freq", 1000, type=int))
        self.dump_freq.setValue(self.settings.value("dump_freq", 10000, type=int))
        self.restart_freq.setValue(self.settings.value("restart_freq", 100000, type=int))
        
        # Load cluster settings
        self.use_cluster.setChecked(self.settings.value("use_cluster", False, type=bool))
        self.job_name_edit.setText(self.settings.value("job_name", "lammps_deform"))
        self.queue_name_edit.setText(self.settings.value("queue_name", "normal"))
        self.num_nodes.setValue(self.settings.value("num_nodes", 1, type=int))
        self.procs_per_node.setValue(self.settings.value("procs_per_node", 16, type=int))
        self.wall_time_edit.setText(self.settings.value("wall_time", "24:00:00"))
        self.memory_per_node.setText(self.settings.value("memory_per_node", "4G"))
        self.lammps_exec_edit.setText(self.settings.value("lammps_exec", "lmp_mpi"))
        self.job_script_edit.setText(self.settings.value("job_script_commands", ""))
        
        # Update system type display
        self.update_system_type(system_path)
        
        # Update timestep display
        self.update_timestep_display(self.units_combo.currentText())
        
        # Toggle settings based on loaded values
        self.toggle_potential_file(self.use_potential_file.isChecked())
        self.toggle_velocity_settings(self.enable_velocity.isChecked())
        self.toggle_pressure_settings(self.ensemble_combo.currentText())
        self.toggle_wall_settings(self.use_walls.isChecked())
        self.toggle_bond_break_settings(self.enable_bond_break.isChecked())
        self.toggle_cluster_settings(self.use_cluster.isChecked())
    
    def closeEvent(self, event):
        """Handle application close event"""
        # Save settings
        self.settings.setValue("system_path", self.system_path_edit.text())
        self.settings.setValue("use_potential_file", self.use_potential_file.isChecked())
        self.settings.setValue("potential_file", self.potential_path_edit.text())
        self.settings.setValue("atom_style", self.atom_style_combo.currentText())
        self.settings.setValue("units", self.units_combo.currentText())
        self.settings.setValue("boundary_x", self.boundary_x_combo.currentText())
        self.settings.setValue("boundary_y", self.boundary_y_combo.currentText())
        self.settings.setValue("boundary_z", self.boundary_z_combo.currentText())
        self.settings.setValue("ensemble", self.ensemble_combo.currentText())
        self.settings.setValue("temp_init", self.temp_init.value())
        self.settings.setValue("temp_end", self.temp_end.value())
        self.settings.setValue("pressure", self.pressure.value())
        self.settings.setValue("enable_velocity", self.enable_velocity.isChecked())
        self.settings.setValue("velocity_seed", self.initial_velocity_seed.value())
        self.settings.setValue("damping_factor", self.damping_factor.value())
        
        # Save deformation settings
        if self.uniaxial_radio.isChecked():
            self.settings.setValue("deformation_type", "uniaxial")
        elif self.biaxial_radio.isChecked():
            self.settings.setValue("deformation_type", "biaxial")
        elif self.triaxial_radio.isChecked():
            self.settings.setValue("deformation_type", "triaxial")
        elif self.shear_radio.isChecked():
            self.settings.setValue("deformation_type", "shear")
        
        self.settings.setValue("deform_rate", self.deform_rate.value())
        self.settings.setValue("start_strain", self.start_strain.value())
        self.settings.setValue("end_strain", self.end_strain.value())
        self.settings.setValue("deform_axis", self.deform_axis_combo.currentText())
        
        # Save wall settings
        self.settings.setValue("use_walls", self.use_walls.isChecked())
        self.settings.setValue("wall_potential", self.wall_potential_combo.currentText())
        self.settings.setValue("wall_epsilon", self.wall_epsilon.value())
        self.settings.setValue("wall_sigma", self.wall_sigma.value())
        self.settings.setValue("wall_cutoff", self.wall_cutoff.value())
        
        # Save bond breakage settings
        self.settings.setValue("enable_bond_break", self.enable_bond_break.isChecked())
        self.settings.setValue("bond_break_nevery", self.bond_break_nevery.value())
        self.settings.setValue("bond_break_type", self.bond_break_type.value())
        self.settings.setValue("bond_break_rmax", self.bond_break_rmax.value())
        self.settings.setValue("bond_break_prob_fixed", self.bond_break_prob_fixed.isChecked())
        self.settings.setValue("bond_break_prob_value", self.bond_break_prob_value.value())
        
        # Save output settings
        self.settings.setValue("output_dir", self.output_dir_edit.text())
        self.settings.setValue("log_file", self.log_file_edit.text())
        self.settings.setValue("data_file", self.data_file_edit.text())
        self.settings.setValue("dump_file", self.dump_file_edit.text())
        self.settings.setValue("thermo_freq", self.thermo_freq.value())
        self.settings.setValue("dump_freq", self.dump_freq.value())
        self.settings.setValue("restart_freq", self.restart_freq.value())
        
        # Save cluster settings
        self.settings.setValue("use_cluster", self.use_cluster.isChecked())
        self.settings.setValue("job_name", self.job_name_edit.text())
        self.settings.setValue("queue_name", self.queue_name_edit.text())
        self.settings.setValue("num_nodes", self.num_nodes.value())
        self.settings.setValue("procs_per_node", self.procs_per_node.value())
        self.settings.setValue("wall_time", self.wall_time_edit.text())
        self.settings.setValue("memory_per_node", self.memory_per_node.text())
        self.settings.setValue("lammps_exec", self.lammps_exec_edit.text())
        self.settings.setValue("job_script_commands", self.job_script_edit.toPlainText())
        
        event.accept()

def main():
    """Main function to run the application"""
    try:
        app = QApplication(sys.argv if sys.argv else ['lammps_gui'])
        window = LammpsScriptGenerator()
        window.show()
        sys.exit(app.exec())
    except Exception as e:
        sys.exit(1)

if __name__ == "__main__":
    main()