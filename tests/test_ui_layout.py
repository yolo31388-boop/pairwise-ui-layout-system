"""UI布局系统 - 红态测试"""
import pytest, sys, os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from ui.layout_system import UILayoutSystem, UIElement

class TestAnchorLayout:
    def test_anchor_based_position(self):
        uls = UILayoutSystem()
        uls.elements["btn"] = UIElement("btn", (0,0), (100,50), anchor="center")
        layout = uls.calculate_layout()
        assert layout["btn"][0] > 0

class TestSafeAreaAllSides:
    def test_safe_area_top_considered(self):
        uls = UILayoutSystem()
        uls.apply_safe_area("portrait")
        assert uls.safe_area["top"] > 0

class TestVerticalLayout:
    def test_vertical_layout_supported(self):
        uls = UILayoutSystem()
        els = [UIElement("a",(0,0),(50,50)), UIElement("b",(0,0),(50,50))]
        positions = uls.auto_layout(els, "vertical")
        assert positions[1][1] > 0

class TestAspectConstraint:
    def test_aspect_ratio_constraint(self):
        uls = UILayoutSystem()
        el = UIElement("img", (0,0), (100,100))
        uls.apply_constraints(el, {"aspect_ratio": 1.0})
        assert el.size[0] == el.size[1]

class TestResolutionRelayout:
    def test_landscape_relayouts(self):
        uls = UILayoutSystem()
        uls.elements["btn"] = UIElement("btn", (100,100), (100,50))
        uls.adapt_resolution((1080, 1920))
        assert uls.screen_size == (1080, 1920)
