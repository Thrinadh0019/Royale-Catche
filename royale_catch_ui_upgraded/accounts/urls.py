from django.urls import path

from . import views

urlpatterns = [
    path('signup/', views.signup_view, name='signup'),
    path('signin/', views.signin_view, name='signin'),
    path('signout/', views.signout_view, name='signout'),
    path('dashboard/', views.dashboard_view, name='dashboard'),
    path('place-order/', views.place_order_view, name='place_order'),

    path('admin-dashboard/', views.admin_dashboard_view, name='admin_dashboard'),
    path(
        'admin-dashboard/orders/<str:order_id>/status/',
        views.admin_update_order_status_view,
        name='admin_update_order_status',
    ),
    path('admin-dashboard/products/add/', views.admin_add_product_view, name='admin_add_product'),
    path(
        'admin-dashboard/products/<str:product_id>/edit/',
        views.admin_edit_product_view,
        name='admin_edit_product',
    ),
    path(
        'admin-dashboard/products/<str:product_id>/toggle/',
        views.admin_toggle_product_view,
        name='admin_toggle_product',
    ),
    path(
        'admin-dashboard/products/<str:product_id>/delete/',
        views.admin_delete_product_view,
        name='admin_delete_product',
    ),
]
