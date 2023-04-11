"""Crack app."""
from sanic import Sanic, text

app = Sanic("crack")


@app.get("/")
async def handler(request):
    """Basic handler."""
    return text(str(request.id))
