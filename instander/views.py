from django.shortcuts import render, get_object_or_404, redirect
from django.http import HttpResponse, JsonResponse
from django.views import View
from django.views.decorators.csrf import csrf_exempt
from django.views.decorators.cache import cache_page
from django.utils.decorators import method_decorator
import json
import logging
from .downloader import (
    is_instagram_url,
    is_facebook_url,
    fetch_facebook_video,
    detect_content_type,
    fetch_instagram_media,
    check_instagram_health,
    refresh_sessions
)

# Configure logging
logger = logging.getLogger(__name__)

def home(request):
    """Home page view"""
    return render(request, 'index.html')

@csrf_exempt
def download_instagram_reels(request):
    """Handle Instagram reels download"""
    return handle_download(request, expected_type="reel")

@csrf_exempt
def download_instagram_posts(request):
    """Handle Instagram posts download"""
    return handle_download(request, expected_type="post")

@csrf_exempt
def download_facebook_video(request):
    """Handle Facebook video download"""
    return handle_download(request, expected_type="facebook")

def handle_download(request, expected_type):
    """
    Enhanced download handler with better error handling and logging
    """
    if request.method != 'POST':
        return JsonResponse({'error': 'Only POST method allowed'}, status=405)

    url = request.POST.get('url', '').strip()
    is_htmx = request.headers.get("HX-Request") == "true"
    
    # Log the request
    logger.info(f"Download request: type={expected_type}, url={url[:100]}...")

    if not url:
        context = {'error': 'No URL provided'}
        return render(request, 'partials/download_result.html' if is_htmx else 'download.html', context)

    try:
        if is_instagram_url(url):
            # Handle Instagram content
            content_type = detect_content_type(url)
            logger.info(f"Detected Instagram content type: {content_type}")
            
            # Validate content type matches expected type
            if (expected_type == "reel" and content_type != "reel") or \
               (expected_type == "post" and content_type not in ["post", "reel"]):  # Allow reels in post handler
                context = {
                    'error': f'Content type mismatch. Expected {expected_type}, got {content_type}',
                    'detected_type': content_type,
                    'expected_type': expected_type
                }
            else:
                try:
                    media = fetch_instagram_media(url)
                    context = {
                        "status": "success",
                        "type": "instagram",
                        "content_type": content_type,
                        "media": media,
                        "url": url,
                        "media_count": len(media)
                    }
                    logger.info(f"Successfully fetched {len(media)} media items from Instagram")
                    
                except Exception as e:
                  # Provide user-friendly error messages
                  error_msg = str(e)
                  if "private" in error_msg.lower() or "restricted" in error_msg.lower():
                      error_msg = "Cannot download private or restricted videos"
                  elif "not available" in error_msg.lower() or "removed" in error_msg.lower():
                      error_msg = "Video is not available or has been removed"
                  elif "timeout" in error_msg.lower():
                      error_msg = "Request timeout - video may be too large"
                  
                  context = {
                      'error': error_msg,
                      'technical_error': str(e) if request.user.is_staff else None
                  }

        else:
            # Invalid URL or unsupported platform
            context = {
                'error': 'Invalid or unsupported URL. Please provide a valid Instagram or Facebook URL',
                'supported_platforms': ['Instagram Posts', 'Instagram Reels', 'Facebook Videos']
            }

        return render(request, 'partials/download_result.html' if is_htmx else 'download.html', context)

    except Exception as e:
        logger.error(f"Unexpected error in handle_download: {e}")
        context = {
            'error': 'An unexpected error occurred. Please try again later.',
            'technical_error': str(e) if request.user.is_staff else None
        }
        return render(request, 'partials/download_result.html' if is_htmx else 'download.html', context)

# --- Proxy Functions ---
import requests
from django.http import HttpResponse
from django.views.decorators.cache import cache_page

@cache_page(60 * 15)  # Cache for 15 minutes
def proxy_image(request):
    """Proxy images to avoid CORS issues with caching"""
    url = request.GET.get("url")
    if not url:
        return HttpResponse("Missing URL parameter", status=400)

    try:
        # Add headers to mimic a real browser request
        headers = {
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36',
            'Referer': 'https://www.instagram.com/',
            'Accept': 'image/webp,image/apng,image/*,*/*;q=0.8'
        }
        
        response = requests.get(url, stream=True, headers=headers, timeout=30)
        response.raise_for_status()
        
        content_type = response.headers.get("Content-Type", "image/jpeg")
        
        # Create response with proper headers
        proxy_response = HttpResponse(response.content, content_type=content_type)
        proxy_response['Cache-Control'] = 'public, max-age=3600'  # Cache for 1 hour
        
        return proxy_response
        
    except requests.exceptions.Timeout:
        return HttpResponse("Request timeout", status=504)
    except requests.exceptions.RequestException as e:
        logger.error(f"Proxy image error: {e}")
        return HttpResponse("Failed to fetch image", status=500)
    except Exception as e:
        logger.error(f"Unexpected proxy image error: {e}")
        return HttpResponse("Internal error", status=500)

from urllib.parse import urlparse, unquote
import os

