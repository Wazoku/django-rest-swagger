import os
import re
from importlib import import_module

from django.conf import settings
from django.core.urlresolvers import RegexURLPattern, RegexURLResolver
from django.utils import six
from rest_framework.views import APIView

from .apidocview import APIDocView

# The following simplify_regex is taken from Django 1.10 admindocs
# https://github.com/django/django/blob/1.10/django/contrib/admindocs/views.py
named_group_matcher = re.compile(r'\(\?P(<\w+>).+?\)')
non_named_group_matcher = re.compile(r'\(.*?\)')


def simplify_regex(pattern):
    """
    Clean up urlpattern regexes into something somewhat readable by Mere Humans:
    turns something like "^(?P<sport_slug>\w+)/athletes/(?P<athlete_slug>\w+)/$"
    into "<sport_slug>/athletes/<athlete_slug>/"
    """
    # handle named groups first
    pattern = named_group_matcher.sub(lambda m: m.group(1), pattern)

    # handle non-named groups
    pattern = non_named_group_matcher.sub("<var>", pattern)

    # clean up any outstanding regex-y characters.
    pattern = pattern.replace('^', '').replace('$', '').replace(
        '?', '').replace('//', '/').replace('\\', '')
    if not pattern.startswith('/'):
        pattern = '/' + pattern
    return pattern


class UrlParser(object):

    def get_apis(self, patterns=None, urlconf=None, filter_path=None,
                 exclude_namespaces=[], version=None):
        """
        Returns all the DRF APIViews found in the project URLs

        patterns -- supply list of patterns (optional)
        exclude_namespaces -- list of namespaces to ignore (optional)
        """
        if patterns is None and urlconf is not None:
            if isinstance(urlconf, six.string_types):
                urls = import_module(urlconf)
            else:
                urls = urlconf
            patterns = urls.urlpatterns
        elif patterns is None and urlconf is None:
            urls = import_module(settings.ROOT_URLCONF)
            patterns = urls.urlpatterns

        apis = self.__flatten_patterns_tree__(
            patterns,
            filter_path=filter_path,
            exclude_namespaces=exclude_namespaces,
        )

        if filter_path is None and version:
            filter_path = 'api/v%s.%s/' % version

        if filter_path:
            return self.get_filtered_apis(apis, filter_path)

        return apis

    def get_filtered_apis(self, apis, filter_path):
        filtered_list = []

        for api in apis:
            if filter_path in api['path'].strip('/'):
                filtered_list.append(api)

        return filtered_list

    def get_top_level_apis(self, apis):
        """
        Returns the 'top level' APIs (ie. swagger 'resources')

        apis -- list of APIs as returned by self.get_apis
        """
        root_paths = set()
        api_paths = [endpoint['path'].strip("/") for endpoint in apis]

        for path in api_paths:
            #  If a URLs /resource/ and /resource/{pk} exist, use the base
            #  as the resource. If there is no base resource URL, then include
            path_base = path.split('/{')[0]
            if '{' in path and path_base in api_paths:
                continue
            root_paths.add(path_base)

        top_level_apis = self.__filter_top_level_apis__(root_paths)

        return sorted(top_level_apis, key=self.__get_last_element__)

    def __filter_top_level_apis__(self, root_paths):
        """
        Returns top level APIs
        """
        filtered_paths = set()
        base_path = self.__get_base_path__(root_paths)
        for path in root_paths:
            resource = path.replace(base_path, '').split('/')[0]
            filtered_paths.add(base_path + resource)

        return list(filtered_paths)

    def __get_base_path__(self, root_paths):
        base_path = os.path.commonprefix(list(root_paths))
        slash_index = base_path.rfind('/') + 1
        base_path = base_path[:slash_index]

        return base_path

    def __get_last_element__(self, paths):
        split_paths = paths.split('/')
        return split_paths[len(split_paths) - 1]

    def __assemble_endpoint_data__(self, pattern, prefix='', filter_path=None):
        """
        Creates a dictionary for matched API urls

        pattern -- the pattern to parse
        prefix -- the API path prefix (used by recursion)
        """
        callback = self.__get_pattern_api_callback__(pattern)

        if callback is None or self.__exclude_router_api_root__(callback):
            return

        # Ugly hack to get version from regex
        regex_path = prefix + pattern.regex.pattern
        regex_path = regex_path.replace(r'(\.0)?', r'\.0')
        regex_path = re.sub(r'v\(\?P\<version\>(\d+\\\.\d+)\)', r'v\1', regex_path)

        path = simplify_regex(regex_path)

        if filter_path is not None:
            if re.match('^/?%s(/.*)?$' % re.escape(filter_path), path) is None:
                return None

        path = path.replace('<', '{').replace('>', '}')

        if self.__exclude_format_endpoints__(path):
            return

        return {
            'path': path,
            'pattern': pattern,
            'callback': callback,
        }

    def __flatten_patterns_tree__(self, patterns, prefix='', filter_path=None,
                                  exclude_namespaces=[]):
        """
        Uses recursion to flatten url tree.

        patterns -- urlpatterns list
        prefix -- (optional) Prefix for URL pattern
        """
        pattern_list = []

        for pattern in patterns:
            if isinstance(pattern, RegexURLPattern):
                endpoint_data = self.__assemble_endpoint_data__(
                    pattern,
                    prefix,
                    filter_path=filter_path,
                )

                if endpoint_data is None:
                    continue

                pattern_list.append(endpoint_data)

            elif isinstance(pattern, RegexURLResolver):

                if pattern.namespace is not None and pattern.namespace in exclude_namespaces:
                    continue

                pref = prefix + pattern.regex.pattern
                pattern_list.extend(self.__flatten_patterns_tree__(
                    pattern.url_patterns,
                    pref,
                    filter_path=filter_path,
                    exclude_namespaces=exclude_namespaces,
                ))

        return pattern_list

    def __get_pattern_api_callback__(self, pattern):
        """
        Verifies that pattern callback is a subclass of APIView, and returns the class
        Handles older django & django rest 'cls_instance'
        """
        if not hasattr(pattern, 'callback'):
            return

        if (hasattr(pattern.callback, 'cls') and
                issubclass(pattern.callback.cls, APIView) and
                not issubclass(pattern.callback.cls, APIDocView)):

            return pattern.callback.cls

        elif (hasattr(pattern.callback, 'cls_instance') and
                isinstance(pattern.callback.cls_instance, APIView) and
                not issubclass(pattern.callback.cls_instance, APIDocView)):

            return pattern.callback.cls_instance

    def __exclude_router_api_root__(self, callback):
        """
        Returns True if the URL's callback is rest_framework.routers.APIRoot
        """
        if callback.__module__ == 'rest_framework.routers':
            return True

        return False

    def __exclude_format_endpoints__(self, path):
        """
        Excludes URL patterns that contain .{format}
        """
        if '.{format}' in path:
            return True

        return False
