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
import re
from pathlib import Path

# Import PyQt6 components
try:
    from PyQt6.QtWidgets import (QApplication, QMainWindow, QTabWidget, QWidget, QVBoxLayout, 
                                QHBoxLayout, QLabel, QLineEdit, QPushButton, QFileDialog, 
                                QComboBox, QCheckBox, QSpinBox, QDoubleSpinBox, QTextEdit,
                                QGroupBox, QFormLayout, QRadioButton, QButtonGroup, QScrollArea,
                                QSplitter, QMessageBox, QProgressBar, QDialog, QGridLayout,
                                QTableWidget, QTableWidgetItem, QHeaderView, QAbstractItemView,
                                QDialogButtonBox, QToolTip, QFrame, QSizePolicy, QItemDelegate,
                                QListWidget)
    from PyQt6.QtCore import Qt, QSettings, pyqtSignal, QThread, QTimer, QUrl, QSize, QPointF
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

# Import the new graph widgets
try:
    from graph_widgets import DeformationTab
except ImportError as e:
    DeformationTab = None

class InfoGroupBox(QGroupBox):
    def __init__(self, title, doc_link, parent=None, is_external=False):
        super().__init__(title, parent)
        self.doc_link = doc_link
        self.is_external = is_external

        self.info_label = QLabel("ℹ️", self)
        self.info_label.setStyleSheet("color: blue; font-size: 14px;")
        self.info_label.setCursor(QCursor(Qt.CursorShape.PointingHandCursor))
        if is_external:
            self.info_label.setToolTip(f"Click to open {doc_link}")
        else:
            self.info_label.setToolTip(f"Click to open LAMMPS {doc_link} documentation")
        self.info_label.mousePressEvent = self.open_doc_link

    def open_doc_link(self, event):
        if self.is_external:
            url = QUrl(self.doc_link)
        else:
            url = QUrl(f"https://docs.lammps.org/{self.doc_link}.html")
        QDesktopServices.openUrl(url)

    def resizeEvent(self, event):
        super().resizeEvent(event)
        # Position the icon in the top-right corner
        self.info_label.move(self.width() - 20, 0)

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
        self.create_fixes_tab()
        self.create_output_tab()
        self.create_job_submission_tab()
        
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
    
    def closeEvent(self, event):
        """Handle window close event - save all settings"""
        try:
            self.save_settings()
            print("Settings saved successfully")
        except Exception as e:
            print(f"Error saving settings on close: {e}")
        
        # Accept the close event
        event.accept()
    
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
        system_group = InfoGroupBox("System Selection", "")
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
        potential_group = InfoGroupBox("Potential File Selection", "include")
        potential_layout = QFormLayout()
        
        self.use_potential_file = QCheckBox("Use separate potential file")
        self.use_potential_file.stateChanged.connect(self.toggle_potential_file)
        self.use_potential_file.setToolTip("Enable to use a separate potential file instead of inline potentials")
        
        self.potential_path_edit = QLineEdit()
        self.potential_path_edit.setEnabled(False)
        self.potential_path_browse = QPushButton("Browse...")
        # Browse button should always be enabled to allow browsing and auto-checking the checkbox
        self.potential_path_browse.clicked.connect(self.browse_potential_file)
        
        # Add tooltips
        self.potential_path_edit.setToolTip("Path to the potential file containing force field parameters")
        self.potential_path_browse.setToolTip("Browse for potential file")
        
        potential_path_layout = QHBoxLayout()
        potential_path_layout.addWidget(self.potential_path_edit)
        potential_path_layout.addWidget(self.potential_path_browse)
        
        potential_label = QLabel("Potential File Path:")
        potential_label.setToolTip("Click to open LAMMPS include documentation")
        
        potential_layout.addRow(self.use_potential_file)
        potential_layout.addRow(potential_label, potential_path_layout)
        potential_group.setLayout(potential_layout)
        scroll_layout.addWidget(potential_group)
        
        # Basic LAMMPS settings
        basic_group = InfoGroupBox("Basic LAMMPS Settings", "atom_style")
        basic_layout = QFormLayout()
        
        self.atom_style_combo = QComboBox()
        self.atom_style_combo.addItems(["atomic", "bond", "molecular", "full", "charge", "dipole"])
        self.atom_style_combo.setToolTip("Specify the atom style for the simulation")
        
        atom_style_label = QLabel("Atom Style:")
        
        basic_layout.addRow(atom_style_label, self.atom_style_combo)
        basic_group.setLayout(basic_layout)
        scroll_layout.addWidget(basic_group)
        
        # Units selection (moved here from top)
        units_group = InfoGroupBox("Units Selection", "units")
        units_layout = QHBoxLayout()
        
        units_label = QLabel("Units:")
        
        self.units_combo = QComboBox()
        self.units_combo.addItems(["lj", "real", "metal", "si", "cgs", "electron", "micro", "nano"])
        self.units_combo.setCurrentText("metal")
        self.units_combo.setToolTip("Select the unit system for the simulation")
        
        # Update timestep display when units change
        self.units_combo.currentTextChanged.connect(self.update_units_display)
        
        units_layout.addWidget(units_label)
        units_layout.addWidget(self.units_combo)
        units_layout.addStretch()
        
        units_group.setLayout(units_layout)
        scroll_layout.addWidget(units_group)

        # Timestep settings
        timestep_group = InfoGroupBox("Timestep Settings", "timestep")
        timestep_layout = QHBoxLayout()

        self.timestep = QDoubleSpinBox()
        self.timestep.setRange(0.000001, 10.0)
        self.timestep.setValue(0.001)
        self.timestep.setDecimals(6)
        self.timestep.setToolTip("Integration timestep for the simulation")
        self.timestep.setMinimumWidth(120)
        self.timestep.valueChanged.connect(self.update_timestep_step)
        self.update_timestep_step(self.timestep.value())

        self.timestep_unit_label = QLabel("ps")

        timestep_label = QLabel("Timestep:")

        timestep_layout.addWidget(timestep_label)
        timestep_layout.addWidget(self.timestep)
        timestep_layout.addWidget(self.timestep_unit_label)
        timestep_layout.addStretch()
        timestep_group.setLayout(timestep_layout)
        scroll_layout.addWidget(timestep_group)

        # Boundary conditions
        boundary_group = InfoGroupBox("Boundary Conditions", "boundary")
        main_boundary_layout = QVBoxLayout()
        boundary_layout = QHBoxLayout()

        # X Boundary
        x_layout = QVBoxLayout()
        x_label = QLabel("X Boundary:")
        self.boundary_x_combo = QComboBox()
        self.boundary_x_combo.addItems(["p", "f", "s", "m"])
        self.boundary_x_combo.setCurrentText("p")
        self.boundary_x_combo.setToolTip("X boundary condition: p=periodic, f=fixed, s=shrink, m=shrink-wrap")
        x_layout.addWidget(x_label)
        x_layout.addWidget(self.boundary_x_combo)
        boundary_layout.addLayout(x_layout)

        # Y Boundary
        y_layout = QVBoxLayout()
        y_label = QLabel("Y Boundary:")
        self.boundary_y_combo = QComboBox()
        self.boundary_y_combo.addItems(["p", "f", "s", "m"])
        self.boundary_y_combo.setCurrentText("p")
        self.boundary_y_combo.setToolTip("Y boundary condition: p=periodic, f=fixed, s=shrink, m=shrink-wrap")
        y_layout.addWidget(y_label)
        y_layout.addWidget(self.boundary_y_combo)
        boundary_layout.addLayout(y_layout)

        # Z Boundary
        z_layout = QVBoxLayout()
        z_label = QLabel("Z Boundary:")
        self.boundary_z_combo = QComboBox()
        self.boundary_z_combo.addItems(["p", "f", "s", "m"])
        self.boundary_z_combo.setCurrentText("p")
        self.boundary_z_combo.setToolTip("Z boundary condition: p=periodic, f=fixed, s=shrink, m=shrink-wrap")
        z_layout.addWidget(z_label)
        z_layout.addWidget(self.boundary_z_combo)
        boundary_layout.addLayout(z_layout)
        
        main_boundary_layout.addLayout(boundary_layout)
        boundary_group.setLayout(main_boundary_layout)
        scroll_layout.addWidget(boundary_group)

        # Ensemble settings
        ensemble_group = InfoGroupBox("Ensemble Settings", "fix_nh")
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
        self.pressure.setRange(-100000, 100000)
        self.pressure.setValue(1.0)
        self.pressure.setDecimals(4)
        self.pressure.setEnabled(False)  # Only enabled for NPT
        self.pressure.setToolTip("Target pressure for NPT ensemble")
        self.pressure.setMinimumWidth(120)

        self.pressure_unit_label = QLabel("atm")

        pressure_layout = QHBoxLayout()
        pressure_layout.addWidget(self.pressure)
        pressure_layout.addWidget(self.pressure_unit_label)

        ensemble_label = QLabel("Ensemble:")

        ensemble_layout.addRow(ensemble_label, self.ensemble_combo)
        ensemble_layout.addRow("Initial Temperature:", self.temp_init)
        ensemble_layout.addRow("Final Temperature:", self.temp_end)
        ensemble_layout.addRow("Pressure (NPT only):", pressure_layout)
        ensemble_group.setLayout(ensemble_layout)
        scroll_layout.addWidget(ensemble_group)

        # Connect ensemble combo box signal
        self.ensemble_combo.currentTextChanged.connect(self.toggle_ensemble_settings)
        
        # Velocity initialization settings
        velocity_group = InfoGroupBox("Velocity Initialization", "velocity")
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
        neighbor_group = InfoGroupBox("Neighbor Settings", "neighbor")
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
        
        # Add stretch to push everything up
        scroll_layout.addStretch()
        
    def create_fixes_tab(self):
        """Create the fixes tab"""
        self.fixes_tab = QWidget()
        self.tab_widget.addTab(self.fixes_tab, "Fixes && Computes")

        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll_widget = QWidget()
        scroll_layout = QVBoxLayout(scroll_widget)
        scroll.setWidget(scroll_widget)

        fixes_layout = QVBoxLayout(self.fixes_tab)
        fixes_layout.addWidget(scroll)

        # Custom fixes
        custom_fixes_group = InfoGroupBox("Custom Fixes", "fix")
        custom_fixes_layout = QVBoxLayout()

        self.enable_custom_fixes = QCheckBox("Enable Custom Fixes")
        self.enable_custom_fixes.setChecked(False)
        self.enable_custom_fixes.setToolTip("Enable custom fix commands")
        self.enable_custom_fixes.stateChanged.connect(self.toggle_custom_fixes)

        self.custom_fixes_text = QTextEdit()
        self.custom_fixes_text.setPlaceholderText("Enter custom fix commands here...")
        self.custom_fixes_text.setMaximumHeight(150)  # Significantly reduce height
        self.custom_fixes_text.setEnabled(False)
        self.custom_fixes_text.setToolTip("Custom LAMMPS fix commands")

        custom_fixes_layout.addWidget(self.enable_custom_fixes)
        custom_fixes_layout.addWidget(self.custom_fixes_text)
        custom_fixes_group.setLayout(custom_fixes_layout)
        scroll_layout.addWidget(custom_fixes_group)

        # Custom computes
        custom_computes_group = InfoGroupBox("Custom Computes", "compute")
        custom_computes_layout = QVBoxLayout()

        self.enable_custom_computes = QCheckBox("Enable Custom Computes")
        self.enable_custom_computes.setChecked(False)
        self.enable_custom_computes.setToolTip("Enable custom compute commands")
        self.enable_custom_computes.stateChanged.connect(self.toggle_custom_computes)

        # Add compute commands button - place it on the same line as the checkbox
        top_layout = QHBoxLayout()
        top_layout.addWidget(self.enable_custom_computes)
        top_layout.addStretch()

        self.compute_commands_button = QPushButton("Add Compute Command")
        self.compute_commands_button.clicked.connect(self.show_compute_commands_dialog)
        self.compute_commands_button.setMaximumWidth(180)  # Limit button width
        top_layout.addWidget(self.compute_commands_button)

        self.custom_computes_text = QTextEdit()
        self.custom_computes_text.setPlaceholderText("Enter custom compute commands here...")
        self.custom_computes_text.setMaximumHeight(150)
        self.custom_computes_text.setEnabled(False)
        self.custom_computes_text.setToolTip("Custom LAMMPS compute commands")

        custom_computes_layout.addLayout(top_layout)
        custom_computes_layout.addWidget(self.custom_computes_text)
        custom_computes_group.setLayout(custom_computes_layout)
        scroll_layout.addWidget(custom_computes_group)

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
                    self.update_units_display(units)
            
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
                # Read the first line which typically contains the units information
                first_line = f.readline().strip()
                
                # Check for units in the first line format: "LAMMPS data file ... units = <unit_type>"
                if "units =" in first_line:
                    # Extract units value after "units ="
                    parts = first_line.split("units =")
                    if len(parts) > 1:
                        units = parts[1].strip()
                        # Remove any trailing commas or other characters
                        units = units.split(',')[0].strip()
                        return units
                
                # If not found in first line, check other lines for different formats
                f.seek(0)  # Reset to beginning of file
                for line in f:
                    line = line.strip()
                    if line.startswith("units") or line.startswith("units ="):
                        # Extract units value (formats: units <value> or units = <value>)
                        if "=" in line:
                            parts = line.split("=", 1)
                        else:
                            parts = line.split(None, 1)
                        if len(parts) > 1:
                            units = parts[1].strip()
                            units = units.split(',')[0].strip()
                            return units
        except Exception as e:
            print(f"Error reading units from data file: {e}")
        return None
    
    def read_atom_style_from_data_file(self, data_file):
        """Read atom style from LAMMPS data file"""
        try:
            with open(data_file, 'r') as f:
                # Look for the "Atoms # <atom_style>" line in the file
                for line in f:
                    line = line.strip()
                    if line.startswith("Atoms") and "#" in line:
                        # Format: "Atoms # <atom_style>"
                        parts = line.split("#")
                        if len(parts) > 1:
                            atom_style_part = parts[1].strip()
                            # The atom style is the rest of the line after #
                            atom_style = atom_style_part
                            return atom_style
                
                # If not found in Atoms line, check for atom_style lines
                f.seek(0)  # Reset to beginning of file
                for line in f:
                    line = line.strip()
                    if line.startswith("atom_style") or line.startswith("atom_style ="):
                        # Extract atom style value (formats: atom_style <value> or atom_style = <value>)
                        if "=" in line:
                            parts = line.split("=", 1)
                        else:
                            parts = line.split(None, 1)
                        if len(parts) > 1:
                            atom_style = parts[1].strip()
                            return atom_style
        except Exception as e:
            print(f"Error reading atom style from data file: {e}")
        return None
            
    def update_units_display(self, units):
        """Update unit displays based on selected units"""
        timestep_units = {
            "lj": "τ", "real": "fs", "metal": "ps", "si": "s",
            "cgs": "s", "electron": "fs", "micro": "µs", "nano": "ns"
        }
        pressure_units = {
            "lj": "pressure*", "real": "atm", "metal": "bars", "si": "Pa",
            "cgs": "dyne/cm^2", "electron": "bars", "micro": "atm", "nano": "atm"
        }
        
        self.timestep_unit_label.setText(timestep_units.get(units.lower(), "ps"))
        self.pressure_unit_label.setText(pressure_units.get(units.lower(), "atm"))
        
        # Update deformation tab graphs
        if hasattr(self, 'deformation_tab_widget'):
            self.deformation_tab_widget.update_all_graphs(self.timestep.value(), units)

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

    def update_timestep_step(self, value):
        """Update the single step of the timestep spinbox to increment the last non-zero digit."""
        s = f"{value:.10f}"
        if '.' in s:
            s = s.rstrip('0')
            last_digit_pos = len(s) - s.rfind('.') - 1
            if last_digit_pos > 0:
                self.timestep.setSingleStep(10**(-last_digit_pos))
                return
        self.timestep.setSingleStep(1.0)
        
    def create_deformation_tab(self):
        """Create the deformation processing tab with the graphical UI"""
        self.deformation_tab = QWidget()
        self.tab_widget.addTab(self.deformation_tab, "Deformation Processing")
        
        deformation_layout = QVBoxLayout(self.deformation_tab)
        
        if DeformationTab is None:
            label = QLabel("Error: DeformationTab could not be imported from graph_widgets.py")
            deformation_layout.addWidget(label)
            return

        self.deformation_tab_widget = DeformationTab(self, self)
        deformation_layout.addWidget(self.deformation_tab_widget)
        
        # Connect signals
        self.timestep.valueChanged.connect(lambda val: self.deformation_tab_widget.update_all_graphs(val, self.units_combo.currentText()))
        self.units_combo.currentTextChanged.connect(lambda text: self.deformation_tab_widget.update_all_graphs(self.timestep.value(), text))
        
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
        traj_group = InfoGroupBox("Trajectory Output Settings", "dump")
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
        thermo_group = InfoGroupBox("Thermo Output Settings", "thermo_style")
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
        
        # Custom dumps
        custom_dumps_group = InfoGroupBox("Custom Dumps", "dump")
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
        
    def toggle_custom_dumps(self, state):
        """Toggle custom dumps text box based on checkbox state"""
        enabled = state == Qt.CheckState.Checked.value
        self.custom_dumps_text.setEnabled(enabled)

    def create_job_submission_tab(self):
        """Create the job submission tab"""
        self.job_submission_tab = QWidget()
        self.tab_widget.addTab(self.job_submission_tab, "Job Submission")

        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll_widget = QWidget()
        scroll_layout = QVBoxLayout(scroll_widget)
        scroll.setWidget(scroll_widget)

        job_submission_layout = QVBoxLayout(self.job_submission_tab)
        job_submission_layout.addWidget(scroll)

        # Local settings
        local_group = QGroupBox("Local Settings")
        local_layout = QFormLayout()

        self.local_lammps_cmd = QLineEdit()
        self.local_lammps_cmd.setPlaceholderText("lmp")
        self.local_lammps_cmd.setToolTip("Command to run LAMMPS locally.")
        local_layout.addRow("Local LAMMPS Command:", self.local_lammps_cmd)

        local_group.setLayout(local_layout)
        scroll_layout.addWidget(local_group)

        # Cluster settings
        cluster_group = InfoGroupBox("Cluster Settings", "https://hpc-wiki.info/hpc/SLURM", is_external=True)
        cluster_layout = QFormLayout()

        self.cluster_lammps_cmd = QLineEdit()
        self.cluster_lammps_cmd.setPlaceholderText("lmp")
        self.cluster_lammps_cmd.setToolTip("Command to run LAMMPS on the cluster.")
        cluster_layout.addRow("Cluster LAMMPS Command:", self.cluster_lammps_cmd)

        self.srun_cmd = QLineEdit()
        self.srun_cmd.setPlaceholderText("srun")
        self.srun_cmd.setToolTip("srun command for cluster execution.")
        cluster_layout.addRow("srun Command:", self.srun_cmd)

        self.sbatch_cmd = QLineEdit()
        self.sbatch_cmd.setPlaceholderText("sbatch")
        self.sbatch_cmd.setToolTip("sbatch command for cluster job submission.")
        cluster_layout.addRow("sbatch Command:", self.sbatch_cmd)

        self.module_load_cmd = QLineEdit()
        self.module_load_cmd.setPlaceholderText("lammps")
        self.module_load_cmd.setToolTip("Module to load on the cluster.")
        cluster_layout.addRow("Module Load:", self.module_load_cmd)

        self.slurm_header_text = QTextEdit()
        self.slurm_header_text.setPlainText("""#!/bin/bash -l
#SBATCH --job-name=lammps_simulation
#SBATCH --partition=singlenode
#SBATCH --nodes=1
#SBATCH --ntasks-per-node=72
#SBATCH --cpus-per-task=1
#SBATCH --time=24:00:00
#SBATCH --export=NONE
#SBATCH --output=lammps_output_%j.txt
#SBATCH --error=lammps_error_%j.txt""")
        self.slurm_header_text.setToolTip("SLURM batch script header.")
        self.slurm_header_text.setMinimumHeight(300)
        cluster_layout.addRow("SLURM Header:", self.slurm_header_text)

        cluster_group.setLayout(cluster_layout)
        scroll_layout.addWidget(cluster_group)

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
            # Automatically check the "Use separate potential file" checkbox
            if not self.use_potential_file.isChecked():
                self.use_potential_file.setChecked(True)
    
    def toggle_potential_file(self, state):
        """Toggle potential file settings"""
        enabled = state == Qt.CheckState.Checked.value
        self.potential_path_edit.setEnabled(enabled)
        # Note: The browse button should always be enabled to allow browsing
    
    def browse_output_path(self):
        """Browse for output path"""
        dir_path = QFileDialog.getExistingDirectory(self, "Select Output Directory")
        if dir_path:
            self.output_path_edit.setText(dir_path)
    
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
        
    def show_compute_commands_dialog(self):
        """Show dialog with common compute commands"""
        commands = [
            "compute ke all ke/atom",
            "compute pe all pe/atom",
            "compute stress all stress/atom NULL",
            "compute temp all temp",
            "compute pressure all pressure",
            "compute msd all msd"
        ]
        
        dialog = QDialog(self)
        dialog.setWindowTitle("Select Compute Command")
        dialog.setMinimumSize(300, 200)
        
        layout = QVBoxLayout()
        
        list_widget = QListWidget()
        list_widget.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection)  # Allow only single selection
        for command in commands:
            list_widget.addItem(command)
        
        button_box = QDialogButtonBox()
        add_button = QPushButton("Add")
        button_box.addButton(add_button, QDialogButtonBox.ButtonRole.AcceptRole)
        button_box.addButton(QDialogButtonBox.StandardButton.Cancel)
        button_box.accepted.connect(lambda: self._add_selected_compute_command(list_widget, dialog))
        button_box.rejected.connect(dialog.reject)
        
        layout.addWidget(list_widget)
        layout.addWidget(button_box)
        
        dialog.setLayout(layout)
        
        dialog.exec()
        
    def _add_selected_compute_command(self, list_widget, dialog):
        """Add selected compute command to the text field"""
        selected_items = list_widget.selectedItems()
        if selected_items:
            command = selected_items[0].text()
            # Enable the custom computes checkbox if it's not already enabled
            if not self.enable_custom_computes.isChecked():
                self.enable_custom_computes.setChecked(True)
            
            # Add the command to the text field
            current_text = self.custom_computes_text.toPlainText()
            if current_text:
                self.custom_computes_text.setPlainText(current_text + "\n" + command)
            else:
                self.custom_computes_text.setPlainText(command)
        dialog.accept()
    
    def toggle_custom_dumps(self, state):
        """Toggle custom dumps settings based on checkbox state"""
        enabled = state == Qt.CheckState.Checked.value
        self.custom_dumps_text.setEnabled(enabled)

    def toggle_custom_fixes(self, state):
        """Toggle custom fixes settings based on checkbox state"""
        enabled = state == Qt.CheckState.Checked.value
        self.custom_fixes_text.setEnabled(enabled)

    def validate_paths(self):
        """Validate all user-provided paths for invalid characters"""
        paths_to_check = {
            "System Path": self.system_path_edit.text(),
            "Potential File Path": self.potential_path_edit.text() if self.use_potential_file.isChecked() else "",
            "Output Path": self.output_path_edit.text()
        }
        
        invalid_paths = []
        # Regex to find spaces or non-ascii characters that are not basic path separators
        invalid_char_re = re.compile(r'[\säöüÄÖÜß]')

        for name, path in paths_to_check.items():
            if not path:
                continue

            if invalid_char_re.search(path):
                # Highlight invalid characters
                highlighted_path = ""
                for char in path:
                    if invalid_char_re.search(char):
                        highlighted_path += f"<b>{char}</b>"
                    else:
                        highlighted_path += char
                invalid_paths.append(f"<li><b>{name}:</b> {highlighted_path}</li>")

        if invalid_paths:
            error_message = "The following paths contain spaces or special characters that are not allowed:<br><ul>"
            error_message += "".join(invalid_paths)
            error_message += "</ul>Please correct them before generating scripts."
            QMessageBox.critical(self, "Invalid Paths", error_message)
            return False
            
        return True
    
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
            "• run_local_all.sh/.bat: OS-specific local execution script (generated based on your OS). Each simulation runs in its own terminal.\n"
            "• run_cluster_jobs.sh: Cluster job submission script for Linux clusters only.\n"
            "• lammps_simulation.job: Single master job file that accepts input file as argument.\n"
            "• All .in files are located in their respective study/system folders\n"
            "• Data files are copied to the input_files folder with correct relative paths (../../input_files/)\n"
            "• Potential files are also copied to input_files folder and referenced correctly\n"
            "• Output directories are created automatically in each study/system folder"
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
            border: 1px solid #cccccc;
            border-radius: 4px;
            margin-top: 8px;
            padding-top: 6px;
            background-color: #ffffff;
        }
        
        QGroupBox::title {
            subcontrol-origin: margin;
            left: 8px;
            padding: 0 3px 0 3px;
            font-size: 11px;
        }
        
        QPushButton {
            background-color: #007acc;
            color: white;
            border: none;
            border-radius: 3px;
            padding: 4px 12px;
            font-size: 12px;
            min-height: 20px;
            max-height: 28px;
            font-weight: normal;
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
            border-radius: 3px;
            padding: 2px;
            background-color: white;
            font-size: 12px;
            min-height: 16px;
        }
        
        QLineEdit:focus, QTextEdit:focus, QComboBox:focus, QSpinBox:focus, QDoubleSpinBox:focus {
            border: 1px solid #007acc;
        }
        
        QCheckBox {
            spacing: 6px;
            font-size: 12px;
        }
        
        QCheckBox::indicator {
            width: 14px;
            height: 14px;
            border: 1px solid #cccccc;
            border-radius: 2px;
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
            padding: 2px;
            font-size: 11px;
        }
        
        QTableWidget::header {
            background-color: #f5f5f5;
            padding: 2px;
            font-weight: bold;
            font-size: 11px;
        }
        
        QLabel {
            font-size: 12px;
        }
        
        QFormLayout {
            spacing: 3px;
        }
        
        QVBoxLayout, QHBoxLayout {
            spacing: 4px;
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
            "fixes": {
                "enable_custom_fixes": self.enable_custom_fixes.isChecked(),
                "custom_fixes": self.custom_fixes_text.toPlainText()
            },
            "output": {
                "output_path": self.output_path_edit.text(),
                "enable_trajectory": self.enable_trajectory.isChecked(),
                "traj_format": self.traj_format.currentText(),
                "trj_output_items": self.trj_output_items.toPlainText(),
                "enable_thermo": self.enable_thermo.isChecked(),
                "thermo_style": self.thermo_style.toPlainText(),
                "enable_custom_computes": self.enable_custom_computes.isChecked(),
                "custom_computes": self.custom_computes_text.toPlainText(),
                "enable_custom_dumps": self.enable_custom_dumps.isChecked(),
                "custom_dumps": self.custom_dumps_text.toPlainText()
            },
            
            "multistudy": {
                "deform_studies": []
            },
            "job_submission": {
                "local_lammps_cmd": self.local_lammps_cmd.text() or "lmp",
                "cluster_lammps_cmd": self.cluster_lammps_cmd.text() or "lmp",
                "srun_cmd": self.srun_cmd.text() or "srun",
                "sbatch_cmd": self.sbatch_cmd.text() or "sbatch",
                "module_load": self.module_load_cmd.text() or "lammps",
                "slurm_header": self.slurm_header_text.toPlainText() or """#!/bin/bash
#SBATCH --job-name=lammps_simulation
#SBATCH --partition=singlenode
#SBATCH --nodes=1
#SBATCH --ntasks-per-node=72
#SBATCH --cpus-per-task=1
#SBATCH --time=24:00:00
#SBATCH --export=NONE
#SBATCH --output=lammps_output_%j.txt
#SBATCH --error=lammps_error_%j.txt"""
            }
        }
        
        # Collect deformation studies from the graphical UI
        if hasattr(self, 'deformation_tab_widget'):
            for i in range(self.deformation_tab_widget.tab_widget.count()):
                study_widget = self.deformation_tab_widget.tab_widget.widget(i)
                study_name = self.deformation_tab_widget.tab_widget.tabText(i)

                if study_name == "+":
                    continue
                
                # Get the full state from the study widget
                study_state = study_widget.get_state()
                study_state["name"] = study_name # Add the name to the state
                config["multistudy"]["deform_studies"].append(study_state)

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
            
            # Fixes settings
            self.enable_custom_fixes.setChecked(self.settings.value("fixes/enable_custom_fixes", False, type=bool))
            self.custom_fixes_text.setPlainText(self.settings.value("fixes/custom_fixes", ""))
            
            # Output settings
            self.output_path_edit.setText(self.settings.value("output/output_path", ""))
            self.enable_trajectory.setChecked(self.settings.value("output/enable_trajectory", True, type=bool))
            self.traj_format.setCurrentText(self.settings.value("output/traj_format", "lammpstrj"))
            self.trj_output_items.setPlainText(self.settings.value("output/trj_output_items", "id type x y z fx fy fz"))
            self.enable_thermo.setChecked(self.settings.value("output/enable_thermo", True, type=bool))
            self.thermo_style.setPlainText(self.settings.value("output/thermo_style", "step etotal pe ke epair ebond evdwl ecoul elong temp press pxx pyy pzz pxy pxz pyz lx ly lz density"))
            self.enable_custom_computes.setChecked(self.settings.value("output/enable_custom_computes", False, type=bool))
            self.custom_computes_text.setPlainText(self.settings.value("output/custom_computes", ""))
            self.enable_custom_dumps.setChecked(self.settings.value("output/enable_custom_dumps", False, type=bool))
            self.custom_dumps_text.setPlainText(self.settings.value("output/custom_dumps", ""))

            # Job submission settings
            self.local_lammps_cmd.setText(self.settings.value("job_submission/local_lammps_cmd", ""))
            self.cluster_lammps_cmd.setText(self.settings.value("job_submission/cluster_lammps_cmd", ""))
            self.srun_cmd.setText(self.settings.value("job_submission/srun_cmd", ""))
            self.sbatch_cmd.setText(self.settings.value("job_submission/sbatch_cmd", ""))
            self.module_load_cmd.setText(self.settings.value("job_submission/module_load", ""))
            self.slurm_header_text.setPlainText(self.settings.value("job_submission/slurm_header", ""))
            
            # Multi-study settings
            if hasattr(self, 'deformation_tab_widget'):
                studies_data = self.settings.value("multistudy/deform_studies")
                studies = []
                if studies_data:
                    try:
                        studies = json.loads(studies_data)
                    except (json.JSONDecodeError, TypeError):
                        studies = [] # If data is corrupted, start fresh

                # Clear existing tabs (created in DeformationTab constructor)
                while self.deformation_tab_widget.tab_widget.count() > 0:
                    self.deformation_tab_widget.tab_widget.removeTab(0)

                if studies:
                    for i, study in enumerate(studies):
                        self.deformation_tab_widget._add_study(is_first=(i==0))
                        study_widget = self.deformation_tab_widget.tab_widget.widget(i)
                        original_name = study.get("name", f"Study_{i+1}")
                        sanitized_name = re.sub(r'[^a-zA-Z0-9_-]', '_', original_name)
                        
                        # Ensure uniqueness
                        final_name = sanitized_name
                        suffix = 1
                        while any(final_name == self.deformation_tab_widget.tab_widget.tabText(j) for j in range(self.deformation_tab_widget.tab_widget.count()) if j != i):
                            final_name = f"{sanitized_name}_{suffix}"
                            suffix += 1

                        self.deformation_tab_widget.tab_widget.setTabText(i, final_name)

                        # Restore the state of the study widget
                        state = {
                            'data_points': study.get("data_points", study.get("points", [])), # backward compatibility
                            'max_steps': study.get("max_steps", 100),
                            'min_strain': study.get("min_strain", 0.0),
                            'max_strain': study.get("max_strain", 1.0),
                            'thermo_freq': study.get("thermo_freq", 100),
                            'deform_axis': study.get("deform_axis", "x"),
                            'bond_breakage': study.get("bond_breakage", {}) # Add bond breakage settings
                        }
                        study_widget.set_state(state)
                else:
                    # No studies in settings, or settings were corrupted. Create a default one.
                    self.deformation_tab_widget._add_study(is_first=True)
                
                # Plus tab is handled by the corner widget button, no need to add it here
                pass

        except Exception as e:
            print(f"Error loading settings: {e}")
    
    def save_settings(self):
        """Save settings to QSettings"""
        try:
            config = self.collect_config()
            
            # Save system settings
            for key, value in config["system"].items():
                self.settings.setValue(f"system/{key}", value)
            
            # Save fixes settings
            for key, value in config["fixes"].items():
                self.settings.setValue(f"fixes/{key}", value)
            
            # Save output settings
            for key, value in config["output"].items():
                self.settings.setValue(f"output/{key}", value)

            # Save job_submission settings
            for key, value in config["job_submission"].items():
                self.settings.setValue(f"job_submission/{key}", value)

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
        if not self.validate_paths():
            return

        try:
            # Collect configuration with error handling
            try:
                config = self.collect_config()
            except Exception as e:
                QMessageBox.critical(self, "Error", f"Error collecting configuration: {str(e)}")
                return
            
            # Validate configuration
            if not config.get("system", {}).get("system_path"):
                QMessageBox.warning(self, "Warning", "Please select a system path.")
                return
            
            deform_studies = config.get("multistudy", {}).get("deform_studies", [])
            if not deform_studies:
                QMessageBox.warning(self, "Warning", "Please define at least one deformation study.")
                return
            
            # Validate system path exists
            system_path = config["system"]["system_path"]
            if not os.path.exists(system_path):
                QMessageBox.critical(self, "Error", f"System path does not exist: {system_path}")
                return

            # Check if output path is not empty and ask user for action
            output_path = config["output"]["output_path"]
            if os.path.exists(output_path) and os.listdir(output_path):
                msg_box = QMessageBox(self)
                msg_box.setIcon(QMessageBox.Icon.Warning)
                msg_box.setText("The output directory is not empty.")
                msg_box.setInformativeText("What would you like to do?")
                delete_button = msg_box.addButton("Delete Contents", QMessageBox.ButtonRole.DestructiveRole)
                overwrite_button = msg_box.addButton("Overwrite", QMessageBox.ButtonRole.AcceptRole)
                abort_button = msg_box.addButton("Abort", QMessageBox.ButtonRole.RejectRole)
                msg_box.setDefaultButton(overwrite_button)

                msg_box.exec()

                if msg_box.clickedButton() == delete_button:
                    try:
                        for filename in os.listdir(output_path):
                            file_path = os.path.join(output_path, filename)
                            if os.path.isfile(file_path) or os.path.islink(file_path):
                                os.unlink(file_path)
                            elif os.path.isdir(file_path):
                                shutil.rmtree(file_path)
                    except Exception as e:
                        QMessageBox.critical(self, "Error", f"Failed to delete directory contents: {e}")
                        return
                elif msg_box.clickedButton() == abort_button:
                    return

            # Generate scripts
            if ScriptGen:
                try:
                    generator = ScriptGen(config)
                    result = generator.generate_all_scripts()
                    
                    if result.get("success"):
                        self.show_generated_files_dialog(result)
                    else:
                        error_msg = result.get("message", "Unknown error occurred")
                        QMessageBox.critical(self, "Error", f"Error generating scripts: {error_msg}")
                except Exception as e:
                    QMessageBox.critical(self, "Error", f"Error in script generator: {str(e)}")
            else:
                QMessageBox.critical(self, "Error", "Script generator not available.")
                
        except Exception as e:
            QMessageBox.critical(self, "Error", f"Unexpected error generating scripts: {str(e)}")
    
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
            # Fixes configuration
            if "fixes" in config:
                fixes = config["fixes"]
                self.enable_custom_fixes.setChecked(fixes.get("enable_custom_fixes", False))
                self.custom_fixes_text.setPlainText(fixes.get("custom_fixes", ""))

            # Output configuration
            if "output" in config:
                output = config["output"]
                self.output_path_edit.setText(output.get("output_path", ""))
                self.enable_trajectory.setChecked(output.get("enable_trajectory", True))
                self.traj_format.setCurrentText(output.get("traj_format", "lammpstrj"))
                self.trj_output_items.setPlainText(output.get("trj_output_items", "id type x y z fx fy fz"))
                self.enable_thermo.setChecked(output.get("enable_thermo", True))
                self.thermo_style.setPlainText(output.get("thermo_style", "step etotal pe ke epair ebond evdwl ecoul elong temp press pxx pyy pzz pxy pxz pyz lx ly lz density"))
                self.enable_custom_computes.setChecked(output.get("enable_custom_computes", False))
                self.custom_computes_text.setPlainText(output.get("custom_computes", ""))
                self.enable_custom_dumps.setChecked(output.get("enable_custom_dumps", False))
                self.custom_dumps_text.setPlainText(output.get("custom_dumps", ""))
            
            # Cluster configuration (widgets removed, so skip loading)
            if "cluster" in config:
                cluster = config["cluster"]
                # self.execution_mode_combo.setCurrentText(cluster.get("execution_mode", "local"))  # Removed - no longer needed
                # self.lammps_command_edit.setText(cluster.get("lammps_command", "lmp"))
                # self.threads_spin.setValue(cluster.get("threads", 4))
                # self.cluster_partition.setText(cluster.get("cluster_partition", "singlenode"))
                # self.cluster_nodes.setValue(cluster.get("cluster_nodes", 1))
                # self.cluster_ntasks.setValue(cluster.get("cluster_ntasks", 72))
                # self.cluster_time.setText(cluster.get("cluster_time", "24:00:00"))
                # self.cluster_mail.setText(cluster.get("cluster_mail", ""))
                # self.cluster_mail_type.setCurrentText(cluster.get("cluster_mail_type", "ALL"))
                # self.auto_submit.setChecked(cluster.get("auto_submit", False))
                # self.show_command.setChecked(cluster.get("show_command", True))
                # self.save_scripts_only.setChecked(cluster.get("save_scripts_only", False))
            
            # Multi-study configuration
            if "multistudy" in config and hasattr(self, 'deformation_tab_widget'):
                multistudy = config["multistudy"]
                studies = multistudy.get("deform_studies", [])

                # Clear existing tabs
                while self.deformation_tab_widget.tab_widget.count() > 0:
                    self.deformation_tab_widget.tab_widget.removeTab(0)

                for i, study_data in enumerate(studies):
                    self.deformation_tab_widget._add_study(is_first=(i==0))
                    study_widget = self.deformation_tab_widget.tab_widget.widget(i)
                    self.deformation_tab_widget.tab_widget.setTabText(i, study_data.get("name", f"Study {i+1}"))

                    state = {
                        'data_points': study_data.get("data_points", []),
                        'max_steps': study_data.get("max_steps", 100),
                        'min_strain': study_data.get("min_strain", 0.0),
                        'max_strain': study_data.get("max_strain", 1.0),
                        'thermo_freq': study_data.get("thermo_freq", 100),
                        'deform_axis': study_data.get("deform_axis", "x"),
                        'bond_breakage': study_data.get("bond_breakage", {}) # Add bond breakage settings
                    }
                    study_widget.set_state(state)

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