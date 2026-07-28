"""Reference grader — the ALM denies any edit under tests/**/*grader*."""


def grade(actual: str, expected: str) -> bool:
    return actual == expected
