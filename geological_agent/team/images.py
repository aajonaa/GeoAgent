"""Authenticated image previews. Never serve uploaded HTML/SVG as executable content."""
from fastapi import HTTPException, Request
from fastapi.responses import Response
from ..imaging import preview_bytes
from ..svg_preview import svg_preview, SVG_CSP
from ..tools import ToolFailure
from .protocol import relative_name


def install_image_routes(app, auth, store):
    from .scientific_images import install_scientific_image_routes
    install_scientific_image_routes(app, auth, store)

    @app.get("/api/conversations/{cid}/image")
    def preview(cid: str, request: Request, name: str, generation: str = ""):
        uid = auth(request)["id"]
        name = relative_name(name)
        files = store.files(uid, cid, generation or None)
        if name not in files:
            raise HTTPException(404, "Image not found")
        try:
            is_svg = name.lower().endswith(".svg")
            if is_svg:
                raw = svg_preview(files[name])
            else:
                raw, _ = preview_bytes(files[name])
        except ToolFailure as exc:
            raise HTTPException(422, str(exc)) from exc
        except ImportError as exc:
            raise HTTPException(503, "Image dependencies are not installed on this server") from exc
        return Response(raw, media_type="image/svg+xml" if is_svg else "image/png", headers={
            "Cache-Control": "private, no-store", "X-Content-Type-Options": "nosniff",
            "Content-Security-Policy": SVG_CSP if is_svg else "default-src 'none'; sandbox",
            "X-GeoAgent-Preview": "validated-static-svg" if is_svg else "raster-preview",
            "Content-Disposition": "inline; filename=preview.svg" if is_svg else "inline; filename=preview.png"})
