.. _install:

=========================
Installation Instructions
=========================

particlerouting is compatible with Python 2.7, 3.6, 3.7, and 3.8. There are only 4 dependencies: `numpy <https://numpy.org/install/>`_, `matplotlib <https://matplotlib.org/3.2.2/users/installing.html>`_, `scipy <https://scipy.org/install.html>`_, and `tqdm <https://pypi.org/project/tqdm/>`_.

Installation via `pip`
----------------------
.. note:: Not yet hosted on PyPI

To `pip`-install this package, use the following command:
::

    $ pip install particlerouting


Installation via `conda`
------------------------
.. note:: Not yet hosted on conda-forge

To `conda`-install this package, use the following command:
::

    $ conda install -c conda-forge particlerouting


Installation from source
------------------------
1. Clone (or download) the repository
::

   $ git clone https://github.com/passaH2O/particlerouting

2. From the cloned (or extracted) folder, run the following in the command line:
::

   $ python setup.py install

to install the particlerouting package.


Editable installation from source
---------------------------------
If you'd prefer an "editable" install (meaning that any modifications you make to the code will be used when you import and run scripts), run the following in the command line after cloning the repository (instead of following the above instructions):
::

   $ pip install -e .