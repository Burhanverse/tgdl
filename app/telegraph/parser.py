from __future__ import annotations

from html.parser import HTMLParser
from re import compile as re_compile
from typing import Any

_RE_WHITESPACE = re_compile(r"\s+")

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

_ALLOWED_ATTRS = {
    "a": {"href"},
    "img": {"src"},
    "video": {"src"},
    "iframe": {"src"},
}

_TAG_MAP = {
    "h1": "h3",
    "h2": "h3",
    "h5": "h4",
    "h6": "h4",
}

_UNWRAP_TAGS = {
    "div",
    "span",
    "article",
    "section",
    "header",
    "footer",
    "main",
    "html",
    "body",
    "font",
    "center",
    "tbody",
    "thead",
    "tfoot",
    "tr",
    "td",
    "th",
    "table",
}

_IGNORE_TAGS = {
    "script",
    "style",
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


class TelegraphError(Exception):
    """Base exception for Telegraph errors."""



class NotAllowedTag(TelegraphError):
    """Exception raised when an HTML tag is not allowed by Telegraph."""



class InvalidHTML(TelegraphError):
    """Exception raised when HTML is malformed."""



class RetryAfterError(TelegraphError):
    """Exception raised when Telegraph flood control is triggered."""

    def __init__(self, retry_after: int) -> None:
        self.retry_after = retry_after
        super().__init__(f"Flood control, retry in {retry_after}s")


class _HTMLToNodes(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.nodes: list[Any] = []
        self._current: list[Any] = self.nodes
        self._parents: list[list[Any]] = []
        self._open_tags: list[str] = []

    def _add_text(self, s: str) -> None:
        if not s:
            return
        if "pre" not in self._open_tags:
            s = _RE_WHITESPACE.sub(" ", s)
            if not s or (s == " " and self._current and isinstance(self._current[-1], str) and self._current[-1].endswith(" ")):
                return
        if self._current and isinstance(self._current[-1], str):
            self._current[-1] += s
        else:
            self._current.append(s)

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        tag_lower = tag.lower()

        if tag_lower in _UNWRAP_TAGS:
            return

        tag_lower = _TAG_MAP.get(tag_lower, tag_lower)

        if tag_lower not in _ALLOWED_TAGS:
            raise NotAllowedTag(f"<{tag}> not allowed")

        node: dict[str, Any] = {"tag": tag_lower}

        allowed = _ALLOWED_ATTRS.get(tag_lower, set())
        valid_attrs = {k.lower(): v for k, v in attrs if k.lower() in allowed and v is not None}
        if valid_attrs:
            node["attrs"] = valid_attrs

        self._current.append(node)

        if tag_lower not in _VOID_ELEMENTS:
            self._parents.append(self._current)
            self._open_tags.append(tag_lower)
            children: list[Any] = []
            node["children"] = children
            self._current = children

    def handle_endtag(self, tag: str) -> None:
        tag_lower = tag.lower()

        if tag_lower in _UNWRAP_TAGS:
            return

        tag_lower = _TAG_MAP.get(tag_lower, tag_lower)

        if tag_lower in _VOID_ELEMENTS:
            return

        if not self._parents or not self._open_tags:
            raise InvalidHTML(f"</{tag}> missing start tag")

        expected_tag = self._open_tags.pop()
        if expected_tag != tag_lower:
            raise InvalidHTML(f"</{tag}> closed instead of </{expected_tag}>")

        self._current = self._parents.pop()
        last = self._current[-1]
        if not last.get("children"):
            last.pop("children", None)

    def handle_data(self, data: str) -> None:
        self._add_text(data)

    def get_nodes(self) -> list[Any]:
        while self._parents and self._open_tags:
            self._open_tags.pop()
            self._current = self._parents.pop()
            last = self._current[-1]
            if not last.get("children"):
                last.pop("children", None)
        return self.nodes


def html_to_nodes(html: str) -> list[Any]:
    """Converts HTML string to Telegraph DOM node array."""
    parser = _HTMLToNodes()
    parser.feed(html)
    return parser.get_nodes()
