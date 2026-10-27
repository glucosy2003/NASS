"""Qt date/time helpers that use Django's configured time zone."""

from PyQt5 import QtCore

from django.utils import timezone


def local_now_qdatetime():
    """Return the current Django-local wall clock as a QDateTime.

    QDateTime.currentDateTime() follows the operating system time zone, which
    may differ from Django's TIME_ZONE. The app displays and interprets
    wall-clock times in Django's time zone, so date widgets must use it.
    """
    now = timezone.localtime()
    return QtCore.QDateTime(
        now.year,
        now.month,
        now.day,
        now.hour,
        now.minute,
        now.second,
        now.microsecond // 1000,
    )
