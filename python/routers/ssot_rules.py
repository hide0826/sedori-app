from fastapi import APIRouter
router = APIRouter(prefix="/ssot/rules", tags=["ssot"])

@router.get("")
def list_rules():
    return {"rules": []}

@router.post("")
def append_rule(rule: dict):
    return {"ok": True, "rule": rule}
