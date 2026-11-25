"""SSE: avisar a las pantallas de un negocio (y solo a las de ese negocio).

Cada suscripción es de un negocio y, si es una bocina vinculada, de una tienda: la bocina de una tienda
no anuncia los pagos de otra. La App del dueño (store=None) ve todas sus tiendas.
"""

import asyncio


class Broadcaster:
    def __init__(self) -> None:
        self.subs: dict[asyncio.Queue, tuple[str, str | None]] = {}

    def subscribe(self, merchant_id: str, store_id: str | None = None) -> asyncio.Queue:
        q: asyncio.Queue = asyncio.Queue(maxsize=100)
        self.subs[q] = (merchant_id, store_id)
        return q

    def unsubscribe(self, q: asyncio.Queue) -> None:
        self.subs.pop(q, None)

    @property
    def listeners(self) -> int:
        return len(self.subs)

    def merchants(self) -> set[str]:
        """Negocios con al menos una pantalla abierta (el respaldo solo consulta a esos)."""
        return {m for m, _ in self.subs.values()}

    async def publish(self, event: dict, merchant_id: str | None, store_id: str | None = None) -> None:
        if not merchant_id:
            return
        for q, (m, s) in list(self.subs.items()):
            if m != merchant_id or (s and store_id and s != store_id):
                continue
            try:
                q.put_nowait(event)
            except asyncio.QueueFull:
                pass


bus = Broadcaster()
