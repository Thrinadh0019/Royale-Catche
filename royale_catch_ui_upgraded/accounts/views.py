import json
import os
import uuid
from datetime import datetime, timezone

from bson import ObjectId
from bson.errors import InvalidId
from django.conf import settings
from django.contrib import messages
from django.contrib.auth.hashers import check_password, make_password
from django.http import JsonResponse
from django.shortcuts import redirect, render
from django.views.decorators.csrf import csrf_protect
from django.views.decorators.http import require_POST

from .mongo import orders_collection, products_collection, users_collection

# ---------------------------------------------------------------------
# Default products, seeded into the `products` collection the first
# time the app runs against an empty database. After that, all product
# data (including anything admins add) lives entirely in MongoDB.
# ---------------------------------------------------------------------
DEFAULT_PRODUCTS = [
    {'name': 'Small', 'unit': '500g pack', 'price': 500, 'available': True},
    {'name': 'Medium', 'unit': '500g pack', 'price': 550, 'available': True},
    {'name': 'Large', 'unit': '500g pack', 'price': 600, 'available': True},
]

PRODUCT_IMAGE_SUBDIR = 'products'  # files land in MEDIA_ROOT/products/


def _ensure_default_products():
    """Seed a few starter products if the collection is empty."""
    if products_collection.count_documents({}) == 0:
        now = datetime.now(timezone.utc)
        for p in DEFAULT_PRODUCTS:
            products_collection.insert_one({**p, 'created_at': now})


def _save_product_image(uploaded_file):
    """
    Save an uploaded image under MEDIA_ROOT/products/ with a random
    filename (avoids collisions/overwrites) and return the relative
    path to store on the product document, e.g. 'products/abc123.jpg'.
    Returns None if no file was given.
    """
    if not uploaded_file:
        return None

    ext = os.path.splitext(uploaded_file.name)[1].lower() or '.jpg'
    filename = f'{uuid.uuid4().hex}{ext}'

    target_dir = os.path.join(settings.MEDIA_ROOT, PRODUCT_IMAGE_SUBDIR)
    os.makedirs(target_dir, exist_ok=True)

    target_path = os.path.join(target_dir, filename)
    with open(target_path, 'wb') as f:
        for chunk in uploaded_file.chunks():
            f.write(chunk)

    return f'{PRODUCT_IMAGE_SUBDIR}/{filename}'


def _delete_product_image(relative_path):
    """Best-effort delete of an old product image file."""
    if not relative_path:
        return
    full_path = os.path.join(settings.MEDIA_ROOT, relative_path)
    try:
        if os.path.isfile(full_path):
            os.remove(full_path)
    except OSError:
        pass  # not worth failing the request over a stray file


def _serialize_product(p):
    image_path = p.get('image')
    return {
        'id': str(p['_id']),
        'name': p['name'],
        'unit': p.get('unit', ''),
        'price': p['price'],
        'available': p.get('available', True),
        'image_url': (settings.MEDIA_URL + image_path) if image_path else None,
    }


def _current_user(request):
    """Return the logged-in user's Mongo document, or None."""
    username = request.session.get('username')
    if not username:
        return None
    return users_collection.find_one({'username': username})


def _require_admin(request):
    """Return the logged-in user's doc if they're an admin, else None."""
    user = _current_user(request)
    if user and user.get('is_admin'):
        return user
    return None


def signup_view(request):
    if request.session.get('username'):
        return redirect('dashboard')

    if request.method == 'POST':
        username = request.POST.get('username', '').strip()
        email = request.POST.get('email', '').strip()
        password = request.POST.get('password', '')
        confirm = request.POST.get('confirm_password', '')

        if not username or not password:
            messages.error(request, 'Username and password are required.')
        elif password != confirm:
            messages.error(request, 'Passwords do not match.')
        elif users_collection.find_one({'username': username}):
            messages.error(request, 'That username is already taken.')
        else:
            users_collection.insert_one({
                'username': username,
                'email': email,
                'password': make_password(password),  # hashed, never store plaintext
                'created_at': datetime.now(timezone.utc),
            })
            # Log the user straight in after signup, no separate sign-in step.
            request.session['username'] = username
            messages.success(request, 'Account created successfully!')
            return redirect('dashboard')

    return render(request, 'signup.html')


