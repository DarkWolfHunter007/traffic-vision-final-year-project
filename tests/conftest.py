import pytest

from pattom.register import Register


@pytest.fixture(scope="session")
def register():
    return Register.load()
