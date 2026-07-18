from fastapi import FastAPI
from pydantic import BaseModel

app = FastAPI()

class GaneshaRequest(BaseModel):
    name: str
    message: str

@app.post("/ganesha")
def ganesha_endpoint(request: GaneshaRequest):
    return {"message": f"Hello, {request.name}!"}