def signin_view(request):
    if request.session.get('username'):
        user = _current_user(request)
        if user and user.get('is_admin'):
            return redirect('admin_dashboard')
        return redirect('dashboard')

    if request.method == 'POST':
        username = request.POST.get('username', '').strip()
        password = request.POST.get('password', '')

        user = users_collection.find_one({'username': username})
        if user and check_password(password, user['password']):
            request.session['username'] = username
            users_collection.update_one(
                {'username': username},
                {'$set': {'last_login': datetime.now(timezone.utc)}},
            )
            if user.get('is_admin'):
                return redirect('admin_dashboard')
            return redirect('dashboard')
        else:
            messages.error(request, 'Invalid username or password.')

    return render(request, 'signin.html')


def signout_view(request):
    request.session.flush()
    return redirect('signin')


def dashboard_view(request):
    user = _current_user(request)
    if not user:
        return redirect('signin')

    _ensure_default_products()

    # Only show products the admin has marked available.
    products = [
        _serialize_product(p)
        for p in products_collection.find({'available': True}).sort('price', 1)
    ]

    recent_orders = list(
        orders_collection.find({'username': user['username']})
        .sort('created_at', -1)
        .limit(10)
    )
    for order in recent_orders:
        order['id'] = str(order['_id'])

    return render(request, 'dashboard.html', {
        'username': user['username'],
        'email': user.get('email', ''),
        'products': products,
        'orders': recent_orders,
    })


@require_POST
@csrf_protect
def place_order_view(request):
    """
    Accepts JSON: {"items": {"<product_id>": 2, ...}, "address": "..."}
    Looks up each product fresh from MongoDB so price/availability can
    never be spoofed from the browser. Saves the order to `orders`.
    """
    user = _current_user(request)
    if not user:
        return JsonResponse({'ok': False, 'error': 'Not logged in.'}, status=401)

    try:
        payload = json.loads(request.body or '{}')
    except json.JSONDecodeError:
        return JsonResponse({'ok': False, 'error': 'Invalid request.'}, status=400)

    raw_items = payload.get('items', {})
    address = str(payload.get('address', '')).strip()[:400]

    if not address:
        return JsonResponse({'ok': False, 'error': 'Please enter a delivery address.'}, status=400)

    if not isinstance(raw_items, dict):
        return JsonResponse({'ok': False, 'error': 'Invalid cart.'}, status=400)

    line_items = []
    total = 0
    for product_id, qty in raw_items.items():
        try:
            qty = int(qty)
        except (TypeError, ValueError):
            qty = 0
        if qty <= 0:
            continue

        try:
            product = products_collection.find_one({
                '_id': ObjectId(product_id),
                'available': True,
            })
        except InvalidId:
            product = None

        if not product:
            continue  # skip unknown / no-longer-available products silently

        subtotal = qty * product['price']
        total += subtotal
        line_items.append({
            'product_id': str(product['_id']),
            'label': product['name'],
            'unit_price': product['price'],
            'quantity': qty,
            'subtotal': subtotal,
        })

    if not line_items:
        return JsonResponse({'ok': False, 'error': 'Your cart is empty.'}, status=400)

    order = {
        'username': user['username'],
        'items': line_items,
        'total': total,
        'address': address,
        'status': 'pending',
        'created_at': datetime.now(timezone.utc),
    }
    result = orders_collection.insert_one(order)

    return JsonResponse({
        'ok': True,
        'order_id': str(result.inserted_id),
        'total': total,
    })


def admin_dashboard_view(request):
    """
    Admin-only view: lists every order placed by every user, revenue
    summary stats, and product management (add / enable / disable).
    """
    admin = _require_admin(request)
    if not admin:
        return redirect('signin')

    _ensure_default_products()

    all_orders = list(orders_collection.find().sort('created_at', -1))
    for order in all_orders:
        order['id'] = str(order['_id'])

    total_revenue = sum(o.get('total', 0) for o in all_orders)
    total_orders = len(all_orders)
    pending_orders = sum(1 for o in all_orders if o.get('status') == 'pending')

    all_products = [
        _serialize_product(p)
        for p in products_collection.find().sort('price', 1)
    ]

    return render(request, 'admin_dashboard.html', {
        'admin_username': admin['username'],
        'orders': all_orders,
        'total_revenue': total_revenue,
        'total_orders': total_orders,
        'pending_orders': pending_orders,
        'products': all_products,
    })


