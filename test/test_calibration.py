import json

import pytest

import config
from app.calibration import Calibration, CalibrationError, load_calibration, save_calibration


def test_default_limits_match_config():
    cal = Calibration.default()
    assert (cal.servos["left_base"].min, cal.servos["left_base"].max) == (20, 160)
    assert (cal.servos["right_gripper"].min, cal.servos["right_gripper"].max) == (25, 100)


def test_clamp_never_exceeds_limits():
    cal = Calibration.default()
    assert cal.clamp("left_base", -50) == 20
    assert cal.clamp("left_base", 500) == 160
    assert cal.clamp("left_elbow", 90) == 90


def test_invert_flips_around_center_then_clamps():
    cal = Calibration.default()
    cal.servos["left_base"].invert = True
    assert cal.to_output("left_base", 100) == 80
    assert cal.to_output("left_base", 170) == 20      # 2*90-170 = 10 -> clamped to 20


def test_home_is_center():
    assert Calibration.default().home_outputs() == [90] * 8


def test_load_creates_default_file(tmp_path):
    path = tmp_path / "calibration.json"
    cal, warnings = load_calibration(path)
    assert path.exists() and warnings == []
    assert cal.servos["right_elbow"].max == 150


def test_save_and_load_roundtrip(tmp_path):
    path = tmp_path / "c.json"
    cal = Calibration.default()
    cal.servos["left_shoulder"].min = 30
    cal.swap_left_right = True
    save_calibration(cal, path)
    loaded, warnings = load_calibration(path)
    assert warnings == [] and loaded.servos["left_shoulder"].min == 30 and loaded.swap_left_right


def test_partial_file_is_filled_with_defaults(tmp_path):
    path = tmp_path / "c.json"
    path.write_text(json.dumps({"left_base": {"min": 30, "max": 150, "center": 90, "invert": True}}))
    cal, warnings = load_calibration(path)
    assert warnings == [] and cal.servos["left_base"].invert and cal.servos["right_base"].min == 20


def test_malformed_json_falls_back_to_defaults(tmp_path):
    path = tmp_path / "c.json"
    path.write_text("{not json")
    cal, warnings = load_calibration(path)
    assert warnings and cal.servos["left_base"].min == 20


def test_invalid_values_rejected(tmp_path):
    with pytest.raises(CalibrationError):
        Calibration.from_dict({"left_base": {"min": 100, "max": 50, "center": 90}})
    with pytest.raises(CalibrationError):
        Calibration.from_dict({"left_base": {"min": 0, "max": 200, "center": 90}})
    with pytest.raises(CalibrationError):
        Calibration.from_dict({"left_base": {"invert": "yes"}})
    path = tmp_path / "c.json"
    path.write_text(json.dumps({"left_base": {"min": 100, "max": 50, "center": 90}}))
    cal, warnings = load_calibration(path)
    assert warnings and cal.servos["left_base"].min == 20


def test_gripper_open_closed():
    cal = Calibration.default()
    assert cal.gripper_angle("left", True) == 90
    assert cal.gripper_angle("left", False) == 30
