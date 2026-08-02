from __future__ import annotations

from html.entities import name2codepoint
from html.parser import HTMLParser
from re import compile as re_compile
from typing import Any

_RE_WHITESPACE = re_compile(r"(\s+)")

_ALLOWED_TAGS = {
    "a",
    "aside",
    "b",
    "blockquote",
    "br",
    "code",
    "em",
    "figcaption",
    "figure",
    "h3",
    "h4",
    "hr",
    "i",
    "iframe",
    "img",
    "li",
    "ol",
    "p",
    "pre",
    "s",
    "strong",
    "u",
    "ul",
    "video",
}

_VOID_ELEMENTS = {
    "area",
    "base",
    "br",
    "col",
    "embed",
    "hr",
    "img",
    "input",
    "keygen",
    "link",
    "menuitem",
    "meta",
    "param",
    "source",
    "track",
    "wbr",
}

_BLOCK_ELEMENTS = {
    "address",
    "article",
    "aside",
    "blockquote",
    "canvas",
    "dd",
    "div",
    "dl",
    "dt",
    "fieldset",
    "figcaption",
    "figure",
    "footer",
    "form",
    "h1",
    "h2",
    "h3",
    "h4",
    "h5",
    "h6",
    "header",
    "hgroup",
    "hr",
    "li",
    "main",
    "nav",
    "noscript",
    "ol",
    "p",
    "pre",
    "section",
    "table",
    "tfoot",
    "ul",
    "video",
}


class TelegraphError(Exception):
    """Base exception for Telegraph errors."""

    pass


class NotAllowedTag(TelegraphError):
    """Exception raised when an HTML tag is not allowed by Telegraph."""

    pass


class InvalidHTML(TelegraphError):
    """Exception raised when HTML is malformed."""

    pass


class RetryAfterError(TelegraphError):
    """Exception raised when Telegraph flood control is triggered."""

    def __init__(self, retry_after: int) -> None:
        self.retry_after = retry_after
        super().__init__(f"Flood control, retry in {retry_after}s")


class _HTMLToNodes(HTMLParser):
    def __init__(self) -> None:
        super().__init__()
        self.nodes: list[Any] = []
        self._current: list[Any] = self.nodes
        self._parents: list[list[Any]] = []
        self._last_text: str | None = None
        self._tags: list[str] = []

    def _add_text(self, s: str) -> None:
        if not s:
            return
        if "pre" not in self._tags:
            s = _RE_WHITESPACE.sub(" ", s)
            if self._last_text is None or self._last_text.endswith(" "):
                s = s.lstrip(" ")
            if not s:
                self._last_text = None
                return
            self._last_text = s
        if self._current and isinstance(self._current[-1], str):
            self._current[-1] += s
        else:
            self._current.append(s)

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        tag_lower = tag.lower()
        if tag_lower not in _ALLOWED_TAGS:
            raise NotAllowedTag(f"<{tag}> not allowed")
        if tag_lower in _BLOCK_ELEMENTS:
            self._last_text = None
        node: dict[str, Any] = {"tag": tag_lower}
        self._tags.append(tag_lower)
        self._current.append(node)
        valid_attrs = {k: v for k, v in attrs if v is not None}
        if valid_attrs:
            node["attrs"] = valid_attrs
        if tag_lower not in _VOID_ELEMENTS:
            self._parents.append(self._current)
            children: list[Any] = []
            node["children"] = children
            self._current = children

    def handle_endtag(self, tag: str) -> None:
        tag_lower = tag.lower()
        if tag_lower in _VOID_ELEMENTS:
            return
        if not self._parents:
            raise InvalidHTML(f"</{tag}> missing start tag")
        self._current = self._parents.pop()
        last = self._current[-1]
        if last["tag"] != tag_lower:
            raise InvalidHTML(f"</{tag}> closed instead of </{last['tag']}>")
        self._tags.pop()
        if not last.get("children"):
            last.pop("children", None)

    def handle_data(self, data: str) -> None:
        self._add_text(data)

    def handle_entityref(self, name: str) -> None:
        if name in name2codepoint:
            self._add_text(chr(name2codepoint[name]))

    def handle_charref(self, name: str) -> None:
        try:
            val = int(name[1:], 16) if name.startswith("x") or name.startswith("X") else int(name)
            self._add_text(chr(val))
        except (ValueError, OverflowError):
            pass

    def get_nodes(self) -> list[Any]:
        if self._parents:
            raise InvalidHTML(f"<{self._parents[-1][-1]['tag']}> not closed")
        return self.nodes


def html_to_nodes(html: str) -> list[Any]:
    """Converts HTML string to Telegraph DOM node array."""
    parser = _HTMLToNodes()
    parser.feed(html)
    return parser.get_nodes()
