import numpy as np

import config
from app.calibration import Calibration
from app.gesture import OPEN, PINCH, HandFeatures, HandObservation
from app.hand_tracker import RawHand, assign_arms
from app.mapping import RobotMapper, apply_deadzone, norm_to_angle, remap_to_norm


def obs(arm, x=0.5, y=0.5, tilt=0.0, gesture=OPEN):
    f = HandFeatures(x, y, tilt, 1.0, 1.8, (True,) * 5)
    return HandObservation(arm, "Left", f, gesture)


def test_remap_and_deadzone():
    assert remap_to_norm(0.5, 0.15, 0.85) == 0.0
    assert remap_to_norm(0.0, 0.15, 0.85) == -1.0 and remap_to_norm(1.0, 0.15, 0.85) == 1.0
    assert apply_deadzone(0.03, 0.05) == 0.0 and apply_deadzone(1.0, 0.05) == 1.0


def test_norm_to_angle_hits_limits():
    s = Calibration.default().servos["left_base"]
    assert norm_to_angle(-1, s) == 20 and norm_to_angle(0, s) == 90 and norm_to_angle(1, s) == 160
    assert norm_to_angle(5, s) == 160


def test_targets_always_inside_limits():
    cal = Calibration.default()
    m = RobotMapper(cal)
    for x in (-5, 0, 0.5, 1, 7):
        for y in (-5, 0.5, 9):
            m.update({"left": obs("left", x, y, tilt=500), "right": obs("right", x, y, tilt=-500)}, 0.0)
            for name, value in zip(config.SERVO_NAMES, m.targets()):
                s = cal.servos[name]
                assert s.min <= value <= s.max


def test_centered_hand_gives_center():
    m = RobotMapper(Calibration.default())
    for _ in range(10):
        m.update({"left": obs("left")}, 0.0)
    assert m.targets()[:3] == [90, 90, 90]


def test_hand_up_raises_shoulder_and_pinch_closes():
    m = RobotMapper(Calibration.default())
    m.update({"left": obs("left", y=0.1, gesture=PINCH)}, 0.0)
    t = m.targets()
    assert t[1] > 90 and t[3] == 30


def test_hand_loss_holds_pose_and_state_transitions():
    m = RobotMapper(Calibration.default())
    m.update({"left": obs("left", x=0.9)}, 10.0)
    before = m.targets()
    m.update({"left": None}, 10.5)
    assert m.targets() == before
    assert m.tracking_state("left", 10.05) == "TRACKING"
    assert m.tracking_state("left", 10.4) == "UNCERTAIN"
    assert m.tracking_state("left", 12.0) == "LOST"
    assert m.tracking_state("right", 12.0) == "LOST"


def test_invert_applies_to_mapped_joint():
    cal = Calibration.default()
    cal.servos["left_base"].invert = True
    m = RobotMapper(cal)
    m.update({"left": obs("left", x=0.95)}, 0.0)
    assert m.targets()[0] < 90


def _raw(label, x):
    lm = np.zeros((21, 3)); lm[0, 0] = x
    return RawHand(label, 0.9, lm)


def test_assign_by_label_mirrored():
    a = assign_arms([_raw("Left", 0.3), _raw("Right", 0.7)], mirrored_input=True)
    assert a["left"].landmarks[0, 0] == 0.3 and a["right"].landmarks[0, 0] == 0.7


def test_assign_labels_reversed_when_not_mirrored():
    a = assign_arms([_raw("Left", 0.3)], mirrored_input=False)
    assert list(a) == ["right"]


def test_swap_setting():
    a = assign_arms([_raw("Left", 0.3)], mirrored_input=True, swap=True)
    assert list(a) == ["right"]


def test_duplicate_labels_fall_back_to_position():
    a = assign_arms([_raw("Left", 0.8), _raw("Left", 0.2)], mirrored_input=True)
    assert a["left"].landmarks[0, 0] == 0.2 and a["right"].landmarks[0, 0] == 0.8
