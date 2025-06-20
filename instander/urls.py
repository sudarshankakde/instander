"""
URL configuration for instander project.

The `urlpatterns` list routes URLs to views. For more information please see:
    https://docs.djangoproject.com/en/4.2/topics/http/urls/
Examples:
Function views
    1. Add an import:  from my_app import views
    2. Add a URL to urlpatterns:  path('', views.home, name='home')
Class-based views
    1. Add an import:  from other_app.views import Home
    2. Add a URL to urlpatterns:  path('', Home.as_view(), name='home')
Including another URLconf
    1. Import the include() function: from django.urls import include, path
    2. Add a URL to urlpatterns:  path('blog/', include('blog.urls'))
"""
from django.contrib import admin
from django.urls import path,include
from . import views
from utilities import views as utilities_views
urlpatterns = [
    path('', views.home, name='home'),
    path('download/reels/', views.download_instagram_reels, name='download_reels'),
    path('download/posts/', views.download_instagram_posts, name='download_posts'),
    path('download/facebook/', views.download_facebook_video, name='download_facebook'),
    path("proxy-image/", views.proxy_image, name="proxy_image"),
    path("download-image/", views.proxy_download, name="proxy_download"),
    path("download_all/", views.download_all_zip, name="download_all_zip"),
    
    # utilities urls
    path('submit-contact/', views.submit_contact, name='submit_contact'),
    path('blog/', utilities_views.blog_list, name='blog_list'),
    path('blog/<slug:slug>/', utilities_views.blog_detail, name='blog_detail'),
    path("contact/", utilities_views.contact_view, name="contact"),
    
    # admin urls
    path('tinymce/', include('tinymce.urls')),
    path('admin/', admin.site.urls),
]


from django.conf.urls.static import static
from django.conf import settings
urlpatterns += static(settings.MEDIA_URL, document_root=settings.MEDIA_ROOT)