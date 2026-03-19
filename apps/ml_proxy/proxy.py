import logging
import requests
from django.conf import settings
from django.core.cache import cache

logger = logging.getLogger(__name__)

NODEJS_BASE = settings.NODEJS_ML_BASE_URL


def _get_nodejs_token(user_id: str) -> str:
    """
    Exchange a Django user UUID for a Node.js JWT token.
    The Node.js auth endpoint accepts { external_id: "<uuid>" } and returns a
    24-hour token. We cache it in Redis for 23 hours under the key
    nodejs_token:<user_id> so we never hit the auth endpoint more than
    once per day per user.
    """
    cache_key = f"nodejs_token:{user_id}"
    token = cache.get(cache_key)
    if token:
        return token

    try:
        response = requests.post(
            f"{NODEJS_BASE}/api/v1/auth/token",
            json={"external_id": str(user_id)},
            timeout=10,
        )
        response.raise_for_status()
        token = response.json()["data"]["token"]
        cache.set(cache_key, token, timeout=23 * 3600)
        return token
    except requests.exceptions.RequestException as exc:
        logger.error("Node.js token exchange failed for user %s: %s", user_id, exc)
        raise


def _headers(user_id: str) -> dict:
    return {
        "Authorization": f"Bearer {_get_nodejs_token(user_id)}",
        "Content-Type": "application/json",
        "Accept": "application/json",
    }


def nodejs_get(user_id: str, path: str, params: dict = None) -> tuple:
    """Forward a GET request to the Node.js backend. Returns (response_dict, status_code)."""
    try:
        resp = requests.get(
            f"{NODEJS_BASE}{path}",
            headers=_headers(user_id),
            params=params,
            timeout=20,
        )
        return resp.json(), resp.status_code
    except requests.exceptions.ConnectionError:
        logger.error("Node.js backend unreachable: GET %s", path)
        return {
            "success": False,
            "message": "The ML prediction service is temporarily unavailable. Please try again shortly.",
        }, 503
    except requests.exceptions.Timeout:
        logger.error("Node.js backend timed out: GET %s", path)
        return {
            "success": False,
            "message": "The ML prediction service took too long to respond. Please try again.",
        }, 504
    except Exception as exc:
        logger.exception("Unexpected error proxying GET %s: %s", path, exc)
        return {"success": False, "message": "An unexpected error occurred."}, 500


def nodejs_post(user_id: str, path: str, body: dict = None) -> tuple:
    """Forward a POST request to the Node.js backend. Returns (response_dict, status_code)."""
    try:
        resp = requests.post(
            f"{NODEJS_BASE}{path}",
            headers=_headers(user_id),
            json=body or {},
            timeout=20,
        )
        return resp.json(), resp.status_code
    except requests.exceptions.ConnectionError:
        logger.error("Node.js backend unreachable: POST %s", path)
        return {
            "success": False,
            "message": "The ML prediction service is temporarily unavailable. Please try again shortly.",
        }, 503
    except requests.exceptions.Timeout:
        logger.error("Node.js backend timed out: POST %s", path)
        return {
            "success": False,
            "message": "The ML prediction service took too long to respond. Please try again.",
        }, 504
    except Exception as exc:
        logger.exception("Unexpected error proxying POST %s: %s", path, exc)
        return {"success": False, "message": "An unexpected error occurred."}, 500
