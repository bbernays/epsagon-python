"""
Wrapper for Django.
"""
from __future__ import absolute_import

import time
import traceback
import warnings
import epsagon
import epsagon.trace
import epsagon.triggers.http
import epsagon.runners.django

from epsagon.common import EpsagonWarning
from epsagon.utils import (
    collect_container_metadata,
    get_traceback_data_from_exception,
)
from ..http_filters import ignore_request


class DjangoMiddleware(object):
    """
    Represents a Django Middleware for Epsagon instrumentation.
    """

    def __init__(self, get_response):
        self.get_response = get_response
        self.runner = None
        self.request = None
        self.response = None
        self.ignored_request = False
        epsagon.trace.trace_factory.switch_to_multiple_traces()

    def process_exception(self, _, process_exception):
        if process_exception:
            traceback_data = get_traceback_data_from_exception(
                process_exception
            )
            self.runner.set_exception(process_exception, traceback_data, False)

    def __call__(self, request):
        self.request = request
        is_ignored_endpoint = epsagon.http_filters.is_ignored_endpoint(
            self.request.path
        )
        if not is_ignored_endpoint:
            # Link epsagon to the request object for easy-access to epsagon lib
            self.request.epsagon = epsagon
            self._before_request()
        self.response = self.get_response(request)
        if not is_ignored_endpoint:
            self._after_request()
        return self.response

    def _before_request(self):
        """
        Runs before process of response.
        """
        trace = epsagon.trace.trace_factory.get_or_create_trace()
        trace.prepare()

        # Ignoring non relevant content types.
        self.ignored_request = ignore_request('', self.request.path.lower())

        if self.ignored_request:
            return

        # Create a Django runner with current request.
        try:
            self.runner = epsagon.runners.django.DjangoRunner(
                time.time(),
                self.request
            )
            trace.set_runner(self.runner)

            # Collect metadata in case this is a container.
            collect_container_metadata(self.runner.resource['metadata'])

        # pylint: disable=W0703
        except Exception as exception:
            # Regress to python runner.
            warnings.warn('Could not extract request', EpsagonWarning)
            epsagon.trace.trace_factory.add_exception(
                exception,
                traceback.format_exc()
            )

        # Extract HTTP trigger data.
        try:
            trigger = epsagon.triggers.http.HTTPTriggerFactory.factory(
                time.time(),
                self.request
            )
            if trigger:
                epsagon.trace.trace_factory.add_event(trigger)
        # pylint: disable=W0703
        except Exception as exception:
            epsagon.trace.trace_factory.add_exception(
                exception,
                traceback.format_exc(),
            )

    def _after_request(self):
        """
        Runs after process of response.
        """
        if self.ignored_request:
            return

        # Ignoring non relevant content types.
        if ignore_request(self.response.get('Content-Type', '').lower(), ''):
            self.ignored_request = True
            return

        # Safety in case we run on an old Django version
        if not self.runner:
            return

        self.runner.update_response(self.response)
        epsagon.trace.trace_factory.send_traces()
