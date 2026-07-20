import sys
import math
import re
from PyQt6.QtWidgets import (
    QApplication, QMainWindow, QWidget, QVBoxLayout, QHBoxLayout,
    QLabel, QSpinBox, QDialog, QDoubleSpinBox, QMenu, QCheckBox,
    QTextEdit, QDialogButtonBox, QFormLayout, QPushButton, QInputDialog,
    QTabWidget, QComboBox, QScrollArea, QMessageBox, QStackedWidget, QListWidget, QSizePolicy
)
from PyQt6.QtCore import Qt, QPointF, QRectF, pyqtSignal, QTimer, QUrl
from PyQt6.QtGui import QPainter, QPen, QBrush, QColor, QFont, QAction, QFontMetrics, QKeySequence, QPixmap, QDesktopServices, QCursor

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
    def __init__(self, last_scheme, last_staircase_params, last_cyclic_params, max_steps, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Generate Scheme")
        self.max_steps = max_steps
        self.scheme_combo = QComboBox()
        self.scheme_combo.addItems(["Staircase Loading", "Cyclic Loading"])
        self.scheme_combo.setCurrentText(last_scheme)
        self.scheme_combo.currentIndexChanged.connect(self._update_options)
        self.stacked_widget = QStackedWidget()
        self._create_staircase_options(last_staircase_params)
        self._create_cyclic_options(last_cyclic_params)
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
        layout.addRow("Final Relaxation Factor (of 1 cycle):", self.cyclic_relax_factor)
        layout.addRow("Start With:", self.cyclic_start)
        self.stacked_widget.addWidget(self.cyclic_widget)

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
        self._dragged_handle_index, self._hovered_handle_index, self._dragged_segment_index, self._hovered_segment_index = None, None, None, None
        self._drag_start_pos_widget, self._drag_axis_lock, self._segment_drag_offset_norm = None, None, QPointF(0,0)
        self._drag_mouse_to_p1_offset = QPointF(0,0); self._clickable_regions = []
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
        painter = QPainter(self); painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        painter.fillRect(self.rect(), STYLE_BACKGROUND); self._clickable_regions.clear()
        self._draw_axes_and_frame(painter)
        if not self.points_norm: return
        fm = QFontMetrics(QFont("Arial", 10))
        # Draw the line segments and slope labels
        for i in range(len(self.points_norm) - 1):
            p1_w, p2_w = self._norm_to_widget(self.points_norm[i]), self._norm_to_widget(self.points_norm[i+1])
            painter.setPen(QPen(self.STYLE_LINE, 2)); painter.drawLine(p1_w, p2_w)
            p1_d, p2_d = self._norm_to_data(self.points_norm[i]), self._norm_to_data(self.points_norm[i+1])
            dx_s, dy_e, dx_t = p2_d.x() - p1_d.x(), p2_d.y() - p1_d.y(), (p2_d.x() - p1_d.x()) * self._timestep
            slope, rate = (dy_e / dx_s if dx_s != 0 else float('inf')), (dy_e / dx_t if dx_t != 0 else float('inf'))
            slope_text = f"{slope:.4e} {self.get_y_unit()}/step"
            rate_text = f"{rate:.4e} {self.get_y_unit()}/t"
            slope_rect = QRectF(fm.boundingRect(slope_text).adjusted(-2,-2,2,2)); slope_rect.moveCenter((p1_w * 2/3 + p2_w * 1/3) - QPointF(0, 20))
            rate_rect = QRectF(fm.boundingRect(rate_text).adjusted(-2,-2,2,2)); rate_rect.moveCenter((p1_w * 2/3 + p2_w * 1/3) - QPointF(0, 6))
            # Check if this segment is fixed and draw in red if so
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
        # Draw the handles and labels
        for i, p_norm in enumerate(self.points_norm):
            p_data, p_w = self._norm_to_data(p_norm), self._norm_to_widget(p_norm)
            painter.setPen(QPen(STYLE_HANDLE_OUTLINE, 2)); painter.setBrush(self.STYLE_HANDLE); painter.drawEllipse(p_w, HANDLE_RADIUS, HANDLE_RADIUS)
            y_text = f"{p_data.y():.3f}"; y_rect = QRectF(fm.boundingRect(y_text)); y_rect.moveCenter(QPointF(p_w.x() + 35, p_w.y()))
            # Check if this y-label is locked and draw in red if so
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
            # Check if this x-tick is locked and draw in red if so
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
    def _draw_axes_and_frame(self, painter):
        painter.setPen(QPen(STYLE_FRAME, 2)); painter.drawRect(self.padding['left'], self.padding['top'], self.width() - (self.padding['left'] + self.padding['right']), self.height() - (self.padding['top'] + self.padding['bottom']))
        painter.setPen(STYLE_TEXT_PRIMARY); painter.setFont(QFont("Arial", 11, QFont.Weight.Bold)); painter.save()
        painter.translate(40, int(self.height() / 2) + 36); painter.rotate(-90)
        y_label = "Temperature / K" if self.mode == 'Temperature' else "Engineering strain"
        painter.drawText(0, 0, y_label)
        painter.restore()
        painter.drawText(int(self.width()/2 - 30), self.height() - self.padding['bottom'] + 55, "Time Steps")

    def get_y_unit(self):
        return "ΔT" if self.mode == 'Temperature' else "ε"
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
        self._hovered_segment_index = self._get_segment_at(pos) if self._hovered_handle_index is None else None
        if self._hovered_handle_index is not None or self._dragged_handle_index is not None: self.setCursor(Qt.CursorShape.PointingHandCursor)
        elif self._hovered_segment_index is not None or self._dragged_segment_index is not None: self.setCursor(Qt.CursorShape.SizeAllCursor)
        else: self.setCursor(Qt.CursorShape.ArrowCursor)
        if not (event.buttons() & Qt.MouseButton.LeftButton): return
        constrained_pos = pos
        if event.modifiers() & Qt.KeyboardModifier.ShiftModifier:
            if self._drag_axis_lock is None: delta = pos - self._drag_start_pos_widget; self._drag_axis_lock = 'y' if abs(delta.y()) > abs(delta.x()) else 'x'
            if self._drag_axis_lock == 'x': constrained_pos.setY(self._drag_start_pos_widget.y())
            else: constrained_pos.setX(self._drag_start_pos_widget.x())
        if self._dragged_handle_index is not None:
            if self._dragged_handle_index == 0 and self.mode == 'Deformation':
                return # Don't move the first handle in deformation mode

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
        # Apply snapping when mouse is released
        if self._dragged_handle_index is not None:
            # Check if adjacent segments are fixed
            prev_segment_fixed = (self._dragged_handle_index - 1) in self._fixed_segments if self._dragged_handle_index > 0 else False
            next_segment_fixed = self._dragged_handle_index in self._fixed_segments if self._dragged_handle_index < len(self.points_norm) - 1 else False
            
            # Check if this handle's y position is locked
            y_locked = self._dragged_handle_index in self._locked_y_labels
            
            # Apply grid snapping when releasing, EXCEPT when adjacent slope is fixed
            # Grid snapping should ONLY NOT be applied when a node is moved while adjacent slope is fixed
            if not (prev_segment_fixed or next_segment_fixed):
                # Snap the dragged handle to the grid
                p_data = self._norm_to_data(self.points_norm[self._dragged_handle_index])
                snapped_p_data = self._snap_data_point(p_data)
                snapped_p_norm = self._data_to_norm(snapped_p_data)
            else:
                # Preserve exact position when adjacent slope is fixed
                snapped_p_norm = self.points_norm[self._dragged_handle_index]
            
            # Ensure first point stays at x=0
            if self._dragged_handle_index == 0:
                snapped_p_norm.setX(0)
                
            # Ensure last point stays at max x
            if self._dragged_handle_index == len(self.points_norm) - 1:
                snapped_p_norm.setX(1.0)
                
            self.points_norm[self._dragged_handle_index] = snapped_p_norm
            self._sort_points()
            
        elif self._dragged_segment_index is not None:
            i = self._dragged_segment_index
            
            # Check if adjacent segments are fixed
            prev_segment_fixed = (i - 1) in self._fixed_segments if i > 0 else False
            next_segment_fixed = (i + 1) in self._fixed_segments if i < len(self.points_norm) - 2 else False
            
            if i < len(self.points_norm) - 1:
                # Apply grid snapping when releasing
                # If adjacent segments are fixed, we preserve exact positions to maintain slopes
                if prev_segment_fixed or next_segment_fixed:
                    # Preserve exact positions when adjacent segments are fixed
                    # to maintain their slopes
                    pass  # Don't snap, keep exact positions
                else:
                    # Normal snapping behavior
                    if i not in self._fixed_segments:
                        p1_data = self._norm_to_data(self.points_norm[i])
                        p2_data = self._norm_to_data(self.points_norm[i+1])
                        
                        # Snap both points
                        snapped_p1_data = self._snap_data_point(p1_data)
                        snapped_p2_data = self._snap_data_point(p2_data)
                        
                        # Convert back to normalized coordinates
                        snapped_p1_norm = self._data_to_norm(snapped_p1_data)
                        snapped_p2_norm = self._data_to_norm(snapped_p2_data)
                    else:
                        # Preserve exact positions when segment is fixed
                        snapped_p1_norm = self.points_norm[i]
                        snapped_p2_norm = self.points_norm[i+1]
                    
                    # Ensure first point stays at x=0 if it's the first segment
                    if i == 0:
                        snapped_p1_norm.setX(0)
                        
                    self.points_norm[i] = snapped_p1_norm
                    self.points_norm[i+1] = snapped_p2_norm
                self._sort_points()
        
        # Ensure the first point stays at x=0 for both modes
        if len(self.points_norm) > 0:
            self.points_norm[0].setX(0)
        self._dragged_handle_index, self._dragged_segment_index, self._drag_start_pos_widget, self._drag_axis_lock = None, None, None, None
        self.dataChanged.emit()
    def mouseDoubleClickEvent(self, event):
        if event.button() == Qt.MouseButton.LeftButton:
            for region, type, index in self._clickable_regions:
                if region.contains(event.position()): self._handle_direct_edit(type, index); return
            new_p_norm = self._data_to_norm(self._snap_data_point(self._norm_to_data(self._widget_to_norm(event.position()))))
            self.points_norm.append(new_p_norm); self._sort_points(); self.update(); self.dataChanged.emit()
    def contextMenuEvent(self, event):
        idx = self._get_handle_at(QPointF(event.pos()))
        if idx is not None:
            menu = QMenu(self); menu.addAction("Set Coordinates...", lambda: self._show_set_coords_dialog(idx))
            if 0 < idx < len(self.points_norm) - 1: menu.addAction("Delete Handle", lambda: self._delete_handle(idx))
            menu.exec(event.globalPos())
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
        self.points_norm[index] = self._data_to_norm(p_data); self._sort_points(); self.update(); self.dataChanged.emit()
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
            self._sort_points()
            self.update()
            self.dataChanged.emit()
    def _delete_handle(self, index): del self.points_norm[index]; self.update(); self.dataChanged.emit()

class StudyWidget(QWidget):
    dataChanged = pyqtSignal()
    def __init__(self, initial_state=None, parent=None):
        super().__init__(parent); 
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
        self.deform_axis_combo.addItems(["x", "y", "z"])
        self.deform_axis_combo.setMinimumWidth(30)
        self.deform_axis_combo.setMaximumWidth(40)
        self.deform_axis_label.setVisible(False)
        self.deform_axis_combo.setVisible(False)
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
        self.deform_scenario_label.setVisible(False)
        self.deform_scenario_combo.setVisible(False)
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

        self.graph_widget.dataChanged.connect(self.dataChanged); self.reset_button.clicked.connect(self.graph_widget.reset_graph); self.generate_button.clicked.connect(self._show_preset_dialog)
        self._update_graph_controls()
        self._save_state_for_undo()
        
        # Update bond breakage UI state to ensure fields are enabled/disabled correctly on startup
        self._update_bond_breakage_ui_state()

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
        dialog = PresetDialog(self._last_scheme, self._last_staircase_params, self._last_cyclic_params, max_steps, self)
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
        self.graph_widget.update()
        self.dataChanged.emit()



    def get_state(self):
        return {
            'data_points': [[p.x(), p.y()] for p in self.graph_widget.get_data_points()],
            'max_steps': self.max_steps_spinbox.value(),
            'min_strain': self.min_strain_spinbox.value(),
            'max_strain': self.max_strain_spinbox.value(),
            'deform_axis': self.deform_axis_combo.currentText(),
            'deform_scenario': self.deform_scenario_combo.currentText(),
            'mode': self.mode,
            'fixed_segments': list(self.graph_widget._fixed_segments),  # Save fixed segments
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
        # Set the spinbox values first
        self.max_steps_spinbox.blockSignals(True)
        self.min_strain_spinbox.blockSignals(True)
        self.max_strain_spinbox.blockSignals(True)
        # Block signals for ensemble controls
        self.ensemble_combo.blockSignals(True)
        self.temp_spinbox.blockSignals(True)
        self.pressure_spinbox.blockSignals(True)
        self.npt_aniso_combo.blockSignals(True)
        self.sync_ensemble_checkbox.blockSignals(True)
        # Block signals for bond breakage controls
        self.enable_bond_breakage_checkbox.blockSignals(True)
        self.nevery_spinbox.blockSignals(True)
        self.bondtype_spinbox.blockSignals(True)
        self.rmax_spinbox.blockSignals(True)
        self.enable_prob_checkbox.blockSignals(True)
        self.prob_fraction_spinbox.blockSignals(True)
        self.prob_seed_spinbox.blockSignals(True)
        self.sync_bond_break_checkbox.blockSignals(True)

        self.max_steps_spinbox.setValue(state.get('max_steps', 100))
        self.min_strain_spinbox.setValue(state.get('min_strain', 0.0))
        self.max_strain_spinbox.setValue(state.get('max_strain', 1.0))
        self.deform_axis_combo.setCurrentText(state.get('deform_axis', 'x'))
        self.deform_scenario_combo.setCurrentText(state.get('deform_scenario', 'symmetric'))

        self.set_mode(state.get('mode', 'Deformation'), adjust_values=False)

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

        self.max_steps_spinbox.blockSignals(False)
        self.min_strain_spinbox.blockSignals(False)
        self.max_strain_spinbox.blockSignals(False)
        # Unblock signals for ensemble controls
        self.ensemble_combo.blockSignals(False)
        self.temp_spinbox.blockSignals(False)
        self.pressure_spinbox.blockSignals(False)
        self.npt_aniso_combo.blockSignals(False)
        self.sync_ensemble_checkbox.blockSignals(False)
        # Unblock signals for bond breakage controls
        self.enable_bond_breakage_checkbox.blockSignals(False)
        self.nevery_spinbox.blockSignals(False)
        self.bondtype_spinbox.blockSignals(False)
        self.rmax_spinbox.blockSignals(False)
        self.enable_prob_checkbox.blockSignals(False)
        self.prob_fraction_spinbox.blockSignals(False)
        self.prob_seed_spinbox.blockSignals(False)
        self.sync_bond_break_checkbox.blockSignals(False)
        
        # Update graph controls to set the correct axis limits
        self._update_graph_controls()
        
        # Load fixed segments
        fixed_segments = state.get('fixed_segments', [])
        self.graph_widget._fixed_segments = set(fixed_segments)
        
        # Now set the data points
        data_points_list = state.get('data_points', [])
        if not data_points_list and 'points' in state:  # For backward compatibility with old save format
            data_points_list = state.get('points', [])

        # Handle old format where points_norm was saved
        if not data_points_list and 'points_norm' in state:
            points_norm = state.get('points_norm', [])
            self.graph_widget.points_norm = [QPointF(p[0], p[1]) if isinstance(p, list) else QPointF(p.x(), p.y()) for p in points_norm]
        else:
            data_points = [QPointF(p[0], p[1]) for p in data_points_list]
            if data_points:
                # Convert data points to normalized coordinates using the current axis limits
                self.graph_widget.points_norm = [self.graph_widget._data_to_norm(p) for p in data_points]
        
        self.graph_widget.update()
        self.dataChanged.emit()  # Emit the dataChanged signal to update summaries
        
        # Update bond breakage UI state to ensure fields are enabled/disabled correctly
        self._update_ensemble_ui_state()
        self._update_bond_breakage_ui_state()

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
        self.pressure_spinbox.setEnabled(is_npt)
        # Show/hide NPT anisotropic options when NPT is selected
        self.npt_aniso_label.setVisible(is_npt)
        self.npt_aniso_combo.setVisible(is_npt)

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

        self._is_mode_switching = True

        self.mode = mode
        is_temp_mode = mode == 'Temperature'

        # Set ranges FIRST to avoid clamping issues
        if is_temp_mode:
            self.min_strain_spinbox.setRange(0.001, 1e9)
            self.max_strain_spinbox.setRange(0.001, 1e9)
        else:
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
        self.deform_scenario_label.setVisible(not is_temp_mode)
        self.deform_scenario_combo.setVisible(not is_temp_mode)

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
    def __init__(self, main_window, parent=None):
        super().__init__(parent); self.setWindowTitle("Interactive Strain-Time Profile Editor")
        self.main_window = main_window
        main_layout = QVBoxLayout(self)
        self.tab_widget = QTabWidget(); self.tab_widget.setTabsClosable(True); self.tab_widget.tabCloseRequested.connect(self._close_tab)
        self.tab_widget.tabBar().setMovable(True)
        self.tab_widget.tabBar().tabMoved.connect(self.update_summaries)
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
        self.mode_combo.setMinimumWidth(120)
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
        add_tab_button.setFixedSize(20, 14)
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
            if widget and hasattr(widget, 'mode') and widget.mode == "Temperature":
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

    def _add_study(self, is_first=False):
        initial_state = self.tab_widget.currentWidget().get_state() if not is_first and self.tab_widget.count() > 0 else None
        new_study = StudyWidget(initial_state)

        # Apply current timestep and units from main window
        timestep = self.main_window.timestep.value()
        units = self.main_window.units_combo.currentText()
        new_study.graph_widget.set_timestep(timestep)
        new_study.graph_widget.set_time_unit(LAMMPS_UNITS[units])

        new_study.dataChanged.connect(self.update_summaries)
        new_study.graph_widget.dataChanged.connect(self.update_summaries)  # Add this line for real-time updates
        new_study.graph_widget.dataChanged.connect(new_study.graph_widget.update)  # Force canvas repaint on data changes
        # Connect mouse move event for real-time updates
        original_mouse_move = new_study.graph_widget.mouseMoveEvent
        new_study.graph_widget.mouseMoveEvent = lambda event: self._wrapped_mouse_move_event(original_mouse_move, event, new_study.graph_widget)
        # Also connect mouse release event for final updates
        original_mouse_release = new_study.graph_widget.mouseReleaseEvent
        new_study.graph_widget.mouseReleaseEvent = lambda event: self._wrapped_mouse_release_event(original_mouse_release, event, new_study.graph_widget)
        tab_name = f"Study{self._get_next_default_study_number():02d}"
        tab_index = self.tab_widget.addTab(new_study, tab_name); self.tab_widget.setCurrentIndex(tab_index)
        self.update_summaries()
        self._update_tab_colors()

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

    def update_all_graphs(self, timestep, unit_key):
        for i in range(self.tab_widget.count()):
            widget = self.tab_widget.widget(i)
            widget.graph_widget.set_timestep(timestep)
            widget.graph_widget.set_time_unit(LAMMPS_UNITS[unit_key])
        self.update_summaries()

    def update_summaries(self):
        timestep = 0
        unit_key = "s"
        if self.tab_widget.count() > 0:
            # Get timestep and unit from first widget
            first_widget = self.tab_widget.widget(0)
            if first_widget:
                timestep = first_widget.graph_widget._timestep
                unit_key = first_widget.graph_widget._time_unit

        # Build all summaries in one text area
        all_summaries = []
        for i in range(self.tab_widget.count()):
            study_widget = self.tab_widget.widget(i)
            study_name = self.tab_widget.tabText(i)
            mode = study_widget.mode
            
            # Add study header with separator
            bond_breakage_status = "Disabled"
            study_state = study_widget.get_state()
            if study_state.get('bond_breakage', {}).get('enable_bond_breakage', False):
                bond_breakage_status = "Enabled"
            all_summaries.append(f"--- Summary for {study_name} | Mode: {mode} | Bond Breakage: {bond_breakage_status} ---")
            
            # Add data
            points = study_widget.graph_widget.get_data_points()
            y_unit = study_widget.graph_widget.get_y_unit()
            y_header = "Temperature" if mode == 'Temperature' else "Strain"
            header = f"{ 'Segment':<10} | { 'Time Step':<18} | { 'Time':<18} | {y_header:<18} | {f'Slope ({y_unit}/step)':<20} | {f'Rate ({y_unit}/t)':<20}"
            all_summaries.append(header)
            all_summaries.append("-" * len(header))
            
            for j in range(len(points) - 1):
                p1, p2 = points[j], points[j+1]
                p1_t = p1.x() * timestep
                p2_t = p2.x() * timestep
                dx_s, dx_t, dy_e = p2.x() - p1.x(), p2_t - p1_t, p2.y() - p1.y()
                slope, rate = (dy_e / dx_s if dx_s != 0 else float('inf')), (dy_e / dx_t if dx_t != 0 else float('inf'))
                time_unit = ""
                for key, val in LAMMPS_UNITS.items():
                    if val == unit_key:
                        time_unit = key
                        break
                all_summaries.append(f"{j+1:<10} | {f'[{p1.x():.0f}, {p2.x():.0f}]':<18} | {f'[{p1_t:.2f}, {p2_t:.2f}] {unit_key}':<18} | {f'[{p1.y():.3f}, {p2.y():.3f}]':<18} | {f'{slope:.4e}':<20} | {rate:.4e}")
            
            # Add blank line between studies (except for the last one)
            if i < self.tab_widget.count() - 1:
                all_summaries.append("")

        # Set the text
        # Preserve scroll position to prevent jumping to top when updating text
        scrollbar = self.summary_text.verticalScrollBar()
        current_scroll_position = scrollbar.value() if scrollbar else 0
        self.summary_text.setText("\n".join(all_summaries))
        # Restore scroll position after updating text
        if scrollbar:
            scrollbar.setValue(current_scroll_position)

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