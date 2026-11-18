"""Preserve the original client; fix only global version routing and plain-text stop ACK."""
import base64
import json
import time
import urllib.error
import urllib.request
from client import APIError, Client as OriginalClient, utc


class Client(OriginalClient):
    def request(self, method, endpoint, data=None, instance=True):
        if method == "GET" and endpoint == "version":
            return super().request(method, endpoint, data, instance=False)
        if not (method == "PUT" and endpoint == "stop"):
            return super().request(method, endpoint, data, instance=instance)
        if not self.testid:
            raise APIError("No testid for stop")
        # Pinned boptestRoutes.js uses res.sendStatus(200): response body is literal OK.
        url = self.base + "/stop/" + self.testid
        self.sequence += 1
        started = time.monotonic()
        raw = b""
        record = {"sequence": self.sequence, "url": url, "method": method,
                  "request": data, "sent_utc": utc(), "attempt": 1,
                  "transport_adapter": "compat_v1"}
        try:
            request = urllib.request.Request(url, data=json.dumps(data or {}).encode(),
                method="PUT", headers={"Content-Type": "application/json"})
            with self.opener(request, timeout=self.timeout) as response:
                raw = response.read()
                record["http_status"] = response.status
            if record["http_status"] != 200 or raw.strip() != b"OK":
                raise APIError("Unexpected stop acknowledgement; cleanup not confirmed")
            return {"acknowledgement": "OK"}
        except Exception as exc:
            if isinstance(exc, urllib.error.HTTPError):
                raw = exc.read()
                record["http_status"] = exc.code
            record["error"] = f"{type(exc).__name__}: {exc}"
            raise APIError(record["error"]) from exc
        finally:
            record.update(received_utc=utc(), elapsed_seconds=time.monotonic()-started,
                          raw_body_base64=base64.b64encode(raw).decode())
            with (self.directory/"raw_api.jsonl").open("a", encoding="utf-8") as stream:
                stream.write(json.dumps(record, allow_nan=False)+"\n")
