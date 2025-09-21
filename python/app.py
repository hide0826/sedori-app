import asyncio
asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

def create_app() -> FastAPI:
    app = FastAPI(title="HIRIO Sedori API", version="0.1.0")

    app.add_middleware(
        CORSMiddleware,
        allow_origins=["*"],
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    @app.get("/health")
    def health():
        return {"status": "ok"}

    # ルーターのインポートと登録
    from routers.csv import router as csv_router
    from routers.ssot_rules import router as ssot_router
    from routers.repricer import router as repricer_router

    app.include_router(csv_router)
    app.include_router(ssot_router)
    app.include_router(repricer_router)

    # キャッシュ問題対策
    app.openapi_schema = None

    return app

app = create_app()

if __name__ == "__main__":
    import uvicorn
    uvicorn.run("app:app", host="127.0.0.1", port=8000, reload=True)
