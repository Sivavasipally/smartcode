from fastapi import APIRouter, HTTPException, status
from pydantic import BaseModel, validator
from typing import Optional

router = APIRouter(tags=['users'])

class User(BaseModel):
    id: Optional[int]
    name: str
    email: str

    @validator('email')
    def validate_email(cls, v):
        if '@' not in v:
            raise ValueError('Invalid email address')
        return v

@router.post('/users/', response_model=User, status_code=status.HTTP_201_CREATED)
async def create_user(user: User):
    try:
        # user creation logic here
        return user
    except ValueError as e:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail=str(e))
