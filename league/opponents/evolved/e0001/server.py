"""Small independent HTTP server factory for local adversaries; PORT selects it."""

import os

from fastapi import FastAPI, Request
import uvicorn

from game import AgentConfig, HandResult, Observation


def create_app(name, new_half, choose_action, on_hand_end=lambda result, memory: None,
               extra_action=None):
    app, memory = FastAPI(), {}

    @app.get("/")
    async def info():
        return {"participant": "Local adversarial league", "agent_name": name}

    @app.post("/new-half")
    async def reset(request: Request):
        body = await request.json()
        memory.clear()
        new_half(AgentConfig.from_dict(body.get("config", {})), memory)
        return {"ok": True}

    @app.post("/act")
    async def action(request: Request):
        body = await request.json()
        for raw in body.get("hand_results", []):
            on_hand_end(HandResult.from_dict(raw), memory)
        obs = Observation.from_dict(body["observation"])
        answer = (extra_action(obs, memory, body.get("oracle")) if extra_action
                  else choose_action(obs, memory))
        return {"action": answer.name, "hand_end_errors": []}

    @app.post("/hand-end")
    async def end(request: Request):
        for raw in (await request.json()).get("results", []):
            on_hand_end(HandResult.from_dict(raw), memory)
        return {"ok": True, "hand_end_errors": []}

    return app


def serve(app):
    uvicorn.run(app, host="127.0.0.1", port=int(os.environ.get("PORT", "5009")),
                log_level="warning", access_log=False)
