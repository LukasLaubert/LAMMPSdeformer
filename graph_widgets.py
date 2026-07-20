import sys
import math
import re
import copy
from PyQt6.QtWidgets import (
    QApplication, QMainWindow, QWidget, QVBoxLayout, QHBoxLayout,
    QLabel, QSpinBox, QDialog, QDoubleSpinBox, QMenu, QCheckBox,
    QTextEdit, QDialogButtonBox, QFormLayout, QPushButton, QInputDialog,
    QTabWidget, QComboBox, QScrollArea, QMessageBox, QStackedWidget, QListWidget, QSizePolicy
)
from PyQt6.QtCore import Qt, QPointF, QRectF, pyqtSignal, QTimer, QUrl
from PyQt6.QtGui import QPainter, QPen, QBrush, QColor, QFont, QAction, QFontMetrics, QKeySequence, QPixmap, QDesktopServices, QCursor, QPolygonF

# --- Sci-Notation SpinBox ---
class SciNotationDoubleSpinBox(QDoubleSpinBox):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.setDecimals(10) # Allow high precision

    def textFromValue(self, value):
        return f"{value:.4e}"

    def valueFromText(self, text):
        try:
            return float(text)
        except ValueError:
            return self.value()

# --- Professional Style & Data ---
STYLE_BACKGROUND = QColor("#FFFFFF"); STYLE_FRAME = QColor("#ADB5BD"); STYLE_LINE = QColor("#007BFF"); STYLE_HANDLE = QColor("#007BFF")
STYLE_HANDLE_OUTLINE = QColor("#FFFFFF"); STYLE_TEXT_PRIMARY = QColor("#212529"); STYLE_TEXT_SECONDARY = QColor("#6C757D"); STYLE_SLOPE_TEXT = QColor("#E8590C")
HANDLE_RADIUS = 7
LAMMPS_UNITS = {"lj": "tau", "real": "fs", "metal": "ps", "si": "s", "cgs": "s", "electron": "fs", "micro": "μs", "nano": "ns"}

# --- Clickable Label for Docs ---
class ClickableLabel(QLabel):
    """A QLabel that opens one or more URLs when clicked."""
    def __init__(self, urls, parent=None):
        super().__init__(parent)
        if not isinstance(urls, list):
            urls = [urls]
        self.urls = urls
        self.setCursor(QCursor(Qt.CursorShape.PointingHandCursor))

    def mousePressEvent(self, event):
        if event.button() == Qt.MouseButton.LeftButton:
            for url in self.urls:
                QDesktopServices.openUrl(url)
        super().mousePressEvent(event)

def create_info_icon_label(urls, tooltip, color_name):
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
    
    label = ClickableLabel(urls)
    label.setPixmap(pixmap)
    label.setFixedSize(18, 18)
    label.setToolTip(tooltip)
    
    return label

# --- Custom Dialogs ---
class PresetDialog(QDialog):
    def __init__(self, last_scheme, last_staircase_params, last_cyclic_params, last_sinusoidal_params, max_steps, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Generate Scheme")
        self.max_steps = max_steps
        self.scheme_combo = QComboBox()
        schemes = ["Staircase Loading", "Cyclic Loading"]
        is_temp_mode = self.parent() and self.parent().mode == 'Temperature'
        if not is_temp_mode:
            schemes.append("Sinusoidal Loading")
        self.scheme_combo.addItems(schemes)
        self.scheme_combo.setCurrentText(last_scheme)
        self.scheme_combo.currentIndexChanged.connect(self._update_options)
        self.stacked_widget = QStackedWidget()
        self._create_staircase_options(last_staircase_params)
        self._create_cyclic_options(last_cyclic_params)
        self._create_sinusoidal_options(last_sinusoidal_params)
        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel)
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        layout = QFormLayout(self)
        layout.addRow("Scheme Type:", self.scheme_combo)
        layout.addWidget(self.stacked_widget)
        layout.addWidget(buttons)
        self._update_options(self.scheme_combo.currentIndex())

    def _create_staircase_options(self, params):
        self.staircase_widget = QWidget()
        layout = QFormLayout(self.staircase_widget)

        self.staircase_equilibration_steps = QSpinBox()
        self.staircase_equilibration_steps.setRange(0, self.max_steps - 1 if self.max_steps > 0 else 0)
        self.staircase_equilibration_steps.setValue(params.get('equilibration_steps', 0))
        layout.addRow("Equilibration timesteps:", self.staircase_equilibration_steps)

        self.staircase_cycles = QSpinBox()
        self.staircase_cycles.setRange(1, 1000)
        self.staircase_cycles.setValue(params['cycles'])
        self.staircase_factor = QDoubleSpinBox()
        self.staircase_factor.setRange(0.0, 1000.0)
        self.staircase_factor.setValue(params['factor'])
        self.staircase_direction = QComboBox()

        is_temp_mode = self.parent() and self.parent().mode == 'Temperature'
        direction_items = ["Heating", "Cooling"] if is_temp_mode else ["Tension", "Compression"]
        self.staircase_direction.addItems(direction_items)

        current_direction = params['direction']
        if is_temp_mode:
            if current_direction == "Tension":
                current_direction = "Heating"
            elif current_direction == "Compression":
                current_direction = "Cooling"

        if current_direction not in direction_items:
            current_direction = direction_items[0]

        self.staircase_direction.setCurrentText(current_direction)

        layout.addRow("Number of Stairs:", self.staircase_cycles)
        layout.addRow("Hold Time Factor:", self.staircase_factor)
        layout.addRow("Direction:", self.staircase_direction)
        self.stacked_widget.addWidget(self.staircase_widget)

    def _create_cyclic_options(self, params):
        self.cyclic_widget = QWidget()
        layout = QFormLayout(self.cyclic_widget)

        self.cyclic_equilibration_steps = QSpinBox()
        self.cyclic_equilibration_steps.setRange(0, self.max_steps - 1 if self.max_steps > 0 else 0)
        self.cyclic_equilibration_steps.setValue(params.get('equilibration_steps', 0))
        layout.addRow("Equilibration timesteps:", self.cyclic_equilibration_steps)

        self.cyclic_cycles = QSpinBox()
        self.cyclic_cycles.setRange(1, 1000)
        self.cyclic_cycles.setValue(params['cycles'])
        self.cyclic_relax_factor = QDoubleSpinBox()
        self.cyclic_relax_factor.setRange(0.0, 1000.0)
        self.cyclic_relax_factor.setValue(params['relax_factor'])
        self.cyclic_start = QComboBox()

        is_temp_mode = self.parent() and self.parent().mode == 'Temperature'
        start_items = ["Heating", "Cooling"] if is_temp_mode else ["Tension", "Compression"]
        self.cyclic_start.addItems(start_items)

        current_start = params['start_with']
        if is_temp_mode:
            if current_start == "Tension":
                current_start = "Heating"
            elif current_start == "Compression":
                current_start = "Cooling"

        if current_start not in start_items:
            current_start = start_items[0]

        self.cyclic_start.setCurrentText(current_start)

        layout.addRow("Number of Cycles:", self.cyclic_cycles)
        layout.addRow("Relaxation (multiple of 1 cycle):", self.cyclic_relax_factor)
        layout.addRow("Start With:", self.cyclic_start)
        self.stacked_widget.addWidget(self.cyclic_widget)

    def _create_sinusoidal_options(self, params):
        self.sinusoidal_widget = QWidget()
        layout = QFormLayout(self.sinusoidal_widget)

        self.sinusoidal_equilibration_steps = QSpinBox()
        self.sinusoidal_equilibration_steps.setRange(0, self.max_steps - 1 if self.max_steps > 0 else 0)
        self.sinusoidal_equilibration_steps.setValue(params.get('equilibration_steps', 0))
        layout.addRow("Equilibration timesteps:", self.sinusoidal_equilibration_steps)

        self.sinusoidal_cycles = QDoubleSpinBox()
        self.sinusoidal_cycles.setRange(0.25, 1000.0)
        self.sinusoidal_cycles.setSingleStep(0.25)
        self.sinusoidal_cycles.setValue(params.get('num_cycles', 1.0))
        layout.addRow("Number of cycles:", self.sinusoidal_cycles)

        self.sinusoidal_relax_factor = QDoubleSpinBox()
        self.sinusoidal_relax_factor.setRange(0, 1000)
        self.sinusoidal_relax_factor.setValue(params.get('relax_factor', 0.0))
        layout.addRow("Relaxation (multiple of 1 cycle):", self.sinusoidal_relax_factor)

        self.sinusoidal_scheme = QComboBox()
        self.sinusoidal_scheme.addItems([
            "Alternating (tensile start)",
            "Alternating (compressive start)",
            "Pulsating tensile load",
            "Pulsating compressive load"
        ])
        self.sinusoidal_scheme.setCurrentText(params.get('scheme', 'Alternating (tensile start)'))
        layout.addRow("Loading scheme:", self.sinusoidal_scheme)

        self.stacked_widget.addWidget(self.sinusoidal_widget)

    def _update_options(self, index):
        self.stacked_widget.setCurrentIndex(index)

    def get_parameters(self):
        scheme_index = self.stacked_widget.currentIndex()
        scheme = self.scheme_combo.itemText(scheme_index)
        if scheme == "Staircase Loading":
            return scheme, {
                'equilibration_steps': self.staircase_equilibration_steps.value(),
                'cycles': self.staircase_cycles.value(),
                'factor': self.staircase_factor.value(),
                'direction': self.staircase_direction.currentText()
            }
        elif scheme == "Cyclic Loading":
            return scheme, {
                'equilibration_steps': self.cyclic_equilibration_steps.value(),
                'cycles': self.cyclic_cycles.value(),
                'relax_factor': self.cyclic_relax_factor.value(),
                'start_with': self.cyclic_start.currentText()
            }
        elif scheme == "Sinusoidal Loading":
            return scheme, {
                'equilibration_steps': self.sinusoidal_equilibration_steps.value(),
                'num_cycles': self.sinusoidal_cycles.value(),
                'relax_factor': self.sinusoidal_relax_factor.value(),
                'scheme': self.sinusoidal_scheme.currentText()
            }
        return None, None

class SlopeEditDialog(QDialog):
    def __init__(self, p1, p2, timestep, time_unit, parent=None):
        super().__init__(parent)
        is_temp_mode = parent and parent.mode == 'Temperature'
        self.setWindowTitle("Edit Temperature Change" if is_temp_mode else "Edit Slope / Strain Rate")
        self._timestep = timestep
        self._dx_steps = p2.x() - p1.x()
        self.slope_box = SciNotationDoubleSpinBox(); self.rate_box = SciNotationDoubleSpinBox()
        initial_slope = (p2.y() - p1.y()) / self._dx_steps if self._dx_steps != 0 else 0
        for box, val in [(self.slope_box, initial_slope), (self.rate_box, 0)]: box.setRange(-1e9, 1e9); box.setSingleStep(max(1e-5, abs(val) * 0.02))
        self.slope_box.setValue(initial_slope); self.slope_box.valueChanged.connect(self._slope_changed); self.rate_box.valueChanged.connect(self._rate_changed); self._slope_changed(initial_slope)
        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel); buttons.accepted.connect(self.accept); buttons.rejected.connect(self.reject)
        layout = QFormLayout(self)
        y_unit = parent.get_y_unit() if parent else "ε"
        slope_label = f"Slope ({y_unit}/step):"
        rate_label = f"Temperature Change Rate ({y_unit}/t):" if is_temp_mode else f"Strain Rate ({y_unit}/t):"
        layout.addRow(slope_label, self.slope_box)
        
        rate_layout = QHBoxLayout()
        rate_layout.addWidget(self.rate_box)
        rate_layout.addWidget(QLabel(f"1/{time_unit}"))
        layout.addRow(rate_label, rate_layout)

        layout.addWidget(buttons)
    def _slope_changed(self, val): self.rate_box.blockSignals(True); dx_time = self._dx_steps * self._timestep; self.rate_box.setValue(val * self._dx_steps / dx_time if dx_time != 0 else 0); self.rate_box.blockSignals(False); self.slope_box.setSingleStep(max(1e-5, abs(val) * 0.02))
    def _rate_changed(self, val): self.slope_box.blockSignals(True); dx_time = self._dx_steps * self._timestep; self.slope_box.setValue(val * dx_time / self._dx_steps if self._dx_steps != 0 else 0); self.slope_box.blockSignals(False); self.rate_box.setSingleStep(max(1e-5, abs(val) * 0.02))
    def get_slope(self): return self.slope_box.value()

class TimeEditDialog(QDialog):
    def __init__(self, step, timestep, max_step, parent=None):
        super().__init__(parent); self.setWindowTitle("Edit Time"); self._timestep = timestep
        self.step_box = QSpinBox(); self.step_box.setRange(0, max_step); self.step_box.setValue(int(step)); self.step_box.setSingleStep(max(1, int(step*0.02) if step > 0 else 1))
        self.time_box = QDoubleSpinBox(); self.time_box.setRange(0, max_step * timestep); self.time_box.setValue(step * timestep); self.time_box.setDecimals(3); self.time_box.setSuffix(" s"); self.time_box.setSingleStep(max(0.01, self.time_box.value()*0.02) if self.time_box.value() > 0 else 0.01)
        self.step_box.valueChanged.connect(self._step_changed); self.time_box.valueChanged.connect(self._time_changed)
        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel); buttons.accepted.connect(self.accept); buttons.rejected.connect(self.reject)
        layout = QFormLayout(self); layout.addRow("Time Step:", self.step_box); layout.addRow("Time (s):", self.time_box); layout.addWidget(buttons)
    def _step_changed(self, v): self.time_box.blockSignals(True); self.time_box.setValue(v * self._timestep); self.time_box.blockSignals(False); self.step_box.setSingleStep(max(1, int(v*0.02) if v > 0 else 1))
    def _time_changed(self, v): self.step_box.blockSignals(True); self.step_box.setValue(round(v / self._timestep)); self.step_box.blockSignals(False); self.time_box.setSingleStep(max(0.01, v*0.02) if v > 0 else 0.01)
    def get_step(self): return self.step_box.value()

class CoordinateDialog(QDialog):
    def __init__(self, index, step, strain, max_step, min_strain, max_strain, parent=None):
        super().__init__(parent)
        is_temp_mode = parent and parent.mode == 'Temperature'
        self.setWindowTitle("Set Time and Temperature" if is_temp_mode else "Set Coordinates")
        self._index = index  # Store the index
        self.step_box = QSpinBox(); self.step_box.setRange(0, max_step); self.step_box.setValue(int(step)); self.step_box.setSingleStep(max(1, int(step*0.02) if step > 0 else 1))
        self.strain_box = QDoubleSpinBox(); self.strain_box.setRange(min_strain, max_strain); self.strain_box.setValue(strain); self.strain_box.setDecimals(4); self.strain_box.setSingleStep(max(0.01, abs(strain)*0.02 if strain != 0 else 0.01))
        if index == 0:
            self.step_box.setEnabled(False)
            self.strain_box.setEnabled(is_temp_mode)
        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel); buttons.accepted.connect(self.accept); buttons.rejected.connect(self.reject)
        layout = QFormLayout(self)
        y_label = "Temperature:" if is_temp_mode else "Strain:"
        layout.addRow("Time Step:", self.step_box); layout.addRow(y_label, self.strain_box); layout.addWidget(buttons)
    def get_coordinates(self): 
        # For the first point, always return step 0
        if self._index == 0:
            return 0, self.strain_box.value()
        return self.step_box.value(), self.strain_box.value()

class InsertSineDialog(QDialog):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Insert Sine Segment")
        
        layout = QFormLayout(self)
        
        self.num_cycles = QDoubleSpinBox()
        self.num_cycles.setRange(0.25, 1000.0)
        self.num_cycles.setSingleStep(0.25)
        self.num_cycles.setValue(1.0)
        layout.addRow("Number of cycles:", self.num_cycles)

        self.scheme = QComboBox()
        self.scheme.addItems([
            "Alternating (tensile start)",
            "Alternating (compressive start)",
            "Pulsating tensile load",
            "Pulsating compressive load"
        ])
        layout.addRow("Loading scheme:", self.scheme)
        
        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel)
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)

    def get_parameters(self):
        return {
            'num_cycles': self.num_cycles.value(),
            'scheme': self.scheme.currentText()
        }

class AmplitudeEditDialog(QDialog):
    def __init__(self, y_center, amplitude, min_strain, max_strain, scheme, parent=None):
        super().__init__(parent)
        self._y_center = y_center
        self._min_strain = min_strain
        self._max_strain = max_strain
        self._scheme = scheme
        self.is_compressive_pulsating = "Pulsating compressive" in self._scheme

        if self.is_compressive_pulsating:
            self.setWindowTitle("Edit Amplitude and Trough Value")
            self._peak_value = y_center - amplitude  # It's a trough
            label_text = "Trough Value:"
        else:
            self.setWindowTitle("Edit Amplitude and Peak Value")
            self._peak_value = y_center + amplitude
            label_text = "Peak Value:"
        
        # Calculate initial peak value
        self._amplitude = amplitude
        
        layout = QFormLayout(self)
        
        self.amplitude_box = QDoubleSpinBox()
        self.amplitude_box.setRange(0.0, max(abs(min_strain), abs(max_strain)))
        self.amplitude_box.setDecimals(6)
        self.amplitude_box.setValue(amplitude)
        self.amplitude_box.setSingleStep(0.01)
        
        self.peak_box = QDoubleSpinBox()
        self.peak_box.setRange(min_strain, max_strain)
        self.peak_box.setDecimals(6)
        self.peak_box.setValue(self._peak_value)
        self.peak_box.setSingleStep(0.01)
        
        layout.addRow("Amplitude:", self.amplitude_box)
        layout.addRow(label_text, self.peak_box)
        
        # Connect value changes to automatically update the other
        self.amplitude_box.valueChanged.connect(self._amplitude_changed)
        self.peak_box.valueChanged.connect(self._peak_changed)
        
        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel)
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)
    
    def _amplitude_changed(self, value):
        self.peak_box.blockSignals(True)  # Prevent circular updates
        if self.is_compressive_pulsating:
            new_peak = self._y_center - value # Trough
        else:
            new_peak = self._y_center + value # Peak
        self.peak_box.setValue(new_peak)
        self._peak_value = new_peak
        self._amplitude = value
        self.peak_box.blockSignals(False)
    
    def _peak_changed(self, value):
        self.amplitude_box.blockSignals(True)  # Prevent circular updates
        new_amplitude = abs(value - self._y_center)
        self.amplitude_box.setValue(new_amplitude)
        self._amplitude = new_amplitude
        self._peak_value = value
        self.amplitude_box.blockSignals(False)
    
    def get_amplitude(self):
        return self._amplitude

class SinePropertiesDialog(QDialog):
    def __init__(self, current_params, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Edit Sine Segment Properties")
        
        layout = QFormLayout(self)
        
        self.num_cycles = QDoubleSpinBox()
        self.num_cycles.setRange(0.25, 1000.0)
        self.num_cycles.setSingleStep(0.25)
        self.num_cycles.setValue(current_params.get('num_cycles', 1.0))
        layout.addRow("Number of cycles:", self.num_cycles)

        self.scheme = QComboBox()
        self.scheme.addItems([
            "Alternating (tensile start)",
            "Alternating (compressive start)",
            "Pulsating tensile load",
            "Pulsating compressive load"
        ])
        self.scheme.setCurrentText(current_params.get('scheme', 'Alternating (tensile start)'))
        layout.addRow("Loading scheme:", self.scheme)
        
        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel)
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)

    def get_parameters(self):
        return {
            'num_cycles': self.num_cycles.value(),
            'scheme': self.scheme.currentText()
        }

