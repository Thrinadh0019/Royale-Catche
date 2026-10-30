# Django + MongoDB Sign-In Project

A minimal Django project that connects to a **local MongoDB** instance
(`localhost:27017`) and implements a sign up / sign in / dashboard flow,
storing user accounts as documents in a `users` collection.

## How it's wired up

- `accounts/mongo.py` — creates a `pymongo.MongoClient` pointed at
  `mongodb://localhost:27017/` (configurable in `App/settings.py`)
  and exposes `users_collection`.
- `accounts/views.py` — sign up (hashes password with Django's
  `make_password`), sign in (verifies with `check_password`), and a
  session-based login (`request.session['username']`) — no Django ORM
  `User` model is used, everything is read/written straight to Mongo.
- `accounts/templates/accounts/` — `signin.html`, `signup.html`,
  `dashboard.html` (styled, responsive, extend a shared `base.html`).
- Django's own `sqlite3` database is kept only so Django's built-in
  sessions/admin framework has somewhere to store session rows — no
  application data lives there.

## Setup

1. **Install MongoDB locally** (if you haven't already) and make sure
   it's running on the default port:
   ```bash
   mongod --dbpath /path/to/your/data
   # or, if installed as a service:
   sudo systemctl start mongod
   ```
   Verify it's up: `mongosh` should connect without errors.

2. **Create a virtual environment and install dependencies:**
   ```bash
   python3 -m venv venv
   source venv/bin/activate   # Windows: venv\Scripts\activate
   pip install -r requirements.txt
   ```

3. **Run Django's own migrations** (for sessions/admin, not your data):
   ```bash
   python manage.py migrate
   ```

4. **Start the server:**
   ```bash
   python manage.py runserver
   ```

5. Visit **http://127.0.0.1:8000/** — you'll land on the sign-in page.
   Click "Sign up" to create an account (stored in MongoDB), then sign
   in with it.

## Configuration

All Mongo connection settings live in `App/settings.py`:

```python
MONGO_HOST = 'localhost'
MONGO_PORT = 27017
MONGO_DB_NAME = 'django_app'
MONGO_URI = f'mongodb://{MONGO_HOST}:{MONGO_PORT}/'
```

If your MongoDB needs auth or lives elsewhere, just set `MONGO_URI`
directly, e.g.:
```python
MONGO_URI = 'mongodb://user:password@your-host:27017/django_app'
```

## Project layout

```
mongo_django_project/
├── manage.py
├── requirements.txt
├── App/                     # Django project (settings, root urls)
│   ├── settings.py
│   └── urls.py
├── accounts/                 # App: signup/signin/dashboard/admin logic
│   ├── mongo.py               # PyMongo connection + collections
│   ├── views.py
│   └── urls.py
├── templates/                # All HTML templates, flat (not nested per-app)
│   ├── base.html
│   ├── signin.html
│   ├── signup.html
│   ├── dashboard.html
│   └── admin_dashboard.html
└── static/                   # CSS/JS/images, served from the project root
    ├── css/
    ├── js/
    └── images/
```

## Notes / next steps

- Passwords are hashed with Django's `make_password`/`check_password`
  (PBKDF2 by default) before being stored — never stored in plaintext.
- This uses simple session-based auth rather than Django's
  `django.contrib.auth` `User` model, since accounts live in MongoDB.
  If you'd rather use Django's full auth system (permissions, admin
  integration, etc.) with MongoDB as the backing store, look into
  `django-mongodb-backend` (official MongoDB-maintained Django DB
  backend) instead of this manual approach.
- Add an `.env` file + `python-decouple`/`django-environ` if you want
  to keep `MONGO_URI` and `SECRET_KEY` out of source control for a
  real deployment.
