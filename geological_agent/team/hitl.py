"""Owner-scoped human-input cards; replies are bound to a saved question."""
import hmac
import os

from fastapi import HTTPException, Request


def install_input_routes(app):
    store = app.state.store

    def principal(request, *, mutation=False):
        from .server import COOKIE
        try:
            user = store.authenticate(request.cookies.get(COOKIE, ""))
        except PermissionError as exc:
            raise HTTPException(401, str(exc)) from exc
        if mutation and not hmac.compare_digest(request.headers.get("x-csrf-token", ""), user["csrf"]):
            raise HTTPException(403, "Invalid CSRF token")
        return user

    @app.get("/api/hitl/requests")
    def pending(request: Request, cid: str = ""):
        user = principal(request)
        enabled = os.environ.get("GEOTOOL_HITL", "0") == "1" and os.environ.get("GEOTOOL_TEAM_EXECUTION") == "trusted"
        items = store.pending_inputs(user["id"], cid or None, include_closed=bool(cid)) if enabled else []
        return {"enabled": enabled, "requests": [item for item in items if item["state"] == "pending"],
                "history": [item for item in items if item["state"] != "pending"]}

    @app.post("/api/hitl/requests/{request_id}/cancel")
    def cancel(request_id: str, request: Request):
        user = principal(request, mutation=True)
        try:
            store.cancel_input(user["id"], request_id)
        except KeyError as exc:
            raise HTTPException(404, "Input request not found") from exc
        except ValueError as exc:
            raise HTTPException(409, str(exc)) from exc
        return {"cancelled": True}
