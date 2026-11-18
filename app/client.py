"""BOPTEST v0.9 REST client. TLS verified; mutations are never retried."""
from __future__ import annotations
import base64
import json
import time
import urllib.error
import urllib.request
from datetime import datetime, timezone
from pathlib import Path


def utc():
    return datetime.now(timezone.utc).isoformat()


class APIError(RuntimeError):
    pass


class Client:
    def __init__(self, base="https://api.boptest.net", evidence="evidence", timeout=20,
                 opener=None, read_retries=1):
        self.base = base.rstrip("/")
        self.directory = Path(evidence)
        self.directory.mkdir(parents=True, exist_ok=True)
        self.timeout = timeout
        self.opener = opener or urllib.request.urlopen
        self.read_retries = read_retries
        self.testid = None
        self.deployment_uncertain = False
        self.sequence = 0

    def request(self, method, endpoint, data=None, instance=True):
        if instance and not self.testid:
            raise APIError("No deployed test instance")
        url = self.base + "/" + endpoint.strip("/")
        if instance:
            url += "/" + self.testid
        attempts = 1 + (self.read_retries if method == "GET" else 0)
        for attempt in range(attempts):
            self.sequence += 1
            sent = utc()
            started = time.monotonic()
            raw = b""
            record = {"sequence": self.sequence, "url": url, "method": method,
                      "request": data, "sent_utc": sent, "attempt": attempt + 1}
            try:
                body = None if data is None else json.dumps(data).encode()
                request = urllib.request.Request(url, data=body, method=method,
                                                headers={"Content-Type": "application/json"})
                with self.opener(request, timeout=self.timeout) as response:
                    raw = response.read()
                    record["http_status"] = response.status
                result = json.loads(raw)
                if isinstance(result, dict) and "status" in result:
                    if result["status"] != 200:
                        raise APIError(str(result))
                    return result.get("payload")
                return result
            except Exception as exc:
                if isinstance(exc, urllib.error.HTTPError):
                    raw = exc.read()
                    record["http_status"] = exc.code
                record["error"] = f"{type(exc).__name__}: {exc}"
                if attempt + 1 == attempts:
                    raise APIError(record["error"]) from exc
                time.sleep(0.25)
            finally:
                record.update(received_utc=utc(), elapsed_seconds=time.monotonic()-started,
                              raw_body_base64=base64.b64encode(raw).decode())
                with (self.directory / "raw_api.jsonl").open("a", encoding="utf-8") as stream:
                    stream.write(json.dumps(record, allow_nan=False) + "\n")

    def deploy(self):
        self.deployment_uncertain = True
        result = self.request("POST", "testcases/bestest_air/select", {}, instance=False)
        if not isinstance(result, dict) or not isinstance(result.get("testid"), str):
            raise APIError("Deployment response has no testid")
        self.testid = result["testid"]
        self.deployment_uncertain = False
        return self.testid

    def discover(self):
        version = self.request("GET", "version")
        if not isinstance(version, dict) or version.get("version") != "0.9.0":
            raise APIError(f"Expected 0.9.0; received {version!r}. Do not silently change versions.")
        metadata = {"endpoint": self.base, "testid": self.testid, "version": version}
        for name in ("name", "measurements", "inputs", "forecast_points", "step", "scenario"):
            metadata[name] = self.request("GET", name)
        if metadata["name"].get("name") != "bestest_air":
            raise APIError("Wrong test case")
        (self.directory / "runtime_metadata.json").write_text(
            json.dumps(metadata, indent=2), encoding="utf-8")
        return metadata

    def stop(self):
        if self.deployment_uncertain and self.testid is None:
            raise APIError("Deployment response was lost or invalid; testid unknown, cleanup unconfirmed. No retry.")
        if self.testid is not None:
            self.request("PUT", "stop", {})
            self.testid = None
