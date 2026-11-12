import asyncio
import logging
import time
from contextlib import asynccontextmanager
from pathlib import Path
from fastapi import Depends, FastAPI, Request, Response
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from fastapi.staticfiles import StaticFiles
from starlette.exceptions import HTTPException
from app.core.config import settings
from app.core.database import SessionLocal
from app.core.errors import AppError
from app.core.migrations import migrate
from app.core.tokens import purge_expired
from app.core.middleware import security_headers
from app.modules.users import router as users_router, service as users_service
from app.modules.products import router as products_router
from app.modules.orders import router as orders_router
from app.modules.notifications import router as notifications_router
from app.modules.dashboard import router as dashboard_router
from app.integrations.inventory.gateway import configure_gateway, close_gateway

log=logging.getLogger(__name__)

def _purge_expired_tokens():
    with SessionLocal() as db:return purge_expired(db)

async def purge_revoked_tokens_loop():
    """Periodically delete expired revoked-token rows (moved off the request path)."""
    while True:
        await asyncio.sleep(settings.revoked_purge_interval_seconds)
        try:
            removed=await asyncio.to_thread(_purge_expired_tokens)
            if removed:log.info('Purged %s expired revoked tokens',removed)
        except Exception:log.exception('Revoked token purge failed')

@asynccontextmanager
async def lifespan(app:FastAPI):
    configure_gateway()
    for attempt in range(20):
        try:
            migrate()
            break
        except Exception:
            if attempt==19:raise
            log.warning('Database not ready; retrying startup (%s/20)',attempt+1)
            time.sleep(2)
    with SessionLocal() as db: users_service.seed_admin(db)
    purge_task=asyncio.create_task(purge_revoked_tokens_loop())
    yield
    purge_task.cancel()
    close_gateway()

app=FastAPI(title='Trendova API v1',version='v1',lifespan=lifespan,openapi_tags=[{'name':name} for name in ('health','auth','users','categories','products','favorites','orders','notifications','dashboard')])
app.middleware('http')(security_headers)
if settings.gzip_enabled:
    from starlette.middleware.gzip import GZipMiddleware
    app.add_middleware(GZipMiddleware,minimum_size=1000)
    from app.core.middleware import MergeVary
    app.add_middleware(MergeVary)

if settings.db_query_count:
    from app.core.query_counter import count_queries
    @app.middleware('http')
    async def query_count_header(request:Request,call_next):
        from app.integrations.inventory.gateway import start_rpc_count
        box=start_rpc_count()
        with count_queries() as log:
            response=await call_next(request)
        response.headers['X-DB-Query-Count']=str(log.count)
        response.headers['X-Inventory-Rpc-Calls']=str(box[0])
        return response

def error_response(status,code,message,details=None,headers=None):
    body={'error':{'code':code,'message':message,'details':details if details is not None else []}}
    return JSONResponse(body,status_code=status,headers=headers)

@app.exception_handler(AppError)
async def app_error(_:Request,e:AppError):return error_response(e.status_code,e.code,e.message,e.details,e.headers)
@app.exception_handler(HTTPException)
async def http_error(_:Request,e:HTTPException):return error_response(e.status_code,'HTTP_ERROR',str(e.detail),headers=e.headers)
@app.exception_handler(RequestValidationError)
async def validation_error(_:Request,e:RequestValidationError):
    details=[{'loc':list(x['loc']),'msg':x['msg'],'type':x['type']} for x in e.errors()]
    return error_response(422,'VALIDATION_ERROR','Request validation failed',details)
@app.exception_handler(Exception)
async def unexpected_error(_:Request,e:Exception):
    log.exception('Unhandled request error')
    return error_response(500,'INTERNAL_ERROR','An unexpected error occurred')

@app.get('/health',tags=['health'],summary='Health check',description='Application is serving requests.',response_model=dict)
def health():return {'status':'ok'}

from app.core.dependencies import admin as _admin_dep
from app.core import cache as _cache, redis as _rds
@app.get('/internal/cache-stats',tags=['health'],summary='Cache counters (admin only)',description='In-process hit/miss/bypass/fill counters of this worker plus Redis availability.')
def cache_stats(_=Depends(_admin_dep)):
    return {'enabled':_cache.enabled(),'redis_up':_rds.ping(),**_cache.stats()}
@app.post('/internal/cache-stats/reset',tags=['health'],summary='Reset cache counters (admin only)',status_code=204,response_model=None)
def cache_stats_reset(_=Depends(_admin_dep)):
    _cache.reset_stats();return Response(status_code=204)

prefix='/api/v1'
for router in (users_router.auth_router,users_router.router,products_router.categories_router,products_router.router,products_router.favorites_router,orders_router.router,notifications_router.router,dashboard_router.router):
    app.include_router(router,prefix=prefix)
Path(settings.upload_dir).mkdir(parents=True,exist_ok=True)
app.mount('/media',StaticFiles(directory=settings.upload_dir),name='media')
