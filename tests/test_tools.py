"""Tools: valida entradas y usa SQL parametrizado (sin tocar una BD real)."""
import inspect
from contextlib import asynccontextmanager
from unittest.mock import AsyncMock, MagicMock

import pytest

from app.agent.tools import ToolError, bind_tools, get_account_balance, get_product_info


class FakeEngine:
    def __init__(self, row):
        self.row = row
        self.executed = []

    @asynccontextmanager
    async def connect(self):
        conn = MagicMock()

        async def execute(stmt, params):
            self.executed.append((str(stmt), params))
            res = MagicMock()
            res.first.return_value = self.row
            return res

        conn.execute = AsyncMock(side_effect=execute)
        yield conn


async def test_balance_uses_parametrized_query():
    eng = FakeEngine(row=("100.50", "EUR"))
    out = await get_account_balance(eng, "C123")
    assert out == {"balance": 100.5, "currency": "EUR"}
    sql, params = eng.executed[0]
    assert ":cid" in sql and params == {"cid": "C123"}
    assert "C123" not in sql  # nunca concatenado


@pytest.mark.parametrize("bad", ["", "1; DROP TABLE accounts", "x" * 40, "a'b"])
async def test_balance_rejects_bad_ids(bad):
    with pytest.raises(ToolError):
        await get_account_balance(FakeEngine(row=None), bad)


async def test_balance_not_found():
    with pytest.raises(ToolError, match="no encontrado"):
        await get_account_balance(FakeEngine(row=None), "C999")


async def test_product_normalizes_code():
    eng = FakeEngine(row=("Depósito Plus", "3.25"))
    out = await get_product_info(eng, " prod-8849-x ")
    assert out["code"] == "PROD-8849-X"
    assert out["annual_rate"] == 3.25


async def test_bound_tools_never_expose_customer_id():
    eng = FakeEngine(row=("7.00", "EUR"))
    fns = bind_tools(eng, "C123")
    assert list(inspect.signature(fns["get_account_balance"]).parameters) == []  # el LLM no elige cliente
    assert (await fns["get_account_balance"]())["balance"] == 7.0
    assert eng.executed[0][1] == {"cid": "C123"}


def test_bind_tools_rejects_bad_identity():
    with pytest.raises(ToolError):
        bind_tools(FakeEngine(row=None), "C1; DROP")
