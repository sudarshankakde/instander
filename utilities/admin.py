from django.contrib import admin
from .models import ContactMessage,BlogPost, BlogCategory

@admin.register(ContactMessage)
class ContactAdmin(admin.ModelAdmin):
    list_display = ('name', 'email', 'subject', 'created_at')
    readonly_fields = ('user_ip', 'user_agent', 'created_at')
    
    
from tinymce.widgets import TinyMCE
from django.db import models
@admin.register(BlogPost)
class BlogPostAdmin(admin.ModelAdmin):
    prepopulated_fields = {"slug": ("title",)}
    list_display = ('title', 'category', 'is_published', 'created_at')
    formfield_overrides = {
        models.TextField: {'widget': TinyMCE(attrs={'cols': 80, 'rows': 30})},
    }

admin.site.register(BlogCategory)