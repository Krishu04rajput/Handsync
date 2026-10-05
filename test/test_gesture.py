from app.gesture import (FIST, NEUTRAL, OPEN, PINCH, GestureDebouncer, GripperLogic,
                         analyze_hand, classify_gesture)
from helpers import make_hand


def test_open_palm():
    f = analyze_hand(make_hand())
    assert classify_gesture(f) == OPEN


def test_fist():
    f = analyze_hand(make_hand(extended=(False, False, False, False)))
    assert classify_gesture(f) == FIST


def test_pinch():
    f = analyze_hand(make_hand(pinch=True))
    assert classify_gesture(f) == PINCH


def test_pinch_hysteresis():
    f = analyze_hand(make_hand())
    f.pinch_ratio = 0.45                    # between close (0.35) and release (0.55)
    assert classify_gesture(f, previous=PINCH) == PINCH
    assert classify_gesture(f, previous=OPEN) == OPEN


def test_tilt_sign_follows_mirror_flag():
    right_lean = make_hand()
    right_lean[9, 0] += 0.06                # middle knuckle moves right in the image
    assert analyze_hand(right_lean, mirror=True).tilt_deg > 10
    assert analyze_hand(right_lean, mirror=False).tilt_deg < -10


def test_position_flips_when_not_mirrored():
    f1 = analyze_hand(make_hand(wrist=(0.2, 0.5)), mirror=True)
    f2 = analyze_hand(make_hand(wrist=(0.2, 0.5)), mirror=False)
    assert f1.palm_x < 0.5 < f2.palm_x


def test_debouncer_requires_consecutive_frames():
    d = GestureDebouncer(frames=3)
    assert d.update(PINCH) == NEUTRAL
    assert d.update(PINCH) == NEUTRAL
    assert d.update(PINCH) == PINCH
    assert d.update(OPEN) == PINCH and d.update(FIST) == PINCH      # noise does not switch
    for _ in range(3):
        d.update(OPEN)
    assert d.stable == OPEN


def test_gripper_logic():
    g = GripperLogic()
    assert g.update(PINCH) is False
    assert g.update(FIST) is False and g.update(NEUTRAL) is False   # hold
    assert g.update(OPEN) is True
