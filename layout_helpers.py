from __future__ import annotations

from dataclasses import dataclass
from typing import Callable, Iterable, Sequence


@dataclass(frozen=True)
class TextBox:
    x: int
    y: int
    w: int
    h: int

    @property
    def right(self) -> int:
        return self.x + self.w

    @property
    def bottom(self) -> int:
        return self.y + self.h

    def overlaps(self, other: "TextBox") -> bool:
        return (
            self.x < other.right
            and self.right > other.x
            and self.y < other.bottom
            and self.bottom > other.y
        )


def status_badge_rows(
    statuses: Iterable[object],
    max_width: int,
    measure: Callable[[str], int],
    gap: int,
    padding: int,
    max_rows: int = 2,
) -> list[list[str]]:
    labels = [str(status) for status in statuses if str(status)]
    rows: list[list[str]] = []
    current: list[str] = []
    current_width = 0

    def badge_width(label: str) -> int:
        return measure(label) + padding * 2

    for index, label in enumerate(labels):
        width = badge_width(label)
        candidate_width = width if not current else current_width + gap + width
        if current and candidate_width > max_width:
            rows.append(current)
            current = []
            current_width = 0
            if len(rows) >= max_rows:
                remaining = len(labels) - index
                summary = f"+{remaining}"
                while rows and rows[-1]:
                    prior = rows[-1][:]
                    prior[-1] = summary
                    total = sum(badge_width(item) for item in prior) + gap * max(0, len(prior) - 1)
                    if total <= max_width:
                        rows[-1] = prior
                        return rows
                    rows[-1] = rows[-1][:-1]
                return rows or [[summary]]
        candidate_width = width if not current else current_width + gap + width
        if current and candidate_width > max_width:
            break
        current.append(label)
        current_width = candidate_width

    if current and len(rows) < max_rows:
        rows.append(current)
    return rows


def stacked_layout_boxes(
    name_height: int,
    status_rows: Sequence[Sequence[str]],
    metric_count: int,
    row_height: int,
    vertical_gap: int,
) -> dict[str, TextBox | list[TextBox]]:
    y = 0
    boxes: dict[str, TextBox | list[TextBox]] = {}
    boxes["name"] = TextBox(0, y, 1, name_height)
    y += name_height

    status_boxes: list[TextBox] = []
    for row in status_rows:
        if row:
            y += vertical_gap
            status_boxes.append(TextBox(0, y, 1, row_height))
            y += row_height
    boxes["statuses"] = status_boxes

    metric_boxes: list[TextBox] = []
    for _ in range(metric_count):
        y += vertical_gap
        metric_boxes.append(TextBox(0, y, 1, row_height))
        y += row_height
    boxes["metrics"] = metric_boxes
    boxes["total"] = TextBox(0, 0, 1, y)
    return boxes
