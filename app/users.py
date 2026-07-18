from fastapi import APIRouter, HTTPException
from pydantic import BaseModel
from typing import List

router = APIRouter()

class User(BaseModel):
    id: int
    name: str
    email: str

@router.post("/users/")
async def create_user(user: User):
    # Implement the logic for creating a new user and storing it in the database
    # For demonstration purposes, we'll just return the created user
    return user
