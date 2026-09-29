"""Smoke tests: import the driver and instantiate it without hardware, asserting the
interfaces it claims.

The Cython extension (qhyccddriver) links the vendored QHYCCD static library during
install, but device enumeration/opening only happens inside open(), so instantiation
is safe with no QHYCCD hardware attached.
"""

from pyobs.interfaces import (
    IAbortable,
    IBinning,
    ICamera,
    ICooling,
    IExposureTime,
    IGain,
    IImageFormat,
    IVideo,
    IWindow,
)
from pyobs.modules import Module

from pyobs_qhyccd import QHYCCDCamera, QHYCCDVideo


def test_instantiate_camera() -> None:
    camera = QHYCCDCamera()
    assert isinstance(camera, Module)
    assert isinstance(camera, ICamera)
    assert isinstance(camera, IWindow)
    assert isinstance(camera, IBinning)
    assert isinstance(camera, ICooling)
    assert isinstance(camera, IGain)
    assert isinstance(camera, IAbortable)


def test_instantiate_video() -> None:
    video = QHYCCDVideo()
    assert isinstance(video, Module)
    assert isinstance(video, IVideo)
    assert isinstance(video, IExposureTime)
    assert isinstance(video, IWindow)
    assert isinstance(video, IBinning)
    assert isinstance(video, IImageFormat)
    assert isinstance(video, IGain)
