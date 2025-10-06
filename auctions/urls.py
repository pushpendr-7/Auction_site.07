from django.urls import path
from . import views

urlpatterns = [
    path('', views.home, name='home'),
    path('login/', views.login_view, name='login'),
    path('logout/', views.logout_view, name='logout'),
    path('register/', views.register_view, name='register'),
    path('items/new/', views.item_create, name='item_create'),
    path('items/<int:pk>/', views.item_detail, name='item_detail'),
    path('items/<int:pk>/bid/', views.place_bid, name='place_bid'),
    path('items/<int:pk>/buy/', views.buy_now, name='buy_now'),
    path('payments/<int:pk>/gpay/', views.google_pay_start, name='google_pay_start'),
    path('payments/<int:pk>/callback/', views.google_pay_callback, name='google_pay_callback'),
]