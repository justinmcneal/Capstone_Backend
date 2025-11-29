# Capstone Backend

Django REST API backend for the Capstone project.

## Setup Instructions

1. **Create a virtual environment** (already done):
   ```bash
   python -m venv .venv
   ```

2. **Activate the virtual environment**:
   ```bash
   source .venv/bin/activate
   ```

3. **Install dependencies**:
   ```bash
   pip install -r requirements.txt
   ```

4. **Set up environment variables**:
   - Copy `.env.example` to `.env`
   - Update the values in `.env` as needed

5. **Run migrations**:
   ```bash
   python manage.py migrate
   ```

6. **Create a superuser** (optional):
   ```bash
   python manage.py createsuperuser
   ```

7. **Run the development server**:
   ```bash
   python manage.py runserver
   ```

The API will be available at `http://localhost:8000/`

## Project Structure

```
capstone_backend/
├── capstone_backend/    # Main project configuration
│   ├── settings.py      # Django settings
│   ├── urls.py          # URL routing
│   ├── wsgi.py          # WSGI config
│   └── asgi.py          # ASGI config
├── manage.py            # Django management script
├── .env                 # Environment variables (not in git)
├── .env.example         # Example environment variables
└── requirements.txt     # Python dependencies
```

## API Documentation

Add your API endpoints documentation here as you build them.

## Technologies Used

- Django
- Django REST Framework
- django-cors-headers (for CORS support)
- python-dotenv (for environment variables)
