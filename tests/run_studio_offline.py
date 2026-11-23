"""Run known local QA scripts with every browser context restricted to loopback."""
import argparse
import runpy
from pathlib import Path
from urllib.parse import urlparse

from playwright.sync_api import Browser

ROOT = Path(__file__).resolve().parent
SCRIPTS = ('studio_headless.py', 'studio_editor_headless.py', 'studio_motion_headless.py',
           'studio_sources_headless.py', 'studio_grounding_headless.py', 'studio_workflow_headless.py')
new_context, new_page = Browser.new_context, Browser.new_page


def local_only(route):
    url = urlparse(route.request.url)
    if url.scheme in {'http', 'https'} and url.hostname not in {'127.0.0.1', 'localhost', '::1'}:
        route.abort('blockedbyclient')
    else:
        route.continue_()


def context(self, *args, **kwargs):
    result = new_context(self, *args, **kwargs)
    result.route('**/*', local_only)
    return result


def page(self, *args, **kwargs):
    result = new_page(self, *args, **kwargs)
    result.context.route('**/*', local_only)
    return result


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('scripts', nargs='*', choices=SCRIPTS)
    args = parser.parse_args()
    Browser.new_context = context
    Browser.new_page = page
    for script in args.scripts or SCRIPTS:
        runpy.run_path(str(ROOT / script), run_name='__main__')
