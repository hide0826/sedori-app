import asyncio
import sys
import os

# Add the 'python' directory to the system path
sys.path.insert(0, os.path.abspath(os.path.dirname(__file__)))


# Windows aiohttp fix
if sys.platform == "win32":
    asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
import traceback

def create_app() -> FastAPI:
    app = FastAPI(title="HIRIO Sedori API", version="0.1.0")

    app.add_middleware(
        CORSMiddleware,
        allow_origins=["*"],
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )
    
    # グローバルエラーハンドラーを追加
    @app.exception_handler(Exception)
    async def global_exception_handler(request: Request, exc: Exception):
        error_trace = traceback.format_exc()
        print(f"[GLOBAL ERROR] ========== 予期しないエラー ==========")
        print(f"[GLOBAL ERROR] パス: {request.url.path}")
        print(f"[GLOBAL ERROR] メソッド: {request.method}")
        print(f"[GLOBAL ERROR] エラーメッセージ: {str(exc)}")
        print(f"[GLOBAL ERROR] エラータイプ: {type(exc).__name__}")
        print(f"[GLOBAL ERROR] トレースバック:\n{error_trace}")
        print(f"[GLOBAL ERROR] ======================================")
        return JSONResponse(
            status_code=500,
            content={"detail": f"Internal Server Error: {str(exc)}"}
        )

    @app.get("/health")
    def health():
        return {"status": "ok"}

    # ルーターのインポートと登録
    from routers.csv import router as csv_router
    from routers.ssot_rules import router as ssot_router
    from routers.repricer import router as repricer_router
    from routers.inventory import router as inventory_router

    app.include_router(csv_router)
    app.include_router(ssot_router)
    app.include_router(repricer_router)  # プレフィックスはルーター内で既に設定済み
    app.include_router(inventory_router)

    # キャッシュ問題対策
    app.openapi_schema = None

    return app

app = create_app()

if __name__ == "__main__":
    import uvicorn
    uvicorn.run("app:app", host="localhost", port=8000, reload=True)
