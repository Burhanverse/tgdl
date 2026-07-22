#!/usr/bin/env python3
"""CLI utility to generate token.pickle for Google Drive authentication.

Usage:
    python3 -m app.gdrive.setup <path_to_client_secret.json> [user_id]
"""

import sys
import pickle
from pathlib import Path

from google_auth_oauthlib.flow import InstalledAppFlow
from app.config import settings

SCOPES = ["https://www.googleapis.com/auth/drive"]


def main():
    if len(sys.argv) < 2:
        print("Usage: python3 -m app.gdrive.setup <path_to_credentials.json> [user_id]")
        print("\nExample:\n  python3 -m app.gdrive.setup client_secret.json 6754789603")
        sys.exit(1)

    json_path = Path(sys.argv[1]).resolve()
    if not json_path.exists():
        print(f"Error: File '{json_path}' not found.")
        sys.exit(1)

    user_id = sys.argv[2] if len(sys.argv) > 2 else None
    if user_id:
        target_dir = settings.auth_dir / str(user_id)
    else:
        target_dir = settings.auth_dir

    target_dir.mkdir(parents=True, exist_ok=True)
    token_path = target_dir / "token.pickle"

    print(f"Reading OAuth credentials from: {json_path}")
    print("Starting local OAuth authorization server...")

    flow = InstalledAppFlow.from_client_secrets_file(str(json_path), SCOPES)
    creds = flow.run_local_server(port=8080, prompt="consent")

    with open(token_path, "wb") as token_file:
        pickle.dump(creds, token_file)

    print(f"\nSuccess! Saved OAuth token to: {token_path}")
    print("You can now use /gd2tg <gdrive_link> in Telegram!")


if __name__ == "__main__":
    main()
