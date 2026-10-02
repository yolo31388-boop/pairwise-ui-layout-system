"""UI布局系统 - 含5个bug"""
from dataclasses import dataclass, field

@dataclass
class UIElement:
    eid: str
    position: tuple  # 绝对坐标 bug1
    size: tuple
    anchor: str = "top_left"

class UILayoutSystem:
    def __init__(self):
        self.elements: dict[str, UIElement] = {}
        self.screen_size: tuple = (1920, 1080)
        self.safe_area: dict = {"top": 0, "bottom": 0, "left": 0, "right": 0}

    def calculate_layout(self) -> dict:
        # bug1: 固定像素，无锚点
        return {eid: el.position for eid, el in self.elements.items()}

    def apply_safe_area(self, orientation: str = "portrait") -> None:
        # bug2: 只考虑底部
        self.safe_area["bottom"] = 30

    def auto_layout(self, elements: list, direction: str = "horizontal") -> list:
        # bug3: 只水平排列，无间距
        positions = []
        x = 0
        for el in elements:
            positions.append((x, 0))
            x += el.size[0]
        return positions

    def apply_constraints(self, element: UIElement, constraints: dict) -> None:
        # bug4: 只支持边距，无循环检测
        if "left" in constraints:
            element.position = (constraints["left"], element.position[1])

    def adapt_resolution(self, new_size: tuple) -> None:
        # bug5: 只缩放，不重排
        scale_x = new_size[0] / self.screen_size[0]
        scale_y = new_size[1] / self.screen_size[1]
        for el in self.elements.values():
            el.position = (el.position[0] * scale_x, el.position[1] * scale_y)
        self.screen_size = new_size
