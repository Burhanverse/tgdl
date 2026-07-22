from __future__ import annotations

import logging
import os
import pickle
from pathlib import Path
from random import shuffle
from typing import Any, Optional

from google.auth.transport.requests import Request
from google.oauth2 import service_account
from google.oauth2.credentials import Credentials
from googleapiclient.discovery import build

from ..config import settings

log = logging.getLogger(__name__)

OAUTH_SCOPE = ["https://www.googleapis.com/auth/drive"]


def get_user_auth_dir(user_id: int | str) -> Path:
    user_dir = settings.auth_dir / str(user_id)
    user_dir.mkdir(parents=True, exist_ok=True)
    return user_dir


def create_oauth_flow_from_json(json_path: Path, redirect_uri: str = "http://127.0.0.1:8080/") -> tuple[Any, str]:
    """Initializes Google OAuth flow from a credentials.json file and returns (flow, auth_url)."""
    from google_auth_oauthlib.flow import InstalledAppFlow

    flow = InstalledAppFlow.from_client_secrets_file(
        str(json_path),
        scopes=OAUTH_SCOPE,
        redirect_uri=redirect_uri,
    )
    auth_url, _ = flow.authorization_url(
        access_type="offline",
        prompt="consent",
        include_granted_scopes="true",
    )
    return flow, auth_url


def finish_oauth_flow_and_save(
    flow: Any,
    auth_code: str,
    user_id: Optional[int | str] = None,
    token_path: Optional[Path] = None,
) -> Credentials:
    """Exchanges authorization code for tokens and saves credentials to auth/{user_id}/token.pickle."""
    if not token_path:
        if user_id:
            token_path = get_user_auth_dir(user_id) / "token.pickle"
        else:
            token_path = settings.gdrive_token_path

    token_path.parent.mkdir(parents=True, exist_ok=True)

    flow.fetch_token(code=auth_code.strip())
    credentials = flow.credentials

    with open(token_path, "wb") as f:
        pickle.dump(credentials, f)

    log.info("Successfully saved user GDrive OAuth token to %s", token_path)
    return credentials


class GoogleDriveAuthManager:
    def __init__(
        self,
        user_id: Optional[int | str] = None,
        token_path: Optional[Path] = None,
        accounts_dir: Optional[Path] = None,
        use_sa: Optional[bool] = None,
    ):
        self.user_id = str(user_id) if user_id else None
        if self.user_id and not token_path and not accounts_dir:
            user_dir = get_user_auth_dir(self.user_id)
            self.token_path = user_dir / "token.pickle"
            self.accounts_dir = user_dir / "accounts"
        else:
            self.token_path = token_path or settings.gdrive_token_path
            self.accounts_dir = accounts_dir or settings.gdrive_accounts_dir

        self.use_sa = use_sa if use_sa is not None else settings.use_service_accounts

    def has_credentials(self) -> bool:
        if self.use_sa and self.accounts_dir.exists() and self.accounts_dir.is_dir():
            if any(f.endswith(".json") for f in os.listdir(self.accounts_dir)):
                return True
        if self.token_path.exists():
            return True

        if self.user_id:
            global_sa = settings.gdrive_accounts_dir
            global_token = settings.gdrive_token_path
            if self.use_sa and global_sa.exists() and global_sa.is_dir():
                if any(f.endswith(".json") for f in os.listdir(global_sa)):
                    return True
            if global_token.exists():
                return True

        return False

    def get_credentials(self) -> Any:
        search_paths = [(self.accounts_dir, self.token_path)]
        if self.user_id:
            search_paths.append((settings.gdrive_accounts_dir, settings.gdrive_token_path))

        for accounts_dir, token_path in search_paths:
            # 1. Try Service Accounts if enabled
            if self.use_sa and accounts_dir.exists() and accounts_dir.is_dir():
                json_files = [f for f in os.listdir(accounts_dir) if f.endswith(".json")]
                if json_files:
                    shuffle(json_files)
                    for sa_file in json_files:
                        selected_sa = accounts_dir / sa_file
                        log.info("Authorizing GDrive with service account: %s", selected_sa.name)
                        try:
                            credentials = service_account.Credentials.from_service_account_file(
                                str(selected_sa), scopes=OAUTH_SCOPE
                            )
                            return credentials
                        except Exception as e:
                            log.warning("Failed to authorize with service account %s: %s", selected_sa.name, e)

            # 2. Try OAuth token pickle
            if token_path.exists():
                log.info("Authorizing GDrive with OAuth token: %s", token_path)
                try:
                    with open(token_path, "rb") as f:
                        credentials = pickle.load(f)

                    if isinstance(credentials, Credentials):
                        if credentials.expired and credentials.refresh_token:
                            log.info("OAuth token expired, refreshing...")
                            try:
                                credentials.refresh(Request())
                                with open(token_path, "wb") as f:
                                    pickle.dump(credentials, f)
                                log.info("Refreshed and saved OAuth token successfully.")
                            except Exception as re:
                                log.warning("Failed to refresh OAuth token: %s", re)

                    return credentials
                except Exception as e:
                    log.error("Failed to load OAuth token from %s: %s", token_path, e)

        raise RuntimeError(
            f"No valid GDrive credentials found for user '{self.user_id or 'default'}'. "
            f"Provide credentials.json or Service Account JSON files."
        )

    def build_service(self) -> Any:
        creds = self.get_credentials()
        return build("drive", "v3", credentials=creds, cache_discovery=False)
