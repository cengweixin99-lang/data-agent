from typing import Optional

import httpx

from app.conf.app_config import EmbeddingConfig, app_config


class LocalTEIEmbeddings:
    def __init__(self, base_url: str):
        self.base_url = base_url.rstrip('/')

    async def aembed_documents(self, texts: list[str]) -> list[list[float]]:
        async with httpx.AsyncClient(timeout=120, trust_env=False) as client:
            response = await client.post(
                f'{self.base_url}/embed',
                json={'inputs': texts},
            )
            response.raise_for_status()
            return response.json()

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