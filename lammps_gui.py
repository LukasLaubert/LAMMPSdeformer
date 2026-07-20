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
        
        # Add documentation link for velocity initialization
        velocity_doc_label = QLabel("Velocity Initialization Documentation:")
        velocity_doc_label.setStyleSheet("color: blue; text-decoration: underline; font-size: 10px;")
        try:
            velocity_doc_label.setCursor(QCursor(Qt.CursorShape.PointingHandCursor))
        except AttributeError:
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
        self.damping_factor.setToolTip("Damping factor as multiple of timestep")
        
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
        
        # Connect ensemble change to pressure enable/disable
        self.ensemble_combo.currentTextChanged.connect(self.toggle_pressure_settings)
        
        scroll_layout.addStretch()
    
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
        
        self.enable_bond_break = QCheckBox("Enable Bond Breakage")
        self.enable_bond_break.setToolTip("Enable bond breakage during deformation simulation")
        self.enable_bond_break.stateChanged.connect(self.toggle_bond_breakage_settings)
        
        bond_breakage_form_layout = QFormLayout()
        
        # Nevery parameter
        self.nevery = QSpinBox()
        self.nevery.setRange(1, 1000000)
        self.nevery.setValue(1)
        self.nevery.setEnabled(False)
        self.nevery.setToolTip("Check for bond breakage every this many timesteps")
        
        # Bond type
        self.bondtype = QSpinBox()
        self.bondtype.setRange(1, 100)
        self.bondtype.setValue(1)
        self.bondtype.setEnabled(False)
        self.bondtype.setToolTip("Type of bonds to check for breakage")
        
        # Rmax parameter
        self.rmax = QDoubleSpinBox()
        self.rmax.setRange(0, 1000)
        self.rmax.setValue(1.5)
        self.rmax.setSingleStep(0.1)
        self.rmax.setEnabled(False)
        self.rmax.setToolTip("Maximum bond length before breakage")
        
        # Probability options
        self.enable_prob = QCheckBox("Enable Probability")
        self.enable_prob.setChecked(False)
        self.enable_prob.setEnabled(False)
        self.enable_prob.setToolTip("Enable probabilistic bond breakage")
        
        self.prob_fraction = QDoubleSpinBox()
        self.prob_fraction.setRange(0, 1)
        self.prob_fraction.setValue(0.1)
        self.prob_fraction.setSingleStep(0.01)
        self.prob_fraction.setEnabled(False)
        self.prob_fraction.setToolTip("Probability of bond breakage")
        
        self.prob_seed = QSpinBox()
        self.prob_seed.setRange(1, 1000000)
        self.prob_seed.setValue(12345)
        self.prob_seed.setEnabled(False)
        self.prob_seed.setToolTip("Random seed for probability")
        
        bond_breakage_form_layout.addRow("Nevery:", self.nevery)
        bond_breakage_form_layout.addRow("Bond Type:", self.bondtype)
        bond_breakage_form_layout.addRow("Rmax:", self.rmax)
        bond_breakage_form_layout.addRow(self.enable_prob)
        bond_breakage_form_layout.addRow("Probability:", self.prob_fraction)
        bond_breakage_form_layout.addRow("Seed:", self.prob_seed)
        
        bond_breakage_layout.addWidget(self.enable_bond_break)
        bond_breakage_layout.addLayout(bond_breakage_form_layout)
        bond_breakage_group.setLayout(bond_breakage_layout)
        scroll_layout.addWidget(bond_breakage_group)
        
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
    
    def browse_output_dir(self):
        """Browse for output directory"""
        dir_path = QFileDialog.getExistingDirectory(self, "Select Output Directory")
        if dir_path:
            self.output_dir_edit.setText(dir_path)
    
    def browse_lammps_exec(self):
        """Browse for LAMMPS executable"""
        file_path, _ = QFileDialog.getOpenFileName(self, "Select LAMMPS Executable", "", "All Files (*)")
        if file_path:
            self.lammps_exec_edit.setText(file_path)
    
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
    
    def toggle_bond_breakage_settings(self, state):
        """Toggle bond breakage settings"""
        enabled = state == Qt.CheckState.Checked.value
        self.nevery.setEnabled(enabled)
        self.bondtype.setEnabled(enabled)
        self.rmax.setEnabled(enabled)
        self.enable_prob.setEnabled(enabled)
        self.prob_fraction.setEnabled(enabled)
        self.prob_seed.setEnabled(enabled)
    
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
        """Update timestep display based on selected units"""
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
        unit = timestep_units.get(units.lower(), "unknown")
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
    
    def open_lammps_doc(self, command):
        """Open LAMMPS documentation for the given command"""
        url = f"https://docs.lammps.org/{command}.html"
        QDesktopServices.openUrl(QUrl(url))
    
    # Deformation table methods
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
            "neighbor_distance": self.neighbor_distance.value(),
            "neigh_modify_every": self.neigh_modify_every.value(),
            "neigh_modify_delay": self.neigh_modify_delay.value(),
            "neigh_modify_check": self.neigh_modify_check.isChecked(),
            "timestep": self.timestep.value(),
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
        
        # Collect deformation studies from table
        deform_studies = []
        for row in range(self.studies_table.rowCount()):
            name_item = self.studies_table.item(row, 0)
            method_combo = self.studies_table.cellWidget(row, 1)
            strain_rate_item = self.studies_table.item(row, 2)
            eng_strain_item = self.studies_table.item(row, 3)
            steps_item = self.studies_table.item(row, 4)
            axis_combo = self.studies_table.cellWidget(row, 5)
            style_combo = self.studies_table.cellWidget(row, 6)
            thermo_item = self.studies_table.item(row, 7)
            
            if all([name_item, method_combo, strain_rate_item, eng_strain_item, steps_item, axis_combo, style_combo, thermo_item]):
                study = {
                    "name": name_item.text(),
                    "method": method_combo.currentText(),
                    "strain_rate": float(strain_rate_item.text()),
                    "engineering_strain": float(eng_strain_item.text()),
                    "steps": int(steps_item.text()),
                    "axis": axis_combo.currentText(),
                    "style": style_combo.currentText(),
                    "thermo_freq": int(thermo_item.text())
                }
                deform_studies.append(study)
        
        config["deform_studies"] = deform_studies
        config["wall_thickness"] = self.wall_thickness.value()
        config["enable_bond_break"] = self.enable_bond_break.isChecked()
        config["nevery"] = self.nevery.value()
        config["bondtype"] = self.bondtype.value()
        config["rmax"] = self.rmax.value()
        config["enable_prob"] = self.enable_prob.isChecked()
        config["prob_fraction"] = self.prob_fraction.value()
        config["prob_seed"] = self.prob_seed.value()
        
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
        file_path, _ = QFileDialog.getSaveFileName(self, "Save Configuration", "", "JSON files (*.json);;All files (*)")
        if file_path:
            config = self.collect_config()
            try:
                with open(file_path, 'w') as f:
                    json.dump(config, f, indent=2)
                QMessageBox.information(self, "Success", "Configuration saved successfully!")
            except Exception as e:
                QMessageBox.critical(self, "Error", f"Failed to save configuration: {e}")
    
    def load_configuration(self):
        """Load configuration from file"""
        file_path, _ = QFileDialog.getOpenFileName(self, "Load Configuration", "", "JSON files (*.json);;All files (*)")
        if file_path:
            try:
                with open(file_path, 'r') as f:
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
        
        # Neighbor settings
        self.neighbor_distance.setValue(config.get("neighbor_distance", 0.3))
        self.neigh_modify_every.setValue(config.get("neigh_modify_every", 1))
        self.neigh_modify_delay.setValue(config.get("neigh_modify_delay", 10))
        self.neigh_modify_check.setChecked(config.get("neigh_modify_check", True))
        
        # Timestep settings
        self.timestep.setValue(config.get("timestep", 0.001))
        
        # Deformation studies
        deform_studies = config.get("deform_studies", [])
        if deform_studies:
            self.studies_table.setRowCount(len(deform_studies))
            for i, study in enumerate(deform_studies):
                self.add_sample_study_data(
                    i, 
                    study.get("name", f"study{i+1}"),
                    study.get("method", "fix_deform"),
                    study.get("strain_rate", 0.001),
                    study.get("engineering_strain", 0.1),
                    study.get("steps", 100),
                    study.get("axis", "x"),
                    study.get("style", "final"),
                    study.get("thermo_freq", 100)
                )
        
        # Wall settings
        self.wall_thickness.setValue(config.get("wall_thickness", 5.0))
        
        # Bond breakage settings
        self.enable_bond_break.setChecked(config.get("enable_bond_break", False))
        self.nevery.setValue(config.get("nevery", 1))
        self.bondtype.setValue(config.get("bondtype", 1))
        self.rmax.setValue(config.get("rmax", 1.5))
        self.enable_prob.setChecked(config.get("enable_prob", False))
        self.prob_fraction.setValue(config.get("prob_fraction", 0.1))
        self.prob_seed.setValue(config.get("prob_seed", 12345))
        
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
        
        # Load neighbor settings
        self.neighbor_distance.setValue(self.settings.value("neighbor_distance", 0.3, type=float))
        self.neigh_modify_every.setValue(self.settings.value("neigh_modify_every", 1, type=int))
        self.neigh_modify_delay.setValue(self.settings.value("neigh_modify_delay", 10, type=int))
        self.neigh_modify_check.setChecked(self.settings.value("neigh_modify_check", True, type=bool))
        
        # Load timestep settings
        self.timestep.setValue(self.settings.value("timestep", 0.001, type=float))
        
        # Load wall settings
        self.wall_thickness.setValue(self.settings.value("wall_thickness", 5.0, type=float))
        
        # Load bond breakage settings
        self.enable_bond_break.setChecked(self.settings.value("enable_bond_break", False, type=bool))
        self.nevery.setValue(self.settings.value("nevery", 1, type=int))
        self.bondtype.setValue(self.settings.value("bondtype", 1, type=int))
        self.rmax.setValue(self.settings.value("rmax", 1.5, type=float))
        self.enable_prob.setChecked(self.settings.value("enable_prob", False, type=bool))
        self.prob_fraction.setValue(self.settings.value("prob_fraction", 0.1, type=float))
        self.prob_seed.setValue(self.settings.value("prob_seed", 12345, type=int))
        
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
        self.toggle_bond_breakage_settings(self.enable_bond_break.isChecked())
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
        
        # Save neighbor settings
        self.settings.setValue("neighbor_distance", self.neighbor_distance.value())
        self.settings.setValue("neigh_modify_every", self.neigh_modify_every.value())
        self.settings.setValue("neigh_modify_delay", self.neigh_modify_delay.value())
        self.settings.setValue("neigh_modify_check", self.neigh_modify_check.isChecked())
        
        # Save timestep settings
        self.settings.setValue("timestep", self.timestep.value())
        
        # Save wall settings
        self.settings.setValue("wall_thickness", self.wall_thickness.value())
        
        # Save bond breakage settings
        self.settings.setValue("enable_bond_break", self.enable_bond_break.isChecked())
        self.settings.setValue("nevery", self.nevery.value())
        self.settings.setValue("bondtype", self.bondtype.value())
        self.settings.setValue("rmax", self.rmax.value())
        self.settings.setValue("enable_prob", self.enable_prob.isChecked())
        self.settings.setValue("prob_fraction", self.prob_fraction.value())
        self.settings.setValue("prob_seed", self.prob_seed.value())
        
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