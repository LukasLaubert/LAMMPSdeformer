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
from PyQt6.QtCore import Qt, QPointF, QRectF, pyqtSignal, QTimer, QUrl, QLocale
from PyQt6.QtGui import QPainter, QPen, QBrush, QColor, QFont, QAction, QFontMetrics, QKeySequence, QPixmap, QDesktopServices, QCursor, QPolygonF, QValidator

def parse_decimal(text):
    """Parse a decimal number from free text, accepting '.' and the system locale separator.

    The C locale is tried first so LAMMPS-style input ('1.5', '1e-4') always means
    the same thing on every system; the system locale is the fallback so e.g.
    German input ('1,5', '1.000,5') also works. Group separators are honored per
    locale by QLocale.toDouble, which a naive comma-swap would corrupt.
    Raises ValueError for non-numeric input. Never touches global locale state.
    """
    s = str(text).strip()
    value, ok = QLocale.c().toDouble(s)
    if ok:
        return value
    value, ok = QLocale.system().toDouble(s)
    if ok:
        return value
    raise ValueError(f"Cannot parse decimal number from {text!r}")

# --- Sci-Notation SpinBox ---
class SciNotationDoubleSpinBox(QDoubleSpinBox):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.setDecimals(20) # Decimal places: covers tiny magnitudes exactly

    def textFromValue(self, value):
        # Shortest scientific form that parses back to the exact value:
        # full digits shown (trailing zeros removed), never silently rounded.
        for _prec in range(6, 17):
            _s = f"{value:.{_prec}e}"
            try:
                if float(_s) == value:
                    _mantissa, _exp = _s.split("e")
                    return f"{_mantissa.rstrip("0").rstrip(".")}e{_exp}"
            except ValueError:
                continue
        _s = f"{value:.16e}"
        _mantissa, _exp = _s.split("e")
        return f"{_mantissa.rstrip("0").rstrip(".")}e{_exp}"

    def valueFromText(self, text):
        try:
            return parse_decimal(text)
        except ValueError:
            return self.value()
    def validate(self, text, pos):
        s = text.strip()
        # In-progress typing (sign, trailing exponent letter/separator)
        # stays editable instead of having keystrokes swallowed.
        if not s or s in ('-', '+') or s[-1] in ('e', 'E', ',', '.') or s[-2:] in ('e-', 'E-', 'e+', 'E+'):
            return (QValidator.State.Intermediate, text, pos)
        try:
            parse_decimal(s)
            return (QValidator.State.Acceptable, text, pos)
        except ValueError:
            return (QValidator.State.Invalid, text, pos)

class TrimDoubleSpinBox(QDoubleSpinBox):
    """QDoubleSpinBox accepting up to 12 decimals while displaying
    without trailing zeros (300.15 stays 300.15, 0.000000456789 keeps
    its full precision; smaller magnitudes fall back to exact scientific)."""
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.setDecimals(20)
    def textFromValue(self, value):
        # Shortest fixed-point form that parses back exactly; beyond
        # 20 places use repr (exact scientific).
        for _prec in range(1, 21):
            _s = f"{value:.{_prec}f}"
            try:
                if float(_s) == value:
                    _t = _s.rstrip("0").rstrip(".")
                    return "0" if _t in ("", "-", "-0") else _t
            except ValueError:
                continue
        return repr(value)
    def validate(self, text, pos):
        s = text.strip()
        # In-progress typing (sign, trailing exponent letter/separator)
        # stays editable instead of having keystrokes swallowed.
        if not s or s in ('-', '+') or s[-1] in ('e', 'E', ',', '.') or s[-2:] in ('e-', 'E-', 'e+', 'E+'):
            return (QValidator.State.Intermediate, text, pos)
        try:
            parse_decimal(s)
            return (QValidator.State.Acceptable, text, pos)
        except ValueError:
            return (QValidator.State.Invalid, text, pos)

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
        # Room for a full scientific-notation value plus spin buttons, so text
        # is never clipped and the buttons keep their normal size.
        for _box in (self.slope_box, self.rate_box):
            _text_width = _box.fontMetrics().horizontalAdvance("-1.2345678901e-123")
            _box.setMinimumWidth(_text_width + 48)
            _box.setKeyboardTracking(False)
        initial_slope = (p2.y() - p1.y()) / self._dx_steps if self._dx_steps != 0 else 0
        for box, val in [(self.slope_box, initial_slope), (self.rate_box, 0)]: box.setRange(-1e9, 1e9); box.setSingleStep(max(1e-5, abs(val) * 0.02))
        self.slope_box.setValue(initial_slope); self.slope_box.valueChanged.connect(self._slope_changed); self.rate_box.valueChanged.connect(self._rate_changed); self._slope_changed(initial_slope)
        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel); buttons.accepted.connect(self._on_accept); buttons.rejected.connect(self.reject)
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
    def _on_accept(self):
        # Commit typed text, but never re-parse already formatted display
        # text: the .6e display holds fewer digits than the value, so parsing
        # it back would silently truncate precision (and the cross-linked
        # boxes would bounce the truncation back and forth).
        for _box in (self.slope_box, self.rate_box):
            if _box.lineEdit().text() != _box.textFromValue(_box.value()):
                _box.interpretText()
                break
        self.accept()

class TimeEditDialog(QDialog):
    def __init__(self, step, timestep, max_step, parent=None):
        super().__init__(parent); self.setWindowTitle("Edit Time"); self._timestep = timestep
        self.step_box = QSpinBox(); self.step_box.setRange(0, max_step); self.step_box.setValue(int(step)); self.step_box.setSingleStep(max(1, int(step*0.02) if step > 0 else 1))
        self.time_box = TrimDoubleSpinBox(); self.time_box.setRange(0, max_step * timestep); self.time_box.setValue(step * timestep); self.time_box.setSuffix(" s"); self.time_box.setSingleStep(max(0.01, self.time_box.value()*0.02) if self.time_box.value() > 0 else 0.01)
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
        self.strain_box = TrimDoubleSpinBox(); self.strain_box.setRange(min_strain, max_strain); self.strain_box.setValue(strain); self.strain_box.setSingleStep(max(0.01, abs(strain)*0.02 if strain != 0 else 0.01))
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
        
        self.amplitude_box = TrimDoubleSpinBox()
        self.amplitude_box.setRange(0.0, max(abs(min_strain), abs(max_strain)))
        self.amplitude_box.setValue(amplitude)
        self.amplitude_box.setSingleStep(0.01)
        
        self.peak_box = TrimDoubleSpinBox()
        self.peak_box.setRange(min_strain, max_strain)
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

class LateralContractDialog(QDialog):
    def __init__(self, current_overrides, study_settings, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Modify Lateral Contraction")
        self.widgets = {}
        
        layout = QFormLayout(self)
        
        for axis, setting in study_settings.items():
            combo = QComboBox()
            
            # Determine options based on study-wide setting
            # setting is either "free (NPT)" or "constrained"
            
            keep_display_text = f"keep ({setting})"
            combo.addItem(keep_display_text, "keep") # Store actual value in UserData
            
            if setting == "free (NPT)":
                combo.addItem("constrained", "constrained")
            else:
                combo.addItem("free (NPT)", "free (NPT)")
            
            # Set current value
            current_val = current_overrides.get(axis, "keep")
            
            # Find index matching current value
            # If current_val matches the data of the second item, select it. Else select "keep".
            if current_val == combo.itemData(1): # Check if it matches the non-keep option
                combo.setCurrentIndex(1)
            else:
                combo.setCurrentIndex(0) # Default to keep
            
            self.widgets[axis] = combo
            layout.addRow(f"Lateral {axis}:", combo) # Label remains simple
            
        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel)
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)
        
    def get_overrides(self):
        result = {}
        for axis, combo in self.widgets.items():
            val = combo.currentData()
            if val != "keep":
                result[axis] = val
        return result

