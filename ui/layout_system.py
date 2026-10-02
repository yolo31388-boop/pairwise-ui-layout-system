"""UI布局系统 - 锚点布局 / 安全区域 / 自动布局 / 约束 / 分辨率适配"""
import json
import os
from dataclasses import dataclass, field

ANCHORS = {
    "top_left": (0.0, 0.0), "top_center": (0.5, 0.0), "top_right": (1.0, 0.0),
    "center_left": (0.0, 0.5), "center": (0.5, 0.5), "center_right": (1.0, 0.5),
    "bottom_left": (0.0, 1.0), "bottom_center": (0.5, 1.0), "bottom_right": (1.0, 1.0),
}

# 设备原始安全区（竖屏未旋转时的刘海/圆角/Home条）
DEFAULT_DEVICE_INSETS = {"top": 44, "bottom": 30, "left": 0, "right": 0}
ROTATIONS = ("portrait", "landscape", "portrait_upside_down", "landscape_flipped")


@dataclass
class UIElement:
    eid: str
    position: tuple  # 相对锚点的偏移（参考分辨率下的像素）
    size: tuple
    anchor: str = "top_left"


def _rotate_insets(insets: dict, orientation: str) -> dict:
    """把竖屏原始安全区按旋转方向映射到当前朝向。"""
    t, b, l, r = insets["top"], insets["bottom"], insets["left"], insets["right"]
    if orientation == "portrait":
        return {"top": t, "bottom": b, "left": l, "right": r}
    if orientation == "landscape":  # 顺时针旋转90°：顶部刘海转到左侧
        return {"top": l, "bottom": r, "left": t, "right": b}
    if orientation == "landscape_flipped":
        return {"top": r, "bottom": l, "left": b, "right": t}
    if orientation == "portrait_upside_down":
        return {"top": b, "bottom": t, "left": r, "right": l}
    raise ValueError(f"unknown orientation: {orientation}")


