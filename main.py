import uuid

from fastapi import FastAPI, Request

from app.api.routers.query_router import query_router
from app.core.lifespan import lifespan
from app.core.context import request_id_ctx_var
app = FastAPI(lifespan=lifespan)
app.include_router(query_router)

# 添加中间件，在每个请求中生成唯一的 request_id
@app.middleware("http")
async def add_process_time_header(request: Request, call_next):
    # 调用路径函数之前
    request_id_ctx_var.set(uuid.uuid4())
    # 调用路径函数
    response = await call_next(request)
    # 调用路径函数之后
    return response