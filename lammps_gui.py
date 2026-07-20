#!/usr/bin/env python3
"""
LAMMPS Input Script Generator GUI

A graphical user interface for creating LAMMPS input scripts for particle-based deformation simulations.
Supports both local execution and cluster job submission.
"""

import sys
import os
import json
import glob
import tempfile
import threading
import time
from pathlib import Path
from PyQt5.QtWidgets import (QApplication, QMainWindow, QTabWidget, QWidget, QVBoxLayout, 
                            QHBoxLayout, QLabel, QLineEdit, QPushButton, QFileDialog, 
                            QComboBox, QCheckBox, QSpinBox, QDoubleSpinBox, QTextEdit,
                            QGroupBox, QFormLayout, QRadioButton, QButtonGroup, QScrollArea,
                            QSplitter, QMessageBox, QProgressBar, QDialog, QGridLayout,
                            QTableWidget, QTableWidgetItem, QHeaderView, QAbstractItemView,
                            QDialogButtonBox, QToolTip, QFrame, QSizePolicy)
from PyQt5.QtCore import Qt, QSettings, pyqtSignal, QThread, QTimer, QUrl, QSize
from PyQt5.QtGui import QFont, QIcon, QDesktopServices, QCursor, QPalette, QColor
from script_generator import LammpsScriptGenerator