@require_POST
@csrf_protect
def admin_update_order_status_view(request, order_id):
    """Admin-only: update an order's status (pending / confirmed / delivered)."""
    admin = _require_admin(request)
    if not admin:
        return JsonResponse({'ok': False, 'error': 'Not authorized.'}, status=403)

    new_status = request.POST.get('status', '').strip().lower()
    if new_status not in {'pending', 'confirmed', 'delivered'}:
        return JsonResponse({'ok': False, 'error': 'Invalid status.'}, status=400)

    try:
        oid = ObjectId(order_id)
    except InvalidId:
        return JsonResponse({'ok': False, 'error': 'Invalid order id.'}, status=400)

    orders_collection.update_one({'_id': oid}, {'$set': {'status': new_status}})
    return JsonResponse({'ok': True})


@require_POST
@csrf_protect
def admin_add_product_view(request):
    """
    Admin-only: add a new product, optionally with a photo. Saved
    straight to MongoDB's `products` collection, and becomes visible
    to every user on the shop page immediately (dashboard reads live
    from this collection).
    """
    admin = _require_admin(request)
    if not admin:
        messages.error(request, 'Not authorized.')
        return redirect('signin')

    name = request.POST.get('name', '').strip()
    unit = request.POST.get('unit', '').strip() or '500g pack'
    price_raw = request.POST.get('price', '').strip()
    image_file = request.FILES.get('image')

    try:
        price = int(price_raw)
    except ValueError:
        price = None

    if not name or price is None or price <= 0:
        messages.error(request, 'Please provide a valid product name and price.')
    else:
        image_path = _save_product_image(image_file)
        products_collection.insert_one({
            'name': name,
            'unit': unit,
            'price': price,
            'image': image_path,  # None if no photo was uploaded
            'available': True,
            'created_at': datetime.now(timezone.utc),
        })
        messages.success(request, f'"{name}" added to the shop.')

    return redirect('admin_dashboard')


@require_POST
@csrf_protect
def admin_edit_product_view(request, product_id):
    """
    Admin-only: edit a product's name/unit/price, and optionally
    replace its photo. Uploading a new photo removes the old file;
    leaving the photo field blank keeps the existing image.
    """
    admin = _require_admin(request)
    if not admin:
        messages.error(request, 'Not authorized.')
        return redirect('signin')

    try:
        oid = ObjectId(product_id)
    except InvalidId:
        messages.error(request, 'Invalid product.')
        return redirect('admin_dashboard')

    product = products_collection.find_one({'_id': oid})
    if not product:
        messages.error(request, 'Product not found.')
        return redirect('admin_dashboard')

    name = request.POST.get('name', '').strip()
    unit = request.POST.get('unit', '').strip() or '500g pack'
    price_raw = request.POST.get('price', '').strip()
    image_file = request.FILES.get('image')

    try:
        price = int(price_raw)
    except ValueError:
        price = None

    if not name or price is None or price <= 0:
        messages.error(request, 'Please provide a valid product name and price.')
        return redirect('admin_dashboard')

    update = {'name': name, 'unit': unit, 'price': price}

    if image_file:
        new_image_path = _save_product_image(image_file)
        update['image'] = new_image_path
        _delete_product_image(product.get('image'))  # clean up the old file

    products_collection.update_one({'_id': oid}, {'$set': update})
    messages.success(request, f'"{name}" updated.')
    return redirect('admin_dashboard')


@require_POST
@csrf_protect
def admin_toggle_product_view(request, product_id):
    """Admin-only: show/hide a product from the shop without deleting it."""
    admin = _require_admin(request)
    if not admin:
        return JsonResponse({'ok': False, 'error': 'Not authorized.'}, status=403)

    try:
        oid = ObjectId(product_id)
    except InvalidId:
        return JsonResponse({'ok': False, 'error': 'Invalid product id.'}, status=400)

    product = products_collection.find_one({'_id': oid})
    if not product:
        return JsonResponse({'ok': False, 'error': 'Product not found.'}, status=404)

    new_state = not product.get('available', True)
    products_collection.update_one({'_id': oid}, {'$set': {'available': new_state}})
    return JsonResponse({'ok': True, 'available': new_state})


@require_POST
@csrf_protect
def admin_delete_product_view(request, product_id):
    """Admin-only: permanently remove a product (and its photo file, if any)."""
    admin = _require_admin(request)
    if not admin:
        return JsonResponse({'ok': False, 'error': 'Not authorized.'}, status=403)

    try:
        oid = ObjectId(product_id)
    except InvalidId:
        return JsonResponse({'ok': False, 'error': 'Invalid product id.'}, status=400)

    product = products_collection.find_one({'_id': oid})
    if product:
        _delete_product_image(product.get('image'))
    products_collection.delete_one({'_id': oid})
    return JsonResponse({'ok': True})
