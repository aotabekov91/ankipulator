from setuptools import setup, find_packages

setup(name='ankipulator', 
      version='0.0.1', 
      include_package_data=True, 
      package_data={'':['*', '*/*', '*/*/*', '*/*/*/*']}, 
      packages=find_packages())