class UILayoutSystem:
    def __init__(self, reference_size: tuple = (1920, 1080),
                 settings_path: str | None = None):
        self.elements: dict[str, UIElement] = {}
        self.reference_size = reference_size  # 设计参考分辨率，用于缩放
        self.screen_size: tuple = reference_size
        self.orientation: str = "portrait"
        self.device_insets: dict = dict(DEFAULT_DEVICE_INSETS)
        self.safe_area: dict = {"top": 0, "bottom": 0, "left": 0, "right": 0}
        self.window_rect: tuple | None = None  # 多窗口/分屏时的窗口 (x, y, w, h)
        self.dpi: float = 160.0
        self.dpi_scale: float = 1.0
        # 默认持久化到用户主目录；传 settings_path 可自定义，传 False/空串可禁用
        self.settings_path = settings_path if settings_path is not None else os.path.join(
            os.path.expanduser("~"), ".ui_layout_settings.json")
        self._dependencies: dict[str, set] = {}  # eid -> 依赖的 eid 集合
        self._load_settings()
        self.apply_safe_area(self.orientation)

    # ---------- 布局计算：锚点 + 相对位置 + 屏幕缩放 ----------
    def _scale(self) -> tuple:
        return (self.screen_size[0] / self.reference_size[0],
                self.screen_size[1] / self.reference_size[1])

    def calculate_layout(self) -> dict:
        """按锚点+相对偏移计算绝对坐标，随屏幕尺寸缩放并夹取到安全区内。"""
        sx, sy = self._scale()
        win_x, win_y = (self.window_rect[0], self.window_rect[1]) if self.window_rect else (0, 0)
        win_w = self.window_rect[2] if self.window_rect else self.screen_size[0]
        win_h = self.window_rect[3] if self.window_rect else self.screen_size[1]
        layout = {}
        for eid, el in self.elements.items():
            ax, ay = ANCHORS.get(el.anchor, ANCHORS["top_left"])
            w, h = el.size[0] * sx * self.dpi_scale, el.size[1] * sy * self.dpi_scale
            x = win_x + ax * win_w + el.position[0] * sx - ax * w
            y = win_y + ay * win_h + el.position[1] * sy - ay * h
            # 夹取到安全区，避免被刘海/圆角遮挡或超出屏幕
            min_x = win_x + self.safe_area["left"]
            min_y = win_y + self.safe_area["top"]
            max_x = win_x + win_w - self.safe_area["right"] - w
            max_y = win_y + win_h - self.safe_area["bottom"] - h
            layout[eid] = (min(max(x, min_x), max(max_x, min_x)),
                           min(max(y, min_y), max(max_y, min_y)))
        return layout

    # ---------- 安全区域：全方向 + 旋转更新 + 多窗口 ----------
    def apply_safe_area(self, orientation: str = "portrait",
                        insets: dict | None = None,
                        window_rect: tuple | None = None) -> None:
        if insets is not None:
            self.device_insets = dict(insets)
        if window_rect is not None:
            self.window_rect = window_rect
        self.orientation = orientation
        rotated = _rotate_insets(self.device_insets, orientation)
        if self.window_rect is not None:
            # 分屏/多窗口：安全区只保留窗口与屏幕边缘重合的部分
            wx, wy, ww, wh = self.window_rect
            sw, sh = self.screen_size
            self.safe_area = {
                "top": rotated["top"] if wy <= 0 else 0,
                "left": rotated["left"] if wx <= 0 else 0,
                "bottom": rotated["bottom"] if wy + wh >= sh else 0,
                "right": rotated["right"] if wx + ww >= sw else 0,
            }
        else:
            self.safe_area = rotated

    def on_orientation_changed(self, orientation: str) -> None:
        """屏幕旋转时重算安全区并重排布局。"""
        self.apply_safe_area(orientation)
        self._relayout()

    def set_window(self, window_rect: tuple | None) -> None:
        """多窗口/分屏模式切换。"""
        self.apply_safe_area(self.orientation, window_rect=window_rect)

    # ---------- 自动布局：水平/垂直/网格 + 间距 + 按元素大小 ----------
    def auto_layout(self, elements: list, direction: str = "horizontal",
                    spacing: float = 0, columns: int | None = None,
                    origin: tuple = (0, 0)) -> list:
        positions = []
        if direction == "horizontal":
            x = origin[0]
            for el in elements:
                positions.append((x, origin[1]))
                x += el.size[0] + spacing
        elif direction == "vertical":
            y = origin[1]
            for el in elements:
                positions.append((origin[0], y))
                y += el.size[1] + spacing
        elif direction == "grid":
            cols = columns or max(1, int(len(elements) ** 0.5 + 0.999))
            col_widths = [0.0] * cols
            rows = (len(elements) + cols - 1) // cols
            row_heights = [0.0] * rows
            for i, el in enumerate(elements):
                col_widths[i % cols] = max(col_widths[i % cols], el.size[0])
                row_heights[i // cols] = max(row_heights[i // cols], el.size[1])
            xs = [origin[0]]
            for c in range(1, cols):
                xs.append(xs[-1] + col_widths[c - 1] + spacing)
            ys = [origin[1]]
            for r in range(1, rows):
                ys.append(ys[-1] + row_heights[r - 1] + spacing)
            for i, _ in enumerate(elements):
                positions.append((xs[i % cols], ys[i // cols]))
        else:
            raise ValueError(f"unknown direction: {direction}")
        for el, pos in zip(elements, positions):
            el.position = pos
        return positions

    # ---------- 约束系统：多类型 + 优先级 + 循环检测 ----------
    def apply_constraints(self, element: UIElement, constraints: dict) -> None:
        """支持 left/right/top/bottom 边距、aspect_ratio、center_x/center_y、
        after/below（相对其他元素）。约束值可为 (value, priority) 元组，
        冲突时高优先级生效，同优先级按声明顺序。"""
        explicit = constraints.get("priorities", {}) if isinstance(
            constraints.get("priorities"), dict) else {}
        ordered = []  # (priority, index, key, value)
        for i, (key, raw) in enumerate(constraints.items()):
            if isinstance(raw, tuple) and len(raw) == 2 and isinstance(raw[1], (int, float)):
                value, priority = raw
            else:
                value, priority = raw, explicit.get(key, 0)
            ordered.append((priority, i, key, value))
        # 优先级高的后应用（覆盖低的），同优先级保持声明顺序
        ordered.sort(key=lambda item: (item[0], item[1]))

        for _, _, key, value in ordered:
            if key == "priorities":
                continue
            if key == "left":
                element.position = (value, element.position[1])
            elif key == "right":
                element.position = (self.reference_size[0] - value - element.size[0],
                                    element.position[1])
            elif key == "top":
                element.position = (element.position[0], value)
            elif key == "bottom":
                element.position = (element.position[0],
                                    self.reference_size[1] - value - element.size[1])
            elif key == "center_x":
                element.anchor = "top_center" if element.anchor.startswith("top") else "center"
                element.position = (value if isinstance(value, (int, float)) else 0,
                                    element.position[1])
            elif key == "center_y":
                element.anchor = "center_left" if element.anchor.endswith("left") else "center"
                element.position = (element.position[0],
                                    value if isinstance(value, (int, float)) else 0)
            elif key == "aspect_ratio":
                ratio = float(value)
                if ratio > 0:
                    element.size = (element.size[0], element.size[0] / ratio)
            elif key in ("after", "below"):
                self._add_dependency(element.eid, value)
            else:
                raise ValueError(f"unsupported constraint: {key}")
        self._resolve_relative(element)

    def _add_dependency(self, eid: str, depends_on: str) -> None:
        deps = self._dependencies.setdefault(eid, set())
        if depends_on in self._dependencies and eid in self._dependencies[depends_on]:
            raise ValueError(f"circular constraint detected: {eid} <-> {depends_on}")
        deps.add(depends_on)
        self._detect_cycle()

    def _detect_cycle(self) -> None:
        WHITE, GRAY, BLACK = 0, 1, 2
        color = {eid: WHITE for eid in self._dependencies}

        def visit(node, stack):
            color[node] = GRAY
            for nxt in self._dependencies.get(node, ()):
                if color.get(nxt, WHITE) == GRAY:
                    raise ValueError(
                        f"circular constraint detected: {' -> '.join(stack + [node, nxt])}")
                if color.get(nxt, WHITE) == WHITE:
                    visit(nxt, stack + [node])
            color[node] = BLACK

        for eid in list(self._dependencies):
            if color[eid] == WHITE:
                visit(eid, [])

    def _resolve_relative(self, element: UIElement) -> None:
        """after 约束：放到被依赖元素右侧（循环已在添加依赖时检测）。"""
        for dep in self._dependencies.get(element.eid, ()):
            other = self.elements.get(dep)
            if other:
                element.position = (other.position[0] + other.size[0], other.position[1])

    # ---------- 分辨率适配：重排 + DPI + 持久化 ----------
    def adapt_resolution(self, new_size: tuple, dpi: float | None = None) -> None:
        was_portrait = self.screen_size[0] <= self.screen_size[1]
        self.screen_size = tuple(new_size)
        if dpi is not None:
            self.dpi = dpi
            self.dpi_scale = max(0.5, dpi / 160.0)
        # 宽高比翻转视为旋转，更新朝向
        is_portrait = new_size[0] <= new_size[1]
        if was_portrait != is_portrait:
            self.orientation = "portrait" if is_portrait else "landscape"
        self.apply_safe_area(self.orientation)
        self._relayout()
        self._save_settings()

    def _relayout(self) -> None:
        """分辨率/朝向变化后重排：把元素偏移换算到新参考系，保持相对位置。"""
        sx, sy = self._scale()
        for el in self.elements.values():
            # 偏移按屏幕比例缩放，保证元素不跑出屏幕
            max_x = max(self.reference_size[0] - el.size[0], 0)
            max_y = max(self.reference_size[1] - el.size[1], 0)
            el.position = (min(max(el.position[0], 0), max_x),
                           min(max(el.position[1], 0), max_y))

    # ---------- 设置持久化 ----------
    def _save_settings(self) -> None:
        data = {
            "screen_size": list(self.screen_size),
            "orientation": self.orientation,
            "dpi": self.dpi,
            "dpi_scale": self.dpi_scale,
            "window_rect": list(self.window_rect) if self.window_rect else None,
            "elements": {eid: {"position": list(el.position), "size": list(el.size),
                               "anchor": el.anchor}
                         for eid, el in self.elements.items()},
        }
        try:
            with open(self.settings_path, "w", encoding="utf-8") as f:
                json.dump(data, f, ensure_ascii=False, indent=2)
        except OSError:
            pass

    def _load_settings(self) -> None:
        if not os.path.exists(self.settings_path):
            return
        try:
            with open(self.settings_path, "r", encoding="utf-8") as f:
                data = json.load(f)
        except (OSError, json.JSONDecodeError):
            return
        self.screen_size = tuple(data.get("screen_size", self.screen_size))
        self.orientation = data.get("orientation", self.orientation)
        self.dpi = data.get("dpi", self.dpi)
        self.dpi_scale = data.get("dpi_scale", self.dpi_scale)
        wr = data.get("window_rect")
        self.window_rect = tuple(wr) if wr else None
        for eid, saved in data.get("elements", {}).items():
            self.elements[eid] = UIElement(eid, tuple(saved["position"]),
                                           tuple(saved["size"]), saved["anchor"])
