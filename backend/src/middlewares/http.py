from uuid import uuid4

from fastapi.responses import JSONResponse
from redis.exceptions import RedisError

from src.models.database import cache


def install(app):
    @app.middleware('http')
    async def request_id(request, call_next):
        response = await call_next(request)
        response.headers['x-request-id'] = uuid4().hex
        response.headers['x-content-type-options'] = 'nosniff'
        return response

    @app.middleware('http')
    async def request_bounds(request, call_next):
        if request.headers.get('content-length', '0').isdigit() and int(request.headers.get('content-length', '0')) > 1_200_000:
            return JSONResponse({'detail': '请求超过 1.2 MB。'}, status_code=413)
        return await call_next(request)

    @app.exception_handler(ValueError)
    async def bad_input(request, error):
        return JSONResponse({'detail': str(error)}, status_code=422)

    @app.exception_handler(RedisError)
    async def cache_unavailable(request, error):
        return JSONResponse({'detail': '缓存暂不可用，请稍后重试。'}, status_code=503)
