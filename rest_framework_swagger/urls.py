from django.conf.urls import patterns
from django.conf.urls import url
from rest_framework_swagger.views import SwaggerResourcesView, SwaggerApiView, SwaggerUIView


urlpatterns = patterns(
    '',
    url(r'^$', SwaggerUIView.as_view(), name="django.swagger.base.view"),
    url(r'^v(?P<version>\d+(\.\d+)?)/$', SwaggerUIView.as_view(), name="django.swagger.base.view__versioned"),
    url(r'^api-docs/v(?P<version>\d+(\.\d+)?)/$', SwaggerResourcesView.as_view(), name="django.swagger.resources.view"),
    url(r'^api-docs/v(?P<version>\d+(\.\d+)?)/(?P<path>.*)/?$', SwaggerApiView.as_view(), name='django.swagger.api.view'),
)
