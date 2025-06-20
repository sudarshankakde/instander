import instaloader
import json
import os
from typing import List, Dict, Optional

SESSION_DIR = "sessions"  # Directory to store all user session files
file_path = "login_accounts.json"  # Path to accounts JSON file

def load_accounts(file_path: str) -> List[Dict[str, str]]:
    """
    Load Instagram login accounts from a JSON file.
    """
    if not os.path.exists(file_path):
        raise FileNotFoundError(f"[❌] Login file '{file_path}' not found.")
    
    with open(file_path, "r") as f:
        accounts = json.load(f)

    if not accounts or not isinstance(accounts, list):
        raise ValueError("[⚠️] 'login_accounts.json' must be a list of account dictionaries.")
    
    return accounts

def ensure_session_dir():
    """
    Ensure the session directory exists.
    """
    os.makedirs(SESSION_DIR, exist_ok=True)

def try_login(account: Dict[str, str]) -> Optional[instaloader.Instaloader]:
    """
    Try to log in with a single account, or load a saved session.
    """
    ensure_session_dir()
    L = instaloader.Instaloader()

    username = account.get("username")
    password = account.get("password")

    if not username or not password:
        print("[⚠️] Skipping account with missing username or password.")
        return None

    session_file = os.path.join(SESSION_DIR, f"{username}.session")

    try:
        L.load_session_from_file(username, session_file)
        print(f"[✔] Loaded session for: {username}")
    except FileNotFoundError:
        try:
            print(f"[🔐] Logging in as {username}...")
            L.login(username, password)
            L.save_session_to_file(session_file)
            print(f"[✔] Session saved for: {username}")
        except Exception as e:
            print(f"[❌] Login failed for {username}: {e}")
            return None
    except Exception as e:
        print(f"[⚠️] Failed loading session for {username}: {e}")
        return None

    return L

def get_available_instaloader(file_path: str) -> instaloader.Instaloader:
    """
    Iterate over all accounts and return the first successful Instaloader session.
    """
    accounts = load_accounts(file_path)
    for account in accounts:
        L = try_login(account)
        if L:
            return L
    raise RuntimeError("⚠️ All accounts failed login or session loading.")
