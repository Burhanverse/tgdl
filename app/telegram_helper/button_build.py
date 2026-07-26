from __future__ import annotations

from typing import Optional
from pyrogram.types import InlineKeyboardButton, InlineKeyboardMarkup


class ButtonMaker:

    def __init__(self) -> None:
        self._button: list[InlineKeyboardButton] = []
        self._header_button: list[InlineKeyboardButton] = []
        self._footer_button: list[InlineKeyboardButton] = []

    def data_button(self, text: str, callback_data: str, position: Optional[str] = None) -> None:
        btn = InlineKeyboardButton(text=text, callback_data=callback_data)
        if position == "header":
            self._header_button.append(btn)
        elif position == "footer":
            self._footer_button.append(btn)
        else:
            self._button.append(btn)

    def url_button(self, text: str, url: str, position: Optional[str] = None) -> None:
        btn = InlineKeyboardButton(text=text, url=url)
        if position == "header":
            self._header_button.append(btn)
        elif position == "footer":
            self._footer_button.append(btn)
        else:
            self._button.append(btn)

    def build_menu(
        self, b_cols: int = 2, h_cols: int = 2, f_cols: int = 2
    ) -> Optional[InlineKeyboardMarkup]:
        menu: list[list[InlineKeyboardButton]] = []

        if self._header_button:
            h_grid = [
                self._header_button[i : i + h_cols]
                for i in range(0, len(self._header_button), h_cols)
            ]
            menu.extend(h_grid)

        if self._button:
            b_grid = [
                self._button[i : i + b_cols]
                for i in range(0, len(self._button), b_cols)
            ]
            menu.extend(b_grid)

        if self._footer_button:
            f_grid = [
                self._footer_button[i : i + f_cols]
                for i in range(0, len(self._footer_button), f_cols)
            ]
            menu.extend(f_grid)

        if not menu:
            return None
        return InlineKeyboardMarkup(menu)
