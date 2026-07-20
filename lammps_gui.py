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
                                QListWidget, QStyle)
    from PyQt6.QtCore import Qt, QSettings, pyqtSignal, QThread, QTimer, QUrl, QSize, QPointF
    from PyQt6.QtGui import QIcon, QDesktopServices, QCursor, QPalette, QColor, QPixmap, QPainter, QFont
    
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
    from graph_widgets import DeformationTab, GraphWidget
except ImportError as e:
    DeformationTab = None
    GraphWidget = None

class Chip(QFrame):
    """A custom chip widget to display a removable item."""
    removed = pyqtSignal(str)

    def __init__(self, text, parent=None):
        super().__init__(parent)
        self.text = text
        self.setLayout(QHBoxLayout())
        self.layout().setContentsMargins(2, 0, 2, 0)
        self.layout().setSpacing(2)
        self.layout().setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.setFixedHeight(18)

        self.label = QLabel(text)
        self.label.setStyleSheet("font-size: 9px;")
        self.layout().addWidget(self.label)

        self.remove_button = QPushButton()
        close_icon = self.style().standardIcon(QStyle.StandardPixmap.SP_DialogCloseButton)
        self.remove_button.setIcon(close_icon)
        self.remove_button.setIconSize(QSize(9, 9))
        self.remove_button.setFixedSize(12, 12)
        self.remove_button.setStyleSheet(""" 
            QPushButton {
                border: none; 
                background-color: transparent;
            }
            QPushButton:hover {
                background-color: #d3d3d3;
                border-radius: 6px;
            }
        """)
        self.remove_button.clicked.connect(self.on_remove)
        self.layout().addWidget(self.remove_button)

        self.setStyleSheet("background-color: #e0e0e0; border-radius: 8px;")

    def on_remove(self):
        self.removed.emit(self.text)
        self.deleteLater()

class ClickableLabel(QLabel):
    """A QLabel that opens a URL when clicked."""
    def __init__(self, url, parent=None):
        super().__init__(parent)
        self.url = url

    def mousePressEvent(self, event):
        if event.button() == Qt.MouseButton.LeftButton:
            QDesktopServices.openUrl(self.url)
        super().mousePressEvent(event)

def create_info_icon_label(url, tooltip, color_name):
    pixmap = QPixmap(16, 16)
    pixmap.fill(Qt.GlobalColor.transparent)
    painter = QPainter(pixmap)
    painter.setRenderHint(QPainter.RenderHint.Antialiasing)
    painter.setBrush(QColor(color_name))
    painter.setPen(Qt.PenStyle.NoPen)
    painter.drawEllipse(0, 0, 15, 15)
    painter.setPen(QColor("white"))
    font = QFont("Arial", 10, QFont.Weight.Bold)
    painter.setFont(font)
    painter.drawText(pixmap.rect(), Qt.AlignmentFlag.AlignCenter, "i")
    painter.end()
    
    label = ClickableLabel(url)
    label.setPixmap(pixmap)
    label.setFixedSize(18, 18)
    label.setToolTip(tooltip)
    label.setCursor(QCursor(Qt.CursorShape.PointingHandCursor))
    
    return label

class InfoGroupBox(QGroupBox):
    def __init__(self, title, doc_link, parent=None, is_external=False, is_hpc=False, additional_docs=None):
        super().__init__(title, parent)
        self.doc_link = doc_link
        self.is_external = is_external
        self.is_hpc = is_hpc
        self.additional_docs = additional_docs or []  # List of additional documentation links

        # Use the main doc link for the URL and tooltip
        if is_external:
            url = QUrl(self.doc_link)
            tooltip = f"Click to open {doc_link}"
        else:
            url = QUrl(f"https://docs.lammps.org/{self.doc_link}.html")
            tooltip = f"Click to open LAMMPS {doc_link} documentation"

        # If additional docs exist, update tooltip to indicate multiple docs
        if self.additional_docs:
            tooltip = f"Click to open LAMMPS documentation for {doc_link} and others"

        color = "green" if self.is_hpc else "blue"
        
        self.info_label = create_info_icon_label(url, tooltip, color)
        self.info_label.setParent(self)

        # Override the mousePressEvent to open multiple links if they exist
        if self.additional_docs:
            def custom_mouse_press(event):
                if event.button() == Qt.MouseButton.LeftButton:
                    # Open all links (main + additional) - only once each
                    # Open the primary link
                    QDesktopServices.openUrl(self.info_label.url)
                    # Open additional links
                    for doc_link, is_ext in self.additional_docs:
                        if is_ext:
                            url = QUrl(doc_link)
                        else:
                            url = QUrl(f"https://docs.lammps.org/{doc_link}.html")
                        QDesktopServices.openUrl(url)
                # For other mouse button events or other handling without duplicate URL opening
                QLabel.mousePressEvent(self.info_label, event)
            
            self.info_label.mousePressEvent = custom_mouse_press

    def resizeEvent(self, event):
        super().resizeEvent(event)
        # Position the icon in the top-right corner
        self.info_label.move(self.width() - 22, 2)

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

