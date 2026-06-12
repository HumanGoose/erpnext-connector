from collections.abc import AsyncGenerator
from contextlib import asynccontextmanager

from fastapi import FastAPI

from connector.api.erpnext_webhooks import router as erpnext_webhooks_router
from connector.api.health import router as health_router
from connector.api.shopify_webhooks import router as shopify_webhooks_router
from connector.api.status import router as status_router
from connector.db import init_db


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncGenerator[None, None]:
    init_db()
    yield


app = FastAPI(title="ERPNext-Shopify Connector", lifespan=lifespan)
app.include_router(health_router)
app.include_router(status_router)
app.include_router(shopify_webhooks_router)
app.include_router(erpnext_webhooks_router)
