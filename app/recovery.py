"""Respaldo del webhook: si un aviso de pey no llega, se recupera consultando a pey.

- Corre cada RECOVERY_POLL_SECONDS mientras haya al menos una pantalla conectada por SSE,
  y de inmediato cuando una pantalla se (re)conecta.
- Solo consulta los negocios que tienen una pantalla abierta.
- Negocio con CLABE propia: una sola consulta, GET /transaction/bank-account/{id} (QR y cobros al celular).
- Negocio demo (cuenta de la API key): el QR fijo activo, los QR con monto pendientes y los cobros al
  celular pendientes (últimas 24 h), uno por uno.
- El `id` de cada transacción de pey es el mismo `transactionId` del webhook (verificado con datos reales),
  así que `record_payment` (INSERT OR IGNORE por transactionId) nunca duplica ni anuncia dos veces.
"""

import asyncio
import logging

import httpx

from app import config, pey, timeutil
from app.db import connect
from app.events import bus
from app.payments import record_payment

log = logging.getLogger("bocina")

MAX_PAGES = 3            # 60 pagos por QR como máximo en una vuelta
LOOKBACK_SECONDS = 86400  # no se pagina más atrás de 24 h
MIN_GAP_SECONDS = 10      # dos reconexiones seguidas no disparan dos consultas
MAX_BACKOFF_SECONDS = 300


def _targets(merchant_ids: set[str] | None) -> tuple[list[str], list[str], list[str]]:
    """(cuentas bancarias a listar, QR a listar, cobros al celular a consultar) de esos negocios (None = todos)."""
    since = timeutil.now_ts() - LOOKBACK_SECONDS
    with connect() as conn:
        merchants = [m for m in conn.execute("SELECT * FROM merchants WHERE codi_status='ACTIVE'")
                     if merchant_ids is None or m["id"] in merchant_ids]
        accounts = [m["pey_bank_account_id"] for m in merchants if m["pey_bank_account_id"]]
        legacy = [m["id"] for m in merchants if not m["pey_bank_account_id"]]
        if not legacy:
            return accounts, [], []
        marks = ",".join("?" * len(legacy))
        qrs = [r["id"] for r in conn.execute(
            f"SELECT id FROM charges WHERE merchant_id IN ({marks}) AND simulated = 0 AND ("
            " (kind='fixed' AND status='active') OR (kind='amount' AND status='pending' AND created_at >= ?))",
            (*legacy, since),
        )]
        pushes = [r["id"] for r in conn.execute(
            f"SELECT id FROM charges WHERE merchant_id IN ({marks}) AND kind='push' AND status='pending' AND created_at >= ?",
            (*legacy, since),
        )]
    return accounts, qrs, pushes


def _known(tx_ids: list[str]) -> set[str]:
    if not tx_ids:
        return set()
    with connect() as conn:
        marks = ",".join("?" * len(tx_ids))
        return {r[0] for r in conn.execute(f"SELECT transaction_id FROM payments WHERE transaction_id IN ({marks})", tx_ids)}


async def _recover_qr(client: httpx.AsyncClient, qr_id: str) -> int:
    found, token = 0, None
    for _ in range(MAX_PAGES):
        page = await pey.list_qr_transactions(client, qr_id, token)
        items = [i for i in page.get("items") or [] if i.get("status") == "PAID" and i.get("id")]
        known = _known([i["id"] for i in items])
        for item in items:
            if item["id"] in known:
                continue
            event = await record_payment({
                "type": "codi.qr.payment_received", "transactionId": item["id"], "codiQrId": qr_id,
                "amount": item.get("amount"), "datePaid": item.get("datePaid") or item.get("dateCreated"),
                "description": item.get("description"), "metadata": item.get("metadata") or {},
            }, source="recovery")
            found += not event["duplicate"]
        token = page.get("nextToken")
        # Seguimos a la página siguiente solo si toda esta era nueva y reciente
        oldest = min((timeutil.to_seconds(i.get("datePaid")) or 0 for i in items), default=0)
        if not token or known or oldest < timeutil.now_ts() - LOOKBACK_SECONDS:
            break
    return found