class LammpsScriptGenerator(QMainWindow):
    """Main application window for LAMMPS script generation"""
    
    def __init__(self):
        super().__init__()
        self.setWindowTitle("LAMMPS Input Script Generator")
        self.setGeometry(100, 100, 1200, 800)
        
        # Initialize settings
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
        self.create_multistudy_tab()
        
        # Create bottom buttons
        self.create_bottom_buttons()
        
        # Load saved settings
        self.load_settings()
        
        # Set up exception handling for crash recovery
        sys.excepthook = self.handle_exception
        
    def handle_exception(self, exc_type, exc_value, exc_traceback):
        """Handle uncaught exceptions and save settings"""
        print(f"Uncaught exception: {exc_type.__name__}: {exc_value}")
        self.emergency_save()
        
        # Show error message
        QMessageBox.critical(self, "Application Error", 
                          f"The application encountered an error:\n{exc_type.__name__}: {exc_value}\n\n"
                          f"Your settings have been saved automatically.")
        
        # Call original exception handler
        sys.__excepthook__(exc_type, exc_value, exc_traceback)
    
    def emergency_save(self):
        """Emergency save of current settings"""
        try:
            config = self.collect_config()
            emergency_file = os.path.join(tempfile.gettempdir(), "lammps_gui_emergency_save.json")
            with open(emergency_file, 'w') as f:
                json.dump(config, f, indent=2)
            print(f"Emergency save completed: {emergency_file}")
        except Exception as e:
            print(f"Emergency save failed: {e}")
    
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
        
        # Data file selection
        data_group = QGroupBox("Data File Selection")
        data_layout = QFormLayout()
        
        self.data_path_edit = QLineEdit()
        self.data_path_browse = QPushButton("Browse...")
        self.data_path_browse.clicked.connect(self.browse_data_file)
        
        # Add tooltips
        self.data_path_edit.setToolTip("Path to the LAMMPS data file containing atom positions and system information")
        self.data_path_browse.setToolTip("Browse for LAMMPS data file")
        
        # Add to widget references for focus jumping
        self.widget_references['data_file'] = self.data_path_edit
        
        data_path_layout = QHBoxLayout()
        data_path_layout.addWidget(self.data_path_edit)
        data_path_layout.addWidget(self.data_path_browse)
        
        # Make label clickable with documentation link
        data_label = QLabel("Data File Path:")
        data_label.setStyleSheet("color: blue; text-decoration: underline;")
        data_label.setCursor(QCursor(Qt.PointingHandCursor))
        data_label.mousePressEvent = lambda e: self.open_lammps_doc("read_data")
        data_label.setToolTip("Click to open LAMMPS read_data documentation")
        
        data_layout.addRow(data_label, data_path_layout)
        data_group.setLayout(data_layout)
        scroll_layout.addWidget(data_group)
        
        # Coordinate direction field
        coord_group = QGroupBox("Coordinate Settings")
        coord_layout = QFormLayout()
        
        self.coord_direction = QComboBox()
        self.coord_direction.addItems(["x", "y", "z", "xy", "xz", "yz", "xyz"])
        self.coord_direction.setCurrentText("xyz")
        self.coord_direction.setToolTip("Specify coordinate directions for loading and processing")
        
        coord_label = QLabel("Coordinate Direction:")
        coord_label.setStyleSheet("color: blue; text-decoration: underline;")
        coord_label.setCursor(QCursor(Qt.PointingHandCursor))
        coord_label.mousePressEvent = lambda e: self.open_lammps_doc("dimension")
        coord_label.setToolTip("Click to open LAMMPS dimension documentation")
        
        coord_layout.addRow(coord_label, self.coord_direction)
        coord_group.setLayout(coord_layout)
        scroll_layout.addWidget(coord_group)
        
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
        potential_label.setCursor(QCursor(Qt.PointingHandCursor))
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
        atom_style_label.setCursor(QCursor(Qt.PointingHandCursor))
        atom_style_label.mousePressEvent = lambda e: self.open_lammps_doc("atom_style")
        atom_style_label.setToolTip("Click to open LAMMPS atom_style documentation")
        
        basic_layout.addRow(atom_style_label, self.atom_style_combo)
        basic_group.setLayout(basic_layout)
        scroll_layout.addWidget(basic_group)
        
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
        boundary_label.setCursor(QCursor(Qt.PointingHandCursor))
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
        
        self.initial_velocity_seed = QSpinBox()
        self.initial_velocity_seed.setRange(1, 1000000)
        self.initial_velocity_seed.setValue(12345)
        self.initial_velocity_seed.setToolTip("Random seed for initial velocity generation")
        
        ensemble_label = QLabel("Ensemble:")
        ensemble_label.setStyleSheet("color: blue; text-decoration: underline;")
        ensemble_label.setCursor(QCursor(Qt.PointingHandCursor))
        ensemble_label.mousePressEvent = lambda e: self.open_lammps_doc("fix_nvt")
        ensemble_label.setToolTip("Click to open LAMMPS ensemble documentation")
        
        ensemble_layout.addRow(ensemble_label, self.ensemble_combo)
        ensemble_layout.addRow("Initial Temperature:", self.temp_init)
        ensemble_layout.addRow("Final Temperature:", self.temp_end)
        ensemble_layout.addRow("Pressure (NPT only):", self.pressure)
        ensemble_layout.addRow("Initial Velocity Seed:", self.initial_velocity_seed)
        ensemble_group.setLayout(ensemble_layout)
        scroll_layout.addWidget(ensemble_group)
        
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
        neighbor_label.setCursor(QCursor(Qt.PointingHandCursor))
        neighbor_label.mousePressEvent = lambda e: self.open_lammps_doc("neighbor")
        neighbor_label.setToolTip("Click to open LAMMPS neighbor documentation")
        
        neighbor_layout.addRow("Neighbor Distance:", self.neighbor_distance)
        neighbor_layout.addRow("Neigh Modify Every:", self.neigh_modify_every)
        neighbor_layout.addRow("Neigh Modify Delay:", self.neigh_modify_delay)
        neighbor_layout.addRow(self.neigh_modify_check)
        neighbor_group.setLayout(neighbor_layout)
        scroll_layout.addWidget(neighbor_group)
        
        # Connect ensemble combo box signal
        self.ensemble_combo.currentTextChanged.connect(self.toggle_ensemble_settings)
        
        # Timestep settings
        timestep_group = QGroupBox("Timestep Settings")
        timestep_layout = QFormLayout()
        
        self.timestep = QDoubleSpinBox()
        self.timestep.setRange(0.0001, 1.0)
        self.timestep.setValue(0.001)
        self.timestep.setSingleStep(0.0001)
        self.timestep.setDecimals(4)
        self.timestep.setToolTip("Integration timestep for the simulation")
        
        self.timestep_units = QComboBox()
        self.timestep_units.addItems(["fs", "ps", "ns"])
        self.timestep_units.setCurrentText("fs")
        self.timestep_units.setToolTip("Units for the timestep value")
        
        timestep_label = QLabel("Timestep:")
        timestep_label.setStyleSheet("color: blue; text-decoration: underline;")
        timestep_label.setCursor(QCursor(Qt.PointingHandCursor))
        timestep_label.mousePressEvent = lambda e: self.open_lammps_doc("timestep")
        timestep_label.setToolTip("Click to open LAMMPS timestep documentation")
        
        timestep_layout.addRow(timestep_label, self.timestep)
        timestep_layout.addRow("Timestep Units:", self.timestep_units)
        timestep_group.setLayout(timestep_layout)
        scroll_layout.addWidget(timestep_group)
        
        # Add stretch to push everything up
        scroll_layout.addStretch()
        
    def toggle_ensemble_settings(self, ensemble):
        """Toggle pressure field based on ensemble selection"""
        self.pressure.setEnabled(ensemble == "NPT")
        
    def create_deformation_tab(self):
        """Create the deformation settings tab"""
        self.deformation_tab = QWidget()
        self.tab_widget.addTab(self.deformation_tab, "Deformation Settings")
        
        # Create scroll area
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll_widget = QWidget()
        scroll_layout = QVBoxLayout(scroll_widget)
        scroll.setWidget(scroll_widget)
        
        # Main layout for deformation tab
        deformation_layout = QVBoxLayout(self.deformation_tab)
        deformation_layout.addWidget(scroll)
        
        # Deformation method selection
        method_group = QGroupBox("Deformation Method")
        method_layout = QVBoxLayout()
        
        self.deform_method_group = QButtonGroup()
        
        self.fix_deform_radio = QRadioButton("Fix Deform")
        self.wall_movement_radio = QRadioButton("Wall Movement")
        
        # Add tooltips
        self.fix_deform_radio.setToolTip("Use fix deform to apply deformation to the simulation box")
        self.wall_movement_radio.setToolTip("Use moving walls to apply deformation to the system")
        
        self.deform_method_group.addButton(self.fix_deform_radio, 0)
        self.deform_method_group.addButton(self.wall_movement_radio, 1)
        
        self.fix_deform_radio.setChecked(True)
        
        method_layout.addWidget(self.fix_deform_radio)
        method_layout.addWidget(self.wall_movement_radio)
        method_group.setLayout(method_layout)
        scroll_layout.addWidget(method_group)
        
        # Fix deform settings
        self.fix_deform_group = QGroupBox("Fix Deform Settings")
        fix_deform_layout = QFormLayout()
        
        self.deform_rate = QDoubleSpinBox()
        self.deform_rate.setRange(-1000, 1000)
        self.deform_rate.setValue(0.001)
        self.deform_rate.setSingleStep(0.0001)
        self.deform_rate.setDecimals(6)
        self.deform_rate.setToolTip("Rate of deformation for the selected axis")
        
        self.deform_axis = QComboBox()
        self.deform_axis.addItems(["x", "y", "z"])
        self.deform_axis.setToolTip("Axis along which to apply deformation")
        
        self.deform_style = QComboBox()
        self.deform_style.addItems(["final", "erate", "trate", "volume", "pressure"])
        self.deform_style.setToolTip("Style of deformation to apply")
        
        deform_label = QLabel("Deform Settings:")
        deform_label.setStyleSheet("color: blue; text-decoration: underline;")
        deform_label.setCursor(QCursor(Qt.PointingHandCursor))
        deform_label.mousePressEvent = lambda e: self.open_lammps_doc("fix_deform")
        deform_label.setToolTip("Click to open LAMMPS fix_deform documentation")
        
        fix_deform_layout.addRow("Deformation Rate:", self.deform_rate)
        fix_deform_layout.addRow("Deformation Axis:", self.deform_axis)
        fix_deform_layout.addRow("Deformation Style:", self.deform_style)
        self.fix_deform_group.setLayout(fix_deform_layout)
        scroll_layout.addWidget(self.fix_deform_group)
        
        # Wall movement settings
        self.wall_movement_group = QGroupBox("Wall Movement Settings")
        wall_movement_layout = QFormLayout()
        
        self.wall_velocity = QDoubleSpinBox()
        self.wall_velocity.setRange(-1000, 1000)
        self.wall_velocity.setValue(0.01)
        self.wall_velocity.setSingleStep(0.001)
        self.wall_velocity.setDecimals(6)
        self.wall_velocity.setToolTip("Velocity of the moving wall")
        
        self.wall_axis = QComboBox()
        self.wall_axis.addItems(["x", "y", "z"])
        self.wall_axis.setToolTip("Axis along which the wall moves")
        
        self.wall_direction = QComboBox()
        self.wall_direction.addItems(["positive", "negative"])
        self.wall_direction.setToolTip("Direction of wall movement")
        
        wall_label = QLabel("Wall Settings:")
        wall_label.setStyleSheet("color: blue; text-decoration: underline;")
        wall_label.setCursor(QCursor(Qt.PointingHandCursor))
        wall_label.mousePressEvent = lambda e: self.open_lammps_doc("fix_wall")
        wall_label.setToolTip("Click to open LAMMPS fix_wall documentation")
        
        wall_movement_layout.addRow("Wall Velocity:", self.wall_velocity)
        wall_movement_layout.addRow("Wall Axis:", self.wall_axis)
        wall_movement_layout.addRow("Wall Direction:", self.wall_direction)
        self.wall_movement_group.setLayout(wall_movement_layout)
        self.wall_movement_group.setEnabled(False)
        scroll_layout.addWidget(self.wall_movement_group)
        
        # Connect deformation method signals
        self.fix_deform_radio.toggled.connect(lambda: self.toggle_deformation_method(0))
        self.wall_movement_radio.toggled.connect(lambda: self.toggle_deformation_method(1))
        
        # Simulation settings
        sim_group = QGroupBox("Simulation Settings")
        sim_layout = QFormLayout()
        
        self.run_steps = QSpinBox()
        self.run_steps.setRange(1, 100000000)
        self.run_steps.setValue(10000)
        self.run_steps.setSingleStep(1000)
        self.run_steps.setToolTip("Number of simulation steps to run")
        
        self.thermo_output_freq = QSpinBox()
        self.thermo_output_freq.setRange(1, 1000000)
        self.thermo_output_freq.setValue(100)
        self.thermo_output_freq.setSingleStep(10)
        self.thermo_output_freq.setToolTip("Frequency of thermodynamic output")
        
        self.trj_output_freq = QSpinBox()
        self.trj_output_freq.setRange(1, 1000000)
        self.trj_output_freq.setValue(1000)
        self.trj_output_freq.setSingleStep(100)
        self.trj_output_freq.setToolTip("Frequency of trajectory output")
        
        # Add to widget references for focus jumping
        self.widget_references['run_steps'] = self.run_steps
        
        sim_label = QLabel("Simulation Settings:")
        sim_label.setStyleSheet("color: blue; text-decoration: underline;")
        sim_label.setCursor(QCursor(Qt.PointingHandCursor))
        sim_label.mousePressEvent = lambda e: self.open_lammps_doc("run")
        sim_label.setToolTip("Click to open LAMMPS run documentation")
        
        sim_layout.addRow("Run Steps:", self.run_steps)
        sim_layout.addRow("Thermo Output Frequency:", self.thermo_output_freq)
        sim_layout.addRow("Trajectory Output Frequency:", self.trj_output_freq)
        sim_group.setLayout(sim_layout)
        scroll_layout.addWidget(sim_group)
        
        # Add stretch to push everything up
        scroll_layout.addStretch()
        
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
        
        self.model_name = QLineEdit()
        self.model_name.setPlaceholderText("Enter model name")
        self.model_name.setToolTip("Name for the model (used for output filenames)")
        
        # Add to widget references for focus jumping
        self.widget_references['model_name'] = self.model_name
        
        path_layout.addRow("Output Path:", output_path_layout)
        path_layout.addRow("Model Name:", self.model_name)
        path_group.setLayout(path_layout)
        scroll_layout.addWidget(path_group)
        
        # Trajectory output settings
        traj_group = QGroupBox("Trajectory Output Settings")
        traj_layout = QVBoxLayout()
        
        self.enable_trajectory = QCheckBox("Enable Trajectory Output")
        self.enable_trajectory.setChecked(True)
        self.enable_trajectory.setToolTip("Enable trajectory file output")
        
        traj_form_layout = QFormLayout()
        
        self.traj_format = QComboBox()
        self.traj_format.addItems(["lammpstrj", "xyz", "dcd"])
        self.traj_format.setToolTip("Format for trajectory files")
        
        self.trj_output_items = QTextEdit()
        self.trj_output_items.setPlainText("id type x y z fx fy fz")
        self.trj_output_items.setMaximumHeight(100)
        self.trj_output_items.setToolTip("Items to include in trajectory output")
        
        traj_label = QLabel("Trajectory Settings:")
        traj_label.setStyleSheet("color: blue; text-decoration: underline;")
        traj_label.setCursor(QCursor(Qt.PointingHandCursor))
        traj_label.mousePressEvent = lambda e: self.open_lammps_doc("dump")
        traj_label.setToolTip("Click to open LAMMPS dump documentation")
        
        traj_form_layout.addRow("Trajectory Format:", self.traj_format)
        traj_form_layout.addRow("Output Items:", self.trj_output_items)
        
        traj_layout.addWidget(self.enable_trajectory)
        traj_layout.addLayout(traj_form_layout)
        traj_group.setLayout(traj_layout)
        scroll_layout.addWidget(traj_group)
        
        # Thermo output settings
        thermo_group = QGroupBox("Thermo Output Settings")
        thermo_layout = QVBoxLayout()
        
        self.enable_thermo = QCheckBox("Enable Thermo Output")
        self.enable_thermo.setChecked(True)
        self.enable_thermo.setToolTip("Enable thermodynamic output")
        
        thermo_form_layout = QFormLayout()
        
        self.thermo_style = QTextEdit()
        self.thermo_style.setPlainText("step etotal pe ke epair ebond evdwl ecoul elong temp press pxx pyy pzz pxy pxz pyz lx ly lz density")
        self.thermo_style.setMaximumHeight(100)
        self.thermo_style.setToolTip("Style for thermodynamic output")
        
        thermo_label = QLabel("Thermo Settings:")
        thermo_label.setStyleSheet("color: blue; text-decoration: underline;")
        thermo_label.setCursor(QCursor(Qt.PointingHandCursor))
        thermo_label.mousePressEvent = lambda e: self.open_lammps_doc("thermo")
        thermo_label.setToolTip("Click to open LAMMPS thermo documentation")
        
        thermo_form_layout.addRow("Thermo Style:", self.thermo_style)
        
        thermo_layout.addWidget(self.enable_thermo)
        thermo_layout.addLayout(thermo_form_layout)
        thermo_group.setLayout(thermo_layout)
        scroll_layout.addWidget(thermo_group)
        
        # Stress calculations
        stress_group = QGroupBox("Stress Calculations")
        stress_layout = QVBoxLayout()
        
        self.enable_stress = QCheckBox("Enable Stress Calculations")
        self.enable_stress.setChecked(True)
        self.enable_stress.setToolTip("Enable stress tensor calculations")
        
        stress_layout.addWidget(self.enable_stress)
        stress_group.setLayout(stress_layout)
        scroll_layout.addWidget(stress_group)
        
        # Custom computes
        custom_group = QGroupBox("Custom Computes")
        custom_layout = QVBoxLayout()
        
        self.enable_custom_computes = QCheckBox("Enable Custom Computes")
        self.enable_custom_computes.setChecked(False)
        self.enable_custom_computes.setToolTip("Enable custom compute commands")
        
        self.custom_computes = QTextEdit()
        self.custom_computes.setPlaceholderText("Enter custom compute commands here")
        self.custom_computes.setMaximumHeight(100)
        self.custom_computes.setEnabled(False)
        self.custom_computes.setToolTip("Custom compute commands to add to the script")
        
        self.enable_custom_computes.stateChanged.connect(
            lambda state: self.custom_computes.setEnabled(state == Qt.Checked)
        )
        
        custom_layout.addWidget(self.enable_custom_computes)
        custom_layout.addWidget(self.custom_computes)
        custom_group.setLayout(custom_layout)
        scroll_layout.addWidget(custom_group)
        
        # Custom dumps
        custom_dump_group = QGroupBox("Custom Dumps")
        custom_dump_layout = QVBoxLayout()
        
        self.enable_custom_dumps = QCheckBox("Enable Custom Dumps")
        self.enable_custom_dumps.setChecked(False)
        self.enable_custom_dumps.setToolTip("Enable custom dump commands")
        
        self.custom_dumps = QTextEdit()
        self.custom_dumps.setPlaceholderText("Enter custom dump commands here")
        self.custom_dumps.setMaximumHeight(100)
        self.custom_dumps.setEnabled(False)
        self.custom_dumps.setToolTip("Custom dump commands to add to the script")
        
        self.enable_custom_dumps.stateChanged.connect(
            lambda state: self.custom_dumps.setEnabled(state == Qt.Checked)
        )
        
        custom_dump_layout.addWidget(self.enable_custom_dumps)
        custom_dump_layout.addWidget(self.custom_dumps)
        custom_dump_group.setLayout(custom_dump_layout)
        scroll_layout.addWidget(custom_dump_group)
        
        # Add stretch to push everything up
        scroll_layout.addStretch()
        
    def create_cluster_tab(self):
        """Create the cluster settings tab"""
        self.cluster_tab = QWidget()
        self.tab_widget.addTab(self.cluster_tab, "Cluster Settings")
        
        # Create scroll area
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll_widget = QWidget()
        scroll_layout = QVBoxLayout(scroll_widget)
        scroll.setWidget(scroll_widget)
        
        # Main layout for cluster tab
        cluster_layout = QVBoxLayout(self.cluster_tab)
        cluster_layout.addWidget(scroll)
        
        # Execution mode
        exec_group = QGroupBox("Execution Mode")
        exec_layout = QVBoxLayout()
        
        self.exec_mode_group = QButtonGroup()
        
        self.local_radio = QRadioButton("Local Execution")
        self.cluster_radio = QRadioButton("Cluster Execution")
        
        # Add tooltips
        self.local_radio.setToolTip("Run simulation on local machine")
        self.cluster_radio.setToolTip("Generate job file for cluster execution")
        
        self.exec_mode_group.addButton(self.local_radio, 0)
        self.exec_mode_group.addButton(self.cluster_radio, 1)
        
        self.local_radio.setChecked(True)
        
        exec_layout.addWidget(self.local_radio)
        exec_layout.addWidget(self.cluster_radio)
        exec_group.setLayout(exec_layout)
        scroll_layout.addWidget(exec_group)
        
        # Cluster settings
        self.cluster_group = QGroupBox("Cluster Settings")
        cluster_form_layout = QFormLayout()
        
        self.cluster_partition = QComboBox()
        self.cluster_partition.addItems(["singlenode", "multinode"])
        self.cluster_partition.setCurrentText("singlenode")
        self.cluster_partition.setToolTip("SLURM partition for job submission")
        
        self.cluster_nodes = QSpinBox()
        self.cluster_nodes.setRange(1, 100)
        self.cluster_nodes.setValue(1)
        self.cluster_nodes.setToolTip("Number of nodes to request")
        
        self.cluster_ntasks = QSpinBox()
        self.cluster_ntasks.setRange(1, 1000)
        self.cluster_ntasks.setValue(72)
        self.cluster_ntasks.setToolTip("Number of tasks to request")
        
        self.cluster_time = QLineEdit()
        self.cluster_time.setText("24:00:00")
        self.cluster_time.setToolTip("Time limit for the job")
        
        self.cluster_mail = QLineEdit()
        self.cluster_mail.setPlaceholderText("your.email@example.com")
        self.cluster_mail.setToolTip("Email address for job notifications")
        
        # Add to widget references for focus jumping
        self.widget_references['cluster_mail'] = self.cluster_mail
        
        cluster_label = QLabel("Cluster Settings:")
        cluster_label.setStyleSheet("color: blue; text-decoration: underline;")
        cluster_label.setCursor(QCursor(Qt.PointingHandCursor))
        cluster_label.mousePressEvent = lambda e: self.open_slurm_doc()
        cluster_label.setToolTip("Click to open SLURM documentation")
        
        cluster_form_layout.addRow("Partition:", self.cluster_partition)
        cluster_form_layout.addRow("Nodes:", self.cluster_nodes)
        cluster_form_layout.addRow("Tasks:", self.cluster_ntasks)
        cluster_form_layout.addRow("Time Limit:", self.cluster_time)
        cluster_form_layout.addRow("Email:", self.cluster_mail)
        self.cluster_group.setLayout(cluster_form_layout)
        self.cluster_group.setEnabled(False)
        scroll_layout.addWidget(self.cluster_group)
        
        # Connect execution mode signals
        self.local_radio.toggled.connect(lambda: self.toggle_execution_mode(0))
        self.cluster_radio.toggled.connect(lambda: self.toggle_execution_mode(1))
        
        # Add stretch to push everything up
        scroll_layout.addStretch()
        
    def create_multistudy_tab(self):
        """Create the multi-study configuration tab"""
        self.multistudy_tab = QWidget()
        self.tab_widget.addTab(self.multistudy_tab, "Multi-Study Configuration")
        
        # Create scroll area
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll_widget = QWidget()
        scroll_layout = QVBoxLayout(scroll_widget)
        scroll.setWidget(scroll_widget)
        
        # Main layout for multistudy tab
        multistudy_layout = QVBoxLayout(self.multistudy_tab)
        multistudy_layout.addWidget(scroll)
        
        # Multi-system processing
        multi_system_group = QGroupBox("Multi-System Processing")
        multi_system_layout = QVBoxLayout()
        
        self.enable_multi_system = QCheckBox("Enable Multi-System Processing")
        self.enable_multi_system.setChecked(False)
        self.enable_multi_system.setToolTip("Process multiple data files automatically")
        
        system_form_layout = QFormLayout()
        
        self.system_path_edit = QLineEdit()
        self.system_path_edit.setPlaceholderText("Enter directory path containing data files")
        self.system_path_edit.setToolTip("Directory containing multiple data files")
        
        self.system_path_browse = QPushButton("Browse...")
        self.system_path_browse.clicked.connect(self.browse_system_path)
        self.system_path_browse.setToolTip("Browse for directory containing data files")
        
        self.system_pattern = QLineEdit()
        self.system_pattern.setText("*.data")
        self.system_pattern.setToolTip("Pattern to match data files (e.g., *.data)")
        
        system_path_layout = QHBoxLayout()
        system_path_layout.addWidget(self.system_path_edit)
        system_path_layout.addWidget(self.system_path_browse)
        
        # Add to widget references for focus jumping
        self.widget_references['system_path'] = self.system_path_edit
        
        system_form_layout.addRow("System Directory:", system_path_layout)
        system_form_layout.addRow("File Pattern:", self.system_pattern)
        
        multi_system_layout.addWidget(self.enable_multi_system)
        multi_system_layout.addLayout(system_form_layout)
        multi_system_group.setLayout(multi_system_layout)
        scroll_layout.addWidget(multi_system_group)
        
        # Multi-deformation processing
        multi_deform_group = QGroupBox("Multi-Deformation Processing")
        multi_deform_layout = QVBoxLayout()
        
        self.enable_multi_deform = QCheckBox("Enable Multi-Deformation Processing")
        self.enable_multi_deform.setChecked(False)
        self.enable_multi_deform.setToolTip("Process multiple deformation studies")
        
        # Deformation studies table
        studies_layout = QVBoxLayout()
        
        self.studies_table = QTableWidget()
        self.studies_table.setColumnCount(4)
        self.studies_table.setHorizontalHeaderLabels(["Name", "Rate", "Axis", "Style"])
        self.studies_table.horizontalHeader().setStretchLastSection(True)
        self.studies_table.setMaximumHeight(200)
        self.studies_table.setToolTip("Table of deformation studies to process")
        
        # Add sample data
        self.studies_table.setRowCount(2)
        self.studies_table.setItem(0, 0, QTableWidgetItem("study1"))
        self.studies_table.setItem(0, 1, QTableWidgetItem("0.001"))
        self.studies_table.setItem(0, 2, QTableWidgetItem("x"))
        self.studies_table.setItem(0, 3, QTableWidgetItem("final"))
        self.studies_table.setItem(1, 0, QTableWidgetItem("study2"))
        self.studies_table.setItem(1, 1, QTableWidgetItem("0.002"))
        self.studies_table.setItem(1, 2, QTableWidgetItem("y"))
        self.studies_table.setItem(1, 3, QTableWidgetItem("erate"))
        
        studies_buttons_layout = QHBoxLayout()
        
        self.add_study_button = QPushButton("Add Study")
        self.add_study_button.clicked.connect(self.add_deformation_study)
        self.add_study_button.setToolTip("Add a new deformation study")
        
        self.remove_study_button = QPushButton("Remove Study")
        self.remove_study_button.clicked.connect(self.remove_deformation_study)
        self.remove_study_button.setToolTip("Remove selected deformation study")
        
        studies_buttons_layout.addWidget(self.add_study_button)
        studies_buttons_layout.addWidget(self.remove_study_button)
        
        studies_layout.addWidget(self.studies_table)
        studies_layout.addLayout(studies_buttons_layout)
        
        multi_deform_layout.addWidget(self.enable_multi_deform)
        multi_deform_layout.addLayout(studies_layout)
        multi_deform_group.setLayout(multi_deform_layout)
        scroll_layout.addWidget(multi_deform_group)
        
        # Add stretch to push everything up
        scroll_layout.addStretch()
        
    def create_bottom_buttons(self):
        """Create bottom buttons"""
        button_layout = QHBoxLayout()
        
        self.save_config_button = QPushButton("Save Configuration")
        self.save_config_button.clicked.connect(self.save_configuration)
        self.save_config_button.setToolTip("Save current configuration to file")
        
        self.load_config_button = QPushButton("Load Configuration")
        self.load_config_button.clicked.connect(self.load_configuration)
        self.load_config_button.setToolTip("Load configuration from file")
        
        self.generate_button = QPushButton("Generate Scripts")
        self.generate_button.clicked.connect(self.generate_scripts)
        self.generate_button.setToolTip("Generate LAMMPS input scripts and job files")
        
        self.show_files_button = QPushButton("Show Used Files")
        self.show_files_button.clicked.connect(self.show_used_files)
        self.show_files_button.setToolTip("Show files used by this program")
        
        self.cleanup_button = QPushButton("Cleanup Files")
        self.cleanup_button.clicked.connect(self.cleanup_files)
        self.cleanup_button.setToolTip("Remove unnecessary files from the directory")
        
        button_layout.addWidget(self.save_config_button)
        button_layout.addWidget(self.load_config_button)
        button_layout.addWidget(self.generate_button)
        button_layout.addWidget(self.show_files_button)
        button_layout.addWidget(self.cleanup_button)
        
        self.main_layout.addLayout(button_layout)
        
    def toggle_potential_file(self, state):
        """Toggle potential file controls"""
        enabled = state == Qt.Checked
        self.potential_path_edit.setEnabled(enabled)
        self.potential_path_browse.setEnabled(enabled)
        
    def toggle_deformation_method(self, method):
        """Toggle deformation method controls"""
        if method == 0:  # Fix deform
            self.fix_deform_group.setEnabled(True)
            self.wall_movement_group.setEnabled(False)
        else:  # Wall movement
            self.fix_deform_group.setEnabled(False)
            self.wall_movement_group.setEnabled(True)
            
    def toggle_execution_mode(self, mode):
        """Toggle execution mode controls"""
        if mode == 0:  # Local
            self.cluster_group.setEnabled(False)
        else:  # Cluster
            self.cluster_group.setEnabled(True)
            
    def browse_data_file(self):
        """Browse for data file"""
        file_path, _ = QFileDialog.getOpenFileName(self, "Select Data File", "", "Data Files (*.data);;All Files (*)")
        if file_path:
            self.data_path_edit.setText(file_path)
            # Try to read atom style from data file
            self.read_atom_style_from_data_file(file_path)
            
    def read_atom_style_from_data_file(self, file_path):
        """Read atom style from data file"""
        try:
            with open(file_path, 'r') as f:
                for line in f:
                    if line.startswith("Atoms"):
                        # Extract atom style from "Atoms # style" format
                        parts = line.split()
                        if len(parts) >= 3:
                            atom_style = parts[2].strip()
                            # Check if the atom style is in our combo box
                            index = self.atom_style_combo.findText(atom_style)
                            if index >= 0:
                                self.atom_style_combo.setCurrentIndex(index)
                            else:
                                # Add the atom style if it's not in the list
                                self.atom_style_combo.addItem(atom_style)
                                self.atom_style_combo.setCurrentText(atom_style)
                            break
        except Exception as e:
            print(f"Warning: Could not read atom style from data file: {str(e)}")
            
    def browse_potential_file(self):
        """Browse for potential file"""
        file_path, _ = QFileDialog.getOpenFileName(self, "Select Potential File", "", "Potential Files (*.in *.pot);;All Files (*)")
        if file_path:
            self.potential_path_edit.setText(file_path)
            
    def browse_output_path(self):
        """Browse for output path"""
        dir_path = QFileDialog.getExistingDirectory(self, "Select Output Directory")
        if dir_path:
            self.output_path_edit.setText(dir_path)
            
    def browse_system_path(self):
        """Browse for system path"""
        dir_path = QFileDialog.getExistingDirectory(self, "Select System Directory")
        if dir_path:
            self.system_path_edit.setText(dir_path)
            
    def scan_systems(self):
        """Scan for system files in the specified directory"""
        system_path = self.system_path_edit.text()
        pattern = self.system_pattern.text()
        
        if not system_path:
            QMessageBox.warning(self, "Warning", "Please specify a system path.")
            return
            
        search_pattern = os.path.join(system_path, pattern)
        files = glob.glob(search_pattern)
        
        if files:
            QMessageBox.information(self, "System Files Found", f"Found {len(files)} system files:\n" + "\n".join(files[:10]))
        else:
            QMessageBox.warning(self, "No Files Found", f"No files found matching pattern: {search_pattern}")
            
    def add_deformation_study(self):
        """Add a new deformation study to the table"""
        row_count = self.studies_table.rowCount()
        self.studies_table.setRowCount(row_count + 1)
        
        # Set default values
        self.studies_table.setItem(row_count, 0, QTableWidgetItem(f"study{row_count + 1}"))
        self.studies_table.setItem(row_count, 1, QTableWidgetItem("0.001"))
        self.studies_table.setItem(row_count, 2, QTableWidgetItem("x"))
        self.studies_table.setItem(row_count, 3, QTableWidgetItem("final"))
        
    def remove_deformation_study(self):
        """Remove selected deformation study from the table"""
        current_row = self.studies_table.currentRow()
        if current_row >= 0:
            self.studies_table.removeRow(current_row)
        else:
            QMessageBox.warning(self, "Warning", "Please select a study to remove.")
            
    def save_configuration(self):
        """Save current configuration to file"""
        file_path, _ = QFileDialog.getSaveFileName(self, "Save Configuration", "", "JSON Files (*.json);;All Files (*)")
        if file_path:
            try:
                config = self.collect_config()
                with open(file_path, 'w') as f:
                    json.dump(config, f, indent=2)
                # Don't show success popup as requested
            except Exception as e:
                QMessageBox.critical(self, "Error", f"Failed to save configuration: {str(e)}")
                
    def load_configuration(self):
        """Load configuration from file"""
        file_path, _ = QFileDialog.getOpenFileName(self, "Load Configuration", "", "JSON Files (*.json);;All Files (*)")
        if file_path:
            try:
                with open(file_path, 'r') as f:
                    config = json.load(f)
                self.apply_config(config)
                # Don't show success popup as requested
            except Exception as e:
                QMessageBox.critical(self, "Error", f"Failed to load configuration: {str(e)}")
                
    def apply_config(self, config):
        """Apply configuration to GUI"""
        # System configuration
        system_config = config.get("system", {})
        self.data_path_edit.setText(system_config.get("data_file", ""))
        self.use_potential_file.setChecked(system_config.get("use_potential_file", False))
        self.potential_path_edit.setText(system_config.get("potential_file", ""))
        
        atom_style = system_config.get("atom_style", "atomic")
        index = self.atom_style_combo.findText(atom_style)
        if index >= 0:
            self.atom_style_combo.setCurrentIndex(index)
            
        self.boundary_x_combo.setCurrentText(system_config.get("boundary_x", "p"))
        self.boundary_y_combo.setCurrentText(system_config.get("boundary_y", "p"))
        self.boundary_z_combo.setCurrentText(system_config.get("boundary_z", "p"))
        
        self.ensemble_combo.setCurrentText(system_config.get("ensemble", "NVT"))
        self.temp_init.setValue(system_config.get("temp_init", 300.0))
        self.temp_end.setValue(system_config.get("temp_end", 300.0))
        self.pressure.setValue(system_config.get("pressure", 1.0))
        self.initial_velocity_seed.setValue(system_config.get("initial_velocity_seed", 12345))
        
        self.neighbor_distance.setValue(system_config.get("neighbor_distance", 0.3))
        self.neigh_modify_every.setValue(system_config.get("neigh_modify_every", 1))
        self.neigh_modify_delay.setValue(system_config.get("neigh_modify_delay", 10))
        self.neigh_modify_check.setChecked(system_config.get("neigh_modify_check", True))
        
        self.timestep.setValue(system_config.get("timestep", 0.001))
        timestep_units = system_config.get("timestep_units", "fs")
        index = self.timestep_units.findText(timestep_units)
        if index >= 0:
            self.timestep_units.setCurrentIndex(index)
            
        # Coordinate direction
        coord_direction = system_config.get("coord_direction", "xyz")
        index = self.coord_direction.findText(coord_direction)
        if index >= 0:
            self.coord_direction.setCurrentIndex(index)
        
        # Deformation configuration
        deform_config = config.get("deformation", {})
        method = deform_config.get("method", "fix_deform")
        if method == "fix_deform":
            self.fix_deform_radio.setChecked(True)
        else:
            self.wall_movement_radio.setChecked(True)
            
        self.deform_rate.setValue(deform_config.get("deform_rate", 0.001))
        self.deform_axis.setCurrentText(deform_config.get("deform_axis", "x"))
        self.deform_style.setCurrentText(deform_config.get("deform_style", "final"))
        
        self.wall_velocity.setValue(deform_config.get("wall_velocity", 0.01))
        self.wall_axis.setCurrentText(deform_config.get("wall_axis", "x"))
        self.wall_direction.setCurrentText(deform_config.get("wall_direction", "positive"))
        
        self.run_steps.setValue(deform_config.get("run_steps", 10000))
        self.thermo_output_freq.setValue(deform_config.get("thermo_output_freq", 100))
        self.trj_output_freq.setValue(deform_config.get("trj_output_freq", 1000))
        
        # Output configuration
        output_config = config.get("output", {})
        self.output_path_edit.setText(output_config.get("output_path", ""))
        self.model_name.setText(output_config.get("model_name", ""))
        
        self.enable_trajectory.setChecked(output_config.get("enable_trajectory", True))
        self.traj_format.setCurrentText(output_config.get("traj_format", "lammpstrj"))
        self.trj_output_items.setPlainText(output_config.get("trj_output_items", "id type x y z fx fy fz"))
        
        self.enable_thermo.setChecked(output_config.get("enable_thermo", True))
        self.thermo_style.setPlainText(output_config.get("thermo_style", "step etotal pe ke epair ebond evdwl ecoul elong temp press pxx pyy pzz pxy pxz pyz lx ly lz density"))
        
        self.enable_stress.setChecked(output_config.get("enable_stress", True))
        
        self.enable_custom_computes.setChecked(output_config.get("enable_custom_computes", False))
        self.custom_computes.setPlainText(output_config.get("custom_computes", ""))
        
        self.enable_custom_dumps.setChecked(output_config.get("enable_custom_dumps", False))
        self.custom_dumps.setPlainText(output_config.get("custom_dumps", ""))
        
        # Cluster configuration
        cluster_config = config.get("cluster", {})
        exec_mode = cluster_config.get("execution_mode", "local")
        if exec_mode == "local":
            self.local_radio.setChecked(True)
        else:
            self.cluster_radio.setChecked(True)
            
        self.cluster_partition.setCurrentText(cluster_config.get("cluster_partition", "singlenode"))
        self.cluster_nodes.setValue(cluster_config.get("cluster_nodes", 1))
        self.cluster_ntasks.setValue(cluster_config.get("cluster_ntasks", 72))
        self.cluster_time.setText(cluster_config.get("cluster_time", "24:00:00"))
        self.cluster_mail.setText(cluster_config.get("cluster_mail", ""))
        
        # Multi-study configuration
        multistudy_config = config.get("multistudy", {})
        self.enable_multi_system.setChecked(multistudy_config.get("enable_multi_system", False))
        self.system_path_edit.setText(multistudy_config.get("system_path", ""))
        self.system_pattern.setText(multistudy_config.get("system_pattern", "*.data"))
        
        self.enable_multi_deform.setChecked(multistudy_config.get("enable_multi_deform", False))
        
        # Load deformation studies
        deform_studies = multistudy_config.get("deform_studies", [])
        self.studies_table.setRowCount(len(deform_studies))
        for i, study in enumerate(deform_studies):
            self.studies_table.setItem(i, 0, QTableWidgetItem(study.get("name", f"study{i+1}")))
            self.studies_table.setItem(i, 1, QTableWidgetItem(str(study.get("rate", 0.001))))
            self.studies_table.setItem(i, 2, QTableWidgetItem(study.get("axis", "x")))
            self.studies_table.setItem(i, 3, QTableWidgetItem(study.get("style", "final")))
            
    def generate_scripts(self):
        """Generate LAMMPS input scripts and job files"""
        try:
            # Collect all settings from the GUI
            config = self.collect_config()
            
            # Validate configuration
            validation_result = self.validate_config(config)
            if not validation_result["valid"]:
                # Show error message and focus on the problematic field
                QMessageBox.critical(self, "Configuration Error", validation_result["message"])
                if "field" in validation_result:
                    widget = self.widget_references.get(validation_result["field"])
                    if widget:
                        widget.setFocus()
                        # Switch to the appropriate tab
                        if validation_result["field"] in ["data_file", "model_name", "output_path"]:
                            self.tab_widget.setCurrentIndex(0)  # System tab
                        elif validation_result["field"] in ["run_steps"]:
                            self.tab_widget.setCurrentIndex(1)  # Deformation tab
                        elif validation_result["field"] in ["cluster_mail"]:
                            self.tab_widget.setCurrentIndex(3)  # Cluster tab
                        elif validation_result["field"] in ["system_path"]:
                            self.tab_widget.setCurrentIndex(4)  # Multi-study tab
                return
                
            # Create script generator
            generator = LammpsScriptGenerator(config)
            
            # Generate scripts
            result = generator.generate_all_scripts()
            
            if result["success"]:
                # Show generated scripts and commands
                self.show_generated_scripts(result["files"], generator)
                # Don't show success popup as requested
            else:
                QMessageBox.critical(self, "Error", result["message"])
                
        except Exception as e:
            QMessageBox.critical(self, "Error", f"Failed to generate scripts: {str(e)}")
            # Emergency save on error
            self.emergency_save()
            
    def collect_config(self):
        """Collect all settings from the GUI into a configuration dictionary"""
        config = {}
        
        # System configuration
        config["system"] = {
            "data_file": self.data_path_edit.text(),
            "use_potential_file": self.use_potential_file.isChecked(),
            "potential_file": self.potential_path_edit.text(),
            "atom_style": self.atom_style_combo.currentText(),
            "boundary_x": self.boundary_x_combo.currentText(),
            "boundary_y": self.boundary_y_combo.currentText(),
            "boundary_z": self.boundary_z_combo.currentText(),
            "ensemble": self.ensemble_combo.currentText(),
            "temp_init": self.temp_init.value(),
            "temp_end": self.temp_end.value(),
            "pressure": self.pressure.value(),
            "initial_velocity_seed": self.initial_velocity_seed.value(),
            "neighbor_distance": self.neighbor_distance.value(),
            "neigh_modify_every": self.neigh_modify_every.value(),
            "neigh_modify_delay": self.neigh_modify_delay.value(),
            "neigh_modify_check": self.neigh_modify_check.isChecked(),
            "timestep": self.timestep.value(),
            "timestep_units": self.timestep_units.currentText(),
            "coord_direction": self.coord_direction.currentText()
        }
        
        # Deformation configuration
        config["deformation"] = {
            "method": "fix_deform" if self.fix_deform_radio.isChecked() else "wall_movement",
            "deform_rate": self.deform_rate.value(),
            "deform_axis": self.deform_axis.currentText(),
            "deform_style": self.deform_style.currentText(),
            "wall_velocity": self.wall_velocity.value(),
            "wall_axis": self.wall_axis.currentText(),
            "wall_direction": self.wall_direction.currentText(),
            "run_steps": self.run_steps.value(),
            "thermo_output_freq": self.thermo_output_freq.value(),
            "trj_output_freq": self.trj_output_freq.value()
        }
        
        # Output configuration
        config["output"] = {
            "output_path": self.output_path_edit.text(),
            "model_name": self.model_name.text(),
            "enable_trajectory": self.enable_trajectory.isChecked(),
            "traj_format": self.traj_format.currentText(),
            "trj_output_items": self.trj_output_items.toPlainText(),
            "enable_thermo": self.enable_thermo.isChecked(),
            "thermo_style": self.thermo_style.toPlainText(),
            "enable_stress": self.enable_stress.isChecked(),
            "enable_custom_computes": self.enable_custom_computes.isChecked(),
            "custom_computes": self.custom_computes.toPlainText(),
            "enable_custom_dumps": self.enable_custom_dumps.isChecked(),
            "custom_dumps": self.custom_dumps.toPlainText()
        }
        
        # Cluster configuration
        config["cluster"] = {
            "execution_mode": "local" if self.local_radio.isChecked() else "cluster",
            "cluster_partition": self.cluster_partition.currentText(),
            "cluster_nodes": self.cluster_nodes.value(),
            "cluster_ntasks": self.cluster_ntasks.value(),
            "cluster_time": self.cluster_time.text(),
            "cluster_mail": self.cluster_mail.text()
        }
        
        # Multi-study configuration
        config["multistudy"] = {
            "enable_multi_system": self.enable_multi_system.isChecked(),
            "system_path": self.system_path_edit.text(),
            "system_pattern": self.system_pattern.text(),
            "enable_multi_deform": self.enable_multi_deform.isChecked(),
            "deform_studies": []
        }
        
        # Collect deformation studies
        for row in range(self.studies_table.rowCount()):
            name_item = self.studies_table.item(row, 0)
            rate_item = self.studies_table.item(row, 1)
            axis_item = self.studies_table.item(row, 2)
            style_item = self.studies_table.item(row, 3)
            
            if name_item and rate_item and axis_item and style_item:
                try:
                    study = {
                        "name": name_item.text(),
                        "rate": float(rate_item.text()),
                        "axis": axis_item.text(),
                        "style": style_item.text()
                    }
                    config["multistudy"]["deform_studies"].append(study)
                except ValueError:
                    # Skip invalid rows
                    continue
                    
        return config
        
    def validate_config(self, config):
        """Validate the configuration and return field name for focus jumping"""
        # Check if multi-system processing is enabled
        if config.get("multistudy", {}).get("enable_multi_system", False):
            # Check system path
            system_path = config.get("multistudy", {}).get("system_path", "")
            if not system_path:
                return {"valid": False, "message": "Please specify a system path for multi-system processing.", "field": "system_path"}
                
            # Check if system path exists
            if not os.path.exists(system_path):
                return {"valid": False, "message": f"System path does not exist: {system_path}", "field": "system_path"}
                
            # Check if multi-deformation is enabled
            if config.get("multistudy", {}).get("enable_multi_deform", False):
                # Check if deformation studies are defined
                deform_studies = config.get("multistudy", {}).get("deform_studies", [])
                if not deform_studies:
                    return {"valid": False, "message": "Please define at least one deformation study."}
        else:
            # Check single data file
            data_file = config.get("system", {}).get("data_file", "")
            if not data_file:
                return {"valid": False, "message": "Please specify a data file.", "field": "data_file"}
                
            # Check if data file exists
            if not os.path.exists(data_file):
                return {"valid": False, "message": f"Data file does not exist: {data_file}", "field": "data_file"}
                
            # Check if multi-deformation is enabled
            if config.get("multistudy", {}).get("enable_multi_deform", False):
                # Check if deformation studies are defined
                deform_studies = config.get("multistudy", {}).get("deform_studies", [])
                if not deform_studies:
                    return {"valid": False, "message": "Please define at least one deformation study."}
                    
        # Check output path
        output_path = config.get("output", {}).get("output_path", "")
        if output_path and not os.path.exists(os.path.dirname(output_path)):
            return {"valid": False, "message": f"Output path does not exist: {output_path}", "field": "output_path"}
            
        # Check model name
        model_name = config.get("output", {}).get("model_name", "")
        if not model_name:
            return {"valid": False, "message": "Please specify a model name.", "field": "model_name"}
            
        # Check run steps
        run_steps = config.get("deformation", {}).get("run_steps", 0)
        if run_steps <= 0:
            return {"valid": False, "message": "Please specify a valid number of run steps.", "field": "run_steps"}
            
        # Check cluster email if cluster execution is enabled
        if config.get("cluster", {}).get("execution_mode") == "cluster":
            email = config.get("cluster", {}).get("cluster_mail", "")
            if not email or "@" not in email:
                return {"valid": False, "message": "Please specify a valid email address for cluster execution.", "field": "cluster_mail"}
            
        return {"valid": True}
        
    def show_generated_scripts(self, files, generator):
        """Show generated scripts and execution commands"""
        dialog = QDialog(self)
        dialog.setWindowTitle("Generated Scripts")
        dialog.setMinimumSize(600, 400)
        
        layout = QVBoxLayout()
        
        # Files list
        files_label = QLabel("Generated Files:")
        layout.addWidget(files_label)
        
        files_text = QTextEdit()
        files_text.setPlainText("\n".join(files))
        files_text.setReadOnly(True)
        layout.addWidget(files_text)
        
        # Execution commands
        commands_label = QLabel("Execution Commands:")
        layout.addWidget(commands_label)
        
        commands_text = QTextEdit()
        commands = []
        
        for file_path in files:
            if file_path.endswith(".in"):
                commands.append(f"lammps -in {file_path}")
            elif file_path.endswith(".job"):
                commands.append(f"sbatch {file_path}")
                
        commands_text.setPlainText("\n".join(commands))
        commands_text.setReadOnly(True)
        layout.addWidget(commands_text)
        
        # Close button
        close_button = QPushButton("Close")
        close_button.clicked.connect(dialog.accept)
        layout.addWidget(close_button)
        
        dialog.setLayout(layout)
        dialog.exec_()
        
    def show_used_files(self):
        """Show files used by this program"""
        used_files = [
            "lammps_gui.py",
            "script_generator.py", 
            "example.data",
            "example.pot",
            "example_config.json",
            "requirements.txt",
            "run_gui.py"
        ]
        
        dialog = QDialog(self)
        dialog.setWindowTitle("Files Used by This Program")
        dialog.setMinimumSize(500, 300)
        
        layout = QVBoxLayout()
        
        label = QLabel("The following files are used by this program:")
        layout.addWidget(label)
        
        text_edit = QTextEdit()
        text_edit.setPlainText("\n".join(used_files))
        text_edit.setReadOnly(True)
        layout.addWidget(text_edit)
        
        close_button = QPushButton("Close")
        close_button.clicked.connect(dialog.accept)
        layout.addWidget(close_button)
        
        dialog.setLayout(layout)
        dialog.exec_()
        
    def cleanup_files(self):
        """Remove unnecessary files from the directory"""
        # Files that should be kept
        keep_files = {
            "lammps_gui.py",
            "script_generator.py", 
            "example.data",
            "example.pot",
            "example_config.json",
            "requirements.txt",
            "run_gui.py",
            "README.md",
            "PROJECT_SUMMARY.md"
        }
        
        # Get all files in current directory
        current_dir = os.getcwd()
        all_files = set(os.listdir(current_dir))
        
        # Files to remove
        files_to_remove = all_files - keep_files
        
        if not files_to_remove:
            QMessageBox.information(self, "Cleanup", "No unnecessary files found.")
            return
            
        # Confirm cleanup
        reply = QMessageBox.question(self, "Confirm Cleanup", 
                                   f"Found {len(files_to_remove)} unnecessary files.\n"
                                   f"Do you want to remove them?\n\n"
                                   f"Files to remove:\n" + "\n".join(sorted(files_to_remove)),
                                   QMessageBox.Yes | QMessageBox.No)
        
        if reply == QMessageBox.Yes:
            removed_count = 0
            for file_name in files_to_remove:
                file_path = os.path.join(current_dir, file_name)
                try:
                    if os.path.isfile(file_path):
                        os.remove(file_path)
                        removed_count += 1
                    elif os.path.isdir(file_path):
                        os.rmdir(file_path)
                        removed_count += 1
                except Exception as e:
                    print(f"Could not remove {file_name}: {e}")
                    
            QMessageBox.information(self, "Cleanup Complete", f"Removed {removed_count} files.")
        
    def open_lammps_doc(self, command):
        """Open LAMMPS documentation for a specific command"""
        url = f"https://docs.lammps.org/{command}.html"
        QDesktopServices.openUrl(QUrl(url))
        
    def open_slurm_doc(self):
        """Open SLURM documentation"""
        url = "https://slurm.schedmd.com/documentation.html"
        QDesktopServices.openUrl(QUrl(url))
        
    def load_settings(self):
        """Load settings from QSettings"""
        try:
            # Load system settings
            self.data_path_edit.setText(self.settings.value("data_file", ""))
            self.use_potential_file.setChecked(self.settings.value("use_potential_file", False, type=bool))
            self.potential_path_edit.setText(self.settings.value("potential_file", ""))
            
            atom_style = self.settings.value("atom_style", "atomic")
            index = self.atom_style_combo.findText(atom_style)
            if index >= 0:
                self.atom_style_combo.setCurrentIndex(index)
                
            self.boundary_x_combo.setCurrentText(self.settings.value("boundary_x", "p"))
            self.boundary_y_combo.setCurrentText(self.settings.value("boundary_y", "p"))
            self.boundary_z_combo.setCurrentText(self.settings.value("boundary_z", "p"))
            
            self.ensemble_combo.setCurrentText(self.settings.value("ensemble", "NVT"))
            self.temp_init.setValue(float(self.settings.value("temp_init", 300.0)))
            self.temp_end.setValue(float(self.settings.value("temp_end", 300.0)))
            self.pressure.setValue(float(self.settings.value("pressure", 1.0)))
            self.initial_velocity_seed.setValue(int(self.settings.value("initial_velocity_seed", 12345)))
            
            self.neighbor_distance.setValue(float(self.settings.value("neighbor_distance", 0.3)))
            self.neigh_modify_every.setValue(int(self.settings.value("neigh_modify_every", 1)))
            self.neigh_modify_delay.setValue(int(self.settings.value("neigh_modify_delay", 10)))
            self.neigh_modify_check.setChecked(self.settings.value("neigh_modify_check", True, type=bool))
            
            self.timestep.setValue(float(self.settings.value("timestep", 0.001)))
            timestep_units = self.settings.value("timestep_units", "fs")
            index = self.timestep_units.findText(timestep_units)
            if index >= 0:
                self.timestep_units.setCurrentIndex(index)
                
            # Coordinate direction
            coord_direction = self.settings.value("coord_direction", "xyz")
            index = self.coord_direction.findText(coord_direction)
            if index >= 0:
                self.coord_direction.setCurrentIndex(index)
            
            # Load deformation settings
            self.deform_rate.setValue(float(self.settings.value("deform_rate", 0.001)))
            self.deform_axis.setCurrentText(self.settings.value("deform_axis", "x"))
            self.deform_style.setCurrentText(self.settings.value("deform_style", "final"))
            
            self.wall_velocity.setValue(float(self.settings.value("wall_velocity", 0.01)))
            self.wall_axis.setCurrentText(self.settings.value("wall_axis", "x"))
            self.wall_direction.setCurrentText(self.settings.value("wall_direction", "positive"))
            
            self.run_steps.setValue(int(self.settings.value("run_steps", 10000)))
            self.thermo_output_freq.setValue(int(self.settings.value("thermo_output_freq", 100)))
            self.trj_output_freq.setValue(int(self.settings.value("trj_output_freq", 1000)))
            
            # Load output settings
            self.output_path_edit.setText(self.settings.value("output_path", ""))
            self.model_name.setText(self.settings.value("model_name", ""))
            
            self.enable_trajectory.setChecked(self.settings.value("enable_trajectory", True, type=bool))
            self.traj_format.setCurrentText(self.settings.value("traj_format", "lammpstrj"))
            self.trj_output_items.setPlainText(self.settings.value("trj_output_items", "id type x y z fx fy fz"))
            
            self.enable_thermo.setChecked(self.settings.value("enable_thermo", True, type=bool))
            self.thermo_style.setPlainText(self.settings.value("thermo_style", "step etotal pe ke epair ebond evdwl ecoul elong temp press pxx pyy pzz pxy pxz pyz lx ly lz density"))
            
            self.enable_stress.setChecked(self.settings.value("enable_stress", True, type=bool))
            
            # Load cluster settings
            exec_mode = self.settings.value("execution_mode", "local")
            if exec_mode == "local":
                self.local_radio.setChecked(True)
            else:
                self.cluster_radio.setChecked(True)
                
            self.cluster_partition.setCurrentText(self.settings.value("cluster_partition", "singlenode"))
            self.cluster_nodes.setValue(int(self.settings.value("cluster_nodes", 1)))
            self.cluster_ntasks.setValue(int(self.settings.value("cluster_ntasks", 72)))
            self.cluster_time.setText(self.settings.value("cluster_time", "24:00:00"))
            self.cluster_mail.setText(self.settings.value("cluster_mail", ""))
            
            # Load multistudy settings
            self.enable_multi_system.setChecked(self.settings.value("enable_multi_system", False, type=bool))
            self.system_path_edit.setText(self.settings.value("system_path", ""))
            self.system_pattern.setText(self.settings.value("system_pattern", "*.data"))
            
            self.enable_multi_deform.setChecked(self.settings.value("enable_multi_deform", False, type=bool))
            
            # Check for emergency save file
            emergency_file = os.path.join(tempfile.gettempdir(), "lammps_gui_emergency_save.json")
            if os.path.exists(emergency_file):
                reply = QMessageBox.question(self, "Recover Settings", 
                                           "Found emergency save file from previous session.\n"
                                           "Do you want to recover your settings?",
                                           QMessageBox.Yes | QMessageBox.No)
                if reply == QMessageBox.Yes:
                    try:
                        with open(emergency_file, 'r') as f:
                            emergency_config = json.load(f)
                        self.apply_config(emergency_config)
                        os.remove(emergency_file)
                    except Exception as e:
                        QMessageBox.warning(self, "Recovery Failed", f"Could not recover settings: {e}")
                        
        except Exception as e:
            print(f"Error loading settings: {e}")
            
    def save_settings(self):
        """Save settings to QSettings"""
        try:
            # Save system settings
            self.settings.setValue("data_file", self.data_path_edit.text())
            self.settings.setValue("use_potential_file", self.use_potential_file.isChecked())
            self.settings.setValue("potential_file", self.potential_path_edit.text())
            self.settings.setValue("atom_style", self.atom_style_combo.currentText())
            self.settings.setValue("boundary_x", self.boundary_x_combo.currentText())
            self.settings.setValue("boundary_y", self.boundary_y_combo.currentText())
            self.settings.setValue("boundary_z", self.boundary_z_combo.currentText())
            self.settings.setValue("ensemble", self.ensemble_combo.currentText())
            self.settings.setValue("temp_init", self.temp_init.value())
            self.settings.setValue("temp_end", self.temp_end.value())
            self.settings.setValue("pressure", self.pressure.value())
            self.settings.setValue("initial_velocity_seed", self.initial_velocity_seed.value())
            self.settings.setValue("neighbor_distance", self.neighbor_distance.value())
            self.settings.setValue("neigh_modify_every", self.neigh_modify_every.value())
            self.settings.setValue("neigh_modify_delay", self.neigh_modify_delay.value())
            self.settings.setValue("neigh_modify_check", self.neigh_modify_check.isChecked())
            self.settings.setValue("timestep", self.timestep.value())
            self.settings.setValue("timestep_units", self.timestep_units.currentText())
            self.settings.setValue("coord_direction", self.coord_direction.currentText())
            
            # Save deformation settings
            self.settings.setValue("deform_rate", self.deform_rate.value())
            self.settings.setValue("deform_axis", self.deform_axis.currentText())
            self.settings.setValue("deform_style", self.deform_style.currentText())
            self.settings.setValue("wall_velocity", self.wall_velocity.value())
            self.settings.setValue("wall_axis", self.wall_axis.currentText())
            self.settings.setValue("wall_direction", self.wall_direction.currentText())
            self.settings.setValue("run_steps", self.run_steps.value())
            self.settings.setValue("thermo_output_freq", self.thermo_output_freq.value())
            self.settings.setValue("trj_output_freq", self.trj_output_freq.value())
            
            # Save output settings
            self.settings.setValue("output_path", self.output_path_edit.text())
            self.settings.setValue("model_name", self.model_name.text())
            self.settings.setValue("enable_trajectory", self.enable_trajectory.isChecked())
            self.settings.setValue("traj_format", self.traj_format.currentText())
            self.settings.setValue("trj_output_items", self.trj_output_items.toPlainText())
            self.settings.setValue("enable_thermo", self.enable_thermo.isChecked())
            self.settings.setValue("thermo_style", self.thermo_style.toPlainText())
            self.settings.setValue("enable_stress", self.enable_stress.isChecked())
            
            # Save cluster settings
            self.settings.setValue("execution_mode", "local" if self.local_radio.isChecked() else "cluster")
            self.settings.setValue("cluster_partition", self.cluster_partition.currentText())
            self.settings.setValue("cluster_nodes", self.cluster_nodes.value())
            self.settings.setValue("cluster_ntasks", self.cluster_ntasks.value())
            self.settings.setValue("cluster_time", self.cluster_time.text())
            self.settings.setValue("cluster_mail", self.cluster_mail.text())
            
            # Save multistudy settings
            self.settings.setValue("enable_multi_system", self.enable_multi_system.isChecked())
            self.settings.setValue("system_path", self.system_path_edit.text())
            self.settings.setValue("system_pattern", self.system_pattern.text())
            self.settings.setValue("enable_multi_deform", self.enable_multi_deform.isChecked())
            
        except Exception as e:
            print(f"Error saving settings: {e}")
            
    def closeEvent(self, event):
        """Handle application close event"""
        self.save_settings()
        event.accept()


def main():
    app = QApplication(sys.argv)
    window = LammpsScriptGenerator()
    window.show()
    sys.exit(app.exec_())


if __name__ == "__main__":
    main()