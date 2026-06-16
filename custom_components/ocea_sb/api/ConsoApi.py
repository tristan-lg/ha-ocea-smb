from aiohttp import ClientConnectorError, ClientResponseError
from aiohttp import ClientSession

import logging

from dev.ocea_sb.custom_components.ocea_sb.api.TokenManager import TokenManager

API_URL_CHAUFF = "https://espace-resident-api.ocea-sb.com/api/v1/local/e7b674b9-3230-4bd3-86f4-5ff4a6f4caae/conso/Cetc"
API_URL_EAU_CH = "https://espace-resident-api.ocea-sb.com/api/v1/local/e7b674b9-3230-4bd3-86f4-5ff4a6f4caae/conso/EauChaude"

_LOGGER = logging.getLogger(__name__)

class ConsoApi:
    def __init__(self, client: ClientSession, manager: TokenManager):
        self.client = client
        self.manager = manager

    async def get_conso_chauffage(self, from_date: str, to_date: str):
        return await self._get_conso(API_URL_CHAUFF, from_date, to_date)

    async def get_conso_eau_chaude(self, from_date: str, to_date: str):
        return await self._get_conso(API_URL_EAU_CH, from_date, to_date)

    async def _get_conso(self, api: str, from_date: str, to_date: str):
        try:
            token = self.manager.get_token()
            async with self.client.post(api, headers={
                "Authorization": f"Bearer {token}",
                "Accept": "application/json",
                "Content-Type": "application/json",
            }, json= {
                "debut": from_date,
                "fin": to_date,
                "granularity": "Day"
            }, timeout=10) as response:

                # Vérification du statut HTTP
                response.raise_for_status()

                data = await response.json()

                _LOGGER.info(f"Requête réussie - Status: {response.status}")
                _LOGGER.debug(f"Réponse JSON: {data}")

                return data

        except ClientConnectorError as e:
            _LOGGER.error(f"Erreur de connexion: {str(e)}")
        except ClientResponseError as e:
            _LOGGER.error(f"Erreur HTTP - Status: {e.status}, Message: {str(e)}")
        except ValueError as e:
            _LOGGER.error(f"La réponse n'est pas un JSON valide: {str(e)}")
        except Exception as e:
            _LOGGER.error(f"Erreur inattendue: {str(e)}")

        return None
