"""Package O: property and stateful tests for the pure modules in the lane.

hypothesis is a dev dependency. Each module is tested for what must hold for any input:
the checklist state machine (no step moves back from a final state, counts add up, a
stopped turn leaves no step pending, the headless plan agrees with the interactive
view), the diff hunk renderer, the turn summary text, the queue model, the plan
approval answer parser, and the context view and session helpers.
"""

from __future__ import annotations

import io
from datetime import datetime, timezone

from hypothesis import HealthCheck, given, settings
from hypothesis import strategies as st
from hypothesis.stateful import RuleBasedStateMachine, initialize, invariant, rule
from rich.cells import cell_len

from ract import context_view, diff_render, plan_state
from ract.session_events import EventStream
from ract.session_render import PlainRenderer
from ract.turn_summary import describe_change
from ract.ui import plan_approval_view as pav
from ract.ui import queue_view as qv

WIDTHS = st.integers(min_value=20, max_value=200)
TEXT = st.text(
    alphabet=st.sampled_from(
        list("abc xyz\n\r\t") + ["é", "日", "🙂", "́", "\x00", "\x1b"]
    ),
    max_size=300,
)
FINAL = {"done", "failed", "refused", "skipped"}


# --- checklist state machine: plan_state.PlanState -----------------------------------


class ChecklistMachine(RuleBasedStateMachine):
    """Steps move pending -> running -> final. A turn finishes once; the headless plan agrees."""

    @initialize()
    def start(self) -> None:
        self.state = plan_state.PlanState()
        self.count = 0
        self.finished = False
        self.last: dict[int, str] = {}

    @rule(count=st.integers(min_value=1, max_value=6))
    def plan(self, count: int) -> None:
        if self.count:
            return
        self.count = count
        steps = [
            {"n": n, "action": f"step {n}", "target": f"f{n}.py"}
            for n in range(1, count + 1)
        ]
        self.state.observe("plan.proposed", {"steps": steps})
        self.last = {n: "pending" for n in range(1, count + 1)}

    @rule(n=st.integers(min_value=1, max_value=6))
    def start_step(self, n: int) -> None:
        if n <= self.count and not self.finished:
            self.state.observe("step.started", {"n": n})
            if self.last.get(n) not in FINAL:
                self.last[n] = "running"

    @rule(
        n=st.integers(min_value=1, max_value=6), outcome=st.sampled_from(sorted(FINAL))
    )
    def finish_step(self, n: int, outcome: str) -> None:
        if n <= self.count and not self.finished and self.last.get(n) not in FINAL:
            self.state.observe(
                "step.finished", {"n": n, "outcome": outcome, "artifact": None}
            )
            self.last[n] = outcome

    @rule(outcome=st.sampled_from(["done", "interrupted", "failed"]))
    def finish_turn(self, outcome: str) -> None:
        if self.count and not self.finished:
            self.state.observe("turn.finished", {"outcome": outcome})
            self.finished = True
            if outcome == "interrupted":
                for n, value in self.last.items():
                    if value not in FINAL:
                        self.last[n] = "skipped"

    @invariant()
    def no_step_moves_back_from_a_final_state(self) -> None:
        for item in self.state.items():
            n = item["step"]
            if self.last.get(n) in FINAL:
                assert item["state"] == self.last[n] or item["state"] in FINAL, (
                    n,
                    item,
                    self.last,
                )

    @invariant()
    def counts_add_up(self) -> None:
        items = self.state.items()
        assert len(items) == self.count

    @invariant()
    def a_stopped_turn_leaves_no_step_pending(self) -> None:
        if self.finished and self.count:
            assert all(
                item["state"] != "pending" and item["state"] != "running"
                for item in self.state.items()
            ), self.state.items()


TestChecklist = ChecklistMachine.TestCase
TestChecklist.settings = settings(
    max_examples=60, stateful_step_count=25, deadline=None
)


