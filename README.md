# django-measurements
Django application for aggregating measurements time series

## Installation
```
pip install django-measurements
```

## Create a bare Measurements server

1. Install requirements
    ```bash
    pip install django
    ```

2. Create a django project from scratch
    ```bash
    django-admin startproject measurements_server
    ```

3. Add measurements and other application to the INSTALLED_APPS setting of your Django project settings.py file
    ```python
    INSTALLED_APPS = (
        ...
        'measurements',
        'django_extensions',
        'django.contrib.postgres',
        'psqlextra',
    )


4. Configure the project urls adding the following rows to the urls.py of your Django project urls.py file
    ```python
    urlpatterns = [
        path('admin/', admin.site.urls),
        path('measurements/', include('measurements.urls')),
    ]
    ```
