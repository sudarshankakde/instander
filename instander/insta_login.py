import os
import json
import time
import threading
import logging
from typing import List, Dict, Optional, Tuple
from datetime import datetime, timedelta
import instaloader
from selenium import webdriver
from selenium.webdriver.common.by import By
from selenium.webdriver.chrome.options import Options
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
from django.conf import settings
from django.core.cache import cache
import random

# Configure logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# Configuration
SESSION_DIR = os.path.join(settings.BASE_DIR, "sessions")
LOGIN_FILE = os.path.join(settings.BASE_DIR, "login_accounts.json")
RATE_LIMIT_CACHE_KEY = "instagram_rate_limit"
ACCOUNT_STATUS_CACHE_KEY = "instagram_account_status"
SESSION_VALIDITY_HOURS = 24

# Ensure directories exist
os.makedirs(SESSION_DIR, exist_ok=True)

class RateLimitManager:
    """Manages rate limiting for Instagram API calls"""
    
    def __init__(self):
        self.last_request_time = {}
        self.request_counts = {}
        self.lock = threading.Lock()
    
    def can_make_request(self, account_username: str) -> bool:
        """Check if we can make a request for this account"""
        with self.lock:
            now = time.time()
            
            # Reset counters every hour
            if account_username not in self.last_request_time:
                self.last_request_time[account_username] = now
                self.request_counts[account_username] = 0
                return True
            
            # If more than an hour has passed, reset counter
            if now - self.last_request_time[account_username] > 3600:  # 1 hour
                self.request_counts[account_username] = 0
                self.last_request_time[account_username] = now
            
            # Instagram allows ~200 requests per hour, we'll be conservative with 150
            if self.request_counts[account_username] >= 150:
                return False
            
            # Enforce minimum delay between requests (3-5 seconds)
            min_delay = random.uniform(3, 5)
            if now - self.last_request_time[account_username] < min_delay:
                return False
            
            return True
    
    def record_request(self, account_username: str):
        """Record that a request was made"""
        with self.lock:
            now = time.time()
            self.last_request_time[account_username] = now
            self.request_counts[account_username] = self.request_counts.get(account_username, 0) + 1
    
    def wait_if_needed(self, account_username: str):
        """Wait if rate limit would be exceeded"""
        while not self.can_make_request(account_username):
            wait_time = random.uniform(5, 10)
            logger.info(f"Rate limit reached for {account_username}, waiting {wait_time:.1f} seconds")
            time.sleep(wait_time)

