"""Shared pytest options.

--reverse-order runs the collected tests in reverse order. A test that only passes after (or
before) some other test depends on what ran earlier in the process - memory addresses decide
the order of a set of Blender elements, and some Blender operators build their output in that
order - so the suite is also run backwards to show the results do not depend on it.
"""


def pytest_addoption(parser):
    parser.addoption("--reverse-order", action="store_true", default=False,
                     help="run the collected tests in reverse order (shows a test does not depend on what ran before)")


def pytest_collection_modifyitems(config, items):
    if config.getoption("--reverse-order"):
        items.reverse()
