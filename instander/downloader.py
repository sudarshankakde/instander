import re
import os
import json
import subprocess
import instaloader
import logging
import time
import random
from typing import List, Dict, Optional
from .insta_login import get_session_manager, get_instagram_session_with_tracking
from django.conf import settings
from django.core.cache import cache

# Configure logging
logger = logging.getLogger(__name__)

# Configuration
CACHE_TIMEOUT = 300  # 5 minutes cache for media URLs
MAX_RETRIES = 3
RETRY_DELAY = 5

# --- URL Validation ---
def is_instagram_url(url: str) -> bool:
    """Check if URL is from Instagram"""
    return "instagram.com" in url

def is_facebook_url(url: str) -> bool:
    """Check if URL is from Facebook"""
    return "facebook.com" in url or "fb.watch" in url

# --- Instagram Username Extraction from Story URL ---
def extract_username_from_story_url(url: str) -> Optional[str]:
    """Extract username from Instagram story URL"""
    match = re.search(r"instagram\.com/stories/([a-zA-Z0-9._]+)/", url)
    return match.group(1) if match else None

# --- Media Type Detection ---
def detect_media_type(url: str) -> str:
    """Detect if media is video or image based on URL"""
    if url and url.endswith((".mp4", ".webm", ".mov")):
        return "video"
    else:
        return "image"

# --- Instagram Content Type Detection ---
def detect_content_type(url: str) -> str:
    """Detect the type of Instagram/Facebook content"""
    if "facebook.com" in url or "fb.watch" in url:
        if "/watch/" in url or "/videos/" in url:
            return "facebook_video"
        elif "reel" in url:
            return "facebook_reel"
    elif "instagram.com" in url:
        if "/reel/" in url:
            return "reel"
        elif "/p/" in url:
            return "post"
        elif "/stories/" in url:
            return "story"
        elif "/tv/" in url:
            return "igtv"
    return "unknown"

def extract_shortcode(url: str) -> Optional[str]:
    """Extract shortcode from Instagram URL"""
    shortcode_match = re.search(r"/(p|reel|tv)/([a-zA-Z0-9_-]+)", url)
    return shortcode_match.group(2) if shortcode_match else None

def get_cached_media(url: str) -> Optional[List[Dict]]:
    """Get cached media data if available"""
    cache_key = f"instagram_media_{hash(url)}"
    return cache.get(cache_key)

def cache_media(url: str, media_data: List[Dict]) -> None:
    """Cache media data"""
    cache_key = f"instagram_media_{hash(url)}"
    cache.set(cache_key, media_data, CACHE_TIMEOUT)

# --- Enhanced Instagram Media Fetcher ---
def fetch_instagram_media(url: str) -> List[Dict]:
    """
    Fetch Instagram media with enhanced error handling and caching
    """
    # Check cache first
    cached_data = get_cached_media(url)
    if cached_data:
        logger.info(f"Returning cached data for {url}")
        return cached_data
    
    shortcode = extract_shortcode(url)
    if not shortcode:
        raise ValueError("Invalid Instagram post URL - could not extract shortcode")
    
    session_manager = get_session_manager()
    
    username, L = get_instagram_session_with_tracking()
    for attempt in range(MAX_RETRIES):
        try:
            logger.info(f"Attempt {attempt + 1}: Using account {username} to fetch {shortcode}")
            
            # Add small random delay to avoid seeming too automated
            time.sleep(random.uniform(1, 3))
            
            # Fetch the post
            post = instaloader.Post.from_shortcode(L.context, shortcode)
            
            results = []
            
            if post.typename == 'GraphSidecar':  # Carousel (multiple media)
                logger.info(f"Processing carousel post with {post.mediacount} items")
                
                for i, node in enumerate(post.get_sidecar_nodes()):
                    try:
                        if node.is_video:
                            results.append({
                                "type": "video",
                                "url": node.video_url,
                                "thumbnail": node.display_url,
                                "index": i
                            })
                            logger.debug(f"Added video {i+1}")
                        else:
                            results.append({
                                "type": "image",
                                "url": node.display_url,
                                "index": i
                            })
                            logger.debug(f"Added image {i+1}")
                    except Exception as e:
                        logger.warning(f"Failed to process carousel item {i}: {e}")
                        continue
                        
            else:  # Single image or video
                try:
                    if post.is_video:
                        results.append({
                            "type": "video",
                            "url": post.video_url,
                            "thumbnail": post.url
                        })
                        logger.info("Added single video")
                    else:
                        results.append({
                            "type": "image",
                            "url": post.url
                        })
                        logger.info("Added single image")
                except Exception as e:
                    logger.error(f"Failed to process single media: {e}")
                    raise
            
            if not results:
                raise ValueError("No media found in the post")
            
            # Record successful usage
            session_manager.record_usage(username, success=True)
            
            # Cache the results
            cache_media(url, results)
            
            logger.info(f"Successfully fetched {len(results)} media items from {shortcode}")
            return results
            
        except instaloader.exceptions.LoginRequiredException:
            logger.error(f"Login required for account {username}")
            if username:
                session_manager.record_usage(username, success=False)
            
            if attempt < MAX_RETRIES - 1:
                logger.info(f"Retrying with different account...")
                time.sleep(RETRY_DELAY)
                continue
            else:
                raise RuntimeError("All Instagram accounts require re-authentication")
                
        except instaloader.exceptions.ProfileNotExistsException:
            logger.error(f"Post {shortcode} not found or is private")
            raise ValueError("Post not found or is private")
            
        except instaloader.exceptions.PrivateProfileNotFollowedException:
            logger.error(f"Post {shortcode} is from a private account")
            raise ValueError("Cannot access private account content")
            
        except instaloader.exceptions.TooManyRequestsException:
            logger.warning(f"Rate limit hit for account {username}")
            if username:
                session_manager.record_usage(username, success=False)
            
            if attempt < MAX_RETRIES - 1:
                wait_time = RETRY_DELAY * (2 ** attempt)  # Exponential backoff
                logger.info(f"Waiting {wait_time} seconds before retry...")
                time.sleep(wait_time)
                continue
            else:
                raise RuntimeError("Instagram rate limit exceeded for all accounts")
                
        except Exception as e:
            logger.error(f"Unexpected error fetching Instagram media: {e}")
            if username:
                session_manager.record_usage(username, success=False)
            
            if attempt < MAX_RETRIES - 1:
                logger.info(f"Retrying after error... ({attempt + 1}/{MAX_RETRIES})")
                time.sleep(RETRY_DELAY)
                continue
            else:
                raise RuntimeError(f"Failed to fetch Instagram media after {MAX_RETRIES} attempts: {e}")
    
    raise RuntimeError("Failed to fetch Instagram media - all attempts exhausted")

