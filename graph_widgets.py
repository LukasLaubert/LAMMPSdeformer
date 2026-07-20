import sys
import math
import re
from PyQt6.QtWidgets import (
    QApplication, QMainWindow, QWidget, QVBoxLayout, QHBoxLayout,
    QLabel, QSpinBox, QDialog, QDoubleSpinBox, QMenu,
    QTextEdit, QDialogButtonBox, QFormLayout, QPushButton, QInputDialog,
    QTabWidget, QComboBox, QScrollArea, QMessageBox, QStackedWidget, QListWidget
)
from PyQt6.QtCore import Qt, QPointF, QRectF, pyqtSignal, QTimer
from PyQt6.QtGui import QPainter, QPen, QBrush, QColor, QFont, QAction, QFontMetrics, QKeySequence

# --- Professional Style & Data ---
STYLE_BACKGROUND = QColor("#FFFFFF"); STYLE_FRAME = QColor("#ADB5BD"); STYLE_LINE = QColor("#007BFF"); STYLE_HANDLE = QColor("#007BFF")
STYLE_HANDLE_OUTLINE = QColor("#FFFFFF"); STYLE_TEXT_PRIMARY = QColor("#212529"); STYLE_TEXT_SECONDARY = QColor("#6C757D"); STYLE_SLOPE_TEXT = QColor("#E8590C")
HANDLE_RADIUS = 7; PADDING = 60
LAMMPS_UNITS = {"lj": "tau", "real": "fs", "metal": "ps", "si": "s", "cgs": "s", "electron": "fs", "micro": "μs", "nano": "ns"}

# --- Custom Dialogs ---
class PresetDialog(QDialog):
    def __init__(self, last_scheme, last_staircase_params, last_cyclic_params, parent=None):
        super().__init__(parent); self.setWindowTitle("Generate Scheme")
        self.scheme_combo = QComboBox(); self.scheme_combo.addItems(["Staircase Loading", "Cyclic Loading"])
        self.scheme_combo.setCurrentText(last_scheme)
        self.scheme_combo.currentIndexChanged.connect(self._update_options)
        self.stacked_widget = QStackedWidget()
        self._create_staircase_options(last_staircase_params); self._create_cyclic_options(last_cyclic_params)
        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel); buttons.accepted.connect(self.accept); buttons.rejected.connect(self.reject)
        layout = QFormLayout(self); layout.addRow("Scheme Type:", self.scheme_combo); layout.addWidget(self.stacked_widget); layout.addWidget(buttons)
        self._update_options(self.scheme_combo.currentIndex())
    def _create_staircase_options(self, params):
        self.staircase_widget = QWidget()
        layout = QFormLayout(self.staircase_widget)
        self.staircase_cycles = QSpinBox(); self.staircase_cycles.setRange(1, 1000); self.staircase_cycles.setValue(params['cycles'])
        self.staircase_factor = QDoubleSpinBox(); self.staircase_factor.setRange(0.0, 1000.0); self.staircase_factor.setValue(params['factor'])
        self.staircase_direction = QComboBox(); self.staircase_direction.addItems(["Tension", "Compression"]); self.staircase_direction.setCurrentText(params['direction'])
        layout.addRow("Number of Stairs:", self.staircase_cycles); layout.addRow("Hold Time Factor:", self.staircase_factor); layout.addRow("Direction:", self.staircase_direction)
        self.stacked_widget.addWidget(self.staircase_widget)
    def _create_cyclic_options(self, params):
        self.cyclic_widget = QWidget()
        layout = QFormLayout(self.cyclic_widget)
        self.cyclic_cycles = QSpinBox(); self.cyclic_cycles.setRange(1, 1000); self.cyclic_cycles.setValue(params['cycles'])
        self.cyclic_relax_factor = QDoubleSpinBox(); self.cyclic_relax_factor.setRange(0.0, 1000.0); self.cyclic_relax_factor.setValue(params['relax_factor'])
        self.cyclic_start = QComboBox(); self.cyclic_start.addItems(["Tension", "Compression"]); self.cyclic_start.setCurrentText(params['start_with'])
        layout.addRow("Number of Cycles:", self.cyclic_cycles); layout.addRow("Final Relaxation Factor (of 1 cycle):", self.cyclic_relax_factor); layout.addRow("Start With:", self.cyclic_start)
        self.stacked_widget.addWidget(self.cyclic_widget)
    def _update_options(self, index): self.stacked_widget.setCurrentIndex(index)
    def get_parameters(self):
        scheme_index = self.stacked_widget.currentIndex()
        scheme = self.scheme_combo.itemText(scheme_index)
        if scheme == "Staircase Loading": return scheme, {'cycles': self.staircase_cycles.value(), 'factor': self.staircase_factor.value(), 'direction': self.staircase_direction.currentText()}
        elif scheme == "Cyclic Loading": return scheme, {'cycles': self.cyclic_cycles.value(), 'relax_factor': self.cyclic_relax_factor.value(), 'start_with': self.cyclic_start.currentText()}
        return None, None

