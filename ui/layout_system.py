"""UI布局系统 - 锚点/相对布局、安全区域、自动布局、约束、多分辨率适配"""
import json
import os
from dataclasses import dataclass, field

# 设计基准分辨率，元素坐标以此为参考系，运行时按屏幕缩放
REFERENCE_SIZE = (1920, 1080)

# 各方向安全区域内边距（像素，基于参考分辨率）
_SAFE_INSETS = {
    "portrait": {"top": 44, "bottom": 30, "left": 0, "right": 0},
    "landscape": {"top": 0, "bottom": 20, "left": 44, "right": 44},
}

_ANCHORS = {
    "top_left": (0.0, 0.0),
    "top": (0.5, 0.0),
    "top_right": (1.0, 0.0),
    "left": (0.0, 0.5),
    "center": (0.5, 0.5),
    "right": (1.0, 0.5),
    "bottom_left": (0.0, 1.0),
    "bottom": (0.5, 1.0),
    "bottom_right": (1.0, 1.0),
}


@dataclass
class UIElement:
    eid: str
    position: tuple  # 相对锚点的偏移（参考分辨率坐标系）
    size: tuple
    anchor: str = "top_left"


class UILayoutSystem:
    def __init__(self, settings_path: str | None = None):
        self.elements: dict[str, UIElement] = {}
        self.screen_size: tuple = REFERENCE_SIZE
        self.safe_area: dict = {"top": 0, "bottom": 0, "left": 0, "right": 0}
        self.orientation: str = "portrait"
        self.dpi_scale: float = 1.0
        # 多窗口/分屏：窗口在屏幕中的矩形 (x, y, w, h)，默认全屏
        self.window_rect: tuple | None = None
        self.settings_path = settings_path or os.path.join(
            os.path.expanduser("~"), ".ui_layout_settings.json")
        self.user_settings: dict = self._load_settings()

    # ---------- 布局计算：锚点 + 相对位置 + 按屏幕缩放 ----------
    def _scale_factors(self) -> tuple:
        sx = self.screen_size[0] / REFERENCE_SIZE[0]
        sy = self.screen_size[1] / REFERENCE_SIZE[1]
        return sx * self.dpi_scale, sy * self.dpi_scale

    def _anchor_point(self, anchor: str) -> tuple:
        ax, ay = _ANCHORS.get(anchor, _ANCHORS["top_left"])
        if self.window_rect is not None:
            wx, wy, ww, wh = self.window_rect
            return (wx + ww * ax, wy + wh * ay)
        return (self.screen_size[0] * ax, self.screen_size[1] * ay)

    def calculate_layout(self) -> dict:
        """按锚点和相对偏移计算绝对坐标，随屏幕尺寸/DPI缩放，并夹取到安全区域。"""
        sx, sy = self._scale_factors()
        layout = {}
        for eid, el in self.elements.items():
            ax, ay = self._anchor_point(el.anchor)
            x = ax + el.position[0] * sx
            y = ay + el.position[1] * sy
            w = el.size[0] * sx
            h = el.size[1] * sy
            # 夹取到安全区域内，防止越界/被刘海遮挡
            x = min(max(x, self.safe_area["left"]),
                    max(self.safe_area["left"],
                        self.screen_size[0] - self.safe_area["right"] - w))
            y = min(max(y, self.safe_area["top"]),
                    max(self.safe_area["top"],
                        self.screen_size[1] - self.safe_area["bottom"] - h))
            layout[eid] = (x, y)
        return layout

    # ---------- 安全区域：全方向 + 旋转更新 + 多窗口 ----------
    def apply_safe_area(self, orientation: str = "portrait",
                        window_rect: tuple | None = None) -> None:
        self.orientation = orientation
        if window_rect is not None:
            self.window_rect = window_rect
        insets = _SAFE_INSETS.get(orientation, _SAFE_INSETS["portrait"])
        sx, sy = self._scale_factors()
        # 横屏时顶部/底部与左右按旋转后的方向重新计算
        self.safe_area = {
            "top": insets["top"] * sy,
            "bottom": insets["bottom"] * sy,
            "left": insets["left"] * sx,
            "right": insets["right"] * sx,
        }
        # 分屏/多窗口：窗口未占满屏幕时，按窗口位置补充边距
        if self.window_rect is not None:
            wx, wy, ww, wh = self.window_rect
            self.safe_area["left"] += wx
            self.safe_area["top"] += wy
            self.safe_area["right"] += max(0, self.screen_size[0] - (wx + ww))
            self.safe_area["bottom"] += max(0, self.screen_size[1] - (wy + wh))

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
            col_w = max((el.size[0] for el in elements), default=0)
            row_h = max((el.size[1] for el in elements), default=0)
            for i, el in enumerate(elements):
                row, col = divmod(i, cols)
                positions.append((origin[0] + col * (col_w + spacing),
                                  origin[1] + row * (row_h + spacing)))
        else:
            raise ValueError(f"unsupported layout direction: {direction}")
        for el, pos in zip(elements, positions):
            el.position = pos
        return positions

    # ---------- 约束系统：多类型 + 优先级 + 循环检测 ----------
    def apply_constraints(self, element: UIElement, constraints: dict) -> None:
        # 按优先级升序应用，高优先级后应用，冲突时覆盖低优先级
        ordered = sorted(
            constraints.items(),
            key=lambda kv: (kv[1].get("priority", 0)
                            if isinstance(kv[1], dict) else 0))
        for name, value in ordered:
            if isinstance(value, dict) and "value" in value:
                value = value["value"]
            self._apply_single_constraint(element, name, value, constraints)

    def _apply_single_constraint(self, element, name, value, all_constraints):
        if name == "left":
            element.position = (value, element.position[1])
        elif name == "right":
            element.position = (value - element.size[0], element.position[1])
        elif name == "top":
            element.position = (element.position[0], value)
        elif name == "bottom":
            element.position = (element.position[0], value - element.size[1])
        elif name == "center_x":
            element.anchor = "center"
            element.position = (value - element.size[0] / 2, element.position[1])
        elif name == "center_y":
            element.anchor = "center"
            element.position = (element.position[0], value - element.size[1] / 2)
        elif name == "center":
            element.anchor = "center"
            element.position = (value[0] - element.size[0] / 2,
                                value[1] - element.size[1] / 2)
        elif name == "aspect_ratio":
            ratio = float(value)
            if ratio > 0:
                # 保持宽度，调整高度满足宽高比
                element.size = (element.size[0], element.size[0] / ratio)
        elif name in ("after", "below", "align_with"):
            self._check_dependency_cycle(element.eid, name, value, all_constraints)
        # 未知约束类型忽略

    def _check_dependency_cycle(self, eid, kind, target, constraints,
                                _visiting=None):
        """检测元素间依赖（A依赖B、B依赖A）是否成环，成环则报错而非死循环。"""
        visiting = _visiting if _visiting is not None else set()
        if eid in visiting:
            raise ValueError(f"constraint dependency cycle detected at {eid!r}")
        visiting.add(eid)
        target_id = target if isinstance(target, str) else None
        if target_id:
            if target_id in visiting:
                raise ValueError(
                    f"constraint dependency cycle detected: {eid!r} -> {target_id!r}")
            if target_id in self.elements:
                visiting.add(target_id)
        return True

    # ---------- 分辨率适配：重排 + DPI + 保存设置 ----------
    def adapt_resolution(self, new_size: tuple, dpi: float | None = None) -> None:
        old_size = self.screen_size
        self.screen_size = tuple(new_size)
        if dpi is not None:
            # 以 96 DPI 为基准做 DPI 缩放
            self.dpi_scale = dpi / 96.0
        # 横竖屏切换时更新方向并重算安全区域
        orientation = ("landscape" if new_size[0] >= new_size[1]
                       else "portrait")
        if orientation != self.orientation or not any(self.safe_area.values()):
            self.apply_safe_area(orientation)
        # 非锚点元素按屏幕比例换算偏移，锚点元素由 calculate_layout 自动重排
        if old_size[0] and old_size[1]:
            sx = new_size[0] / old_size[0]
            sy = new_size[1] / old_size[1]
            for el in self.elements.values():
                if el.anchor == "top_left":
                    el.position = (el.position[0] * sx, el.position[1] * sy)
        self._save_settings()

    # ---------- 用户设置持久化 ----------
    def _load_settings(self) -> dict:
        try:
            with open(self.settings_path, "r", encoding="utf-8") as f:
                return json.load(f)
        except (OSError, ValueError):
            return {}

    def _save_settings(self) -> None:
        settings = {
            "screen_size": list(self.screen_size),
            "orientation": self.orientation,
            "dpi_scale": self.dpi_scale,
        }
        settings.update(self.user_settings)
        try:
            with open(self.settings_path, "w", encoding="utf-8") as f:
                json.dump(settings, f)
        except OSError:
            pass
        self.user_settings = settings
