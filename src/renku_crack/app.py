"""Crack app."""
from sanic import Sanic, text

app = Sanic("renku_crack")


@app.get("/")
async def handler(request):
    """Basic handler."""
    return text(str(request.id))