class SlopeEditDialog(QDialog):
    def __init__(self, p1, p2, timestep, parent=None):
        super().__init__(parent); self.setWindowTitle("Edit Slope / Strain Rate"); self._timestep = timestep
        self._dx_steps = p2.x() - p1.x()
        self.slope_box = QDoubleSpinBox(decimals=5); self.rate_box = QDoubleSpinBox(decimals=5)
        initial_slope = (p2.y() - p1.y()) / self._dx_steps if self._dx_steps != 0 else 0
        for box, val in [(self.slope_box, initial_slope), (self.rate_box, 0)]: box.setRange(-1e9, 1e9); box.setSingleStep(max(1e-5, abs(val) * 0.02))
        self.slope_box.setValue(initial_slope); self.slope_box.valueChanged.connect(self._slope_changed); self.rate_box.valueChanged.connect(self._rate_changed); self._slope_changed(initial_slope)
        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel); buttons.accepted.connect(self.accept); buttons.rejected.connect(self.reject)
        layout = QFormLayout(self); layout.addRow("Slope (ε/step):", self.slope_box); layout.addRow("Strain Rate (ε/t):", self.rate_box); layout.addWidget(buttons)
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
        super().__init__(parent); self.setWindowTitle("Set Coordinates")
        self.step_box = QSpinBox(); self.step_box.setRange(0, max_step); self.step_box.setValue(int(step)); self.step_box.setSingleStep(max(1, int(step*0.02) if step > 0 else 1))
        self.strain_box = QDoubleSpinBox(); self.strain_box.setRange(min_strain, max_strain); self.strain_box.setValue(strain); self.strain_box.setDecimals(4); self.strain_box.setSingleStep(max(0.01, abs(strain)*0.02 if strain != 0 else 0.01))
        if index == 0: self.step_box.setEnabled(False); self.strain_box.setEnabled(False)
        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel); buttons.accepted.connect(self.accept); buttons.rejected.connect(self.reject)
        layout = QFormLayout(self); layout.addRow("Time Step:", self.step_box); layout.addRow("Strain:", self.strain_box); layout.addWidget(buttons)
    def get_coordinates(self): return self.step_box.value(), self.strain_box.value()

