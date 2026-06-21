"""
Kite Connect login flow. Access tokens expire every day around 6am IST, so
this needs to run once per trading day before the rest of the system.

Usage:
    python kite_auth.py        # interactive login, saves token to disk
    from kite_auth import get_kite   # everywhere else, just reuse the saved token
"""
from kiteconnect import KiteConnect
import config


def login():
    kite = KiteConnect(api_key=config.KITE_API_KEY)
    print("1. Open this URL, log in, and approve the app:")
    print(kite.login_url())
    request_token = input("2. Paste the request_token from the redirected URL: ").strip()
    data = kite.generate_session(request_token, api_secret=config.KITE_API_SECRET)
    access_token = data["access_token"]
    with open(config.KITE_ACCESS_TOKEN_FILE, "w") as f:
        f.write(access_token)
    kite.set_access_token(access_token)
    print("Login OK, token saved to", config.KITE_ACCESS_TOKEN_FILE)
    return kite


def get_kite():
    kite = KiteConnect(api_key=config.KITE_API_KEY)
    try:
        with open(config.KITE_ACCESS_TOKEN_FILE) as f:
            token = f.read().strip()
        kite.set_access_token(token)
        kite.profile()  # cheap call - throws if the token is dead
        return kite
    except Exception:
        print("Stored token missing or expired, running interactive login.")
        return login()


if __name__ == "__main__":
    login()