# --- Main Graph Widget ---
class GraphWidget(QWidget):
    dataChanged = pyqtSignal()
    commitPoint = pyqtSignal()  # user commit points for undo tracking only
    handleInserted = pyqtSignal(int)
    handleDeleted = pyqtSignal(int)
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
        # Handles were rescaled/clamped, so every sine has to be re-fitted to them and
        # re-checked against the new strain range - otherwise its curve detaches.
        for seg_idx in range(len(self.segments)):
            self._resync_sine_amplitude(seg_idx)
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
    def update_cache_insert(self, index):
        """Update all cached segment overrides by inserting an empty entry at index."""
        for axis in self._segment_overrides_cache:
            overrides_list = self._segment_overrides_cache[axis]
            # Always insert; list.insert handles index >= len by appending
            overrides_list.insert(index, {})
            
            # Reset the previous segment if we inserted inside the graph (split)
            # This matches the logic in GraphWidget for the current view
            # If we split segment i (now i and i+1), i is reset.
            if 0 < index < len(overrides_list):
                 overrides_list[index-1] = {}

    def update_cache_delete(self, seg_idx):
        """Update all cached segment overrides by removing entry at seg_idx and resetting the new entry at that position."""
        for axis in self._segment_overrides_cache:
            overrides_list = self._segment_overrides_cache[axis]
            if 0 <= seg_idx < len(overrides_list):
                overrides_list.pop(seg_idx)
                # Reset the segment that moved into this position (merged result)
                # This corresponds to the 'merged' segment after deletion
                if seg_idx < len(overrides_list):
                    overrides_list[seg_idx] = {}

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
            # If it's the last handle and strain recovery is active, don't make it clickable
            if i == len(self.points_norm) - 1 and i > 0:
                if self.segments[i-1].get('strain_recovery', False):
                    continue
            
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
    def _ordered_clickable_regions(self):
        # Handle value labels paint on top of slope labels, so they win
        # hit-testing too. Stable sort keeps every other priority as-is.
        return sorted(self._clickable_regions, key=lambda r: 0 if r[1] in ("y_val", "x_val") else 1)
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
                is_recovery = segment_info.get('strain_recovery', False)
                
                # Check for overrides
                line_color = self.STYLE_LINE
                overrides = segment_info.get('lateral_overrides', {})
                if overrides:
                    line_color = QColor("purple")

                if is_recovery:
                    # Force segment type to line
                    segment_info['type'] = 'line'
                    
                    # Draw dashed line instead of gradient
                    painter.setPen(QPen(line_color, 2, Qt.PenStyle.DashLine))
                    painter.drawLine(p1_w, p2_w)
                    
                    # Skip slope text for recovery segment (no fixed rate target)
                    
                elif segment_info['type'] == 'line':
                    painter.setPen(QPen(line_color, 2)); painter.drawLine(p1_w, p2_w)
                    p1_d, p2_d = self._norm_to_data(self.points_norm[i]), self._norm_to_data(self.points_norm[i+1])
                    dx_s, dy_e, dx_t = p2_d.x() - p1_d.x(), p2_d.y() - p1_d.y(), (p2_d.x() - p1_d.x()) * self._timestep
                    slope, rate = (dy_e / dx_s if dx_s != 0 else float('inf')), (dy_e / dx_t if dx_t != 0 else float('inf'))
                    slope_text = f"{slope:.4e} {self.get_y_unit()}/step"
                    rate_text = f"{rate:.4e} {self.get_y_unit()}/t"
                    slope_rect = QRectF(fm.boundingRect(slope_text).adjusted(-2,-2,2,2)); slope_rect.moveCenter((p1_w * 2/3 + p2_w * 1/3) - QPointF(0, 20))
                    rate_rect = QRectF(fm.boundingRect(rate_text).adjusted(-2,-2,2,2)); rate_rect.moveCenter((p1_w * 2/3 + p2_w * 1/3) - QPointF(0, 6))
                    if segment_info.get('fixed_slope', False):
                        painter.setPen(QColor("red"))
                    else:
                        painter.setPen(STYLE_SLOPE_TEXT)
                    painter.setFont(QFont("Arial", 9, QFont.Weight.Bold)); painter.drawText(slope_rect, slope_text)
                    if segment_info.get('fixed_slope', False):
                        painter.setPen(QColor("red"))
                    else:
                        painter.setPen(STYLE_TEXT_SECONDARY)
                    painter.drawText(rate_rect, rate_text)
                    self._clickable_regions.append((slope_rect.united(rate_rect), "slope", i))
                elif segment_info['type'] == 'sine':
                    self._draw_sine_segment(painter, i, p1_w, p2_w, segment_info, line_color)            
            
                # Draw lateral override labels
                if overrides:
                    line_segment_center_x = (p1_w.x() + p2_w.x()) / 2
                    # Position slightly below the line itself. Adjust vertical offset based on whether slope text is drawn
                    y_pos_below_line = ((p1_w.y() + p2_w.y()) / 2) + 15
                    
                    font = QFont("Arial", 9, QFont.Weight.Bold)
                    painter.setFont(font)
                    
                    sorted_axes = sorted(overrides.keys())
                    
                    # Calculate total width for centering
                    total_text_width = 0
                    for axis in sorted_axes:
                        total_text_width += fm.horizontalAdvance(axis)
                    total_text_width += (len(sorted_axes) - 1) * 5 # Add 5px space between letters
                    
                    current_x = line_segment_center_x - (total_text_width / 2)
                    
                    for axis in sorted_axes:
                        val = overrides[axis]
                        if val == "free (NPT)": color = QColor("green")
                        else: color = QColor("red")
                        
                        painter.setPen(color)
                        text_width = fm.horizontalAdvance(axis)
                        text_rect = QRectF(current_x, y_pos_below_line, text_width, fm.height())
                        painter.drawText(text_rect, Qt.AlignmentFlag.AlignVCenter, axis)
                        current_x += text_width + 5 # Move to next position with spacing

            for i, p_norm in enumerate(self.points_norm):
                # Hide last handle if recovery enabled
                if i == len(self.points_norm) - 1 and i > 0:
                    if self.segments[i-1].get('strain_recovery', False):
                        continue

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
                t_str = f"{p_data.x() * self._timestep:.2f}".rstrip('0').rstrip('.')
                sep = " " if self._time_unit else ""
                step_text, time_text = f"{p_data.x():.0f}", f"({t_str}{sep}{self._time_unit})"
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
        painter.translate(40, int(self.height() / 2) + 44); painter.rotate(-90)
        y_label = "Temperature / K" if self.mode == 'Temperature' else f"Engineering strain {self.get_y_unit()} / 1"
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

    def _draw_sine_segment(self, painter, segment_index, p1_w, p2_w, segment_info, line_color=None):
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

        # Draw the sine wave in the normal style color or override
        painter.setPen(QPen(line_color if line_color else self.STYLE_LINE, 2))
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
                
                if segment_info.get('fixed_slope', False):
                    painter.setPen(QColor("red"))
                else:
                    painter.setPen(STYLE_SLOPE_TEXT)
                painter.setFont(QFont("Arial", 9, QFont.Weight.Bold)); painter.drawText(slope_rect, slope_text)
                
                # Use red for rate_text too if slope is fixed
                if segment_info.get('fixed_slope', False):
                    painter.setPen(QColor("red"))
                else:
                    painter.setPen(STYLE_TEXT_SECONDARY)
                painter.drawText(rate_rect, rate_text)
                
                # Register clickable region for context menu
                self._clickable_regions.append((slope_rect.united(rate_rect), "slope", segment_index))

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

    def _is_shear_deformation(self):
        parent_study_widget = self.parent()
        if parent_study_widget and hasattr(parent_study_widget, 'deform_axis_combo'):
            return parent_study_widget.deform_axis_combo.currentText() in ["xy", "xz", "yz"]
        return False

    def get_y_unit(self):
        if self.mode == 'Temperature':
            return "ΔT"
        return "γ" if self._is_shear_deformation() else "ε"
    
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
                        # Prevent dragging if strain recovery is active for this segment
                        if self.segments[self._dragged_segment_index].get('strain_recovery', False):
                            self._dragged_segment_index = None
                        else:
                            # Segments can always be selected for dragging...
                            i = self._dragged_segment_index
                            p1_w = self._norm_to_widget(self.points_norm[i])
                            self._drag_mouse_to_p1_offset = self._drag_start_pos_widget - p1_w
                            self._segment_drag_offset_norm = self.points_norm[i+1] - self.points_norm[i]
        elif event.button() == Qt.MouseButton.RightButton:
            # Handle right-click for locking/unlocking x-axis ticks, y-value labels, and slope segments
            pos = event.position()
            for region, type, index in self._ordered_clickable_regions():
                if region.contains(pos):
                    if type == "slope":
                        # Slope locking is handled exactly once, in contextMenuEvent.
                        # Qt delivers BOTH a right-button press and a context-menu event
                        # for a single right-click, so toggling here as well used to leave
                        # a stale entry in the legacy _fixed_segments set after unlocking.
                        return
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
                    self.commitPoint.emit()
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
                    
                    # --- NEW: Final safeguard check using _calculate_max_safe_amplitude ---
                    # The logic above clamps the handle position, but the resulting amplitude might still cause
                    # OTHER parts of the wave to exceed bounds (e.g. if the handle is not at the peak).
                    # We reverse-check: is this amplitude safe for the current baseline?
                    # Note: p1_d is the baseline starting Y.
                    max_safe = self._calculate_max_safe_amplitude(scheme, num_cycles, p1_d.y())
                    new_amplitude = min(new_amplitude, max_safe)
                    # ----------------------------------------------------------------------
            
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
            
            # Calculate new position early for rigid group offset logic
            constrained_pos = event.position()
            target_p_norm = self._widget_to_norm(constrained_pos)
            
            # Respect X-locking constraints immediately so rigid group logic sees correct X
            if i in self._locked_x_ticks:
                target_p_norm.setX(self.points_norm[i].x())
            if i in self._locked_y_labels:
                target_p_norm.setY(self.points_norm[i].y())

            # Also respect Drag constraints (e.g. if Shift is held, or specific axis locks)
            # (Assuming simplified logic for now, standard dragging)

            # --- Resolve the dragged handle's final X up front ---
            # Every slope/offset calculation below derives dy from dx, so it has to see
            # the X that is actually going to be applied. Resolving it afterwards (as was
            # done before) let the boundary/neighbour clamps silently change dx and thereby
            # break fixed slopes.
            new_x_i = self._resolve_dragged_handle_x(i, self._norm_to_data(target_p_norm).x())
            p_current_data = self._norm_to_data(target_p_norm)

            # Helper to check rigidity
            def is_rigid(idx):
                return self._is_segment_rigid_vertical(idx)

            # Helper to calculate dy based on dx and segment properties
            # For segments with fixed_slope: calculate dy from slope equation
            # For implicitly rigid segments (full cycles): dy = 0 (endpoints at same Y)
            calculate_dy = self._fixed_slope_dy

            def solve(x_i):
                """Rigid group and clamped Y for the dragged handle placed at x_i.

                Returns (offsets, y, hit_frame) where hit_frame reports that the wanted Y
                had to be pulled back to keep the group inside the top/bottom of the frame.
                """
                # --- Determine Moving Handles (Rigid Group / Constraints) ---
                rigid_offsets = {i: 0.0}
                left_anchor = None # (anchor_idx, seg_idx_connecting_to_group)
                right_anchor = None

                # Temporary X coordinates for offset calculation
                current_xs = {}
                for idx in range(len(self.points_norm)):
                    if idx == i:
                        current_xs[idx] = x_i
                    else:
                        current_xs[idx] = self._norm_to_data(self.points_norm[idx]).x()

                # Propagate Left
                curr = i
                while curr > 0:
                    seg_idx = curr - 1
                    neighbor_idx = curr - 1

                    # Check for Locks (Anchors)
                    neighbor_locked = (neighbor_idx in self._locked_y_labels) or \
                                      (neighbor_idx == 0 and self.mode == 'Deformation')

                    if is_rigid(seg_idx):
                        if neighbor_locked:
                            left_anchor = (neighbor_idx, seg_idx)
                            break

                        dx = current_xs[curr] - current_xs[curr-1]
                        dy = calculate_dy(seg_idx, dx)

                        # Relation: Y_curr = Y_prev + dy => Y_prev = Y_curr - dy
                        rigid_offsets[curr-1] = rigid_offsets[curr] - dy
                        curr -= 1
                    else:
                        break

                # Propagate Right
                curr = i
                while curr < len(self.points_norm) - 1:
                    seg_idx = curr
                    neighbor_idx = curr + 1

                    # Check for Locks (Anchors)
                    neighbor_locked = (neighbor_idx in self._locked_y_labels)

                    if is_rigid(seg_idx):
                        if neighbor_locked:
                            right_anchor = (neighbor_idx, seg_idx)
                            break

                        dx = current_xs[curr+1] - current_xs[curr]
                        dy = calculate_dy(seg_idx, dx)

                        # Relation: Y_next = Y_curr + dy
                        rigid_offsets[curr+1] = rigid_offsets[curr] + dy
                        curr += 1
                    else:
                        break

                # --- Calculate Safe Y Range using Helper ---
                min_y, max_y = self._get_safe_y_range_for_moving_handles(rigid_offsets)
                anchored = False

                # --- Apply Anchor Constraints ---
                # If constrained by anchors via rigid segments, the valid Y range likely collapses to a single value.

                if left_anchor:
                    a_idx, seg_idx = left_anchor
                    # Calculate required Y for the handle NEXT to the anchor (which is a_idx + 1)
                    # Relation: y_{a+1} = y_a + dy
                    # But 'a' is locked, so y_a is fixed.
                    y_anchor = self._norm_to_data(self.points_norm[a_idx]).y()
                    dx = current_xs[a_idx+1] - current_xs[a_idx]
                    dy = calculate_dy(seg_idx, dx)

                    target_y_next = y_anchor + dy

                    # We know 'a_idx + 1' is in rigid_offsets.
                    # rigid_offsets maps idx -> offset_from_i.  y_idx = y_i + offset_idx
                    # So y_{a+1} = y_i + offset_{a+1} = target_y_next
                    # y_i = target_y_next - offset_{a+1}

                    required_y_i = target_y_next - rigid_offsets[a_idx+1]

                    # Use exact value, clamped to global bounds
                    min_y = max(min_y, required_y_i)
                    max_y = min(max_y, required_y_i)
                    anchored = True

                if right_anchor:
                    a_idx, seg_idx = right_anchor
                    # Relation: y_a = y_{a-1} + dy
                    # y_{a-1} = y_a - dy
                    y_anchor = self._norm_to_data(self.points_norm[a_idx]).y()
                    dx = current_xs[a_idx] - current_xs[a_idx-1]
                    dy = calculate_dy(seg_idx, dx)

                    target_y_prev = y_anchor - dy

                    # y_{a-1} = y_i + offset_{a-1}
                    # y_i = target_y_prev - offset_{a-1}

                    required_y_i = target_y_prev - rigid_offsets[a_idx-1]

                    # Use exact value, clamped to global bounds
                    min_y = max(min_y, required_y_i)
                    max_y = min(max_y, required_y_i)
                    anchored = True

                # Is the group held together by a slope the user locked? An anchored
                # group is tied through the anchoring segment, which is not itself part
                # of the group, so it has to be checked separately.
                slope_locked = self._drag_group_has_slope_lock(rigid_offsets)
                for anchor in (left_anchor, right_anchor):
                    if anchor and self._is_slope_locked(anchor[1]):
                        slope_locked = True

                # --- Apply Clamping ---
                # If dragged handle has Y locked, use the locked Y value directly
                # (bypass clamping which might conflict with sine geometry constraints)
                if i in self._locked_y_labels:
                    return rigid_offsets, self._norm_to_data(self.points_norm[i]).y(), False, slope_locked
                # If anchors constrained us to a single Y value, use it exactly
                if anchored or abs(max_y - min_y) < 1e-9:
                    y = (min_y + max_y) / 2
                    # The anchor dictates Y for this X. If that puts any handle of the
                    # group outside the frame, this X is simply not reachable.
                    outside = any(not (self._min_strain - 1e-9 <= y + off <= self._max_strain + 1e-9)
                                  for off in rigid_offsets.values())
                    return rigid_offsets, y, outside, slope_locked

                wanted_y = p_current_data.y()
                clamped_y = max(min_y, min(max_y, wanted_y))
                return rigid_offsets, clamped_y, abs(clamped_y - wanted_y) > 1e-12, slope_locked

            rigid_offsets, clamped_y, hit_frame, slope_locked = solve(new_x_i)

            # A locked slope must not be traded away just because the group ran into the
            # top or bottom of the frame. Once it touches, the drag stops instead of
            # sliding along the edge (sliding keeps its slope but silently reshapes the
            # profile, because the locked segment gets shorter or longer as it goes).
            if hit_frame and slope_locked:
                new_x_i = round(self._norm_to_data(self.points_norm[i]).x())
                rigid_offsets, clamped_y, hit_frame, slope_locked = solve(new_x_i)
                if hit_frame:
                    return   # already hard against the edge - nothing may move

            # --- Update All Moving Handles ---
            for idx, offset in rigid_offsets.items():
                p_idx_data = self._norm_to_data(self.points_norm[idx])
                p_idx_data.setY(clamped_y + offset)
                
                if idx == i:
                    # X was already resolved (endpoints pinned, neighbour-clamped and
                    # snapped to integer steps) before the slope propagation above.
                    p_idx_data.setX(new_x_i)

                self.points_norm[idx] = self._data_to_norm(p_idx_data)
            
            # Ensure sorting/consistency
            self._sort_points()
            
            # Update Sine Amplitudes for Connected Segments (if handles moved)
            self._resync_adjacent_sines(i)

            self.dataChanged.emit()
        elif self._dragged_segment_index is not None:
            i = self._dragged_segment_index

            # A locked neighbour has to keep its slope, so the handle this segment shares
            # with it may only travel ALONG that neighbour's line: the segment then slides
            # as a whole with dy = slope * dx. With both neighbours locked there is no such
            # direction left, so the segment cannot be moved at all.
            prev_locked = self._is_slope_locked(i - 1) if i > 0 else False
            next_locked = self._is_slope_locked(i + 1) if (i + 2) < len(self.points_norm) else False
            if prev_locked and next_locked:
                return

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

                # Special handling for the last segment to mimic first segment behavior (mirrored)
                # Ensure the right-most point stays at x=max (normalized 1.0)
                if i == len(self.points_norm) - 2:
                    p1_new_norm.setX(1.0 - self._segment_drag_offset_norm.x())
                    p1_new_data = self._norm_to_data(p1_new_norm) # Sync data for subsequent Y clamping

                if prev_locked or next_locked:
                    # Ride the locked neighbour's line. Nothing is clamped here on purpose:
                    # nudging the segment back into the frame would tilt that neighbour, so
                    # a move that does not fit is refused and the segment stops instead.
                    if prev_locked:
                        anchor = self._norm_to_data(self.points_norm[i-1])
                        slope = self._locked_slope_value(i-1)
                        p1_new_data.setY(anchor.y() + slope * (p1_new_data.x() - anchor.x()))
                        p1_new_norm = self._data_to_norm(p1_new_data)
                        p2_new_norm = p1_new_norm + self._segment_drag_offset_norm
                    else:
                        anchor = self._norm_to_data(self.points_norm[i+2])
                        slope = self._locked_slope_value(i+1)
                        p2_new_data = self._norm_to_data(p1_new_norm + self._segment_drag_offset_norm)
                        p2_new_data.setY(anchor.y() - slope * (anchor.x() - p2_new_data.x()))
                        p2_new_norm = self._data_to_norm(p2_new_data)
                        p1_new_norm = p2_new_norm - self._segment_drag_offset_norm

                    if not self._segment_within_frame(i, p1_new_norm, p2_new_norm):
                        return
                else:
                    # --- Start: NEW logic for boundary clamping for SINE segments ---
                    p2_new_norm = p1_new_norm + self._segment_drag_offset_norm
                    p2_new_data = self._norm_to_data(p2_new_norm)
                    min_y_data = min(p1_new_data.y(), p2_new_data.y())
                    max_y_data = max(p1_new_data.y(), p2_new_data.y())

                    if self.segments[i]['type'] == 'sine':
                        # Use the improved method that handles stored amplitude appropriately
                        amp, y_center, _ = self._get_sine_parameters_with_stored_amp(p1_new_data, p2_new_data, self.segments[i], i)

                        # Use exact unit wave excursions for precise bounds checking
                        min_ex, max_ex = self._get_unit_wave_excursions(self.segments[i]['scheme'], self.segments[i]['num_cycles'])
                        if amp is not None:
                            # amp is magnitude
                            # y_start = p1_new_data.y(). The wave is relative to this start point.
                            # y_val = y_start + Amp * unit_val
                            # So min_y = y_start + Amp * min_ex
                            # max_y = y_start + Amp * max_ex

                            min_y_data = p1_new_data.y() + abs(amp) * min_ex
                            max_y_data = p1_new_data.y() + abs(amp) * max_ex

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
                if (p_prev is None or p1_new_norm.x() >= p_prev.x()) and (p_next is None or p2_new_norm.x() <= p_next.x()) and all(-1e-9 <= p.y() <= 1.0 + 1e-9 for p in [p1_new_norm, p2_new_norm]):
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
        self.commitPoint.emit()
        self.dataChanged.emit()
    def mouseDoubleClickEvent(self, event):
        if event.button() == Qt.MouseButton.LeftButton:
            # 1. Check if a clickable region (slope, x_val, y_val) is hit
            for region, type, index in self._ordered_clickable_regions():
                if region.contains(event.position()):
                    self._handle_direct_edit(type, index)
                    return
            
            # 2. Check if a segment is hit
            seg_idx = self._get_segment_at(event.position())
            if seg_idx is not None:
                # --- Topology Change: Splitting a segment (seg_idx) ---
                # This original segment at seg_idx is being replaced by two new segments.
                # Reset overrides and strain_recovery for these two new parts.
                
                # Check if original seg_idx was the last segment.
                was_original_last_segment = (seg_idx == len(self.segments) - 1)

                new_p_norm = self._data_to_norm(self._snap_data_point(self._norm_to_data(self._widget_to_norm(event.position()))))
                self.points_norm.insert(seg_idx + 1, new_p_norm) # Insert new point at original seg_idx+1
                
                # Reset left part of split (implicitly clears overrides and strain_recovery)
                self.segments[seg_idx] = {'type': 'line'}
                # Reset right part of split (implicitly clears overrides and strain_recovery)
                self.segments.insert(seg_idx + 1, {'type': 'line'})
                
                # Emit signal for cache update
                self.handleInserted.emit(seg_idx + 1)
                
                # If original seg_idx was the last segment, clear strain_recovery on the new last segment
                if was_original_last_segment and seg_idx + 1 < len(self.segments):
                    if 'strain_recovery' in self.segments[seg_idx + 1]:
                        del self.segments[seg_idx + 1]['strain_recovery']
                
                self.update(); self.dataChanged.emit()
                return # Event handled

            # 3. If nothing else is hit, add a new point at the clicked position
            new_p_norm = self._data_to_norm(self._snap_data_point(self._norm_to_data(self._widget_to_norm(event.position()))))
            
            # Find correct insertion index to maintain segment synchronization
            insert_idx = len(self.points_norm)
            for i, p in enumerate(self.points_norm):
                if new_p_norm.x() < p.x():
                    insert_idx = i
                    break
            
            # --- Topology Change: Adding a new point ---
            # Check if insertion point affects the last segment (i.e., new point is inside or becomes the end of the last segment)
            was_last_segment_affected = (insert_idx == len(self.segments))
            
            self.points_norm.insert(insert_idx, new_p_norm)
            self.segments.insert(insert_idx, {'type': 'line'}) # New segment is clean
            
            # Emit signal for cache update
            self.handleInserted.emit(insert_idx)
            
            # If inserting inside an existing segment (not at start/end of graph), reset the left part
            if 0 < insert_idx < len(self.points_norm) - 1:
                self.segments[insert_idx - 1] = {'type': 'line'} # Left part of split is reset
            
            # If the new point affected the last segment (either by splitting it or appending to it), 
            # clear strain_recovery on the new last segment
            if was_last_segment_affected:
                if 'strain_recovery' in self.segments[insert_idx]:
                    del self.segments[insert_idx]['strain_recovery']
            
            self.update(); self.dataChanged.emit()
    def contextMenuEvent(self, event):
        pos_f = QPointF(event.pos())
        
        # 1. Check clickable regions first (Slope Labels, Axis Labels)
        for region, type, index in self._ordered_clickable_regions():
            if region.contains(pos_f):
                if type == "slope":
                    # Immediately toggle fixed slope state (no context menu)
                    self._toggle_fixed_slope(index)
                    return
                # Optional: Add context menu for X/Y labels if desired (currently double-click edits)

        # 2. Check Handle
        idx = self._get_handle_at(pos_f)
        if idx is not None:
            menu = QMenu(self)
            menu.addAction("Set Coordinates...", lambda: self._show_set_coords_dialog(idx))
            
            # Fix Strain (Y)
            fix_y_action = menu.addAction("Fix Strain (Y)")
            fix_y_action.setCheckable(True)
            fix_y_action.setChecked(idx in self._locked_y_labels)
            def toggle_y_lock():
                if idx in self._locked_y_labels: self._locked_y_labels.remove(idx)
                else: self._locked_y_labels.add(idx)
                self.update()
                self.commitPoint.emit()
            fix_y_action.triggered.connect(toggle_y_lock)
            
            # Fix Time Step (X)
            fix_x_action = menu.addAction("Fix Time Step (X)")
            fix_x_action.setCheckable(True)
            fix_x_action.setChecked(idx in self._locked_x_ticks)
            def toggle_x_lock():
                if idx in self._locked_x_ticks: self._locked_x_ticks.remove(idx)
                else: self._locked_x_ticks.add(idx)
                self.update()
                self.commitPoint.emit()
            fix_x_action.triggered.connect(toggle_x_lock)

            if 0 < idx < len(self.points_norm) - 1: menu.addAction("Delete Handle", lambda: self._delete_handle(idx))
            menu.exec(event.globalPos())
        else: # Check for segment (hit test on line/curve)
            seg_idx = self._get_segment_at(pos_f)
            if seg_idx is not None:
                menu = QMenu(self)
                if self.segments[seg_idx]['type'] == 'line':
                    if self.mode != 'Temperature':
                        menu.addAction("Insert Sine...", lambda: self._show_insert_sine_dialog(seg_idx))
                elif self.segments[seg_idx]['type'] == 'sine':
                    menu.addAction("Edit Sine Properties...", lambda: self._show_sine_properties_dialog(seg_idx))
                    menu.addAction("Change to Line", lambda: self._change_segment_type(seg_idx, 'line'))
                
                # Fixed Slope Option
                fix_slope_action = menu.addAction("Fix Slope/Rate")
                fix_slope_action.setCheckable(True)
                fix_slope_action.setChecked(self.segments[seg_idx].get('fixed_slope', False))
                fix_slope_action.triggered.connect(lambda: self._toggle_fixed_slope(seg_idx))
                
                if self.mode == 'Deformation':
                    menu.addAction("Modify lateral contract.", lambda: self._show_lateral_contract_dialog(seg_idx))
                    
                    if seg_idx == len(self.segments) - 1:
                        recovery_action = menu.addAction("Strain recovery")
                        recovery_action.setCheckable(True)
                        recovery_action.setChecked(self.segments[seg_idx].get('strain_recovery', False))
                        recovery_action.triggered.connect(lambda: self._toggle_strain_recovery(seg_idx))
                    
                menu.exec(event.globalPos())

    def _show_lateral_contract_dialog(self, seg_idx):
        study_widget = self.parent()
        if not study_widget or not hasattr(study_widget, 'lateral_widgets'):
            return
            
        study_settings = {axis: w.currentText() for axis, w in study_widget.lateral_widgets.items()}
        current_overrides = self.segments[seg_idx].get('lateral_overrides', {})
        
        dialog = LateralContractDialog(current_overrides, study_settings, self)
        if dialog.exec():
            new_overrides = dialog.get_overrides()
            self.commitPoint.emit()
            if new_overrides:
                self.segments[seg_idx]['lateral_overrides'] = new_overrides
            else:
                # Remove key if empty to keep dict clean
                if 'lateral_overrides' in self.segments[seg_idx]:
                    del self.segments[seg_idx]['lateral_overrides']
            self.update()
            self.dataChanged.emit()

    def _toggle_strain_recovery(self, seg_idx):
        current = self.segments[seg_idx].get('strain_recovery', False)
        self.segments[seg_idx]['strain_recovery'] = not current
        
        # If enabling recovery, force the last handle to Y=0
        if not current:
             if seg_idx < len(self.points_norm) - 1:
                 last_point_idx = seg_idx + 1
                 p_norm = self.points_norm[last_point_idx]
                 p_data = self._norm_to_data(p_norm)
                 p_data.setY(0.0)
                 self.points_norm[last_point_idx] = self._data_to_norm(p_data)

        self.update()
        self.dataChanged.emit()
        self.commitPoint.emit()

    def _change_segment_type(self, seg_idx, new_type):
        seg = self.segments[seg_idx]
        is_fixed = seg.get('fixed_slope', False)
        target_slope = seg.get('fixed_slope_value', 0) if is_fixed else 0
        
        # If explicitly fixed, or if we want to preserve visual slope even if not fixed?
        # User said: "make sure that when a line slope is red and we change to sine, try to keep this slope as midpoint slope"
        # And "Of course, graphically, the red highlighting... should then be translatable"
        
        self.segments[seg_idx]['type'] = new_type
        self.commitPoint.emit()
        
        if is_fixed:
             # Calculate parameters to match the target slope
             # Need geometry
             p1 = self._norm_to_data(self.points_norm[seg_idx])
             p2 = self._norm_to_data(self.points_norm[seg_idx+1])
             dx = p2.x() - p1.x()
             if abs(dx) < 1e-9: return # Vertical segment...
             
             if new_type == 'line':
                 # Target: dy/dx = m  => dy = m*dx
                 # We must move p2 to match slope. (Or p1?)
                 # Standard: Move P2 Y.
                 new_y2 = p1.y() + target_slope * dx
                 
                 # Check bounds?
                 new_y2 = max(self._min_strain, min(self._max_strain, new_y2))
                 # Update Slope if clamped? No, keep it fixed but clamp geometry?
                 # If we assume 'Fixed Slope' takes precedence, we strictly set it.
                 # If it exceeds bounds, maybe we can't switch? 
                 # Let's clamp and update stored slope value if we must?
                 # Or just set coordinate.
                 
                 p2_data = self._norm_to_data(self.points_norm[seg_idx+1])
                 p2_data.setY(new_y2)
                 self.points_norm[seg_idx+1] = self._data_to_norm(p2_data)
                 
             elif new_type == 'sine':
                 # Target: Midpoint Slope = m
                 # m = A * k * cos(phase).
                 # We need to find A.
                 # A = m / (k * cos(phase))
                 
                 # Default Scheme/Cycles
                 num_cycles = seg.get('num_cycles', 1.0)
                 scheme = seg.get('scheme', "Alternating (tensile start)")
                 
                 k = num_cycles * 2 * math.pi / dx
                 
                 # Determine phase
                 phi_start = 0
                 if "Alternating" in scheme:
                    phi_start = math.pi if "compressive" in scheme else 0
                 elif "Pulsating" in scheme:
                    phi_start = -math.pi/2 if "tensile" in scheme else math.pi/2
                 
                 # Find phase at zero crossing
                 n = 0
                 first_zero_x_offset = -1
                 while True:
                    x_offset = (n * math.pi - phi_start) / k if k != 0 else -1
                    if x_offset >= -1e-9 and x_offset <= dx + 1e-9:
                        first_zero_x_offset = x_offset
                        break
                    n += 1
                    if n > 1000: break
                 
                 if first_zero_x_offset != -1:
                     phase = k * first_zero_x_offset + phi_start
                     cos_val = math.cos(phase)
                     if abs(cos_val) > 1e-9:
                         new_amp = target_slope / (k * cos_val)
                         seg['amplitude'] = new_amp
                         
                         # Also need to update P2 based on new amplitude?
                         # For Alternating: y2 = y1 + Amp * sin(end). (If end != 0).
                         # For Pulsating: y2 = y1 + Amp * (sin(end) - sin(start))
                         
                         end_angle = num_cycles * 2 * math.pi + phi_start
                         sin_end = math.sin(end_angle)
                         sin_start = math.sin(phi_start)
                         
                         # Check if y2 is free or fixed?
                         # Usually we adjust y2 to fit the sine shape if Amp is defined.
                         # y2 = y1 + Amp * (sin_end - sin_start)
                         new_y2 = p1.y() + new_amp * (sin_end - sin_start)
                         
                         # Clamp
                         new_y2 = max(self._min_strain, min(self._max_strain, new_y2))
                         
                         p2_data = self._norm_to_data(self.points_norm[seg_idx+1])
                         p2_data.setY(new_y2)
                         self.points_norm[seg_idx+1] = self._data_to_norm(p2_data)

        self.update()
        self.dataChanged.emit()

    def _calculate_segment_slope(self, seg_idx):
        """Calculates current slope (Line) or midpoint slope (Sine)."""
        if seg_idx < 0 or seg_idx >= len(self.segments): return 0
        seg = self.segments[seg_idx]
        p1 = self._norm_to_data(self.points_norm[seg_idx])
        p2 = self._norm_to_data(self.points_norm[seg_idx+1])
        
        if seg['type'] == 'line':
            dx = p2.x() - p1.x()
            dy = p2.y() - p1.y()
            return dy / dx if dx != 0 else 0
            
        elif seg['type'] == 'sine':
            amplitude, y_center, phi_start = self._get_sine_parameters_with_stored_amp(p1, p2, seg, seg_idx)
            if amplitude is None: return 0
            
            x_range = p2.x() - p1.x()
            k = seg['num_cycles'] * 2 * math.pi / x_range if x_range != 0 else 0
            
            # Find first zero crossing (same logic as in _draw_sine_segment)
            n = 0
            first_zero_x_offset = -1
            while True:
                x_d_offset = (n * math.pi - phi_start) / k if k != 0 else -1
                if x_d_offset >= -1e-9 and x_d_offset <= x_range + 1e-9:
                    first_zero_x_offset = x_d_offset
                    break
                n += 1
                if n > 1000: break
            
            if first_zero_x_offset != -1:
                phase = k * first_zero_x_offset + phi_start
                return amplitude * k * math.cos(phase)
            return 0 

    def _toggle_fixed_slope(self, seg_idx):
        currently_fixed = self.segments[seg_idx].get('fixed_slope', False)

        # The legacy _fixed_segments set is superseded by the per-segment
        # 'fixed_slope' flag. Drop any entry in both directions so a stale one can
        # never re-enable the old constraint path (which does not pin the last handle).
        if hasattr(self, '_fixed_segments'):
            self._fixed_segments.discard(seg_idx)

        if not currently_fixed:
            # Locking the slope
            current_slope = self._calculate_segment_slope(seg_idx)
            self.segments[seg_idx]['fixed_slope'] = True
            self.segments[seg_idx]['fixed_slope_value'] = current_slope
        else:
            # Unlocking
            self.segments[seg_idx]['fixed_slope'] = False
            # We can keep the value stored or clear it, doesn't matter much.
            
        self.update()
        self.dataChanged.emit()
        self.commitPoint.emit()

    def _get_unit_wave_excursions(self, scheme, num_cycles):
        """
        Calculates the min and max values of a unit sine wave (amplitude=1) relative to its baseline.
        Returns (min_excursion, max_excursion).
        """
        unit_amp = 1.0
        phi_start = 0
        y_center_offset = 0
        
        if "Alternating" in scheme:
            if "compressive start" in scheme:
                unit_amp = -1.0
        elif "Pulsating tensile" in scheme:
            y_center_offset = 1.0
            phi_start = -math.pi / 2
        elif "Pulsating compressive" in scheme:
            y_center_offset = -1.0
            phi_start = math.pi / 2

        # 2. Find min/max values of the unit wave relative to baseline
        limit_theta = num_cycles * 2 * math.pi
        
        # Check critical points: start, end, and local extrema
        points_to_check = [0, limit_theta]
        
        k_start = math.ceil((phi_start - math.pi/2) / math.pi) - 2 
        k_end = math.floor((limit_theta + phi_start - math.pi/2) / math.pi) + 2
        
        for k in range(int(k_start), int(k_end) + 1):
            theta = (math.pi / 2) - phi_start + k * math.pi
            if 0 <= theta <= limit_theta:
                points_to_check.append(theta)
                
        vals = []
        for theta in points_to_check:
            val = y_center_offset + unit_amp * math.sin(theta + phi_start)
            vals.append(val)
            
        return min(vals), max(vals)

    def _calculate_max_safe_amplitude(self, scheme, num_cycles, y_baseline):
        """
        Calculates the maximum safe amplitude (magnitude) for a sine wave starting at y_baseline
        so that it never exceeds self._min_strain or self._max_strain.
        """
        min_unit_excursion, max_unit_excursion = self._get_unit_wave_excursions(scheme, num_cycles)
        
        # 3. Calculate max safe amplitude
        possible_amps = []
        
        # Upper bound constraint
        if max_unit_excursion > 0:
            a_limit = (self._max_strain - y_baseline) / max_unit_excursion
            if a_limit >= 0: possible_amps.append(a_limit)
        elif max_unit_excursion == 0:
            pass 
            
        # Lower bound constraint
        if min_unit_excursion < 0:
            a_limit = (y_baseline - self._min_strain) / abs(min_unit_excursion)
            if a_limit >= 0: possible_amps.append(a_limit)
        elif min_unit_excursion == 0:
            pass

        if not possible_amps:
            return 0.1 # Fallback
            
        return min(possible_amps)

    def _show_insert_sine_dialog(self, seg_idx):
        self._context_menu_segment_index = seg_idx
        dialog = InsertSineDialog(self)
        if dialog.exec():
            params = dialog.get_parameters()
            self.commitPoint.emit()
            seg_idx = self._context_menu_segment_index
            if seg_idx is not None:
                # 1. Get existing points
                p1_d = self._norm_to_data(self.points_norm[seg_idx])

                # 2. Calculate the correct end Y-value based on the start point
                num_cycles = params['num_cycles']
                scheme = params['scheme']

                # Calculate maximum safe amplitude to prevent exceeding bounds
                max_safe_amp = self._calculate_max_safe_amplitude(scheme, num_cycles, p1_d.y())
                
                # Heuristic default amplitude
                amplitude = min(abs(self._max_strain), abs(self._min_strain))
                if amplitude == 0: amplitude = max(abs(self._max_strain), abs(self._min_strain))
                if amplitude == 0: amplitude = 0.1
                
                # Clamp amplitude
                amplitude = min(amplitude, max_safe_amp)

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
            self.commitPoint.emit()
            self.segments[seg_idx] = {
                'type': 'sine',
                'num_cycles': new_params['num_cycles'],
                'scheme': new_params['scheme']
            }

            # Recalculate the end-point y-value using the current stored amplitude if available
            p1_d = self._norm_to_data(self.points_norm[seg_idx])
            p2_d = self._norm_to_data(self.points_norm[seg_idx + 1])
            
            # --- Fixed Slope Logic ---
            if self.segments[seg_idx].get('fixed_slope', False):
                 m_target = self.segments[seg_idx].get('fixed_slope_value', 0)
                 dx = p2_d.x() - p1_d.x()
                 if abs(dx) > 1e-9:
                     k = new_params['num_cycles'] * 2 * math.pi / dx
                     
                     phi_start = 0
                     if "Alternating" in new_params['scheme']:
                        phi_start = math.pi if "compressive" in new_params['scheme'] else 0
                     elif "Pulsating" in new_params['scheme']:
                        phi_start = -math.pi/2 if "tensile" in new_params['scheme'] else math.pi/2
                     
                     n = 0
                     first_zero_x_offset = -1
                     while True:
                        x_offset = (n * math.pi - phi_start) / k if k != 0 else -1
                        if x_offset >= -1e-9 and x_offset <= dx + 1e-9:
                            first_zero_x_offset = x_offset
                            break
                        n += 1
                        if n > 1000: break
                     
                     if first_zero_x_offset != -1:
                         phase = k * first_zero_x_offset + phi_start
                         cos_val = math.cos(phase)
                         if abs(cos_val) > 1e-9:
                             new_amp = m_target / (k * cos_val)
                             self.segments[seg_idx]['amplitude'] = new_amp

            # Use the stored amplitude if available, otherwise calculate from endpoints
            amplitude_to_use, y_center, phi_start = self._get_sine_parameters_with_stored_amp(p1_d, p2_d, self.segments[seg_idx], seg_idx)
            
            # --- START FIX: Ensure Amplitude Safety ---
            # If the properties changed, the existing amplitude might now be unsafe.
            # We recalculate the max safe amplitude for the NEW settings.
            if amplitude_to_use is not None:
                max_safe = self._calculate_max_safe_amplitude(new_params['scheme'], new_params['num_cycles'], p1_d.y())
                # Clamp the amplitude
                amplitude_to_use = min(abs(amplitude_to_use), max_safe)
                
                # Update the stored amplitude in the segment
                self.segments[seg_idx]['amplitude'] = amplitude_to_use
                
                # Update phi_start for new scheme (needed for y2 calculation)
                if "tensile" in new_params['scheme']: phi_start = -math.pi/2 if "Pulsating" in new_params['scheme'] else (-math.pi/2 if "tensile start" in new_params['scheme'] else math.pi/2)
                elif "compressive" in new_params['scheme']: phi_start = math.pi/2 if "Pulsating" in new_params['scheme'] else (math.pi/2 if "compressive start" in new_params['scheme'] else -math.pi/2)
                # Actually, easier to let _get_sine_parameters logic handle phi_start or derive it
                # But here we are constructing y2.
                # Let's just follow the logic in _get_sine_parameters roughly:
                # Pulsating T: phi=-pi/2. Pulsating C: phi=pi/2.
                # Alt T: phi=-pi/2 ?? No, Alt starts at 0.
                if "Alternating" in new_params['scheme']:
                    phi_start = 0
                    if "compressive start" in new_params['scheme']:
                        phi_start = math.pi # Standard Alternating logic often starts at 0 or pi
                        # My _get_sine_parameters says: phi_start = pi if compressive, 0 if tensile.
                elif "Pulsating" in new_params['scheme']:
                     if "tensile" in new_params['scheme']: phi_start = -math.pi/2
                     elif "compressive" in new_params['scheme']: phi_start = math.pi/2
                
                num_cycles = new_params['num_cycles']
                end_angle = num_cycles * 2 * math.pi + phi_start
                
                if "Pulsating" in new_params['scheme']:
                     # y2 = y1 + Amp * (sin(end) - sin(start))
                     new_y2 = p1_d.y() + amplitude_to_use * (math.sin(end_angle) - math.sin(phi_start))
                else: 
                     # Alternating: y_center = y1. y2 = y1 + Amp * sin(end)
                     new_y2 = p1_d.y() + amplitude_to_use * math.sin(end_angle)

                # Clamp y2 to bounds just in case
                new_y2 = max(self._min_strain, min(self._max_strain, new_y2))
                
                p2_d.setY(new_y2)
                self.points_norm[seg_idx + 1] = self._data_to_norm(p2_d)

            # If it's an even quarter-period in alternating mode or INTEGER Pulsating, ensure both handles have the same y-value (horizontal line)
            if ((num_cycles * 4) % 2 == 0 and "Alternating" in new_params['scheme']) or \
               (abs(num_cycles - round(num_cycles)) < 1e-9 and "Pulsating" in new_params['scheme']):
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
            if not ok: return
            p_data.setY(new_val)
            # Carry locked neighbours along instead of silently breaking their slope.
            self.points_norm[index] = self._data_to_norm(p_data)
            self._apply_fixed_slope_chain(index, new_val)
            p_data = self._norm_to_data(self.points_norm[index])
        elif type == "x_val" and 0 < index < len(self.points_norm) - 1:
            dialog = TimeEditDialog(p_data.x(), self._timestep, self._max_steps, self);
            if not dialog.exec(): return
            p_data.setX(float(dialog.get_step()))
            self.commitPoint.emit()
            # A locked segment keeps its slope, so its new length moves the far endpoint.
            self.points_norm[index] = self._data_to_norm(p_data)
            self._apply_fixed_slope_chain(index, p_data.y())
            p_data = self._norm_to_data(self.points_norm[index])
        elif type == "slope":
            dialog = SlopeEditDialog(*self.get_data_points()[index:index+2], self._timestep, self._time_unit, self)
            if dialog.exec():
                self._apply_slope_from_dialog(index, dialog.get_slope())
                self.commitPoint.emit()
                self._sort_points(); self.update(); self.dataChanged.emit()
            return
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
                    self.commitPoint.emit()
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

        # The wave is drawn from the stored amplitude, so it has to be re-derived from
        # the handles that just moved - otherwise the curve detaches from them.
        self._resync_adjacent_sines(index)

        self._sort_points(); self.update(); self.dataChanged.emit()
    def _show_set_coords_dialog(self, index):
        p_data = self._norm_to_data(self.points_norm[index])
        dialog = CoordinateDialog(index, p_data.x(), p_data.y(), self._max_steps, self._min_strain, self._max_strain, self)
        if dialog.exec():
            step, strain = dialog.get_coordinates()
            self.commitPoint.emit()
            # For the first point, always force step to 0
            if index == 0:
                step = 0
            new_p_data = QPointF(float(step), strain)
            if index == len(self.points_norm) - 1:
                new_p_data.setX(float(self._max_steps))
            self.points_norm[index] = self._data_to_norm(new_p_data)

            # Both coordinates may have changed, so locked neighbours have to follow
            # (their slope is kept over the new segment length).
            self._apply_fixed_slope_chain(index, new_p_data.y())
            new_p_data = self._norm_to_data(self.points_norm[index])

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

            # Keep the adjacent waves attached to the handle that just moved.
            self._resync_adjacent_sines(index)

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
            
            # Emit signal for cache update
            self.handleDeleted.emit(index - 1)

            if index -1 < len(self.segments):
                self.segments[index-1] = {'type': 'line'} # replace the first segment

            self.update()
            self.dataChanged.emit()
            self.commitPoint.emit()

    def _resolve_dragged_handle_x(self, i, raw_x):
        """Final X (data coordinates) for the handle currently being dragged.

        The first and the last handle are anchored to the start/end of the profile and
        may only be moved vertically; every other handle is kept between its neighbours.
        The result is snapped to whole time steps so that slope/Y calculations agree
        with the rendered X.
        """
        if i <= 0:
            return 0.0
        if i >= len(self.points_norm) - 1:
            return float(self._max_steps)
        if i in self._locked_x_ticks:
            return round(self._norm_to_data(self.points_norm[i]).x())

        prev_x = self._norm_to_data(self.points_norm[i - 1]).x()
        next_x = self._norm_to_data(self.points_norm[i + 1]).x()
        new_x = max(prev_x + self._timestep, raw_x)
        new_x = min(next_x - self._timestep, new_x)
        return round(new_x)

    def _fixed_slope_dy(self, seg_idx, dx):
        """Height change over a segment of length dx that keeps its locked slope.

        Only segments carrying an explicit 'fixed_slope' impose a slope; implicitly
        rigid segments (e.g. full-cycle sines) return 0, i.e. their endpoints stay at
        the same height and their amplitude must not be touched.
        """
        seg = self.segments[seg_idx]

        if not seg.get('fixed_slope', False):
            return 0

        m = seg.get('fixed_slope_value', 0)

        if seg['type'] == 'line':
            return m * dx

        elif seg['type'] == 'sine':
            # Sine Slope Logic - only for explicitly fixed slope
            phi_start = 0
            if "Alternating" in seg['scheme']:
                phi_start = math.pi if "compressive" in seg['scheme'] else 0
            elif "Pulsating" in seg['scheme']:
                phi_start = -math.pi/2 if "tensile" in seg['scheme'] else math.pi/2

            k = seg['num_cycles'] * 2 * math.pi / dx if dx != 0 else 0

            n = 0
            first_zero_x_offset = -1
            while True:
                x_offset = (n * math.pi - phi_start) / k if k != 0 else -1
                if x_offset >= -1e-9 and x_offset <= dx + 1e-9:
                    first_zero_x_offset = x_offset
                    break
                n += 1
                if n > 1000: break

            if first_zero_x_offset != -1 and k != 0:
                phase_at_zero = k * first_zero_x_offset + phi_start
                cos_val = math.cos(phase_at_zero)
                if abs(cos_val) > 1e-9:
                    A = m / (k * cos_val)
                    # Update amplitude to maintain fixed slope
                    seg['amplitude'] = A

                    end_angle = seg['num_cycles'] * 2 * math.pi + phi_start
                    ds = math.sin(end_angle) - math.sin(phi_start)
                    return A * ds
        return 0

    def _resync_sine_amplitude(self, seg_idx):
        """Re-derive a sine segment's stored amplitude from its two handles.

        The wave is drawn from the *stored* amplitude, so whenever a handle moves the
        stored value has to follow - otherwise the curve no longer starts and ends on
        its handles. Dragging always did this; direct (dialog) edits did not.
        """
        if seg_idx < 0 or seg_idx >= len(self.segments): return
        # set_state() rescales the axes before it swaps in the new segments, so the two
        # lists can briefly disagree in length.
        if seg_idx + 1 >= len(self.points_norm): return
        seg = self.segments[seg_idx]
        if seg.get('type') != 'sine': return

        is_even_alt = abs((seg['num_cycles'] * 4) % 2) < 1e-9 and "Alternating" in seg['scheme']
        is_full_puls = abs((seg['num_cycles'] * 4) % 4) < 1e-9 and "Pulsating" in seg['scheme']

        p1 = self._norm_to_data(self.points_norm[seg_idx])
        p2 = self._norm_to_data(self.points_norm[seg_idx+1])

        if is_even_alt or is_full_puls:
            # Both handles sit at the same height for these schemes, so they carry no
            # amplitude information. Keep the user's amplitude, but make sure it still
            # fits in the frame now that the baseline may have moved.
            stored = seg.get('amplitude')
            if stored is not None:
                try:
                    max_safe = self._calculate_max_safe_amplitude(seg['scheme'], seg['num_cycles'], p1.y())
                    if abs(stored) > max_safe + 1e-12:
                        seg['amplitude'] = math.copysign(max_safe, stored)
                except Exception:
                    pass
            return

        # 1. Calculate implied amplitude (signed)
        new_amp, _, _ = self._get_sine_parameters(p1, p2, seg)

        if new_amp is not None:
            # 2. Check for Mode Switching (Mirroring)
            if new_amp < 0:
                current_scheme = seg['scheme']
                new_scheme = current_scheme

                if "Alternating" in current_scheme:
                    if "tensile start" in current_scheme:
                        new_scheme = current_scheme.replace("tensile start", "compressive start")
                    elif "compressive start" in current_scheme:
                        new_scheme = current_scheme.replace("compressive start", "tensile start")
                elif "Pulsating" in current_scheme:
                    if "tensile" in current_scheme:
                        new_scheme = current_scheme.replace("tensile", "compressive")
                    elif "compressive" in current_scheme:
                        new_scheme = current_scheme.replace("compressive", "tensile")

                if new_scheme != current_scheme:
                    seg['scheme'] = new_scheme
                    # Recalculate with new scheme to get positive amplitude
                    new_amp, _, _ = self._get_sine_parameters(p1, p2, seg)

            # 3. Clamp to safe limits
            try:
                 # Ensure stored amplitude is valid for bounds
                max_safe = self._calculate_max_safe_amplitude(seg['scheme'], seg['num_cycles'], p1.y())
                seg['amplitude'] = min(abs(new_amp), max_safe)
            except:
                seg['amplitude'] = abs(new_amp)

    def _resync_adjacent_sines(self, handle_idx):
        """Keep the sine segments on both sides of a moved handle attached to it."""
        if handle_idx > 0: self._resync_sine_amplitude(handle_idx - 1)
        if handle_idx < len(self.segments): self._resync_sine_amplitude(handle_idx)

    def _fixed_slope_offsets(self, index):
        """Handles tied to `index` by explicit 'Fix Slope/Rate' locks.

        Returns {handle_idx: dy relative to `index`}: moving `index` by some amount
        has to move every handle in that chain by the same amount plus this offset.
        """
        offsets = {index: 0.0}
        xs = [self._norm_to_data(p).x() for p in self.points_norm]

        curr = index
        while curr > 0 and self.segments[curr - 1].get('fixed_slope', False):
            dy = self._fixed_slope_dy(curr - 1, xs[curr] - xs[curr - 1])
            offsets[curr - 1] = offsets[curr] - dy
            curr -= 1

        curr = index
        while curr < len(self.points_norm) - 1 and self.segments[curr].get('fixed_slope', False):
            dy = self._fixed_slope_dy(curr, xs[curr + 1] - xs[curr])
            offsets[curr + 1] = offsets[curr] + dy
            curr += 1

        return offsets

    def _apply_fixed_slope_chain(self, index, y_value):
        """Set handle `index` to y_value, carrying every fixed-slope neighbour with it.

        The requested value is pulled back just far enough to keep the whole locked
        chain inside [min_strain, max_strain], so that running into the top/bottom edge
        never silently breaks a lock. Returns the value actually applied.
        """
        offsets = self._fixed_slope_offsets(index)

        lo, hi = self._min_strain, self._max_strain
        for off in offsets.values():
            lo = max(lo, self._min_strain - off)
            hi = min(hi, self._max_strain - off)

        if lo <= hi:
            y_value = max(lo, min(hi, y_value))
        else:
            # The chain cannot fit in the frame at all; keep at least this handle valid.
            y_value = max(self._min_strain, min(self._max_strain, y_value))

        for idx, off in offsets.items():
            p = self._norm_to_data(self.points_norm[idx])
            p.setY(y_value + off)
            self.points_norm[idx] = self._data_to_norm(p)

        for idx in offsets:
            self._resync_adjacent_sines(idx)

        return y_value

    def _apply_slope_from_dialog(self, seg_idx, slope):
        """Apply a slope/rate typed into the Slope dialog to segment `seg_idx`.

        The dialog is authoritative: it overrules this segment's own lock (the stored
        lock value is updated to the entered one) as well as the slope or position of
        the neighbour it pushes, and the neighbouring sine follows the handle it shares.
        """
        p1_data = self._norm_to_data(self.points_norm[seg_idx])
        p2_data = self._norm_to_data(self.points_norm[seg_idx + 1])
        dx = p2_data.x() - p1_data.x()
        seg = self.segments[seg_idx]

        if seg.get('type') == 'sine':
            # For a sine the label shows the mid-point slope, which is set through the
            # amplitude (A = m / (k*cos(phase))) - the same relation used when a line
            # with a locked slope is converted into a sine.
            if abs(dx) < 1e-9: return
            seg['amplitude'] = self._amplitude_for_midpoint_slope(seg, dx, slope)
            new_y2 = p1_data.y() + self._sine_end_offset(seg)
        else:
            new_y2 = p1_data.y() + slope * dx

        # The entered slope wins over this segment's own stored lock value.
        if seg.get('fixed_slope', False):
            seg['fixed_slope_value'] = slope

        self.points_norm[seg_idx + 1] = self._data_to_norm(
            QPointF(p2_data.x(), max(self._min_strain, min(self._max_strain, new_y2))))

        # Drag the far side of the graph along so a locked neighbour keeps its slope,
        # and re-fit any neighbouring sine to the handle that just moved.
        self._apply_fixed_slope_chain(seg_idx + 1,
                                      self._norm_to_data(self.points_norm[seg_idx + 1]).y())
        self._enforce_sine_endpoint_link(seg_idx + 1)
        self._resync_adjacent_sines(seg_idx + 1)

    def _sine_phi_start(self, seg):
        """Starting phase of a sine segment, as used by _get_sine_parameters."""
        scheme = seg['scheme']
        if "Alternating" in scheme:
            return math.pi if "compressive" in scheme else 0
        if "Pulsating" in scheme:
            return -math.pi/2 if "tensile" in scheme else math.pi/2
        return 0

    def _amplitude_for_midpoint_slope(self, seg, dx, slope):
        """Amplitude that gives a sine segment the requested mid-point slope."""
        phi_start = self._sine_phi_start(seg)
        k = seg['num_cycles'] * 2 * math.pi / dx if dx != 0 else 0

        n = 0
        first_zero_x_offset = -1
        while True:
            x_offset = (n * math.pi - phi_start) / k if k != 0 else -1
            if x_offset >= -1e-9 and x_offset <= dx + 1e-9:
                first_zero_x_offset = x_offset
                break
            n += 1
            if n > 1000: break

        if first_zero_x_offset != -1 and k != 0:
            cos_val = math.cos(k * first_zero_x_offset + phi_start)
            if abs(cos_val) > 1e-9:
                return slope / (k * cos_val)
        return seg.get('amplitude', 0)

    def _sine_end_offset(self, seg):
        """Height of a sine segment's end point relative to its start point."""
        phi_start = self._sine_phi_start(seg)
        end_angle = seg['num_cycles'] * 2 * math.pi + phi_start
        amp = seg.get('amplitude', 0)
        if "Pulsating" in seg['scheme']:
            return amp * (math.sin(end_angle) - math.sin(phi_start))
        return amp * math.sin(end_angle)

    def _enforce_sine_endpoint_link(self, handle_idx):
        """Keep both handles of a level sine segment at the same height.

        Even-multiple Alternating and whole-period Pulsating waves return to their
        baseline, so their two handles must stay level; `handle_idx` is the one that
        just moved and therefore wins.
        """
        y = self._norm_to_data(self.points_norm[handle_idx]).y()

        for seg_idx, other in ((handle_idx - 1, handle_idx - 1), (handle_idx, handle_idx + 1)):
            if seg_idx < 0 or seg_idx >= len(self.segments): continue
            seg = self.segments[seg_idx]
            if seg.get('type') != 'sine': continue
            is_even_alt = (seg['num_cycles'] * 4) % 2 == 0 and "Alternating" in seg['scheme']
            is_full_puls = (seg['num_cycles'] * 4) % 4 == 0 and "Pulsating" in seg['scheme']
            if not (is_even_alt or is_full_puls): continue
            p = self._norm_to_data(self.points_norm[other])
            p.setY(y)
            self.points_norm[other] = self._data_to_norm(p)

    def _is_slope_locked(self, seg_idx):
        """True if the user locked this segment's slope/rate ('Fix Slope/Rate')."""
        if seg_idx < 0 or seg_idx >= len(self.segments): return False
        if self.segments[seg_idx].get('fixed_slope', False): return True
        return seg_idx in self._fixed_segments   # configs from before the flag existed

    def _locked_slope_value(self, seg_idx):
        """The slope a locked segment has to keep."""
        seg = self.segments[seg_idx]
        if seg.get('fixed_slope', False):
            return seg.get('fixed_slope_value', 0)
        return self._calculate_segment_slope(seg_idx)

    def _drag_group_has_slope_lock(self, rigid_offsets):
        """True if the handles moving together are tied by an explicit slope lock.

        Only user locks count: a whole-cycle sine also moves its endpoints together, but
        that link is implicit and must keep behaving as before.
        """
        return any(idx + 1 in rigid_offsets and self._is_slope_locked(idx)
                   for idx in rigid_offsets)

    def _segment_within_frame(self, seg_idx, p1_norm, p2_norm):
        """True if a segment placed on these two handles stays inside the frame."""
        if not (-1e-9 <= p1_norm.y() <= 1.0 + 1e-9 and -1e-9 <= p2_norm.y() <= 1.0 + 1e-9):
            return False

        seg = self.segments[seg_idx]
        if seg.get('type') != 'sine':
            return True

        p1 = self._norm_to_data(p1_norm)
        amp, _, _ = self._get_sine_parameters_with_stored_amp(p1, self._norm_to_data(p2_norm),
                                                             seg, seg_idx)
        if amp is None:
            return True
        min_ex, max_ex = self._get_unit_wave_excursions(seg['scheme'], seg['num_cycles'])
        return (p1.y() + abs(amp) * min_ex >= self._min_strain - 1e-9 and
                p1.y() + abs(amp) * max_ex <= self._max_strain + 1e-9)

    def _is_segment_rigid_vertical(self, seg_idx):
        """
        Determines if a segment should be treated as a rigid vertical linkage
        (dragging one endpoint moves the other by the same amount, or fixed relation).
        """
        if seg_idx < 0 or seg_idx >= len(self.segments): return False
        seg = self.segments[seg_idx]
        
        # Explicit User Lock
        if seg.get('fixed_slope', False): return True
        
        # Implicit Algorithmic Lock
        if seg['type'] == 'sine':
             is_even_alt = (seg['num_cycles'] * 4) % 2 == 0 and "Alternating" in seg['scheme']
             is_p_locked = abs(seg['num_cycles'] - round(seg['num_cycles'])) < 1e-9 and "Pulsating" in seg['scheme']
             return (is_even_alt or is_p_locked)
        return False

    def _get_safe_y_range_for_moving_handles(self, rigid_offsets):
        """
        Calculates the safe [min_y, max_y] range for the dragged handle (at offset 0),
        given a dict of {handle_idx: y_offset} representing the rigid group.
        
        rigid_offsets: {idx: offset_from_dragged_handle}
        The handle at 'idx' will be at y_dragged + offset.
        """
        global_min = self._min_strain
        global_max = self._max_strain
        
        limit_min = global_min
        limit_max = global_max
        
        moving_indices = rigid_offsets.keys()
        
        # Identify all segments connected to the moving handles
        segments_to_check = set()
        for idx in moving_indices:
            if idx > 0: segments_to_check.add(idx - 1)
            if idx < len(self.points_norm) - 1: segments_to_check.add(idx)
            
        for s_idx in segments_to_check:
            if self.segments[s_idx]['type'] != 'sine':
                # Check Line constraints (endpoints)
                # If s_idx in moving, check P1
                if s_idx in rigid_offsets:
                    off = rigid_offsets[s_idx]
                    # y_drag + off <= GlobalMax -> y_drag <= GlobalMax - off
                    limit_max = min(limit_max, global_max - off)
                    limit_min = max(limit_min, global_min - off)
                # If s_idx+1 in moving, check P2
                if (s_idx+1) in rigid_offsets:
                    off = rigid_offsets[s_idx+1]
                    limit_max = min(limit_max, global_max - off)
                    limit_min = max(limit_min, global_min - off)
                continue
                
            seg = self.segments[s_idx]
            
            p1_moving = s_idx in rigid_offsets
            p2_moving = (s_idx + 1) in rigid_offsets
            
            if not p1_moving and not p2_moving:
                continue 
                
            # --- Case 1: Fixed Amplitude (Both Endpoints Moving Rigidly) ---
            if p1_moving and p2_moving:
                stored_amp = seg.get('amplitude', 0)
                min_unit, max_unit = self._get_unit_wave_excursions(seg['scheme'], seg['num_cycles'])
                
                # _get_unit_wave_excursions returns min/max excursions for unit amplitude
                # relative to P1's Y position. For actual amplitude, scale by stored_amp.
                # Peak_Y = Y_P1 + stored_amp * max_unit
                # Trough_Y = Y_P1 + stored_amp * min_unit
                
                offset_p1 = rigid_offsets[s_idx]
                
                # Y_P1 = Y_Drag + offset_p1
                # Constraint: Y_P1 + stored_amp * max_unit <= global_max
                #            Y_Drag + offset_p1 + stored_amp * max_unit <= global_max
                #            Y_Drag <= global_max - (offset_p1 + stored_amp * max_unit)
                
                limit_max = min(limit_max, global_max - (offset_p1 + stored_amp * max_unit))
                limit_min = max(limit_min, global_min - (offset_p1 + stored_amp * min_unit))

            # --- Case 2: Variable Amplitude (One Endpoint Moving) ---
            else:
                # Y_Moving = Y_Drag + Offset_Moving
                # Y_Fixed is constant.
                offset_moving = rigid_offsets[s_idx] if p1_moving else rigid_offsets[s_idx+1]
                
                # ... Linear Solver Logic ...
                # Y_Peak = A * Y_Moving + B
                #        = A * (Y_Drag + Off) + B
                #        = A * Y_Drag + (A*Off + B)
                
                # Copy-paste previous solver logic but apply offset
                phi_start = 0
                if "Alternating" in seg['scheme']:
                    if "compressive" in seg['scheme']: phi_start = math.pi
                    else: phi_start = 0
                elif "Pulsating" in seg['scheme']:
                    if "tensile" in seg['scheme']: phi_start = -math.pi / 2
                    elif "compressive" in seg['scheme']: phi_start = math.pi / 2
                
                phi_end = phi_start + seg['num_cycles'] * 2 * math.pi
                S_start = math.sin(phi_start)
                S_end = math.sin(phi_end)
                D = S_end - S_start
                
                is_alternating = "Alternating" in seg['scheme']
                if not is_alternating and abs(D) < 1e-9: continue 
                if is_alternating and abs(S_end) < 1e-9: continue
                denom = S_end if is_alternating else D
                
                if p1_moving: y_fixed = self._norm_to_data(self.points_norm[s_idx+1]).y()
                else: y_fixed = self._norm_to_data(self.points_norm[s_idx]).y()
                
                critical_S = [S_start, S_end]
                k_start = math.ceil((phi_start - math.pi/2) / math.pi)
                k_end = math.floor((phi_end - math.pi/2) / math.pi)
                for k in range(k_start, k_end + 1):
                    theta = math.pi/2 + k * math.pi
                    if phi_start - 1e-9 <= theta <= phi_end + 1e-9:
                        critical_S.append(math.sin(theta))
                
                for S in critical_S:
                    coeff = 0
                    const_poly = 0 # 'B' term from Y_Peak = A*Y_Mov + B
                    
                    if is_alternating:
                        factor = S / denom
                        if p1_moving: # y1 moving
                             coeff = 1 - factor
                             const_poly = y_fixed * factor
                        else: # y2 moving
                             coeff = factor
                             const_poly = y_fixed * (1 - factor)
                    else: # Pulsating
                        factor = (S - S_start) / denom
                        if p1_moving: 
                             coeff = 1 - factor
                             const_poly = y_fixed * factor
                        else: 
                             coeff = factor
                             const_poly = y_fixed * (1 - factor)
                             
                    # Apply Offset to get final Coeff/Const for Y_Drag
                    # Y_Peak = Coeff * (Y_Drag + Offset) + Const_Poly
                    #        = Coeff * Y_Drag + (Coeff * Offset + Const_Poly)
                    
                    real_const = coeff * offset_moving + const_poly
                    
                    rhs_max = global_max - real_const
                    rhs_min = global_min - real_const
                    
                    if coeff > 1e-9:
                        limit_max = min(limit_max, rhs_max / coeff)
                        limit_min = max(limit_min, rhs_min / coeff)
                    elif coeff < -1e-9:
                        limit_min = max(limit_min, rhs_max / coeff)
                        limit_max = min(limit_max, rhs_min / coeff)
                    elif real_const > global_max + 1e-5:
                        pass # Impossible
                    elif real_const < global_min - 1e-5:
                        pass

        if limit_min > limit_max:
            limit_min = global_min
            limit_max = global_max
            
        return limit_min, limit_max

