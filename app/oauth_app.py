from fastapi import FastAPI

from app.oauth_routes import oauth_router


oauth_app = FastAPI()
oauth_app.include_router(oauth_router)
