from bugmod import bug


def test_bug_doubles():
    assert bug(2) == 4


def test_bug_zero():
    assert bug(0) == 0