class StudyWidget(QWidget):
    dataChanged = pyqtSignal()
    maxStepsChanged = pyqtSignal()
    def __init__(self, initial_state=None, parent=None):
        super().__init__(parent)
        self.is_enabled = True
        self.mode = "Deformation"
        layout = QVBoxLayout(self)
        layout.setContentsMargins(5,5,5,5)
        layout.setSpacing(2)
        controls_layout = QHBoxLayout()
        self.max_steps_spinbox = QSpinBox(); self.max_steps_spinbox.setPrefix("Max Steps: "); self.max_steps_spinbox.setRange(1, 2147483647); self.max_steps_spinbox.setValue(100); self.max_steps_spinbox.setKeyboardTracking(False)
        self.min_strain_spinbox = TrimDoubleSpinBox(); self.min_strain_spinbox.setPrefix("Min Strain: "); self.min_strain_spinbox.setRange(-0.999999, 1e9); self.min_strain_spinbox.setValue(0.0); self.min_strain_spinbox.setKeyboardTracking(False)
        self.max_strain_spinbox = TrimDoubleSpinBox(); self.max_strain_spinbox.setPrefix("Max Strain: "); self.max_strain_spinbox.setRange(-1e9, 1e9); self.max_strain_spinbox.setValue(1.0); self.max_strain_spinbox.setKeyboardTracking(False)

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
        self.deform_axis_combo.addItems(["x", "y", "z", "vol", "xy", "xz", "yz"])
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
        # Permanently hide Deform Scenario widgets as per new requirement
        self.deform_scenario_label.setVisible(False)
        self.deform_scenario_combo.setVisible(False)

        self.remap_label = QLabel("<b>Remap:</b>")
        self.remap_combo = QComboBox()
        self.remap_combo.addItems(["x", "v", "none"])
        self.remap_combo.setToolTip("Remap parameter for fix deform")
        self.remap_combo.setStyleSheet("""
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
        # Add hidden scenario widgets to keep layout reference if needed, or just don't add them.
        # Adding them but hidden ensures no layout issues if code expects them.
        controls_layout.addWidget(self.deform_scenario_label)
        controls_layout.addWidget(self.deform_scenario_combo)
        
        # Add new Remap controls
        remap_url = QUrl("https://docs.lammps.org/fix_deform.html")
        remap_tooltip = "Click to open LAMMPS documentation for fix deform (remap)"
        self.remap_info_label = create_info_icon_label([remap_url], remap_tooltip, "blue")
        
        controls_layout.addWidget(self.remap_label)
        controls_layout.addWidget(self.remap_combo)
        controls_layout.addSpacing(5) # Added space between remap combo and info icon
        controls_layout.addWidget(self.remap_info_label)

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
        self.graph_widget.handleInserted.connect(self.update_cache_insert)
        self.graph_widget.handleDeleted.connect(self.update_cache_delete)

        layout.addLayout(controls_layout)
        layout.addLayout(deform_direc_thermo_layout)
        layout.addWidget(self.graph_widget)

        # Ensemble Settings
        self.lateral_widgets = {}
        self._lateral_settings_cache = {}
        self._tensile_npt_aniso_cache = "aniso"
        self._segment_overrides_cache = {}
        self._last_deform_axis = "x" # Default for tracking
        
        self.ensemble_container = QWidget()
        self.ensemble_layout = QHBoxLayout(self.ensemble_container)
        self.ensemble_layout.setContentsMargins(0, 0, 0, 0)
        self.ensemble_layout.setSpacing(5)
        
        # Initialize widgets
        self.ensemble_combo = QComboBox()
        self.ensemble_combo.addItems(["NVT", "NPT"])
        self.ensemble_combo.setToolTip("Select the thermodynamic ensemble for the simulation")
        self.ensemble_combo.setFixedWidth(70)

        ensemble_urls = [QUrl("https://docs.lammps.org/fix_nvt.html"), QUrl("https://docs.lammps.org/fix_nh.html")]
        ensemble_tooltip = "Click to open LAMMPS documentation for NVT and NPT ensembles"
        self.ensemble_info_label = create_info_icon_label(ensemble_urls, ensemble_tooltip, "blue")

        self.temp_spinbox = QDoubleSpinBox()
        self.temp_spinbox.setPrefix("Temperature: ")
        self.temp_spinbox.setRange(0, 10000)
        self.temp_spinbox.setValue(300.0)
        self.temp_spinbox.setSingleStep(10.0)
        self.temp_spinbox.setToolTip("Temperature for the simulation")
        self.temp_spinbox.setFixedWidth(150)

        self.pressure_spinbox = QDoubleSpinBox()
        self.pressure_spinbox.setPrefix("P: ")
        self.pressure_spinbox.setRange(-100000, 100000)
        self.pressure_spinbox.setValue(1.0)
        self.pressure_spinbox.setDecimals(4)
        self.pressure_spinbox.setToolTip("Target pressure for NPT ensemble")
        self.pressure_spinbox.setFixedWidth(100)

        self.npt_aniso_label = QLabel("NPT Aniso:")
        self.npt_aniso_combo = QComboBox()
        self.npt_aniso_combo.addItems(["iso", "aniso", "tri"])
        self.npt_aniso_combo.setToolTip("Select NPT anisotropic option for the simulation")
        self.npt_aniso_combo.setFixedWidth(70)

        self.sync_ensemble_checkbox = QCheckBox("Sync ensemble")
        self.sync_ensemble_checkbox.setToolTip("Synchronize ensemble settings across all studies")
        
        sync_url = QUrl("https://docs.lammps.org/fix_nh.html")
        sync_tooltip = "Click to open LAMMPS documentation for ensembles (fix nvt/npt)"
        self.sync_ensemble_info_label = create_info_icon_label([sync_url], sync_tooltip, "blue")
        
        self._rebuild_ensemble_layout()
        
        layout.addWidget(self.ensemble_container)

        # Free Text Custom Commands Controls
        # Create a horizontal layout for the text field and sync button
        custom_commands_layout = QHBoxLayout()
        custom_commands_layout.setContentsMargins(0, 0, 0, 0)  # No margins for a compact look
        custom_commands_layout.setSpacing(5)  # Small spacing between elements

        # Create the text edit field with appropriate size policy for proper expansion
        self.custom_commands_text = QTextEdit()
        self.custom_commands_text.setPlaceholderText("Enter custom study-specific LAMMPS commands (e.g. fix bond/break) ...")

        # Make the font slightly smaller
        font = self.custom_commands_text.font()
        font.setPointSize(max(8, font.pointSize() - 1))  # Reduce font size by 1, minimum 8
        self.custom_commands_text.setFont(font)

        # Set initial size constraints - this is the key for proper behavior
        font_height = self.custom_commands_text.fontMetrics().lineSpacing()
        # 18px covers: line height + document margins (4px*2) + frame borders (1px*2) + breathing room
        total_height = font_height + 12
        self.custom_commands_text.setMinimumHeight(total_height)
        self.custom_commands_text.setMaximumHeight(total_height)

        # Set size policy to expand horizontally but control vertical expansion
        self.custom_commands_text.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)

        # Apply custom stylesheet to make scrollbar more visually appealing without up/down arrows
        self.custom_commands_text.setStyleSheet("""
            QScrollBar:vertical {
                background: #f0f0f0;
                width: 8px;
                margin: 0px 0px 0px 0px;
            }
            QScrollBar::handle:vertical {
                background: #b0b0b0;
                min-height: 20px;
                border-radius: 4px;
            }
            QScrollBar::handle:vertical:hover {
                background: #909090;
            }
            QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical {
                height: 0px;
            }
            QScrollBar::add-page:vertical, QScrollBar::sub-page:vertical {
                background: none;
            }
        """)

        # Add the text field to the layout
        custom_commands_layout.addWidget(self.custom_commands_text)

        # Add sync checkbox
        self.sync_custom_commands_checkbox = QCheckBox("Sync custom commands")
        self.sync_custom_commands_checkbox.setToolTip("Synchronize custom commands across all studies")
        custom_commands_layout.addWidget(self.sync_custom_commands_checkbox)

        layout.addLayout(custom_commands_layout)  # Add the new custom commands layout to the main layout

        # Connect signals for ensemble settings
        self.ensemble_combo.currentTextChanged.connect(self._on_ensemble_setting_changed)
        self.temp_spinbox.valueChanged.connect(self._on_ensemble_setting_changed)
        self.pressure_spinbox.valueChanged.connect(self._on_ensemble_setting_changed)
        self.npt_aniso_combo.currentTextChanged.connect(self._on_ensemble_setting_changed)
        self.sync_ensemble_checkbox.stateChanged.connect(self._on_ensemble_setting_changed)

        # Connect signals for the new custom commands text field
        self.custom_commands_text.textChanged.connect(self._on_custom_commands_changed)
        self.sync_custom_commands_checkbox.stateChanged.connect(self._on_custom_commands_changed)

        # Initial UI state update
        self._update_ensemble_ui_state()

        # Update text field height when content changes
        self.custom_commands_text.textChanged.connect(self._update_custom_commands_height)

        self._last_staircase_params = {'cycles': 5, 'factor': 1.0, 'direction': 'Tension'}
        self._last_cyclic_params = {'cycles': 3, 'relax_factor': 0.0, 'start_with': 'Tension'}
        self._last_sinusoidal_params = {'equilibration_steps': 0, 'num_cycles': 4.0, 'relax_factor': 0.0, 'scheme': 'Alternating (tensile start)'}
        self._last_scheme = "Staircase Loading"

        self._is_mode_switching = False
        self._undo_stacks = {'Deformation': [], 'Temperature': []}
        self._redo_stacks = {'Deformation': [], 'Temperature': []}
        self._mode_states = {}

        if initial_state:
            self.set_state(initial_state)
        else:
            self.graph_widget.reset_graph()

        self._setup_undo_redo()
        self.max_steps_spinbox.editingFinished.connect(self._update_graph_controls)
        self.min_strain_spinbox.editingFinished.connect(self._update_graph_controls)
        self.max_strain_spinbox.editingFinished.connect(self._update_graph_controls)
        self.max_steps_spinbox.valueChanged.connect(self._schedule_undo_save)
        self.min_strain_spinbox.valueChanged.connect(self._schedule_undo_save)
        self.max_strain_spinbox.valueChanged.connect(self._schedule_undo_save)

        self.min_strain_spinbox.lineEdit().editingFinished.connect(self._min_strain_cleared)
        self.max_strain_spinbox.lineEdit().editingFinished.connect(self._max_strain_cleared)

        self.graph_widget.dataChanged.connect(self.dataChanged)
        self.graph_widget.dataChanged.connect(self._update_deform_scenario_visibility)
        self.deform_axis_combo.currentTextChanged.connect(self._update_deform_scenario_visibility)
        self.deform_axis_combo.currentTextChanged.connect(self._rebuild_ensemble_layout)
        self.reset_button.clicked.connect(self.graph_widget.reset_graph)
        self.generate_button.clicked.connect(self._show_preset_dialog)
        self._update_graph_controls()
        self._save_state_for_undo()
        
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
        old_max_steps = getattr(self.graph_widget, "_max_steps", None)
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

        if old_max_steps is not None and old_max_steps != max_steps:
            self.maxStepsChanged.emit()

    def _show_preset_dialog(self):
        max_steps = self.max_steps_spinbox.value()
        dialog = PresetDialog(self._last_scheme, self._last_staircase_params, self._last_cyclic_params, self._last_sinusoidal_params, max_steps, self)
        if dialog.exec():
            scheme, params = dialog.get_parameters()
            self._schedule_undo_save()
            self._schedule_undo_save()
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

    @property
    def _undo_stack(self):
        return self._undo_stacks[self.mode]

    @property
    def _redo_stack(self):
        return self._redo_stacks[self.mode]

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
        self.graph_widget.commitPoint.connect(self._schedule_undo_save)
        
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
            'locked_x': sorted(self.graph_widget._locked_x_ticks),
            'locked_y': sorted(self.graph_widget._locked_y_labels),
            'fixed_slopes': sorted(self.graph_widget._fixed_segments),
            'locked_x': sorted(self.graph_widget._locked_x_ticks),
            'locked_y': sorted(self.graph_widget._locked_y_labels),
            'fixed_slopes': sorted(self.graph_widget._fixed_segments),
        }

    def set_undo_state(self, state):
        self.max_steps_spinbox.blockSignals(True)
        self.min_strain_spinbox.blockSignals(True)
        self.max_strain_spinbox.blockSignals(True)

        self.max_steps_spinbox.setValue(state['max_steps'])
        self.min_strain_spinbox.setValue(state['min_strain'])
        self.max_strain_spinbox.setValue(state['max_strain'])
        self.graph_widget._locked_x_ticks = set(state.get('locked_x', []))
        self.graph_widget._locked_y_labels = set(state.get('locked_y', []))
        self.graph_widget._fixed_segments = set(state.get('fixed_slopes', []))
        self.graph_widget._locked_x_ticks = set(state.get('locked_x', []))
        self.graph_widget._locked_y_labels = set(state.get('locked_y', []))
        self.graph_widget._fixed_segments = set(state.get('fixed_slopes', []))

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
        self.remap_combo.setEnabled(enabled)
        
        for widget in self.lateral_widgets.values():
            widget.setEnabled(enabled)

        self.ensemble_combo.setEnabled(enabled)
        self.temp_spinbox.setEnabled(enabled)
        # Don't set pressure_spinbox enabled state here, let _update_ensemble_ui_state handle it
        # based on both study activation state and ensemble
        self.npt_aniso_combo.setEnabled(enabled)
        self.sync_ensemble_checkbox.setEnabled(enabled)
        self.custom_commands_text.setEnabled(enabled)
        self.sync_custom_commands_checkbox.setEnabled(enabled)

        # These functions will correctly handle the logic for their own children
        # based on the state of the parent checkboxes, which are now correctly enabled/disabled.
        self._update_ensemble_ui_state()

        # The graph widget is a special case; we don't disable it,
        # but its paintEvent will draw an overlay. We just need to trigger a repaint.
        self.graph_widget.update()

        self.dataChanged.emit()

    def _update_deform_scenario_visibility(self):
        """Update the visibility of Deform Scenario (hidden) and Remap controls"""
        # Deform Scenario is now permanently hidden
        self.deform_scenario_label.setVisible(False)
        self.deform_scenario_combo.setVisible(False)
        
        # Remap is visible in Deformation mode, hidden in Temperature mode
        is_deformation = self.mode == 'Deformation'
        self.remap_label.setVisible(is_deformation)
        self.remap_combo.setVisible(is_deformation)
        self.remap_info_label.setVisible(is_deformation)



    def get_state(self):
        ensemble_state = {
            'ensemble': self.ensemble_combo.currentText(),
            'temperature': self.temp_spinbox.value(),
            'pressure': self.pressure_spinbox.value(),
            'npt_aniso': self.npt_aniso_combo.currentText(),
            'sync_ensemble': self.sync_ensemble_checkbox.isChecked(),
            'lateral_contraction': {}
        }
        
        # Capture lateral contraction settings
        for axis, widget in self.lateral_widgets.items():
            ensemble_state['lateral_contraction'][axis] = widget.currentText()

        return {
            'data_points': [[p.x(), p.y()] for p in self.graph_widget.get_data_points()],
            'max_steps': self.max_steps_spinbox.value(),
            'min_strain': self.min_strain_spinbox.value(),
            'max_strain': self.max_strain_spinbox.value(),
            'deform_axis': self.deform_axis_combo.currentText(),
            'deform_scenario': self.deform_scenario_combo.currentText(),
            'remap': self.remap_combo.currentText(),
            'mode': self.mode,
            'segments': copy.deepcopy(self.graph_widget.segments),
            'is_enabled': self.is_enabled,
            'ensemble': ensemble_state,
            'bond_commands': {
                'commands': self.custom_commands_text.toPlainText(),
                'sync_bond_commands': self.sync_custom_commands_checkbox.isChecked()
            },
            'segment_overrides_cache': copy.deepcopy(self._segment_overrides_cache)
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
        self.custom_commands_text.blockSignals(True)
        self.sync_custom_commands_checkbox.blockSignals(True)

        # 1. Set mode and update mode-dependent UI
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

        # Restore segment overrides cache
        self._segment_overrides_cache = copy.deepcopy(state.get('segment_overrides_cache', {}))

        # 3. Set control values directly from state
        max_steps = state.get('max_steps', 100)
        min_strain = state.get('min_strain', 0.0)
        max_strain = state.get('max_strain', 1.0)
        self.max_steps_spinbox.setValue(max_steps)
        self.min_strain_spinbox.setValue(min_strain)
        self.max_strain_spinbox.setValue(max_strain)
        self.deform_axis_combo.setCurrentText(state.get('deform_axis', 'x'))
        self.deform_scenario_combo.setCurrentText(state.get('deform_scenario', 'symmetric'))
        self.remap_combo.setCurrentText(state.get('remap', 'x'))

        # Set last deform axis before rebuilding to ensure cache consistency
        self._last_deform_axis = state.get('deform_axis', 'x')

        # Rebuild the ensemble layout before setting values (crucial for dynamic widgets)
        self._rebuild_ensemble_layout()

        ensemble_state = state.get('ensemble', {})
        self.ensemble_combo.setCurrentText(ensemble_state.get('ensemble', 'NVT'))
        self.temp_spinbox.setValue(ensemble_state.get('temperature', 300.0))
        self.pressure_spinbox.setValue(ensemble_state.get('pressure', 1.0))
        
        npt_val = ensemble_state.get('npt_aniso', 'iso')
        self.npt_aniso_combo.setCurrentText(npt_val)
        # Update cache if loaded state is valid for tensile
        if self.mode == 'Deformation' and self.deform_axis_combo.currentText() not in ["xy", "xz", "yz"]:
             if npt_val in ["aniso", "tri"]:
                 self._tensile_npt_aniso_cache = npt_val

        self.sync_ensemble_checkbox.setChecked(ensemble_state.get('sync_ensemble', False))
        
        # Handle Lateral Contraction Settings (Backward Compatibility)
        lateral_settings = ensemble_state.get('lateral_contraction', {})
        
        if not lateral_settings:
            # Backward compatibility: map old ensemble setting to new lateral settings
            old_ensemble = ensemble_state.get('ensemble', 'NVT')
            default_setting = "free (NPT)" if old_ensemble == "NPT" else "constrained"
            for widget in self.lateral_widgets.values():
                widget.blockSignals(True)
                widget.setCurrentText(default_setting)
                widget.blockSignals(False)
        else:
            # Load saved settings
            for axis, setting in lateral_settings.items():
                if axis in self.lateral_widgets:
                    self.lateral_widgets[axis].blockSignals(True)
                    self.lateral_widgets[axis].setCurrentText(setting)
                    self.lateral_widgets[axis].blockSignals(False)
        
        # Update visibility based on loaded settings
        if self.mode == 'Deformation':
            self._update_lateral_npt_visibility()
        
        # Always update overall ensemble UI state (handles Pressure prefix, etc.)
        self._update_ensemble_ui_state()

        # Handle custom commands loading
        if 'bond_commands' in state:
            # Load new format
            bond_commands_state = state.get('bond_commands', {})
            self.custom_commands_text.setPlainText(bond_commands_state.get('commands', ''))
            self.sync_custom_commands_checkbox.setChecked(bond_commands_state.get('sync_bond_commands', False))
        else:
            # Old format (bond_breakage) or no data: default to empty (ignore old settings)
            self.custom_commands_text.setPlainText('')
            self.sync_custom_commands_checkbox.setChecked(False)

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
        self.custom_commands_text.blockSignals(False)
        self.sync_custom_commands_checkbox.blockSignals(False)

        # 7. Final UI refresh
        self.graph_widget.update()
        self.dataChanged.emit()
        self._update_deform_scenario_visibility()
        self._update_custom_commands_height()  # Update the text field height after loading
        self.set_enabled(state.get('is_enabled', True))


    def _rebuild_ensemble_layout(self):
        # Cache current settings before clearing
        for axis, widget in self.lateral_widgets.items():
            self._lateral_settings_cache[axis] = widget.currentText()

        # Cache segment overrides for the OLD axis
        if hasattr(self, '_last_deform_axis'):
            current_overrides_list = [copy.deepcopy(s.get('lateral_overrides', {})) for s in self.graph_widget.segments]
            self._segment_overrides_cache[self._last_deform_axis] = current_overrides_list
        
        new_axis = self.deform_axis_combo.currentText()
        self._last_deform_axis = new_axis
        
        # Restore segment overrides for the NEW axis if available and topology matches
        cached_overrides = self._segment_overrides_cache.get(new_axis, [])
        if len(cached_overrides) == len(self.graph_widget.segments):
            for i, overrides in enumerate(cached_overrides):
                if overrides:
                    self.graph_widget.segments[i]['lateral_overrides'] = copy.deepcopy(overrides)
                elif 'lateral_overrides' in self.graph_widget.segments[i]:
                    del self.graph_widget.segments[i]['lateral_overrides']
        else:
            # Reset/Clear if no cache or mismatch
            for s in self.graph_widget.segments:
                if 'lateral_overrides' in s:
                    del s['lateral_overrides']
        
        self.graph_widget.update()

        # Clear existing layout items
        while self.ensemble_layout.count():
            item = self.ensemble_layout.takeAt(0)
            widget = item.widget()
            if widget:
                widget.setParent(None)
        
        self.lateral_widgets.clear()

        if self.mode == 'Temperature':
            self.ensemble_layout.addWidget(QLabel("Ensemble:"))
            self.ensemble_layout.addWidget(self.ensemble_combo)
            self.ensemble_layout.addWidget(self.ensemble_info_label)
            self.ensemble_layout.addWidget(self.temp_spinbox)
            self.ensemble_layout.addWidget(self.pressure_spinbox)
            self.ensemble_layout.addWidget(self.npt_aniso_label)
            self.ensemble_layout.addWidget(self.npt_aniso_combo)
            self.ensemble_layout.addStretch(1)
            self.ensemble_layout.addWidget(self.sync_ensemble_checkbox)
            self.ensemble_layout.addWidget(self.sync_ensemble_info_label)
            
            # Ensure correct visibility for Temperature mode
            self._update_ensemble_ui_state()

        else: # Deformation Mode
            deform_axis = self.deform_axis_combo.currentText()
            all_axes = ['x', 'y', 'z']
            
            lateral_axes = []
            if len(deform_axis) == 1: # x, y, z
                lateral_axes = [axis for axis in all_axes if axis != deform_axis]
            elif len(deform_axis) == 2: # xy, xz, yz
                lateral_axes = [axis for axis in all_axes if axis not in deform_axis]
            
            self.ensemble_layout.addWidget(QLabel("Lateral contraction:"))
            
            for axis in lateral_axes:
                self.ensemble_layout.addWidget(QLabel(axis))
                combo = QComboBox()
                combo.addItems(["constrained", "free (NPT)"])
                combo.setFixedWidth(90)
                combo.setEnabled(self.is_enabled) # Ensure new widgets respect enabled state
                
                # Restore from cache if available
                if axis in self._lateral_settings_cache:
                    combo.setCurrentText(self._lateral_settings_cache[axis])

                combo.currentTextChanged.connect(self._on_lateral_contraction_changed)
                self.lateral_widgets[axis] = combo
                self.ensemble_layout.addWidget(combo)
            
            self.ensemble_layout.addWidget(self.pressure_spinbox)
            self.ensemble_layout.addWidget(self.npt_aniso_label)
            self.ensemble_layout.addWidget(self.npt_aniso_combo)
            self.ensemble_layout.addWidget(self.temp_spinbox)
            self.ensemble_layout.addStretch(1)
            self.ensemble_layout.addWidget(self.sync_ensemble_checkbox)
            self.ensemble_layout.addWidget(self.sync_ensemble_info_label)
            
            # Initial visibility check for Deformation mode
            self._update_lateral_npt_visibility()
            self._update_ensemble_ui_state()

    def update_cache_insert(self, index):
        """Update all cached segment overrides by inserting an empty entry at index."""
        for axis in self._segment_overrides_cache:
            overrides_list = self._segment_overrides_cache[axis]
            # Always insert; list.insert handles index >= len by appending
            overrides_list.insert(index, {})
            
            # Reset the previous segment if we inserted inside the graph (split)
            # If we split segment i (now i and i+1), i is reset.
            if 0 < index < len(overrides_list):
                 overrides_list[index-1] = {}

    def update_cache_delete(self, seg_idx):
        """Update all cached segment overrides by removing entry at seg_idx and resetting the new entry at that position."""
        for axis in self._segment_overrides_cache:
            overrides_list = self._segment_overrides_cache[axis]
            if 0 <= seg_idx < len(overrides_list):
                overrides_list.pop(seg_idx)
                # Reset the segment that moved into this position (merged result)
                if seg_idx < len(overrides_list):
                    overrides_list[seg_idx] = {}

    def _on_lateral_contraction_changed(self, text):
        self._update_lateral_npt_visibility()
        self._on_ensemble_setting_changed()

    def _update_lateral_npt_visibility(self):
        if self.mode != 'Deformation':
            return

        has_free_npt = any(w.currentText() == "free (NPT)" for w in self.lateral_widgets.values())
        deform_axis = self.deform_axis_combo.currentText()
        is_shear = deform_axis in ["xy", "xz", "yz"]

        # NPT Aniso dropdown appears if at least one axis is free
        # BUT if it's shear, we hide it (implicitly tri) per requirements
        show_aniso = has_free_npt and not is_shear
        
        self.npt_aniso_label.setVisible(show_aniso)
        self.npt_aniso_combo.setVisible(show_aniso)
        
        # Reset/Update choices based on visibility
        self.npt_aniso_combo.blockSignals(True)
        self.npt_aniso_combo.clear()
        
        if is_shear:
             # Implicitly 'tri' for shear, but widget is hidden. 
             # We add 'tri' so get_state retrieves it correctly if needed.
             self.npt_aniso_combo.addItem("tri")
             self.npt_aniso_combo.setCurrentText("tri")
        else:
            self.npt_aniso_combo.addItems(["aniso", "tri"])
            # Restore from cache for tensile direction
            self.npt_aniso_combo.setCurrentText(self._tensile_npt_aniso_cache)
            
        self.npt_aniso_combo.blockSignals(False)

    def _on_ensemble_setting_changed(self):
        # Update cache if currently tensile and valid
        if self.mode == 'Deformation':
             deform_axis = self.deform_axis_combo.currentText()
             is_shear = deform_axis in ["xy", "xz", "yz"]
             if not is_shear and self.npt_aniso_combo.isVisible():
                 current = self.npt_aniso_combo.currentText()
                 if current in ["aniso", "tri"]:
                     self._tensile_npt_aniso_cache = current

        self._update_ensemble_ui_state()
        stacked_widget = self.parent()
        if stacked_widget is not None:
            tab_widget = stacked_widget.parent()
            if tab_widget is not None:
                deformation_tab = tab_widget.parent()
                # Import locally to avoid circular import issues if any, 
                # though mostly safe in methods.
                # Assuming DeformationTab is available in scope or via import
                if hasattr(deformation_tab, '_sync_ensemble_settings'):
                    sync_state = self.sync_ensemble_checkbox.isChecked()
                    if sync_state:
                        deformation_tab._sync_ensemble_settings(self)
                    else:
                        sender = self.sender()
                        if sender == self.sync_ensemble_checkbox:
                            deformation_tab._sync_ensemble_settings(self, force_unchecked=True)
        self.dataChanged.emit()

    def _update_ensemble_ui_state(self):
        if self.mode == 'Temperature':
            is_npt = self.ensemble_combo.currentText() == "NPT"
            
            self.pressure_spinbox.setPrefix("P: ")
            self.pressure_spinbox.setFixedWidth(100)
            self.pressure_spinbox.setToolTip("Target pressure for NPT ensemble")
            self.pressure_spinbox.setEnabled(self.is_enabled)

            self.npt_aniso_label.setVisible(is_npt)
            self.npt_aniso_combo.setVisible(is_npt)

            if is_npt:
                current_selection = self.npt_aniso_combo.currentText()
                self.npt_aniso_combo.blockSignals(True)
                self.npt_aniso_combo.clear()
                self.npt_aniso_combo.addItems(["iso", "aniso", "tri"])
                if not current_selection:
                    self.npt_aniso_combo.setCurrentText("iso")
                else:
                    self.npt_aniso_combo.setCurrentText(current_selection)
                self.npt_aniso_combo.blockSignals(False)

        else: # Deformation Mode
            # In Deformation mode, the pressure box logic changes
            # It's always visible.
            
            # Determine if we are effectively in NPT (at least one axis free)
            is_npt_effective = any(w.currentText() == "free (NPT)" for w in self.lateral_widgets.values())
            
            if is_npt_effective:
                self.pressure_spinbox.setPrefix("P: ")
                self.pressure_spinbox.setFixedWidth(100)
                self.pressure_spinbox.setToolTip("Target pressure for lateral NPT control")
            else:
                self.pressure_spinbox.setPrefix("P (equil): ")
                self.pressure_spinbox.setFixedWidth(120) # Slightly wider
                self.pressure_spinbox.setToolTip("Pressure from equilibration (used for stress correction)")
            
            self.pressure_spinbox.setEnabled(self.is_enabled)
            
            # NPT Aniso visibility is handled by _update_lateral_npt_visibility. Call it to ensure updates.
            self._update_lateral_npt_visibility()

    # Old method for bond breakage - no longer needed since we replaced with custom text field
    # Keeping this method for backward compatibility during transition
    def _on_bond_breakage_setting_changed(self):
        pass

    def set_mode(self, mode, adjust_values=True):
        if self.mode == mode:
            return

        # 1. Save current state
        self._mode_states[self.mode] = self.get_state()

        # 2. Switch mode
        self.mode = mode
        self.graph_widget.set_mode(mode) # Ensure graph widget mode is updated
        self._is_mode_switching = True  # Flag to prevent control updates during transition

        # 3. Restore state or initialize defaults
        if mode in self._mode_states:
            # Restore saved state
            self.set_state(self._mode_states[mode])
        else:
            # Initialize defaults for new mode
            self.graph_widget.set_mode(mode)
            
            # Block signals to prevent premature updates
            self.min_strain_spinbox.blockSignals(True)
            self.max_strain_spinbox.blockSignals(True)
            self.max_steps_spinbox.blockSignals(True)

            if mode == 'Temperature':
                self.min_strain_spinbox.setRange(0.001, 1e9)
                self.max_strain_spinbox.setRange(0.001, 1e9)
                
                # Default Temperature setup
                self.max_steps_spinbox.setValue(10000)
                self.min_strain_spinbox.setValue(300.0)
                self.max_strain_spinbox.setValue(300.0)
                
                self.min_strain_spinbox.setPrefix("Min Temp: ")
                self.max_strain_spinbox.setPrefix("Max Temp: ")
                
                # Reset graph for Temperature (linear, 300K)
                self.graph_widget.set_max_values(10000, 300.0, 300.0)
                self.graph_widget.points_norm = [QPointF(0, 0.0), QPointF(1.0, 0.0)] # Flat line at min
                self.graph_widget.segments = [{'type': 'line'}]
                
            else: # Deformation
                self.min_strain_spinbox.setRange(-0.999999, 1e9)
                self.max_strain_spinbox.setRange(-1e9, 1e9)
                
                # Default Deformation setup
                self.max_steps_spinbox.setValue(10000)
                self.min_strain_spinbox.setValue(0.0)
                self.max_strain_spinbox.setValue(1.0)
                
                self.min_strain_spinbox.setPrefix("Min Strain: ")
                self.max_strain_spinbox.setPrefix("Max Strain: ")
                
                # Reset graph for Deformation (linear ramp 0->1)
                self.graph_widget.set_max_values(10000, 0.0, 1.0)
                self.graph_widget.points_norm = [QPointF(0, 0.0), QPointF(1.0, 1.0)] # Linear ramp
                self.graph_widget.segments = [{'type': 'line'}]

            self.min_strain_spinbox.blockSignals(False)
            self.max_strain_spinbox.blockSignals(False)
            self.max_steps_spinbox.blockSignals(False)
            
            # Force update controls to reflect new ranges/values
            self._update_graph_controls()
            
            # Rebuild layout for the new mode (defaults)
            self._rebuild_ensemble_layout()

        # Final UI updates common to both paths
        self.temp_spinbox.setVisible(mode == 'Deformation')
        self.deform_axis_label.setVisible(mode == 'Deformation')
        self.deform_axis_combo.setVisible(mode == 'Deformation')
        
        self._update_deform_scenario_visibility()
        
        # If we restored state, layout rebuild happened in set_state.
        # If we initialized defaults, layout rebuild happened above.
        
        button_style = "background-color: darkorange;" if mode == 'Temperature' else ""
        self.undo_button.setStyleSheet(button_style)
        self.redo_button.setStyleSheet(button_style)
        self.generate_button.setStyleSheet(button_style)
        self.reset_button.setStyleSheet(button_style)

        parent_tab = self.parent().parent() if self.parent() and self.parent().parent() else None
        if parent_tab and hasattr(parent_tab, '_update_tab_colors'):
            parent_tab._update_tab_colors()

        # Save the state for the new mode to its undo stack
        self._save_state_for_undo()

        self.dataChanged.emit()
        self.graph_widget.update()

        self._is_mode_switching = False

    def _update_custom_commands_height(self):
        """Update the height of the custom commands text field based on content."""
        # Calculate the required height based on number of lines
        # Empty document reports 0 lines: clamp to 1 so the field never
        # collapses below its one-line minimum height.
        line_count = max(1, self.custom_commands_text.document().lineCount())
        font_height = self.custom_commands_text.fontMetrics().lineSpacing()
        
        # Use consistent padding of 18px to account for borders and margins
        padding = 14

        # Calculate the required height for the content
        content_height = int(line_count * font_height + padding)
        max_height = int(4 * font_height + padding)

        # Only show scrollbar when content exceeds the display area (more than 4 lines)
        if line_count > 4:
            self.custom_commands_text.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAsNeeded)
        else:
            self.custom_commands_text.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)

        # Set the height constraints
        # Ensure minimum is exactly one line + padding
        self.custom_commands_text.setMinimumHeight(int(font_height + padding))

        if line_count <= 4:
            # Expand to fit content up to 4 lines
            self.custom_commands_text.setMaximumHeight(content_height)
        else:
            # Keep fixed height and let scrollbar handle overflow
            self.custom_commands_text.setMaximumHeight(max_height)

    def _on_custom_commands_changed(self):
        """Handle changes to the custom commands text field or sync checkbox."""
        # Get the parent DeformationTab instance
        stacked_widget = self.parent()  # This is the QStackedWidget
        if stacked_widget is not None:
            tab_widget = stacked_widget.parent()  # This should be the QTabWidget
            if tab_widget is not None:
                deformation_tab = tab_widget.parent()  # This should be the DeformationTab
                if isinstance(deformation_tab, DeformationTab):
                    # Check if sync is enabled in THIS tab (the one that changed)
                    sync_state = self.sync_custom_commands_checkbox.isChecked()
                    if sync_state:
                        # Sync is enabled in this tab, propagate the text from this tab to all other tabs
                        deformation_tab._sync_custom_commands_settings(self)
                    else:
                        # Sync is disabled, check if this was a sync checkbox change
                        sender = self.sender()
                        if sender == self.sync_custom_commands_checkbox:
                            # The sync checkbox was just unchecked in this tab
                            # Uncheck sync in all other tabs
                            deformation_tab._sync_custom_commands_settings(self, force_unchecked=True)

        self.dataChanged.emit() # Emit dataChanged to update summaries

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
        add_tab_button.clicked.connect(lambda: self._add_study(is_first=False, auto_rename=True))
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

    def _add_study(self, is_first=False, source_index=None, auto_rename=False):
        # Capture the currently active widget to restore selection if cancelled
        previous_active_widget = self.tab_widget.currentWidget()
        
        initial_state = None
        tab_name = ""
        
        # Determine insertion index and source widget
        if source_index is not None:
            # Context Menu Copy: Insert RIGHT of the source tab
            insert_index = source_index + 1
            source_widget = self.tab_widget.widget(source_index)
            base_name = self.tab_widget.tabText(source_index)
        else:
            # Button Click (+): Insert RIGHT of the currently selected tab
            insert_index = self.tab_widget.currentIndex() + 1 if self.tab_widget.count() > 0 else 0
            source_widget = self.tab_widget.currentWidget()
            if source_widget:
                base_name = self.tab_widget.tabText(self.tab_widget.currentIndex())
            else:
                base_name = f"Study{self._get_next_default_study_number():02d}"

        if is_first:
            # This is for the initial tab or when the last tab is closed
            initial_state = None # No state to copy
            tab_name = f"Study{self._get_next_default_study_number():02d}"
        else:
            # Copying an existing tab
            if source_widget:
                initial_state = source_widget.get_state()
                # Use base name directly for copies
                tab_name = base_name
            else:
                # Fallback if no widget found (shouldn't happen if count > 0)
                initial_state = None
                tab_name = f"Study{self._get_next_default_study_number():02d}"

        new_study = StudyWidget(initial_state)

        # Apply current timestep and units from main window
        if hasattr(self.main_window, 'timestep'):
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
        
        tab_index = self.tab_widget.insertTab(insert_index, new_study, tab_name)
        self.tab_widget.setCurrentIndex(tab_index)

        if not self._batch_loading:
            self.update_summaries()
            self._update_tab_colors()
        self.studiesChanged.emit()

        # Handle auto-rename for copies
        if auto_rename:
            # Prepare callback to restore selection to the previous active widget if canceled
            cancel_callback = None
            if previous_active_widget:
                cancel_callback = lambda: self.tab_widget.setCurrentWidget(previous_active_widget)
            
            self._rename_tab(tab_index, dialog_title="Create Copy", delete_on_cancel=True, cancel_callback=cancel_callback)

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

    def _rename_tab(self, index, dialog_title="Rename Study", delete_on_cancel=False, cancel_callback=None):
        current_name = self.tab_widget.tabText(index)

        while True:
            new_name, ok = QInputDialog.getText(self, dialog_title, "New study name:", text=current_name)

            if not ok:
                if delete_on_cancel:
                    # Remove the newly added tab if user cancels
                    self.tab_widget.widget(index).deleteLater()
                    self.tab_widget.removeTab(index)
                    self.update_summaries()
                    self._update_tab_colors()
                    self.studiesChanged.emit()
                    
                    # Restore selection to where it was before
                    if cancel_callback:
                        cancel_callback()
                return

            if not new_name:
                QMessageBox.warning(self, "Invalid Name", "Study name cannot be empty.")
                continue

            # Validate the new name
            if re.match(r"^[a-zA-Z0-9_-]+$", new_name):
                # Check if name already exists (excluding the current tab itself)
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

    # Old method for bond breakage - no longer needed since we replaced with custom text field
    # Keeping this method for backward compatibility during transition
    def _sync_bond_breakage_settings(self, source_study_widget, force_unchecked=False):
        pass

    def _sync_custom_commands_settings(self, source_study_widget, force_unchecked=False):
        """Sync custom commands text across all study tabs"""
        # Get the source state (the custom commands text and sync status)
        source_state = source_study_widget.get_state()['bond_commands']  # Use old key for backward compatibility

        # Propagate settings to all other tabs
        for i in range(self.tab_widget.count()):
            target_study_widget = self.tab_widget.widget(i)
            # Skip the source widget (the one that changed)
            if target_study_widget == source_study_widget:
                continue

            # Block signals on target widget to prevent recursive calls
            target_study_widget.custom_commands_text.blockSignals(True)
            target_study_widget.sync_custom_commands_checkbox.blockSignals(True)

            if force_unchecked:
                # Only uncheck the sync checkbox in all other tabs
                target_study_widget.sync_custom_commands_checkbox.setChecked(False)
            else:
                # Copy the custom commands text from source to target
                target_study_widget.custom_commands_text.setPlainText(source_state['commands'])
                # Also copy the sync checkbox state
                target_study_widget.sync_custom_commands_checkbox.setChecked(source_state['sync_bond_commands'])

            # Unblock signals
            target_study_widget.custom_commands_text.blockSignals(False)
            target_study_widget.sync_custom_commands_checkbox.blockSignals(False)

            # Trigger height update for target widget
            target_study_widget._update_custom_commands_height()
            target_study_widget.dataChanged.emit() # Trigger summary update for target

    def _sync_ensemble_settings(self, source_study_widget, force_unchecked=False):
        source_state = source_study_widget.get_state()['ensemble']
        source_mode = source_study_widget.mode

        for i in range(self.tab_widget.count()):
            target_study_widget = self.tab_widget.widget(i)
            if target_study_widget == source_study_widget:
                continue
            
            # Only sync studies of the same mode
            if target_study_widget.mode != source_mode:
                continue

            # Block signals common to all modes
            target_study_widget.pressure_spinbox.blockSignals(True)
            target_study_widget.temp_spinbox.blockSignals(True)
            target_study_widget.sync_ensemble_checkbox.blockSignals(True)
            target_study_widget.npt_aniso_combo.blockSignals(True)

            if force_unchecked:
                target_study_widget.sync_ensemble_checkbox.setChecked(False)
            else:
                # Sync common settings
                target_study_widget.pressure_spinbox.setValue(source_state['pressure'])
                target_study_widget.temp_spinbox.setValue(source_state['temperature'])
                target_study_widget.sync_ensemble_checkbox.setChecked(source_state['sync_ensemble'])
                target_study_widget.npt_aniso_combo.setCurrentText(source_state['npt_aniso'])

                if source_mode == 'Temperature':
                    target_study_widget.ensemble_combo.blockSignals(True)
                    target_study_widget.ensemble_combo.setCurrentText(source_state['ensemble'])
                    target_study_widget.ensemble_combo.blockSignals(False)
                
                elif source_mode == 'Deformation':
                    # Sync lateral contraction settings for matching axes
                    source_lateral = source_state.get('lateral_contraction', {})
                    for axis, widget in target_study_widget.lateral_widgets.items():
                        if axis in source_lateral:
                            widget.blockSignals(True)
                            widget.setCurrentText(source_lateral[axis])
                            widget.blockSignals(False)
                    
                    # Trigger visibility update for target since lateral settings changed
                    target_study_widget._update_lateral_npt_visibility()

            # Unblock signals common to all modes
            target_study_widget.pressure_spinbox.blockSignals(False)
            target_study_widget.temp_spinbox.blockSignals(False)
            target_study_widget.sync_ensemble_checkbox.blockSignals(False)
            target_study_widget.npt_aniso_combo.blockSignals(False)

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

        # Enabled toggle
        enabled_action = QAction("Enabled", self, checkable=True)
        enabled_action.setChecked(widget.is_enabled)
        enabled_action.toggled.connect(lambda checked: self._toggle_study_enabled(index, checked))
        menu.addAction(enabled_action)

        # Create copy option
        copy_action = QAction("Create copy", self)
        # Call _add_study with specific source_index and enable auto_rename
        copy_action.triggered.connect(lambda: self._add_study(is_first=False, source_index=index, auto_rename=True))
        menu.addAction(copy_action)
        
        # Rename option
        rename_action = QAction("Rename", self)
        rename_action.triggered.connect(lambda: self._rename_tab(index))
        menu.addAction(rename_action)

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
        if self._batch_loading: return
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
            all_summaries.append(f'--- Summary for {study_name} | Mode: {mode} ---')

            points = study_widget.graph_widget.get_data_points()
            segments = study_widget.graph_widget.segments
            y_unit = study_widget.graph_widget.get_y_unit()
            y_header = "Temperature" if mode == 'Temperature' else "Strain"

            linear_segments_data = []
            sine_segments_data = []
            for j, segment_info in enumerate(segments):
                if j + 1 < len(points):
                    p1, p2 = points[j], points[j+1]
                    is_recovery = segment_info.get('strain_recovery', False) # Check recovery status
                    
                    # For recovery segments, p2.y is forced to 0.0, so use that value in summary
                    effective_p2_y = 0.0 if is_recovery else p2.y()

                    if segment_info['type'] == 'line':
                        linear_segments_data.append({'index': j, 'p1': p1, 'p2': QPointF(p2.x(), effective_p2_y), 'is_recovery': is_recovery})
                    elif segment_info['type'] == 'sine':
                        # Sine segments in recovery mode are treated as line segments for summary and script
                        if is_recovery:
                            linear_segments_data.append({'index': j, 'p1': p1, 'p2': QPointF(p2.x(), effective_p2_y), 'is_recovery': is_recovery})
                        else:
                            sine_segments_data.append({'index': j, 'p1': p1, 'p2': QPointF(p2.x(), effective_p2_y), 'info': segment_info})

            if linear_segments_data:
                header = f"{ 'Lin Seg':<8} | {'Time Step':<20} | {'Time':<30} | {y_header:<16} | {f'Slope ({y_unit}/step)':<14} | {f'Rate ({y_unit}/t)':<14}"
                all_summaries.append(header)
                all_summaries.append("-" * len(header))
                for data in linear_segments_data:
                    j, p1, p2, is_recovery_seg = data['index'], data['p1'], data['p2'], data['is_recovery']
                    p1_t, p2_t = p1.x() * timestep, p2.x() * timestep
                    dx_s, dx_t, dy_e = p2.x() - p1.x(), p2_t - p1_t, p2.y() - p1.y()
                    
                    slope_str = "---"
                    rate_str = "---"
                    strain_p2_str = "~"
                    
                    if not is_recovery_seg:
                        slope = (dy_e / dx_s if dx_s != 0 else float('inf'))
                        rate = (dy_e / dx_t if dx_t != 0 else float('inf'))
                        slope_str = f'{slope:.4e}'
                        rate_str = f'{rate:.4e}'
                        strain_p2_str = f'{p2.y():.3f}'
                    
                    all_summaries.append(f"{j+1:<8} | {f'[{p1.x():.0f}, {p2.x():.0f}]':<20} | {f'[{p1_t:.2f}, {p2_t:.2f}] {unit_key}':<30} | {f'[{p1.y():.3f}, {strain_p2_str}]':<16} | {slope_str:<14} | {rate_str:<14}")

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