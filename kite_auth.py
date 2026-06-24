"""
Kite Connect login flow. Access tokens expire every day around 6am IST, so
this needs to run once per trading day before the rest of the system.

Usage:
    python kite_auth.py        # interactive login, saves token to disk
    from kite_auth import get_kite   # everywhere else, just reuse the saved token

get_kite() tries, in order: a still-valid saved token -> automated TOTP
login (if KITE_USER_ID/PASSWORD/TOTP_SECRET are all set) -> interactive
paste-a-token login. The automated path exists specifically so this can
run unattended on a schedule (cron, GitHub Actions) - see config.py for the
security tradeoff that comes with it.
"""
import sys
from urllib.parse import urlparse, parse_qs

import requests
import pyotp
from kiteconnect import KiteConnect
import config

ZERODHA_LOGIN_URL = "https://kite.zerodha.com/api/login"
ZERODHA_TWOFA_URL = "https://kite.zerodha.com/api/twofa"


def login():
    kite = KiteConnect(api_key=config.KITE_API_KEY)
    print("1. Open this URL, log in, and approve the app:")
    print(kite.login_url())
    request_token = input("2. Paste the request_token from the redirected URL: ").strip()
    return _complete_session(kite, request_token)


def automated_login():
    """
    Scripts the same login flow a browser would do, using your account
    password and a TOTP code generated from your 2FA secret, then completes
    the Kite Connect handshake exactly like the interactive flow does.
    Requires KITE_USER_ID, KITE_PASSWORD, KITE_TOTP_SECRET to be set.
    """
    session = requests.Session()

    r = session.post(ZERODHA_LOGIN_URL, data={
        "user_id": config.KITE_USER_ID,
        "password": config.KITE_PASSWORD,
    })
    r.raise_for_status()
    request_id = r.json()["data"]["request_id"]

    totp_code = pyotp.TOTP(config.KITE_TOTP_SECRET).now()
    r2 = session.post(ZERODHA_TWOFA_URL, data={
        "user_id": config.KITE_USER_ID,
        "request_id": request_id,
        "twofa_value": totp_code,
        "twofa_type": "totp",
    })
    r2.raise_for_status()

    kite = KiteConnect(api_key=config.KITE_API_KEY)
    r3 = session.get(kite.login_url(), allow_redirects=True)
    request_token = parse_qs(urlparse(r3.url).query).get("request_token", [None])[0]
    if not request_token:
        raise RuntimeError(
            "Could not extract request_token from the post-login redirect - "
            "Zerodha's login flow may have changed, or the credentials/TOTP "
            "secret are wrong. Run kite_auth.py interactively to confirm "
            "the basic login still works before debugging this further."
        )
    return _complete_session(kite, request_token)


def _complete_session(kite, request_token):
    data = kite.generate_session(request_token, api_secret=config.KITE_API_SECRET)
    access_token = data["access_token"]
    with open(config.KITE_ACCESS_TOKEN_FILE, "w") as f:
        f.write(access_token)
    kite.set_access_token(access_token)
    print("Login OK, token saved to", config.KITE_ACCESS_TOKEN_FILE)
    return kite


def _automated_credentials_available():
    return bool(config.KITE_USER_ID and config.KITE_PASSWORD and config.KITE_TOTP_SECRET)


def get_kite():
    kite = KiteConnect(api_key=config.KITE_API_KEY)
    try:
        with open(config.KITE_ACCESS_TOKEN_FILE) as f:
            token = f.read().strip()
        kite.set_access_token(token)
        kite.profile()  # cheap call - throws if the token is dead
        return kite
    except Exception:
        pass

    if _automated_credentials_available():
        print("Stored token missing or expired, running automated TOTP login.")
        return automated_login()

    if not sys.stdin.isatty():
        raise RuntimeError(
            "Token expired and no automated-login credentials are set "
            "(KITE_USER_ID/KITE_PASSWORD/KITE_TOTP_SECRET), and this isn't "
            "an interactive session - can't prompt for a token paste. "
            "Set the automated-login env vars, or run this interactively."
        )
    print("Stored token missing or expired, running interactive login.")
    return login()


if __name__ == "__main__":
    login()