# --- diff hunk renderer --------------------------------------------------------------


@settings(max_examples=250, deadline=None, suppress_health_check=[HealthCheck.too_slow])
@given(
    TEXT.filter(lambda t: "\x00" not in t),
    TEXT.filter(lambda t: "\x00" not in t),
    WIDTHS,
)
def test_diff_lines_fit_the_width_and_counts_match_the_line_difference(old, new, width):
    # NUL makes a file binary: its notice carries no line counts (by design).
    lines, added, removed = diff_render._diff("f.py", old, new, width=width)
    for line in lines:
        assert cell_len(line) <= width, (width, line)
    assert added >= 0 and removed >= 0
    if old == new:
        assert (added, removed) == (0, 0)
    assert added - removed == len(diff_render._lines(new)) - len(
        diff_render._lines(old)
    ), (old, new)


@settings(max_examples=120, deadline=None)
@given(TEXT, WIDTHS)
def test_a_binary_or_line_ending_notice_fits_the_width(text, width):
    # Binary notice and line-ending notice are file-level lines; both must fit.
    crlf = chr(13) + chr(10)
    for old, new in (("", text + chr(0)), (text + crlf, text.replace(crlf, chr(10)))):
        lines, _, _ = diff_render._diff("f.py", old, new, width=width)
        for line in lines:
            assert cell_len(line) <= width, (width, line)


@settings(max_examples=120, deadline=None)
@given(TEXT, WIDTHS)
def test_a_diff_against_nothing_renders_without_error(text, width):
    for side in ((None, text), (text, None)):
        diff_render.render_hunks("f.py", side[0], side[1], width=width)


# --- turn summary text --------------------------------------------------------------


@settings(max_examples=40, deadline=None)
@given(st.integers(min_value=0, max_value=1000), WIDTHS)
def test_the_changed_files_line_counts_every_file_and_fits_the_width(count, width):
    out = io.StringIO()
    stream = EventStream(
        session="s", clock=lambda: datetime(2026, 10, 26, tzinfo=timezone.utc)
    )
    renderer = PlainRenderer(out.write, width=width, wrap=True)
    stream.subscribe(renderer)
    changed = [f"dir/file_{i}.py" for i in range(count)]
    stream.emit(
        "turn.finished",
        {"outcome": "done", "verdict": "Done.", "changed": changed, "diffstat": {}},
        turn=1,
    )
    renderer.close()
    text = out.getvalue()
    for line in text.splitlines():
        assert cell_len(line) <= width, (width, line)
    if count > 10:
        assert f"and {count - 10} more" in " ".join(text.split())
    assert describe_change("a.py", None) == "a.py"


@settings(max_examples=200, deadline=None)
@given(st.integers(min_value=0, max_value=10**6))
def test_describe_change_says_line_or_lines_by_count(n):
    text = describe_change("n.md", {"new": n})
    assert text == (f"n.md (new, {n} line)" if n == 1 else f"n.md (new, {n} lines)")


# --- queue model: a stateful machine over add, take back, drop and list -----------------


class QueueMachine(RuleBasedStateMachine):
    @initialize()
    def start(self) -> None:
        self.model = qv.QueueModel()
        self.texts: list[str] = []
        self.ids: list[int] = []
        self.next_id = 1

    @rule(text=st.text(alphabet="abc xyz", min_size=1, max_size=20))
    def add(self, text: str) -> None:
        self.model = self.model.append(text)
        self.texts.append(text)
        self.ids.append(self.next_id)
        self.next_id += 1

    @rule()
    def take_back(self) -> None:
        self.model, last = self.model.take_last()
        if self.texts:
            assert last is not None and last.text == self.texts.pop()
            self.ids.pop()
        else:
            assert last is None

    @rule(position=st.integers(min_value=-2, max_value=12))
    def drop(self, position: int) -> None:
        if self.texts and 1 <= position <= len(self.texts):
            self.model, removed = self.model.drop(position)
            assert removed.text == self.texts.pop(position - 1)
            self.ids.pop(position - 1)
        else:
            before = self.model
            try:
                self.model, _ = self.model.drop(position)
                raise AssertionError("a bad position was accepted")
            except qv.QueueError:
                assert self.model is before

    @rule(width=st.integers(min_value=20, max_value=200))
    def list_it(self, width: int) -> None:
        lines = qv.list_lines(self.model, width)
        for line in lines:
            assert cell_len(line) <= width

    @invariant()
    def order_and_ids_agree(self) -> None:
        assert [i.text for i in self.model.items] == self.texts
        assert [i.id for i in self.model.items] == self.ids
        assert all(a < b for a, b in zip(self.ids, self.ids[1:]))