async def _recover_account(client: httpx.AsyncClient, bank_account_id: str) -> int:
    found, token = 0, None
    for _ in range(MAX_PAGES):
        page = await pey.list_bank_account_transactions(client, bank_account_id, token)
        items = [i for i in page.get("items") or [] if i.get("status") == "PAID" and i.get("id")]
        known = _known([i["id"] for i in items])
        for item in items:
            if item["id"] in known:
                continue
            is_push = item.get("payableType") == "API_CODI_PN"
            payload = {
                "type": "codi.pn.payment_received" if is_push else "codi.qr.payment_received",
                "transactionId": item["id"], "bankAccountId": bank_account_id,
                "amount": item.get("amount"), "datePaid": item.get("datePaid") or item.get("dateCreated"),
                "description": item.get("description"), "metadata": item.get("metadata") or {},
            }
            if not is_push and item.get("payableId"):
                payload["codiQrId"] = item["payableId"]
            event = await record_payment(payload, source="recovery")
            found += not event["duplicate"]
        token = page.get("nextToken")
        oldest = min((timeutil.to_seconds(i.get("datePaid")) or 0 for i in items), default=0)
        if not token or known or oldest < timeutil.now_ts() - LOOKBACK_SECONDS:
            break
    return found


async def _recover_push(client: httpx.AsyncClient, tx_id: str) -> int:
    tx = await pey.get_transaction(client, tx_id)
    if tx.get("status") != "PAID":
        return 0
    event = await record_payment({
        "type": "codi.pn.payment_received", "transactionId": tx.get("id") or tx_id,
        "amount": tx.get("amount"), "datePaid": tx.get("datePaid"),
        "description": tx.get("description"), "metadata": tx.get("metadata") or {},
    }, source="recovery")
    return 0 if event["duplicate"] else 1


class Recovery:
    def __init__(self) -> None:
        self._lock = asyncio.Lock()
        self._wake = asyncio.Event()
        self.last_run = 0.0
        self.failures = 0

    def kick(self) -> None:
        """Una pantalla se acaba de (re)conectar: consultar ya."""
        self._wake.set()

    async def poll_once(self, merchant_ids: set[str] | None = None) -> int:
        """Una vuelta completa (de esos negocios; None = todos). Devuelve cuántos pagos faltantes encontró.
        Un error en una consulta no frena a las demás."""
        if not config.PEY_API_KEY:
            return 0
        async with self._lock:
            self.last_run = timeutil.now_ts()
            accounts, qrs, pushes = _targets(merchant_ids)
            found, errors = 0, 0
            async with httpx.AsyncClient(timeout=15) as client:
                for fn, ids in ((_recover_account, accounts), (_recover_qr, qrs), (_recover_push, pushes)):
                    for target in ids:
                        try:
                            found += await fn(client, target)
                        except (httpx.HTTPError, ValueError, KeyError) as e:
                            errors += 1
                            log.warning("Respaldo: no se pudo consultar %s en pey: %s", target, e)
            self.failures = self.failures + 1 if errors and errors == len(accounts) + len(qrs) + len(pushes) else 0
            if found:
                log.info("Respaldo: %d pago(s) recuperado(s) que no llegaron por webhook", found)
            return found

    def _interval(self) -> float:
        # Si pey falla (o nos limita con 429), esperamos más entre intentos
        return min(config.RECOVERY_POLL_SECONDS * (2 ** self.failures), MAX_BACKOFF_SECONDS)

    async def run(self) -> None:
        while True:
            try:
                await asyncio.wait_for(self._wake.wait(), timeout=self._interval())
            except asyncio.TimeoutError:
                pass
            self._wake.clear()
            if bus.listeners == 0 or timeutil.now_ts() - self.last_run < MIN_GAP_SECONDS:
                continue
            try:
                await self.poll_once(bus.merchants())
            except Exception:  # el ciclo nunca debe morir
                log.exception("Respaldo: error inesperado")


recovery = Recovery()
