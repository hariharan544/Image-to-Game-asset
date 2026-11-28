"""Shared pytest options.

--reverse-order runs the collected tests in reverse order. A test that only passes after (or
before) some other test depends on what ran earlier in the process - memory addresses decide
the order of a set of Blender elements, and some Blender operators build their output in that
order - so the suite is also run backwards to show the results do not depend on it.

Every test also gets back the environment variables it started with: the Forge command line
reads the .env file of the folder it runs in into the environment (forge.cli._load_dotenv), so a
test that runs it next to a throwaway .env would otherwise leave, say, FORGE_BLENDER pointing
at a fake Blender for every test after it.
"""
import os

import pytest


@pytest.fixture(autouse=True)
def _environment_as_it_was():
    saved = dict(os.environ)
    yield
    if dict(os.environ) != saved:
        os.environ.clear()
        os.environ.update(saved)


def pytest_addoption(parser):
    parser.addoption("--reverse-order", action="store_true", default=False,
                     help="run the collected tests in reverse order (shows a test does not depend on what ran before)")


def pytest_collection_modifyitems(config, items):
    if config.getoption("--reverse-order"):
        items.reverse()
