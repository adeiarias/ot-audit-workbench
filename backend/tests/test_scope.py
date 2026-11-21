import pytest

from app.scope import target_in_scope, validate_scope

SCOPE = "10.0.0.0/24\n# comentario\n192.168.1.5\nplc.local\n"


@pytest.mark.parametrize("target,ok", [
    ("10.0.0.7", True), ("10.0.0.0/25", True), ("10.0.0.0/23", False), ("10.0.1.1", False),
    ("192.168.1.5", True), ("192.168.1.6", False), ("PLC.local", True), ("other.local", False),
    ("-sV", False), ("", False), ("10.0.0.1; rm -rf /", False), ("::1", False),
])
def test_target_in_scope(target, ok):
    assert target_in_scope(target, SCOPE) is ok


def test_empty_scope_allows_nothing():
    assert target_in_scope("10.0.0.1", "") is False


def test_numeric_tld_is_not_a_hostname():
    for bad in ("10.0.0.256", "1.2.3", "300.1.1.1", "123"):
        with pytest.raises(ValueError):
            validate_scope(bad)
        assert target_in_scope(bad, "10.0.0.0/24\nplc.corp") is False
    validate_scope("plc\nhost-1.corp.local\nx.co")


def test_validate_scope():
    validate_scope(SCOPE)
    with pytest.raises(ValueError):
        validate_scope("10.0.0.0/24\nno es válido!!")
