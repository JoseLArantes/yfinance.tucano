import os
from datetime import datetime
from fastapi import FastAPI, Depends, HTTPException, status
from fastapi.responses import RedirectResponse
from fastapi.middleware.cors import CORSMiddleware
from sqlalchemy.orm import Session

from app.config import settings
from app.database import engine, Base, get_db
from app.models import ApiUser
from app.routers import tickers, users, auth

# ─────────────────────────────────────────────────────────────
# 🗄️ Database Initialization & Seeding
# ─────────────────────────────────────────────────────────────
Base.metadata.create_all(bind=engine)

# ─────────────────────────────────────────────────────────────
# 🚀 FastAPI Application Setup
# ─────────────────────────────────────────────────────────────
app = FastAPI(
    title="Tucano yfinance REST API",
    description="Production-grade stock data importer and API for Brazilian B3 tickers.",
    version="1.0.0",
    debug=settings.debug
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Seed default API user at startup if database is empty
@app.on_event("startup")
def seed_default_user():
    db = Session(bind=engine)
    try:
        # Check if the default admin user exists
        admin = db.query(ApiUser).filter(ApiUser.username == settings.default_api_username).first()
        if not admin:
            print(f"Seeding default user '{settings.default_api_username}'...")
            admin = ApiUser(
                username=settings.default_api_username,
                token=settings.default_api_token
            )
            db.add(admin)
            db.commit()
            print("Default user seeded successfully.")
        else:
            # Sync token if it differs from current .env settings
            if admin.token != settings.default_api_token:
                print(f"Syncing default user '{settings.default_api_username}' token with current .env configuration...")
                admin.token = settings.default_api_token
                db.commit()
                print("Default user token synchronized.")
    except Exception as e:
        print(f"Warning: Failed to seed default user: {e}")
        db.rollback()
    finally:
        db.close()

# Include REST API Routers
app.include_router(auth.router)
app.include_router(tickers.router)
app.include_router(users.router)

@app.get("/health", tags=["health"])
def health_check():
    return {
        "status": "ok",
        "timestamp": datetime.utcnow().isoformat() + "Z"
    }

# ─────────────────────────────────────────────────────────────
# 🚀 Root Route Redirecting to OpenAPI Docs
# ─────────────────────────────────────────────────────────────
@app.get("/", include_in_schema=False)
async def root_redirect():
    return RedirectResponse(url="/docs")

# ─────────────────────────────────────────────────────────────
# 🚀 Local execution handler
# ─────────────────────────────────────────────────────────────
if __name__ == "__main__":
    import uvicorn
    uvicorn.run("app.main:app", host="0.0.0.0", port=8009, reload=True)