class LammpsGui(QMainWindow):
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
        
        # Custom data file extensions
        self.data_file_extensions = [".data"]

        
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
            config = self.collect_config(for_saving=True)
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
        
        # Lower part of the system selection group
        lower_layout = QHBoxLayout()

        # File extensions for data files
        extensions_group = QWidget()
        extensions_layout = QHBoxLayout(extensions_group)
        extensions_layout.setContentsMargins(0,0,0,0)
        extensions_label = QLabel("File Extensions:")
        self.extensions_input = QLineEdit()
        self.extensions_input.setPlaceholderText("Add, e.g., .data, .txt, .atom")
        self.extensions_input.returnPressed.connect(self._add_data_extension_chip)
        self.extensions_input.editingFinished.connect(self._add_data_extension_chip)
        self.extensions_input.installEventFilter(self)

        self.chips_layout = QHBoxLayout()
        self._add_chip(".data", self.chips_layout, self._remove_data_extension_chip)

        extensions_layout.addWidget(extensions_label)
        extensions_layout.addLayout(self.chips_layout)
        extensions_layout.addWidget(self.extensions_input, 1)
        
        lower_layout.addWidget(extensions_group, 1)

        # System type display
        self.system_type_label = QLabel("System Type: Not selected")
        self.system_type_label.setStyleSheet("font-weight: bold;")
        lower_layout.addWidget(self.system_type_label)

        system_layout_main.addLayout(lower_layout)

        # Single field for file/directory selection
        selection_layout = QHBoxLayout()
        
        system_path_label = QLabel("System File Path:")
        selection_layout.addWidget(system_path_label)
        
        self.system_path_edit = QLineEdit()
        self.system_path_edit.setPlaceholderText("Select data file or directory containing data files")
        self.system_path_edit.setToolTip("Path to a single .data file or directory with multiple .data files")
        
        self.system_path_browse = QPushButton("Browse...")
        self.system_path_browse.clicked.connect(self.browse_system_path)
        self.system_path_browse.setToolTip("Browse for data file or directory")
        
        selection_layout.addWidget(self.system_path_edit)
        selection_layout.addWidget(self.system_path_browse)
        
        system_layout_main.addLayout(selection_layout)
        
        # Update system type when path changes
        self.system_path_edit.textChanged.connect(self.update_system_type)
        
        system_group.setLayout(system_layout_main)
        scroll_layout.addWidget(system_group)
        
        # Potential Definition
        potential_group = InfoGroupBox("Potential Definition", "include")
        potential_layout = QVBoxLayout(potential_group)

        # Header row
        header_layout = QHBoxLayout()
        self.use_potential_file = QCheckBox("Use separate potential definition from")
        self.use_potential_file.setChecked(False) 
        self.use_potential_file.stateChanged.connect(self.toggle_potential_settings)
        
        self.potential_source_combo = QComboBox()
        self.potential_source_combo.addItems(["file", "text"])
        self.potential_source_combo.currentTextChanged.connect(self.update_potential_visibility)
        
        header_layout.addWidget(self.use_potential_file)
        header_layout.addWidget(self.potential_source_combo)
        header_layout.addWidget(QLabel("and initialize"))
        
        self.potential_pos_combo = QComboBox()
        self.potential_pos_combo.addItems(["after", "before"])
        self.potential_pos_combo.setCurrentText("after")
        header_layout.addWidget(self.potential_pos_combo)
        
        header_layout.addWidget(QLabel("reading atom data"))
        header_layout.addStretch()
        
        potential_layout.addLayout(header_layout)

        # File Mode UI
        self.potential_file_widget = QWidget()
        file_layout = QHBoxLayout(self.potential_file_widget)
        file_layout.setContentsMargins(0,0,0,0)
        self.potential_path_edit = QLineEdit()
        self.potential_path_browse = QPushButton("Browse...")
        self.potential_path_browse.clicked.connect(self.browse_potential_file)
        self.potential_path_edit.setToolTip("Path to the potential file")
        file_layout.addWidget(QLabel("Path:"))
        file_layout.addWidget(self.potential_path_edit)
        file_layout.addWidget(self.potential_path_browse)
        potential_layout.addWidget(self.potential_file_widget)

        # Text Mode UI
        self.potential_text_edit = QTextEdit()
        self.potential_text_edit.setPlaceholderText("Enter potential commands here...")
        self.set_precise_height(self.potential_text_edit, 4.3) # Precise 4.3 lines
        
        # Apply style to scrollbar
        scrollbar_style = """
            QScrollBar:vertical {
                border: none;
                background: #f0f0f0;
                width: 10px;
                margin: 0px 0px 0px 0px;
            }
            QScrollBar::handle:vertical {
                background: #c0c0c0;
                min-height: 20px;
                border-radius: 5px;
            }
            QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical {
                height: 0px;
            }
        """
        self.potential_text_edit.setStyleSheet(scrollbar_style)
        potential_layout.addWidget(self.potential_text_edit)
        
        # Initial visibility update
        self.update_potential_visibility(self.potential_source_combo.currentText())
        self.toggle_potential_settings(self.use_potential_file.checkState())

        scroll_layout.addWidget(potential_group)
        
        # Create a horizontal layout for the three widgets
        settings_layout = QHBoxLayout()
        
        # Basic LAMMPS settings
        basic_group = InfoGroupBox("Basic LAMMPS Settings", "atom_style")
        basic_layout = QFormLayout()
        
        self.atom_style_combo = QComboBox()
        self.atom_style_combo.addItems(["atomic", "bond", "molecular", "full", "charge", "dipole"])
        self.atom_style_combo.setToolTip("Specify the atom style for the simulation")
        
        atom_style_label = QLabel("Atom Style:")
        
        basic_layout.addRow(atom_style_label, self.atom_style_combo)
        basic_group.setLayout(basic_layout)
        basic_group.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Preferred)
        
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
        units_layout.addWidget(self.units_combo, 1) # Stretch to fill
        
        units_group.setLayout(units_layout)
        units_group.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Preferred)

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
        timestep_layout.addWidget(self.timestep, 1) # Stretch to fill
        timestep_layout.addWidget(self.timestep_unit_label)
        timestep_group.setLayout(timestep_layout)
        timestep_group.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Preferred)
        
        # Add all three widgets to the horizontal layout
        settings_layout.addWidget(basic_group)
        settings_layout.addWidget(units_group)
        settings_layout.addWidget(timestep_group)
        
        # Add the horizontal layout to the scroll layout
        scroll_layout.addLayout(settings_layout)

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

        # Ensemble settings (MOVED to deformation tab)
        
        # Velocity initialization settings
        velocity_group = InfoGroupBox("Velocity Initialization", "velocity")
        velocity_layout = QHBoxLayout() # Changed to HBox
        
        self.enable_velocity = QCheckBox("Initialize velocity")
        self.enable_velocity.setChecked(True)
        self.enable_velocity.setToolTip("Enable initial velocity generation")
        self.enable_velocity.stateChanged.connect(self.toggle_velocity_settings)
        velocity_layout.addWidget(self.enable_velocity)
        
        velocity_layout.addSpacing(20)

        self.initial_velocity_seed = QSpinBox()
        self.initial_velocity_seed.setRange(1, 1000000)
        self.initial_velocity_seed.setValue(12345)
        self.initial_velocity_seed.setToolTip("Random seed for initializing the velocity")
        
        self.damping_factor = QDoubleSpinBox()
        self.damping_factor.setRange(0.1, 1000)
        self.damping_factor.setValue(100.0)
        self.damping_factor.setSingleStep(10.0)
        self.damping_factor.setToolTip("Damping factor multiplied with timestep for thermostating the system")
        
        velocity_layout.addWidget(QLabel("Seed:"))
        velocity_layout.addWidget(self.initial_velocity_seed, 1)
        velocity_layout.addSpacing(10)
        velocity_layout.addWidget(QLabel("Damping factor:"))
        velocity_layout.addWidget(self.damping_factor, 1)
        
        velocity_group.setLayout(velocity_layout)
        scroll_layout.addWidget(velocity_group)
        
        # Custom Commands (formerly Neighbor Settings)
        custom_commands_group = InfoGroupBox("Custom Commands", "neighbor", additional_docs=[("comm_modify", False)])
        custom_commands_layout = QVBoxLayout(custom_commands_group)
        
        self.custom_commands_edit = QTextEdit()
        self.custom_commands_edit.setPlaceholderText("e.g., neighbor 2.0 bin\nneigh_modify delay 5 every 1 check yes one 20000 page 200000\ncomm_modify cutoff 20.0")
        
        # Apply style to scrollbar
        self.custom_commands_edit.setStyleSheet(scrollbar_style)
        
        # Fixed height (4 lines)
        self.set_precise_height(self.custom_commands_edit, 4)
        
        custom_commands_layout.addWidget(self.custom_commands_edit)
        scroll_layout.addWidget(custom_commands_group)
        
        # Add stretch to push everything up
        scroll_layout.addStretch()

    def adjust_text_height(self, text_edit, min_lines, max_lines):
        """Adjust QTextEdit height dynamically based on content."""
        doc = text_edit.document()
        # Ensure layout is up to date
        doc.adjustSize()
        layout = doc.documentLayout()
        
        # Calculate line height based on font metrics
        font_metrics = text_edit.fontMetrics()
        line_height = font_metrics.lineSpacing()
        
        # Calculate content height using document size
        content_height = layout.documentSize().height()
        
        # Consistent padding matching graph_widgets.py (12px covers margins + frame)
        padding = 12
        
        min_h = int(min_lines * line_height + padding)
        max_h = int(max_lines * line_height + padding)
        
        # Determine new height
        new_height = int(content_height + padding)
        
        # Clamp
        if new_height < min_h:
            new_height = min_h
        if new_height > max_h:
            new_height = max_h
            
        text_edit.setFixedHeight(new_height)

    def set_precise_height(self, text_edit, num_lines):
        """Set a precise fixed height based on line count."""
        font_metrics = text_edit.fontMetrics()
        line_height = font_metrics.lineSpacing()
        padding = 12 # Consistent padding
        height = int(num_lines * line_height + padding)
        text_edit.setFixedHeight(height)
        


    def toggle_potential_settings(self, state):
        """Toggle potential definition widgets."""
        enabled = (state == Qt.CheckState.Checked.value)
        self.potential_source_combo.setEnabled(enabled)
        self.potential_pos_combo.setEnabled(enabled)
        
        # Also toggle current visible mode widget
        self.update_potential_visibility(self.potential_source_combo.currentText())

    def update_potential_visibility(self, source_text):
        """Show/Hide potential widgets based on source selection."""
        is_enabled = self.use_potential_file.isChecked()
        
        if source_text == "file":
            self.potential_file_widget.setVisible(True)
            self.potential_text_edit.setVisible(False)
            self.potential_file_widget.setEnabled(is_enabled)
        else:
            self.potential_file_widget.setVisible(False)
            self.potential_text_edit.setVisible(True)
            self.potential_text_edit.setEnabled(is_enabled)

    def _add_chip(self, text, layout, remove_slot):
        chip = Chip(text)
        chip.removed.connect(remove_slot)
        layout.addWidget(chip)

    def _add_data_extension_chip(self):
        self._add_extension_chip(self.extensions_input, self.data_file_extensions, self.chips_layout, self._remove_data_extension_chip)

    def _add_extension_chip(self, input_widget, extensions_list, chips_layout, remove_slot):
        text = input_widget.text().strip()
        delimiters = [',', ';', ':', ' ']
        for delimiter in delimiters:
            if delimiter in text:
                extensions = [ext.strip() for ext in text.split(delimiter)]
                for ext in extensions:
                    if ext:
                        self._add_single_extension(ext, extensions_list, chips_layout, remove_slot)
                input_widget.clear()
                return

        if text:
            self._add_single_extension(text, extensions_list, chips_layout, remove_slot)
            input_widget.clear()

    def _add_single_extension(self, text, extensions_list, chips_layout, remove_slot):
        if not text.startswith('.'):
            text = '.' + text
        if text not in extensions_list:
            extensions_list.append(text)
            self._add_chip(text, chips_layout, remove_slot)
            # Refresh the system type display if a path is entered
            self.update_system_type()

    def _remove_data_extension_chip(self, text):
        self._remove_extension_chip(text, self.data_file_extensions, self.chips_layout)

    def _remove_extension_chip(self, text, extensions_list, chips_layout):
        if text in extensions_list:
            extensions_list.remove(text)
        # Find and remove the chip widget
        for i in range(chips_layout.count()):
            widget = chips_layout.itemAt(i).widget()
            if isinstance(widget, Chip) and widget.text == text:
                widget.deleteLater()
                break
        # Refresh the system type display if a path is entered
        self.update_system_type()

    def _add_item_chip(self, index, combo_box, chips_layout, remove_slot):
        """Generic method to add a chip for a selected item from a combo box."""
        if index == 0:  # "Add quantity..."
            return

        text = combo_box.currentText()
        combo_box.removeItem(index)

        chip = Chip(text)
        chip.removed.connect(remove_slot)
        chips_layout.addWidget(chip)

    def _re_add_item_to_combo(self, text, combo_box, master_list):
        """Adds a text item back to a combo box, maintaining the master list's order."""
        # Find the correct index to insert the item to maintain master order
        master_index = master_list.index(text)
        insert_at_index = 1  # Start after "Add quantity..."
        
        for i in range(1, combo_box.count()):
            current_item_text = combo_box.itemText(i)
            current_item_master_index = master_list.index(current_item_text)
            if current_item_master_index > master_index:
                break
            insert_at_index += 1
        else: # If we went through the whole loop, add it to the end
            insert_at_index = combo_box.count()

        combo_box.insertItem(insert_at_index, text)

    def add_averaged_quantity_chip(self, index):
        """Add a chip for the selected averaged quantity."""
        self._add_item_chip(index, self.averaged_quantities_combo, self.avg_chips_layout, self.remove_averaged_quantity_chip)
        self._update_averaging_spinboxes_state()

    def remove_averaged_quantity_chip(self, text):
        """Remove an averaged quantity chip and add the option back to the combo box."""
        self._re_add_item_to_combo(text, self.averaged_quantities_combo, self.all_avg_quantities)
        # Schedule update after event loop to ensure chip is removed
        QTimer.singleShot(0, self._update_averaging_spinboxes_state)

    def _update_averaging_spinboxes_state(self):
        """Enable/disable averaging spinboxes based on whether chips exist."""
        has_chips = self.avg_chips_layout.count() > 0
        
        self.avg_nevery_spinbox.setEnabled(has_chips)
        self.avg_nrepeat_spinbox.setEnabled(has_chips)
        
        color = "black" if has_chips else "gray"
        style = f"color: {color};"
        
        if hasattr(self, 'avg_label_every'):
            self.avg_label_every.setStyleSheet(style)
        if hasattr(self, 'avg_label_timesteps'):
            self.avg_label_timesteps.setStyleSheet(style)
        if hasattr(self, 'avg_label_values'):
            self.avg_label_values.setStyleSheet(style)
        
        if not has_chips:
             self.avg_nevery_spinbox.setStyleSheet("color: gray;")
             self.avg_nrepeat_spinbox.setStyleSheet("color: gray;")
        else:
             self.avg_nevery_spinbox.setStyleSheet("")
             self.avg_nrepeat_spinbox.setStyleSheet("")

    def add_eng_strain_chip(self, index):
        """Add a chip for the selected engineering strain."""
        self._add_item_chip(index, self.eng_strains_combo, self.eng_strains_chips_layout, self.remove_eng_strain_chip)

    def remove_eng_strain_chip(self, text):
        """Remove an engineering strain chip."""
        self._re_add_item_to_combo(text, self.eng_strains_combo, self.all_eng_strains)

    def add_cauchy_stress_chip(self, index):
        """Add a chip for the selected Cauchy stress."""
        self._add_item_chip(index, self.cauchy_stresses_combo, self.cauchy_stresses_chips_layout, self.remove_cauchy_stress_chip)

    def remove_cauchy_stress_chip(self, text):
        """Remove a Cauchy stress chip."""
        self._re_add_item_to_combo(text, self.cauchy_stresses_combo, self.all_cauchy_stresses)

    def validate_and_round_nevery(self):
        """Validate that avg_nevery is a divisor of thermo_freq, rounding to the nearest valid divisor if not."""
        thermo_freq = self.thermo_freq_spinbox.value()
        nevery = self.avg_nevery_spinbox.value()

        if thermo_freq <= 0 or nevery <= 0:  # Avoid division by zero and invalid values
            self.validate_nrepeat() # Still validate nrepeat in case thermo_freq changed
            return
        
        # If it's already a valid divisor, do nothing.
        if thermo_freq % nevery == 0:
            self.validate_nrepeat() # Still validate nrepeat in case thermo_freq changed
            return

        # Find all divisors of thermo_freq
        divisors = set()
        for i in range(1, int(thermo_freq**0.5) + 1):
            if thermo_freq % i == 0:
                divisors.add(i)
                divisors.add(thermo_freq // i)
        
        if not divisors:
            self.validate_nrepeat()
            return

        # Find the closest divisor to the current nevery value
        closest_divisor = min(divisors, key=lambda d: abs(d - nevery))
        
        # Set the spinbox value to the closest divisor, blocking signals to prevent recursion
        self.avg_nevery_spinbox.blockSignals(True)
        self.avg_nevery_spinbox.setValue(closest_divisor)
        self.avg_nevery_spinbox.blockSignals(False)
        
        # Now that nevery is valid, trigger validation for nrepeat
        self.validate_nrepeat()

    def validate_nrepeat(self):
        """Ensure nrepeat is valid based on thermo_freq and nevery."""
        thermo_freq = self.thermo_freq_spinbox.value()
        nevery = self.avg_nevery_spinbox.value()
        nrepeat = self.avg_nrepeat_spinbox.value()

        if nevery <= 0:  # Avoid division by zero
            return
            
        # We enforce thermo_freq = nevery * nrepeat.
        # The validation for nevery ensures it's a divisor of thermo_freq.
        # Therefore, the maximum allowed nrepeat is thermo_freq / nevery.
        max_nrepeat = thermo_freq // nevery
        
        # nrepeat must be at least 1.
        if max_nrepeat < 1:
            max_nrepeat = 1
        
        if nrepeat > max_nrepeat:
            self.avg_nrepeat_spinbox.blockSignals(True)
            self.avg_nrepeat_spinbox.setValue(max_nrepeat)
            self.avg_nrepeat_spinbox.blockSignals(False)


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
            if any(path.endswith(ext) for ext in self.data_file_extensions):
                self.system_type_label.setText("System Type: Single file")
                # Auto-detect units and atom style from .data file
                self.auto_detect_from_data_file(path)
            else:
                self.system_type_label.setText("System Type: Single file")
        elif os.path.isdir(path):
            # Count data files in directory
            data_files = []
            for ext in self.data_file_extensions:
                data_files.extend(glob.glob(os.path.join(path, f"*{ext}")))
            count = len(data_files)
            if count > 0:
                self.system_type_label.setText(f"System Type: Multiple files ({count} files found)")
                # Auto-detect units and atom style from first .data file
                self.auto_detect_from_data_file(data_files[0])
            else:
                self.system_type_label.setText("System Type: Directory (no files found)")
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
        self.tab_widget.addTab(self.deformation_tab, "Processing")
        
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
        self.deformation_tab_widget.studiesChanged.connect(self._update_output_tab_visibility)
        
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
            
    def _update_output_tab_visibility(self):
        """Update visibility of output options based on study modes."""
        if not hasattr(self, 'deformation_tab_widget'):
            return

        modes = self.deformation_tab_widget.get_study_modes()
        
        has_deformation_study = "Deformation" in modes
        has_temperature_study = "Temperature" in modes

        self.eng_strains_widget.setVisible(has_deformation_study)
        self.cauchy_stresses_widget.setVisible(has_deformation_study)
        self.target_temp_widget.setVisible(has_temperature_study)

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
        
        # Write data at end setting - moved to top position
        write_data_group = InfoGroupBox("Write Data", "write_data")
        write_data_layout = QVBoxLayout()

        self.write_data_combo = QComboBox()
        self.write_data_combo.addItems([
            "Never",
            "After each deformation/temperature step",
            "At the end of the simulation"
        ])
        self.write_data_combo.setToolTip("Select when to write atom data.")
        
        write_data_layout.addWidget(self.write_data_combo)
        write_data_group.setLayout(write_data_layout)
        scroll_layout.addWidget(write_data_group)
        
        # Thermo output settings
        thermo_group = InfoGroupBox("Thermo Output Settings", "thermo_style")
        thermo_layout = QVBoxLayout()

        # Top row layout
        thermo_top_layout = QHBoxLayout()

        self.enable_thermo = QCheckBox("Enable Thermo Output")
        self.enable_thermo.setChecked(True)
        self.enable_thermo.setToolTip("Enable thermodynamic output")
        self.enable_thermo.stateChanged.connect(self.toggle_thermo_settings)
        thermo_top_layout.addWidget(self.enable_thermo, 1)

        thermo_freq_layout = QHBoxLayout()
        thermo_freq_label = QLabel("Thermo Freq:")
        self.thermo_freq_spinbox = QSpinBox()
        self.thermo_freq_spinbox.setRange(1, 999999999)
        self.thermo_freq_spinbox.setValue(100)
        self.thermo_freq_spinbox.setSingleStep(100)
        self.thermo_freq_spinbox.setToolTip("Frequency of thermodynamic output")
        self.thermo_freq_spinbox.setMinimumWidth(150)
        self.thermo_freq_spinbox.valueChanged.connect(self.validate_and_round_nevery) # Connect to validation cascade
        thermo_freq_layout.addWidget(thermo_freq_label)
        thermo_freq_layout.addWidget(self.thermo_freq_spinbox)
        thermo_freq_layout.addStretch()
        thermo_top_layout.addLayout(thermo_freq_layout, 2)

        self.target_temp_widget = QWidget()
        target_temp_layout = QHBoxLayout(self.target_temp_widget)
        target_temp_layout.setContentsMargins(0,0,0,0)
        self.add_target_to_thermo_check = QCheckBox("Add target temperature to thermo output")
        self.add_target_to_thermo_check.setToolTip("If checked, adds the target temperature for the current study step to the thermo output.")
        target_temp_layout.addWidget(self.add_target_to_thermo_check)
        thermo_top_layout.addWidget(self.target_temp_widget, 2)

        thermo_layout.addLayout(thermo_top_layout)

        # Thermo Style
        thermo_style_layout = QHBoxLayout()
        thermo_style_label = QLabel("Thermo Style:")
        self.thermo_style = QLineEdit()
        self.thermo_style.setText("step etotal pe ke epair ebond evdwl ecoul elong temp press pxx pyy pzz pxy pxz pyz lx ly lz density")
        self.thermo_style.setToolTip("Thermo style specification")
        thermo_style_layout.addWidget(thermo_style_label)
        thermo_style_layout.addWidget(self.thermo_style)
        
        # Engineering Strains
        self.eng_strains_widget = QWidget()
        eng_strains_layout_main = QHBoxLayout(self.eng_strains_widget)
        eng_strains_layout_main.setContentsMargins(0, 0, 0, 0)
        eng_strains_label = QLabel("Engineering strains:")
        self.eng_strains_combo = QComboBox()
        self.eng_strains_chips_layout = QHBoxLayout(); self.eng_strains_chips_layout.setSpacing(2)
        eng_strains_layout_main.addWidget(eng_strains_label)
        eng_strains_layout_main.addLayout(self.eng_strains_chips_layout)
        eng_strains_layout_main.addWidget(self.eng_strains_combo, 1)
        self.all_eng_strains = ['deformation direction', 'εxx', 'εyy', 'εzz', 'εxy', 'εxz', 'εyz']
        self.eng_strains_combo.addItem("Add quantity...")
        self.eng_strains_combo.addItems(self.all_eng_strains)
        self.eng_strains_combo.activated.connect(self.add_eng_strain_chip)

        # Cauchy Stresses
        self.cauchy_stresses_widget = QWidget()
        cauchy_stresses_layout_main = QHBoxLayout(self.cauchy_stresses_widget)
        cauchy_stresses_layout_main.setContentsMargins(0, 0, 0, 0)
        cauchy_stresses_label = QLabel("Cauchy stresses:")
        self.cauchy_stresses_combo = QComboBox()
        self.cauchy_stresses_chips_layout = QHBoxLayout(); self.cauchy_stresses_chips_layout.setSpacing(2)
        cauchy_stresses_layout_main.addWidget(cauchy_stresses_label)
        cauchy_stresses_layout_main.addLayout(self.cauchy_stresses_chips_layout)
        cauchy_stresses_layout_main.addWidget(self.cauchy_stresses_combo, 1)
        self.all_cauchy_stresses = ['deformation direction', 'σxx', 'σyy', 'σzz', 'σxy', 'σxz', 'σyz', 'von Mises', 'hydrostatic']
        self.cauchy_stresses_combo.addItem("Add quantity...")
        self.cauchy_stresses_combo.addItems(self.all_cauchy_stresses)
        self.cauchy_stresses_combo.activated.connect(self.add_cauchy_stress_chip)
        
        # Time averaged thermo styles
        time_averaged_layout = QHBoxLayout()
        time_averaged_label = QLabel("Average")
        self.averaged_quantities_combo = QComboBox()
        self.avg_chips_layout = QHBoxLayout()
        self.avg_chips_layout.setSpacing(2)

        self.avg_nevery_spinbox = QSpinBox()
        self.avg_nevery_spinbox.setToolTip("nevery")
        self.avg_nevery_spinbox.setRange(1, 10000)
        self.avg_nevery_spinbox.setValue(10)
        self.avg_nevery_spinbox.setFixedWidth(80)
        self.avg_nevery_spinbox.editingFinished.connect(self.validate_and_round_nevery)

        self.avg_nrepeat_spinbox = QSpinBox()
        self.avg_nrepeat_spinbox.setToolTip("nrepeat")
        self.avg_nrepeat_spinbox.setRange(1, 100000)
        self.avg_nrepeat_spinbox.setValue(10) # Default changed to make it consistent with default thermo_freq and nevery
        self.avg_nrepeat_spinbox.setFixedWidth(80)
        self.avg_nrepeat_spinbox.editingFinished.connect(self.validate_nrepeat)

        time_averaged_layout.addWidget(time_averaged_label)
        time_averaged_layout.addLayout(self.avg_chips_layout)
        time_averaged_layout.addWidget(self.averaged_quantities_combo, 1)
        time_averaged_layout.addStretch(0)
        self.avg_label_every = QLabel("every")
        time_averaged_layout.addWidget(self.avg_label_every)
        time_averaged_layout.addWidget(self.avg_nevery_spinbox)
        self.avg_label_timesteps = QLabel("timesteps and consider")
        time_averaged_layout.addWidget(self.avg_label_timesteps)
        time_averaged_layout.addWidget(self.avg_nrepeat_spinbox)
        self.avg_label_values = QLabel("values before thermo ouput")
        time_averaged_layout.addWidget(self.avg_label_values)
        
        avg_time_url = QUrl("https://docs.lammps.org/fix_ave_time.html")
        avg_time_tooltip = "Click to open LAMMPS documentation for fix ave/time"
        self.avg_time_info_label = create_info_icon_label(avg_time_url, avg_time_tooltip, "blue")
        time_averaged_layout.addWidget(self.avg_time_info_label)

        self.all_avg_quantities = ['temp', 'press', 'pxx', 'pyy', 'pzz', 'pxy', 'pxz', 'pyz', 'ke', 'pe', 'stress', 'strain']
        self.averaged_quantities_combo.addItem("Add quantity...")
        self.averaged_quantities_combo.addItems(self.all_avg_quantities)
        self.averaged_quantities_combo.activated.connect(self.add_averaged_quantity_chip)

        thermo_layout.addLayout(thermo_style_layout)
        thermo_layout.addWidget(self.eng_strains_widget)
        thermo_layout.addWidget(self.cauchy_stresses_widget)
        thermo_layout.addLayout(time_averaged_layout)
        thermo_group.setLayout(thermo_layout)
        scroll_layout.addWidget(thermo_group)
        self._update_averaging_spinboxes_state()

        # Trajectory output settings
        traj_group = InfoGroupBox("Trajectory Output Settings", "dump")
        traj_layout = QVBoxLayout()

        # Top row layout
        traj_top_layout = QHBoxLayout()

        self.enable_trajectory = QCheckBox("Enable Trajectory Output")
        self.enable_trajectory.setChecked(True)
        self.enable_trajectory.setToolTip("Enable trajectory file output")
        self.enable_trajectory.stateChanged.connect(self.toggle_trajectory_settings)
        traj_top_layout.addWidget(self.enable_trajectory, 1) # 1/5

        # Trajectory Freq
        traj_freq_layout = QHBoxLayout()
        traj_freq_label = QLabel("Trajectory Freq:")
        self.traj_freq_spinbox = QSpinBox()
        self.traj_freq_spinbox.setRange(1, 999999999)
        self.traj_freq_spinbox.setValue(100)
        self.traj_freq_spinbox.setSingleStep(100)
        self.traj_freq_spinbox.setToolTip("Frequency of trajectory output")
        self.traj_freq_spinbox.setMinimumWidth(150)
        traj_freq_layout.addWidget(traj_freq_label)
        traj_freq_layout.addWidget(self.traj_freq_spinbox)
        traj_freq_layout.addStretch()
        traj_top_layout.addLayout(traj_freq_layout, 2) # 2/5

        # Trajectory Format
        traj_format_layout = QHBoxLayout()
        traj_format_label = QLabel("Trajectory Format:")
        self.traj_format = QComboBox()
        self.traj_format.addItems(["lammpstrj", "xyz", "dcd"])
        self.traj_format.setToolTip("Format for trajectory files")
        self.traj_format.setMinimumWidth(150)
        traj_format_layout.addWidget(traj_format_label)
        traj_format_layout.addWidget(self.traj_format)
        traj_format_layout.addStretch()
        traj_top_layout.addLayout(traj_format_layout, 2) # 2/5

        traj_layout.addLayout(traj_top_layout)

        # Output Items
        traj_form_layout = QFormLayout()
        self.trj_output_items = QLineEdit()
        self.trj_output_items.setText("id type x y z fx fy fz")
        self.trj_output_items.setToolTip("Items to include in trajectory output")
        traj_form_layout.addRow("Output Items:", self.trj_output_items)
        
        traj_layout.addLayout(traj_form_layout)
        traj_group.setLayout(traj_layout)
        scroll_layout.addWidget(traj_group)
        
        # Custom dumps
        custom_dumps_group = InfoGroupBox("Custom Dumps", "dump")
        custom_dumps_layout = QVBoxLayout()
        
        self.custom_dumps_text = QTextEdit()
        self.custom_dumps_text.setPlaceholderText("Enter custom dump commands here...")
        self.custom_dumps_text.setMaximumHeight(100)  # Reduced height (about 4 lines)
        self.custom_dumps_text.setToolTip("Custom LAMMPS dump commands")
        
        custom_dumps_layout.addWidget(self.custom_dumps_text)
        custom_dumps_group.setLayout(custom_dumps_layout)
        custom_dumps_group.setMaximumHeight(112)
        scroll_layout.addWidget(custom_dumps_group)
        
        # Add stretch to push everything up
        scroll_layout.addStretch()
        
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

        multi_proc_row = QHBoxLayout()
        self.local_multiprocessor_check = QCheckBox("Use multiple processors")
        self.local_multiprocessor_check.toggled.connect(self.toggle_multiprocessor_settings)
        self.local_multiprocessor_check.setFixedHeight(22)
        multi_proc_row.addWidget(self.local_multiprocessor_check)

        self.local_processors_label = QLabel("Number of processors:")
        self.local_processors_label.setFixedHeight(22)
        self.local_processors_spinbox = QSpinBox()
        self.local_processors_spinbox.setRange(1, 128)
        self.local_processors_spinbox.setValue(4)
        self.local_processors_spinbox.setFixedHeight(22)
        multi_proc_row.addWidget(self.local_processors_label)
        multi_proc_row.addWidget(self.local_processors_spinbox)
        multi_proc_row.addStretch()
        
        local_layout.addRow(multi_proc_row)

        self.local_lammps_cmd_label = QLabel("Local LAMMPS Command:")
        self.local_lammps_cmd = QLineEdit()
        self.local_lammps_cmd.setPlaceholderText("lmp")
        self.local_lammps_cmd.setToolTip("Command to run LAMMPS locally.")
        local_layout.addRow(self.local_lammps_cmd_label, self.local_lammps_cmd)

        self.local_lammps_executable_label = QLabel("LAMMPS Executable:")
        self.local_lammps_executable = QLineEdit("lmp_mpi")
        local_layout.addRow(self.local_lammps_executable_label, self.local_lammps_executable)

        # Log file name
        self.log_file_name_label = QLabel("Log file name:")
        self.log_file_name = QLineEdit()
        self.log_file_name.setPlaceholderText("job.log")
        self.log_file_name.setToolTip("Name of the log file for LAMMPS output. If empty, no log file will be created.")
        local_layout.addRow(self.log_file_name_label, self.log_file_name)
        
        # OS Selection
        self.os_selection_label = QLabel("Operating System:")
        self.os_selection_combo = QComboBox()
        self.os_selection_combo.addItems(["Auto-detect", "Windows", "Unix/Linux"])
        self.os_selection_combo.setToolTip("Select the operating system for local execution script generation")
        local_layout.addRow(self.os_selection_label, self.os_selection_combo)

        local_group.setLayout(local_layout)
        scroll_layout.addWidget(local_group)

        self.toggle_multiprocessor_settings(False)

        # Cluster settings
        cluster_group = InfoGroupBox("Cluster Settings", "https://hpc-wiki.info/hpc/SLURM", is_external=True, is_hpc=True)
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
#SBATCH --output=job_%j.log
#SBATCH --error=Job_%j.err""")
        self.slurm_header_text.setToolTip("SLURM batch script header.")
        self.slurm_header_text.setMinimumHeight(300)
        cluster_layout.addRow("SLURM Header:", self.slurm_header_text)

        # Restart settings
        self.enable_restart_checkbox = QCheckBox("Enable automatic restart")
        self.enable_restart_checkbox.setToolTip("Enable automatic job restart for long simulations on clusters. This will configure the simulation to save its state periodically and automatically resubmit the job before the runtime threshold is reached.")
        
        restart_toggle_layout = QHBoxLayout()
        restart_toggle_layout.setContentsMargins(0,0,0,0)
        restart_toggle_layout.addWidget(self.enable_restart_checkbox)
        restart_toggle_layout.addStretch()

        lammps_restart_link = "https://docs.lammps.org/restart.html"
        lammps_tooltip = "Click to open LAMMPS documentation for the restart command"
        lammps_info_label = create_info_icon_label(QUrl(lammps_restart_link), lammps_tooltip, "blue")
        restart_toggle_layout.addWidget(lammps_info_label)

        cluster_layout.addRow(restart_toggle_layout)

        # Create a widget to hold the restart options so it can be hidden/shown
        self.restart_options_widget = QWidget()
        restart_options_layout = QFormLayout()
        self.restart_options_widget.setLayout(restart_options_layout)
        restart_options_layout.setContentsMargins(0, 0, 0, 0)

        self.restart_freq_spinbox = QSpinBox()
        self.restart_freq_spinbox.setRange(10, 2147483647)
        self.restart_freq_spinbox.setValue(100000)
        self.restart_freq_spinbox.setSingleStep(100)
        self.restart_freq_spinbox.setToolTip("Frequency (in MD steps) to write a restart file. For example, a value of 1000 will save the simulation state every 1000 steps.")
        restart_options_layout.addRow("Restart Write Frequency:", self.restart_freq_spinbox)

        # Runtime threshold with hours and minutes
        runtime_threshold_layout = QHBoxLayout()
        
        # Hours
        hours_label = QLabel("Hours:")
        self.runtime_threshold_hours = QSpinBox()
        self.runtime_threshold_hours.setRange(0, 999)
        self.runtime_threshold_hours.setValue(23)
        self.runtime_threshold_hours.setFixedWidth(80)  # Fixed width to match minutes field
        self.runtime_threshold_hours.setToolTip("Hours portion of the runtime threshold")
        
        # Minutes
        minutes_label = QLabel("Minutes:")
        self.runtime_threshold_minutes = QSpinBox()
        self.runtime_threshold_minutes.setRange(0, 59)
        self.runtime_threshold_minutes.setValue(45)
        self.runtime_threshold_minutes.setFixedWidth(80)  # Fixed width to match hours field
        self.runtime_threshold_minutes.setToolTip("Minutes portion of the runtime threshold")
        
        runtime_threshold_layout.addWidget(hours_label)
        runtime_threshold_layout.addWidget(self.runtime_threshold_hours)
        runtime_threshold_layout.addSpacing(5)  # Small space between hours and minutes
        runtime_threshold_layout.addWidget(minutes_label)
        runtime_threshold_layout.addWidget(self.runtime_threshold_minutes)
        runtime_threshold_layout.addStretch()
        
        # Create a container for the label and layout
        runtime_container_layout = QHBoxLayout()
        runtime_label = QLabel("Runtime threshold:")
        runtime_label.setToolTip("If prediction scheme estimates that the next run will surpass this total job runtime, it will restart the job before starting with this run.")
        runtime_container_layout.addWidget(runtime_label)
        runtime_container_layout.addLayout(runtime_threshold_layout)
        
        restart_options_layout.addRow(runtime_container_layout)

        # Delete restart files after successful simulation checkbox
        self.delete_restart_files_checkbox = QCheckBox("Delete restart files after successful simulation")
        self.delete_restart_files_checkbox.setToolTip("If checked, adds a command in the .job script to delete the restart_files folder inside each respective simulation folder after successful completion.")
        restart_options_layout.addRow(self.delete_restart_files_checkbox)


        cluster_layout.addRow(self.restart_options_widget)

        self.enable_restart_checkbox.toggled.connect(self.restart_options_widget.setVisible)
        self.restart_options_widget.setVisible(False)  # Initially hidden

        cluster_group.setLayout(cluster_layout)
        scroll_layout.addWidget(cluster_group)

        scroll_layout.addStretch()

    def toggle_multiprocessor_settings(self, checked):
        self.local_processors_label.setVisible(checked)
        self.local_processors_spinbox.setVisible(checked)
        self.local_lammps_executable_label.setVisible(checked)
        self.local_lammps_executable.setVisible(checked)
        if checked:
            self.local_lammps_cmd_label.setText("MPI Command:")
            self.local_lammps_cmd.setText("mpirun")
        else:
            self.local_lammps_cmd_label.setText("Local LAMMPS Command:")
            self.local_lammps_cmd.setText("lmp")
        
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
        # Determine starting directory based on current text field content
        current_path = self.system_path_edit.text().strip()
        if current_path and os.path.exists(current_path):
            # If it's a file, use its directory; if it's a directory, use it directly
            if os.path.isfile(current_path):
                start_dir = os.path.dirname(current_path)
            else:
                start_dir = current_path
        else:
            start_dir = ""

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
            extensions = " ".join([f"*{ext}" for ext in self.data_file_extensions])
            file_path, _ = QFileDialog.getOpenFileName(dialog, "Select Data File", start_dir, f"Data Files ({extensions});;All Files (*)")
            if file_path:
                selected_path = file_path
                select_file = True
                dialog.accept()

        def select_dir_path():
            nonlocal selected_path, select_file
            dir_path = QFileDialog.getExistingDirectory(dialog, "Select Directory", start_dir)
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
        # Determine starting directory based on current text field content
        current_path = self.potential_path_edit.text().strip()
        if current_path and os.path.exists(current_path):
            # If it's a file, use its directory; if it's a directory, use it directly
            if os.path.isfile(current_path):
                start_dir = os.path.dirname(current_path)
            else:
                start_dir = current_path
        else:
            start_dir = ""

        file_path, _ = QFileDialog.getOpenFileName(self, "Select Potential File", start_dir, "All Files (*)")
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
        # Determine starting directory based on current text field content
        current_path = self.output_path_edit.text().strip()
        if current_path and os.path.exists(current_path):
            # If it's a file, use its directory; if it's a directory, use it directly
            if os.path.isfile(current_path):
                start_dir = os.path.dirname(current_path)
            else:
                start_dir = current_path
        else:
            start_dir = ""

        dir_path = QFileDialog.getExistingDirectory(self, "Select Output Directory", start_dir)
        if dir_path:
            self.output_path_edit.setText(dir_path)
    
    def open_lammps_doc(self, command):
        """Open LAMMPS documentation for a specific command"""
        url = QUrl(f"https://docs.lammps.org/{command}.html")
        QDesktopServices.openUrl(url)
    
    def eventFilter(self, obj, event):
        """Event filter to handle key presses for extension input and clicks on groupbox titles"""
        if event.type() == event.Type.KeyPress:
            if obj == self.extensions_input and event.key() in [Qt.Key.Key_Comma, Qt.Key.Key_Space, Qt.Key.Key_Semicolon, Qt.Key.Key_Colon]:
                self._add_data_extension_chip()
                return True # Eat the event
            


        if event.type() == event.Type.MouseButtonPress and event.button() == Qt.MouseButton.LeftButton:
            for widget, doc_command in self.groupbox_doc_links.items():
                if obj == getattr(self, widget, None):
                    self.open_lammps_doc(doc_command)
                    return True
        return super().eventFilter(obj, event)


    

    
    def toggle_trajectory_settings(self, state):
        """Toggle trajectory settings based on checkbox state"""
        enabled = state == Qt.CheckState.Checked.value
        self.traj_freq_spinbox.setEnabled(enabled)
        self.traj_format.setEnabled(enabled)
        self.trj_output_items.setEnabled(enabled)
    
    def toggle_thermo_settings(self, state):
        """Toggle thermo settings based on checkbox state"""
        enabled = state == Qt.CheckState.Checked.value
        self.thermo_freq_spinbox.setEnabled(enabled)
        self.thermo_style.setEnabled(enabled)
    
    def toggle_stress_settings(self, state):
        """Toggle stress settings based on checkbox state"""
        enabled = state == Qt.CheckState.Checked.value
        # Stress calculations don't have additional settings currently, but added for consistency
    



    def toggle_custom_dumps(self, state):
        """Toggle custom dumps settings based on checkbox state"""
        enabled = state == Qt.CheckState.Checked.value
        self.custom_dumps_text.setEnabled(enabled)


    def toggle_field_enabled(self, field_widget, state):
        """Toggle field enabled state and appearance based on checkbox state"""
        enabled = state == Qt.CheckState.Checked.value
        field_widget.setEnabled(enabled)
        
        # Set appearance to make text look grey when disabled
        palette = field_widget.palette()
        if enabled:
            # Reset to default colors
            field_widget.setStyleSheet("")
        else:
            # Apply greyed out appearance
            field_widget.setStyleSheet("color: grey;")

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
        structure_lines = ["Generated Files:"]
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
            "• Run OS-specific local exectuion script (generated based on your OS) local_run_all.sh/.bat to run all simulations locally.\n"
            "• Copy all generated files (or root folder) to the cluster and run ``chmod 755 *`` before calling ./cluster_run_jobs.sh to submit all jobs to the sbatch queuing.\n"
            "\n"
            "• All input .in files are located in their respective study/system folders\n"
            "• Data files and potential iles were copied to the _input_files folder and are referenced in the .in scripts using the relative path (../../_input_files/)\n"
            "• BEWARE! If system/atom data files contained a 'Pair Coeffs' section, it was removed to avoid LAMMPS errors. Make sure to state pair_style followed by the pair_coeff in the potential file!\n"
            "• Output will be generated in each study/system folder"
        )
        layout.addWidget(instructions_text)
        
        # Buttons layout - custom layout to position Open Path button on bottom left
        buttons_layout = QHBoxLayout()
        
        # Open Path button
        open_path_button = QPushButton("Open Path")
        open_path_button.clicked.connect(lambda: self.open_generated_path(result))
        buttons_layout.addWidget(open_path_button)
        
        # Stretch to push OK button to the right
        buttons_layout.addStretch()
        
        # OK button
        ok_button = QPushButton("OK")
        ok_button.clicked.connect(dialog.accept)
        buttons_layout.addWidget(ok_button)
        
        layout.addLayout(buttons_layout)
        
        dialog.setLayout(layout)
        dialog.exec()
    
    def generate_file_structure_text(self, files):
        """Generate text representation of file structure"""
        if not files:
            return "No files generated."
        
        # Build a tree structure from the file paths
        tree = {}
        for file_path in files:
            parts = file_path.split(os.sep)
            current = tree
            for part in parts[:-1]:  # All parts except the last (filename)
                if part not in current:
                    current[part] = {}
                current = current[part]
            
            # Add the filename to the deepest directory
            if None not in current:
                current[None] = []
            current[None].append(parts[-1])  # The filename
        
        def build_tree_text(tree_dict, prefix="", is_last=True):
            lines = []
            items = list(tree_dict.items())
            for i, (key, value) in enumerate(items):
                is_last_item = (i == len(items) - 1)
                
                if key is None:  # This is the list of files in the directory
                    for j, filename in enumerate(value):
                        is_last_file = (j == len(value) - 1) and is_last_item
                        connector = "└── " if is_last_file else "├── "
                        lines.append(f"{prefix}{connector}{filename}")
                else:  # This is a subdirectory
                    connector = "└── " if is_last_item else "├── "
                    lines.append(f"{prefix}{connector}{key}/")
                    extension = "    " if is_last_item else "│   "
                    lines.extend(build_tree_text(value, prefix + extension, is_last_item))
            
            return lines
        
        structure_lines = ["Generated Files:"]
        structure_lines.extend(build_tree_text(tree))
        
        return "\n".join(structure_lines)
    
    def open_generated_path(self, result):
        """Open the output directory specified in the Output Options tab"""
        import subprocess
        import sys
        
        output_path = self.output_path_edit.text()
        
        if output_path and os.path.exists(output_path):
            # Open the folder using the OS-appropriate method
            if sys.platform == "win32":
                # Use subprocess.run with explorer for better reliability on Windows
                subprocess.run(["explorer", os.path.normpath(output_path)])
            elif sys.platform == "darwin":  # macOS
                subprocess.run(["open", output_path])
            else:  # Linux and other Unix-like
                subprocess.run(["xdg-open", output_path])
        else:
            QMessageBox.critical(self, "Error", f"Output path does not exist: {output_path}")
    
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
        
        QLineEdit, QTextEdit, QSpinBox, QDoubleSpinBox {
            border: 1px solid #cccccc;
            border-radius: 3px;
            padding: 2px;
            background-color: white;
            font-size: 12px;
            min-height: 16px;
        }

        QComboBox {
            border: 1px solid #cccccc;
            border-radius: 3px;
            padding: 2px;
            background-color: white;
            font-size: 12px;
            min-height: 16px;
            combobox-popup: 0;
        }
        
        QLineEdit:focus, QTextEdit:focus, QComboBox:focus, QSpinBox:focus, QDoubleSpinBox:focus {
            border: 1px solid #007acc;
        }

        QComboBox QAbstractItemView {
            background-color: white;
            selection-background-color: #007acc;
            selection-color: white;
            border: 1px solid #cccccc;
            outline: none;
        }
        
        /* QCheckBox styling removed to revert to native look for visibility fix */
        
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
    
    def collect_config(self, for_saving=False):
        """Collect configuration from all GUI elements"""
        config = {
            "system": {
                "system_path": self.system_path_edit.text(),
                "data_file_extensions": self.data_file_extensions,

                "use_potential_file": self.use_potential_file.isChecked(),
                "potential_file": self.potential_path_edit.text(),
                "potential_source": self.potential_source_combo.currentText(),
                "potential_position": self.potential_pos_combo.currentText(),
                "potential_content": self.potential_text_edit.toPlainText(),
                
                "atom_style": self.atom_style_combo.currentText(),
                "units": self.units_combo.currentText(),
                "boundary_x": self.boundary_x_combo.currentText(),
                "boundary_y": self.boundary_y_combo.currentText(),
                "boundary_z": self.boundary_z_combo.currentText(),
                "enable_velocity": self.enable_velocity.isChecked(),
                "initial_velocity_seed": self.initial_velocity_seed.value(),
                "damping_factor": self.damping_factor.value(),
                
                "custom_commands": self.custom_commands_edit.toPlainText(),
                "timestep": self.timestep.value()
            },

            "output": {
                "output_path": self.output_path_edit.text(),
                "enable_trajectory": self.enable_trajectory.isChecked(),
                "traj_freq": self.traj_freq_spinbox.value(),
                "traj_format": self.traj_format.currentText(),
                "trj_output_items": self.trj_output_items.text(),
                "enable_thermo": self.enable_thermo.isChecked(),
                "thermo_freq": self.thermo_freq_spinbox.value(),
                "thermo_style": self.thermo_style.text(),
                "eng_strains": [self.eng_strains_chips_layout.itemAt(i).widget().text for i in range(self.eng_strains_chips_layout.count()) if isinstance(self.eng_strains_chips_layout.itemAt(i).widget(), Chip)],
                "cauchy_stresses": [self.cauchy_stresses_chips_layout.itemAt(i).widget().text for i in range(self.cauchy_stresses_chips_layout.count()) if isinstance(self.cauchy_stresses_chips_layout.itemAt(i).widget(), Chip)],
                "averaged_quantities": [self.avg_chips_layout.itemAt(i).widget().text for i in range(self.avg_chips_layout.count()) if isinstance(self.avg_chips_layout.itemAt(i).widget(), Chip)],
                "avg_nevery": self.avg_nevery_spinbox.value(),
                "avg_nrepeat": self.avg_nrepeat_spinbox.value(),
                "add_target_to_thermo": self.add_target_to_thermo_check.isChecked(),

                "custom_dumps": self.custom_dumps_text.toPlainText(),
                "write_data_option": self.write_data_combo.currentText(),
            },
            
            "multistudy": {
                "deform_studies": []
            },
            "job_submission": {
                "local_lammps_cmd": self.local_lammps_cmd.text() or "lmp",
                "local_multiprocessor": self.local_multiprocessor_check.isChecked(),
                "local_processors": self.local_processors_spinbox.value(),
                "local_lammps_executable": self.local_lammps_executable.text() or "lmp_mpi",
                "log_file_name": self.log_file_name.text() or "job.log",
                "os_type": self.os_selection_combo.currentText(),
                "cluster_lammps_cmd": self.cluster_lammps_cmd.text() or "lmp",
                "srun_cmd": self.srun_cmd.text() or "srun",
                "sbatch_cmd": self.sbatch_cmd.text() or "sbatch",
                "module_load": self.module_load_cmd.text() or "lammps",
                "slurm_header": self.slurm_header_text.toPlainText() or '''#!/bin/bash
#SBATCH --job-name=lammps_simulation
#SBATCH --partition=singlenode
#SBATCH --nodes=1
#SBATCH --ntasks-per-node=72
#SBATCH --cpus-per-task=1
#SBATCH --time=24:00:00
#SBATCH --export=NONE
#SBATCH --output=lammps_output_%j.txt
#SBATCH --error=lammps_error_%j.txt''',
                "enable_restart": self.enable_restart_checkbox.isChecked(),
                "restart_freq": self.restart_freq_spinbox.value(),
                "runtime_threshold_hours": self.runtime_threshold_hours.value(),
                "runtime_threshold_minutes": self.runtime_threshold_minutes.value(),
                "delete_restart_files": self.delete_restart_files_checkbox.isChecked()
            }
        }
        
        # Collect deformation studies from the graphical UI
        if hasattr(self, 'deformation_tab_widget'):
            for i in range(self.deformation_tab_widget.tab_widget.count()):
                study_widget = self.deformation_tab_widget.tab_widget.widget(i)
                study_name = self.deformation_tab_widget.tab_widget.tabText(i)

                if study_name == "+":
                    continue
                
                if for_saving or study_widget.is_enabled:
                    # Get the full state from the study widget
                    study_state = study_widget.get_state()
                    study_state["name"] = study_name # Add the name to the state

                    # Pre-process segments to add detailed sine parameters
                    graph = study_widget.graph_widget
                    raw_segments = study_state.get('segments', [])
                    processed_segments = []
                    for i, segment in enumerate(raw_segments):
                        if segment.get('type') == 'sine':
                            sine_params = graph.get_sine_segment_info(i)
                            if sine_params:
                                # Merge original segment info with new calculated params
                                processed_segment = {**segment, **sine_params}
                                processed_segments.append(processed_segment)
                            else:
                                # Handle error or fallback
                                processed_segments.append(segment)
                        else:
                            processed_segments.append(segment)
                    
                    # Replace original segments with processed ones
                    study_state['segments'] = processed_segments
                    
                    config["multistudy"]["deform_studies"].append(study_state)

        return config
    
    def load_settings(self):
        """Load settings from QSettings"""
        try:
            # System settings
            system_path = self.settings.value("system/system_path", "")
            if system_path:
                self.system_path_edit.setText(system_path)

            # Load custom extensions
            extensions = self.settings.value("system/data_file_extensions", [".data"])
            if isinstance(extensions, str): # QSettings might return a string
                extensions = extensions.split(',')

            self.data_file_extensions = []
            # Clear existing chips
            for i in reversed(range(self.chips_layout.count())):
                widget = self.chips_layout.itemAt(i).widget()
                if widget is not None:
                    widget.setParent(None)
            for ext in extensions:
                if ext and ext not in self.data_file_extensions:
                    self.data_file_extensions.append(ext)
                    self._add_chip(ext, self.chips_layout, self._remove_data_extension_chip)


            
            self.use_potential_file.setChecked(self.settings.value("system/use_potential_file", False, type=bool))
            self.potential_path_edit.setText(self.settings.value("system/potential_file", ""))
            self.potential_source_combo.setCurrentText(self.settings.value("system/potential_source", "file"))
            self.potential_pos_combo.setCurrentText(self.settings.value("system/potential_position", "after"))
            self.potential_text_edit.setPlainText(self.settings.value("system/potential_content", ""))
            
            self.atom_style_combo.setCurrentText(self.settings.value("system/atom_style", "atomic"))
            self.units_combo.setCurrentText(self.settings.value("system/units", "metal"))
            self.boundary_x_combo.setCurrentText(self.settings.value("system/boundary_x", "p"))
            self.boundary_y_combo.setCurrentText(self.settings.value("system/boundary_y", "p"))
            self.boundary_z_combo.setCurrentText(self.settings.value("system/boundary_z", "p"))
            self.enable_velocity.setChecked(self.settings.value("system/enable_velocity", True, type=bool))
            self.initial_velocity_seed.setValue(self.settings.value("system/initial_velocity_seed", 12345, type=int))
            self.damping_factor.setValue(self.settings.value("system/damping_factor", 100.0, type=float))
            
            self.damping_factor.setValue(self.settings.value("system/damping_factor", 100.0, type=float))
            
            self.custom_commands_edit.setPlainText(self.settings.value("system/custom_commands", ""))
            self.timestep.setValue(self.settings.value("system/timestep", 0.001, type=float))
            

            
            # Output settings
            self.output_path_edit.setText(self.settings.value("output/output_path", ""))
            self.enable_trajectory.setChecked(self.settings.value("output/enable_trajectory", True, type=bool))
            self.traj_freq_spinbox.setValue(self.settings.value("output/traj_freq", 100, type=int))
            self.traj_format.setCurrentText(self.settings.value("output/traj_format", "lammpstrj"))
            self.trj_output_items.setText(self.settings.value("output/trj_output_items", "id type x y z fx fy fz"))
            self.enable_thermo.setChecked(self.settings.value("output/enable_thermo", True, type=bool))
            self.thermo_freq_spinbox.setValue(self.settings.value("output/thermo_freq", 100, type=int))
            self.thermo_style.setText(self.settings.value("output/thermo_style", "step etotal pe ke epair ebond evdwl ecoul elong temp press pxx pyy pzz pxy pxz pyz lx ly lz density"))
            
            # Load new chip fields
            self.apply_chips_from_settings('output/eng_strains', self.eng_strains_chips_layout, self.all_eng_strains, self.eng_strains_combo, self.remove_eng_strain_chip)
            self.apply_chips_from_settings('output/cauchy_stresses', self.cauchy_stresses_chips_layout, self.all_cauchy_stresses, self.cauchy_stresses_combo, self.remove_cauchy_stress_chip)
            self.apply_chips_from_settings('output/averaged_quantities', self.avg_chips_layout, self.all_avg_quantities, self.averaged_quantities_combo, self.remove_averaged_quantity_chip)
            self._update_averaging_spinboxes_state()

            self.avg_nevery_spinbox.setValue(self.settings.value('output/avg_nevery', 10, type=int))
            self.avg_nrepeat_spinbox.setValue(self.settings.value('output/avg_nrepeat', 100, type=int))

            self.add_target_to_thermo_check.setChecked(self.settings.value("output/add_target_to_thermo", False, type=bool))


            self.custom_dumps_text.setPlainText(self.settings.value("output/custom_dumps", ""))
            # For backward compatibility, handle the old boolean setting
            if self.settings.contains("output/write_data_option"):
                self.write_data_combo.setCurrentText(self.settings.value("output/write_data_option", "Never", type=str))
            elif self.settings.contains("output/enable_write_data"):
                if self.settings.value("output/enable_write_data", False, type=bool):
                    self.write_data_combo.setCurrentText("At the end of the simulation")
                else:
                    self.write_data_combo.setCurrentText("Never")

            # Job submission settings
            self.local_multiprocessor_check.setChecked(self.settings.value("job_submission/local_multiprocessor", False, type=bool))
            self.local_processors_spinbox.setValue(self.settings.value("job_submission/local_processors", 4, type=int))
            self.local_lammps_executable.setText(self.settings.value("job_submission/local_lammps_executable", "lmp_mpi"))
            self.os_selection_combo.setCurrentText(self.settings.value("job_submission/os_type", "Auto-detect"))
            self.local_lammps_cmd.setText(self.settings.value("job_submission/local_lammps_cmd", ""))
            self.log_file_name.setText(self.settings.value("job_submission/log_file_name", "job.log"))
            self.cluster_lammps_cmd.setText(self.settings.value("job_submission/cluster_lammps_cmd", ""))
            self.srun_cmd.setText(self.settings.value("job_submission/srun_cmd", ""))
            self.sbatch_cmd.setText(self.settings.value("job_submission/sbatch_cmd", ""))
            self.module_load_cmd.setText(self.settings.value("job_submission/module_load", ""))
            self.slurm_header_text.setPlainText(self.settings.value("job_submission/slurm_header", ""))

            # Restart settings
            enable_restart = self.settings.value("job_submission/enable_restart", False, type=bool)
            self.enable_restart_checkbox.setChecked(enable_restart)
            self.restart_options_widget.setVisible(enable_restart)
            self.restart_freq_spinbox.setValue(self.settings.value("job_submission/restart_freq", 100000, type=int))
            self.runtime_threshold_hours.setValue(self.settings.value("job_submission/runtime_threshold_hours", 23, type=int))
            self.runtime_threshold_minutes.setValue(self.settings.value("job_submission/runtime_threshold_minutes", 45, type=int))
            self.delete_restart_files_checkbox.setChecked(self.settings.value("job_submission/delete_restart_files", False, type=bool))
            
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

                # Enable batch loading mode to optimize performance
                self.deformation_tab_widget._batch_loading = True

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

                        # Restore the state of the study widget, blocking signals to prevent premature updates
                        study_widget.blockSignals(True)
                        study_widget.set_state(study)
                        study_widget.blockSignals(False)
                else:
                    # No studies in settings, or settings were corrupted. Create a default one.
                    self.deformation_tab_widget._add_study(is_first=True)

                # Disable batch loading mode and perform a single update
                self.deformation_tab_widget._batch_loading = False
                self.deformation_tab_widget.update_summaries()
                self.deformation_tab_widget._update_tab_colors()

                # After loading all tabs, ensure the mode dropdown reflects the current tab's mode
                current_widget = self.deformation_tab_widget.tab_widget.currentWidget()
                if current_widget:
                    self.deformation_tab_widget.mode_combo.blockSignals(True)
                    self.deformation_tab_widget.mode_combo.setCurrentText(current_widget.mode)
                    self.deformation_tab_widget.mode_combo.blockSignals(False)

                # Restore active deformation tab
                deform_tab_index = self.settings.value("gui/active_deformation_tab_index", 0, type=int)
                if 0 <= deform_tab_index < self.deformation_tab_widget.tab_widget.count():
                    self.deformation_tab_widget.tab_widget.setCurrentIndex(deform_tab_index)

                # Plus tab is handled by the corner widget button, no need to add it here
                pass

        except Exception as e:
            print(f"Error loading settings: {e}")

        # Restore active main tab at the very end
        main_tab_index = self.settings.value("gui/active_main_tab_index", 0, type=int)
        if 0 <= main_tab_index < self.tab_widget.count():
            self.tab_widget.setCurrentIndex(main_tab_index)
            
        self._update_output_tab_visibility()


    def apply_chips_from_settings(self, settings_key, chips_layout, all_items_list, combo_box, remove_slot):
        """Helper to load chip selections from QSettings."""
        selected_items = self.settings.value(settings_key, [])
        if isinstance(selected_items, str): # QSettings can return a string
            selected_items = [q.strip() for q in selected_items.split(',') if q.strip()]

        while chips_layout.count():
            child = chips_layout.takeAt(0)
            if child.widget():
                child.widget().deleteLater()
        
        combo_box.clear()
        combo_box.addItem("Add quantity...")
        
        available_items = [q for q in all_items_list if q not in selected_items]
        available_items.sort()
        combo_box.addItems(available_items)
        
        for item in selected_items:
            chip = Chip(item)
            chip.removed.connect(remove_slot)
            chips_layout.addWidget(chip)
    
    def save_settings(self):
        """Save settings to QSettings"""
        try:
            config = self.collect_config(for_saving=True)
            
            # Save system settings
            self.settings.setValue("system/system_path", config["system"]["system_path"])
            self.settings.setValue("system/data_file_extensions", ",".join(config["system"]["data_file_extensions"]))

            self.settings.setValue("system/use_potential_file", config["system"]["use_potential_file"])
            self.settings.setValue("system/potential_file", config["system"]["potential_file"])
            self.settings.setValue("system/potential_source", config["system"]["potential_source"])
            self.settings.setValue("system/potential_position", config["system"]["potential_position"])
            self.settings.setValue("system/potential_content", config["system"]["potential_content"])
            
            self.settings.setValue("system/atom_style", config["system"]["atom_style"])
            self.settings.setValue("system/units", config["system"]["units"])
            self.settings.setValue("system/boundary_x", config["system"]["boundary_x"])
            self.settings.setValue("system/boundary_y", config["system"]["boundary_y"])
            self.settings.setValue("system/boundary_z", config["system"]["boundary_z"])
            self.settings.setValue("system/enable_velocity", config["system"]["enable_velocity"])
            self.settings.setValue("system/initial_velocity_seed", config["system"]["initial_velocity_seed"])
            self.settings.setValue("system/damping_factor", config["system"]["damping_factor"])
            
            self.settings.setValue("system/custom_commands", config["system"]["custom_commands"])
            self.settings.setValue("system/timestep", config["system"]["timestep"])
            

            
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
            
            # Save active tab indices
            self.settings.setValue("gui/active_main_tab_index", self.tab_widget.currentIndex())
            if hasattr(self, 'deformation_tab_widget'):
                self.settings.setValue("gui/active_deformation_tab_index", self.deformation_tab_widget.tab_widget.currentIndex())

        except Exception as e:
            print(f"Error saving settings: {e}")
    
    def generate_scripts(self):
        """Generate LAMMPS scripts based on current configuration"""
        if not self.validate_paths():
            return

        try:
            # Collect configuration with error handling
            try:
                # For script generation, only collect enabled studies
                config = self.collect_config(for_saving=False)
                
                # Also collect full configuration (for saving) to preserve all studies 
                full_config = self.collect_config(for_saving=True)
            except Exception as e:
                QMessageBox.critical(self, "Error", f"Error collecting configuration: {str(e)}")
                return
            
            # Validate configuration
            if not config.get("system", {}).get("system_path"):
                QMessageBox.warning(self, "Warning", "Please select a system path.")
                return
            
            deform_studies = config.get("multistudy", {}).get("deform_studies", [])
            if not deform_studies:
                QMessageBox.warning(self, "Warning", "Please define or activate at least one study.")
                return
            
            # Validate system path exists
            system_path = config["system"]["system_path"]
            if not os.path.exists(system_path):
                QMessageBox.critical(self, "Error", f"System path does not exist: {system_path}")
                return

            # Check if averaged quantities are present and validate that all handles are integer multiples of thermo frequency
            averaged_quantities = config.get("output", {}).get("averaged_quantities", [])
            thermo_freq = config.get("output", {}).get("thermo_freq", 100)
            avg_nevery = config.get("output", {}).get("avg_nevery", 1)
            
            if averaged_quantities:
                # Check if all handles in all studies are integer multiples of thermo frequency
                invalid_studies = []
                
                for study in deform_studies:
                    study_name = study.get("name", "unnamed")
                    data_points = study.get("data_points", [])
                    
                    # Extract time steps (x-coordinates) from data points
                    time_steps = [int(point[0]) for point in data_points]
                    
                    # Check if all time steps are integer multiples of thermo_freq
                    invalid_steps = []
                    for step in time_steps:
                        if step % thermo_freq != 0:
                            invalid_steps.append(step)
                    
                    # Check if avg_nevery is a divisor of thermo_freq
                    if thermo_freq % avg_nevery != 0:
                        invalid_steps.append(f"avg_nevery={avg_nevery}")
                    
                    if invalid_steps:
                        invalid_studies.append({
                            "name": study_name,
                            "invalid_steps": invalid_steps
                        })

                if invalid_studies:
                    # Create a detailed error message
                    error_message = "Averaged quantities are present but some handles are not integer multiples of the thermo frequency.\n\n"
                    error_message += "Invalid studies:\n"
                    
                    for study in invalid_studies:
                        error_message += f"- {study['name']}: "
                        invalid_items = []
                        for item in study['invalid_steps']:
                            if isinstance(item, str):  # For avg_nevery issue
                                invalid_items.append(item)
                            else:  # For time step issues
                                invalid_items.append(str(item))
                        error_message += f"{', '.join(invalid_items)}\n"
                    
                    error_message += "\nPlease either:\n"
                    error_message += "1. Shift the handles to integer multiples of the thermo frequency,\n"
                    error_message += "2. Change the thermo frequency accordingly,\n"
                    error_message += "3. Remove all quantities from the 'Average' line in the Thermo Output Settings, or\n"
                    error_message += "4. Delete or right click on the respective sutdy tab to deactivate it."
                    
                    QMessageBox.critical(self, "Validation Error", error_message)
                    return

            # Instantiate Generator temporarily to check specific files (Potential, Data files integrity)
            # This must happen BEFORE asking to delete files.
            if ScriptGen:
                temp_generator = ScriptGen(config)
                val_result = temp_generator.validate_configuration()
                
                if not val_result["success"]:
                    QMessageBox.critical(self, "Validation Error", val_result["message"])
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
                    
                    # Save the full configuration (including disabled studies) by temporarily replacing the method
                    original_save_settings = generator.save_settings_to_json
                    def save_all_studies_settings(root_simulation_dir):
                        return self._save_full_config_for_generator(full_config, root_simulation_dir)
                    generator.save_settings_to_json = save_all_studies_settings
                    
                    result = generator.generate_all_scripts()
                    
                    # Restore the original method if needed
                    generator.save_settings_to_json = original_save_settings
                    
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
            # Determine starting directory based on Output Path field content
            output_path = self.output_path_edit.text().strip()
            if output_path and os.path.exists(output_path):
                # If output path is a file, use its directory; if it's a directory, use it directly
                if os.path.isfile(output_path):
                    start_dir = os.path.dirname(output_path)
                else:
                    start_dir = output_path
            else:
                start_dir = ""

            file_path, _ = QFileDialog.getSaveFileName(self, "Save Configuration", start_dir, "JSON Files (*.json);;All Files (*)")
            if file_path:
                config = self.collect_config(for_saving=True)
                with open(file_path, 'w') as f:
                    json.dump(config, f, indent=2)
                QMessageBox.information(self, "Success", f"Configuration saved to {file_path}")
        except Exception as e:
            QMessageBox.critical(self, "Error", f"Error saving configuration: {str(e)}")
    
    def load_configuration(self):
        """Load configuration from file"""
        try:
            # Determine starting directory based on Output Path field content
            output_path = self.output_path_edit.text().strip()
            if output_path and os.path.exists(output_path):
                # If output path is a file, use its directory; if it's a directory, use it directly
                if os.path.isfile(output_path):
                    start_dir = os.path.dirname(output_path)
                else:
                    start_dir = output_path
            else:
                start_dir = ""

            file_path, _ = QFileDialog.getOpenFileName(self, "Load Configuration", start_dir, "JSON Files (*.json);;All Files (*)")
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

                # Load custom extensions
                extensions = system.get("data_file_extensions", [".data"])
                self.data_file_extensions = []
                # Clear existing chips
                for i in reversed(range(self.chips_layout.count())):
                    self.chips_layout.itemAt(i).widget().setParent(None)
                for ext in extensions:
                    if ext not in self.data_file_extensions:
                        self.data_file_extensions.append(ext)
                        self._add_chip(ext, self.chips_layout, self._remove_data_extension_chip)



                self.use_potential_file.setChecked(system.get("use_potential_file", False))
                self.potential_path_edit.setText(system.get("potential_file", ""))
                self.potential_source_combo.setCurrentText(system.get("potential_source", "file"))
                self.potential_pos_combo.setCurrentText(system.get("potential_position", "after"))
                self.potential_text_edit.setPlainText(system.get("potential_content", ""))
                
                self.atom_style_combo.setCurrentText(system.get("atom_style", "atomic"))
                self.units_combo.setCurrentText(system.get("units", "metal"))
                self.boundary_x_combo.setCurrentText(system.get("boundary_x", "p"))
                self.boundary_y_combo.setCurrentText(system.get("boundary_y", "p"))
                self.boundary_z_combo.setCurrentText(system.get("boundary_z", "p"))
                self.enable_velocity.setChecked(system.get("enable_velocity", True))
                self.initial_velocity_seed.setValue(system.get("initial_velocity_seed", 12345))
                self.damping_factor.setValue(system.get("damping_factor", 100.0))
                
                self.custom_commands_edit.setPlainText(system.get("custom_commands", ""))
                self.timestep.setValue(system.get("timestep", 0.001))



            # Output configuration
            if "output" in config:
                output = config["output"]
                self.output_path_edit.setText(output.get("output_path", ""))
                self.enable_trajectory.setChecked(output.get("enable_trajectory", True))
                self.traj_freq_spinbox.setValue(output.get("traj_freq", 100))
                self.traj_format.setCurrentText(output.get("traj_format", "lammpstrj"))
                self.trj_output_items.setText(output.get("trj_output_items", "id type x y z fx fy fz"))
                self.enable_thermo.setChecked(output.get("enable_thermo", True))
                self.thermo_freq_spinbox.setValue(output.get("thermo_freq", 100))
                self.thermo_style.setText(output.get("thermo_style", "step etotal pe ke epair ebond evdwl ecoul elong temp press pxx pyy pzz pxy pxz pyz lx ly lz density"))
                
                self.apply_chips_from_config(output, 'eng_strains', self.eng_strains_chips_layout, self.all_eng_strains, self.eng_strains_combo, self.remove_eng_strain_chip)
                self.apply_chips_from_config(output, 'cauchy_stresses', self.cauchy_stresses_chips_layout, self.all_cauchy_stresses, self.cauchy_stresses_combo, self.remove_cauchy_stress_chip)
                self.apply_chips_from_config(output, 'averaged_quantities', self.avg_chips_layout, self.all_avg_quantities, self.averaged_quantities_combo, self.remove_averaged_quantity_chip)

                self.avg_nevery_spinbox.setValue(output.get('avg_nevery', 10))
                self.avg_nrepeat_spinbox.setValue(output.get('avg_nrepeat', 100))
                self.add_target_to_thermo_check.setChecked(output.get("add_target_to_thermo", False))

                self.custom_dumps_text.setPlainText(output.get("custom_dumps", ""))
                # For backward compatibility, handle the old boolean setting
                if "write_data_option" in output:
                    self.write_data_combo.setCurrentText(output.get("write_data_option", "Never"))
                elif "enable_write_data" in output:
                    if output.get("enable_write_data", False):
                        self.write_data_combo.setCurrentText("At the end of the simulation")
                    else:
                        self.write_data_combo.setCurrentText("Never")

            # Job submission settings
            if "job_submission" in config:
                job_submission = config["job_submission"]
                self.local_multiprocessor_check.setChecked(job_submission.get("local_multiprocessor", False))
                self.local_processors_spinbox.setValue(job_submission.get("local_processors", 4))
                self.local_lammps_executable.setText(job_submission.get("local_lammps_executable", "lmp_mpi"))
                self.local_lammps_cmd.setText(job_submission.get("local_lammps_cmd", "lmp"))
                self.log_file_name.setText(job_submission.get("log_file_name", "job.log"))
                self.os_selection_combo.setCurrentText(job_submission.get("os_type", "Auto-detect"))
                self.cluster_lammps_cmd.setText(job_submission.get("cluster_lammps_cmd", "lmp"))
                self.srun_cmd.setText(job_submission.get("srun_cmd", "srun"))
                self.sbatch_cmd.setText(job_submission.get("sbatch_cmd", "sbatch"))
                self.module_load_cmd.setText(job_submission.get("module_load", "lammps"))
                self.slurm_header_text.setPlainText(job_submission.get("slurm_header", ""))
                # Load restart settings
                enable_restart = job_submission.get("enable_restart", False)
                self.enable_restart_checkbox.setChecked(enable_restart)
                self.restart_options_widget.setVisible(enable_restart)
                self.restart_freq_spinbox.setValue(job_submission.get("restart_freq", 100000))
                self.runtime_threshold_hours.setValue(job_submission.get("runtime_threshold_hours", 23))
                self.runtime_threshold_minutes.setValue(job_submission.get("runtime_threshold_minutes", 45))
                self.delete_restart_files_checkbox.setChecked(job_submission.get("delete_restart_files", False))

            # Multi-study configuration
            if "multistudy" in config and hasattr(self, 'deformation_tab_widget'):
                multistudy = config["multistudy"]
                studies = multistudy.get("deform_studies", [])

                # Clear existing tabs
                while self.deformation_tab_widget.tab_widget.count() > 0:
                    self.deformation_tab_widget.tab_widget.removeTab(0)

                # Enable batch loading mode to optimize performance
                self.deformation_tab_widget._batch_loading = True

                if studies:
                    for i, study_data in enumerate(studies):
                        self.deformation_tab_widget._add_study(is_first=(i==0))
                        study_widget = self.deformation_tab_widget.tab_widget.widget(i)
                        self.deformation_tab_widget.tab_widget.setTabText(i, study_data.get("name", f"Study {i+1}"))

                        # Restore the state of the study widget, blocking signals
                        study_widget.blockSignals(True)
                        study_widget.set_state(study_data)
                        study_widget.blockSignals(False)
                else:
                    # if no studies, create a default one
                    self.deformation_tab_widget._add_study(is_first=True)

                # Disable batch loading mode and perform a single update
                self.deformation_tab_widget._batch_loading = False
                self.deformation_tab_widget.update_summaries()
                self.deformation_tab_widget._update_tab_colors()

                # After loading all tabs, ensure the mode dropdown reflects the current tab's mode
                current_widget = self.deformation_tab_widget.tab_widget.currentWidget()
                if current_widget:
                    self.deformation_tab_widget.mode_combo.blockSignals(True)
                    self.deformation_tab_widget.mode_combo.setCurrentText(current_widget.mode)
                    self.deformation_tab_widget.mode_combo.blockSignals(False)
        except Exception as e:
            print(f"Error applying configuration: {e}")
        
        self._update_output_tab_visibility()

    def apply_chips_from_config(self, config_section, key, chips_layout, all_items_list, combo_box, remove_slot):
        """Helper to load chip selections from a config dictionary."""
        selected_items = config_section.get(key, [])
        
        while chips_layout.count():
            child = chips_layout.takeAt(0)
            if child.widget():
                child.widget().deleteLater()
        
        combo_box.clear()
        combo_box.addItem("Add quantity...")
        
        available_items = [q for q in all_items_list if q not in selected_items]
        available_items.sort()
        combo_box.addItems(available_items)
        
        for item in selected_items:
            chip = Chip(item)
            chip.removed.connect(remove_slot)
            chips_layout.addWidget(chip)

    def _save_full_config_for_generator(self, full_config, root_simulation_dir):
        """Save the full configuration (including disabled studies) for the script generator"""
        try:
            import json
            import os
            settings_file = os.path.join(root_simulation_dir, "lammps_settings.json")
            with open(settings_file, 'w') as f:
                json.dump(full_config, f, indent=2)
            return {"success": True, "message": f"Settings saved to: {settings_file}"}
        except Exception as e:
            return {"success": False, "message": f"Error saving settings: {str(e)}"}


def main():
    """Main function to run the application"""
    app = QApplication(sys.argv)
    app.setStyle('Fusion')
    
    # Create and show the main window
    window = LammpsGui()
    window.show()
    
    # Run the application
    sys.exit(app.exec())

if __name__ == "__main__":
    main()