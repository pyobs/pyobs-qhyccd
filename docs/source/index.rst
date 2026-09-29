pyobs-qhyccd
############

This is a `pyobs <https://www.pyobs.org>`_ (`documentation <https://docs.pyobs.org>`_) module for QHYCCD cameras.


Example configuration
*********************

This is an example configuration::

    class: pyobs_qhyccd.QHYCCDCamera

    # cooling
    setpoint: -10

    # filename pattern
    filenames: /cache/pyobs-{DAY-OBS|date:}-{FRAMENUM|string:04d}-{IMAGETYP|type}00.fits

    # location
    timezone: utc
    location:
      longitude: 9.944333
      latitude: 51.560583
      elevation: 201.

    # communication
    comm:
      jid: test@example.com
      password: ***

    # virtual file system
    vfs:
      class: pyobs.vfs.VirtualFileSystem
      roots:
        cache:
          class: pyobs.vfs.HttpFile
          upload: http://localhost:37075/


Available classes
*****************

:class:`~pyobs_qhyccd.QHYCCDCamera` takes single exposures, :class:`~pyobs_qhyccd.QHYCCDVideo` streams video
from a QHYCCD camera in live mode, e.g. for acquisition, guiding or focusing. Only one of them can use a camera at a
time.

QHYCCDCamera
============
.. autoclass:: pyobs_qhyccd.QHYCCDCamera
   :members:
   :show-inheritance:

QHYCCDVideo
===========
.. autoclass:: pyobs_qhyccd.QHYCCDVideo
   :members:
   :show-inheritance:
