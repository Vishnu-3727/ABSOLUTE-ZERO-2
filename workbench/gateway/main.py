"""Workbench API Gateway — the single boundary between UI and OS.

REST for reads/commands, WebSocket for the live event stream, replay from
the real Communication log. Run:

    cd workbench/gateway && python -m uvicorn main:app --port 8777

The UI never reaches past this file.
"""
import asyncio
import os
import tempfile

from fastapi import FastAPI, WebSocket, WebSocketDisconnect
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from pydantic import BaseModel

from session import OsSession

UI = os.path.join(os.path.dirname(os.path.abspath(__file__)), "ui.html")

VAULT = os.environ.get("AZ_VAULT",
                       os.path.join(tempfile.gettempdir(), "az-workbench-vault"))

app = FastAPI(title="ABSOLUTE-ZERO Workbench Gateway")
app.add_middleware(CORSMiddleware, allow_origins=["http://localhost:3000"],
                   allow_methods=["*"], allow_headers=["*"])

session = None
_ws_clients = set()
_loop = None


@app.on_event("startup")
def _boot():
    global session, _loop
    _loop = asyncio.get_event_loop()
    # fresh vault per boot keeps the demo deterministic; point AZ_VAULT at a
    # persistent dir to keep history across boots
    import shutil
    shutil.rmtree(VAULT, ignore_errors=True)
    session = OsSession(VAULT)
    session.add_listener(_broadcast)


@app.on_event("shutdown")
def _halt():
    if session is not None:
        session.close()


def _broadcast(batch):
    if not batch or _loop is None:
        return
    for client in list(_ws_clients):
        for event in batch:
            asyncio.run_coroutine_threadsafe(client.send_json(event), _loop)


class SubmitRequest(BaseModel):
    intent: str
    goals: list[str] = []


@app.get("/", include_in_schema=False)
def ui():
    return FileResponse(UI, media_type="text/html")


@app.get("/az-logo.png", include_in_schema=False)
@app.get("/favicon.ico", include_in_schema=False)
def logo():
    return FileResponse(os.path.join(os.path.dirname(UI), "az-logo.png"),
                        media_type="image/png")


@app.get("/api/system")
def system():
    return session.system_overview()


@app.get("/api/requests")
def requests():
    return [session.describe_request(rid) for rid in session.requests]


@app.get("/api/requests/{rid}")
def request_detail(rid: str):
    return session.describe_request(rid)


@app.post("/api/requests")
def submit(body: SubmitRequest):
    return session.submit_request(body.intent, body.goals)


@app.get("/api/events")
def events(after: int = 0, limit: int = 500):
    return [e for e in session.events if e["seq"] > after][:limit]


@app.get("/api/bus/topics")
def topics():
    return session.topics


@app.get("/api/storage")
def storage():
    return session.storage_namespaces()


@app.get("/api/storage/read")
def storage_read(key: str):
    namespace = key.split("/", 1)[0]
    data = session.store.namespace(namespace).read(key)
    return {"key": key, "bytes": len(data),
            "preview": data[:2000].decode("utf-8", errors="replace")}


@app.get("/api/replay/{topic:path}")
def replay(topic: str):
    return session.replay_topic(topic)


@app.get("/api/kernel/log")
def kernel_log(limit: int = 500):
    return session.kernel.log[-limit:]


@app.websocket("/ws/events")
async def ws_events(socket: WebSocket):
    await socket.accept()
    _ws_clients.add(socket)
    try:
        while True:
            await socket.receive_text()  # pings; server pushes independently
    except WebSocketDisconnect:
        _ws_clients.discard(socket)
