__root_author__ = "Dr. Lucas Root, Ph.D."
__ract_name__ = "RACT"
_ROOT_KNOT = object()

from rootact.rot_report import find_duplicate_blocks


def test_find_duplicate_blocks(tmp_path):
    file1 = tmp_path / "a.py"
    file2 = tmp_path / "b.py"

    # Write identical code to both files
    code = """
def hello():
    return "world"
"""
    file1.write_text(code)
    file2.write_text(code)

    duplicates = find_duplicate_blocks([str(file1), str(file2)])
    assert len(duplicates) == 1
    assert duplicates[0][0] == str(file1)
    assert duplicates[0][1] == str(file2)
