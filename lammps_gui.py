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
from pathlib import Path
from PyQt5.QtWidgets import (QApplication, QMainWindow, QTabWidget, QWidget, QVBoxLayout, 
                            QHBoxLayout, QLabel, QLineEdit, QPushButton, QFileDialog, 
                            QComboBox, QCheckBox, QSpinBox, QDoubleSpinBox, QTextEdit,
                            QGroupBox, QFormLayout, QRadioButton, QButtonGroup, QScrollArea,
                            QSplitter, QMessageBox, QProgressBar, QDialog, QGridLayout,
                            QTableWidget, QTableWidgetItem, QHeaderView, QAbstractItemView,
                            QDialogButtonBox)
from PyQt5.QtCore import Qt, QSettings, pyqtSignal, QThread
from PyQt5.QtGui import QFont, QIcon
from script_generator import LammpsScriptGenerator

class LammpsScriptGenerator(QMainWindow):
    """Main application window for LAMMPS script generation"""
    
    def __init__(self):
        super().__init__()
        self.setWindowTitle("LAMMPS Input Script Generator")
        self.setGeometry(100, 100, 1200, 800)
        
        # Initialize settings
        self.settings = QSettings("LammpsScriptGenerator", "LammpsInputGenerator")
        
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
        
        data_path_layout = QHBoxLayout()
        data_path_layout.addWidget(self.data_path_edit)
        data_path_layout.addWidget(self.data_path_browse)
        
        data_layout.addRow("Data File Path:", data_path_layout)
        data_group.setLayout(data_layout)
        scroll_layout.addWidget(data_group)
        
        # Potential file selection
        potential_group = QGroupBox("Potential File Selection")
        potential_layout = QFormLayout()
        
        self.use_potential_file = QCheckBox("Use separate potential file")
        self.use_potential_file.stateChanged.connect(self.toggle_potential_file)
        
        self.potential_path_edit = QLineEdit()
        self.potential_path_edit.setEnabled(False)
        self.potential_path_browse = QPushButton("Browse...")
        self.potential_path_browse.setEnabled(False)
        self.potential_path_browse.clicked.connect(self.browse_potential_file)
        
        potential_path_layout = QHBoxLayout()
        potential_path_layout.addWidget(self.potential_path_edit)
        potential_path_layout.addWidget(self.potential_path_browse)
        
        potential_layout.addRow(self.use_potential_file)
        potential_layout.addRow("Potential File Path:", potential_path_layout)
        potential_group.setLayout(potential_layout)
        scroll_layout.addWidget(potential_group)
        
        # Basic LAMMPS settings
        basic_group = QGroupBox("Basic LAMMPS Settings")
        basic_layout = QFormLayout()
        
        self.atom_style_combo = QComboBox()
        self.atom_style_combo.addItems(["atomic", "bond", "molecular", "full", "charge", "dipole"])
        
        basic_layout.addRow("Atom Style:", self.atom_style_combo)
        basic_group.setLayout(basic_layout)
        scroll_layout.addWidget(basic_group)
        
        # Boundary conditions
        boundary_group = QGroupBox("Boundary Conditions")
        boundary_layout = QFormLayout()
        
        self.boundary_x_combo = QComboBox()
        self.boundary_x_combo.addItems(["p", "f", "s", "m"])
        self.boundary_x_combo.setCurrentText("p")
        
        self.boundary_y_combo = QComboBox()
        self.boundary_y_combo.addItems(["p", "f", "s", "m"])
        self.boundary_y_combo.setCurrentText("p")
        
        self.boundary_z_combo = QComboBox()
        self.boundary_z_combo.addItems(["p", "f", "s", "m"])
        self.boundary_z_combo.setCurrentText("p")
        
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
        
        self.temp_init = QDoubleSpinBox()
        self.temp_init.setRange(0, 10000)
        self.temp_init.setValue(300.0)
        self.temp_init.setSingleStep(10.0)
        
        self.temp_end = QDoubleSpinBox()
        self.temp_end.setRange(0, 10000)
        self.temp_end.setValue(300.0)
        self.temp_end.setSingleStep(10.0)
        
        self.pressure = QDoubleSpinBox()
        self.pressure.setRange(0, 100000)
        self.pressure.setValue(1.0)
        self.pressure.setSingleStep(0.1)
        self.pressure.setEnabled(False)  # Only enabled for NPT
        
        self.initial_velocity_seed = QSpinBox()
        self.initial_velocity_seed.setRange(1, 1000000)
        self.initial_velocity_seed.setValue(12345)
        
        ensemble_layout.addRow("Ensemble:", self.ensemble_combo)
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
        
        self.neigh_modify_every = QSpinBox()
        self.neigh_modify_every.setRange(1, 1000)
        self.neigh_modify_every.setValue(1)
        
        self.neigh_modify_delay = QSpinBox()
        self.neigh_modify_delay.setRange(0, 1000)
        self.neigh_modify_delay.setValue(10)
        
        self.neigh_modify_check = QCheckBox("Enable neighbor checking")
        self.neigh_modify_check.setChecked(True)
        
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
        
        timestep_layout.addRow("Timestep:", self.timestep)
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
        
        self.deform_axis = QComboBox()
        self.deform_axis.addItems(["x", "y", "z"])
        
        self.deform_style = QComboBox()
        self.deform_style.addItems(["final", "erate", "trate", "volume", "pressure"])
        
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
        
        self.wall_axis = QComboBox()
        self.wall_axis.addItems(["x", "y", "z"])
        
        self.wall_direction = QComboBox()
        self.wall_direction.addItems(["positive", "negative"])
        
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
        
        self.thermo_output_freq = QSpinBox()
        self.thermo_output_freq.setRange(1, 1000000)
        self.thermo_output_freq.setValue(100)
        self.thermo_output_freq.setSingleStep(10)
        
        self.trj_output_freq = QSpinBox()
        self.trj_output_freq.setRange(1, 1000000)
        self.trj_output_freq.setValue(1000)
        self.trj_output_freq.setSingleStep(100)
        
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
        
        output_path_layout = QHBoxLayout()
        output_path_layout.addWidget(self.output_path_edit)
        output_path_layout.addWidget(self.output_path_browse)
        
        self.model_name = QLineEdit()
        self.model_name.setPlaceholderText("Enter model name")
        
        path_layout.addRow("Output Path:", output_path_layout)
        path_layout.addRow("Model Name:", self.model_name)
        path_group.setLayout(path_layout)
        scroll_layout.addWidget(path_group)
        
        # Trajectory output settings
        traj_group = QGroupBox("Trajectory Output Settings")
        traj_layout = QVBoxLayout()
        
        self.enable_trajectory = QCheckBox("Enable Trajectory Output")
        self.enable_trajectory.setChecked(True)
        
        traj_form_layout = QFormLayout()
        
        self.traj_format = QComboBox()
        self.traj_format.addItems(["lammpstrj", "xyz", "dcd"])
        
        self.trj_output_items = QTextEdit()
        self.trj_output_items.setPlainText("id type x y z fx fy fz")
        self.trj_output_items.setMaximumHeight(100)
        
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
        
        thermo_form_layout = QFormLayout()
        
        self.thermo_style = QTextEdit()
        self.thermo_style.setPlainText("step etotal pe ke epair ebond evdwl ecoul elong temp press pxx pyy pzz pxy pxz pyz lx ly lz density")
        self.thermo_style.setMaximumHeight(100)
        
        thermo_form_layout.addRow("Thermo Style:", self.thermo_style)
        
        thermo_layout.addWidget(self.enable_thermo)
        thermo_layout.addLayout(thermo_form_layout)
        thermo_group.setLayout(thermo_layout)
        scroll_layout.addWidget(thermo_group)
        
        # Stress calculation settings
        stress_group = QGroupBox("Stress Calculation Settings")
        stress_layout = QVBoxLayout()
        
        self.enable_stress = QCheckBox("Enable Stress Calculation")
        self.enable_stress.setChecked(True)
        
        stress_form_layout = QFormLayout()
        
        self.stress_components = QComboBox()
        self.stress_components.addItems(["all", "xx yy zz xy xz yz", "xx yy zz"])
        
        stress_form_layout.addRow("Stress Components:", self.stress_components)
        
        stress_layout.addWidget(self.enable_stress)
        stress_layout.addLayout(stress_form_layout)
        stress_group.setLayout(stress_layout)
        scroll_layout.addWidget(stress_group)
        
        # Additional output settings
        additional_group = QGroupBox("Additional Output Settings")
        additional_layout = QVBoxLayout()
        
        self.enable_custom_dumps = QCheckBox("Enable Custom Dumps")
        
        self.custom_dumps = QTextEdit()
        self.custom_dumps.setPlaceholderText("Enter custom dump commands here...")
        self.custom_dumps.setMaximumHeight(100)
        self.custom_dumps.setEnabled(False)
        
        self.enable_custom_computes = QCheckBox("Enable Custom Computes")
        
        self.custom_computes = QTextEdit()
        self.custom_computes.setPlaceholderText("Enter custom compute commands here...")
        self.custom_computes.setMaximumHeight(100)
        self.custom_computes.setEnabled(False)
        
        additional_layout.addWidget(self.enable_custom_dumps)
        additional_layout.addWidget(self.custom_dumps)
        additional_layout.addWidget(self.enable_custom_computes)
        additional_layout.addWidget(self.custom_computes)
        
        # Connect signals
        self.enable_custom_dumps.stateChanged.connect(self.toggle_custom_dumps)
        self.enable_custom_computes.stateChanged.connect(self.toggle_custom_computes)
        
        additional_group.setLayout(additional_layout)
        scroll_layout.addWidget(additional_group)
        
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
        
        # Execution mode selection
        exec_group = QGroupBox("Execution Mode")
        exec_layout = QVBoxLayout()
        
        self.exec_mode_group = QButtonGroup()
        
        self.local_exec_radio = QRadioButton("Local Execution")
        self.cluster_exec_radio = QRadioButton("Cluster Execution")
        
        self.exec_mode_group.addButton(self.local_exec_radio, 0)
        self.exec_mode_group.addButton(self.cluster_exec_radio, 1)
        
        self.local_exec_radio.setChecked(True)
        
        exec_layout.addWidget(self.local_exec_radio)
        exec_layout.addWidget(self.cluster_exec_radio)
        exec_group.setLayout(exec_layout)
        scroll_layout.addWidget(exec_group)
        
        # Local execution settings
        self.local_exec_group = QGroupBox("Local Execution Settings")
        local_exec_layout = QFormLayout()
        
        self.lmp_command = QLineEdit()
        self.lmp_command.setPlaceholderText("lmp")
        
        self.lmp_threads = QSpinBox()
        self.lmp_threads.setRange(1, 256)
        self.lmp_threads.setValue(4)
        
        local_exec_layout.addRow("LAMMPS Command:", self.lmp_command)
        local_exec_layout.addRow("Number of Threads:", self.lmp_threads)
        self.local_exec_group.setLayout(local_exec_layout)
        scroll_layout.addWidget(self.local_exec_group)
        
        # Cluster execution settings
        self.cluster_exec_group = QGroupBox("Cluster Execution Settings")
        cluster_exec_layout = QFormLayout()
        
        self.cluster_partition = QLineEdit()
        self.cluster_partition.setPlaceholderText("singlenode")
        
        self.cluster_nodes = QSpinBox()
        self.cluster_nodes.setRange(1, 100)
        self.cluster_nodes.setValue(1)
        
        self.cluster_ntasks = QSpinBox()
        self.cluster_ntasks.setRange(1, 1000)
        self.cluster_ntasks.setValue(72)
        
        self.cluster_cpus_per_task = QSpinBox()
        self.cluster_cpus_per_task.setRange(1, 64)
        self.cluster_cpus_per_task.setValue(1)
        
        self.cluster_time = QLineEdit()
        self.cluster_time.setPlaceholderText("02:00:00")
        
        self.cluster_mail = QLineEdit()
        self.cluster_mail.setPlaceholderText("your.email@example.com")
        
        self.cluster_modules = QTextEdit()
        self.cluster_modules.setPlaceholderText("module load openmpi/4.1.3-nvhpc22.3 nvhpc/22.3")
        self.cluster_modules.setMaximumHeight(60)
        
        cluster_exec_layout.addRow("Partition:", self.cluster_partition)
        cluster_exec_layout.addRow("Nodes:", self.cluster_nodes)
        cluster_exec_layout.addRow("Tasks per Node:", self.cluster_ntasks)
        cluster_exec_layout.addRow("CPUs per Task:", self.cluster_cpus_per_task)
        cluster_exec_layout.addRow("Time Limit:", self.cluster_time)
        cluster_exec_layout.addRow("Email:", self.cluster_mail)
        cluster_exec_layout.addRow("Modules:", self.cluster_modules)
        self.cluster_exec_group.setLayout(cluster_exec_layout)
        self.cluster_exec_group.setEnabled(False)
        scroll_layout.addWidget(self.cluster_exec_group)
        
        # Connect execution mode signals
        self.local_exec_radio.toggled.connect(lambda: self.toggle_execution_mode(0))
        self.cluster_exec_radio.toggled.connect(lambda: self.toggle_execution_mode(1))
        
        # Job submission settings
        job_group = QGroupBox("Job Submission Settings")
        job_layout = QFormLayout()
        
        self.auto_submit = QCheckBox("Automatically submit job")
        
        self.show_command = QCheckBox("Show command before execution")
        self.show_command.setChecked(True)
        
        self.save_scripts_only = QCheckBox("Save scripts only (don't execute)")
        
        job_layout.addRow(self.auto_submit)
        job_layout.addRow(self.show_command)
        job_layout.addRow(self.save_scripts_only)
        job_group.setLayout(job_layout)
        scroll_layout.addWidget(job_group)
        
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
        
        # Multi-system settings
        multi_system_group = QGroupBox("Multi-System Settings")
        multi_system_layout = QVBoxLayout()
        
        self.enable_multi_system = QCheckBox("Enable Multi-System Processing")
        
        multi_system_form_layout = QFormLayout()
        
        self.system_path_edit = QLineEdit()
        self.system_path_browse = QPushButton("Browse...")
        self.system_path_browse.clicked.connect(self.browse_system_path)
        
        system_path_layout = QHBoxLayout()
        system_path_layout.addWidget(self.system_path_edit)
        system_path_layout.addWidget(self.system_path_browse)
        
        self.system_pattern = QLineEdit()
        self.system_pattern.setPlaceholderText("*.data")
        
        self.system_list = QTextEdit()
        self.system_list.setPlaceholderText("List of .data files will appear here...")
        self.system_list.setMaximumHeight(150)
        self.system_list.setReadOnly(True)
        
        self.scan_systems_btn = QPushButton("Scan for Systems")
        self.scan_systems_btn.clicked.connect(self.scan_systems)
        
        multi_system_form_layout.addRow("System Path:", system_path_layout)
        multi_system_form_layout.addRow("File Pattern:", self.system_pattern)
        multi_system_form_layout.addRow(self.scan_systems_btn)
        multi_system_form_layout.addRow("System List:", self.system_list)
        
        multi_system_layout.addWidget(self.enable_multi_system)
        multi_system_layout.addLayout(multi_system_form_layout)
        multi_system_group.setLayout(multi_system_layout)
        scroll_layout.addWidget(multi_system_group)
        
        # Multi-deformation settings
        multi_deform_group = QGroupBox("Multi-Deformation Settings")
        multi_deform_layout = QVBoxLayout()
        
        self.enable_multi_deform = QCheckBox("Enable Multi-Deformation Studies")
        
        # Deformation studies table
        self.deform_table = QTableWidget()
        self.deform_table.setColumnCount(4)
        self.deform_table.setHorizontalHeaderLabels(["Name", "Rate", "Axis", "Style"])
        self.deform_table.horizontalHeader().setStretchLastSection(True)
        self.deform_table.setMaximumHeight(200)
        self.deform_table.setEnabled(False)
        
        # Deformation study buttons
        deform_btn_layout = QHBoxLayout()
        
        self.add_deform_btn = QPushButton("Add Study")
        self.add_deform_btn.clicked.connect(self.add_deformation_study)
        self.add_deform_btn.setEnabled(False)
        
        self.remove_deform_btn = QPushButton("Remove Study")
        self.remove_deform_btn.clicked.connect(self.remove_deformation_study)
        self.remove_deform_btn.setEnabled(False)
        
        deform_btn_layout.addWidget(self.add_deform_btn)
        deform_btn_layout.addWidget(self.remove_deform_btn)
        
        multi_deform_layout.addWidget(self.enable_multi_deform)
        multi_deform_layout.addWidget(self.deform_table)
        multi_deform_layout.addLayout(deform_btn_layout)
        multi_deform_group.setLayout(multi_deform_layout)
        scroll_layout.addWidget(multi_deform_group)
        
        # Parallel execution settings
        parallel_group = QGroupBox("Parallel Execution Settings")
        parallel_layout = QFormLayout()
        
        self.max_parallel_jobs = QSpinBox()
        self.max_parallel_jobs.setRange(1, 100)
        self.max_parallel_jobs.setValue(4)
        
        self.use_job_array = QCheckBox("Use Job Array (Cluster)")
        
        parallel_layout.addRow("Max Parallel Jobs:", self.max_parallel_jobs)
        parallel_layout.addRow(self.use_job_array)
        parallel_group.setLayout(parallel_layout)
        scroll_layout.addWidget(parallel_group)
        
        # Connect signals
        self.enable_multi_system.stateChanged.connect(self.toggle_multi_system)
        self.enable_multi_deform.stateChanged.connect(self.toggle_multi_deform)
        
        # Add stretch to push everything up
        scroll_layout.addStretch()
        
    def create_bottom_buttons(self):
        """Create the bottom buttons"""
        button_layout = QHBoxLayout()
        
        self.generate_btn = QPushButton("Generate Scripts")
        self.generate_btn.clicked.connect(self.generate_scripts)
        
        self.save_config_btn = QPushButton("Save Configuration")
        self.save_config_btn.clicked.connect(self.save_configuration)
        
        self.load_config_btn = QPushButton("Load Configuration")
        self.load_config_btn.clicked.connect(self.load_configuration)
        
        self.exit_btn = QPushButton("Exit")
        self.exit_btn.clicked.connect(self.close)
        
        button_layout.addWidget(self.generate_btn)
        button_layout.addWidget(self.save_config_btn)
        button_layout.addWidget(self.load_config_btn)
        button_layout.addWidget(self.exit_btn)
        
        self.main_layout.addLayout(button_layout)
        
    def toggle_potential_file(self, state):
        """Toggle potential file input based on checkbox"""
        self.potential_path_edit.setEnabled(state == Qt.Checked)
        self.potential_path_browse.setEnabled(state == Qt.Checked)
        
    def toggle_deformation_method(self, method):
        """Toggle deformation method settings"""
        if method == 0:  # Fix deform
            self.fix_deform_group.setEnabled(True)
            self.wall_movement_group.setEnabled(False)
        else:  # Wall movement
            self.fix_deform_group.setEnabled(False)
            self.wall_movement_group.setEnabled(True)
            
    def toggle_execution_mode(self, mode):
        """Toggle execution mode settings"""
        if mode == 0:  # Local
            self.local_exec_group.setEnabled(True)
            self.cluster_exec_group.setEnabled(False)
        else:  # Cluster
            self.local_exec_group.setEnabled(False)
            self.cluster_exec_group.setEnabled(True)
            
    def toggle_custom_dumps(self, state):
        """Toggle custom dumps input based on checkbox"""
        self.custom_dumps.setEnabled(state == Qt.Checked)
        
    def toggle_custom_computes(self, state):
        """Toggle custom computes input based on checkbox"""
        self.custom_computes.setEnabled(state == Qt.Checked)
        
    def toggle_multi_system(self, state):
        """Toggle multi-system settings"""
        enabled = state == Qt.Checked
        self.system_path_edit.setEnabled(enabled)
        self.system_path_browse.setEnabled(enabled)
        self.system_pattern.setEnabled(enabled)
        self.scan_systems_btn.setEnabled(enabled)
        
    def toggle_multi_deform(self, state):
        """Toggle multi-deformation settings"""
        enabled = state == Qt.Checked
        self.deform_table.setEnabled(enabled)
        self.add_deform_btn.setEnabled(enabled)
        self.remove_deform_btn.setEnabled(enabled)
        
    def browse_data_file(self):
        """Browse for data file"""
        file_path, _ = QFileDialog.getOpenFileName(self, "Select Data File", "", "Data Files (*.data);;All Files (*)")
        if file_path:
            self.data_path_edit.setText(file_path)
            
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
        system_files = glob.glob(search_pattern)
        
        if system_files:
            system_list_text = "\n".join(system_files)
            self.system_list.setText(system_list_text)
        else:
            self.system_list.setText("No files found matching the pattern.")
            
    def add_deformation_study(self):
        """Add a new deformation study to the table"""
        row_count = self.deform_table.rowCount()
        self.deform_table.insertRow(row_count)
        
        # Add default values
        self.deform_table.setItem(row_count, 0, QTableWidgetItem(f"Study_{row_count+1}"))
        self.deform_table.setItem(row_count, 1, QTableWidgetItem("0.001"))
        self.deform_table.setItem(row_count, 2, QTableWidgetItem("x"))
        self.deform_table.setItem(row_count, 3, QTableWidgetItem("final"))
        
    def remove_deformation_study(self):
        """Remove selected deformation study from the table"""
        current_row = self.deform_table.currentRow()
        if current_row >= 0:
            self.deform_table.removeRow(current_row)
            
    def generate_scripts(self):
        """Generate LAMMPS input scripts and job files"""
        # Collect all settings from the GUI
        config = self.collect_config()
        
        # Validate configuration
        validation_result = self.validate_config(config)
        if not validation_result["valid"]:
            QMessageBox.warning(self, "Configuration Error", validation_result["message"])
            return
            
        # Create script generator
        generator = LammpsScriptGenerator(config)
        
        # Generate scripts
        result = generator.generate_all_scripts()
        
        if result["success"]:
            # Show generated scripts and commands
            self.show_generated_scripts(result["files"], generator)
            QMessageBox.information(self, "Success", result["message"])
        else:
            QMessageBox.critical(self, "Error", result["message"])
            
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
            "timestep": self.timestep.value()
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
            "stress_components": self.stress_components.currentText(),
            "enable_custom_dumps": self.enable_custom_dumps.isChecked(),
            "custom_dumps": self.custom_dumps.toPlainText(),
            "enable_custom_computes": self.enable_custom_computes.isChecked(),
            "custom_computes": self.custom_computes.toPlainText()
        }
        
        # Cluster configuration
        config["cluster"] = {
            "execution_mode": "local" if self.local_exec_radio.isChecked() else "cluster",
            "lmp_command": self.lmp_command.text(),
            "lmp_threads": self.lmp_threads.value(),
            "cluster_partition": self.cluster_partition.text(),
            "cluster_nodes": self.cluster_nodes.value(),
            "cluster_ntasks": self.cluster_ntasks.value(),
            "cluster_cpus_per_task": self.cluster_cpus_per_task.value(),
            "cluster_time": self.cluster_time.text(),
            "cluster_mail": self.cluster_mail.text(),
            "cluster_modules": self.cluster_modules.toPlainText(),
            "auto_submit": self.auto_submit.isChecked(),
            "show_command": self.show_command.isChecked(),
            "save_scripts_only": self.save_scripts_only.isChecked()
        }
        
        # Multi-study configuration
        config["multistudy"] = {
            "enable_multi_system": self.enable_multi_system.isChecked(),
            "system_path": self.system_path_edit.text(),
            "system_pattern": self.system_pattern.text(),
            "enable_multi_deform": self.enable_multi_deform.isChecked(),
            "max_parallel_jobs": self.max_parallel_jobs.value(),
            "use_job_array": self.use_job_array.isChecked()
        }
        
        # Save deformation studies
        if self.enable_multi_deform.isChecked():
            deform_studies = []
            for row in range(self.deform_table.rowCount()):
                study = {
                    "name": self.deform_table.item(row, 0).text(),
                    "rate": self.deform_table.item(row, 1).text(),
                    "axis": self.deform_table.item(row, 2).text(),
                    "style": self.deform_table.item(row, 3).text()
                }
                deform_studies.append(study)
            config["multistudy"]["deform_studies"] = deform_studies
            
        return config
        
    def validate_config(self, config):
        """Validate the configuration"""
        # Check if multi-system processing is enabled
        if config.get("multistudy", {}).get("enable_multi_system", False):
            # Check system path
            system_path = config.get("multistudy", {}).get("system_path", "")
            if not system_path:
                return {"valid": False, "message": "Please specify a system path for multi-system processing."}
                
            # Check if system path exists
            if not os.path.exists(system_path):
                return {"valid": False, "message": f"System path does not exist: {system_path}"}
                
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
                return {"valid": False, "message": "Please specify a data file."}
                
            # Check if data file exists
            if not os.path.exists(data_file):
                return {"valid": False, "message": f"Data file does not exist: {data_file}"}
                
            # Check if multi-deformation is enabled
            if config.get("multistudy", {}).get("enable_multi_deform", False):
                # Check if deformation studies are defined
                deform_studies = config.get("multistudy", {}).get("deform_studies", [])
                if not deform_studies:
                    return {"valid": False, "message": "Please define at least one deformation study."}
                    
        # Check output path
        output_path = config.get("output", {}).get("output_path", "")
        if output_path and not os.path.exists(os.path.dirname(output_path)):
            return {"valid": False, "message": f"Output path does not exist: {output_path}"}
            
        # Check model name
        model_name = config.get("output", {}).get("model_name", "")
        if not model_name:
            return {"valid": False, "message": "Please specify a model name."}
            
        # Check cluster email if cluster execution is enabled
        if config.get("cluster", {}).get("execution_mode") == "cluster":
            email = config.get("cluster", {}).get("cluster_mail", "")
            if not email or "@" not in email:
                return {"valid": False, "message": "Please specify a valid email address for cluster execution."}
                
        return {"valid": True, "message": "Configuration is valid."}
        
    def show_generated_scripts(self, files, generator):
        """Show the generated scripts and commands in a dialog"""
        dialog = QDialog(self)
        dialog.setWindowTitle("Generated Scripts")
        dialog.setMinimumSize(800, 600)
        
        layout = QVBoxLayout(dialog)
        
        # Create tab widget for different files
        tab_widget = QTabWidget()
        layout.addWidget(tab_widget)
        
        # Add tabs for each generated file
        for file_path in files:
            # Create tab for the file
            file_tab = QWidget()
            file_layout = QVBoxLayout(file_tab)
            
            # Add file path label
            path_label = QLabel(f"File: {file_path}")
            path_label.setStyleSheet("font-weight: bold;")
            file_layout.addWidget(path_label)
            
            # Add text edit for file content
            text_edit = QTextEdit()
            text_edit.setReadOnly(True)
            
            try:
                with open(file_path, 'r') as f:
                    content = f.read()
                text_edit.setText(content)
            except Exception as e:
                text_edit.setText(f"Error reading file: {str(e)}")
                
            file_layout.addWidget(text_edit)
            
            # Add execution command if it's a script file
            if file_path.endswith('.in'):
                command = generator.get_execution_command(file_path)
                command_label = QLabel(f"Execution command: {command}")
                command_label.setStyleSheet("font-weight: bold; color: blue;")
                file_layout.addWidget(command_label)
                
                # Add copy button
                copy_btn = QPushButton("Copy Command")
                copy_btn.clicked.connect(lambda checked, cmd=command: self.copy_to_clipboard(cmd))
                file_layout.addWidget(copy_btn)
            
            # Add the tab
            tab_name = os.path.basename(file_path)
            tab_widget.addTab(file_tab, tab_name)
        
        # Add close button
        button_box = QDialogButtonBox(QDialogButtonBox.Close)
        button_box.rejected.connect(dialog.reject)
        layout.addWidget(button_box)
        
        # Show dialog
        dialog.exec_()
        
    def copy_to_clipboard(self, text):
        """Copy text to clipboard"""
        clipboard = QApplication.clipboard()
        clipboard.setText(text)
        QMessageBox.information(self, "Copied", "Command copied to clipboard.")
        
    def save_configuration(self):
        """Save current configuration to file"""
        file_path, _ = QFileDialog.getSaveFileName(self, "Save Configuration", "", "JSON Files (*.json);;All Files (*)")
        if file_path:
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
                "timestep": self.timestep.value()
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
                "stress_components": self.stress_components.currentText(),
                "enable_custom_dumps": self.enable_custom_dumps.isChecked(),
                "custom_dumps": self.custom_dumps.toPlainText(),
                "enable_custom_computes": self.enable_custom_computes.isChecked(),
                "custom_computes": self.custom_computes.toPlainText()
            }
            
            # Cluster configuration
            config["cluster"] = {
                "execution_mode": "local" if self.local_exec_radio.isChecked() else "cluster",
                "lmp_command": self.lmp_command.text(),
                "lmp_threads": self.lmp_threads.value(),
                "cluster_partition": self.cluster_partition.text(),
                "cluster_nodes": self.cluster_nodes.value(),
                "cluster_ntasks": self.cluster_ntasks.value(),
                "cluster_cpus_per_task": self.cluster_cpus_per_task.value(),
                "cluster_time": self.cluster_time.text(),
                "cluster_mail": self.cluster_mail.text(),
                "cluster_modules": self.cluster_modules.toPlainText(),
                "auto_submit": self.auto_submit.isChecked(),
                "show_command": self.show_command.isChecked(),
                "save_scripts_only": self.save_scripts_only.isChecked()
            }
            
            # Multi-study configuration
            config["multistudy"] = {
                "enable_multi_system": self.enable_multi_system.isChecked(),
                "system_path": self.system_path_edit.text(),
                "system_pattern": self.system_pattern.text(),
                "enable_multi_deform": self.enable_multi_deform.isChecked(),
                "max_parallel_jobs": self.max_parallel_jobs.value(),
                "use_job_array": self.use_job_array.isChecked()
            }
            
            # Save deformation studies
            if self.enable_multi_deform.isChecked():
                deform_studies = []
                for row in range(self.deform_table.rowCount()):
                    study = {
                        "name": self.deform_table.item(row, 0).text(),
                        "rate": self.deform_table.item(row, 1).text(),
                        "axis": self.deform_table.item(row, 2).text(),
                        "style": self.deform_table.item(row, 3).text()
                    }
                    deform_studies.append(study)
                config["multistudy"]["deform_studies"] = deform_studies
            
            try:
                with open(file_path, 'w') as f:
                    json.dump(config, f, indent=4)
                QMessageBox.information(self, "Success", "Configuration saved successfully.")
            except Exception as e:
                QMessageBox.critical(self, "Error", f"Failed to save configuration: {str(e)}")
                
    def load_configuration(self):
        """Load configuration from file"""
        file_path, _ = QFileDialog.getOpenFileName(self, "Load Configuration", "", "JSON Files (*.json);;All Files (*)")
        if file_path:
            try:
                with open(file_path, 'r') as f:
                    config = json.load(f)
                
                # Load system configuration
                if "system" in config:
                    sys_config = config["system"]
                    self.data_path_edit.setText(sys_config.get("data_file", ""))
                    self.use_potential_file.setChecked(sys_config.get("use_potential_file", False))
                    self.potential_path_edit.setText(sys_config.get("potential_file", ""))
                    self.atom_style_combo.setCurrentText(sys_config.get("atom_style", "atomic"))
                    self.boundary_x_combo.setCurrentText(sys_config.get("boundary_x", "p"))
                    self.boundary_y_combo.setCurrentText(sys_config.get("boundary_y", "p"))
                    self.boundary_z_combo.setCurrentText(sys_config.get("boundary_z", "p"))
                    self.ensemble_combo.setCurrentText(sys_config.get("ensemble", "NVT"))
                    self.temp_init.setValue(sys_config.get("temp_init", 300.0))
                    self.temp_end.setValue(sys_config.get("temp_end", 300.0))
                    self.pressure.setValue(sys_config.get("pressure", 1.0))
                    self.initial_velocity_seed.setValue(sys_config.get("initial_velocity_seed", 12345))
                    self.neighbor_distance.setValue(sys_config.get("neighbor_distance", 0.3))
                    self.neigh_modify_every.setValue(sys_config.get("neigh_modify_every", 1))
                    self.neigh_modify_delay.setValue(sys_config.get("neigh_modify_delay", 10))
                    self.neigh_modify_check.setChecked(sys_config.get("neigh_modify_check", True))
                    self.timestep.setValue(sys_config.get("timestep", 0.001))
                
                # Load deformation configuration
                if "deformation" in config:
                    deform_config = config["deformation"]
                    if deform_config.get("method") == "fix_deform":
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
                
                # Load output configuration
                if "output" in config:
                    output_config = config["output"]
                    self.output_path_edit.setText(output_config.get("output_path", ""))
                    self.model_name.setText(output_config.get("model_name", ""))
                    self.enable_trajectory.setChecked(output_config.get("enable_trajectory", True))
                    self.traj_format.setCurrentText(output_config.get("traj_format", "lammpstrj"))
                    self.trj_output_items.setText(output_config.get("trj_output_items", "id type x y z fx fy fz"))
                    self.enable_thermo.setChecked(output_config.get("enable_thermo", True))
                    self.thermo_style.setText(output_config.get("thermo_style", "step etotal pe ke epair ebond evdwl ecoul elong temp press pxx pyy pzz pxy pxz pyz lx ly lz density"))
                    self.enable_stress.setChecked(output_config.get("enable_stress", True))
                    self.stress_components.setCurrentText(output_config.get("stress_components", "all"))
                    self.enable_custom_dumps.setChecked(output_config.get("enable_custom_dumps", False))
                    self.custom_dumps.setText(output_config.get("custom_dumps", ""))
                    self.enable_custom_computes.setChecked(output_config.get("enable_custom_computes", False))
                    self.custom_computes.setText(output_config.get("custom_computes", ""))
                
                # Load cluster configuration
                if "cluster" in config:
                    cluster_config = config["cluster"]
                    if cluster_config.get("execution_mode") == "local":
                        self.local_exec_radio.setChecked(True)
                    else:
                        self.cluster_exec_radio.setChecked(True)
                    self.lmp_command.setText(cluster_config.get("lmp_command", ""))
                    self.lmp_threads.setValue(cluster_config.get("lmp_threads", 4))
                    self.cluster_partition.setText(cluster_config.get("cluster_partition", ""))
                    self.cluster_nodes.setValue(cluster_config.get("cluster_nodes", 1))
                    self.cluster_ntasks.setValue(cluster_config.get("cluster_ntasks", 72))
                    self.cluster_cpus_per_task.setValue(cluster_config.get("cluster_cpus_per_task", 1))
                    self.cluster_time.setText(cluster_config.get("cluster_time", ""))
                    self.cluster_mail.setText(cluster_config.get("cluster_mail", ""))
                    self.cluster_modules.setText(cluster_config.get("cluster_modules", ""))
                    self.auto_submit.setChecked(cluster_config.get("auto_submit", False))
                    self.show_command.setChecked(cluster_config.get("show_command", True))
                    self.save_scripts_only.setChecked(cluster_config.get("save_scripts_only", False))
                
                # Load multi-study configuration
                if "multistudy" in config:
                    multi_config = config["multistudy"]
                    self.enable_multi_system.setChecked(multi_config.get("enable_multi_system", False))
                    self.system_path_edit.setText(multi_config.get("system_path", ""))
                    self.system_pattern.setText(multi_config.get("system_pattern", "*.data"))
                    self.enable_multi_deform.setChecked(multi_config.get("enable_multi_deform", False))
                    self.max_parallel_jobs.setValue(multi_config.get("max_parallel_jobs", 4))
                    self.use_job_array.setChecked(multi_config.get("use_job_array", False))
                    
                    # Load deformation studies
                    if "deform_studies" in multi_config and self.enable_multi_deform.isChecked():
                        deform_studies = multi_config["deform_studies"]
                        self.deform_table.setRowCount(0)  # Clear existing rows
                        for study in deform_studies:
                            row_count = self.deform_table.rowCount()
                            self.deform_table.insertRow(row_count)
                            self.deform_table.setItem(row_count, 0, QTableWidgetItem(study.get("name", "")))
                            self.deform_table.setItem(row_count, 1, QTableWidgetItem(study.get("rate", "")))
                            self.deform_table.setItem(row_count, 2, QTableWidgetItem(study.get("axis", "")))
                            self.deform_table.setItem(row_count, 3, QTableWidgetItem(study.get("style", "")))
                
                QMessageBox.information(self, "Success", "Configuration loaded successfully.")
            except Exception as e:
                QMessageBox.critical(self, "Error", f"Failed to load configuration: {str(e)}")
                
    def load_settings(self):
        """Load settings from QSettings"""
        # This method loads settings that are saved automatically when the application closes
        # These are different from the configuration files that users explicitly save/load
        
        # Example of loading a setting:
        # last_data_file = self.settings.value("last_data_file", "")
        # if last_data_file:
        #     self.data_path_edit.setText(last_data_file)
        
    def save_settings(self):
        """Save settings to QSettings"""
        # This method saves settings that will be automatically loaded when the application starts
        # These are different from the configuration files that users explicitly save/load
        
        # Example of saving a setting:
        # self.settings.setValue("last_data_file", self.data_path_edit.text())
        
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