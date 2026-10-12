"""ASGI entrypoint: `uvicorn app.main:app --host 127.0.0.1 --port 8000` (run from backend/)."""
from app.api.routes import build_engine_from_env, create_app

app = create_app(build_engine_from_env())
