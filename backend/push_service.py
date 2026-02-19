import json
import os
from typing import Dict, List

import firebase_admin
from firebase_admin import credentials, messaging

_firebase_ready = False


def init_firebase():
    """Initialise Firebase Admin SDK une seule fois."""
    global _firebase_ready
    if _firebase_ready:
        return True

    try:
        if firebase_admin._apps:
            _firebase_ready = True
            return True

        service_account_json = os.environ.get("FIREBASE_SERVICE_ACCOUNT_JSON")
        credentials_path = (
            os.environ.get("FIREBASE_CREDENTIALS_PATH")
            or os.environ.get("GOOGLE_APPLICATION_CREDENTIALS")
        )

        cred = None
        if service_account_json:
            cred_info = json.loads(service_account_json)
            cred = credentials.Certificate(cred_info)
        elif credentials_path and os.path.exists(credentials_path):
            cred = credentials.Certificate(credentials_path)

        if cred is None:
            return False

        firebase_admin.initialize_app(cred)
        _firebase_ready = True
        return True
    except Exception as exc:
        print(f"[PUSH] Firebase init error: {exc}")
        return False


def send_push(tokens: List[str], title: str, body: str, data: Dict[str, str] | None = None):
    """
    Envoie une notification FCM multicast.
    Retourne: {"sent": int, "failed": int, "invalid_tokens": [..], "enabled": bool}
    """
    if not tokens:
        return {"sent": 0, "failed": 0, "invalid_tokens": [], "enabled": False}

    if not init_firebase():
        return {"sent": 0, "failed": 0, "invalid_tokens": [], "enabled": False}

    safe_data = {}
    if data:
        safe_data = {str(k): str(v) for k, v in data.items()}

    message = messaging.MulticastMessage(
        tokens=list({t for t in tokens if t}),
        notification=messaging.Notification(title=title, body=body),
        data=safe_data,
        android=messaging.AndroidConfig(priority="high"),
        apns=messaging.APNSConfig(
            payload=messaging.APNSPayload(
                aps=messaging.Aps(sound="default", badge=1, content_available=True)
            )
        ),
    )

    try:
        response = messaging.send_each_for_multicast(message)
        invalid_tokens: List[str] = []
        for index, result in enumerate(response.responses):
            if result.success:
                continue
            error_text = str(result.exception).lower() if result.exception else ""
            if "registration-token-not-registered" in error_text or "invalid-registration-token" in error_text:
                invalid_tokens.append(message.tokens[index])

        return {
            "sent": response.success_count,
            "failed": response.failure_count,
            "invalid_tokens": invalid_tokens,
            "enabled": True,
        }
    except Exception as exc:
        print(f"[PUSH] send error: {exc}")
        return {"sent": 0, "failed": len(tokens), "invalid_tokens": [], "enabled": True}