TestQueue = QueueMachine.TestCase
TestQueue.settings = settings(max_examples=60, stateful_step_count=30, deadline=None)


# --- plan approval answer parser --------------------------------------------------


@settings(max_examples=400, deadline=None)
@given(TEXT, st.integers(min_value=0, max_value=12))
def test_the_answer_parser_never_raises_and_never_approves_by_accident(line, count):
    answer = pav.parse_answer(line, count)
    assert answer.kind in {"approve", "skip", "edit", "cancel", "error"}
    if answer.kind == "approve":
        assert line.strip().lower() in {"a", "approve", "run", "yes"}
    if answer.kind in {"skip", "edit"}:
        assert answer.n is not None and 1 <= answer.n <= count
    if answer.kind == "error":
        assert answer.error


# --- context view and session helpers ------------------------------------------------


@settings(max_examples=200, deadline=None)
@given(
    st.lists(
        st.fixed_dictionaries(
            {
                "host": st.one_of(st.none(), st.text(max_size=30)),
                "tokens_in": st.one_of(
                    st.none(), st.integers(min_value=0, max_value=10**9)
                ),
                "tokens_out": st.one_of(
                    st.none(), st.integers(min_value=0, max_value=10**9)
                ),
            }
        ),
        max_size=3,
    ),
    st.one_of(st.none(), st.integers(min_value=0, max_value=10**6)),
    WIDTHS,
)
def test_the_context_view_fits_the_width_for_any_numbers_and_hosts(
    records, window, width
):
    for line in context_view.context_lines(records, window, width=width):
        assert cell_len(line) <= width, (width, line)


@settings(max_examples=200, deadline=None)
@given(st.text(max_size=200))
def test_the_session_text_is_short_and_one_line(text):
    from ract import session_listing

    shown = session_listing._short(text)
    assert "\n" not in shown and "\r" not in shown
    assert len(shown) <= 60


def test_a_file_level_notice_with_wide_characters_fits_by_columns():
    # _fit cut by characters; a path of CJK characters ran past the width.
    lines, _, _ = diff_render._diff("日本語のファイル名前.py", "", "x\x00", width=20)
    assert all(cell_len(line) <= 20 for line in lines), lines


def test_the_context_view_folds_a_wide_host_name_by_columns():
    # context_view wrapped with textwrap (characters); a host of CJK ran past the width.
    host = "日本語のホスト名" * 3
    lines = context_view.context_lines(
        [{"host": host, "tokens_in": 1, "tokens_out": 2}], None, width=40
    )
    assert all(cell_len(line) <= 40 for line in lines), lines


def test_a_five_thousand_line_diff_is_summarized_within_a_time_bound():
    # Package Q: the exact matcher grew quadratically between 1000 and 5000 lines (about
    # 2.5 s at 5000). Past the exact range the diff is a count, which must be quick.
    import time

    old = "".join(f"line {i} of the file\n" for i in range(5000))
    new = "".join(f"line {i} of the file, changed\n" if i % 2 else f"line {i} of the file\n" for i in range(5000))
    start = time.perf_counter()
    diff_render._diff("big.py", old, new, width=80)
    assert time.perf_counter() - start < 1.0
