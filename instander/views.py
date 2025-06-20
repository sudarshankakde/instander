from django.shortcuts import render, get_object_or_404, redirect
from django.http import HttpResponse, JsonResponse
from django.views import View
from django.views.decorators.csrf import csrf_exempt
import json
from .downloader import (
    is_instagram_url,
    is_facebook_url,
    fetch_facebook_video,
    detect_content_type
    ,
    fetch_instagram_media
)
def home(request):
  return render(request, 'index.html')


@csrf_exempt
def download_instagram_reels(request):
    return handle_download(request, expected_type="reel")


@csrf_exempt
def download_instagram_posts(request):
    return handle_download(request, expected_type="post")


@csrf_exempt
def download_facebook_video(request):
    return handle_download(request, expected_type="facebook")


def handle_download(request, expected_type):
    if request.method != 'POST':
        return JsonResponse({'error': 'Only POST allowed'}, status=405)

    url = request.POST.get('url')
    is_htmx = request.headers.get("HX-Request") == "true"

    if not url:
        context = {'error': 'No URL provided'}
        return render(request, 'partials/download_result.html' if is_htmx else 'download.html', context)

    try:
        if is_instagram_url(url):
            content_type = detect_content_type(url)
            if (expected_type == "reel" and content_type != "reel") or (expected_type == "post" and content_type != "post"):
                context = {'error': 'Incorrect content type'}
            else:
                media = fetch_instagram_media(url)
                context = {
                "status": "success",
                "type": "instagram",
                "media": media,
                "url": url
            }

        elif is_facebook_url(url) and expected_type == "facebook":
            media = fetch_facebook_video(url)
            context = {
                "status": "success",
                "type": "facebook_video",
                "media": media,
                "url": url
            }

        else:
            context = {'error': 'Invalid or unsupported URL'}

        return render(request, 'partials/download_result.html' if is_htmx else 'download.html', context)

    except Exception as e:
        context = {'error': str(e)}
        return render(request, 'partials/download_result.html' if is_htmx else 'download.html', context)
      
      
      
import requests
from django.http import HttpResponse   
def proxy_image(request):
    url = request.GET.get("url")
    if not url:
        return HttpResponse("Missing URL", status=400)

    try:
        resp = requests.get(url, stream=True)
        content_type = resp.headers.get("Content-Type", "image/jpeg")
        return HttpResponse(resp.content, content_type=content_type)
    except Exception as e:
        return HttpResponse(f"Failed to fetch image: {e}", status=500)
      
      
      
from urllib.parse import urlparse, unquote
import os    
def proxy_download(request):
    url = request.GET.get("url")
    if not url:
        return HttpResponse("Missing URL", status=400)

    try:
        # Fetch media from source
        response = requests.get(url, stream=True)
        if response.status_code != 200:
            return HttpResponse("Failed to fetch media", status=400)

        # Get filename from URL
        path = urlparse(unquote(url)).path
        filename = os.path.basename(path)

        # Get content type (video/mp4, image/jpeg, etc.)
        content_type = response.headers.get("Content-Type", "application/octet-stream")

        # Return response with appropriate download headers
        resp = HttpResponse(response.content, content_type=content_type)
        resp["Content-Disposition"] = f'attachment; filename="{filename}"'
        return resp

    except Exception as e:
        return HttpResponse(f"Error: {e}", status=500)
      
import io
import zipfile
@csrf_exempt
def download_all_zip(request):
    urls = request.POST.getlist("urls[]")  # Expecting a list of media URLs

    if not urls:
        return HttpResponse("No media URLs provided", status=400)

    zip_buffer = io.BytesIO()
    with zipfile.ZipFile(zip_buffer, "w", zipfile.ZIP_DEFLATED) as zip_file:
        for i, url in enumerate(urls):
            try:
                response = requests.get(url, stream=True)
                if response.status_code == 200:
                    # Extract a name or assign one
                    path = urlparse(unquote(url)).path
                    filename = os.path.basename(path)
                    if not filename:
                        ext = "jpg" if "image" in response.headers.get("Content-Type", "") else "mp4"
                        filename = f"media_{i + 1}.{ext}"
                    zip_file.writestr(filename, response.content)
            except Exception as e:
                continue  # Skip failed downloads

    zip_buffer.seek(0)
    response = HttpResponse(zip_buffer, content_type="application/zip")
    response["Content-Disposition"] = 'attachment; filename="all_media.zip"'
    return response
  
  
  
from utilities.models import ContactMessage
@csrf_exempt
def submit_contact(request):
    if request.method == 'POST':
        name = request.POST.get('name')
        email = request.POST.get('email')
        message = request.POST.get('message')

        if not (name and email and message):
            return JsonResponse({'success': False, 'error': 'All fields are required'})

        ContactMessage.objects.create(name=name, email=email, message=message)
        return JsonResponse({'success': True})

    return JsonResponse({'success': False, 'error': 'Invalid request method'})