# --- Main Graph Widget ---
class GraphWidget(QWidget):
    dataChanged = pyqtSignal()
    def __init__(self, parent=None):
        super().__init__(parent); self.setMinimumSize(600, 320); self.setMouseTracking(True)
        self.mode = "Deformation"
        self.STYLE_LINE = QColor("#007BFF")
        self.STYLE_HANDLE = QColor("#007BFF")
        self.padding = {'top': 10, 'bottom': 60, 'left': 60, 'right': 60}
        self._max_steps, self._min_strain, self._max_strain, self._timestep, self._time_unit = 100, 0.0, 1.0, 1.0, "s"
        self.points_norm = [self._data_to_norm(QPointF(0,0)), self._data_to_norm(QPointF(100, 1.0))]; self._sort_points()
        self.segments = [{'type': 'line'}] # A segment for each pair of points
        self._dragged_handle_index, self._hovered_handle_index, self._dragged_segment_index, self._hovered_segment_index, self._dragged_amplitude_handle_index, self._hovered_amplitude_handle_index = None, None, None, None, None, None
        self._drag_start_pos_widget, self._drag_axis_lock, self._segment_drag_offset_norm = None, None, QPointF(0,0)
        self._drag_mouse_to_p1_offset = QPointF(0,0); self._clickable_regions = []; self._sine_amplitude_handles = {}
        # Add data structures to track fixed segments, locked x-axis ticks, and locked y-value labels
        self._fixed_segments = set()
        self._locked_x_ticks = set()
        self._locked_y_labels = set()
    def set_max_values(self, s, min_e, max_e):
        old_points_data = self.get_data_points(); old_max_steps = self._max_steps
        self._max_steps, self._min_strain, self._max_strain = int(s), float(min_e), float(max_e)
        new_points_data = []
        for p in old_points_data:
            new_x = p.x() * (self._max_steps / old_max_steps) if old_max_steps > 0 else 0
            clamped_y = max(self._min_strain, min(self._max_strain, p.y()))
            new_points_data.append(QPointF(new_x, clamped_y))
        if self.mode == 'Deformation':
            new_points_data[0].setY(0)
        new_points_data[0].setX(0)
        if len(new_points_data) > 1:
            new_points_data[-1].setX(float(self._max_steps))
        # Round all x values to nearest integer
        for i in range(len(new_points_data)):
            new_points_data[i].setX(round(new_points_data[i].x()))
        self.points_norm = [self._data_to_norm(p) for p in new_points_data]
        self.update(); self.dataChanged.emit()
    def set_timestep(self, s): self._timestep = s; self.update(); self.dataChanged.emit()
    def set_time_unit(self, u): self._time_unit = u; self.update()

    def get_y_start(self):
        return self._min_strain if self.mode == 'Temperature' else 0.0

    def set_mode(self, mode):
        self.mode = mode
        is_temp_mode = mode == 'Temperature'
        if is_temp_mode:
            self.STYLE_LINE = QColor("darkorange")
            self.STYLE_HANDLE = QColor("darkorange")
        else:
            self.STYLE_LINE = QColor("#007BFF")
            self.STYLE_HANDLE = QColor("#007BFF")
        self.update()
    def reset_graph(self):
        y_start = self.get_y_start()
        self.points_norm = [self._data_to_norm(QPointF(0, y_start)), self._data_to_norm(QPointF(self._max_steps, self._max_strain))]
        self.segments = [{'type': 'line'}]
        # Clear fixed segments when resetting the graph
        self._fixed_segments.clear()
        self.update()
        self.dataChanged.emit()
    def generate_staircase_scheme(self, equilibration_steps, cycles, relax_factor, direction):
        if cycles <= 0 or relax_factor < 0: return

        y_start = self.get_y_start()
        is_temp_mode = self.mode == 'Temperature'

        if is_temp_mode:
            target_y = self._max_strain if direction == "Heating" else self._min_strain
        else:
            target_y = self._max_strain if direction == "Tension" else self._min_strain

        if abs(target_y - y_start) < 1e-9: self.reset_graph(); return

        y_per_cycle = (target_y - y_start) / cycles

        effective_max_steps = self._max_steps - equilibration_steps
        if effective_max_steps <= 0: return

        total_ratio_units = cycles * (1 + relax_factor)
        if total_ratio_units == 0: return

        steps_per_load_unit = effective_max_steps / total_ratio_units
        load_steps, relax_steps = steps_per_load_unit, steps_per_load_unit * relax_factor

        new_data_points = [QPointF(0, y_start)]
        if equilibration_steps > 0:
            new_data_points.append(QPointF(equilibration_steps, y_start))

        for i in range(1, cycles + 1):
            load_end_step = equilibration_steps + i * load_steps + (i - 1) * relax_steps
            load_end_y = y_start + i * y_per_cycle
            new_data_points.append(QPointF(load_end_step, load_end_y))

            if (i * (load_steps + relax_steps)) < effective_max_steps:
                relax_end_step = equilibration_steps + i * (load_steps + relax_steps)
                new_data_points.append(QPointF(relax_end_step, load_end_y))

        if new_data_points[-1].x() < self._max_steps:
            new_data_points.append(QPointF(self._max_steps, target_y))

        self.points_norm = [self._data_to_norm(self._snap_data_point(p)) for p in new_data_points]
        self.segments = [{'type': 'line'} for _ in range(len(self.points_norm) - 1)]
        self._sort_points()
        self.update()
        self.dataChanged.emit()
    def generate_cyclic_scheme(self, equilibration_steps, cycles, relax_factor, start_with):
        if cycles <= 0: return
        y_start = self.get_y_start()
        path = [y_start]

        is_temp_mode = self.mode == 'Temperature'
        if is_temp_mode:
            peak1 = self._max_strain if start_with == "Heating" else self._min_strain
            peak2 = self._min_strain if start_with == "Heating" else self._max_strain
        else:
            peak1 = self._max_strain if start_with == "Tension" else self._min_strain
            peak2 = self._min_strain if start_with == "Tension" else self._max_strain

        for i in range(cycles):
            path.append(peak1)
            path.extend([y_start, peak2, y_start])

        total_dist = sum(abs(path[i] - path[i-1]) for i in range(1, len(path)))
        if total_dist == 0: return

        effective_max_steps = self._max_steps - equilibration_steps
        if effective_max_steps <= 0: return

        steps_per_one_cycle = total_dist / cycles if cycles > 0 else 0
        total_steps_for_cycles_and_relax = total_dist + (steps_per_one_cycle * relax_factor)
        scaling_factor = effective_max_steps / total_steps_for_cycles_and_relax if total_steps_for_cycles_and_relax > 0 else 0

        points = [QPointF(0, y_start)]
        if equilibration_steps > 0:
            points.append(QPointF(equilibration_steps, y_start))

        current_step_dist = 0.0
        for i in range(1, len(path)):
            current_step_dist += abs(path[i] - path[i-1])
            points.append(QPointF(equilibration_steps + current_step_dist * scaling_factor, path[i]))

        if relax_factor > 0:
            current_step_dist += steps_per_one_cycle * relax_factor
            points.append(QPointF(equilibration_steps + current_step_dist * scaling_factor, points[-1].y()))

        final_points = points
        if final_points[-1].x() < self._max_steps:
            final_points.append(QPointF(self._max_steps, final_points[-1].y()))

        self.points_norm = [self._data_to_norm(self._snap_data_point(p)) for p in final_points]
        self.segments = [{'type': 'line'} for _ in range(len(self.points_norm) - 1)]
        self._sort_points()
        self.update()
        self.dataChanged.emit()

    def generate_sinusoidal_scheme(self, equilibration_steps, num_cycles, relax_factor, scheme):
        if num_cycles <= 0: return

        # 1. Determine Amplitude, Phase, and Offset from scheme
        amplitude = min(abs(self._max_strain), abs(self._min_strain))
        if amplitude == 0: amplitude = max(abs(self._max_strain), abs(self._min_strain))
        if amplitude == 0: amplitude = 0.1  # Final fallback

        phi_start = 0
        y_center_offset = 0

        if "Alternating" in scheme:
            if "compressive start" in scheme:
                amplitude *= -1 # Starts downwards
        elif "Pulsating tensile" in scheme:
            y_center_offset = amplitude
            phi_start = -math.pi / 2  # Start at the bottom (y=0)
        elif "Pulsating compressive" in scheme:
            y_center_offset = -amplitude
            phi_start = math.pi / 2   # Start at the top (y=0)

        # 2. Calculate start and end points of the entire profile
        y_start = self.get_y_start()
        start_y_val = y_start + y_center_offset + amplitude * math.sin(phi_start)

        end_angle = num_cycles * 2 * math.pi + phi_start
        end_y_val = y_start + y_center_offset + amplitude * math.sin(end_angle)

        # 3. Calculate step durations
        effective_max_steps = self._max_steps - equilibration_steps
        if effective_max_steps <= 0: return

        total_cycle_equivalents = num_cycles + relax_factor
        if total_cycle_equivalents <= 0: return
        steps_per_cycle = effective_max_steps / total_cycle_equivalents

        sine_duration_steps = steps_per_cycle * num_cycles
        relax_duration_steps = steps_per_cycle * relax_factor

        # 4. Build points and segments lists
        new_data_points = [QPointF(0, start_y_val)]
        new_segments = []

        if equilibration_steps > 0:
            new_data_points.append(QPointF(float(equilibration_steps), start_y_val))
            new_segments.append({'type': 'line'})

        sine_start_step = new_data_points[-1].x()
        sine_end_step = sine_start_step + sine_duration_steps
        new_data_points.append(QPointF(sine_end_step, end_y_val))
        new_segments.append({'type': 'sine', 'num_cycles': num_cycles, 'scheme': scheme, 'amplitude': abs(amplitude)})

        if relax_duration_steps > 0:
            relax_end_step = sine_end_step + relax_duration_steps
            if relax_end_step <= self._max_steps:
                new_data_points.append(QPointF(relax_end_step, end_y_val))
                new_segments.append({'type': 'line'})

        # Fill remaining space
        if new_data_points[-1].x() < self._max_steps:
            new_data_points.append(QPointF(float(self._max_steps), new_data_points[-1].y()))
            new_segments.append({'type': 'line'})
        else:
            new_data_points[-1].setX(float(self._max_steps))

        # 5. Update graph state
        self.points_norm = [self._data_to_norm(p) for p in new_data_points]
        self.segments = new_segments
        self._sort_points()
        self.update()
        self.dataChanged.emit()

    def get_data_points(self): return [self._norm_to_data(p) for p in self.points_norm]
    def _norm_to_data(self, p_norm):
        strain_range = self._max_strain - self._min_strain
        y_data = self._min_strain + p_norm.y() * strain_range
        return QPointF(p_norm.x() * self._max_steps, y_data)

    def _data_to_norm(self, p_data):
        strain_range = self._max_strain - self._min_strain
        if strain_range < 1e-9:
            y_norm = 0.5
        else:
            y_norm = (p_data.y() - self._min_strain) / strain_range
        
        x_norm = p_data.x() / self._max_steps if self._max_steps > 0 else 0
        return QPointF(x_norm, y_norm)
    def _widget_to_norm(self, pos):
        dw, dh = self.width() - (self.padding['left'] + self.padding['right']), self.height() - (self.padding['top'] + self.padding['bottom'])
        if dw <= 0 or dh <= 0: return QPointF(0, 0)
        return QPointF(max(0.0, min(1.0, (pos.x() - self.padding['left']) / dw)), max(0.0, min(1.0, 1.0 - (pos.y() - self.padding['top']) / dh)))
    def _norm_to_widget(self, p): return QPointF(self.padding['left'] + p.x() * (self.width() - (self.padding['left'] + self.padding['right'])), self.padding['top'] + (1.0 - p.y()) * (self.height() - (self.padding['top'] + self.padding['bottom'])))
    def _sort_points(self): self.points_norm.sort(key=lambda p: p.x())
    def _snap_data_point(self, p):
        strain_range = self._max_strain - self._min_strain
        if strain_range > 0:
            step_size = strain_range / 200.0
            snapped_y = self._min_strain + round((p.y() - self._min_strain) / step_size) * step_size
            snapped_y = max(self._min_strain, snapped_y)
        else:
            snapped_y = p.y()
        return QPointF(round(p.x()), snapped_y)
    def _get_handle_at(self, pos):
        for i, p in enumerate(self.points_norm):
            if (pos - self._norm_to_widget(p)).manhattanLength() < HANDLE_RADIUS * 1.5: return i
        return None
    def _get_amplitude_handle_at(self, pos):
        if not hasattr(self, '_sine_amplitude_handles'):
            return None
        for seg_idx, handle_pos_w in self._sine_amplitude_handles.items():
            if (pos - handle_pos_w).manhattanLength() < HANDLE_RADIUS * 1.5:
                return seg_idx
        return None
    def _get_segment_at(self, pos):
        for i in range(len(self.points_norm) - 1):
            if len(self.points_norm) <= 2: continue
            p1_w, p2_w = self._norm_to_widget(self.points_norm[i]), self._norm_to_widget(self.points_norm[i+1])
            v, w = p2_w - p1_w, pos - p1_w; l2 = v.x()**2 + v.y()**2
            if l2 == 0: continue
            t = max(0, min(1, QPointF.dotProduct(w, v) / l2))
            if (pos - (p1_w + t * v)).manhattanLength() < 5: return i
        return None
    def paintEvent(self, event):
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        
        # --- Draw the normal graph content first ---
        painter.fillRect(self.rect(), STYLE_BACKGROUND)
        self._clickable_regions.clear()
        if hasattr(self, '_sine_amplitude_handles'): self._sine_amplitude_handles.clear()
        self._draw_axes_and_frame(painter)

        if self.points_norm:
            fm = QFontMetrics(QFont("Arial", 10))
            # Draw the line segments and slope labels
            for i in range(len(self.points_norm) - 1):
                p1_w, p2_w = self._norm_to_widget(self.points_norm[i]), self._norm_to_widget(self.points_norm[i+1])
                segment_info = self.segments[i]
                if segment_info['type'] == 'line':
                    painter.setPen(QPen(self.STYLE_LINE, 2)); painter.drawLine(p1_w, p2_w)
                    p1_d, p2_d = self._norm_to_data(self.points_norm[i]), self._norm_to_data(self.points_norm[i+1])
                    dx_s, dy_e, dx_t = p2_d.x() - p1_d.x(), p2_d.y() - p1_d.y(), (p2_d.x() - p1_d.x()) * self._timestep
                    slope, rate = (dy_e / dx_s if dx_s != 0 else float('inf')), (dy_e / dx_t if dx_t != 0 else float('inf'))
                    slope_text = f"{slope:.4e} {self.get_y_unit()}/step"
                    rate_text = f"{rate:.4e} {self.get_y_unit()}/t"
                    slope_rect = QRectF(fm.boundingRect(slope_text).adjusted(-2,-2,2,2)); slope_rect.moveCenter((p1_w * 2/3 + p2_w * 1/3) - QPointF(0, 20))
                    rate_rect = QRectF(fm.boundingRect(rate_text).adjusted(-2,-2,2,2)); rate_rect.moveCenter((p1_w * 2/3 + p2_w * 1/3) - QPointF(0, 6))
                    if i in self._fixed_segments:
                        painter.setPen(QColor("red"))
                    else:
                        painter.setPen(STYLE_SLOPE_TEXT)
                    painter.setFont(QFont("Arial", 9, QFont.Weight.Bold)); painter.drawText(slope_rect, slope_text)
                    if i in self._fixed_segments:
                        painter.setPen(QColor("red"))
                    else:
                        painter.setPen(STYLE_TEXT_SECONDARY)
                    painter.drawText(rate_rect, rate_text)
                    self._clickable_regions.append((slope_rect.united(rate_rect), "slope", i))
                elif segment_info['type'] == 'sine':
                    self._draw_sine_segment(painter, i, p1_w, p2_w, segment_info)            # Draw the handles and labels
            for i, p_norm in enumerate(self.points_norm):
                p_data, p_w = self._norm_to_data(p_norm), self._norm_to_widget(p_norm)
                painter.setPen(QPen(STYLE_HANDLE_OUTLINE, 2)); painter.setBrush(self.STYLE_HANDLE); painter.drawEllipse(p_w, HANDLE_RADIUS, HANDLE_RADIUS)
                y_text = f"{p_data.y():.3f}"; y_rect = QRectF(fm.boundingRect(y_text)); y_rect.moveCenter(QPointF(p_w.x() + 35, p_w.y()))
                if i in self._locked_y_labels:
                    painter.setPen(QColor("red"))
                elif self.mode == 'Temperature':
                    painter.setPen(QColor("darkorange"))
                else:
                    painter.setPen(STYLE_TEXT_PRIMARY)
                painter.setFont(QFont("Arial", 10, QFont.Weight.Bold)); painter.drawText(y_rect, y_text)
                self._clickable_regions.append((y_rect, "y_val", i))
                step_text, time_text = f"{p_data.x():.0f}", f"({p_data.x() * self._timestep:.2f}{self._time_unit})"
                step_rect = QRectF(fm.boundingRect(step_text).adjusted(-4,0,4,0)); step_rect.moveCenter(QPointF(p_w.x(), self.height() - self.padding['bottom'] + 18))
                time_rect = QRectF(fm.boundingRect(time_text)); time_rect.moveCenter(QPointF(p_w.x(), self.height() - self.padding['bottom'] + 34))
                if i in self._locked_x_ticks:
                    painter.setPen(QColor("red"))
                else:
                    painter.setPen(STYLE_TEXT_PRIMARY)
                painter.drawText(step_rect, step_text)
                if i in self._locked_x_ticks:
                    painter.setPen(QColor("red"))
                else:
                    painter.setPen(STYLE_TEXT_SECONDARY)
                painter.setFont(QFont("Arial", 9)); painter.drawText(time_rect, time_text)
                self._clickable_regions.append((step_rect.united(time_rect), "x_val", i))

        # --- Now, draw the overlay if disabled ---
        parent_study_widget = self.parent()
        if parent_study_widget and hasattr(parent_study_widget, 'is_enabled') and not parent_study_widget.is_enabled:
            overlay_color = QColor("#E9ECEF")
            overlay_color.setAlphaF(0.85)
            painter.fillRect(self.rect(), overlay_color)
            painter.setPen(QColor("#495057"))
            font_bold = QFont("Arial", 14, QFont.Weight.Bold)
            painter.setFont(font_bold)
            painter.drawText(self.rect(), Qt.AlignmentFlag.AlignCenter, "STUDY DISABLED")
            font_normal = QFont("Arial", 10)
            painter.setFont(font_normal)
            text_rect = self.rect().adjusted(0, 40, 0, 0)
            painter.drawText(text_rect, Qt.AlignmentFlag.AlignCenter, "right-click the study tab to reactivate")

    def _draw_axes_and_frame(self, painter):
        painter.setPen(QPen(STYLE_FRAME, 2)); painter.drawRect(self.padding['left'], self.padding['top'], self.width() - (self.padding['left'] + self.padding['right']), self.height() - (self.padding['top'] + self.padding['bottom']))
        painter.setPen(STYLE_TEXT_PRIMARY); painter.setFont(QFont("Arial", 11, QFont.Weight.Bold)); painter.save()
        painter.translate(40, int(self.height() / 2) + 36); painter.rotate(-90)
        y_label = "Temperature / K" if self.mode == 'Temperature' else "Engineering strain"
        painter.drawText(0, 0, y_label)
        painter.restore()
        painter.drawText(int(self.width()/2 - 30), self.height() - self.padding['bottom'] + 55, "Time Steps")

    def _get_sine_handle_type(self, handle_index, segment_index):
        if segment_index < 0 or segment_index >= len(self.segments):
            return None
        segment = self.segments[segment_index]
        if segment['type'] != 'sine':
            return None

        num_cycles = segment['num_cycles']
        scheme = segment['scheme']

        phi_start = 0
        if "tensile start" in scheme: phi_start = -math.pi / 2
        elif "compressive start" in scheme: phi_start = math.pi / 2
        elif "Pulsating compressive" in scheme: phi_start = math.pi

        angle = 0
        if handle_index == segment_index:
            angle = phi_start
        elif handle_index == segment_index + 1:
            angle = num_cycles * 2 * math.pi + phi_start
        else:
            return None

        sin_val = math.sin(angle)
        if abs(sin_val) > 0.999:
            return "peak" if sin_val > 0 else "trough"
        elif abs(sin_val) < 0.001:
            return "zero"
        else:
            return "other"

    def _get_sine_parameters(self, p1_d, p2_d, segment_info):
        num_cycles = segment_info['num_cycles']
        scheme = segment_info['scheme']
        y1, y2 = p1_d.y(), p2_d.y()

        phi_start, y_center, amplitude = 0, 0, 0

        if "Alternating" in scheme:
            y_center = y1
            phi_start = math.pi if "compressive" in scheme else 0
            end_angle = num_cycles * 2 * math.pi + phi_start
            sin_end = math.sin(end_angle)
            if abs(sin_end) < 1e-9:
                amplitude = (self._max_strain - self._min_strain) / 4
            else:
                amplitude = (y2 - y_center) / sin_end
        elif "Pulsating" in scheme:
            phi_start = -math.pi / 2 if "tensile" in scheme else math.pi / 2
            end_angle = num_cycles * 2 * math.pi + phi_start
            # y1 = y_center + amp * sin(phi_start)
            # y2 = y_center + amp * sin(end_angle)
            # y2 - y1 = amp * (sin(end_angle) - sin(phi_start))
            denominator = math.sin(end_angle) - math.sin(phi_start)
            if abs(denominator) < 1e-9:
                amplitude = (self._max_strain - self._min_strain) / 4
            else:
                amplitude = (y2 - y1) / denominator
            y_center = y1 - amplitude * math.sin(phi_start)
        else:
            return None, None, None

        return amplitude, y_center, phi_start


    def _get_sine_parameters_with_stored_amp(self, p1_d, p2_d, segment_info, segment_index):
        """Get sine parameters, using stored amplitude if available (for user-modified amplitudes)"""
        amplitude, y_center, phi_start = self._get_sine_parameters(p1_d, p2_d, segment_info)
        
        # Use stored amplitude if available (for user-modified amplitude)
        stored_amplitude = self.segments[segment_index].get('amplitude')
        if stored_amplitude is not None:
            # For even multiple alternating schemes and integer full period pulsating schemes,
            # the original _get_sine_parameters calculation may need to be preserved to maintain the mathematically correct shape
            # But for user-modified amplitude, we still want to use the stored value
            num_cycles = segment_info['num_cycles']
            scheme = segment_info['scheme']
            is_even_multiple_alternating = (num_cycles * 4) % 2 == 0 and "Alternating" in scheme
            is_integer_full_period_pulsating = (num_cycles * 4) % 4 == 0 and "Pulsating" in scheme
            
            if is_even_multiple_alternating:
                # For even multiple alternating schemes, both endpoints should have the same y-value (horizontal line)
                y_center = (p1_d.y() + p2_d.y()) / 2  # Use average as the horizontal line
                amplitude = stored_amplitude
            elif is_integer_full_period_pulsating:
                # For integer full period pulsating schemes, we still need to use the original calculation
                # but with the new stored amplitude. The start point should remain at the same y-value as originally
                # Recalculate the proper y_center based on the original formula using stored amplitude
                phi_start = -math.pi / 2 if "tensile" in scheme else math.pi / 2
                y_center = p1_d.y() - stored_amplitude * math.sin(phi_start)  # Original formula with new amplitude
                amplitude = stored_amplitude
            else:
                # For non-special cases, just use the stored amplitude
                amplitude = stored_amplitude
        
        return amplitude, y_center, phi_start

    def _draw_sine_segment(self, painter, segment_index, p1_w, p2_w, segment_info):
        p1_d = self._norm_to_data(self.points_norm[segment_index])
        p2_d = self._norm_to_data(self.points_norm[segment_index+1])

        amplitude, y_center, phi_start = self._get_sine_parameters_with_stored_amp(p1_d, p2_d, segment_info, segment_index)

        if amplitude is None:
            painter.setPen(QPen(Qt.GlobalColor.red, 2)); painter.drawLine(p1_w, p2_w)
            return

        # Draw a light grey line between the handles to show the base connection
        # This line represents the direct connection between start and end points
        painter.setPen(QPen(QColor("#D3D3D3"), 1, Qt.PenStyle.SolidLine))
        painter.drawLine(p1_w, p2_w)
        
        # 1. Draw the sine wave
        points_to_draw = []
        num_points = int(p2_w.x() - p1_w.x()) * 2
        if num_points < 100: num_points = 100
        if num_points > 1000: num_points = 1000

        x_range_d = p2_d.x() - p1_d.x()
        k = segment_info['num_cycles'] * 2 * math.pi / x_range_d if x_range_d != 0 else 0

        for i in range(num_points + 1):
            t = i / num_points
            x_d = p1_d.x() + t * x_range_d
            y_d = y_center + amplitude * math.sin(k * (x_d - p1_d.x()) + phi_start)
            points_to_draw.append(self._norm_to_widget(self._data_to_norm(QPointF(x_d, y_d))))

        # Draw the sine wave in the normal style color
        painter.setPen(QPen(self.STYLE_LINE, 2))
        painter.drawPolyline(QPolygonF(points_to_draw))

        # 2. Draw the ghost slope indicator
        # Find first zero crossing: y_center = y_center + amp * sin(k*x + phi)
        # sin(k*x + phi) = 0  => k*x + phi = n*pi
        # x = (n*pi - phi) / k
        first_zero_x = -1
        n = 0
        while True:
            x_d_offset = (n * math.pi - phi_start) / k if k != 0 else -1
            if x_d_offset >= -1e-9 and x_d_offset <= x_range_d + 1e-9:
                first_zero_x = p1_d.x() + x_d_offset
                break
            n += 1
            if n > 1000: break # Safety break

        if first_zero_x != -1:
            zero_crossing_p_d = QPointF(first_zero_x, y_center)
            slope_at_zero = amplitude * k * math.cos(k * (first_zero_x - p1_d.x()) + phi_start)
            rate_at_zero = slope_at_zero / self._timestep if self._timestep > 0 else float('inf')

            # Find next peak/trough to determine length
            # k*x + phi = (n+0.5)*pi
            next_peak_x_offset = (n * math.pi + math.pi/2 - phi_start) / k if k != 0 else -1
            if not (0 <= next_peak_x_offset <= x_range_d):
                 next_peak_x_offset = (n * math.pi - math.pi/2 - phi_start) / k if k != 0 else -1

            if 0 <= next_peak_x_offset <= x_range_d:
                p_start_w = self._norm_to_widget(self._data_to_norm(zero_crossing_p_d))
                
                # End point of tangent line
                x_end_d = p1_d.x() + next_peak_x_offset
                y_end_d = zero_crossing_p_d.y() + slope_at_zero * (x_end_d - zero_crossing_p_d.x())
                p_end_w = self._norm_to_widget(self._data_to_norm(QPointF(x_end_d, y_end_d)))

                painter.setPen(QPen(QColor("#BDBDBD"), 2, Qt.PenStyle.DashLine))
                painter.drawLine(p_start_w, p_end_w)

                # Draw slope text
                fm = QFontMetrics(QFont("Arial", 10))
                slope_text = f"{slope_at_zero:.4e} {self.get_y_unit()}/step"
                rate_text = f"{rate_at_zero:.4e} {self.get_y_unit()}/t"
                text_pos = (p_start_w + p_end_w) / 2
                slope_rect = QRectF(fm.boundingRect(slope_text).adjusted(-2,-2,2,2)); slope_rect.moveCenter(text_pos - QPointF(0, 12))
                rate_rect = QRectF(fm.boundingRect(rate_text).adjusted(-2,-2,2,2)); rate_rect.moveCenter(text_pos + QPointF(0, 2))
                
                painter.setPen(STYLE_SLOPE_TEXT)
                painter.setFont(QFont("Arial", 9, QFont.Weight.Bold)); painter.drawText(slope_rect, slope_text)
                painter.setPen(STYLE_TEXT_SECONDARY)
                painter.drawText(rate_rect, rate_text)

        # 3. Draw amplitude handle - Position at first peak/trough after the midpoint slope
        # According to the requirements: the handle should always be one quarter period length after the midpoint slope
        # The midpoint slope occurs where the sine crosses zero (or at the starting phase)
        
        num_cycles = segment_info['num_cycles']

        # Only draw the handle if the segment is longer than a quarter cycle
        if num_cycles > 0.25:
            # First, find the first zero crossing (midpoint slope starting point)
            first_zero_x = -1
            n = 0
            while True:
                x_d_offset = (n * math.pi - phi_start) / k if k != 0 else -1
                if x_d_offset >= -1e-9 and x_d_offset <= x_range_d + 1e-9:
                    first_zero_x = p1_d.x() + x_d_offset
                    break
                n += 1
                if n > 1000: break # Safety break

            # Position the amplitude handle at one quarter period after the first zero crossing
            quarter_period = x_range_d / (4 * num_cycles) if num_cycles > 0 else 0
            peak_trough_x = first_zero_x + quarter_period if first_zero_x != -1 else p1_d.x() + quarter_period

            # Make sure it's within the segment bounds
            if peak_trough_x >= p1_d.x() - 1e-9 and peak_trough_x <= p2_d.x() + 1e-9:
                peak_trough_y_d = y_center + amplitude * math.sin(k * (peak_trough_x - p1_d.x()) + phi_start)
                peak_trough_pos_d = QPointF(peak_trough_x, peak_trough_y_d)
                peak_trough_pos_w = self._norm_to_widget(self._data_to_norm(peak_trough_pos_d))

                # Store this for mouse events - only for even multiples of quarter periods
                # Always store the amplitude handle position for display
                self._sine_amplitude_handles[segment_index] = peak_trough_pos_w

                # Draw the handle (e.g., a diamond shape)
                painter.setPen(QPen(self.STYLE_HANDLE, 2))
                painter.setBrush(QBrush(QColor("white")))
                poly = QPolygonF([
                    peak_trough_pos_w + QPointF(0, -HANDLE_RADIUS),
                    peak_trough_pos_w + QPointF(HANDLE_RADIUS, 0),
                    peak_trough_pos_w + QPointF(0, HANDLE_RADIUS),
                    peak_trough_pos_w + QPointF(-HANDLE_RADIUS, 0),
                ])
                painter.drawPolygon(poly)
                
                # Draw amplitude value label - using actual stored amplitude if available
                fm = QFontMetrics(QFont("Arial", 10))
                # Use the stored amplitude value if available, otherwise calculate from the drawn position
                stored_amplitude = self.segments[segment_index].get('amplitude')
                if stored_amplitude is not None:
                    # Calculate the actual Y-value that the amplitude handle represents based on the stored amplitude
                    # This is where the handle is drawn on the screen: y_center + A*sin(angle_at_handle)
                    # Calculate the angle at the point where the amplitude handle is drawn
                    k_for_calc = segment_info['num_cycles'] * 2 * math.pi / x_range_d if x_range_d != 0 else 0
                    angle_at_handle = k_for_calc * (peak_trough_x - p1_d.x()) + phi_start
                    y_at_handle = y_center + stored_amplitude * math.sin(angle_at_handle)
                    
                    amplitude_text = f"{y_at_handle:.3f}"
                else:
                    amplitude_text = f"{peak_trough_y_d:.3f}"  # Fallback to drawn position
                
                amplitude_rect = QRectF(fm.boundingRect(amplitude_text).adjusted(-4,-2,4,2))
                amplitude_rect.moveCenter(QPointF(peak_trough_pos_w.x() + 35, peak_trough_pos_w.y()))
                painter.setPen(QPen(STYLE_TEXT_PRIMARY, 1))
                painter.setFont(QFont("Arial", 9, QFont.Weight.Bold))
                painter.drawText(amplitude_rect, Qt.AlignmentFlag.AlignCenter, amplitude_text)
                
                # Add amplitude label to clickable regions for both even multiple alternating schemes and integer full period pulsating schemes
                is_even_multiple_alternating = (segment_info['num_cycles'] * 4) % 2 == 0 and "Alternating" in segment_info['scheme']
                is_integer_full_period_pulsating = (segment_info['num_cycles'] * 4) % 4 == 0 and "Pulsating" in segment_info['scheme']
                if is_even_multiple_alternating or is_integer_full_period_pulsating:
                    self._clickable_regions.append((amplitude_rect, "amplitude_label", segment_index))

                # Only draw the second amplitude handle if we have 5 or more quarter periods (to avoid coincidence at 4 quarters)
                num_quarters = segment_info['num_cycles'] * 4
                if num_quarters >= 5:
                    second_peak_trough_x = peak_trough_x + 2 * quarter_period  # One full period after the first
                    
                    # Condition: Draw if the next peak/trough is also within the segment bounds.
                    if second_peak_trough_x <= p2_d.x() + 1e-9:
                        # Calculate the Y position for the second handle
                        second_peak_trough_y_d = y_center + amplitude * math.sin(k * (second_peak_trough_x - p1_d.x()) + phi_start)
                        second_peak_trough_pos_d = QPointF(second_peak_trough_x, second_peak_trough_y_d)
                        second_peak_trough_pos_w = self._norm_to_widget(self._data_to_norm(second_peak_trough_pos_d))
                        
                        # Draw the second handle (e.g., a diamond shape)
                        painter.setPen(QPen(self.STYLE_HANDLE, 2))
                        painter.setBrush(QBrush(QColor("white")))
                        second_poly = QPolygonF([
                            second_peak_trough_pos_w + QPointF(0, -HANDLE_RADIUS),
                            second_peak_trough_pos_w + QPointF(HANDLE_RADIUS, 0),
                            second_peak_trough_pos_w + QPointF(0, HANDLE_RADIUS),
                            second_peak_trough_pos_w + QPointF(-HANDLE_RADIUS, 0),
                        ])
                        painter.drawPolygon(second_poly)
                        
                        # Draw the second amplitude value label - using actual stored amplitude if available
                        stored_amplitude = self.segments[segment_index].get('amplitude')
                        if stored_amplitude is not None:
                            # Calculate the actual Y-value that the second amplitude handle represents based on the stored amplitude
                            # This is where the handle is drawn on the screen: y_center + A*sin(angle_at_second_handle)
                            # Calculate the angle at the point where the second amplitude handle is drawn
                            k_for_calc = segment_info['num_cycles'] * 2 * math.pi / x_range_d if x_range_d != 0 else 0
                            angle_at_second_handle = k_for_calc * (second_peak_trough_x - p1_d.x()) + phi_start
                            y_at_second_handle = y_center + stored_amplitude * math.sin(angle_at_second_handle)
                            
                            second_amplitude_text = f"{y_at_second_handle:.3f}"
                        else:
                            second_amplitude_text = f"{second_peak_trough_y_d:.3f}"  # Fallback to drawn position
                        
                        second_amplitude_rect = QRectF(fm.boundingRect(second_amplitude_text).adjusted(-4,-2,4,2))
                        second_amplitude_rect.moveCenter(QPointF(second_peak_trough_pos_w.x() + 35, second_peak_trough_pos_w.y()))
                        painter.setPen(QPen(STYLE_TEXT_PRIMARY, 1))
                        painter.setFont(QFont("Arial", 9, QFont.Weight.Bold))
                        painter.drawText(second_amplitude_rect, Qt.AlignmentFlag.AlignCenter, second_amplitude_text)
                        
                        # Add second amplitude label to clickable regions for both even multiple alternating and integer full period pulsating schemes
                        is_even_multiple_alternating = (segment_info['num_cycles'] * 4) % 2 == 0 and "Alternating" in segment_info['scheme']
                        is_integer_full_period_pulsating = (segment_info['num_cycles'] * 4) % 4 == 0 and "Pulsating" in segment_info['scheme']
                        if is_even_multiple_alternating or is_integer_full_period_pulsating:
                            self._clickable_regions.append((second_amplitude_rect, "amplitude_label", segment_index))

    def get_y_unit(self):
        return "ΔT" if self.mode == 'Temperature' else "ε"
    
    def count_sine_segments(self):
        """Count the number of sine segments in the graph"""
        return sum(1 for segment in self.segments if segment.get('type') == 'sine')

    def get_sine_segment_info(self, segment_index):
        """
        Calculates and returns a dictionary of sine wave parameters for script generation.
        These parameters are derived from the segment's properties and the graph's current state.
        """
        if segment_index < 0 or segment_index >= len(self.segments):
            return None
        
        segment_info = self.segments[segment_index]
        if segment_info['type'] != 'sine':
            return None

        p1_d = self._norm_to_data(self.points_norm[segment_index])
        p2_d = self._norm_to_data(self.points_norm[segment_index+1])

        amplitude_strain, y_center_strain, phi_start_rad = self._get_sine_parameters_with_stored_amp(p1_d, p2_d, segment_info, segment_index)

        if amplitude_strain is None:
            return None

        num_cycles = segment_info['num_cycles']
        scheme = segment_info['scheme']
        x_range_d = p2_d.x() - p1_d.x() # Total steps for this segment

        # Calculate period in steps (Sp in LAMMPS script)
        period_steps = x_range_d / num_cycles if num_cycles > 0 else 0

        # Determine Ashift_factor and LAMMPS-equivalent phi_start based on scheme
        ashift_factor = 0
        lammps_phi_start_rad = 0 # This is the phase of the sine function in LAMMPS, relative to the start of the segment

        if "Alternating" in scheme:
            ashift_factor = 0
            if "compressive start" in scheme:
                lammps_phi_start_rad = math.pi # Starts at -A
            else: # Alternating (tensile start)
                lammps_phi_start_rad = 0 # Starts at 0, goes to +A
        elif "Pulsating tensile" in scheme:
            ashift_factor = 1 # A + A*sin(...) -> oscillates between 0 and 2A
            lammps_phi_start_rad = -math.pi / 2 # sin(-pi/2) = -1, so A + A*(-1) = 0 at start
        elif "Pulsating compressive" in scheme:
            ashift_factor = -1 # -A + A*sin(...) -> oscillates between -2A and 0
            lammps_phi_start_rad = math.pi / 2 # sin(pi/2) = 1, so -A + A*(1) = 0 at start

        # Calculate phaseShift in steps (phaseShift in LAMMPS script)
        # The LAMMPS sine function is A * sin(2*PI * (step-v_phaseShift)/v_Sp) + Ashift
        # We want this to match amplitude_strain * sin(k * (step - p1_d.x()) + phi_start_rad) + y_center_strain
        # After careful derivation, the phaseShift in LAMMPS is:
        # v_phaseShift = p1_d.x() - (lammps_phi_start_rad * period_steps / (2 * math.pi))
        # Note: The y_center_strain is handled by Ashift_factor * amplitude_strain in LAMMPS
        
        # The LAMMPS formula is: A * sin(2*PI * (step-v_phaseShift)/v_Sp) + Ashift
        # The Python formula is: y_center + amplitude * sin(k * (x_d - p1_d.x()) + phi_start)
        # Where k = num_cycles * 2 * math.pi / x_range_d = 2 * math.pi / period_steps
        # So, Python: y_center + amplitude * sin(2*PI/period_steps * (x_d - p1_d.x()) + phi_start)
        # We need to match the phase part:
        # 2*PI/period_steps * (step - phaseShift)  ==  2*PI/period_steps * (step - p1_d.x()) + phi_start
        # (step - phaseShift) == (step - p1_d.x()) + phi_start * period_steps / (2*PI)
        # -phaseShift == -p1_d.x() + phi_start * period_steps / (2*PI)
        # phaseShift = p1_d.x() - (phi_start * period_steps / (2*PI))
        
        # Use the lammps_phi_start_rad for the phaseShift calculation
        phase_shift_steps = p1_d.x() - (lammps_phi_start_rad * period_steps / (2 * math.pi))

        return {
            'amplitude_strain': abs(amplitude_strain), # Always positive for LAMMPS A variable
            'period_steps': period_steps,
            'phase_shift_steps': phase_shift_steps,
            'ashift_factor': ashift_factor,
            'num_cycles': num_cycles,
            'scheme': scheme,
            'start_step': p1_d.x(),
            'end_step': p2_d.x(),
            'start_y': p1_d.y(),
            'end_y': p2_d.y(),
            'y_center_strain': y_center_strain # For debugging/verification
        }

    def mousePressEvent(self, event):
        if event.button() == Qt.MouseButton.LeftButton:
            self._drag_start_pos_widget = event.position()
            self._dragged_handle_index = self._get_handle_at(self._drag_start_pos_widget)

            if self._dragged_handle_index is not None:
                # Check if adjacent segments are fixed, which would constrain movement
                prev_segment_fixed = (self._dragged_handle_index - 1) in self._fixed_segments if self._dragged_handle_index > 0 else False
                next_segment_fixed = self._dragged_handle_index in self._fixed_segments if self._dragged_handle_index < len(self.points_norm) - 1 else False
                # Check if this handle's x or y positions are locked
                x_locked = self._dragged_handle_index in self._locked_x_ticks
                y_locked = self._dragged_handle_index in self._locked_y_labels
                
                # Cannot move handle if both adjacent segments are fixed
                if prev_segment_fixed and next_segment_fixed:
                    self._dragged_handle_index = None
                    return
                    
                # Cannot move handle if both x and y are locked
                if x_locked and y_locked:
                    self._dragged_handle_index = None
                    return
                    
                # Cannot move handle if y is locked and either adjacent segment is fixed (slope is fixed)
                if y_locked and (prev_segment_fixed or next_segment_fixed):
                    self._dragged_handle_index = None
                    return
                    
                # Cannot move handle if it's at the first or last position and has a fixed segment
                if (self._dragged_handle_index == 0 and next_segment_fixed) or (self._dragged_handle_index == len(self.points_norm) - 1 and prev_segment_fixed):
                    self._dragged_handle_index = None
                    return
            
            if self._dragged_handle_index is None:
                self._dragged_amplitude_handle_index = self._get_amplitude_handle_at(self._drag_start_pos_widget)
                # Allow amplitude handle dragging for even multiples of quarter periods in alternating modes
                # and also for integer multiples of full periods in pulsating modes
                if self._dragged_amplitude_handle_index is not None:
                    segment_info = self.segments[self._dragged_amplitude_handle_index]
                    num_cycles = segment_info['num_cycles']
                    scheme = segment_info['scheme']
                    
                    # Allow dragging for even multiples (every 2 quarter periods) in alternating modes
                    # and for integer full periods (every 4 quarter periods) in pulsating modes
                    is_even_multiple_alternating = (num_cycles * 4) % 2 == 0 and "Alternating" in scheme
                    is_integer_full_period_pulsating = (num_cycles * 4) % 4 == 0 and "Pulsating" in scheme
                    
                    if not (is_even_multiple_alternating or is_integer_full_period_pulsating):
                        self._dragged_amplitude_handle_index = None  # Don't allow dragging
                if self._dragged_amplitude_handle_index is None:
                    self._dragged_segment_index = self._get_segment_at(self._drag_start_pos_widget)
                    if self._dragged_segment_index is not None:
                        # Segments can always be selected for dragging, regardless of fixed status
                        # The movement logic will handle constraints appropriately
                        i = self._dragged_segment_index
                        p1_w = self._norm_to_widget(self.points_norm[i])
                        self._drag_mouse_to_p1_offset = self._drag_start_pos_widget - p1_w
                        self._segment_drag_offset_norm = self.points_norm[i+1] - self.points_norm[i]
        elif event.button() == Qt.MouseButton.RightButton:
            # Handle right-click for locking/unlocking x-axis ticks, y-value labels, and slope segments
            pos = event.position()
            for region, type, index in self._clickable_regions:
                if region.contains(pos):
                    if type == "slope":
                        # Toggle fixed state for slope segments
                        if index in self._fixed_segments:
                            self._fixed_segments.remove(index)
                        else:
                            self._fixed_segments.add(index)
                    elif type == "x_val":
                        # Toggle locked state for x-axis tick labels
                        if index in self._locked_x_ticks:
                            self._locked_x_ticks.remove(index)
                        else:
                            self._locked_x_ticks.add(index)
                    elif type == "y_val":
                        # Toggle locked state for y-value labels
                        if index in self._locked_y_labels:
                            self._locked_y_labels.remove(index)
                        else:
                            self._locked_y_labels.add(index)
                    self.update()
                    self.dataChanged.emit()
                    return

    def mouseMoveEvent(self, event):
        pos = event.position()
        self._hovered_handle_index = self._get_handle_at(pos)
        self._hovered_amplitude_handle_index = self._get_amplitude_handle_at(pos)
        self._hovered_segment_index = self._get_segment_at(pos) if self._hovered_handle_index is None and self._hovered_amplitude_handle_index is None else None

        # --- Cursor Logic ---
        cursor_set = False
        if self._hovered_amplitude_handle_index is not None or self._dragged_amplitude_handle_index is not None:
            seg_idx = self._hovered_amplitude_handle_index if self._hovered_amplitude_handle_index is not None else self._dragged_amplitude_handle_index
            if seg_idx is not None and seg_idx < len(self.segments):
                segment_info = self.segments[seg_idx]
                # Allow amplitude handle dragging for even multiples in alternating schemes OR integer full periods in pulsating schemes
                is_even_multiple_alternating = (segment_info['num_cycles'] * 4) % 2 == 0 and "Alternating" in segment_info['scheme']
                is_integer_full_period_pulsating = (segment_info['num_cycles'] * 4) % 4 == 0 and "Pulsating" in segment_info['scheme']
                is_draggable = is_even_multiple_alternating or is_integer_full_period_pulsating
                if is_draggable:
                    self.setCursor(Qt.CursorShape.SizeVerCursor)
                    cursor_set = True
        
        if not cursor_set:
            if self._hovered_handle_index is not None or self._dragged_handle_index is not None:
                self.setCursor(Qt.CursorShape.PointingHandCursor)
            elif self._hovered_segment_index is not None or self._dragged_segment_index is not None:
                self.setCursor(Qt.CursorShape.SizeAllCursor)
            else:
                self.setCursor(Qt.CursorShape.ArrowCursor)
        
        if not (event.buttons() & Qt.MouseButton.LeftButton): return
        
        constrained_pos = pos
        if event.modifiers() & Qt.KeyboardModifier.ShiftModifier:
            if self._drag_axis_lock is None: delta = pos - self._drag_start_pos_widget; self._drag_axis_lock = 'y' if abs(delta.y()) > abs(delta.x()) else 'x'
            if self._drag_axis_lock == 'x': constrained_pos.setY(self._drag_start_pos_widget.y())
            else: constrained_pos.setX(self._drag_start_pos_widget.x())

        # --- Amplitude Handle Drag Logic ---
        if self._dragged_amplitude_handle_index is not None:
            seg_idx = self._dragged_amplitude_handle_index
            segment_info = self.segments[seg_idx]
            
            # Allow dragging for even multiples in alternating schemes or integer full periods in pulsating schemes
            is_even_multiple_alternating = (segment_info['num_cycles'] * 4) % 2 == 0 and "Alternating" in segment_info['scheme']
            is_integer_full_period_pulsating = (segment_info['num_cycles'] * 4) % 4 == 0 and "Pulsating" in segment_info['scheme']
            
            is_draggable = is_even_multiple_alternating or is_integer_full_period_pulsating
            if not is_draggable: return

            new_pos_w = event.position()
            new_pos_w.setX(self._drag_start_pos_widget.x()) # Constrain to vertical
            new_pos_data_y = self._norm_to_data(self._widget_to_norm(new_pos_w)).y()

            p1_d = self._norm_to_data(self.points_norm[seg_idx])
            p2_d = self._norm_to_data(self.points_norm[seg_idx+1])
            
            # Calculate y_center appropriately for the scheme type
            # For alternating schemes: y_center is the horizontal line (average of endpoints)  
            # For pulsating schemes: y_center is calculated as per original sine formula
            num_cycles = segment_info['num_cycles']
            scheme = segment_info['scheme']
            is_pulsating_scheme = "Pulsating" in scheme
            
            if is_pulsating_scheme:
                # Corrected logic for pulsating schemes.
                # The handle position represents the peak/trough. The wave oscillates around a baseline y-value (p1_d.y()).
                # The amplitude is therefore half the distance from the handle to this baseline.
                clamped_pos_data_y = max(self._min_strain, min(self._max_strain, new_pos_data_y))
                new_amplitude = abs(clamped_pos_data_y - p1_d.y()) / 2.0
            else:
                # Original logic for alternating schemes
                if "Alternating" in scheme:
                    # For alternating schemes, both endpoints should have the same y-value for even multiples (horizontal line)
                    is_even_multiple = (segment_info['num_cycles'] * 4) % 2 == 0
                    if is_even_multiple:
                        y_center = (p1_d.y() + p2_d.y()) / 2  # Use average as horizontal line
                    else:
                        # For non-even multiple alternating schemes
                        orig_amp, orig_y_center, orig_phi = self._get_sine_parameters(p1_d, p2_d, segment_info)
                        y_center = orig_y_center if orig_y_center is not None else (p1_d.y() + p2_d.y()) / 2
                else:
                    # For other schemes, calculate y_center using original method
                    orig_amp, orig_y_center, orig_phi = self._get_sine_parameters(p1_d, p2_d, segment_info)
                    y_center = orig_y_center if orig_y_center is not None else (p1_d.y() + p2_d.y()) / 2
            
            # Determine if we have enough quarter periods for potentially 2 handles
            # For alternating schemes: show second handle at >3 quarter periods (even multiple cases)
            # For pulsating schemes: show second handle at >4 quarter periods (to avoid coincidence with endpoint at 4 quarters)
            num_quarters = segment_info['num_cycles'] * 4
            is_alternating_scheme = "Alternating" in segment_info['scheme']
            is_pulsating_scheme = "Pulsating" in segment_info['scheme']
            
            if is_alternating_scheme:
                # For alternating schemes, 4+ quarter periods (even multiples) allow for second handle
                has_two_handles = num_quarters > 3
            elif is_pulsating_scheme:
                # For pulsating schemes, avoid second handle at 4 quarters since it would coincide with endpoint
                has_two_handles = num_quarters > 4
            else:
                # For other schemes
                has_two_handles = num_quarters > 3
            
            # Determine the type of pulsating scheme (tensile or compressive)
            is_pulsating_scheme = "Pulsating" in segment_info['scheme']
            is_pulsating_compressive = is_pulsating_scheme and "compressive" in segment_info['scheme'].lower()
            
            if not is_pulsating_scheme: # This block is now only for non-pulsating schemes
                if has_two_handles:
                    # With two handles, both peak and trough need to be within boundaries
                    # So calculate amplitude with constraints on both sides
                    raw_amplitude = abs(new_pos_data_y - y_center)
                    
                    # Apply proper boundary constraints: ensure the entire sine wave stays within bounds
                    # For the sine wave y = y_center + A*sin(...), the range is [y_center - A, y_center + A]
                    # So we need: y_center - A >= min_strain AND y_center + A <= max_strain
                    # Which gives us: A <= y_center - min_strain AND A <= max_strain - y_center
                    max_amplitude_for_min_bound = y_center - self._min_strain
                    max_amplitude_for_max_bound = self._max_strain - y_center
                    
                    # The valid amplitude is constrained by both bounds
                    max_valid_amplitude = min(max_amplitude_for_min_bound, max_amplitude_for_max_bound)
                    max_valid_amplitude = max(0, max_valid_amplitude)  # Ensure non-negative
                    
                    # Apply the boundary constraint to the amplitude
                    new_amplitude = min(raw_amplitude, max_valid_amplitude)
                else:
                    # With one handle, constrain only the relevant side based on current handle position
                    # For pulsating schemes, we need to consider if this is a tensile or compressive start
                    if is_pulsating_scheme and is_pulsating_compressive:
                        # For pulsating compressive, the amplitude handle typically represents the trough (minimum)
                        # So when dragging, the amplitude should be calculated from how far below the center line it is
                        if new_pos_data_y < y_center:
                            # Currently a trough handle below center, constrain lower boundary only
                            clamped_pos_data_y = max(self._min_strain, new_pos_data_y)
                            new_amplitude = abs(clamped_pos_data_y - y_center)
                        else:
                            # Currently a peak handle above center, constrain upper boundary only
                            clamped_pos_data_y = min(self._max_strain, new_pos_data_y)
                            new_amplitude = abs(clamped_pos_data_y - y_center)
                    else:
                        # For alternating schemes and pulsating tensile, handle as before
                        if new_pos_data_y > y_center:
                            # Currently a peak handle above center, constrain upper boundary only
                            clamped_pos_data_y = min(self._max_strain, new_pos_data_y)
                            new_amplitude = abs(clamped_pos_data_y - y_center)
                        else:
                            # Currently a trough handle below center, constrain lower boundary only
                            clamped_pos_data_y = max(self._min_strain, new_pos_data_y)
                            new_amplitude = abs(clamped_pos_data_y - y_center)
            
            # For even multiple alternating schemes and integer full period pulsating schemes, 
            # the horizontal line constraint is maintained elsewhere
            if is_even_multiple_alternating or is_integer_full_period_pulsating:
                # The horizontal constraint is maintained through the handle synchronization logic elsewhere, 
                # not by changing endpoints here
                pass  # Just store the amplitude value
            else:
                # For other schemes, store amplitude normally
                pass  # Just store the amplitude value
            
            self.segments[seg_idx]['amplitude'] = new_amplitude

        # --- Main Handle Drag Logic ---
        elif self._dragged_handle_index is not None:
            if self._dragged_handle_index == 0 and self.mode == 'Deformation':
                return # Don't move the first handle in deformation mode

            i = self._dragged_handle_index
            
            # --- Start: NEW PRE-PROCESSING logic for SINE handles ---
            new_p_norm = self._widget_to_norm(constrained_pos)
            y_delta_norm = new_p_norm.y() - self.points_norm[i].y()
            is_y_drag = self._drag_axis_lock != 'x'

            # Check if this handle is part of an even multiple quarter period sine segment in alternating mode
            # or an integer multiple full period sine segment in pulsating mode
            is_even_multiple_alternating = False
            is_integer_full_period_pulsating = False
            
            if i > 0 and self.segments[i-1]['type'] == 'sine':
                seg = self.segments[i-1]
                # Even multiple: 2, 4, 6, 8... quarter periods means same y-values for endpoints (alternating schemes only)
                is_even_multiple_alternating = (seg['num_cycles'] * 4) % 2 == 0 and "Alternating" in seg['scheme']
                # Integer full period: 1, 2, 3, 4... full periods means same y-values for endpoints (pulsating schemes only)
                is_integer_full_period_pulsating = (seg['num_cycles'] * 4) % 4 == 0 and "Pulsating" in seg['scheme']
                
                should_lock_y_values = is_even_multiple_alternating or is_integer_full_period_pulsating
                if should_lock_y_values:
                    # For even multiples in alternating mode or integer full periods in pulsating mode, 
                    # the line should remain horizontal
                    # So we lock both handles to the same y-value
                    self.points_norm[i-1].setY(new_p_norm.y())
                    self.points_norm[i].setY(new_p_norm.y())
            elif i < len(self.points_norm) - 1 and self.segments[i]['type'] == 'sine':
                seg = self.segments[i]
                # Even multiple: 2, 4, 6, 8... quarter periods means same y-values for endpoints (alternating schemes only)
                is_even_multiple_alternating = (seg['num_cycles'] * 4) % 2 == 0 and "Alternating" in seg['scheme']
                # Integer full period: 1, 2, 3, 4... full periods means same y-values for endpoints (pulsating schemes only)
                is_integer_full_period_pulsating = (seg['num_cycles'] * 4) % 4 == 0 and "Pulsating" in seg['scheme']
                
                should_lock_y_values = is_even_multiple_alternating or is_integer_full_period_pulsating
                if should_lock_y_values:
                    # For even multiples in alternating mode or integer full periods in pulsating mode, 
                    # the line should remain horizontal
                    # So we lock both handles to the same y-value
                    self.points_norm[i].setY(new_p_norm.y())
                    self.points_norm[i+1].setY(new_p_norm.y())
            
            # Only proceed with linked vertical drag if not in even multiple mode
            if not (is_even_multiple_alternating or is_integer_full_period_pulsating):
                # Linked vertical drag for special sine cases
                if i > 0 and self.segments[i-1]['type'] == 'sine' and is_y_drag:
                    seg = self.segments[i-1]
                    if (seg['num_cycles'] * 4) % 2 == 0 and "Alternating" in seg['scheme']:
                        self.points_norm[i-1].setY(self.points_norm[i-1].y() + y_delta_norm)
                if i < len(self.points_norm) - 1 and self.segments[i]['type'] == 'sine' and is_y_drag:
                    seg = self.segments[i]
                    if (seg['num_cycles'] * 4) % 2 == 0 and "Alternating" in seg['scheme']:
                        self.points_norm[i+1].setY(self.points_norm[i+1].y() + y_delta_norm)
            
            # Boundary clamping for the dragged handle itself (only if not in special multiple mode)
            if not (is_even_multiple_alternating or is_integer_full_period_pulsating):
                p_data_pre = self._norm_to_data(new_p_norm)
                p_data_pre.setY(max(self._min_strain, min(self._max_strain, p_data_pre.y())))
                new_p_norm = self._data_to_norm(p_data_pre)
                # Update constrained_pos to reflect clamping for subsequent logic
                constrained_pos = self._norm_to_widget(new_p_norm)
            # --- End: NEW PRE-PROCESSING logic ---

            # Check if this handle's x or y positions are locked
            x_locked = self._dragged_handle_index in self._locked_x_ticks
            y_locked = self._dragged_handle_index in self._locked_y_labels
            
            # Check if adjacent segments are fixed, which would constrain movement
            prev_segment_fixed = (self._dragged_handle_index - 1) in self._fixed_segments if self._dragged_handle_index > 0 else False
            next_segment_fixed = self._dragged_handle_index in self._fixed_segments if self._dragged_handle_index < len(self.points_norm) - 1 else False
            
            # If both x and y are locked, or if y is locked and both adjacent segments are fixed, cannot move this handle at all
            if (x_locked and y_locked) or (y_locked and prev_segment_fixed and next_segment_fixed):
                return
                
            # Cannot move handle if it's at the first or last position and has a fixed segment
            if (self._dragged_handle_index == 0 and next_segment_fixed) or (self._dragged_handle_index == len(self.points_norm) - 1 and prev_segment_fixed):
                return
                
            if self._dragged_handle_index == 0:
                if self.mode == 'Deformation':
                    # First point x is always locked in deformation mode
                    if not y_locked:  # Only allow y movement if not locked
                        constrained_pos.setX(self._drag_start_pos_widget.x())
                        # Ensure the first point stays at x=0
                        p_data = self._norm_to_data(self._widget_to_norm(constrained_pos))
                        p_data.setX(0)  # Force x to be 0 for the first point
                        # Clamp y to min/max strain values
                        p_data.setY(max(self._min_strain, min(self._max_strain, p_data.y())))
                        final_p_norm = self._data_to_norm(p_data)  # Don't snap while dragging
                        final_p_norm.setX(0)  # Ensure normalized x is also 0
                    else:
                        # Y is locked, don't move at all
                        return
                else: # Temperature mode, only allow y-drag and ensure x stays at 0
                    if not y_locked:  # Only allow y movement if not locked
                        constrained_pos.setX(self._drag_start_pos_widget.x())
                        # Ensure the first point stays at x=0
                        p_data = self._norm_to_data(self._widget_to_norm(constrained_pos))
                        p_data.setX(0)  # Force x to be 0 for the first point
                        # Clamp y to min/max strain values
                        p_data.setY(max(self._min_strain, min(self._max_strain, p_data.y())))
                        final_p_norm = self._data_to_norm(p_data)  # Don't snap while dragging
                        final_p_norm.setX(0)  # Ensure normalized x is also 0
                    else:
                        # Y is locked, don't move at all
                        return
            else:
                p_data = self._norm_to_data(self._widget_to_norm(constrained_pos))
                
                # During dragging, enforce INTEGER time step values for x-coordinate
                p_data.setX(round(p_data.x()))
                
                # Apply locking constraints
                if x_locked:
                    # X position is locked, keep the original x value
                    orig_data = self._norm_to_data(self.points_norm[self._dragged_handle_index])
                    p_data.setX(orig_data.x())
                if y_locked:
                    # Y position is locked, keep the original y value
                    orig_data = self._norm_to_data(self.points_norm[self._dragged_handle_index])
                    p_data.setY(orig_data.y())
                
                # If adjacent segments are fixed, constrain movement along the fixed slope
                movement_allowed = True
                if prev_segment_fixed and not next_segment_fixed:
                    # Only previous segment is fixed, constrain movement along its slope
                    prev_point = self._norm_to_data(self.points_norm[self._dragged_handle_index - 1])
                    current_point = self._norm_to_data(self.points_norm[self._dragged_handle_index])
                    # Calculate slope of fixed segment
                    if current_point.x() != prev_point.x():
                        slope = (current_point.y() - prev_point.y()) / (current_point.x() - prev_point.x())
                        # Constrain y position based on x position and slope (unless y is locked)
                        if not y_locked:
                            calculated_y = prev_point.y() + slope * (p_data.x() - prev_point.x())
                            # Check if we've hit min or max y
                            if calculated_y < self._min_strain or calculated_y > self._max_strain:
                                movement_allowed = False
                            # Clamp to min/max strain values
                            p_data.setY(max(self._min_strain, min(self._max_strain, calculated_y)))
                elif not prev_segment_fixed and next_segment_fixed:
                    # Only next segment is fixed, constrain movement along its slope
                    current_point = self._norm_to_data(self.points_norm[self._dragged_handle_index])
                    next_point = self._norm_to_data(self.points_norm[self._dragged_handle_index + 1])
                    # Calculate slope of fixed segment
                    if next_point.x() != current_point.x():
                        slope = (next_point.y() - current_point.y()) / (next_point.x() - current_point.x())
                        # Constrain y position based on x position and slope (unless y is locked)
                        if not y_locked:
                            calculated_y = current_point.y() + slope * (p_data.x() - current_point.x())
                            # Check if we've hit min or max y
                            if calculated_y < self._min_strain or calculated_y > self._max_strain:
                                movement_allowed = False
                            # Clamp to min/max strain values
                            p_data.setY(max(self._min_strain, min(self._max_strain, calculated_y)))
                elif prev_segment_fixed and next_segment_fixed:
                    # Both segments are fixed, constrain to the average slope
                    prev_point = self._norm_to_data(self.points_norm[self._dragged_handle_index - 1])
                    current_point = self._norm_to_data(self.points_norm[self._dragged_handle_index])
                    next_point = self._norm_to_data(self.points_norm[self._dragged_handle_index + 1])
                    # Calculate slopes of both fixed segments
                    slope1 = (current_point.y() - prev_point.y()) / (current_point.x() - prev_point.x()) if current_point.x() != prev_point.x() else 0
                    slope2 = (next_point.y() - current_point.y()) / (next_point.x() - current_point.x()) if next_point.x() != current_point.x() else 0
                    # Use average slope for constraint
                    avg_slope = (slope1 + slope2) / 2
                    # Constrain y position based on x position and average slope (unless y is locked)
                    if not y_locked:
                        # We'll use the position relative to the previous point
                        calculated_y = prev_point.y() + avg_slope * (p_data.x() - prev_point.x())
                        # Check if we've hit min or max y
                        if calculated_y < self._min_strain or calculated_y > self._max_strain:
                            movement_allowed = False
                        # Clamp to min/max strain values
                        p_data.setY(max(self._min_strain, min(self._max_strain, calculated_y)))
                    
                final_p_norm = self._data_to_norm(p_data)  # Don't snap while dragging
                
                # If we've hit min or max y while following a fixed slope, stop all movement
                if not movement_allowed:
                    orig_data = self._norm_to_data(self.points_norm[self._dragged_handle_index])
                    orig_p_norm = self._data_to_norm(orig_data)
                    final_p_norm = orig_p_norm
                
                # If y is locked or if a slope is fixed, prevent moving past neighboring points
                neighbor_hit = False
                if (y_locked or prev_segment_fixed or next_segment_fixed) and self._dragged_handle_index > 0 and self._dragged_handle_index < len(self.points_norm) - 1:
                    # Get neighboring points in normalized coordinates
                    prev_point_norm = self.points_norm[self._dragged_handle_index - 1]
                    next_point_norm = self.points_norm[self._dragged_handle_index + 1]
                    
                    # Check if we're trying to move past neighbors
                    if final_p_norm.x() <= prev_point_norm.x() or final_p_norm.x() >= next_point_norm.x():
                        neighbor_hit = True
                        # Stop all movement when hitting a neighbor
                        orig_data = self._norm_to_data(self.points_norm[self._dragged_handle_index])
                        orig_p_norm = self._data_to_norm(orig_data)
                        final_p_norm = orig_p_norm
                    else:
                        # Constrain x position to stay between neighbors
                        final_p_norm.setX(max(prev_point_norm.x(), min(next_point_norm.x(), final_p_norm.x())))
                
            if self._dragged_handle_index == len(self.points_norm) - 1:
                # Last point x is always locked to max_steps
                final_p_norm.setX(1.0)
                # Also clamp y to min/max strain values
                p_data = self._norm_to_data(final_p_norm)
                p_data.setY(max(self._min_strain, min(self._max_strain, p_data.y())))
                final_p_norm = self._data_to_norm(p_data)
                final_p_norm.setX(1.0)  # Ensure x stays locked
                
            self.points_norm[self._dragged_handle_index] = final_p_norm
            self._sort_points()
            self._dragged_handle_index = self.points_norm.index(final_p_norm)
        elif self._dragged_segment_index is not None:
            i = self._dragged_segment_index
            
            # Check if this segment is fixed
            is_segment_fixed = self._dragged_segment_index in self._fixed_segments
            
            # Check if adjacent segments are fixed
            prev_segment_fixed = (i - 1) in self._fixed_segments if i > 0 else False
            next_segment_fixed = (i + 1) in self._fixed_segments if i < len(self.points_norm) - 2 else False
            
            # If this segment is fixed, check if it can be moved
            if is_segment_fixed:
                # Cannot move fixed segment if any adjacent segment is also fixed
                if prev_segment_fixed or next_segment_fixed:
                    return
                # Otherwise, fixed segment can be moved (no adjacent fixed segments)
            
            # If adjacent segments are fixed, we need to preserve their slopes while allowing movement
            # BUT we must preserve the slope of the dragged segment itself
            if prev_segment_fixed or next_segment_fixed:
                # Get original positions
                original_p1_data = self._norm_to_data(self.points_norm[i])
                original_p2_data = self._norm_to_data(self.points_norm[i+1])
                
                # Calculate the original slope and length of the dragged segment
                original_delta_x = original_p2_data.x() - original_p1_data.x()
                original_delta_y = original_p2_data.y() - original_p1_data.y()
                
                # Calculate the new position based on mouse movement
                target_p1_w = constrained_pos - self._drag_mouse_to_p1_offset
                target_p1_data = self._norm_to_data(self._widget_to_norm(target_p1_w))
                
                # Calculate the offset (delta) from original position
                delta_x = target_p1_data.x() - original_p1_data.x()
                delta_y = target_p1_data.y() - original_p1_data.y()
                
                # Start with unconstrained new positions
                new_p1_data = QPointF(original_p1_data.x() + delta_x, original_p1_data.y() + delta_y)
                new_p2_data = QPointF(original_p2_data.x() + delta_x, original_p2_data.y() + delta_y)
                
                # During dragging, enforce INTEGER time step values for x-coordinates
                new_p1_data.setX(round(new_p1_data.x()))
                new_p2_data.setX(round(new_p2_data.x()))
                
                # Clamp y values to min/max strain
                new_p1_data.setY(max(self._min_strain, min(self._max_strain, new_p1_data.y())))
                new_p2_data.setY(max(self._min_strain, min(self._max_strain, new_p2_data.y())))
                
                # Handle constraints based on which neighbors are fixed
                # IMPORTANT: We preserve the ORIGINAL slope of the dragged segment, not calculate new slopes
                if prev_segment_fixed and next_segment_fixed:
                    # Both neighbors fixed - this case should have been caught earlier, but handle gracefully
                    # Preserve both neighbor slopes by adjusting the connecting points
                    if i > 1:
                        prev_prev_point_data = self._norm_to_data(self.points_norm[i-2])
                        prev_point_data = self._norm_to_data(self.points_norm[i-1])
                        if prev_point_data.x() != prev_prev_point_data.x():
                            original_slope = (prev_point_data.y() - prev_prev_point_data.y()) / (prev_point_data.x() - prev_prev_point_data.x())
                            new_p1_data.setY(prev_prev_point_data.y() + original_slope * (new_p1_data.x() - prev_prev_point_data.x()))
                    if i + 2 < len(self.points_norm):
                        next_point_data = self._norm_to_data(self.points_norm[i+1])
                        next_next_point_data = self._norm_to_data(self.points_norm[i+2])
                        if next_next_point_data.x() != next_point_data.x():
                            original_slope = (next_next_point_data.y() - next_point_data.y()) / (next_next_point_data.x() - next_point_data.x())
                            new_p2_data.setY(next_point_data.y() + original_slope * (new_p2_data.x() - next_point_data.x()))
                    # Preserve the original slope of the dragged segment
                    new_p2_data.setX(new_p1_data.x() + original_delta_x)
                    new_p2_data.setY(new_p1_data.y() + original_delta_y)
                elif prev_segment_fixed:
                    # Previous neighbor fixed - preserve its slope
                    if i > 1:
                        prev_prev_point_data = self._norm_to_data(self.points_norm[i-2])
                        prev_point_data = self._norm_to_data(self.points_norm[i-1])
                        if prev_point_data.x() != prev_prev_point_data.x():
                            original_slope = (prev_point_data.y() - prev_prev_point_data.y()) / (prev_point_data.x() - prev_prev_point_data.x())
                            new_p1_data.setY(prev_prev_point_data.y() + original_slope * (new_p1_data.x() - prev_prev_point_data.x()))
                    # Preserve the original slope of the dragged segment by maintaining delta
                    new_p2_data.setX(new_p1_data.x() + original_delta_x)
                    new_p2_data.setY(new_p1_data.y() + original_delta_y)
                elif next_segment_fixed:
                    # Next neighbor fixed - preserve its slope
                    if i + 2 < len(self.points_norm):
                        next_point_data = self._norm_to_data(self.points_norm[i+1])
                        next_next_point_data = self._norm_to_data(self.points_norm[i+2])
                        if next_next_point_data.x() != next_point_data.x():
                            original_slope = (next_next_point_data.y() - next_point_data.y()) / (next_next_point_data.x() - next_point_data.x())
                            new_p2_data.setY(next_point_data.y() + original_slope * (new_p2_data.x() - next_point_data.x()))
                    # Preserve the original slope of the dragged segment by maintaining delta
                    new_p1_data.setX(new_p2_data.x() - original_delta_x)
                    new_p1_data.setY(new_p2_data.y() - original_delta_y)
                
                # Convert to normalized coordinates
                new_p1_norm = self._data_to_norm(new_p1_data)
                new_p2_norm = self._data_to_norm(new_p2_data)
                
                # Check bounds constraints
                p_prev = self.points_norm[i-1] if i > 0 else None
                p_next = self.points_norm[i+2] if i < len(self.points_norm) - 2 else None
                if (p_prev is None or new_p1_norm.x() >= p_prev.x()) and (p_next is None or new_p2_norm.x() <= p_next.x()) and all(0.0 <= p.y() <= 1.0 for p in [new_p1_norm, new_p2_norm]):
                    self.points_norm[i] = new_p1_norm
                    self.points_norm[i+1] = new_p2_norm
            else:
                # Normal segment dragging when no adjacent segments are fixed
                if i == 0:
                    p1_new_norm = self._data_to_norm(self._norm_to_data(self._widget_to_norm(constrained_pos - self._drag_mouse_to_p1_offset)))
                    p1_new_norm.setX(0)  # Ensure first point stays at x=0
                    self.points_norm[i] = p1_new_norm
                else:
                    target_p1_w = constrained_pos - self._drag_mouse_to_p1_offset
                    p1_new_data = self._norm_to_data(self._widget_to_norm(target_p1_w))  # Don't snap while dragging
                    # During dragging, enforce INTEGER time step values for x-coordinate
                    p1_new_data.setX(round(p1_new_data.x()))
                    p1_new_norm = self._data_to_norm(p1_new_data)
                    
                    # --- Start: NEW logic for boundary clamping for SINE segments ---
                    p2_new_norm = p1_new_norm + self._segment_drag_offset_norm
                    p2_new_data = self._norm_to_data(p2_new_norm)
                    min_y_data = min(p1_new_data.y(), p2_new_data.y())
                    max_y_data = max(p1_new_data.y(), p2_new_data.y())
                    
                    if self.segments[i]['type'] == 'sine':
                        # Use the improved method that handles stored amplitude appropriately
                        amp, y_center, _ = self._get_sine_parameters_with_stored_amp(p1_new_data, p2_new_data, self.segments[i], i)
                        
                        if amp is not None:
                            min_y_data = min(min_y_data, y_center - abs(amp))
                            max_y_data = max(max_y_data, y_center + abs(amp))

                    y_offset_data = 0
                    if max_y_data > self._max_strain:
                        y_offset_data = max_y_data - self._max_strain
                    if min_y_data < self._min_strain:
                        y_offset_data = min_y_data - self._min_strain
                    # Clamp new data before proceeding
                    p1_new_data.setY(p1_new_data.y() - y_offset_data)
                    # --- End: NEW logic ---

                    # Clamp y values to min/max strain
                    p1_new_data.setY(max(self._min_strain, min(self._max_strain, p1_new_data.y())))
                    p1_new_norm = self._data_to_norm(p1_new_data)
                    p2_new_norm = p1_new_norm + self._segment_drag_offset_norm
                    # Also clamp the second point
                    p2_new_data = self._norm_to_data(p2_new_norm)
                    p2_new_data.setY(max(self._min_strain, min(self._max_strain, p2_new_data.y())))
                    p2_new_norm = self._data_to_norm(p2_new_data)
                    p_prev = self.points_norm[i-1] if i > 0 else None
                    p_next = self.points_norm[i+2] if i < len(self.points_norm) - 2 else None
                    if (p_prev is None or p1_new_norm.x() >= p_prev.x()) and (p_next is None or p2_new_norm.x() <= p_next.x()) and all(0.0 <= p.y() <= 1.0 for p in [p1_new_norm, p2_new_norm]):
                        self.points_norm[i], self.points_norm[i+1] = p1_new_norm, p2_new_norm
        self.update()

    def mouseReleaseEvent(self, event): 
        # When mouse is released, preserve the exact position from dragging
        # During dragging, x-coordinates are rounded to integers, so the final position will be integer
        # The user wants values to change during dragging (with integer time steps in x direction)
        # but after release, no changes should happen anymore
        if self._dragged_handle_index is not None:
            # Check if adjacent segments are fixed 
            prev_segment_fixed = (self._dragged_handle_index - 1) in self._fixed_segments if self._dragged_handle_index > 0 else False
            next_segment_fixed = self._dragged_handle_index in self._fixed_segments if self._dragged_handle_index < len(self.points_norm) - 1 else False
            
            # Check if this handle's y position is locked
            y_locked = self._dragged_handle_index in self._locked_y_labels
            
            # Check if this handle is part of an even multiple sine segment in alternating mode
            is_even_multiple = False
            if self._dragged_handle_index > 0 and self.segments[self._dragged_handle_index-1]['type'] == 'sine':
                seg = self.segments[self._dragged_handle_index-1]
                if (seg['num_cycles'] * 4) % 2 == 0 and "Alternating" in seg['scheme']:
                    is_even_multiple = True
            elif self._dragged_handle_index < len(self.points_norm) - 1 and self.segments[self._dragged_handle_index]['type'] == 'sine':
                seg = self.segments[self._dragged_handle_index]
                if (seg['num_cycles'] * 4) % 2 == 0 and "Alternating" in seg['scheme']:
                    is_even_multiple = True
            
            # Preserve exact position when releasing, which should already have integer x-coordinates
            # Only apply constraints like fixed position at boundaries, but don't apply grid snapping
            preserved_p_norm = self.points_norm[self._dragged_handle_index]
            
            # Ensure first point stays at x=0
            if self._dragged_handle_index == 0:
                preserved_p_norm.setX(0)
                
            # Ensure last point stays at max x
            if self._dragged_handle_index == len(self.points_norm) - 1:
                preserved_p_norm.setX(1.0)
                
            # If in even multiple alternating mode, ensure both handles stay at same y-value
            if is_even_multiple:
                if self._dragged_handle_index > 0 and self.segments[self._dragged_handle_index-1]['type'] == 'sine':
                    # Left segment is sine with even multiple alternating mode
                    self.points_norm[self._dragged_handle_index-1].setY(preserved_p_norm.y())
                    self.points_norm[self._dragged_handle_index].setY(preserved_p_norm.y())
                elif self._dragged_handle_index < len(self.points_norm) - 1 and self.segments[self._dragged_handle_index]['type'] == 'sine':
                    # Right segment is sine with even multiple alternating mode
                    self.points_norm[self._dragged_handle_index].setY(preserved_p_norm.y())
                    self.points_norm[self._dragged_handle_index+1].setY(preserved_p_norm.y())
            else:
                self.points_norm[self._dragged_handle_index] = preserved_p_norm
                
            self._sort_points()
            
        elif self._dragged_segment_index is not None:
            i = self._dragged_segment_index
            
            # Check if adjacent segments are fixed
            prev_segment_fixed = (i - 1) in self._fixed_segments if i > 0 else False
            next_segment_fixed = (i + 1) in self._fixed_segments if i < len(self.points_norm) - 2 else False
            
            if i < len(self.points_norm) - 1:
                # Preserve exact positions when releasing - no additional snapping
                if prev_segment_fixed or next_segment_fixed:
                    # Preserve exact positions when adjacent segments are fixed
                    # to maintain their slopes
                    pass  # Keep exact positions
                else:
                    # Keep exact positions from dragging
                    pass  # Keep exact positions
                
                # Ensure first point stays at x=0 if it's the first segment
                if i == 0:
                    self.points_norm[i].setX(0)
                    
                self._sort_points()
        
        # Ensure the first point stays at x=0 for both modes
        if len(self.points_norm) > 0:
            self.points_norm[0].setX(0)
            
        # Clear all dragging state to ensure no further changes happen after release
        self._dragged_handle_index, self._dragged_segment_index, self._drag_start_pos_widget, self._drag_axis_lock, self._dragged_amplitude_handle_index = None, None, None, None, None
        self.dataChanged.emit()
    def mouseDoubleClickEvent(self, event):
        if event.button() == Qt.MouseButton.LeftButton:
            # 1. Check if a clickable region (slope, x_val, y_val) is hit
            for region, type, index in self._clickable_regions:
                if region.contains(event.position()):
                    self._handle_direct_edit(type, index)
                    return
            
            # 2. Check if a segment is hit
            seg_idx = self._get_segment_at(event.position())
            if seg_idx is not None:
                segment_info = self.segments[seg_idx]
                if segment_info['type'] == 'line':
                    # Split the line segment by adding a new point
                    new_p_norm = self._data_to_norm(self._snap_data_point(self._norm_to_data(self._widget_to_norm(event.position()))))
                    self.points_norm.append(new_p_norm)
                    self._sort_points()
                    # The segment at seg_idx was split. Replace it with a line and insert another line.
                    self.segments[seg_idx] = {'type': 'line'}
                    self.segments.insert(seg_idx + 1, {'type': 'line'})
                    self.update()
                    self.dataChanged.emit()
                elif segment_info['type'] == 'sine':
                    self._show_sine_properties_dialog(seg_idx)
                return # Event handled

            # 3. If nothing else is hit, add a new point at the clicked position
            new_p_norm = self._data_to_norm(self._snap_data_point(self._norm_to_data(self._widget_to_norm(event.position()))))
            self.points_norm.append(new_p_norm)
            self._sort_points()
            # A new point was added. It creates a new segment at the end.
            self.segments.append({'type': 'line'})
            self.update()
            self.dataChanged.emit()
    def contextMenuEvent(self, event):
        idx = self._get_handle_at(QPointF(event.pos()))
        if idx is not None:
            menu = QMenu(self); menu.addAction("Set Coordinates...", lambda: self._show_set_coords_dialog(idx))
            if 0 < idx < len(self.points_norm) - 1: menu.addAction("Delete Handle", lambda: self._delete_handle(idx))
            menu.exec(event.globalPos())
        else: # Check for segment
            seg_idx = self._get_segment_at(QPointF(event.pos()))
            if seg_idx is not None:
                menu = QMenu(self)
                if self.segments[seg_idx]['type'] == 'line':
                    if self.mode != 'Temperature':
                        menu.addAction("Insert Sine...", lambda: self._show_insert_sine_dialog(seg_idx))
                elif self.segments[seg_idx]['type'] == 'sine':
                    menu.addAction("Edit Sine Properties...", lambda: self._show_sine_properties_dialog(seg_idx))
                    menu.addAction("Change to Line", lambda: self._change_segment_type(seg_idx, 'line'))
                menu.exec(event.globalPos())

    def _change_segment_type(self, seg_idx, new_type):
        self.segments[seg_idx]['type'] = new_type
        self.update()
        self.dataChanged.emit()

    def _show_insert_sine_dialog(self, seg_idx):
        self._context_menu_segment_index = seg_idx
        dialog = InsertSineDialog(self)
        if dialog.exec():
            params = dialog.get_parameters()
            seg_idx = self._context_menu_segment_index
            if seg_idx is not None:
                # 1. Get existing points
                p1_d = self._norm_to_data(self.points_norm[seg_idx])

                # 2. Calculate the correct end Y-value based on the start point
                num_cycles = params['num_cycles']
                scheme = params['scheme']

                amplitude = min(abs(self._max_strain), abs(self._min_strain))
                if amplitude == 0: amplitude = max(abs(self._max_strain), abs(self._min_strain))
                if amplitude == 0: amplitude = 0.1

                phi_start = 0
                y_center_offset = 0
                y_baseline = p1_d.y()

                if "Alternating" in scheme:
                    if "compressive start" in scheme:
                        amplitude *= -1
                elif "Pulsating tensile" in scheme:
                    y_center_offset = amplitude
                    phi_start = -math.pi / 2
                elif "Pulsating compressive" in scheme:
                    y_center_offset = -amplitude
                    phi_start = math.pi / 2

                end_angle = num_cycles * 2 * math.pi + phi_start
                y_end_relative = amplitude * math.sin(end_angle)
                new_y2 = y_baseline + y_center_offset + y_end_relative

                # 3. Update the right handle's position
                self.points_norm[seg_idx + 1].setY(self._data_to_norm(QPointF(0, new_y2)).y())

                # 4. Update segment type
                self.segments[seg_idx] = {
                    'type': 'sine',
                    'num_cycles': num_cycles,
                    'scheme': scheme,
                    'amplitude': amplitude
                }

                # If it's an even quarter-period in alternating mode, ensure both handles have the same y-value (horizontal line)
                is_alternating_mode = "Alternating" in scheme
                if (num_cycles * 4) % 2 == 0 and is_alternating_mode:
                    p1_y_norm = self.points_norm[seg_idx].y()
                    self.points_norm[seg_idx + 1].setY(p1_y_norm)

                self.update()
                self.dataChanged.emit()

    def _show_sine_properties_dialog(self, seg_idx):
        segment_info = self.segments[seg_idx]
        dialog = SinePropertiesDialog(segment_info, self)
        if dialog.exec():
            new_params = dialog.get_parameters()
            self.segments[seg_idx] = {
                'type': 'sine',
                'num_cycles': new_params['num_cycles'],
                'scheme': new_params['scheme']
            }

            # Recalculate the end-point y-value using the current stored amplitude if available
            p1_d = self._norm_to_data(self.points_norm[seg_idx])
            p2_d = self._norm_to_data(self.points_norm[seg_idx + 1])
            
            # Use the stored amplitude if available, otherwise calculate from endpoints
            amplitude, y_center, phi_start = self._get_sine_parameters_with_stored_amp(p1_d, p2_d, self.segments[seg_idx], seg_idx)
            if amplitude is not None:
                num_cycles = new_params['num_cycles']
                end_angle = num_cycles * 2 * math.pi + phi_start
                new_y2 = y_center + amplitude * math.sin(end_angle)

                p2_d.setY(new_y2)
                self.points_norm[seg_idx + 1] = self._data_to_norm(p2_d)

            # If it's an even quarter-period in alternating mode, ensure both handles have the same y-value (horizontal line)
            if (num_cycles * 4) % 2 == 0 and "Alternating" in new_params['scheme']:
                p1_y_norm = self.points_norm[seg_idx].y()
                self.points_norm[seg_idx + 1].setY(p1_y_norm)

            self.update()
            self.dataChanged.emit()
            self.update()
            self.dataChanged.emit()
    def _handle_direct_edit(self, type, index):
        if index == 0 and type == "x_val": return
        if index == 0 and type == "y_val" and self.mode == 'Deformation': return

        p_data = self._norm_to_data(self.points_norm[index])
        if type == "y_val":
            title = "Set Temperature" if self.mode == 'Temperature' else "Set Strain"
            label = "New Temperature Value:" if self.mode == 'Temperature' else "New Strain Value:"
            new_val, ok = QInputDialog.getDouble(self, title, label, p_data.y(), self._min_strain, self._max_strain, 4, flags=Qt.WindowType.Dialog, step=max(0.001, abs(p_data.y())*0.02) if p_data.y() != 0 else 0.001)
            if ok: p_data.setY(new_val)
        elif type == "x_val" and 0 < index < len(self.points_norm) - 1:
            dialog = TimeEditDialog(p_data.x(), self._timestep, self._max_steps, self);
            if dialog.exec(): p_data.setX(float(dialog.get_step()))
        elif type == "slope":
            dialog = SlopeEditDialog(*self.get_data_points()[index:index+2], self._timestep, self._time_unit, self)
            if dialog.exec():
                p1_data, p2_data = self.get_data_points()[index], self.get_data_points()[index+1]
                p2_data.setY(max(self._min_strain, min(self._max_strain, p1_data.y() + dialog.get_slope() * (p2_data.x() - p1_data.x()))))
                # Ensure first point stays at x=0
                if index == 0:
                    p1_data.setX(0)
                self.points_norm[index] = self._data_to_norm(p1_data)
                self.points_norm[index+1] = self._data_to_norm(p2_data)
        elif type == "amplitude_label":
            if index < len(self.segments) and self.segments[index]['type'] == 'sine':
                p1_d = self._norm_to_data(self.points_norm[index])
                segment_info = self.segments[index]
                scheme = segment_info['scheme']

                # Get stored amplitude
                current_amplitude = self.segments[index].get('amplitude')
                if current_amplitude is None:
                    # Fallback if not stored
                    p2_d = self._norm_to_data(self.points_norm[index+1])
                    orig_amp, _, _ = self._get_sine_parameters(p1_d, p2_d, segment_info)
                    current_amplitude = abs(orig_amp) if orig_amp is not None else 0.0

                # Calculate the correct center of oscillation for the dialog
                if "Pulsating" in scheme:
                    if "tensile" in scheme:
                        y_center = p1_d.y() + current_amplitude
                    else:  # compressive
                        y_center = p1_d.y() - current_amplitude
                else:  # Alternating
                    y_center = p1_d.y()

                # Create and show the amplitude edit dialog
                dialog = AmplitudeEditDialog(y_center, current_amplitude, self._min_strain, self._max_strain, scheme, self)
                if dialog.exec():
                    new_amp = dialog.get_amplitude()
                    self.segments[index]['amplitude'] = new_amp
                    self.update()
                    self.dataChanged.emit()
                return # Return to avoid falling through
        
        self.points_norm[index] = self._data_to_norm(p_data)
        
        # Check if this handle is part of an even multiple sine segment in alternating mode
        # or an integer full period sine segment in pulsating mode
        # If so, synchronize the other handle
        if type == "y_val":  # Only synchronize for y-value changes
            # Check left segment (index > 0)
            if index > 0:
                left_segment_idx = index - 1
                if left_segment_idx < len(self.segments) and self.segments[left_segment_idx]['type'] == 'sine':
                    num_cycles = self.segments[left_segment_idx]['num_cycles']
                    scheme = self.segments[left_segment_idx]['scheme']
                    is_even_multiple_alternating = (num_cycles * 4) % 2 == 0 and "Alternating" in scheme
                    is_integer_full_period_pulsating = (num_cycles * 4) % 4 == 0 and "Pulsating" in scheme
                    if is_even_multiple_alternating or is_integer_full_period_pulsating:
                        # This is the right handle of the sine segment, update the left handle to match y
                        self.points_norm[left_segment_idx].setY(self._data_to_norm(p_data).y())
            # Check right segment (index < len(self.segments))
            if index < len(self.segments):
                right_segment_idx = index
                if self.segments[right_segment_idx]['type'] == 'sine':
                    num_cycles = self.segments[right_segment_idx]['num_cycles']
                    scheme = self.segments[right_segment_idx]['scheme']
                    is_even_multiple_alternating = (num_cycles * 4) % 2 == 0 and "Alternating" in scheme
                    is_integer_full_period_pulsating = (num_cycles * 4) % 4 == 0 and "Pulsating" in scheme
                    if is_even_multiple_alternating or is_integer_full_period_pulsating:
                        # This is the left handle of the sine segment, update the right handle to match y
                        self.points_norm[right_segment_idx + 1].setY(self._data_to_norm(p_data).y())
        
        self._sort_points(); self.update(); self.dataChanged.emit()
    def _show_set_coords_dialog(self, index):
        p_data = self._norm_to_data(self.points_norm[index])
        dialog = CoordinateDialog(index, p_data.x(), p_data.y(), self._max_steps, self._min_strain, self._max_strain, self)
        if dialog.exec():
            step, strain = dialog.get_coordinates()
            # For the first point, always force step to 0
            if index == 0:
                step = 0
            new_p_data = QPointF(float(step), strain)
            if index == len(self.points_norm) - 1:
                new_p_data.setX(float(self._max_steps))
            self.points_norm[index] = self._data_to_norm(new_p_data)
            
            # Check if this handle is part of a sine segment with even multiple in alternating mode
            # If so, synchronize the other handle
            # Check left segment (index > 0)
            if index > 0:
                left_segment_idx = index - 1
                if left_segment_idx < len(self.segments) and self.segments[left_segment_idx]['type'] == 'sine':
                    num_cycles = self.segments[left_segment_idx]['num_cycles']
                    scheme = self.segments[left_segment_idx]['scheme']
                    is_even_multiple = (num_cycles * 4) % 2 == 0
                    is_alternating_mode = "Alternating" in scheme
                    if is_even_multiple and is_alternating_mode:
                        # This is the right handle of the sine segment, update the left handle to match y
                        self.points_norm[left_segment_idx].setY(self._data_to_norm(new_p_data).y())
            # Check right segment (index < len(self.segments))
            if index < len(self.segments):
                right_segment_idx = index
                if self.segments[right_segment_idx]['type'] == 'sine':
                    num_cycles = self.segments[right_segment_idx]['num_cycles']
                    scheme = self.segments[right_segment_idx]['scheme']
                    is_even_multiple = (num_cycles * 4) % 2 == 0
                    is_alternating_mode = "Alternating" in scheme
                    if is_even_multiple and is_alternating_mode:
                        # This is the left handle of the sine segment, update the right handle to match y
                        self.points_norm[right_segment_idx + 1].setY(self._data_to_norm(new_p_data).y())
            
            self._sort_points()
            self.update()
            self.dataChanged.emit()
    def _delete_handle(self, index):
        if 0 < index < len(self.points_norm) - 1:
            del self.points_norm[index]
            # Merge segments: remove the two segments adjacent to the handle
            # and replace them with a single line segment.
            if index -1 < len(self.segments):
                del self.segments[index-1] # remove the second segment first
            if index -1 < len(self.segments):
                self.segments[index-1] = {'type': 'line'} # replace the first segment

            self.update()
            self.dataChanged.emit()

