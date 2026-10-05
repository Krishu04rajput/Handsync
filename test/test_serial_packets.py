import pytest

from app.serial_controller import build_packet, parse_packet, parse_status


def test_build_packet_format():
    assert build_packet([90, 80, 110, 90, 90, 100, 70, 30]) == "90,80,110,90,90,100,70,30\n"


def test_build_packet_rounds_and_limits():
    assert build_packet([90.4, 80.6, -5, 999, 0, 180, 1, 2]) == "90,81,0,180,0,180,1,2\n"


def test_build_packet_wrong_length():
    with pytest.raises(ValueError):
        build_packet([90] * 7)


def test_parse_packet_roundtrip():
    angles = [90, 80, 110, 90, 90, 100, 70, 30]
    assert parse_packet(build_packet(angles)) == angles


@pytest.mark.parametrize("bad", ["", "1,2,3", "1,2,3,4,5,6,7,8,9", "a,b,c,d,e,f,g,h",
                                 "90,90,90,90,90,90,90,181", "90,90,90,90,90,90,90,-1", "9 0,1,2,3,4,5,6,7"])
def test_parse_packet_rejects_invalid(bad):
    with pytest.raises(ValueError):
        parse_packet(bad)


def test_parse_status():
    assert parse_status("STATUS,ENABLED,120,0") == {"state": "ENABLED", "age_ms": 120, "invalid": 0}
    assert parse_status("STATUS,ESTOP")["state"] == "ESTOP"
    assert parse_status("STATUS,BANANA,1") is None
    assert parse_status("garbage") is None
    assert parse_status("STATUS,ENABLED,xx") is None
