from __future__ import annotations

from json import dumps as jdumps
from typing import Any

import httpx

from .parser import RetryAfterError, TelegraphError, html_to_nodes


def _json_serialize(data: Any) -> str:
    return jdumps(data, separators=(",", ":"), ensure_ascii=False)


class Telegraph:
    """Async API client for Telegraph / Graph.org services."""

    __slots__ = ("access_token", "domain", "_client", "_owns_client")

    def __init__(
        self,
        access_token: str | None = None,
        domain: str = "graph.org",
        client: httpx.AsyncClient | None = None,
    ) -> None:
        self.access_token = access_token
        self.domain = domain
        if client is not None:
            self._client = client
            self._owns_client = False
        else:
            self._client = httpx.AsyncClient(timeout=30.0)
            self._owns_client = True

    async def close(self) -> None:
        """Close underlying HTTP client if owned."""
        if self._owns_client and not self._client.is_closed:
            await self._client.aclose()

    async def _method(self, method: str, values: dict[str, Any] | None = None, path: str = "") -> Any:
        payload = dict(values or {})
        if "access_token" not in payload and self.access_token:
            payload["access_token"] = self.access_token

        endpoint = f"https://api.{self.domain}/{method}"
        if path:
            endpoint = f"{endpoint}/{path}"

        headers = {"Content-Type": "application/x-www-form-urlencoded"}
        try:
            resp = await self._client.post(endpoint, data=payload, headers=headers)
            resp.raise_for_status()
            data = resp.json()
        except httpx.HTTPError as exc:
            raise TelegraphError(f"HTTP request failed: {exc}") from exc

        if data.get("ok"):
            return data.get("result")

        error = data.get("error")
        if isinstance(error, str) and error.startswith("FLOOD_WAIT_"):
            try:
                seconds = int(error.rsplit("_", 1)[-1])
            except ValueError:
                seconds = 5
            raise RetryAfterError(seconds)

        raise TelegraphError(str(error or "Unknown Telegraph API error"))

    async def create_account(
        self,
        short_name: str,
        author_name: str | None = None,
        author_url: str | None = None,
    ) -> dict[str, Any]:
        """Creates a new Telegraph account."""
        params: dict[str, Any] = {"short_name": short_name}
        if author_name:
            params["author_name"] = author_name
        if author_url:
            params["author_url"] = author_url

        res = await self._method("createAccount", params)
        if isinstance(res, dict) and "access_token" in res:
            self.access_token = res["access_token"]
        return res

    async def create_page(
        self,
        title: str,
        html_content: str,
        author_name: str | None = None,
        author_url: str | None = None,
        return_content: bool = False,
    ) -> dict[str, Any]:
        """Creates a new page on Telegraph."""
        nodes = html_to_nodes(html_content)
        params: dict[str, Any] = {
            "title": title,
            "content": _json_serialize(nodes),
            "return_content": "true" if return_content else "false",
        }
        if author_name:
            params["author_name"] = author_name
        if author_url:
            params["author_url"] = author_url

        return await self._method("createPage", params)

    async def edit_page(
        self,
        path: str,
        title: str,
        html_content: str,
        author_name: str | None = None,
        author_url: str | None = None,
        return_content: bool = False,
    ) -> dict[str, Any]:
        """Edits an existing Telegraph page."""
        nodes = html_to_nodes(html_content)
        params: dict[str, Any] = {
            "title": title,
            "content": _json_serialize(nodes),
            "return_content": "true" if return_content else "false",
        }
        if author_name:
            params["author_name"] = author_name
        if author_url:
            params["author_url"] = author_url

        return await self._method("editPage", values=params, path=path)

    async def get_page(self, path: str, return_content: bool = True) -> dict[str, Any]:
        """Gets info about a Telegraph page."""
        return await self._method(
            "getPage",
            values={"return_content": "true" if return_content else "false"},
            path=path,
        )

    async def get_page_list(self, offset: int = 0, limit: int = 50) -> dict[str, Any]:
        """Gets list of pages created by this account."""
        return await self._method("getPageList", {"offset": offset, "limit": limit})
