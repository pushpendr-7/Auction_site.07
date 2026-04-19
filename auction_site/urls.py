"""
URL configuration for auction_site project.

The `urlpatterns` list routes URLs to views. For more information please see:
    https://docs.djangoproject.com/en/5.2/topics/http/urls/
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
from django.urls import path, include, re_path
from django.conf import settings
from django.conf.urls.static import static
from django.views.static import serve as static_serve
from django.views.generic import RedirectView
from django.http import HttpResponse, Http404
from django.shortcuts import render
from auctions.models import AuctionItem


def robots_txt(request):
    domain = request.build_absolute_uri('/').rstrip('/')
    lines = [
        "User-agent: *",
        "Allow: /",
        "Disallow: /admin/",
        "Disallow: /verify/",
        "Disallow: /wallet/",
        f"Sitemap: {domain}/sitemap.xml",
    ]
    return HttpResponse("\n".join(lines), content_type="text/plain")


def sitemap_xml(request):
    domain = request.build_absolute_uri('/').rstrip('/')
    items = AuctionItem.objects.all().order_by('-ends_at')[:100]
    urls = [
        f"""  <url><loc>{domain}/</loc><changefreq>daily</changefreq><priority>1.0</priority></url>""",
        f"""  <url><loc>{domain}/register/</loc><changefreq>monthly</changefreq><priority>0.7</priority></url>""",
        f"""  <url><loc>{domain}/login/</loc><changefreq>monthly</changefreq><priority>0.5</priority></url>""",
    ]
    for item in items:
        urls.append(
            f"""  <url><loc>{domain}/items/{item.pk}/</loc><changefreq>hourly</changefreq><priority>0.9</priority></url>"""
        )
    xml = '<?xml version="1.0" encoding="UTF-8"?>\n'
    xml += '<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">\n'
    xml += "\n".join(urls)
    xml += "\n</urlset>"
    return HttpResponse(xml, content_type="application/xml")


def custom_404(request, exception=None):
    return render(request, '404.html', status=404)


def custom_500(request):
    return render(request, '500.html', status=500)


handler404 = custom_404
handler500 = custom_500

urlpatterns = [
    path('admin/', admin.site.urls),
    path('robots.txt', robots_txt),
    path('sitemap.xml', sitemap_xml),
    path('', include('auctions.urls')),
    re_path(r'^favicon\.ico$', RedirectView.as_view(url=f"{settings.STATIC_URL}favicon.ico", permanent=True)),
]

# Serve uploaded media files so item images display both locally and on Render.
# static() only works when DEBUG=True, so add an explicit fallback for production.
if settings.DEBUG:
    urlpatterns += static(settings.MEDIA_URL, document_root=settings.MEDIA_ROOT)
else:
    urlpatterns += [
        re_path(r'^media/(?P<path>.*)$', static_serve, {
            'document_root': settings.MEDIA_ROOT,
        }),
    ]
