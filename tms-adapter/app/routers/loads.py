"""POST /loads/search (LOAD_QUERY) and POST /loads/get (LOAD_GET).

Both return 200 + a status field. `max_buy` is stripped from every response
by the mappers; on /loads/get the ceiling is captured server-side into the
load-economics cache so /offers/evaluate can read it without ever exposing it.
"""
from __future__ import annotations

from fastapi import APIRouter, Depends, Request

from app.deps import get_commands, get_load_economics, require_bearer
from app.mappers import bridge_equipment_to_tms, map_load_detail, map_load_summary
from app.schemas import GetLoadRequest, SearchLoadsRequest

router = APIRouter(tags=["loads"], dependencies=[Depends(require_bearer)])

MAX_LOADS_RETURNED = 3  # find-loads pitches the best few; never the whole board


def _build_query(body: SearchLoadsRequest) -> dict:
    f: dict[str, object] = {}
    if body.origin_state:
        f["ORIG_STATE"] = body.origin_state.upper()
    if body.origin_city:
        f["ORIG_CITY"] = body.origin_city
    if body.destination_state:
        f["DEST_STATE"] = body.destination_state.upper()
    if body.destination_city:
        f["DEST_CITY"] = body.destination_city
    eq = bridge_equipment_to_tms(body.equipment_type)
    if eq:
        f["EQTYPE"] = eq
    return f


@router.post("/loads/search")
async def search_loads(body: SearchLoadsRequest, commands=Depends(get_commands)):
    filters = _build_query(body)
    if not filters:
        return {"status": "invalid_request", "error": "at least one lane/equipment filter required"}
    filters["MAX_RESULTS"] = 25  # fetch a good set; we pitch the top few
    records = await commands.load_query(**filters)  # TMSError/TMSFaultError -> handlers
    # Only pitch loads still OPEN on the board. Booking writes to the real TMS, so a load that
    # is already covered can never be booked — offering it would just dead-end the call at book
    # time. Filter to bookable BEFORE taking the top few, so a covered load doesn't use up a
    # pitch slot. (map_load_summary maps the TMS "OPEN" status to "available".)
    bookable = [s for s in (map_load_summary(r) for r in records) if s["status"] == "available"]
    return {"status": "ok", "loads": bookable[:MAX_LOADS_RETURNED]}


@router.post("/loads/get")
async def get_load(body: GetLoadRequest, request: Request, commands=Depends(get_commands),
                   economics: dict = Depends(get_load_economics)):
    record = await commands.load_get(body.load_id)  # TMSError NOT_FOUND/UNKNOWN_LOAD -> handler -> not_found
    # Capture the hidden ceiling SERVER-SIDE for /offers/evaluate; never serialized out.
    if record.get("MAX_BUY") is not None:
        economics[str(record.get("LOAD_ID")).strip()] = {
            "max_buy": record["MAX_BUY"],
            "posted_rate": record.get("RATE"),
        }
    return {"status": "found", "load": map_load_detail(record)}
