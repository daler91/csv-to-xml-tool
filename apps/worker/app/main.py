from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from .routes import health, preview, convert, validate

app = FastAPI(title="CSV-to-XML Worker", version="1.1.0")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(health.router)
app.include_router(preview.router)
app.include_router(convert.router)
app.include_router(validate.router)
