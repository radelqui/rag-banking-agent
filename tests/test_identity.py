import pytest

from app.core.config import Settings
from app.security.identity import get_customer_id


class R:
    def __init__(self, headers):
        self.headers = headers


def test_reads_identity_from_gateway_header():
    assert get_customer_id(R({"X-Customer-Id": " C123 "}), Settings(_env_file=None)) == "C123"


@pytest.mark.parametrize("bad", [None, "", "C1 OR 1=1", "x" * 40])
def test_rejects_missing_or_forged_identity(bad):
    from fastapi import HTTPException

    with pytest.raises(HTTPException) as e:
        get_customer_id(R({} if bad is None else {"X-Customer-Id": bad}), Settings(_env_file=None))
    assert e.value.status_code == 401