# --- Enhanced Facebook Downloader ---
def fetch_facebook_video(url: str) -> List[Dict]:
    """
    Fetch Facebook video with enhanced error handling and timeout management
    """
    try:
        logger.info(f"Downloading Facebook video: {url}")
        
        # Use yt-dlp with specific options for Facebook
        cmd = [
            "yt-dlp",
            "--no-playlist",
            "--quiet",
            "--dump-json",
            "--socket-timeout", "30",
            "--retries", "3",
            url
        ]
        
        result = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            timeout=60  # Increased timeout
        )
        
        if result.returncode != 0:
            error_msg = result.stderr.strip() if result.stderr else "Unknown error"
            logger.error(f"yt-dlp failed: {error_msg}")
            raise Exception(f"Failed to fetch Facebook video: {error_msg}")
        
        if not result.stdout.strip():
            raise Exception("No metadata returned from yt-dlp")
        
        try:
            metadata = json.loads(result.stdout)
        except json.JSONDecodeError as e:
            logger.error(f"Failed to parse yt-dlp output: {e}")
            raise Exception("Invalid response from video service")
        
        video_url = metadata.get("url")
        if not video_url:
            raise Exception("No video URL found in metadata")
        
        result_data = [{
            "type": "video",
            "url": video_url,
            "title": metadata.get("title", "Facebook Video"),
            "duration": metadata.get("duration"),
            "thumbnail": metadata.get("thumbnail")
        }]
        
        logger.info(f"Successfully fetched Facebook video metadata")
        return result_data
        
    except subprocess.TimeoutExpired:
        logger.error("Timeout while fetching Facebook video")
        raise Exception("Request timeout - the video may be too large or unavailable")
        
    except FileNotFoundError:
        logger.error("yt-dlp not found - please install it")
        raise Exception("Video downloader not available - please contact support")
        
    except Exception as e:
        logger.error(f"Facebook download error: {e}")
        if "private" in str(e).lower():
            raise Exception("Cannot download private or restricted videos")
        elif "not available" in str(e).lower():
            raise Exception("Video is not available or has been removed")
        else:
            raise Exception(f"Failed to download Facebook video: {str(e)}")

# --- Health Check Functions ---
def check_instagram_health() -> Dict[str, any]:
    """Check the health of Instagram session manager"""
    try:
        session_manager = get_session_manager()
        active_sessions = sum(1 for status in session_manager.account_status.values() if status.get('active', False))
        total_sessions = len(session_manager.account_status)
        
        return {
            'status': 'healthy' if active_sessions > 0 else 'unhealthy',
            'active_sessions': active_sessions,
            'total_sessions': total_sessions,
            'initialized': session_manager.initialized
        }
    except Exception as e:
        return {
            'status': 'error',
            'error': str(e)
        }

def refresh_sessions():
    """Manually refresh Instagram sessions"""
    try:
        session_manager = get_session_manager()
        session_manager.refresh_inactive_sessions()
        return True
    except Exception as e:
        logger.error(f"Failed to refresh sessions: {e}")
        return False