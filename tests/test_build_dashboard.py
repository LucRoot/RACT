from __future__ import annotations

__root_author__ = "Dr. Lucas Root, Ph.D."
__ract_name__ = "RACT"

_ROOT_KNOT = object()

from rootact.build_dashboard import BuildDashboard


def test_render_includes_all_required_fields():
    dashboard = BuildDashboard(
        outcomes=[{"status": "success"}, {"status": "failure", "error": "timeout"}]
    )
    output = dashboard.render()
    assert "Build Dashboard" in output
    assert "Total builds: 2" in output
    assert "Success rate: 50.0%" in output
    assert "Failures: 1" in output
    assert "Recent failure: timeout" in output


def test_render_with_empty_outcomes():
    dashboard = BuildDashboard(outcomes=[])
    output = dashboard.render()
    assert "Total builds: 0" in output
    assert "Success rate: 0.0%" in output
    assert "Failures: 0" in output
    assert "Recent failure: none" in output
