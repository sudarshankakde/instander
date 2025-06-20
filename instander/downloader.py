import re
import os
import json
import subprocess
import instaloader
from .insta_login import get_available_instaloader
import os
from django.conf import settings

file_path = os.path.join(settings.BASE_DIR, "login_accounts.json")

L = get_available_instaloader(file_path)


# --- URL Validation ---
def is_instagram_url(url):
    return "instagram.com" in url

def is_facebook_url(url):
    return "facebook.com" in url or "fb.watch" in url

# --- Instagram Username Extraction from Story URL ---
def extract_username_from_story_url(url):
    match = re.search(r"instagram\\.com/stories/([a-zA-Z0-9._]+)/", url)
    return match.group(1) if match else None

# --- Media Type Detection ---
def detect_media_type(url):
    if url and url.endswith((".mp4", ".webm", ".mov")):
        return "video"
    else:
        return "image"

# --- Instagram Content Type Detection ---
def detect_content_type(url):
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

# --- Instagram Media Fetcher ---
def fetch_instagram_media(url):
    shortcode_match = re.search(r"/(p|reel|tv)/([a-zA-Z0-9_-]+)", url)
    if not shortcode_match:
        raise ValueError("Invalid Instagram post URL")

    shortcode = shortcode_match.group(2)
    try:
        post = instaloader.Post.from_shortcode(L.context, shortcode)
    except Exception as e:
        raise RuntimeError(f"Failed to fetch post: {e}")

    results = []
    if post.typename == 'GraphSidecar':  # Carousel (multiple media)
        for node in post.get_sidecar_nodes():
            if node.is_video:
                results.append({"type": "video", "url": node.video_url})
            else:
                results.append({"type": "image", "url": node.display_url})
    else:  # Single image or video
        if post.is_video:
            results.append({"type": "video", "url": post.video_url})
        else:
            results.append({"type": "image", "url": post.url})

    return results

# --- Facebook Downloader (with subprocess isolation) ---
def fetch_facebook_video(url):
    try:
        print(f"[✔] Downloading Facebook video: {url}")

        result = subprocess.run([
            "yt-dlp",
            "--no-playlist",
            "--quiet",
            "--dump-json",
            url
        ], capture_output=True, text=True, timeout=20)

        if result.returncode != 0:
            raise Exception("Failed to fetch Facebook video metadata")

        metadata = json.loads(result.stdout)
        return [{"type": "video", "url": metadata.get("url")}]

    except subprocess.TimeoutExpired:
        raise Exception("Timeout while trying to fetch Facebook video")
    except Exception as e:
        raise Exception(f"Facebook download error: {e}")

