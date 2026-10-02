"""Sanitize pytest reports before terminal/JUnit plugins consume them."""
import pytest
import re
from tests.evidence_hygiene import KEYS, MARKER, redact


def clean_report(report):
    if report.longrepr:
        if isinstance(report.longrepr, tuple):
            report.longrepr = tuple(redact(x)[0] if isinstance(x, str) else x for x in report.longrepr)
        else:
            clean, count = redact(str(report.longrepr))
            if count:
                report.longrepr = clean
    report.sections = [(name, redact(content)[0]) for name, content in report.sections]
    report.user_properties = [(redact(key)[0] if isinstance(key, str) else key,
                               MARKER if re.fullmatch(KEYS, str(key), re.I) and value else
                               redact(value)[0] if isinstance(value, str) else value)
                              for key, value in report.user_properties]


@pytest.hookimpl(hookwrapper=True, tryfirst=True)
def pytest_runtest_makereport(item, call):
    outcome = yield
    clean_report(outcome.get_result())


@pytest.hookimpl(hookwrapper=True, tryfirst=True)
def pytest_make_collect_report(collector):
    outcome = yield
    report = outcome.get_result()
    if not hasattr(report, "user_properties"):
        report.user_properties = []
    clean_report(report)
