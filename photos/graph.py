"""A small Microsoft Graph client for OneDrive photos: listing with metadata, and thumbnails, nothing else.

Sign-in is the rclone remote "onedrive" (read-only scopes), because registering an app of our own needs an Azure
account. rclone keeps its token fresh whenever it runs, so before a token is due to expire this runs a cheap rclone
command and reads the renewed token back from rclone's config. Only GET requests are made, and originals are only
fetched one at a time for the few photos being shown, never the library.
"""
import json
import logging
import socket
import subprocess
import time
import urllib.error
import urllib.parse
import urllib.request
from datetime import datetime, timezone

log = logging.getLogger("photos.graph")
API = "https://graph.microsoft.com/v1.0"
REMOTE = "onedrive"

# Some home networks hand out IPv6 that can't reach Microsoft: each connection then hangs for the whole timeout before
# falling back. Try IPv4 addresses first (IPv6 still works where IPv4 doesn't exist).
_getaddrinfo = socket.getaddrinfo


def _ipv4_first(*args, **kwargs):
    return sorted(_getaddrinfo(*args, **kwargs), key=lambda a: a[0] != socket.AF_INET)


socket.getaddrinfo = _ipv4_first


class Graph:
    def __init__(self, remote: str = REMOTE):
        self.remote = remote
        self._token = None
        self._expiry = 0.0

    def _read_token(self):
        dump = json.loads(subprocess.run(["rclone", "config", "dump"], capture_output=True, text=True, check=True).stdout)
        tok = json.loads(dump[self.remote]["token"])
        self._token = tok["access_token"]
        self._expiry = datetime.fromisoformat(tok["expiry"].replace("Z", "+00:00")).timestamp()

    def token(self) -> str:
        if not self._token or self._expiry - time.time() < 300:
            self._read_token()
            if self._expiry - time.time() < 300:  # due: let rclone renew it, then read it again
                subprocess.run(["rclone", "about", f"{self.remote}:"], capture_output=True, timeout=60)
                self._read_token()
        return self._token

    def _open(self, url: str, timeout=60, auth=True):
        for attempt in range(4):
            req = urllib.request.Request(url if url.startswith("http") else API + url,
                                         headers={"Authorization": f"Bearer {self.token()}"} if auth else {})
            try:
                return urllib.request.urlopen(req, timeout=timeout)
            except urllib.error.HTTPError as e:
                if e.code in (429, 503) and attempt < 3:  # throttled: wait as asked, then try again
                    time.sleep(min(int(e.headers.get("Retry-After", "5")), 60))
                    continue
                if e.code == 401 and attempt == 0:  # token expired early: renew once
                    self._expiry = 0
                    continue
                raise
            except (urllib.error.URLError, OSError) as e:  # a dropped connection: try again shortly
                if attempt == 3:
                    raise
                log.debug("retrying after %s", e)
                time.sleep(2 * (attempt + 1))

    def get(self, url: str) -> dict:
        with self._open(url) as r:
            return json.load(r)

    def content(self, url: str, auth=True) -> bytes:
        with self._open(url, timeout=90, auth=auth) as r:
            return r.read()

    def delta(self, folder: str, link: str | None = None):
        """Everything under a folder (or only what changed since `link`): yields items, returns the next delta link."""
        url = link or (f"/me/drive/root:{urllib.parse.quote('/' + folder.strip('/'))}:/delta"
                       "?$select=id,name,size,file,image,photo,parentReference,deleted")
        while url:
            page = self.get(url)
            for item in page.get("value", []):
                yield item
            if page.get("@odata.deltaLink"):
                return page["@odata.deltaLink"]
            url = page.get("@odata.nextLink")

    def thumbnail(self, item_id: str, size: str = "large") -> bytes:
        """`large` is about 800px, for looking at faces. Bigger sizes are recompressed, so showing uses `original`."""
        return self.content(f"/me/drive/items/{item_id}/thumbnails/0/{size}/content")

    def original(self, item_id: str) -> bytes:
        """The photo file itself. Graph hands out a short-lived pre-signed link for it, which refuses a bearer token."""
        link = self.get(f"/me/drive/items/{item_id}")["@microsoft.graph.downloadUrl"]
        return self.content(link, auth=False)
