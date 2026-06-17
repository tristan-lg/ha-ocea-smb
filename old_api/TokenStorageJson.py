import json
import os
from typing import Optional

class TokenStorageJson:
    def __init__(self, path: str):
        self.path = path

    def load(self) -> dict:
        if not os.path.exists(self.path):
            return {}

        with open(self.path, "r", encoding="utf-8") as f:
            return json.load(f)

    def save(
        self,
        access_token: str,
        refresh_token: Optional[str] = None,
        expires_at: Optional[int] = None,
    ):
        print("[Storage] Token saved in local storage")
        data = {
            "access_token": access_token,
        }

        if refresh_token is not None:
            data["refresh_token"] = refresh_token

        if expires_at is not None:
            data["expires_at"] = expires_at

        with open(self.path, "w", encoding="utf-8") as f:
            json.dump(data, f, indent=2)

    def get_access_token(self) -> Optional[str]:
        return self.load().get("access_token")

    def get_refresh_token(self) -> Optional[str]:
        return self.load().get("refresh_token")

    def get_expires_at(self) -> Optional[int]:
        return self.load().get("expires_at")

    def clear(self):
        if os.path.exists(self.path):
            os.remove(self.path)
