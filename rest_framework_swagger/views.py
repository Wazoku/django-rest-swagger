import json
from django.utils import six

from django.views.generic import View
from django.utils.safestring import mark_safe
from django.utils.encoding import smart_text
from django.shortcuts import render_to_response, RequestContext
from django.core.exceptions import PermissionDenied
from django.shortcuts import redirect
from django.core.urlresolvers import reverse
from .compat import import_string

from rest_framework.views import Response
from rest_framework.settings import api_settings
from rest_framework.utils import formatting

from rest_framework_swagger.urlparser import UrlParser
from rest_framework_swagger.apidocview import APIDocView
from rest_framework_swagger.docgenerator import DocumentationGenerator

import rest_framework_swagger as rfs


try:
    JSONRenderer = list(filter(
        lambda item: item.format == 'json',
        api_settings.DEFAULT_RENDERER_CLASSES,
    ))[0]
except IndexError:
    from rest_framework.renderers import JSONRenderer


def get_restructuredtext(view_cls, html=False):
    from docutils import core

    description = view_cls.__doc__ or ''
    description = formatting.dedent(smart_text(description))
    if html:
        parts = core.publish_parts(source=description, writer_name='html')
        html = parts['body_pre_docinfo'] + parts['fragment']
        return mark_safe(html)
    return description


def get_full_base_path(request):
    try:
        base_path = rfs.SWAGGER_SETTINGS['base_path']
    except KeyError:
        return request.build_absolute_uri(request.path).rstrip('/')
    else:
        protocol = 'https' if request.is_secure() else 'http'
        return '{0}://{1}'.format(protocol, base_path.rstrip('/'))


class SwaggerUIView(View):
    def get(self, request, *args, **kwargs):
        if not self.has_permission(request):
            return self.handle_permission_denied(request)

        version_resolver = import_string(rfs.SWAGGER_SETTINGS['version_resolver'])

        version = kwargs.get('version')
        if version:
            version = version_resolver.parse_version_string(version)

            # Check version is available
            if version not in version_resolver.available_versions:
                version = None

        # In case of missing or invalid version - redirect to the latest version docs.
        if not version:
            latest_version = max(version_resolver.available_versions)
            return redirect(
                reverse(
                    'django.swagger.base.view__versioned',
                    kwargs=dict(version='.'.join(map(str, latest_version))),
                ),
            )

        version_string = '%s.%s' % version

        available_versions = []

        for ver in sorted(version_resolver.available_versions):
            ver_str = '%s.%s' % ver
            available_versions.append({
                'version': ver_str,
                'is_current': ver == version,
                'link': "/v%s/" % ver_str,
            })

        template_name = rfs.SWAGGER_SETTINGS.get('template_path')
        data = {
            'swagger_settings': {
                'discovery_url': "%s/api-docs/v%s/" % (
                    get_full_base_path(request),
                    version_string,
                ),
                'api_key': rfs.SWAGGER_SETTINGS.get('api_key', ''),
                'token_type': rfs.SWAGGER_SETTINGS.get('token_type'),
                'enabled_methods': mark_safe(
                    json.dumps(rfs.SWAGGER_SETTINGS.get('enabled_methods'))),
                'doc_expansion': rfs.SWAGGER_SETTINGS.get('doc_expansion', ''),
            },
            'version': version_string,
            'available_versions': available_versions,
        }
        response = render_to_response(
            template_name,
            RequestContext(request, data),
        )

        return response

    def has_permission(self, request):
        if rfs.SWAGGER_SETTINGS.get('is_superuser') and \
                not request.user.is_superuser:
            return False

        if rfs.SWAGGER_SETTINGS.get('is_authenticated') and \
                not request.user.is_authenticated():
            return False

        return True

    def handle_permission_denied(self, request):
        permission_denied_handler = rfs.SWAGGER_SETTINGS.get(
            'permission_denied_handler')
        if isinstance(permission_denied_handler, six.string_types):
            permission_denied_handler = import_string(
                permission_denied_handler)

        if permission_denied_handler:
            return permission_denied_handler(request)
        else:
            raise PermissionDenied()


class SwaggerResourcesView(APIDocView):
    renderer_classes = (JSONRenderer, )

    def get(self, request, version):
        apis = [{'path': '/' + path} for path in self.get_resources()]
        return Response({
            'apiVersion': rfs.SWAGGER_SETTINGS.get('api_version', ''),
            'swaggerVersion': '1.2',
            'basePath': self.get_base_path(version=version),
            'apis': apis,
            'info': rfs.SWAGGER_SETTINGS.get('info', {
                'contact': '',
                'description': '',
                'license': '',
                'licenseUrl': '',
                'termsOfServiceUrl': '',
                'title': '',
            }),
        })

    def get_base_path(self, version):
        try:
            base_path = rfs.SWAGGER_SETTINGS['base_path']
        except KeyError:
            return self.request.build_absolute_uri(
                self.request.path).rstrip('/')
        else:
            protocol = 'https' if self.request.is_secure() else 'http'
            return '{0}://{1}/{2}/v{3}'.format(protocol, base_path, 'api-docs', version)

    def get_resources(self):
        urlparser = UrlParser()
        urlconf = getattr(self.request, "urlconf", None)
        exclude_namespaces = rfs.SWAGGER_SETTINGS.get('exclude_namespaces')

        apis = urlparser.get_apis(
            urlconf=urlconf,
            exclude_namespaces=exclude_namespaces,
            version=self.version,
        )
        authorized_apis = filter(lambda a: self.handle_resource_access(self.request, a['pattern']), apis)
        return urlparser.get_top_level_apis(list(authorized_apis))


class SwaggerApiView(APIDocView):
    renderer_classes = (JSONRenderer, )

    def get(self, request, version, path):
        apis = self.get_apis_for_resource(path)
        generator = DocumentationGenerator(
            for_user=request.user,
            version=self.version,
        )
        return Response({
            'apiVersion': rfs.SWAGGER_SETTINGS.get('api_version', ''),
            'swaggerVersion': '1.2',
            'basePath': self.api_full_uri.rstrip('/'),
            'resourcePath': '/' + path,
            'apis': generator.generate(apis),
            'models': generator.get_models(apis),
        })

    def get_apis_for_resource(self, filter_path):
        urlparser = UrlParser()
        urlconf = getattr(self.request, "urlconf", None)
        apis = urlparser.get_apis(
            urlconf=urlconf,
            filter_path=filter_path,
            version=self.version,
        )
        authorized_apis = filter(lambda a: self.handle_resource_access(self.request, a['pattern']), apis)
        return list(authorized_apis)
