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

    # ルーターのインポートと登録（デバッグ付き）
    try:
        from routers.csv import router as csv_router
        print(f"CSV router imported: {csv_router}")
        app.include_router(csv_router)
        print("CSV router registered")
    except Exception as e:
        print(f"CSV router error: {e}")
    
    try:
        from routers.ssot_rules import router as ssot_router
        print(f"SSOT router imported: {ssot_router}")
        app.include_router(ssot_router)
        print("SSOT router registered")
    except Exception as e:
        print(f"SSOT router error: {e}")
    
    try:
        from routers.repricer import router as repricer_router
        print(f"Repricer router imported: {repricer_router}")
        app.include_router(repricer_router)
        print("Repricer router registered")
    except Exception as e:
        print(f"Repricer router error: {e}")

    # キャッシュ問題対策
    app.openapi_schema = None

    return app

app = create_app()

if __name__ == "__main__":
    import uvicorn
    uvicorn.run("app_debug:create_app", host="127.0.0.1", port=8001, reload=True, factory=True)