class StudyWidget(QWidget):
    dataChanged = pyqtSignal()
    def __init__(self, initial_state=None, parent=None):
        super().__init__(parent)
        self.is_enabled = True
        self.mode = "Deformation"
        layout = QVBoxLayout(self)
        layout.setContentsMargins(5,5,5,5)
        layout.setSpacing(2)
        controls_layout = QHBoxLayout()
        self.max_steps_spinbox = QSpinBox(); self.max_steps_spinbox.setPrefix("Max Steps: "); self.max_steps_spinbox.setRange(1, 2147483647); self.max_steps_spinbox.setValue(100); self.max_steps_spinbox.setKeyboardTracking(False)
        self.min_strain_spinbox = QDoubleSpinBox(); self.min_strain_spinbox.setPrefix("Min Strain: "); self.min_strain_spinbox.setRange(-0.999999, 1e9); self.min_strain_spinbox.setValue(0.0); self.min_strain_spinbox.setDecimals(3); self.min_strain_spinbox.setKeyboardTracking(False)
        self.max_strain_spinbox = QDoubleSpinBox(); self.max_strain_spinbox.setPrefix("Max Strain: "); self.max_strain_spinbox.setRange(-1e9, 1e9); self.max_strain_spinbox.setValue(1.0); self.max_strain_spinbox.setDecimals(3); self.max_strain_spinbox.setKeyboardTracking(False)

        # Make the Min/Max Strain fields shorter (20% shorter)
        self.min_strain_spinbox.setMaximumWidth(120)
        self.max_strain_spinbox.setMaximumWidth(120)

        self.undo_button = QPushButton("↩"); self.redo_button = QPushButton("↪")
        self.generate_button = QPushButton("Generate Scheme..."); self.reset_button = QPushButton("Reset Graph")
        
        # Remove all custom styles
        self.undo_button.setStyleSheet("")
        self.redo_button.setStyleSheet("")
        self.generate_button.setStyleSheet("")
        self.reset_button.setStyleSheet("")

        controls_layout.addWidget(QLabel("<b>Axis Controls:</b>"))
        controls_layout.addWidget(self.max_steps_spinbox)
        controls_layout.addWidget(self.min_strain_spinbox)
        controls_layout.addWidget(self.max_strain_spinbox)
        
        self.deform_axis_label = QLabel("<b>Deform Direction:</b>")
        self.deform_axis_combo = QComboBox()
        self.deform_axis_combo.addItems(["x", "y", "z", "xy", "xz", "yz"])
        self.deform_axis_combo.setMinimumWidth(40)
        self.deform_axis_combo.setMaximumWidth(50)
        self.deform_axis_combo.setStyleSheet("""
            QComboBox {
                combobox-popup: 0;
            }
            QComboBox QAbstractItemView {
                background-color: white;
                selection-background-color: #007acc;
                selection-color: white;
            }
        """)

        self.deform_scenario_label = QLabel("<b>Deform Scenario:</b>")
        self.deform_scenario_combo = QComboBox()
        self.deform_scenario_combo.addItems(["symmetric", "shift hi, fix lo", "shift lo, fix hi"])
        self.deform_scenario_combo.setStyleSheet("""
            QComboBox {
                combobox-popup: 0;
            }
            QComboBox QAbstractItemView {
                background-color: white;
                selection-background-color: #007acc;
                selection-color: white;
            }
        """)
        
        controls_layout.addSpacing(5)
        controls_layout.addWidget(self.deform_axis_label)
        controls_layout.addWidget(self.deform_axis_combo)
        controls_layout.addSpacing(5)
        controls_layout.addWidget(self.deform_scenario_label)
        controls_layout.addWidget(self.deform_scenario_combo)

        controls_layout.addStretch()  # Push buttons to the right
        # Add buttons with right alignment
        controls_layout.addWidget(self.undo_button)
        controls_layout.addWidget(self.redo_button)
        controls_layout.addWidget(self.generate_button)
        controls_layout.addWidget(self.reset_button)

        # Empty layout for thermo controls (thermo freq has been moved to output tab)
        deform_direc_thermo_layout = QHBoxLayout()
        deform_direc_thermo_layout.addStretch()

        self.graph_widget = GraphWidget(self)

        layout.addLayout(controls_layout)
        layout.addLayout(deform_direc_thermo_layout)
        layout.addWidget(self.graph_widget)

        # Ensemble Settings
        ensemble_layout = QHBoxLayout()
        ensemble_layout.setContentsMargins(0, 0, 0, 0)
        ensemble_layout.setSpacing(5)

        self.ensemble_combo = QComboBox()
        self.ensemble_combo.addItems(["NVT", "NPT"])
        self.ensemble_combo.setToolTip("Select the thermodynamic ensemble for the simulation")
        self.ensemble_combo.setFixedWidth(70)
        ensemble_layout.addWidget(QLabel("Ensemble:"))
        ensemble_layout.addWidget(self.ensemble_combo)

        ensemble_urls = [QUrl("https://docs.lammps.org/fix_nvt.html"), QUrl("https://docs.lammps.org/fix_nh.html")]
        ensemble_tooltip = "Click to open LAMMPS documentation for NVT and NPT ensembles"
        self.ensemble_info_label = create_info_icon_label(ensemble_urls, ensemble_tooltip, "blue")
        ensemble_layout.addWidget(self.ensemble_info_label)

        self.temp_spinbox = QDoubleSpinBox()
        self.temp_spinbox.setPrefix("Temperature: ")
        self.temp_spinbox.setRange(0, 10000)
        self.temp_spinbox.setValue(300.0)
        self.temp_spinbox.setSingleStep(10.0)
        self.temp_spinbox.setToolTip("Temperature for the simulation")
        self.temp_spinbox.setFixedWidth(150)
        ensemble_layout.addWidget(self.temp_spinbox)

        self.pressure_spinbox = QDoubleSpinBox()
        self.pressure_spinbox.setPrefix("P: ")
        self.pressure_spinbox.setRange(-100000, 100000)
        self.pressure_spinbox.setValue(1.0)
        self.pressure_spinbox.setDecimals(4)
        self.pressure_spinbox.setToolTip("Target pressure for NPT ensemble")
        self.pressure_spinbox.setFixedWidth(100)
        ensemble_layout.addWidget(self.pressure_spinbox)

        # NPT Anisotropic dropdown (only visible when NPT is selected)
        self.npt_aniso_label = QLabel("NPT Aniso:")
        self.npt_aniso_combo = QComboBox()
        self.npt_aniso_combo.addItems(["iso", "aniso", "tri"])
        self.npt_aniso_combo.setToolTip("Select NPT anisotropic option for the simulation")
        self.npt_aniso_combo.setFixedWidth(70)
        self.npt_aniso_label.setVisible(False)
        self.npt_aniso_combo.setVisible(False)
        ensemble_layout.addWidget(self.npt_aniso_label)
        ensemble_layout.addWidget(self.npt_aniso_combo)

        ensemble_layout.addStretch(1)

        self.sync_ensemble_checkbox = QCheckBox("Sync ensemble")
        self.sync_ensemble_checkbox.setToolTip("Synchronize ensemble settings across all studies")
        ensemble_layout.addWidget(self.sync_ensemble_checkbox)

        layout.addLayout(ensemble_layout)

        # Bond Breakage Controls
        bond_breakage_layout = QHBoxLayout()
        bond_breakage_layout.setContentsMargins(0, 0, 0, 0) # No margins for a compact look
        bond_breakage_layout.setSpacing(5) # Small spacing between elements

        self.enable_bond_breakage_checkbox = QCheckBox("Enable Bond Breakage")
        self.enable_bond_breakage_checkbox.setToolTip("Enable bond breakage during deformation simulation")
        bond_breakage_layout.addWidget(self.enable_bond_breakage_checkbox)

        self.nevery_spinbox = QSpinBox()
        self.nevery_spinbox.setPrefix("Nevery: ")
        self.nevery_spinbox.setRange(1, 1000000)
        self.nevery_spinbox.setValue(1)
        self.nevery_spinbox.setToolTip("Attempt bond breaking every this many steps")
        self.nevery_spinbox.setFixedWidth(100) # Adjust width
        bond_breakage_layout.addWidget(self.nevery_spinbox)

        self.bondtype_spinbox = QSpinBox()
        self.bondtype_spinbox.setPrefix("Bond Type: ")
        self.bondtype_spinbox.setRange(1, 100)
        self.bondtype_spinbox.setValue(1)
        self.bondtype_spinbox.setToolTip("Type of bonds to break (integer or type label)")
        self.bondtype_spinbox.setFixedWidth(100) # Adjust width
        bond_breakage_layout.addWidget(self.bondtype_spinbox)

        self.rmax_spinbox = QDoubleSpinBox()
        self.rmax_spinbox.setPrefix("Rmax: ")
        self.rmax_spinbox.setRange(0, 1000)
        self.rmax_spinbox.setValue(1.5)
        self.rmax_spinbox.setSingleStep(0.1)
        self.rmax_spinbox.setToolTip("Bond longer than Rmax can break (distance units)")
        self.rmax_spinbox.setFixedWidth(100) # Adjust width
        bond_breakage_layout.addWidget(self.rmax_spinbox)

        self.enable_prob_checkbox = QCheckBox("Enable Probability")
        self.enable_prob_checkbox.setToolTip("Enable probabilistic bond breakage")
        bond_breakage_layout.addWidget(self.enable_prob_checkbox)

        self.prob_fraction_spinbox = QDoubleSpinBox()
        self.prob_fraction_spinbox.setPrefix("Prob: ")
        self.prob_fraction_spinbox.setRange(0, 1)
        self.prob_fraction_spinbox.setValue(0.1)
        self.prob_fraction_spinbox.setSingleStep(0.01)
        self.prob_fraction_spinbox.setToolTip("Break a bond with this probability if otherwise eligible")
        self.prob_fraction_spinbox.setFixedWidth(100) # Adjust width
        bond_breakage_layout.addWidget(self.prob_fraction_spinbox)

        self.prob_seed_spinbox = QSpinBox()
        self.prob_seed_spinbox.setPrefix("Seed: ")
        self.prob_seed_spinbox.setRange(1, 1000000)
        self.prob_seed_spinbox.setValue(12345)
        self.prob_seed_spinbox.setToolTip("Random number seed (positive integer)")
        self.prob_seed_spinbox.setFixedWidth(100) # Adjust width
        bond_breakage_layout.addWidget(self.prob_seed_spinbox)

        # Add info icon for bond breakage
        bond_break_url = QUrl("https://docs.lammps.org/fix_bond_break.html")
        bond_break_tooltip = "Click to open LAMMPS fix bond/break documentation"
        self.bond_break_info_label = create_info_icon_label(bond_break_url, bond_break_tooltip, "blue")
        bond_breakage_layout.addWidget(self.bond_break_info_label)

        bond_breakage_layout.addStretch(1) # Push sync button to the right

        self.sync_bond_break_checkbox = QCheckBox("Sync bond break")
        self.sync_bond_break_checkbox.setToolTip("Synchronize bond breakage settings across all studies")
        bond_breakage_layout.addWidget(self.sync_bond_break_checkbox)

        layout.addLayout(bond_breakage_layout) # Add the new bond breakage layout to the main layout

        # Connect signals for ensemble settings
        self.ensemble_combo.currentTextChanged.connect(self._on_ensemble_setting_changed)
        self.temp_spinbox.valueChanged.connect(self._on_ensemble_setting_changed)
        self.pressure_spinbox.valueChanged.connect(self._on_ensemble_setting_changed)
        self.npt_aniso_combo.currentTextChanged.connect(self._on_ensemble_setting_changed)
        self.sync_ensemble_checkbox.stateChanged.connect(self._on_ensemble_setting_changed)

        # Connect signals for bond breakage controls
        self.enable_bond_breakage_checkbox.stateChanged.connect(self._update_bond_breakage_ui_state)
        self.enable_prob_checkbox.stateChanged.connect(self._update_bond_breakage_ui_state)

        # Connect all bond breakage controls to a common handler for sync logic
        self.enable_bond_breakage_checkbox.stateChanged.connect(self._on_bond_breakage_setting_changed)
        self.nevery_spinbox.valueChanged.connect(self._on_bond_breakage_setting_changed)
        self.bondtype_spinbox.valueChanged.connect(self._on_bond_breakage_setting_changed)
        self.rmax_spinbox.valueChanged.connect(self._on_bond_breakage_setting_changed)
        self.enable_prob_checkbox.stateChanged.connect(self._on_bond_breakage_setting_changed)
        self.prob_fraction_spinbox.valueChanged.connect(self._on_bond_breakage_setting_changed)
        self.prob_seed_spinbox.valueChanged.connect(self._on_bond_breakage_setting_changed)
        self.sync_bond_break_checkbox.stateChanged.connect(self._on_bond_breakage_setting_changed)

        # Initial UI state update for bond breakage controls
        self._update_ensemble_ui_state()
        self._update_bond_breakage_ui_state()

        self._last_staircase_params = {'cycles': 5, 'factor': 1.0, 'direction': 'Tension'}
        self._last_cyclic_params = {'cycles': 3, 'relax_factor': 0.0, 'start_with': 'Tension'}
        self._last_sinusoidal_params = {'equilibration_steps': 0, 'num_cycles': 4.0, 'relax_factor': 0.0, 'scheme': 'Alternating (tensile start)'}
        self._last_scheme = "Staircase Loading"

        self._is_mode_switching = False
        self._undo_stack = []
        self._redo_stack = []

        if initial_state:
            self.set_state(initial_state)
        else:
            self.graph_widget.reset_graph()

        self._setup_undo_redo()
        self.max_steps_spinbox.editingFinished.connect(self._update_graph_controls)
        self.min_strain_spinbox.editingFinished.connect(self._update_graph_controls)
        self.max_strain_spinbox.editingFinished.connect(self._update_graph_controls)

        self.min_strain_spinbox.lineEdit().editingFinished.connect(self._min_strain_cleared)
        self.max_strain_spinbox.lineEdit().editingFinished.connect(self._max_strain_cleared)

        self.graph_widget.dataChanged.connect(self.dataChanged)
        self.graph_widget.dataChanged.connect(self._update_deform_scenario_visibility)
        self.deform_axis_combo.currentTextChanged.connect(self._update_deform_scenario_visibility)
        self.deform_axis_combo.currentTextChanged.connect(self._update_ensemble_ui_state)
        self.reset_button.clicked.connect(self.graph_widget.reset_graph)
        self.generate_button.clicked.connect(self._show_preset_dialog)
        self._update_graph_controls()
        self._save_state_for_undo()
        
        # Update bond breakage UI state to ensure fields are enabled/disabled correctly on startup
        self._update_bond_breakage_ui_state()
        
        # Update deform scenario visibility on startup
        self._update_deform_scenario_visibility()

    def _min_strain_cleared(self):
        if self.min_strain_spinbox.lineEdit().text() == "":
            if self.mode == 'Deformation':
                self.min_strain_spinbox.setValue(0.0)
            else:  # Temperature
                self.min_strain_spinbox.setValue(1.0)

    def _max_strain_cleared(self):
        if self.max_strain_spinbox.lineEdit().text() == "":
            min_val = self.min_strain_spinbox.value()
            if self.mode == 'Deformation':
                self.max_strain_spinbox.setValue(min_val + 0.1)
            else:  # Temperature
                self.max_strain_spinbox.setValue(min_val + 1.0)

    def _update_graph_controls(self):
        max_steps = self.max_steps_spinbox.value()
        min_val = self.min_strain_spinbox.value()
        max_val = self.max_strain_spinbox.value()

        self.min_strain_spinbox.blockSignals(True)
        self.max_strain_spinbox.blockSignals(True)

        # Set ranges based on mode
        if self.mode == 'Deformation':
            self.min_strain_spinbox.setRange(-0.999999, 1e9)
            self.max_strain_spinbox.setRange(-1e9, 1e9)
        else:  # Temperature
            self.min_strain_spinbox.setRange(0.001, 1e9)
            self.max_strain_spinbox.setRange(0.001, 1e9)

        if not self._is_mode_switching:
            # Apply value corrections only when not mode switching
            if self.mode == 'Deformation':
                if min_val > 0:
                    self.min_strain_spinbox.setValue(-min_val)
                if min_val <= -1:
                    self.min_strain_spinbox.setValue(-0.999)
                if max_val < 0:
                    self.max_strain_spinbox.setValue(-max_val)
            else:  # Temperature
                if min_val < 0.001:
                    self.min_strain_spinbox.setValue(0.001)
                if max_val < 0.001:
                    self.max_strain_spinbox.setValue(0.001)

        # Re-read values after potential changes
        current_min = self.min_strain_spinbox.value()
        current_max = self.max_strain_spinbox.value()

        if current_min >= current_max:
            if not self._is_mode_switching:
                if self.mode == 'Temperature':
                    self.max_strain_spinbox.setValue(current_min + 1.0)
                else:
                    self.min_strain_spinbox.setValue(round(current_max - 0.01, 3))

        self.min_strain_spinbox.blockSignals(False)
        self.max_strain_spinbox.blockSignals(False)

        self.max_steps_spinbox.setSingleStep(max(1, int(max_steps * 0.02)))
        self.min_strain_spinbox.setSingleStep(max(0.001, abs(self.min_strain_spinbox.value()) * 0.02) if self.min_strain_spinbox.value() != 0 else 0.001)
        self.max_strain_spinbox.setSingleStep(max(0.001, abs(self.max_strain_spinbox.value()) * 0.02) if self.max_strain_spinbox.value() != 0 else 0.001)

        self.graph_widget.set_max_values(max_steps, self.min_strain_spinbox.value(), self.max_strain_spinbox.value())

    def _show_preset_dialog(self):
        max_steps = self.max_steps_spinbox.value()
        dialog = PresetDialog(self._last_scheme, self._last_staircase_params, self._last_cyclic_params, self._last_sinusoidal_params, max_steps, self)
        if dialog.exec():
            scheme, params = dialog.get_parameters()
            self._last_scheme = scheme
            if scheme == "Staircase Loading":
                direction = params['direction']
                is_temp_mode = self.mode == 'Temperature'
                if not is_temp_mode:
                    if direction == "Tension" and self.max_strain_spinbox.value() <= 0:
                        QMessageBox.warning(self, "Invalid Parameter", "Max Strain must be > 0 for a Tension staircase."); return
                    if direction == "Compression" and self.min_strain_spinbox.value() >= 0:
                        QMessageBox.warning(self, "Invalid Parameter", "Min Strain must be < 0 for a Compression staircase."); return

                self._last_staircase_params = params
                self.graph_widget.generate_staircase_scheme(params['equilibration_steps'], params['cycles'], params['factor'], params['direction'])
            elif scheme == "Cyclic Loading":
                self._last_cyclic_params = params
                self.graph_widget.generate_cyclic_scheme(params['equilibration_steps'], params['cycles'], params['relax_factor'], params['start_with'])
            elif scheme == "Sinusoidal Loading":
                self._last_sinusoidal_params = params
                
                # --- Axis Initialization Logic ---
                min_s_box = self.min_strain_spinbox
                max_s_box = self.max_strain_spinbox
                scheme_type = params['scheme']
                
                current_max_abs = max(abs(min_s_box.value()), abs(max_s_box.value()))
                if current_max_abs == 0: current_max_abs = 0.1 # Default if axes are at 0
                
                needs_update = False
                if "Pulsating tensile" in scheme_type:
                    if max_s_box.value() < current_max_abs:
                        max_s_box.setValue(current_max_abs)
                        needs_update = True
                elif "Pulsating compressive" in scheme_type:
                    if min_s_box.value() > -current_max_abs:
                        min_s_box.setValue(-current_max_abs)
                        needs_update = True
                else: # Alternating
                    if min_s_box.value() > -current_max_abs or max_s_box.value() < current_max_abs:
                        min_s_box.setValue(-current_max_abs)
                        max_s_box.setValue(current_max_abs)
                        needs_update = True

                if needs_update:
                    self._update_graph_controls()
                # --- End Axis Logic ---

                self.graph_widget.generate_sinusoidal_scheme(params['equilibration_steps'], params['num_cycles'], params['relax_factor'], params['scheme'])



    def _setup_undo_redo(self):
        self.undo_action = QAction("Undo", self)
        self.undo_action.setShortcut(QKeySequence("Ctrl+Z"))
        self.undo_action.triggered.connect(self.undo)
        self.addAction(self.undo_action)

        self.redo_action = QAction("Redo", self)
        self.redo_action.setShortcut(QKeySequence("Ctrl+Y"))
        self.redo_action.triggered.connect(self.redo)
        self.addAction(self.redo_action)

        self.undo_button.clicked.connect(self.undo)
        self.redo_button.clicked.connect(self.redo)

        # Use a single connection for all change events to prevent duplicate recordings
        self.graph_widget.dataChanged.connect(self._schedule_undo_save)
        
        # Timer to debounce undo saves
        self._undo_debounce_timer = QTimer()
        self._undo_debounce_timer.setSingleShot(True)
        self._undo_debounce_timer.timeout.connect(self._save_state_for_undo)
        
    def _schedule_undo_save(self):
        # Debounce undo saves to prevent multiple recordings of the same user action
        self._undo_debounce_timer.start(50)  # 50ms debounce

        self.update_undo_redo_buttons()

    def _save_state_for_undo(self):
        state = self.get_undo_state()
        if not self._undo_stack or self._undo_stack[-1] != state:
            self._undo_stack.append(state)
            self._redo_stack.clear()
            self.update_undo_redo_buttons()

    def undo(self):
        if len(self._undo_stack) > 1:
            # Move current state to redo stack
            current_state = self._undo_stack.pop()
            self._redo_stack.append(current_state)
            # Restore previous state
            previous_state = self._undo_stack[-1]
            self.set_undo_state(previous_state)
            self.update_undo_redo_buttons()

    def redo(self):
        if self._redo_stack:
            # Move state from redo stack back to undo stack
            state_to_redo = self._redo_stack.pop()
            self._undo_stack.append(state_to_redo)
            # Apply the state
            self.set_undo_state(state_to_redo)
            self.update_undo_redo_buttons()

    def update_undo_redo_buttons(self):
        self.undo_button.setEnabled(len(self._undo_stack) > 1)
        self.redo_button.setEnabled(len(self._redo_stack) > 0)
        self.undo_action.setEnabled(len(self._undo_stack) > 1)
        self.redo_action.setEnabled(len(self._redo_stack) > 0)

    def get_undo_state(self):
        return {
            'data_points': [QPointF(p.x(), p.y()) for p in self.graph_widget.get_data_points()],
            'segments': copy.deepcopy(self.graph_widget.segments),
            'max_steps': self.max_steps_spinbox.value(),
            'min_strain': self.min_strain_spinbox.value(),
            'max_strain': self.max_strain_spinbox.value(),
        }

    def set_undo_state(self, state):
        self.max_steps_spinbox.blockSignals(True)
        self.min_strain_spinbox.blockSignals(True)
        self.max_strain_spinbox.blockSignals(True)

        self.max_steps_spinbox.setValue(state['max_steps'])
        self.min_strain_spinbox.setValue(state['min_strain'])
        self.max_strain_spinbox.setValue(state['max_strain'])

        self.max_steps_spinbox.blockSignals(False)
        self.min_strain_spinbox.blockSignals(False)
        self.max_strain_spinbox.blockSignals(False)

        self._update_graph_controls()
        self.graph_widget.points_norm = [self.graph_widget._data_to_norm(p) for p in state['data_points']]
        self.graph_widget.segments = copy.deepcopy(state.get('segments', [{'type': 'line'} for _ in range(len(state['data_points']) - 1)]))
        self.graph_widget.update()
        self.dataChanged.emit()

    def set_enabled(self, enabled):
        if self.is_enabled == enabled:
            return
        self.is_enabled = enabled

        # Manually enable/disable all interactive child widgets.
        # This avoids disabling the parent StudyWidget, which may have been causing it to not be rendered
        # correctly on load. The GraphWidget itself is handled separately by its paintEvent.
        self.max_steps_spinbox.setEnabled(enabled)
        self.min_strain_spinbox.setEnabled(enabled)
        self.max_strain_spinbox.setEnabled(enabled)
        self.undo_button.setEnabled(enabled)
        self.redo_button.setEnabled(enabled)
        self.generate_button.setEnabled(enabled)
        self.reset_button.setEnabled(enabled)
        self.deform_axis_combo.setEnabled(enabled)
        self.deform_scenario_combo.setEnabled(enabled)
        self.ensemble_combo.setEnabled(enabled)
        self.temp_spinbox.setEnabled(enabled)
        # Don't set pressure_spinbox enabled state here, let _update_ensemble_ui_state handle it
        # based on both study activation state and ensemble
        self.npt_aniso_combo.setEnabled(enabled)
        self.sync_ensemble_checkbox.setEnabled(enabled)
        self.enable_bond_breakage_checkbox.setEnabled(enabled)
        self.sync_bond_break_checkbox.setEnabled(enabled)
        
        # These functions will correctly handle the logic for their own children
        # based on the state of the parent checkboxes, which are now correctly enabled/disabled.
        self._update_ensemble_ui_state()
        self._update_bond_breakage_ui_state()

        # The graph widget is a special case; we don't disable it,
        # but its paintEvent will draw an overlay. We just need to trigger a repaint.
        self.graph_widget.update()

        self.dataChanged.emit()

    def _update_deform_scenario_visibility(self):
        """Update the visibility of the Deform Scenario label and field based on mode, sine segments, and shear"""
        is_shear = self.deform_axis_combo.currentText() in ["xy", "xz", "yz"]
        sine_count = self.graph_widget.count_sine_segments()

        # Hide for non-deformation modes, or if there are sine segments, or if it's a shear deformation
        if self.mode != 'Deformation' or sine_count > 0 or is_shear:
            self.deform_scenario_label.setVisible(False)
            self.deform_scenario_combo.setVisible(False)
            # Set the deform scenario to symmetric as default when hidden
            self.deform_scenario_combo.setCurrentText("symmetric")
        else:
            self.deform_scenario_label.setVisible(True)
            self.deform_scenario_combo.setVisible(True)



    def get_state(self):
        return {
            'data_points': [[p.x(), p.y()] for p in self.graph_widget.get_data_points()],
            'max_steps': self.max_steps_spinbox.value(),
            'min_strain': self.min_strain_spinbox.value(),
            'max_strain': self.max_strain_spinbox.value(),
            'deform_axis': self.deform_axis_combo.currentText(),
            'deform_scenario': self.deform_scenario_combo.currentText(),
            'mode': self.mode,
            'segments': copy.deepcopy(self.graph_widget.segments),
            'is_enabled': self.is_enabled,
            'ensemble': {
                'ensemble': self.ensemble_combo.currentText(),
                'temperature': self.temp_spinbox.value(),
                'pressure': self.pressure_spinbox.value(),
                'npt_aniso': self.npt_aniso_combo.currentText(),
                'sync_ensemble': self.sync_ensemble_checkbox.isChecked()
            },
            'bond_breakage': {
                'enable_bond_breakage': self.enable_bond_breakage_checkbox.isChecked(),
                'nevery': self.nevery_spinbox.value(),
                'bondtype': self.bondtype_spinbox.value(),
                'rmax': self.rmax_spinbox.value(),
                'enable_prob': self.enable_prob_checkbox.isChecked(),
                'prob_fraction': self.prob_fraction_spinbox.value(),
                'prob_seed': self.prob_seed_spinbox.value(),
                'sync_bond_break': self.sync_bond_break_checkbox.isChecked()
            }
        }
    def set_state(self, state):
        # Block signals to prevent feedback loops and unwanted updates
        self.max_steps_spinbox.blockSignals(True)
        self.min_strain_spinbox.blockSignals(True)
        self.max_strain_spinbox.blockSignals(True)
        self.ensemble_combo.blockSignals(True)
        self.temp_spinbox.blockSignals(True)
        self.pressure_spinbox.blockSignals(True)
        self.npt_aniso_combo.blockSignals(True)
        self.sync_ensemble_checkbox.blockSignals(True)
        self.enable_bond_breakage_checkbox.blockSignals(True)
        self.nevery_spinbox.blockSignals(True)
        self.bondtype_spinbox.blockSignals(True)
        self.rmax_spinbox.blockSignals(True)
        self.enable_prob_checkbox.blockSignals(True)
        self.prob_fraction_spinbox.blockSignals(True)
        self.prob_seed_spinbox.blockSignals(True)
        self.sync_bond_break_checkbox.blockSignals(True)

        # 1. Set mode and update mode-dependent UI without triggering corrective logic
        new_mode = state.get('mode', 'Deformation')
        if self.mode != new_mode:
            self.mode = new_mode
            self.graph_widget.set_mode(new_mode)
        
        is_temp_mode = self.mode == 'Temperature'
        self.min_strain_spinbox.setPrefix("Min Temp: " if is_temp_mode else "Min Strain: ")
        self.max_strain_spinbox.setPrefix("Max Temp: " if is_temp_mode else "Max Strain: ")
        self.temp_spinbox.setVisible(not is_temp_mode)
        self.deform_axis_label.setVisible(not is_temp_mode)
        self.deform_axis_combo.setVisible(not is_temp_mode)

        # 2. Set spinbox ranges based on mode
        if is_temp_mode:
            self.min_strain_spinbox.setRange(0.001, 1e9)
            self.max_strain_spinbox.setRange(0.001, 1e9)
        else:
            self.min_strain_spinbox.setRange(-0.999999, 1e9)
            self.max_strain_spinbox.setRange(-1e9, 1e9)

        # 3. Set control values directly from state
        max_steps = state.get('max_steps', 100)
        min_strain = state.get('min_strain', 0.0)
        max_strain = state.get('max_strain', 1.0)
        self.max_steps_spinbox.setValue(max_steps)
        self.min_strain_spinbox.setValue(min_strain)
        self.max_strain_spinbox.setValue(max_strain)
        self.deform_axis_combo.setCurrentText(state.get('deform_axis', 'x'))
        self.deform_scenario_combo.setCurrentText(state.get('deform_scenario', 'symmetric'))

        ensemble_state = state.get('ensemble', {})
        self.ensemble_combo.setCurrentText(ensemble_state.get('ensemble', 'NVT'))
        self.temp_spinbox.setValue(ensemble_state.get('temperature', 300.0))
        self.pressure_spinbox.setValue(ensemble_state.get('pressure', 1.0))
        self.npt_aniso_combo.setCurrentText(ensemble_state.get('npt_aniso', 'iso'))
        self.sync_ensemble_checkbox.setChecked(ensemble_state.get('sync_ensemble', False))

        bond_breakage_state = state.get('bond_breakage', {})
        self.enable_bond_breakage_checkbox.setChecked(bond_breakage_state.get('enable_bond_breakage', False))
        self.nevery_spinbox.setValue(bond_breakage_state.get('nevery', 1))
        self.bondtype_spinbox.setValue(bond_breakage_state.get('bondtype', 1))
        self.rmax_spinbox.setValue(bond_breakage_state.get('rmax', 1.5))
        self.enable_prob_checkbox.setChecked(bond_breakage_state.get('enable_prob', False))
        self.prob_fraction_spinbox.setValue(bond_breakage_state.get('prob_fraction', 0.1))
        self.prob_seed_spinbox.setValue(bond_breakage_state.get('prob_seed', 12345))
        self.sync_bond_break_checkbox.setChecked(bond_breakage_state.get('sync_bond_break', False))

        # 4. Directly update the graph's axes with the loaded values
        self.graph_widget.set_max_values(max_steps, min_strain, max_strain)

        # 5. Load graph data
        self.graph_widget._fixed_segments = set(state.get('fixed_segments', []))
        self.graph_widget.segments = copy.deepcopy(state.get('segments', [{'type': 'line'} for _ in range(len(state.get('data_points', [])) - 1)]))
        
        data_points_list = state.get('data_points', [])
        if not data_points_list and 'points' in state:
            data_points_list = state.get('points', [])

        if not data_points_list and 'points_norm' in state:
            points_norm = state.get('points_norm', [])
            self.graph_widget.points_norm = [QPointF(p[0], p[1]) if isinstance(p, list) else QPointF(p.x(), p.y()) for p in points_norm]
        else:
            data_points = [QPointF(p[0], p[1]) for p in data_points_list]
            if data_points:
                self.graph_widget.points_norm = [self.graph_widget._data_to_norm(p) for p in data_points]
        
        # 6. Unblock signals
        self.max_steps_spinbox.blockSignals(False)
        self.min_strain_spinbox.blockSignals(False)
        self.max_strain_spinbox.blockSignals(False)
        self.ensemble_combo.blockSignals(False)
        self.temp_spinbox.blockSignals(False)
        self.pressure_spinbox.blockSignals(False)
        self.npt_aniso_combo.blockSignals(False)
        self.sync_ensemble_checkbox.blockSignals(False)
        self.enable_bond_breakage_checkbox.blockSignals(False)
        self.nevery_spinbox.blockSignals(False)
        self.bondtype_spinbox.blockSignals(False)
        self.rmax_spinbox.blockSignals(False)
        self.enable_prob_checkbox.blockSignals(False)
        self.prob_fraction_spinbox.blockSignals(False)
        self.prob_seed_spinbox.blockSignals(False)
        self.sync_bond_break_checkbox.blockSignals(False)
        
        # 7. Final UI refresh
        self.graph_widget.update()
        self.dataChanged.emit()
        self._update_ensemble_ui_state()
        self._update_bond_breakage_ui_state()
        self._update_deform_scenario_visibility()
        self.set_enabled(state.get('is_enabled', True))

    def _update_bond_breakage_ui_state(self):
        enabled_bond_breakage = self.enable_bond_breakage_checkbox.isChecked()
        self.nevery_spinbox.setEnabled(enabled_bond_breakage)
        self.bondtype_spinbox.setEnabled(enabled_bond_breakage)
        self.rmax_spinbox.setEnabled(enabled_bond_breakage)
        self.enable_prob_checkbox.setEnabled(enabled_bond_breakage)

        enabled_prob = self.enable_prob_checkbox.isChecked() and enabled_bond_breakage
        self.prob_fraction_spinbox.setEnabled(enabled_prob)
        self.prob_seed_spinbox.setEnabled(enabled_prob)

    def _on_ensemble_setting_changed(self):
        self._update_ensemble_ui_state()
        stacked_widget = self.parent()
        if stacked_widget is not None:
            tab_widget = stacked_widget.parent()
            if tab_widget is not None:
                deformation_tab = tab_widget.parent()
                if isinstance(deformation_tab, DeformationTab):
                    sync_state = self.sync_ensemble_checkbox.isChecked()
                    if sync_state:
                        deformation_tab._sync_ensemble_settings(self)
                    else:
                        sender = self.sender()
                        if sender == self.sync_ensemble_checkbox:
                            deformation_tab._sync_ensemble_settings(self, force_unchecked=True)
        self.dataChanged.emit()

    def _update_ensemble_ui_state(self):
        is_npt = self.ensemble_combo.currentText() == "NPT"

        # Update the prefix based on ensemble type
        if is_npt:
            self.pressure_spinbox.setPrefix("P: ")
            self.pressure_spinbox.setFixedWidth(100)
            self.pressure_spinbox.setToolTip("Target pressure for NPT ensemble")
        else:
            self.pressure_spinbox.setPrefix("P (used in equilibration): ")
            self.pressure_spinbox.setFixedWidth(200)
            self.pressure_spinbox.setToolTip("Pressure that was used during equilibration. The vaiue entered here is used only to correct the stress measured in the system during deformation.")

        # Set pressure spinbox enabled state based on whether the study is enabled
        # If the study is not enabled, always disable the pressure field
        # If the study is enabled, the pressure field should be available for input regardless of ensemble
        self.pressure_spinbox.setEnabled(self.is_enabled)

        self.npt_aniso_label.setVisible(is_npt)
        self.npt_aniso_combo.setVisible(is_npt)

        if not is_npt:
            return

        is_deformation_mode = self.mode == 'Deformation'
        is_shear = self.deform_axis_combo.currentText() in ["xy", "xz", "yz"]

        current_selection = self.npt_aniso_combo.currentText()

        self.npt_aniso_combo.blockSignals(True)
        self.npt_aniso_combo.clear()

        if is_deformation_mode:
            if is_shear:
                # For shear, only 'tri' is meaningful as the box must be triclinic
                self.npt_aniso_combo.addItem("tri")
                self.npt_aniso_combo.setCurrentText("tri")
            else:
                # For tensile deformation, 'aniso' and 'tri' are valid
                self.npt_aniso_combo.addItems(["aniso", "tri"])
                if current_selection == "iso" or not current_selection:
                    self.npt_aniso_combo.setCurrentText("aniso")
                else:
                    self.npt_aniso_combo.setCurrentText(current_selection)
        else: # Temperature mode
            # In temperature mode, all options are valid
            self.npt_aniso_combo.addItems(["iso", "aniso", "tri"])
            if not current_selection:
                self.npt_aniso_combo.setCurrentText("iso")
            else:
                self.npt_aniso_combo.setCurrentText(current_selection)

        self.npt_aniso_combo.blockSignals(False)

    def _on_bond_breakage_setting_changed(self):
        # Update UI state first
        self._update_bond_breakage_ui_state()

        # Get the parent DeformationTab instance
        # The StudyWidget is added directly to the tab_widget, so we need to go up the hierarchy
        # StudyWidget -> QStackedWidget (tab_widget) -> QTabWidget (tab_widget) -> DeformationTab
        stacked_widget = self.parent()  # This is the QStackedWidget
        if stacked_widget is not None:
            tab_widget = stacked_widget.parent()  # This should be the QTabWidget
            if tab_widget is not None:
                deformation_tab = tab_widget.parent()  # This should be the DeformationTab
                if isinstance(deformation_tab, DeformationTab):
                    # Check if sync is enabled in THIS tab (the one that changed)
                    sync_state = self.sync_bond_break_checkbox.isChecked()
                    if sync_state:
                        # Sync is enabled in this tab, propagate all settings from this tab to all other tabs
                        deformation_tab._sync_bond_breakage_settings(self)
                    else:
                        # Sync is disabled, check if this was a sync checkbox change
                        sender = self.sender()
                        if sender == self.sync_bond_break_checkbox:
                            # The sync checkbox was just unchecked in this tab
                            # Uncheck sync in all other tabs
                            deformation_tab._sync_bond_breakage_settings(self, force_unchecked=True)

        self.dataChanged.emit() # Emit dataChanged to update summaries

    def set_mode(self, mode, adjust_values=True):
        if self.mode == mode:
            return

        self.mode = mode
        is_temp_mode = mode == 'Temperature'

        # Convert sine segments to linear when switching to Temperature mode
        if is_temp_mode:
            for segment in self.graph_widget.segments:
                if segment['type'] == 'sine':
                    segment['type'] = 'line'



        # Set ranges FIRST to avoid clamping issues
        if is_temp_mode:
            self.min_strain_spinbox.setRange(0.001, 1e9)
            self.max_strain_spinbox.setRange(0.001, 1e9)
        else:  # Deformation mode
            self.min_strain_spinbox.setRange(-0.999999, 1e9)
            self.max_strain_spinbox.setRange(-1e9, 1e9)

        # Adjust min/max based on slope only if adjust_values is True
        if adjust_values:
            points = self.graph_widget.get_data_points()
            if len(points) > 1:
                first_point = points[0]
                last_point = points[-1]

                dx = last_point.x() - first_point.x()
                dy = last_point.y() - first_point.y()
                slope = dy / dx if dx != 0 else 0

                if is_temp_mode:
                    self.min_strain_spinbox.setValue(1.0)
                    self.max_strain_spinbox.setValue(300.0)
                else:  # Deformation mode
                    if slope >= 0:
                        self.min_strain_spinbox.setValue(0.0)
                        self.max_strain_spinbox.setValue(0.5)
                    else:
                        self.min_strain_spinbox.setValue(-0.5)
                        self.max_strain_spinbox.setValue(0.0)

        self.min_strain_spinbox.setPrefix("Min Temp: " if is_temp_mode else "Min Strain: ")
        self.max_strain_spinbox.setPrefix("Max Temp: " if is_temp_mode else "Max Strain: ")

        self.temp_spinbox.setVisible(not is_temp_mode)
        self.deform_axis_label.setVisible(not is_temp_mode)
        self.deform_axis_combo.setVisible(not is_temp_mode)
        
        # Update the visibility of the Deform Scenario controls based on the new mode
        self._update_deform_scenario_visibility()
        # Update ensemble UI state to refresh NPT options based on the new mode
        self._update_ensemble_ui_state()

        self.graph_widget.set_mode(mode)
        self._update_graph_controls()

        button_style = "background-color: darkorange;" if is_temp_mode else ""
        self.undo_button.setStyleSheet(button_style)
        self.redo_button.setStyleSheet(button_style)
        self.generate_button.setStyleSheet(button_style)
        self.reset_button.setStyleSheet(button_style)

        parent_tab = self.parent().parent() if self.parent() and self.parent().parent() else None
        if parent_tab and hasattr(parent_tab, '_update_tab_colors'):
            parent_tab._update_tab_colors()

        self.dataChanged.emit()

        self._is_mode_switching = False

