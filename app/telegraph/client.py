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

    async def __aenter__(self) -> Telegraph:
        return self

    async def __aexit__(self, exc_type: Any, exc_val: Any, exc_tb: Any) -> None:
        await self.close()

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
            if resp.status_code == 429:
                retry_after = int(resp.headers.get("Retry-After", 5))
                raise RetryAfterError(retry_after)
            resp.raise_for_status()
            data = resp.json()
        except RetryAfterError:
            raise
        except httpx.HTTPError as exc:
            raise TelegraphError(f"HTTP request failed: {exc}") from exc

        if data.get("ok"):
            return data.get("result")

        error = data.get("error")
        if isinstance(error, str):
            if "FLOOD_WAIT" in error:
                try:
                    parts = error.replace("_", " ").split()
                    seconds = int(parts[-1])
                except (ValueError, IndexError):
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

    async def edit_account_info(
        self,
        short_name: str,
        author_name: str | None = None,
        author_url: str | None = None,
    ) -> dict[str, Any]:
        """Edits account info for the current access token."""
        params: dict[str, Any] = {"short_name": short_name}
        if author_name:
            params["author_name"] = author_name
        if author_url:
            params["author_url"] = author_url

        return await self._method("editAccountInfo", params)

    async def get_account_info(
        self,
        fields: list[str] | None = None,
    ) -> dict[str, Any]:
        """Gets info about a Telegraph account."""
        params: dict[str, Any] = {}
        if fields:
            params["fields"] = _json_serialize(fields)
        return await self._method("getAccountInfo", params)

    async def revoke_access_token(self) -> dict[str, Any]:
        """Revokes the current access token and returns a new one."""
        res = await self._method("revokeAccessToken")
        if isinstance(res, dict) and "access_token" in res:
            self.access_token = res["access_token"]
        return res

    def _prepare_content(
        self,
        html_content: str | None = None,
        content: str | list[Any] | None = None,
    ) -> str:
        target = content if content is not None else html_content
        if target is None:
            raise TelegraphError("No content provided for page creation/editing")
        if isinstance(target, str):
            nodes = html_to_nodes(target)
        else:
            nodes = target
        return _json_serialize(nodes)

    async def create_page(
        self,
        title: str,
        html_content: str | None = None,
        author_name: str | None = None,
        author_url: str | None = None,
        return_content: bool = False,
        content: str | list[Any] | None = None,
    ) -> dict[str, Any]:
        """Creates a new page on Telegraph."""
        serialized_content = self._prepare_content(html_content, content)
        params: dict[str, Any] = {
            "title": title,
            "content": serialized_content,
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
        html_content: str | None = None,
        author_name: str | None = None,
        author_url: str | None = None,
        return_content: bool = False,
        content: str | list[Any] | None = None,
    ) -> dict[str, Any]:
        """Edits an existing Telegraph page."""
        serialized_content = self._prepare_content(html_content, content)
        params: dict[str, Any] = {
            "title": title,
            "content": serialized_content,
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

    async def get_views(
        self,
        path: str,
        year: int | None = None,
        month: int | None = None,
        day: int | None = None,
        hour: int | None = None,
    ) -> dict[str, Any]:
        """Gets page views statistics."""
        params: dict[str, Any] = {}
        if year is not None:
            params["year"] = year
        if month is not None:
            params["month"] = month
        if day is not None:
            params["day"] = day
        if hour is not None:
            params["hour"] = hour
        return await self._method("getViews", values=params, path=path)

