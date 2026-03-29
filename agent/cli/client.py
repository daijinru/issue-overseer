"""MangoClient — HTTP wrapper for the Mango REST API."""

from __future__ import annotations

import sys
from typing import Any

import httpx

from agent.cli.output import print_error


class MangoClient:
    """Synchronous HTTP client for the Mango server API."""

    def __init__(self, base_url: str) -> None:
        self.base_url = base_url.rstrip("/")
        self._client = httpx.Client(base_url=self.base_url, timeout=30.0)

    def close(self) -> None:
        self._client.close()

    # ── Internal helpers ────────────────────────────────────────────

    def _request(
        self,
        method: str,
        path: str,
        *,
        json: dict | None = None,
        params: dict | None = None,
        expect_status: int | tuple[int, ...] | None = None,
    ) -> httpx.Response:
        """Make an HTTP request with unified error handling."""
        try:
            resp = self._client.request(method, path, json=json, params=params)
        except httpx.ConnectError:
            print_error(
                f"无法连接到 Mango 服务器 ({self.base_url})。"
                f"\n  请确认 `mango serve` 已启动。"
            )
            sys.exit(1)
        except httpx.TimeoutException:
            print_error("请求超时，请检查服务器状态。")
            sys.exit(1)

        if expect_status:
            expected = expect_status if isinstance(expect_status, tuple) else (expect_status,)
            if resp.status_code in expected:
                return resp

        if resp.status_code == 404:
            detail = _extract_detail(resp)
            print_error(detail or "资源不存在")
            sys.exit(1)
        if resp.status_code == 409:
            detail = _extract_detail(resp)
            print_error(detail or "状态冲突")
            sys.exit(1)
        if resp.status_code == 422:
            detail = _extract_detail(resp)
            print_error(detail or "请求参数错误")
            sys.exit(1)
        if resp.status_code >= 400:
            detail = _extract_detail(resp)
            print_error(f"服务器错误: {resp.status_code} {detail}")
            sys.exit(1)

        return resp

    def _get(self, path: str, **kwargs: Any) -> httpx.Response:
        return self._request("GET", path, **kwargs)

    def _post(self, path: str, **kwargs: Any) -> httpx.Response:
        return self._request("POST", path, **kwargs)

    def _patch(self, path: str, **kwargs: Any) -> httpx.Response:
        return self._request("PATCH", path, **kwargs)

    def _put(self, path: str, **kwargs: Any) -> httpx.Response:
        return self._request("PUT", path, **kwargs)

    def _delete(self, path: str, **kwargs: Any) -> httpx.Response:
        return self._request("DELETE", path, expect_status=204, **kwargs)

    # ── API methods ─────────────────────────────────────────────────

    def health(self) -> dict:
        """GET /api/health"""
        return self._get("/api/health").json()

    def create_issue(
        self,
        title: str,
        description: str = "",
        workspace: str | None = None,
        priority: str | None = None,
    ) -> dict:
        """POST /api/issues"""
        body: dict[str, Any] = {"title": title, "description": description}
        if workspace:
            body["workspace"] = workspace
        if priority:
            body["priority"] = priority
        return self._post("/api/issues", json=body, expect_status=201).json()

    def list_issues(
        self,
        status: str | None = None,
        priority: str | None = None,
    ) -> list[dict]:
        """GET /api/issues"""
        params: dict[str, str] = {}
        if status:
            params["status"] = status
        if priority:
            params["priority"] = priority
        return self._get("/api/issues", params=params).json()

    def get_issue(self, issue_id: str) -> dict:
        """GET /api/issues/{id}"""
        return self._get(f"/api/issues/{issue_id}").json()

    def edit_issue(
        self,
        issue_id: str,
        title: str | None = None,
        description: str | None = None,
        priority: str | None = None,
    ) -> dict:
        """PATCH /api/issues/{id}"""
        body: dict[str, Any] = {}
        if title is not None:
            body["title"] = title
        if description is not None:
            body["description"] = description
        if priority is not None:
            body["priority"] = priority
        return self._patch(f"/api/issues/{issue_id}", json=body).json()

    def delete_issue(self, issue_id: str) -> None:
        """DELETE /api/issues/{id}"""
        self._delete(f"/api/issues/{issue_id}")

    def run_issue(self, issue_id: str) -> dict:
        """POST /api/issues/{id}/run"""
        return self._post(f"/api/issues/{issue_id}/run", expect_status=202).json()

    def cancel_issue(self, issue_id: str) -> dict:
        """POST /api/issues/{id}/cancel"""
        return self._post(f"/api/issues/{issue_id}/cancel").json()

    def retry_issue(
        self,
        issue_id: str,
        instruction: str | None = None,
        workspace: str | None = None,
    ) -> dict:
        """POST /api/issues/{id}/retry"""
        body: dict[str, Any] = {}
        if instruction:
            body["human_instruction"] = instruction
        if workspace:
            body["workspace"] = workspace
        return self._post(
            f"/api/issues/{issue_id}/retry", json=body, expect_status=202
        ).json()

    def plan_issue(self, issue_id: str) -> dict:
        """POST /api/issues/{id}/plan"""
        return self._post(f"/api/issues/{issue_id}/plan", expect_status=202).json()

    def get_spec(self, issue_id: str) -> dict:
        """GET /api/issues/{id} — returns issue with spec field."""
        return self.get_issue(issue_id)

    def update_spec(self, issue_id: str, spec: str) -> dict:
        """PUT /api/issues/{id}/spec"""
        return self._put(f"/api/issues/{issue_id}/spec", json={"spec": spec}).json()

    def reject_spec(self, issue_id: str) -> dict:
        """POST /api/issues/{id}/reject-spec"""
        return self._post(f"/api/issues/{issue_id}/reject-spec").json()

    def complete_issue(self, issue_id: str) -> dict:
        """POST /api/issues/{id}/complete"""
        return self._post(f"/api/issues/{issue_id}/complete").json()

    def get_logs(self, issue_id: str) -> list[dict]:
        """GET /api/issues/{id}/logs"""
        return self._get(f"/api/issues/{issue_id}/logs").json()

    def get_steps(self, issue_id: str) -> list[dict]:
        """GET /api/issues/{id}/steps"""
        return self._get(f"/api/issues/{issue_id}/steps").json()

    def stream_events(self, issue_id: str) -> httpx.Response:
        """GET /api/issues/{id}/stream — returns a streaming response.

        The caller is responsible for consuming the stream via
        ``stream.consume_sse_stream(response, issue_id)``.
        """
        try:
            return self._client.stream(
                "GET", f"/api/issues/{issue_id}/stream"
            )
        except httpx.ConnectError:
            print_error(
                f"无法连接到 Mango 服务器 ({self.base_url})。"
                f"\n  请确认 `mango serve` 已启动。"
            )
            sys.exit(1)


def _extract_detail(resp: httpx.Response) -> str:
    """Try to extract a detail message from an error response."""
    try:
        body = resp.json()
        if isinstance(body, dict):
            detail = body.get("detail", "")
            if isinstance(detail, str):
                return detail
            # FastAPI validation errors
            if isinstance(detail, list):
                return "; ".join(
                    d.get("msg", str(d)) for d in detail if isinstance(d, dict)
                )
    except Exception:
        pass
    return resp.text[:200]
