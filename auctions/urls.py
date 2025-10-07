from django.urls import path
from . import views

urlpatterns = [
    path('', views.home, name='home'),
    path('login/', views.login_view, name='login'),
    path('logout/', views.logout_view, name='logout'),
    path('register/', views.register_view, name='register'),
    path('history/', views.history, name='history'),
    path('items/new/', views.item_create, name='item_create'),
    path('items/<int:pk>/', views.item_detail, name='item_detail'),
    path('items/<int:pk>/bid/', views.place_bid, name='place_bid'),
    path('items/<int:pk>/buy/', views.buy_now, name='buy_now'),
    path('payments/<int:pk>/gpay/', views.google_pay_start, name='google_pay_start'),
    path('payments/<int:pk>/callback/', views.google_pay_callback, name='google_pay_callback'),
    path('items/<int:pk>/book/', views.book_seat, name='book_seat'),
    path('items/<int:pk>/unbook/', views.unbook_seat, name='unbook_seat'),
    path('join/', views.join_with_code, name='join_with_code'),
    path('items/<int:pk>/preview/start/', views.start_preview, name='start_preview'),
    path('items/<int:pk>/call/start/', views.start_call, name='start_call'),
    path('items/<int:pk>/call/', views.call_room, name='call_room'),
    path('items/<int:pk>/presence/', views.presence_ping, name='presence_ping'),
    path('items/<int:pk>/penalty/pay/', views.pay_penalty, name='pay_penalty'),
    path('items/<int:pk>/settle/', views.settle, name='settle'),
]