# --- Main Graph Widget ---
class GraphWidget(QWidget):
    dataChanged = pyqtSignal()
    def __init__(self, parent=None):
        super().__init__(parent); self.setMinimumSize(600, 400); self.setMouseTracking(True)
        self._max_steps, self._min_strain, self._max_strain, self._timestep, self._time_unit = 100, 0.0, 1.0, 1.0, "s"
        self.points_norm = [self._data_to_norm(QPointF(0,0)), self._data_to_norm(QPointF(100, 1.0))]; self._sort_points()
        self._dragged_handle_index, self._hovered_handle_index, self._dragged_segment_index, self._hovered_segment_index = None, None, None, None
        self._drag_start_pos_widget, self._drag_axis_lock, self._segment_drag_offset_norm = None, None, QPointF(0,0)
        self._drag_mouse_to_p1_offset = QPointF(0,0); self._clickable_regions = []
    def set_max_values(self, s, min_e, max_e):
        old_points_data = self.get_data_points(); old_max_steps = self._max_steps
        self._max_steps, self._min_strain, self._max_strain = int(s), float(min_e), float(max_e)
        new_points_data = []
        for p in old_points_data:
            new_x = p.x() * (self._max_steps / old_max_steps) if old_max_steps > 0 else 0
            clamped_y = max(self._min_strain, min(self._max_strain, p.y()))
            new_points_data.append(QPointF(new_x, clamped_y))
        new_points_data[0] = QPointF(0,0)
        if len(new_points_data) > 1:
            new_points_data[-1].setX(float(self._max_steps))
        self.points_norm = [self._data_to_norm(p) for p in new_points_data]
        self.update(); self.dataChanged.emit()
    def set_timestep(self, s): self._timestep = s; self.update(); self.dataChanged.emit()
    def set_time_unit(self, u): self._time_unit = u; self.update()
    def reset_graph(self): self.points_norm = [self._data_to_norm(QPointF(0,0)), self._data_to_norm(QPointF(self._max_steps, self._max_strain))]; self.update(); self.dataChanged.emit()
    def generate_staircase_scheme(self, cycles, relax_factor, direction):
        if cycles <= 0 or relax_factor < 0: return
        target_strain = self._max_strain if direction == "Tension" else self._min_strain
        if target_strain == 0: self.reset_graph(); return
        strain_per_cycle = target_strain / cycles; total_ratio_units = cycles * (1 + relax_factor)
        if total_ratio_units == 0: return
        steps_per_load_unit = self._max_steps / total_ratio_units
        load_steps, relax_steps = steps_per_load_unit, steps_per_load_unit * relax_factor
        new_data_points = [QPointF(0, 0)]
        for i in range(1, cycles + 1):
            load_end_step = i * load_steps + (i - 1) * relax_steps; load_end_strain = i * strain_per_cycle
            new_data_points.append(QPointF(load_end_step, load_end_strain))
            if (i * (load_steps + relax_steps)) < self._max_steps:
                relax_end_step = i * (load_steps + relax_steps); new_data_points.append(QPointF(relax_end_step, load_end_strain))
        if new_data_points[-1].x() < self._max_steps: new_data_points.append(QPointF(self._max_steps, target_strain))
        self.points_norm = [self._data_to_norm(self._snap_data_point(p)) for p in new_data_points]; self._sort_points(); self.update(); self.dataChanged.emit()
    def generate_cyclic_scheme(self, cycles, relax_factor, start_with):
        if cycles <= 0: return
        path = [0.0]
        peak1 = self._max_strain if start_with == "Tension" else self._min_strain
        peak2 = self._min_strain if start_with == "Tension" else self._max_strain
        for i in range(cycles):
            path.append(peak1)
            if self._min_strain < 0 < self._max_strain: path.extend([0.0, peak2, 0.0])
            else: path.append(0.0)
        total_dist = sum(abs(path[i] - path[i-1]) for i in range(1, len(path)))
        if total_dist == 0: return
        steps_per_one_cycle = total_dist / cycles
        total_steps_for_cycles_and_relax = total_dist + (steps_per_one_cycle * relax_factor)
        scaling_factor = self._max_steps / total_steps_for_cycles_and_relax if total_steps_for_cycles_and_relax > 0 else 0
        points = [QPointF(0,0)]; current_step = 0.0
        for i in range(1, len(path)):
            current_step += abs(path[i] - path[i-1])
            points.append(QPointF(current_step, path[i]))
        if relax_factor > 0:
            current_step += steps_per_one_cycle * relax_factor
            points.append(QPointF(current_step, points[-1].y()))
        final_points = [QPointF(p.x() * scaling_factor, p.y()) for p in points]
        self.points_norm = [self._data_to_norm(self._snap_data_point(p)) for p in final_points]; self._sort_points(); self.update(); self.dataChanged.emit()
    def get_data_points(self): return [self._norm_to_data(p) for p in self.points_norm]
    def _norm_to_data(self, p_norm):
        strain_range = self._max_strain - self._min_strain
        if strain_range < 1e-9: return QPointF(p_norm.x() * self._max_steps, self._min_strain)
        y_norm_zero = abs(self._min_strain) / strain_range if self._min_strain < 0 else 0.0
        if p_norm.y() >= y_norm_zero: y_data = (p_norm.y() - y_norm_zero) / (1.0 - y_norm_zero) * self._max_strain if (1.0 - y_norm_zero) > 1e-9 else self._max_strain
        else: y_data = (p_norm.y() / y_norm_zero - 1.0) * abs(self._min_strain) if y_norm_zero > 1e-9 else self._min_strain
        return QPointF(p_norm.x() * self._max_steps, y_data)
    def _data_to_norm(self, p_data):
        strain_range = self._max_strain - self._min_strain
        if strain_range < 1e-9: return QPointF(p_data.x() / self._max_steps if self._max_steps > 0 else 0, 0.5)
        y_norm_zero = abs(self._min_strain) / strain_range if self._min_strain < 0 else 0.0
        if p_data.y() >= 0: y_norm = y_norm_zero + (p_data.y() / self._max_strain) * (1.0 - y_norm_zero) if self._max_strain > 1e-9 else y_norm_zero
        else: y_norm = (p_data.y() - self._min_strain) / abs(self._min_strain) * y_norm_zero if self._min_strain < -1e-9 else y_norm_zero
        return QPointF(p_data.x() / self._max_steps if self._max_steps > 0 else 0, y_norm)
    def _widget_to_norm(self, pos):
        dw, dh = self.width() - 2 * PADDING, self.height() - 2 * PADDING
        if dw <= 0 or dh <= 0: return QPointF(0, 0)
        return QPointF(max(0.0, min(1.0, (pos.x() - PADDING) / dw)), max(0.0, min(1.0, 1.0 - (pos.y() - PADDING) / dh)))
    def _norm_to_widget(self, p): return QPointF(PADDING + p.x() * (self.width() - 2 * PADDING), PADDING + (1.0 - p.y()) * (self.height() - 2 * PADDING))
    def _sort_points(self): self.points_norm.sort(key=lambda p: p.x())
    def _snap_data_point(self, p): strain_range = self._max_strain - self._min_strain; return QPointF(round(p.x()), round(p.y() / (strain_range/200.0)) * (strain_range/200.0) if strain_range > 0 else p.y())
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
        for i in range(len(self.points_norm) - 1):
            p1_w, p2_w = self._norm_to_widget(self.points_norm[i]), self._norm_to_widget(self.points_norm[i+1])
            painter.setPen(QPen(STYLE_LINE, 2)); painter.drawLine(p1_w, p2_w)
            p1_d, p2_d = self._norm_to_data(self.points_norm[i]), self._norm_to_data(self.points_norm[i+1])
            dx_s, dy_e, dx_t = p2_d.x() - p1_d.x(), p2_d.y() - p1_d.y(), (p2_d.x() - p1_d.x()) * self._timestep
            slope, rate = (dy_e / dx_s if dx_s != 0 else float('inf')), (dy_e / dx_t if dx_t != 0 else float('inf'))
            slope_text, rate_text = f"{slope:.2e} ε/step", f"{rate:.2e} ε/t"
            slope_rect = QRectF(fm.boundingRect(slope_text).adjusted(-2,-2,2,2)); slope_rect.moveCenter((p1_w/2 + p2_w/2) - QPointF(0, 20))
            rate_rect = QRectF(fm.boundingRect(rate_text).adjusted(-2,-2,2,2)); rate_rect.moveCenter((p1_w/2 + p2_w/2) - QPointF(0, 6))
            painter.setPen(STYLE_SLOPE_TEXT); painter.setFont(QFont("Arial", 9, QFont.Weight.Bold)); painter.drawText(slope_rect, slope_text)
            painter.setPen(STYLE_TEXT_SECONDARY); painter.drawText(rate_rect, rate_text)
            self._clickable_regions.append((slope_rect.united(rate_rect), "slope", i))
        for i, p_norm in enumerate(self.points_norm):
            p_data, p_w = self._norm_to_data(p_norm), self._norm_to_widget(p_norm)
            painter.setPen(QPen(STYLE_HANDLE_OUTLINE, 2)); painter.setBrush(STYLE_HANDLE); painter.drawEllipse(p_w, HANDLE_RADIUS, HANDLE_RADIUS)
            y_text = f"{p_data.y():.3f}"; y_rect = QRectF(fm.boundingRect(y_text)); y_rect.moveCenter(QPointF(p_w.x() + 35, p_w.y()))
            painter.setPen(STYLE_TEXT_PRIMARY); painter.setFont(QFont("Arial", 10, QFont.Weight.Bold)); painter.drawText(y_rect, y_text)
            self._clickable_regions.append((y_rect, "y_val", i))
            step_text, time_text = f"{p_data.x():.0f}", f"({p_data.x() * self._timestep:.2f}{self._time_unit})"
            step_rect = QRectF(fm.boundingRect(step_text).adjusted(-4,0,4,0)); step_rect.moveCenter(QPointF(p_w.x(), self.height() - PADDING + 18))
            time_rect = QRectF(fm.boundingRect(time_text)); time_rect.moveCenter(QPointF(p_w.x(), self.height() - PADDING + 34))
            painter.setPen(STYLE_TEXT_PRIMARY); painter.drawText(step_rect, step_text)
            painter.setPen(STYLE_TEXT_SECONDARY); painter.setFont(QFont("Arial", 9)); painter.drawText(time_rect, time_text)
            self._clickable_regions.append((step_rect.united(time_rect), "x_val", i))
    def _draw_axes_and_frame(self, painter):
        painter.setPen(QPen(STYLE_FRAME, 2)); painter.drawRect(PADDING, PADDING, self.width() - 2 * PADDING, self.height() - 2 * PADDING)
        painter.setPen(STYLE_TEXT_PRIMARY); painter.setFont(QFont("Arial", 11, QFont.Weight.Bold)); painter.save()
        painter.translate(20, int(self.height() / 2)); painter.rotate(-90); painter.drawText(0, 0, "Strain"); painter.restore()
        painter.drawText(int(self.width()/2 - 30), self.height() - PADDING + 55, "Time Steps")
    def mousePressEvent(self, event):
        if event.button() == Qt.MouseButton.LeftButton:
            self._drag_start_pos_widget = event.position()
            self._dragged_handle_index = self._get_handle_at(self._drag_start_pos_widget)
            if self._dragged_handle_index is None:
                self._dragged_segment_index = self._get_segment_at(self._drag_start_pos_widget)
                if self._dragged_segment_index is not None:
                    i = self._dragged_segment_index; p1_w = self._norm_to_widget(self.points_norm[i])
                    self._drag_mouse_to_p1_offset = self._drag_start_pos_widget - p1_w
                    self._segment_drag_offset_norm = self.points_norm[i+1] - self.points_norm[i]
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
            if self._dragged_handle_index == 0: return
            p_data = self._norm_to_data(self._widget_to_norm(constrained_pos)); final_p_norm = self._data_to_norm(self._snap_data_point(p_data))
            if self._dragged_handle_index == len(self.points_norm) - 1: final_p_norm.setX(1.0)
            self.points_norm[self._dragged_handle_index] = final_p_norm; self._sort_points(); self._dragged_handle_index = self.points_norm.index(final_p_norm)
        elif self._dragged_segment_index is not None:
            i = self._dragged_segment_index
            target_p1_w = constrained_pos - self._drag_mouse_to_p1_offset
            p1_new_data_snapped = self._snap_data_point(self._norm_to_data(self._widget_to_norm(target_p1_w)))
            p1_new_norm = self._data_to_norm(p1_new_data_snapped)
            p2_new_norm = p1_new_norm + self._segment_drag_offset_norm
            p_prev = self.points_norm[i-1] if i > 0 else None
            p_next = self.points_norm[i+2] if i < len(self.points_norm) - 2 else None
            if (p_prev is None or p1_new_norm.x() >= p_prev.x()) and (p_next is None or p2_new_norm.x() <= p_next.x()) and all(0.0 <= p.y() <= 1.0 for p in [p1_new_norm, p2_new_norm]):
                self.points_norm[i], self.points_norm[i+1] = p1_new_norm, p2_new_norm
        self.update()
    def mouseReleaseEvent(self, event): self._dragged_handle_index, self._dragged_segment_index, self._drag_start_pos_widget, self._drag_axis_lock = None, None, None, None; self.dataChanged.emit()
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
        if (index == 0 and type in ["x_val", "y_val"]): return
        p_data = self._norm_to_data(self.points_norm[index])
        if type == "y_val":
            new_val, ok = QInputDialog.getDouble(self, "Set Strain", "New Strain Value:", p_data.y(), self._min_strain, self._max_strain, 4, flags=Qt.WindowType.Dialog, step=max(0.001, abs(p_data.y())*0.02) if p_data.y() != 0 else 0.001)
            if ok: p_data.setY(new_val)
        elif type == "x_val" and 0 < index < len(self.points_norm) - 1:
            dialog = TimeEditDialog(p_data.x(), self._timestep, self._max_steps, self);
            if dialog.exec(): p_data.setX(float(dialog.get_step()))
        elif type == "slope":
            dialog = SlopeEditDialog(*self.get_data_points()[index:index+2], self._timestep, self)
            if dialog.exec():
                p1_data, p2_data = self.get_data_points()[index], self.get_data_points()[index+1]
                p2_data.setY(max(self._min_strain, min(self._max_strain, p1_data.y() + dialog.get_slope() * (p2_data.x() - p1_data.x())))); self.points_norm[index+1] = self._data_to_norm(p2_data)
        self.points_norm[index] = self._data_to_norm(p_data); self._sort_points(); self.update(); self.dataChanged.emit()
    def _show_set_coords_dialog(self, index):
        p_data = self._norm_to_data(self.points_norm[index])
        dialog = CoordinateDialog(index, p_data.x(), p_data.y(), self._max_steps, self._min_strain, self._max_strain, self)
        if dialog.exec():
            step, strain = dialog.get_coordinates(); new_p_data = QPointF(float(step), strain)
            if index == 0: return
            elif index == len(self.points_norm) - 1: new_p_data.setX(float(self._max_steps))
            self.points_norm[index] = self._data_to_norm(new_p_data); self._sort_points(); self.update(); self.dataChanged.emit()
    def _delete_handle(self, index): del self.points_norm[index]; self.update(); self.dataChanged.emit()

