"""Synchronous client for the simplified Issue API."""

from __future__ import annotations

import sys

import httpx

from agent.cli.output import print_error


class MangoClient:
    def __init__(self, base_url: str) -> None:
        self.base_url = base_url.rstrip("/")
        self._client = httpx.Client(base_url=self.base_url, timeout=30.0)

    def close(self) -> None:
        self._client.close()

    def _request(self, method: str, path: str, **kwargs) -> httpx.Response:
        try:
            response = self._client.request(method, path, **kwargs)
        except (httpx.ConnectError, httpx.TimeoutException) as exc:
            print_error(f"无法连接到 Mango 服务器: {exc}")
            raise SystemExit(1) from exc
        if response.status_code >= 400:
            print_error(_extract_detail(response) or f"HTTP {response.status_code}")
            raise SystemExit(1)
        return response

    def health(self) -> dict:
        return self._request("GET", "/api/health").json()

    def create_issue(self, content: str, project: str) -> dict:
        return self._request(
            "POST", "/api/issues", json={"content": content, "project": project}
        ).json()

    def list_issues(self, status: str | None = None) -> list[dict]:
        params = {"status": status} if status else None
        return self._request("GET", "/api/issues", params=params).json()

    def get_issue(self, issue_id: str) -> dict:
        return self._request("GET", f"/api/issues/{issue_id}").json()

    def delete_issue(self, issue_id: str) -> None:
        self._request("DELETE", f"/api/issues/{issue_id}")

    def run_issue(self, issue_id: str) -> dict:
        return self._request("POST", f"/api/issues/{issue_id}/run").json()

    def cancel_issue(self, issue_id: str) -> dict:
        return self._request("POST", f"/api/issues/{issue_id}/cancel").json()

    def get_logs(self, issue_id: str) -> list[dict]:
        return self._request("GET", f"/api/issues/{issue_id}/logs").json()

    def get_steps(self, issue_id: str) -> list[dict]:
        return self._request("GET", f"/api/issues/{issue_id}/steps").json()


def _extract_detail(response: httpx.Response) -> str:
    try:
        detail = response.json().get("detail", "")
        return detail if isinstance(detail, str) else str(detail)
    except Exception:
        return response.text[:200]