def proxy_download(request):
    """Proxy downloads with enhanced error handling"""
    url = request.GET.get("url")
    if not url:
        return HttpResponse("Missing URL parameter", status=400)

    try:
        # Add headers to mimic a real browser request
        headers = {
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36',
            'Referer': 'https://www.instagram.com/',
        }
        
        # Stream the response to handle large files
        response = requests.get(url, stream=True, headers=headers, timeout=60)
        response.raise_for_status()

        # Extract filename from URL
        try:
            path = urlparse(unquote(url)).path
            filename = os.path.basename(path)
            if not filename or '.' not in filename:
                # Generate filename based on content type
                content_type = response.headers.get("Content-Type", "")
                if "video" in content_type:
                    filename = f"video_{int(time.time())}.mp4"
                elif "image" in content_type:
                    filename = f"image_{int(time.time())}.jpg"
                else:
                    filename = f"media_{int(time.time())}"
        except:
            filename = f"download_{int(time.time())}"

        # Get content type
        content_type = response.headers.get("Content-Type", "application/octet-stream")

        # Create download response
        download_response = HttpResponse(
            response.iter_content(chunk_size=8192),
            content_type=content_type
        )
        download_response["Content-Disposition"] = f'attachment; filename="{filename}"'
        
        # Add content length if available
        content_length = response.headers.get("Content-Length")
        if content_length:
            download_response["Content-Length"] = content_length

        return download_response

    except requests.exceptions.Timeout:
        return HttpResponse("Download timeout - file may be too large", status=504)
    except requests.exceptions.RequestException as e:
        logger.error(f"Proxy download error: {e}")
        return HttpResponse("Failed to download media", status=500)
    except Exception as e:
        logger.error(f"Unexpected proxy download error: {e}")
        return HttpResponse("Download error occurred", status=500)

import io
import zipfile
import time

@csrf_exempt
def download_all_zip(request):
    """Create and download a ZIP file containing all media"""
    urls = request.POST.getlist("urls[]")

    if not urls:
        return HttpResponse("No media URLs provided", status=400)

    if len(urls) > 20:  # Limit to prevent abuse
        return HttpResponse("Too many files requested (max 20)", status=400)

    try:
        zip_buffer = io.BytesIO()
        successful_downloads = 0
        
        with zipfile.ZipFile(zip_buffer, "w", zipfile.ZIP_DEFLATED) as zip_file:
            headers = {
                'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36',
                'Referer': 'https://www.instagram.com/',
            }
            
            for i, url in enumerate(urls, 1):
                try:
                    logger.info(f"Downloading file {i}/{len(urls)} for ZIP")
                    response = requests.get(url, stream=True, headers=headers, timeout=30)
                    response.raise_for_status()
                    
                    # Generate filename
                    try:
                        path = urlparse(unquote(url)).path
                        filename = os.path.basename(path)
                        if not filename or '.' not in filename:
                            content_type = response.headers.get("Content-Type", "")
                            if "video" in content_type:
                                filename = f"video_{i}.mp4"
                            elif "image" in content_type:
                                filename = f"image_{i}.jpg"
                            else:
                                filename = f"media_{i}"
                    except:
                        filename = f"media_{i}"
                    
                    # Ensure unique filename in ZIP
                    counter = 1
                    original_filename = filename
                    while filename in [info.filename for info in zip_file.filelist]:
                        name, ext = original_filename.rsplit('.', 1) if '.' in original_filename else (original_filename, '')
                        filename = f"{name}_{counter}.{ext}" if ext else f"{name}_{counter}"
                        counter += 1
                    
                    zip_file.writestr(filename, response.content)
                    successful_downloads += 1
                    
                except Exception as e:
                    logger.warning(f"Failed to download file {i} for ZIP: {e}")
                    continue

        if successful_downloads == 0:
            return HttpResponse("No files could be downloaded", status=500)

        zip_buffer.seek(0)
        
        # Create response
        response = HttpResponse(zip_buffer.getvalue(), content_type="application/zip")
        timestamp = int(time.time())
        response["Content-Disposition"] = f'attachment; filename="media_collection_{timestamp}.zip"'
        
        logger.info(f"ZIP created with {successful_downloads}/{len(urls)} files")
        return response
        
    except Exception as e:
        logger.error(f"ZIP creation error: {e}")
        return HttpResponse("Failed to create ZIP file", status=500)

# --- Contact Form ---
from utilities.models import ContactMessage

@csrf_exempt
def submit_contact(request):
    """Handle contact form submission"""
    if request.method != 'POST':
        return JsonResponse({'success': False, 'error': 'Invalid request method'})

    try:
        name = request.POST.get('name', '').strip()
        email = request.POST.get('email', '').strip()
        message = request.POST.get('message', '').strip()

        # Validation
        if not all([name, email, message]):
            return JsonResponse({'success': False, 'error': 'All fields are required'})

        if len(name) > 100:
            return JsonResponse({'success': False, 'error': 'Name is too long'})
        
        if len(message) > 1000:
            return JsonResponse({'success': False, 'error': 'Message is too long'})
      
        # Save contact message
        ContactMessage.objects.create(name=name, email=email, message=message)
        logger.info(f"Contact form submitted by {name} ({email})")
        
        return JsonResponse({'success': True, 'message': 'Thank you for your message!'})

    except Exception as e:
        logger.error(f"Contact form error: {e}")
        return JsonResponse({'success': False, 'error': 'Failed to submit message. Please try again.'})

# --- Health Check and Admin Functions ---
def instagram_health_check(request):
    """Check Instagram service health (for monitoring)"""
    if not request.user.is_staff:
        return JsonResponse({'error': 'Unauthorized'}, status=403)
    
    health_data = check_instagram_health()
    return JsonResponse(health_data)

@csrf_exempt
def refresh_instagram_sessions(request):
    """Manually refresh Instagram sessions (admin only)"""
    if not request.user.is_staff:
        return JsonResponse({'error': 'Unauthorized'}, status=403)
    
    if request.method != 'POST':
        return JsonResponse({'error': 'Only POST method allowed'}, status=405)
    
    try:
        success = refresh_sessions()
        if success:
            return JsonResponse({'success': True, 'message': 'Sessions refresh initiated'})
        else:
            return JsonResponse({'success': False, 'error': 'Failed to refresh sessions'})
    except Exception as e:
        logger.error(f"Session refresh error: {e}")
        return JsonResponse({'success': False, 'error': str(e)})
                   