class StudyWidget(QWidget):
    dataChanged = pyqtSignal()
    def __init__(self, initial_state=None, parent=None):
        super().__init__(parent); 
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0,5,0,0)
        layout.setSpacing(2)
        controls_layout = QHBoxLayout()
        self.max_steps_spinbox = QSpinBox(); self.max_steps_spinbox.setPrefix("Max Steps: "); self.max_steps_spinbox.setRange(1, 2147483647); self.max_steps_spinbox.setValue(100)
        self.min_strain_spinbox = QDoubleSpinBox(); self.min_strain_spinbox.setPrefix("Min Strain: "); self.min_strain_spinbox.setRange(-1e9, 0.0); self.min_strain_spinbox.setValue(0.0); self.min_strain_spinbox.setDecimals(3)
        self.max_strain_spinbox = QDoubleSpinBox(); self.max_strain_spinbox.setPrefix("Max Strain: "); self.max_strain_spinbox.setRange(0.0, 1e9); self.max_strain_spinbox.setValue(1.0); self.max_strain_spinbox.setDecimals(3)

        self.undo_button = QPushButton("↩"); self.redo_button = QPushButton("↪")
        self.generate_button = QPushButton("Generate Scheme..."); self.reset_button = QPushButton("Reset Graph")

        controls_layout.addWidget(QLabel("<b>Axis Controls:</b>")); controls_layout.addWidget(self.max_steps_spinbox); controls_layout.addWidget(self.min_strain_spinbox); controls_layout.addWidget(self.max_strain_spinbox); controls_layout.addStretch()
        controls_layout.addWidget(self.undo_button); controls_layout.addWidget(self.redo_button)
        controls_layout.addWidget(self.generate_button); controls_layout.addWidget(self.reset_button)

        self.graph_widget = GraphWidget(self)

        # Add bottom controls
        bottom_controls_layout = QHBoxLayout()
        
        self.deform_axis_combo = QComboBox()
        self.deform_axis_combo.addItems(["x", "y", "z"])
        self.deform_axis_combo.setMinimumWidth(50)  # Reduce horizontal size
        self.deform_axis_combo.setMaximumWidth(70)  # Set maximum width
        bottom_controls_layout.addWidget(QLabel("Deformation Direction:"))
        bottom_controls_layout.addWidget(self.deform_axis_combo)
        
        bottom_controls_layout.addStretch()

        self.thermo_freq_spinbox = QSpinBox()
        self.thermo_freq_spinbox.setPrefix("Thermo Freq: ")
        self.thermo_freq_spinbox.setRange(1, 1000000)
        self.thermo_freq_spinbox.setValue(100)
        self.thermo_freq_spinbox.setSingleStep(100)
        bottom_controls_layout.addWidget(self.thermo_freq_spinbox)

        layout.addLayout(controls_layout)
        layout.addWidget(self.graph_widget)
        layout.addLayout(bottom_controls_layout)

        self._last_staircase_params = {'cycles': 5, 'factor': 1.0, 'direction': 'Tension'}
        self._last_cyclic_params = {'cycles': 3, 'relax_factor': 0.0, 'start_with': 'Tension'}
        self._last_scheme = "Staircase Loading"

        self._undo_stack = []
        self._redo_stack = []
        self._undo_timer = None  # Will be initialized in _setup_undo_redo

        if initial_state:
            self.set_state(initial_state)
        else:
            self.graph_widget.reset_graph()

        self._setup_undo_redo()
        self.max_steps_spinbox.valueChanged.connect(self._update_graph_controls); self.min_strain_spinbox.valueChanged.connect(self._update_graph_controls); self.max_strain_spinbox.valueChanged.connect(self._update_graph_controls)
        self.graph_widget.dataChanged.connect(self.dataChanged); self.reset_button.clicked.connect(self.graph_widget.reset_graph); self.generate_button.clicked.connect(self._show_preset_dialog)
        self._update_graph_controls()
        self._save_state_for_undo()
    def _update_graph_controls(self):
        max_steps, min_strain, max_strain = self.max_steps_spinbox.value(), self.min_strain_spinbox.value(), self.max_strain_spinbox.value()
        self.max_steps_spinbox.setSingleStep(max(1, int(max_steps * 0.02)))
        self.min_strain_spinbox.setSingleStep(max(0.001, abs(min_strain) * 0.02) if min_strain != 0 else 0.001)
        self.max_strain_spinbox.setSingleStep(max(0.001, abs(max_strain) * 0.02) if max_strain != 0 else 0.001)
        if min_strain >= max_strain: self.min_strain_spinbox.setValue(round(max_strain - 0.01, 3))
        self.graph_widget.set_max_values(max_steps, self.min_strain_spinbox.value(), max_strain)
    def _show_preset_dialog(self):
        dialog = PresetDialog(self._last_scheme, self._last_staircase_params, self._last_cyclic_params, self)
        if dialog.exec():
            scheme, params = dialog.get_parameters()
            self._last_scheme = scheme
            if scheme == "Staircase Loading":
                if params['direction'] == "Tension" and self.max_strain_spinbox.value() <= 0: QMessageBox.warning(self, "Invalid Parameter", "Max Strain must be > 0 for a Tension staircase."); return
                if params['direction'] == "Compression" and self.min_strain_spinbox.value() >= 0: QMessageBox.warning(self, "Invalid Parameter", "Min Strain must be < 0 for a Compression staircase."); return
                self._last_staircase_params = params; self.graph_widget.generate_staircase_scheme(params['cycles'], params['factor'], params['direction'])
            elif scheme == "Cyclic Loading":
                self._last_cyclic_params = params; self.graph_widget.generate_cyclic_scheme(params['cycles'], params['relax_factor'], params['start_with'])
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

        self.graph_widget.dataChanged.connect(self._save_state_for_undo)
        self.max_steps_spinbox.valueChanged.connect(self._save_state_for_undo)
        self.min_strain_spinbox.valueChanged.connect(self._save_state_for_undo)
        self.max_strain_spinbox.valueChanged.connect(self._save_state_for_undo)

        # Add a timer to debounce undo saves
        self._undo_timer = QTimer()
        self._undo_timer.setSingleShot(True)
        self._undo_timer.timeout.connect(self._save_state_for_undo)
        self.graph_widget.dataChanged.connect(lambda: self._undo_timer.start(100))
        self.max_steps_spinbox.valueChanged.connect(lambda: self._undo_timer.start(100))
        self.min_strain_spinbox.valueChanged.connect(lambda: self._undo_timer.start(100))
        self.max_strain_spinbox.valueChanged.connect(lambda: self._undo_timer.start(100))

        self.update_undo_redo_buttons()

    def _save_state_for_undo(self):
        # If timer is active, we're being called from the timer, so don't restart it
        if self._undo_timer.isActive():
            self._undo_timer.stop()
        state = self.get_undo_state()
        if not self._undo_stack or self._undo_stack[-1] != state:
            self._undo_stack.append(state)
            self._redo_stack.clear()
            self.update_undo_redo_buttons()

    def undo(self):
        if len(self._undo_stack) > 1:
            self._redo_stack.append(self._undo_stack.pop())
            state = self._undo_stack[-1]
            self.set_undo_state(state)
            self.update_undo_redo_buttons()

    def redo(self):
        if self._redo_stack:
            state = self._redo_stack.pop()
            self._undo_stack.append(state)
            self.set_undo_state(state)
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
            'thermo_freq': self.thermo_freq_spinbox.value(),
            'deform_axis': self.deform_axis_combo.currentText()
        }
    def set_state(self, state):
        self.max_steps_spinbox.blockSignals(True); self.min_strain_spinbox.blockSignals(True); self.max_strain_spinbox.blockSignals(True); self.thermo_freq_spinbox.blockSignals(True)
        self.max_steps_spinbox.setValue(state.get('max_steps', 100))
        self.min_strain_spinbox.setValue(state.get('min_strain', 0.0))
        self.max_strain_spinbox.setValue(state.get('max_strain', 1.0))
        self.thermo_freq_spinbox.setValue(state.get('thermo_freq', 100))
        self.deform_axis_combo.setCurrentText(state.get('deform_axis', 'x'))
        self.max_steps_spinbox.blockSignals(False); self.min_strain_spinbox.blockSignals(False); self.max_strain_spinbox.blockSignals(False); self.thermo_freq_spinbox.blockSignals(False)
        self._update_graph_controls() # This now correctly sets the graph's axes
        
        data_points_list = state.get('data_points', [])
        if not data_points_list and 'points' in state: # For backward compatibility with old save format
            data_points_list = state.get('points', [])

        # Handle old format where points_norm was saved
        if not data_points_list and 'points_norm' in state:
            points_norm = state.get('points_norm', [])
            self.graph_widget.points_norm = [QPointF(p[0], p[1]) if isinstance(p, list) else QPointF(p.x(), p.y()) for p in points_norm]
        else:
            data_points = [QPointF(p[0], p[1]) for p in data_points_list]
            if data_points:
                self.graph_widget.points_norm = [self.graph_widget._data_to_norm(p) for p in data_points]
        
        self.graph_widget.update()

