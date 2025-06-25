from django.shortcuts import render

# Create your views here.
from django.shortcuts import render, get_object_or_404
from .models import BlogPost, BlogCategory

def blog_list(request):
    posts = BlogPost.objects.filter(is_published=True).order_by('-created_at')
    return render(request, 'blog/blog_list.html', {'posts': posts})

def blog_detail(request, slug):
    post = get_object_or_404(BlogPost, slug=slug, is_published=True)
    return render(request, 'blog/blog_detail.html', {'post': post})



from django.shortcuts import render, redirect
from django.core.mail import send_mail,mail_admins
from django.conf import settings
from .forms import ContactForm
from .models import ContactMessage
from django.contrib import messages

def contact_view(request):
    if request.method == 'POST':
        form = ContactForm(request.POST, request.FILES)
        if form.is_valid():
          message = form.save(commit=False)
          message.user_ip = get_client_ip(request)
          message.user_agent = request.META.get('HTTP_USER_AGENT', '')
          message.save()

          # Confirmation to user
          send_mail(
              subject="Thank you for contacting us!",
              message=f"Hi {message.name},\n\nWe have received your message and will get back to you shortly.\n\nRegards,\nInstaSave Team",
              from_email=settings.DEFAULT_FROM_EMAIL,
              recipient_list=[message.email],
              fail_silently=True
          )

          # Copy to admin
          mail_admins(
              subject=f"New Contact Message: {message.subject}",
              message=f"From: {message.name} <{message.email}>\n\n{message.message}\n\nFile: {message.file.url if message.file else 'No file'}\nIP: {message.user_ip}\nAgent: {message.user_agent}",
              fail_silently=True
          )

          messages.success(request, "Your message has been sent successfully.")
          return redirect('contact')
    else:
        form = ContactForm()
    return render(request, 'contact.html', {'form': form})


def get_client_ip(request):
    x_forwarded = request.META.get('HTTP_X_FORWARDED_FOR')
    if x_forwarded:
        return x_forwarded.split(',')[0]
    return request.META.get('REMOTE_ADDR')