class InstagramSessionManager:
    """Manages Instagram sessions with automatic failover and rate limiting"""
    
    def __init__(self):
        self.sessions = {}
        self.account_status = {}
        self.rate_limiter = RateLimitManager()
        self.lock = threading.Lock()
        self.current_account_index = 0
        self.accounts = []
        self.initialization_lock = threading.Lock()
        self.initialized = False
    
    def load_accounts(self) -> List[Dict[str, str]]:
        """Load accounts from JSON file"""
        if not os.path.exists(LOGIN_FILE):
            raise FileNotFoundError(f"Login file '{LOGIN_FILE}' not found.")
        
        with open(LOGIN_FILE, "r") as f:
            accounts = json.load(f)
        
        if not isinstance(accounts, list) or not accounts:
            raise ValueError("'login_accounts.json' must contain a list of account objects.")
        
        return accounts
    
    def is_session_valid(self, username: str) -> bool:
        """Check if a session file exists and is recent"""
        session_file = os.path.join(SESSION_DIR, f"{username}.session")
        if not os.path.exists(session_file):
            return False
        
        # Check if session is less than 24 hours old
        session_age = time.time() - os.path.getmtime(session_file)
        return session_age < (SESSION_VALIDITY_HOURS * 3600)
    
    def selenium_login(self, username: str, password: str) -> bool:
        """Login using Selenium with enhanced error handling"""
        session_file = os.path.join(SESSION_DIR, f"{username}.session")
        
        try:
            logger.info(f"Starting Selenium login for {username}")
            
            options = Options()
            options.add_argument("--headless=new")
            options.add_argument("--no-sandbox")
            options.add_argument("--disable-dev-shm-usage")
            options.add_argument("--disable-gpu")
            options.add_argument("--window-size=1920,1080")
            options.add_argument("--user-agent=Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36")
            
            driver = webdriver.Chrome(options=options)
            wait = WebDriverWait(driver, 20)
            
            try:
                driver.get("https://www.instagram.com/accounts/login/")
                
                # Wait for login form to load
                username_field = wait.until(EC.presence_of_element_located((By.NAME, "username")))
                password_field = driver.find_element(By.NAME, "password")
                
                # Add random delays to mimic human behavior
                time.sleep(random.uniform(2, 4))
                
                username_field.send_keys(username)
                time.sleep(random.uniform(1, 2))
                password_field.send_keys(password)
                time.sleep(random.uniform(1, 2))
                
                # Click login button
                login_button = driver.find_element(By.CSS_SELECTOR, "button[type='submit']")
                login_button.click()
                
                # Wait for navigation
                time.sleep(random.uniform(5, 8))
                
                # Check for various possible outcomes
                current_url = driver.current_url
                
                if "challenge" in current_url:
                    logger.warning(f"Instagram checkpoint detected for {username}")
                    return False
                elif "login" in current_url:
                    logger.error(f"Login failed for {username} - still on login page")
                    return False
                
                # Extract cookies and save session
                cookies = driver.get_cookies()
                
                # Create Instaloader instance and set cookies
                L = instaloader.Instaloader()
                for cookie in cookies:
                    L.context._session.cookies.set(cookie['name'], cookie['value'])
                
                # Test the session by making a simple request
                try:
                    L.context.graphql_query("", {})  # Simple test query
                except:
                    pass  # Expected to fail, but session should be set
                
                L.save_session_to_file(session_file)
                logger.info(f"Session saved successfully for {username}")
                return True
                
            finally:
                driver.quit()
                
        except Exception as e:
            logger.error(f"Selenium login failed for {username}: {e}")
            return False
    
    def try_login(self, account: Dict[str, str]) -> Optional[instaloader.Instaloader]:
        """Attempt to login with various methods"""
        username = account.get("username")
        password = account.get("password")
        
        if not username or not password:
            logger.warning("Account missing username or password")
            return None
        
        session_file = os.path.join(SESSION_DIR, f"{username}.session")
        L = instaloader.Instaloader()
        
        # Try loading existing session if it's valid
        if self.is_session_valid(username):
            try:
                L.load_session_from_file(username, session_file)
                # Test the session
                profile = instaloader.Profile.from_username(L.context, username)
                logger.info(f"Loaded valid session for: {username} workuing")
                return L
            except Exception as e:
                logger.warning(f"Saved session invalid for {username}: {e}")
        
        # Try direct instaloader login
        try:
            L.login(username, password)
            L.save_session_to_file(session_file)
            logger.info(f"Direct login successful for {username}")
            return L
        except Exception as e:
            logger.warning(f"Direct login failed for {username}: {e}")
        
        # Fallback to Selenium
        logger.info(f"Attempting Selenium login for {username}")
        if self.selenium_login(username, password):
            try:
                L.load_session_from_file(username, session_file)
                # Test the session
                profile = instaloader.Profile.from_username(L.context, username)
                logger.info(f"Selenium login successful for {username}")
                return L
            except Exception as e:
                logger.error(f"Failed to load session after Selenium login: {e}")
        
        return None
    
    def initialize_sessions(self):
        """Initialize all available sessions at startup"""
        with self.initialization_lock:
            if self.initialized:
                return
            
            logger.info("Initializing Instagram sessions...")
            self.accounts = self.load_accounts()
            
            for account in self.accounts:
                username = account.get("username")
                if not username:
                    continue
                
                logger.info(f"Attempting to initialize session for {username}")
                session = self.try_login(account)
                
                if session:
                    self.sessions[username] = session
                    self.account_status[username] = {
                        'active': True,
                        'last_used': time.time(),
                        'request_count': 0
                    }
                    logger.info(f"Session initialized for {username}")
                else:
                    self.account_status[username] = {
                        'active': False,
                        'last_failed': time.time(),
                        'retry_after': time.time() + 3600  # Retry after 1 hour
                    }
                    logger.error(f"Failed to initialize session for {username}")
            
            if not self.sessions:
                raise RuntimeError("No Instagram accounts could be logged in")
            
            self.initialized = True
            logger.info(f"Instagram session manager initialized with {len(self.sessions)} active sessions")
    
    def get_best_session(self) -> Tuple[str, instaloader.Instaloader]:
        """Get the best available session considering rate limits"""
        if not self.initialized:
            self.initialize_sessions()
        
        with self.lock:
            # Filter active sessions
            active_sessions = {
                username: session for username, session in self.sessions.items()
                if self.account_status[username]['active']
            }
            
            if not active_sessions:
                raise RuntimeError("No active Instagram sessions available")
            
            # Find session with lowest usage
            best_username = min(
                active_sessions.keys(),
                key=lambda u: self.account_status[u]['request_count']
            )
            
            # Check rate limits
            if not self.rate_limiter.can_make_request(best_username):
                # Try to find an alternative session
                for username in active_sessions.keys():
                    if self.rate_limiter.can_make_request(username):
                        best_username = username
                        break
                else:
                    # All sessions are rate limited, wait for the best one
                    self.rate_limiter.wait_if_needed(best_username)
            
            return best_username, active_sessions[best_username]
    
    def record_usage(self, username: str, success: bool = True):
        """Record usage statistics"""
        with self.lock:
            if username in self.account_status:
                self.account_status[username]['last_used'] = time.time()
                self.account_status[username]['request_count'] += 1
                
                if not success:
                    # Mark as temporarily inactive on failure
                    self.account_status[username]['active'] = False
                    self.account_status[username]['retry_after'] = time.time() + 1800  # 30 minutes
        
        self.rate_limiter.record_request(username)
    
    def refresh_inactive_sessions(self):
        """Periodically try to reactivate failed sessions"""
        current_time = time.time()
        
        for username, status in self.account_status.items():
            if not status['active'] and current_time > status.get('retry_after', 0):
                account = next((acc for acc in self.accounts if acc['username'] == username), None)
                if account:
                    logger.info(f"Attempting to reactivate session for {username}")
                    session = self.try_login(account)
                    if session:
                        with self.lock:
                            self.sessions[username] = session
                            self.account_status[username]['active'] = True
                            self.account_status[username]['request_count'] = 0
                        logger.info(f"Session reactivated for {username}")

# Global instance
_session_manager = InstagramSessionManager()

def get_session_manager() -> InstagramSessionManager:
    """Get the global session manager instance"""
    return _session_manager

def get_instaloader_instance() -> instaloader.Instaloader:
    """Get an available Instaloader instance (backward compatibility)"""
    username, session = _session_manager.get_best_session()
    return session

def initialize_instagram_sessions():
    """Initialize Instagram sessions (call this at Django startup)"""
    _session_manager.initialize_sessions()

def get_instagram_session_with_tracking():
    """Get Instagram session with usage tracking"""
    username, session = _session_manager.get_best_session()
    return username, session