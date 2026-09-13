from fastapi import HTTPException

def conflict(code: str, message: str):
    raise HTTPException(status_code=409, detail={"code": code, "message": message})

def unprocessable(code: str, message: str):
    raise HTTPException(status_code=422, detail={"code": code, "message": message})

def not_found(code: str, message: str):
    raise HTTPException(status_code=404, detail={"code": code, "message": message})

def unavailable(code: str, message: str):
    raise HTTPException(status_code=503, detail={"code": code, "message": message})