class DeformationTab(QWidget):
    studiesChanged = pyqtSignal()

    def __init__(self, main_window, parent=None):
        super().__init__(parent); self.setWindowTitle("Interactive Strain-Time Profile Editor")
        self.main_window = main_window
        self._batch_loading = False  # Flag to optimize loading by batching summary updates
        main_layout = QVBoxLayout(self)
        self.tab_widget = QTabWidget(); self.tab_widget.setTabsClosable(True); self.tab_widget.tabCloseRequested.connect(self._close_tab)
        self.tab_widget.tabBar().setMovable(True)
        self.tab_widget.tabBar().tabMoved.connect(self.update_summaries)
        self.tab_widget.tabBar().setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self.tab_widget.tabBar().customContextMenuRequested.connect(self._show_tab_context_menu)
        # Set base stylesheet for the tab widget
        self._update_tab_stylesheet()
        self.tab_widget.tabBarDoubleClicked.connect(self._rename_tab)
        self.tab_widget.currentChanged.connect(self._on_tab_changed)

        corner_widget = QWidget()
        corner_layout = QHBoxLayout(corner_widget)
        corner_layout.setContentsMargins(0, 0, 0, 0)
        corner_layout.setSpacing(5)

        self.mode_combo = QComboBox()
        self.mode_combo.addItems(["Deformation", "Temperature"])
        font = QFont()
        font.setBold(True)
        self.mode_combo.setFont(font)
        self.mode_combo.setToolTip("Select the processing mode for this study")
        self.mode_combo.setMinimumWidth(100)
        self.mode_combo.setStyleSheet("""
            QComboBox {
                combobox-popup: 0;
            }
            QComboBox QAbstractItemView {
                background-color: white;
                selection-background-color: #007acc;
                selection-color: white;
            }
        """)
        self.mode_combo.currentIndexChanged.connect(self._mode_changed)
        
        corner_layout.addWidget(QLabel("<b>Mode:</b>"))
        corner_layout.addWidget(self.mode_combo)

        add_tab_button = QPushButton("+")
        add_tab_button.setToolTip("Add a new study")
        add_tab_button.clicked.connect(self._add_study)
        add_tab_button.setFixedSize(20, 18)
        add_tab_button.setStyleSheet("QPushButton { margin: -3px 5px 0px 0px; padding: 0px; }")
        corner_layout.addWidget(add_tab_button)
        
        self.tab_widget.setCornerWidget(corner_widget, Qt.Corner.TopRightCorner)

        main_layout.addWidget(self.tab_widget)

        self._create_summary_area(main_layout)
        self._add_study(is_first=True)

    def _mode_changed(self, index):
        mode = self.mode_combo.currentText()
        current_widget = self.tab_widget.currentWidget()
        if current_widget:
            current_widget.set_mode(mode, adjust_values=True)
        self._update_tab_colors()
        self.update_summaries()
        self.studiesChanged.emit()

    def _on_tab_changed(self, index):
        widget = self.tab_widget.widget(index)
        if widget:
            self.mode_combo.blockSignals(True)
            self.mode_combo.setCurrentText(widget.mode)
            self.mode_combo.blockSignals(False)
        # Update tab colors when the current tab changes
        self._update_tab_colors()

    def _update_tab_stylesheet(self):
        """Update the tab widget stylesheet based on the current tab's mode"""
        current_index = self.tab_widget.currentIndex()
        is_temperature_mode = False
        
        if current_index >= 0:
            current_widget = self.tab_widget.widget(current_index)
            if current_widget and hasattr(current_widget, 'mode') and current_widget.mode == "Temperature":
                is_temperature_mode = True
        
        # Set the stylesheet with appropriate selected tab indicator color
        indicator_color = "darkorange" if is_temperature_mode else "#007acc"
        
        self.tab_widget.setStyleSheet(f"""
            QTabWidget::pane {{
                border: 1px solid #c0c0c0;
            }}
            QTabBar::tab {{
                height: 14px; 
                min-width: 70px; 
                padding: 2px 4px;
            }}
            QTabBar::close-button {{
                padding: 0px;
            }}
            QTabBar::tab:selected {{
                border-bottom: 2px solid {indicator_color};
            }}
        """)

    def _update_tab_colors(self):
        # Update individual tab text colors
        for i in range(self.tab_widget.count()):
            widget = self.tab_widget.widget(i)
            if widget:
                if not widget.is_enabled:
                    self.tab_widget.tabBar().setTabTextColor(i, QColor(Qt.GlobalColor.gray))
                else:
                    if widget.mode == "Temperature":
                        self.tab_widget.tabBar().setTabTextColor(i, QColor("darkorange"))
                    else:
                        self.tab_widget.tabBar().setTabTextColor(i, QColor(Qt.GlobalColor.black))
                
        # Update the stylesheet for selected tab indicator
        self._update_tab_stylesheet()


    def _create_summary_area(self, layout):
        # Use a single scrollable text area for all summaries
        scroll_area = QScrollArea()
        scroll_area.setWidgetResizable(True)
        self.summary_text = QTextEdit()
        self.summary_text.setReadOnly(True)
        self.summary_text.setFont(QFont("Courier New", 10))
        scroll_area.setWidget(self.summary_text)
        layout.addWidget(scroll_area)

    def _get_unique_copy_name(self, base_name):
        copy_num = 1
        new_name = f"{base_name}_copy"
        while any(new_name == self.tab_widget.tabText(i) for i in range(self.tab_widget.count())):
            copy_num += 1
            new_name = f"{base_name}_copy{copy_num}"
        return new_name

    def _add_study(self, is_first=False):
        initial_state = None
        tab_name = ""
        insert_index = self.tab_widget.currentIndex() + 1 if self.tab_widget.count() > 0 else 0

        if is_first:
            # This is for the initial tab or when the last tab is closed
            initial_state = None # No state to copy
            tab_name = f"Study{self._get_next_default_study_number():02d}"
        else:
            # Copying an existing tab
            current_widget = self.tab_widget.currentWidget()
            if current_widget:
                initial_state = current_widget.get_state()
                base_name = self.tab_widget.tabText(self.tab_widget.currentIndex())
                tab_name = self._get_unique_copy_name(base_name)
            else:
                # Fallback if no current widget (shouldn't happen if count > 0)
                initial_state = None
                tab_name = f"Study{self._get_next_default_study_number():02d}"

        new_study = StudyWidget(initial_state)

        # Apply current timestep and units from main window
        timestep = self.main_window.timestep.value()
        units = self.main_window.units_combo.currentText()
        new_study.graph_widget.set_timestep(timestep)
        new_study.graph_widget.set_time_unit(LAMMPS_UNITS[units])

        new_study.dataChanged.connect(self.update_summaries)
        new_study.graph_widget.dataChanged.connect(self.update_summaries)
        new_study.graph_widget.dataChanged.connect(new_study.graph_widget.update)
        original_mouse_move = new_study.graph_widget.mouseMoveEvent
        new_study.graph_widget.mouseMoveEvent = lambda event: self._wrapped_mouse_move_event(original_mouse_move, event, new_study.graph_widget)
        original_mouse_release = new_study.graph_widget.mouseReleaseEvent
        new_study.graph_widget.mouseReleaseEvent = lambda event: self._wrapped_mouse_release_event(original_mouse_release, event, new_study.graph_widget)
        
        tab_index = self.tab_widget.insertTab(insert_index, new_study, tab_name) # Use insertTab
        self.tab_widget.setCurrentIndex(tab_index)

        if not self._batch_loading:
            self.update_summaries()
            self._update_tab_colors()
        self.studiesChanged.emit()

    def _wrapped_mouse_move_event(self, original_mouse_move_event, event, graph_widget):
        # Call the original mouse move event
        result = original_mouse_move_event(event)
        # Trigger real-time summary updates during mouse movement
        self.update_summaries()
        return result
        
    def _wrapped_mouse_release_event(self, original_mouse_release_event, event, graph_widget):
        # Call the original mouse release event
        result = original_mouse_release_event(event)
        # Trigger final summary update when mouse is released
        self.update_summaries()
        return result

    def _get_next_default_study_number(self):
        num = 1
        while any(f"Study{num:02d}" == self.tab_widget.tabText(i) for i in range(self.tab_widget.count())): num += 1
        return num

    def _close_tab(self, index):
        if self.tab_widget.count() > 1:
            self.tab_widget.widget(index).deleteLater(); self.tab_widget.removeTab(index)
            self.update_summaries()
            self._update_tab_colors()
        else:
            # If it's the last tab, create a new default one
            self.tab_widget.widget(index).deleteLater(); self.tab_widget.removeTab(index)
            self._add_study(is_first=True)
            # Reset to default values
            new_widget = self.tab_widget.currentWidget()
            new_widget.max_steps_spinbox.setValue(10000)
            new_widget.min_strain_spinbox.setValue(0.0)
            new_widget.max_strain_spinbox.setValue(1.0)
            new_widget.graph_widget.reset_graph()
            self._update_tab_colors()
        self.studiesChanged.emit()

    def _rename_tab(self, index):
        current_name = self.tab_widget.tabText(index)

        while True:
            new_name, ok = QInputDialog.getText(self, "Rename Study", "New study name:", text=current_name)

            if not ok:
                return # User cancelled

            if not new_name:
                QMessageBox.warning(self, "Invalid Name", "Study name cannot be empty.")
                continue

            # Validate the new name
            if re.match(r"^[a-zA-Z0-9_-]+$", new_name):
                # Check if name already exists
                if any(new_name == self.tab_widget.tabText(i) for i in range(self.tab_widget.count()) if i != index):
                    QMessageBox.warning(self, "Invalid Name", "A study with this name already exists.")
                    continue

                self.tab_widget.setTabText(index, new_name)
                self.update_summaries()
                break
            else:
                QMessageBox.warning(self, "Invalid Name", "Study name can only contain letters, numbers, underscores, and hyphens.")

    def _renumber_default_tabs(self):
        default_study_counter = 1
        for i in range(self.tab_widget.count()):
            tab_text = self.tab_widget.tabText(i)
            if re.match(r"^Study\d+$", tab_text):
                self.tab_widget.setTabText(i, f"Study{default_study_counter:02d}"); default_study_counter += 1

    def _sync_bond_breakage_settings(self, source_study_widget, force_unchecked=False):
        # Get the source state
        source_state = source_study_widget.get_state()['bond_breakage']
        
        # Propagate settings to all other tabs
        for i in range(self.tab_widget.count()):
            target_study_widget = self.tab_widget.widget(i)
            # Skip the source widget (the one that changed)
            if target_study_widget == source_study_widget:
                continue

            # Block signals on target widget to prevent recursive calls
            target_study_widget.enable_bond_breakage_checkbox.blockSignals(True)
            target_study_widget.nevery_spinbox.blockSignals(True)
            target_study_widget.bondtype_spinbox.blockSignals(True)
            target_study_widget.rmax_spinbox.blockSignals(True)
            target_study_widget.enable_prob_checkbox.blockSignals(True)
            target_study_widget.prob_fraction_spinbox.blockSignals(True)
            target_study_widget.prob_seed_spinbox.blockSignals(True)
            target_study_widget.sync_bond_break_checkbox.blockSignals(True)

            if force_unchecked:
                # Only uncheck the sync checkbox in all other tabs
                target_study_widget.sync_bond_break_checkbox.setChecked(False)
            else:
                # Copy all bond breakage settings from source to target
                target_study_widget.enable_bond_breakage_checkbox.setChecked(source_state['enable_bond_breakage'])
                target_study_widget.nevery_spinbox.setValue(source_state['nevery'])
                target_study_widget.bondtype_spinbox.setValue(source_state['bondtype'])
                target_study_widget.rmax_spinbox.setValue(source_state['rmax'])
                target_study_widget.enable_prob_checkbox.setChecked(source_state['enable_prob'])
                target_study_widget.prob_fraction_spinbox.setValue(source_state['prob_fraction'])
                target_study_widget.prob_seed_spinbox.setValue(source_state['prob_seed'])
                # Also copy the sync checkbox state
                target_study_widget.sync_bond_break_checkbox.setChecked(source_state['sync_bond_break'])

            # Unblock signals
            target_study_widget.enable_bond_breakage_checkbox.blockSignals(False)
            target_study_widget.nevery_spinbox.blockSignals(False)
            target_study_widget.bondtype_spinbox.blockSignals(False)
            target_study_widget.rmax_spinbox.blockSignals(False)
            target_study_widget.enable_prob_checkbox.blockSignals(False)
            target_study_widget.prob_fraction_spinbox.blockSignals(False)
            target_study_widget.prob_seed_spinbox.blockSignals(False)
            target_study_widget.sync_bond_break_checkbox.blockSignals(False)

            # Update UI state for the target widget
            target_study_widget._update_bond_breakage_ui_state()
            target_study_widget.dataChanged.emit() # Trigger summary update for target

    def _sync_ensemble_settings(self, source_study_widget, force_unchecked=False):
        source_state = source_study_widget.get_state()['ensemble']
        for i in range(self.tab_widget.count()):
            target_study_widget = self.tab_widget.widget(i)
            if target_study_widget == source_study_widget:
                continue

            target_study_widget.ensemble_combo.blockSignals(True)
            target_study_widget.temp_spinbox.blockSignals(True)
            target_study_widget.pressure_spinbox.blockSignals(True)
            target_study_widget.npt_aniso_combo.blockSignals(True)
            target_study_widget.sync_ensemble_checkbox.blockSignals(True)

            if force_unchecked:
                target_study_widget.sync_ensemble_checkbox.setChecked(False)
            else:
                target_study_widget.ensemble_combo.setCurrentText(source_state['ensemble'])
                target_study_widget.temp_spinbox.setValue(source_state['temperature'])
                target_study_widget.pressure_spinbox.setValue(source_state['pressure'])
                target_study_widget.npt_aniso_combo.setCurrentText(source_state['npt_aniso'])
                target_study_widget.sync_ensemble_checkbox.setChecked(source_state['sync_ensemble'])

            target_study_widget.ensemble_combo.blockSignals(False)
            target_study_widget.temp_spinbox.blockSignals(False)
            target_study_widget.pressure_spinbox.blockSignals(False)
            target_study_widget.npt_aniso_combo.blockSignals(False)
            target_study_widget.sync_ensemble_checkbox.blockSignals(False)

            target_study_widget._update_ensemble_ui_state()
            target_study_widget.dataChanged.emit()

    def _show_tab_context_menu(self, pos):
        tab_bar = self.tab_widget.tabBar()
        index = tab_bar.tabAt(pos)
        if index < 0:
            return

        widget = self.tab_widget.widget(index)
        if not widget:
            return

        menu = QMenu(self)
        enabled_action = QAction("Enabled", self, checkable=True)
        enabled_action.setChecked(widget.is_enabled)
        enabled_action.toggled.connect(lambda checked: self._toggle_study_enabled(index, checked))
        menu.addAction(enabled_action)

        menu.exec(tab_bar.mapToGlobal(pos))

    def _toggle_study_enabled(self, index, enabled):
        widget = self.tab_widget.widget(index)
        if widget:
            widget.set_enabled(enabled)
        self.studiesChanged.emit()

    def get_study_modes(self):
        """Returns a list of modes for all studies."""
        modes = []
        for i in range(self.tab_widget.count()):
            widget = self.tab_widget.widget(i)
            if widget and hasattr(widget, 'mode'):
                modes.append(widget.mode)
        return modes

    def update_all_graphs(self, timestep, unit_key):
        for i in range(self.tab_widget.count()):
            widget = self.tab_widget.widget(i)
            widget.graph_widget.set_timestep(timestep)
            widget.graph_widget.set_time_unit(LAMMPS_UNITS[unit_key])
        self.update_summaries()

    def update_summaries(self):
        if self._batch_loading: return
        self._update_tab_colors()
        timestep = self.main_window.timestep.value() if self.main_window else 0
        unit_key = LAMMPS_UNITS.get(self.main_window.units_combo.currentText(), "s") if self.main_window else "s"

        all_summaries = []
        active_studies = [(i, self.tab_widget.widget(i)) for i in range(self.tab_widget.count()) if self.tab_widget.widget(i) and self.tab_widget.widget(i).is_enabled]

        for idx, (i, study_widget) in enumerate(active_studies):
            study_name = self.tab_widget.tabText(i)
            mode = study_widget.mode
            study_state = study_widget.get_state()
            bond_breakage_status = "Enabled" if study_state.get('bond_breakage', {}).get('enable_bond_breakage', False) else "Disabled"
            all_summaries.append(f'--- Summary for {study_name} | Mode: {mode} | Bond Breakage: {bond_breakage_status} ---')

            points = study_widget.graph_widget.get_data_points()
            segments = study_widget.graph_widget.segments
            y_unit = study_widget.graph_widget.get_y_unit()
            y_header = "Temperature" if mode == 'Temperature' else "Strain"

            linear_segments_data = []
            sine_segments_data = []
            for j, segment_info in enumerate(segments):
                if j + 1 < len(points):
                    p1, p2 = points[j], points[j+1]
                    if segment_info['type'] == 'line':
                        linear_segments_data.append({'index': j, 'p1': p1, 'p2': p2})
                    elif segment_info['type'] == 'sine':
                        sine_segments_data.append({'index': j, 'p1': p1, 'p2': p2, 'info': segment_info})

            if linear_segments_data:
                header = f"{ 'Lin Seg':<8} | {'Time Step':<20} | {'Time':<30} | {y_header:<16} | {f'Slope ({y_unit}/step)':<14} | {f'Rate ({y_unit}/t)':<14}"
                all_summaries.append(header)
                all_summaries.append("-" * len(header))
                for data in linear_segments_data:
                    j, p1, p2 = data['index'], data['p1'], data['p2']
                    p1_t, p2_t = p1.x() * timestep, p2.x() * timestep
                    dx_s, dx_t, dy_e = p2.x() - p1.x(), p2_t - p1_t, p2.y() - p1.y()
                    slope, rate = (dy_e / dx_s if dx_s != 0 else float('inf')), (dy_e / dx_t if dx_t != 0 else float('inf'))
                    all_summaries.append(f"{j+1:<8} | {f'[{p1.x():.0f}, {p2.x():.0f}]':<20} | {f'[{p1_t:.2f}, {p2_t:.2f}] {unit_key}':<30} | {f'[{p1.y():.3f}, {p2.y():.3f}]':<16} | {f'{slope:.4e}':<14} | {rate:.4e}")

            if sine_segments_data:
                if linear_segments_data: all_summaries.append("")
                header = f"{ 'Sine Seg':<8} | {'Time Step':<20} | {'Phase shift':<11} | {'Cycles':<6} | {'Amplitude':<9} | {'Period':<7} | {'Midpoint Slope':<14} | {'Midpoint Rate':<15}"
                all_summaries.append(header)
                all_summaries.append("-" * len(header))
                for data in sine_segments_data:
                    j, p1, p2, info = data['index'], data['p1'], data['p2'], data['info']
                    # Use the centralized method that handles stored amplitude appropriately
                    amplitude, y_center, phi_start = study_widget.graph_widget._get_sine_parameters_with_stored_amp(p1, p2, info, j)
                    amplitude = 0 if amplitude is None else amplitude
                    
                    num_cycles = info['num_cycles']
                    period = (p2.x() - p1.x()) / num_cycles if num_cycles > 0 else 0

                    x_range_d = p2.x() - p1.x()
                    k = num_cycles * 2 * math.pi / x_range_d if x_range_d != 0 else 0
                    
                    # Find the first zero-crossing to match the canvas slope indicator
                    first_zero_x_offset = -1
                    n = 0
                    while True:
                        x_offset = (n * math.pi - phi_start) / k if k != 0 else -1
                        if x_offset >= -1e-9 and x_offset <= x_range_d + 1e-9:
                            first_zero_x_offset = x_offset
                            break
                        n += 1
                        if n > 1000: break # Safety break

                    midpoint_slope = 0
                    if first_zero_x_offset != -1:
                        midpoint_slope = amplitude * k * math.cos(k * first_zero_x_offset + phi_start)
                    
                    midpoint_rate = midpoint_slope / timestep if timestep > 0 else float('inf')
                    center_step_phase_shift = p1.x() + (x_range_d) * (-phi_start / (2*math.pi)) # phase shift in time steps of a sine oscillating around y = 0

                    all_summaries.append(f"{j+1:<8} | {f'[{p1.x():.0f}, {p2.x():.0f}]':<20} | {f'{center_step_phase_shift:.2f}':<11} | {num_cycles:<6.2f} | {f'{abs(amplitude):.4f}':<9} | {f'{period:.0f}':<7} | {f'{midpoint_slope:.4e}':<14} | {f'{midpoint_rate:.4e}':<15}")

            if idx < len(active_studies) - 1: all_summaries.append("")

        scrollbar = self.summary_text.verticalScrollBar()
        current_scroll_position = scrollbar.value() if scrollbar else 0
        self.summary_text.setText("\n".join(all_summaries))
        if scrollbar: scrollbar.setValue(current_scroll_position)

if __name__ == "__main__":
    app = QApplication(sys.argv)
    # This is a library of widgets, so we don't run it directly.
    # We can create a simple test window to show the DeformationTab
    class TestWindow(QMainWindow):
        def __init__(self):
            super().__init__()
            self.setWindowTitle("Deformation Tab Test")
            self.setCentralWidget(DeformationTab())
    window = TestWindow()
    window.show()
    sys.exit(app.exec())