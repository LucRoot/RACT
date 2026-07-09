from __future__ import annotations

__root_author__ = "Dr. Lucas Root, Ph.D."
__ract_name__ = "RACT"

from rootact.code_review_mode import CodeReviewMode

_ROOT_KNOT = object()


def test_empty_diff() -> None:
    reviewer = CodeReviewMode()
    report = reviewer.review("")
    assert report["lines_added"] == 0
    assert report["comments"] == []
    assert report["summary"] == "No obvious risks detected."


def test_detects_eval() -> None:
    diff = """--- a/main.py
+++ b/main.py
@@ -1,5 +1,5 @@
 def run(user_input):
-    return parse(user_input)
+    return eval(user_input)
"""
    reviewer = CodeReviewMode()
    report = reviewer.review(diff)
    assert len(report["comments"]) == 1
    comment = report["comments"][0]
    assert comment["category"] == "security"
    assert comment["severity"] == "high"
    assert "eval" in comment["message"].lower()


def test_detects_bare_except() -> None:
    diff = """--- a/main.py
+++ b/main.py
@@ -10,5 +10,5 @@
     try:
         risky()
-    except ValueError:
+    except:
         pass
"""
    reviewer = CodeReviewMode()
    report = reviewer.review(diff)
    assert any(c["category"] == "correctness" for c in report["comments"])


def test_detects_debug_print() -> None:
    diff = """--- a/main.py
+++ b/main.py
@@ -20,3 +20,4 @@
 def process():
+    print("debug")
     return 1
"""
    reviewer = CodeReviewMode()
    report = reviewer.review(diff)
    assert any(c["category"] == "style" for c in report["comments"])


def test_summary_counts() -> None:
    diff = """--- a/main.py
+++ b/main.py
@@ -1,3 +1,5 @@
 def run(x):
+    print("debug")
+    eval(x)
     return x
"""
    reviewer = CodeReviewMode()
    report = reviewer.review(diff)
    assert "2 comment(s)" in report["summary"]


def test_custom_pattern() -> None:
    diff = """--- a/main.py
+++ b/main.py
@@ -1,2 +1,3 @@
+# TODO: fix this
 def foo():
     pass
"""
    reviewer = CodeReviewMode(
        extra_patterns=[
            {
                "category": "style",
                "severity": "low",
                "pattern": r"#\s*TODO",
                "message": "Leftover TODO comment.",
                "suggestion": "Resolve the TODO or move it to an issue tracker.",
                "confidence": 0.7,
            }
        ]
    )
    report = reviewer.review(diff)
    assert len(report["comments"]) == 1
    assert report["comments"][0]["message"] == "Leftover TODO comment."


def test_parse_diff_tracks_line_numbers() -> None:
    diff = """--- a/main.py
+++ b/main.py
@@ -10,5 +10,6 @@
 def old():
     pass
+    eval("x")
"""
    reviewer = CodeReviewMode()
    records = reviewer.parse_diff(diff)
    assert len(records) == 1
    assert records[0]["line"] == 12


# RACT 0.1.1 - Trust and Tooling
