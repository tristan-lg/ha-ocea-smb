import time
import base64
import json
import requests

from TokenStorageJson import TokenStorageJson

TOKEN_URL = "https://osbespaceresident.b2clogin.com/osbespaceresident.onmicrosoft.com/b2c_1a_signup_signin/oauth2/v2.0/token"
CLIENT_ID = "1cacfb15-0b3c-42cc-a662-736e4737e7d9"

class TokenManager:
    def __init__(self, safety_margin=1800, force_refresh=False):
        """
        safety_margin: secondes avant expiration pour renouveler
        force_refresh: forcer le rafraîchissement au démarrage
        """


        #TODO - Dans l'init, mettre la config et faire en sorte que le storage soit dans la config

        self.safety_margin = safety_margin
        self.access_token = None
        self.refresh_token = None
        self.expires_at = 0
        self.storage = TokenStorageJson("tokens.json")
        self._loadStoredTokens()

        if force_refresh:
            print("[TokenManager] Force refresh at startup")
            self._refresh()

    def get_token(self) -> str:
        if self._needs_refresh():
            self._refresh()
        return self.access_token

    def _loadStoredTokens(self):
        self.access_token = self.storage.get_access_token()
        self.refresh_token = self.storage.get_refresh_token()
        self.expires_at = self.storage.get_expires_at() or 0

        if not self.refresh_token:
            raise Exception("No refresh token stored!")

        print("Loaded stored tokens:")
        self._debug()

    def _debug(self):
        print(f"  Access token: {self.access_token}")
        print(f"  Refresh token: {self.refresh_token}")
        print(f"  Expires at: {self.expires_at}")


    def _needs_refresh(self) -> bool:
        return not self.access_token or time.time() >= self.expires_at - self.safety_margin

    def _refresh(self):
        print("[TokenManager] Refreshing token...")
        token_data = self._refresh_token()

        # Update refresh & access tokens
        self.access_token = token_data["access_token"]
        self.refresh_token = token_data["refresh_token"]

        # 1️⃣ priorité au expires_in
        if "expires_in" in token_data:
            self.expires_at = time.time() + int(token_data["expires_in"])
            print(f"[TokenManager] Token expires in {token_data['expires_in']} seconds")
        else:
            # 2️⃣ fallback : décodage JWT
            self.expires_at = self._decode_exp(self.access_token)
            print(f"[TokenManager] Token expires at {self.expires_at} (from JWT)")

        self.storage.save(
            access_token=self.access_token,
            refresh_token=self.refresh_token,
            expires_at=self.expires_at,
        )
        self._debug()

    def _refresh_token(self):
        response = requests.post(
            TOKEN_URL,
            data={
                "grant_type": "refresh_token",
                "client_id": CLIENT_ID,
                "refresh_token": self.refresh_token,
            },
            headers={"Content-Type": "application/x-www-form-urlencoded"},
        )
        response.raise_for_status()
        return response.json()

    @staticmethod
    def _decode_exp(token: str) -> int:
        payload = token.split(".")[1]
        padded = payload + "=" * (-len(payload) % 4)
        decoded = base64.urlsafe_b64decode(padded)
        data = json.loads(decoded)
        return int(data["exp"])
