"""Tools expuestas al LLM. Dos reglas de oro:

1. NUNCA SQL libre: cada tool es una función Python con firma tipada y consulta
   parametrizada, ejecutada con el motor de SOLO LECTURA.
2. El LLM NUNCA elige el cliente: el customer_id viene de la identidad autenticada
   (cabecera de la pasarela) y se enlaza a las tools antes de entregárselas al modelo.
"""
from decimal import Decimal

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncEngine


class ToolError(Exception):
    pass


def _validate_id(value: str, name: str) -> str:
    if not value or not value.isalnum() or len(value) > 32:
        raise ToolError(f"{name} inválido")
    return value


async def get_account_balance(engine: AsyncEngine, customer_id: str) -> dict:
    """Devuelve el saldo del cliente. Consulta parametrizada, sin f-strings."""
    customer_id = _validate_id(customer_id, "customer_id")
    stmt = text("SELECT balance, currency FROM accounts WHERE customer_id = :cid")
    async with engine.connect() as conn:
        row = (await conn.execute(stmt, {"cid": customer_id})).first()
    if row is None:
        raise ToolError("cliente no encontrado")
    return {"balance": float(Decimal(row[0])), "currency": row[1]}


async def get_product_info(engine: AsyncEngine, product_code: str) -> dict:
    code = product_code.strip().upper()
    if not code.replace("-", "").isalnum() or len(code) > 20:
        raise ToolError("product_code inválido")
    stmt = text("SELECT name, annual_rate FROM products WHERE code = :code")
    async with engine.connect() as conn:
        row = (await conn.execute(stmt, {"code": code})).first()
    if row is None:
        raise ToolError("producto no encontrado")
    return {"code": code, "name": row[0], "annual_rate": float(row[1])}


def bind_tools(engine: AsyncEngine, customer_id: str) -> dict:
    """Devuelve las funciones que verá el LLM, con el cliente YA fijado.

    El modelo no puede pasar un customer_id: la firma de `balance` no lo admite.
    """
    customer_id = _validate_id(customer_id, "customer_id")

    async def balance() -> dict:
        """Consulta el saldo de la cuenta del cliente autenticado."""
        return await get_account_balance(engine, customer_id)

    async def product(product_code: str) -> dict:
        """Consulta información de un producto bancario por su código (ej. PROD-8849-X)."""
        return await get_product_info(engine, product_code)

    return {"get_account_balance": balance, "get_product_info": product}


def build_llamaindex_tools(engine: AsyncEngine, customer_id: str):  # pragma: no cover - requiere llama_index
    """Empaqueta las funciones enlazadas como FunctionTool de LlamaIndex (import perezoso)."""
    from llama_index.core.tools import FunctionTool

    fns = bind_tools(engine, customer_id)
    return [FunctionTool.from_defaults(async_fn=fn, name=name) for name, fn in fns.items()]
