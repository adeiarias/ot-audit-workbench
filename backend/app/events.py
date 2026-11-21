"""Pub/sub en memoria por campaña, para empujar cambios a la UI por WebSocket."""
import asyncio
from collections import defaultdict

_subscribers: dict[int, set[asyncio.Queue]] = defaultdict(set)


def subscribe(campaign_id: int) -> asyncio.Queue:
    q: asyncio.Queue = asyncio.Queue(maxsize=100)
    _subscribers[campaign_id].add(q)
    return q


def unsubscribe(campaign_id: int, q: asyncio.Queue) -> None:
    _subscribers[campaign_id].discard(q)
    if not _subscribers[campaign_id]:
        del _subscribers[campaign_id]


def publish(campaign_id: int, event: dict) -> None:
    for q in list(_subscribers.get(campaign_id, ())):
        try:
            q.put_nowait(event)
        except asyncio.QueueFull:
            pass  # cliente lento: la UI se resincroniza con el siguiente evento
