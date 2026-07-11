import asyncio
from typing import Optional

import httpx

from app.conf.app_config import EmbeddingConfig, app_config


class LocalTEIEmbeddings:
    def __init__(self, base_url: str):
        self.base_url = base_url.rstrip('/')
        self._cache: dict[str, list[float]] = {}
        self._inflight: dict[str, asyncio.Future[list[float]]] = {}
        self._lock = asyncio.Lock()

    async def _request_embeddings(self, texts: list[str]) -> list[list[float]]:
        async with httpx.AsyncClient(timeout=120, trust_env=False) as client:
            response = await client.post(
                f'{self.base_url}/embed',
                json={'inputs': texts},
            )
            response.raise_for_status()
            embeddings = response.json()
            if len(embeddings) != len(texts):
                raise RuntimeError(
                    f'Embedding service returned {len(embeddings)} vectors for {len(texts)} texts'
                )
            return embeddings

    async def _resolve_batch(
        self,
        texts: list[str],
        futures: list[asyncio.Future[list[float]]],
    ) -> None:
        try:
            embeddings = await self._request_embeddings(texts)
        except Exception as exc:
            async with self._lock:
                for text, future in zip(texts, futures):
                    self._inflight.pop(text, None)
                    if not future.done():
                        future.set_exception(exc)
            return

        async with self._lock:
            for text, embedding, future in zip(texts, embeddings, futures):
                self._cache[text] = embedding
                self._inflight.pop(text, None)
                if not future.done():
                    future.set_result(embedding)

    async def aembed_documents(self, texts: list[str]) -> list[list[float]]:
        if not texts:
            return []

        loop = asyncio.get_running_loop()
        futures: list[asyncio.Future[list[float]]] = []
        batch_texts: list[str] = []
        batch_futures: list[asyncio.Future[list[float]]] = []

        async with self._lock:
            for text in texts:
                cached = self._cache.get(text)
                if cached is not None:
                    future = loop.create_future()
                    future.set_result(cached)
                else:
                    future = self._inflight.get(text)
                    if future is None:
                        future = loop.create_future()
                        self._inflight[text] = future
                        batch_texts.append(text)
                        batch_futures.append(future)
                futures.append(future)

        if batch_texts:
            asyncio.create_task(self._resolve_batch(batch_texts, batch_futures))

        return await asyncio.gather(*futures)

    async def aembed_query(self, text: str) -> list[float]:
        embeddings = await self.aembed_documents([text])
        return embeddings[0]


class EmbeddingClientManager:
    def __init__(self, config: EmbeddingConfig):
        self.client: Optional[LocalTEIEmbeddings] = None
        self.config = config

    def _get_url(self):
        return f'http://{self.config.host}:{self.config.port}'

    def init(self):
        self.client = LocalTEIEmbeddings(self._get_url())


embedding_client_manager = EmbeddingClientManager(app_config.embedding)