class DeformationTab(QWidget):
    def __init__(self, main_window, parent=None):
        super().__init__(parent); self.setWindowTitle("Interactive Strain-Time Profile Editor")
        self.main_window = main_window
        main_layout = QVBoxLayout(self)
        self.tab_widget = QTabWidget(); self.tab_widget.setTabsClosable(True); self.tab_widget.tabCloseRequested.connect(self._close_tab)
        self.tab_widget.tabBar().setMovable(True)
        self.tab_widget.tabBar().tabMoved.connect(self.update_summaries)  # Add this line
        self.tab_widget.setStyleSheet("QTabBar::tab { height: 12px; min-width: 60px; padding: 2px 4px; } QTabBar::close-button { padding: 0px; }")
        self.tab_widget.tabBarDoubleClicked.connect(self._rename_tab)

        add_tab_button = QPushButton("+")
        add_tab_button.setToolTip("Add a new study")
        add_tab_button.clicked.connect(self._add_study)
        self.tab_widget.setCornerWidget(add_tab_button, Qt.Corner.TopRightCorner)

        main_layout.addWidget(self.tab_widget)

        self._create_summary_area(main_layout)
        self._add_study(is_first=True)

    def _create_summary_area(self, layout):
        scroll_area = QScrollArea()
        scroll_area.setWidgetResizable(True)
        self.summary_container = QWidget()
        self.summary_layout = QVBoxLayout(self.summary_container)
        self.summary_layout.setSpacing(10)  # Add some spacing between summaries
        self.summary_layout.setContentsMargins(5, 5, 5, 5)  # Add some margins
        scroll_area.setWidget(self.summary_container)
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
        tab_name = f"Study{self._get_next_default_study_number():02d}"
        tab_index = self.tab_widget.addTab(new_study, tab_name); self.tab_widget.setCurrentIndex(tab_index)
        self.update_summaries()

    def _get_next_default_study_number(self):
        num = 1
        while any(f"Study{num:02d}" == self.tab_widget.tabText(i) for i in range(self.tab_widget.count())): num += 1
        return num

    def _close_tab(self, index):
        if self.tab_widget.count() > 1:
            self.tab_widget.widget(index).deleteLater(); self.tab_widget.removeTab(index)
            self.update_summaries()
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

    def update_all_graphs(self, timestep, unit_key):
        for i in range(self.tab_widget.count()):
            widget = self.tab_widget.widget(i)
            widget.graph_widget.set_timestep(timestep)
            widget.graph_widget.set_time_unit(LAMMPS_UNITS[unit_key])
        self.update_summaries()

    def update_summaries(self):
        while self.summary_layout.count():
            item = self.summary_layout.takeAt(0)
            if item.widget(): item.widget().deleteLater()

        timestep = 0
        if self.tab_widget.count() > 0:
            # A bit of a hack to get the timestep, since it's not stored here.
            # Assumes all graphs have the same timestep.
            first_widget = self.tab_widget.widget(0)
            if first_widget:
                timestep = first_widget.graph_widget._timestep
                unit_key = first_widget.graph_widget._time_unit

        for i in range(self.tab_widget.count()):
            study_widget = self.tab_widget.widget(i)
            self.summary_layout.addWidget(QLabel(f"<b>Summary for {self.tab_widget.tabText(i)}</b>"))
            summary_text = QTextEdit(readOnly=True, font=QFont("Courier New", 10))
            summary_text.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
            summary_text.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
            # Disable text interaction to prevent scrolling
            summary_text.setTextInteractionFlags(Qt.TextInteractionFlag.NoTextInteraction)
            points = study_widget.graph_widget.get_data_points()
            header = "{:<10} | {:<18} | {:<18} | {:<18} | {:<20} | {}".format("Segment", "Time Step", "Time", "Strain", "Slope (ε/step)", "Strain Rate (ε/t)")
            lines = [header, "-" * (len(header)+2)]
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
                lines.append(f"{j+1:<10} | {f'[{p1.x():.0f}, {p2.x():.0f}]':<18} | {f'[{p1_t:.2f}, {p2_t:.2f}] {unit_key}':<18} | {f'[{p1.y():.3f}, {p2.y():.3f}]':<18} | {f'{slope:.4e}':<20} | {rate:.4e}")
            summary_text.setText("\n".join(lines))
            # Calculate height based on number of lines
            font_metrics = QFontMetrics(summary_text.font())
            line_height = font_metrics.lineSpacing()
            total_height = line_height * (len(lines) + 2)  # +2 for padding
            summary_text.setFixedHeight(total_height)
            self.summary_layout.addWidget(summary_text)
        self.summary_layout.addStretch()

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