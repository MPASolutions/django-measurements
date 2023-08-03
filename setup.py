from setuptools import setup, find_packages

setup(
    name='django-measurements',
    version='0.29',
    # packages=['measurements'],
    packages=find_packages(),
    url='',
    license='GPL3',
    author='Stefano Menegon',
    author_email='stefano.menegon@cnr.it',
    description='',
    install_requires=['requests',
                      'pycryptodome',
                      'django-postgres-extra',
                      'django_pandas',
                      'geojson',
                      'colorbrewer',
                      'django-basicauth',
                      'lxml',
                      'beautifulsoup4',
                      'pint',
                      'django-leaflet']
)
