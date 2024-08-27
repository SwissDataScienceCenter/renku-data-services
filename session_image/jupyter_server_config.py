import os
from urllib.parse import urljoin

c.ServerApp.ip="0.0.0.0"
c.ServerApp.port = 8888
c.ServerApp.base_url = os.environ.get("RENKU_BASE_URL_PATH", "/")
c.ServerApp.token = ""
c.ServerApp.password = ""
c.ServerApp.allow_remote_access=True
c.ContentsManager.allow_hidden=True
# base_url = os.environ.get("RENKU_BASE_URL", "http://127.0.0.1")
# c.ServerApp.allow_origin = urljoin(base_url, "/").rstrip("/")
c.ServerApp.allow_origin = '*'
