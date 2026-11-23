"""Vetted resource IDs only; no user URL fetching or remote content execution."""
import json
from pathlib import Path
from typing import Literal
from urllib.parse import urlsplit

RESOURCE_CATALOG = json.loads((Path(__file__).resolve().parents[2] / 'static/ai-slides/resources.json').read_text(encoding='utf-8'))
RESOURCE_BY_ID = {item['id']: item for item in RESOURCE_CATALOG}
if len(RESOURCE_BY_ID) != len(RESOURCE_CATALOG):
    raise ValueError('Duplicate Studio resource ID')
for item in RESOURCE_CATALOG:
    if 'url' in item:
        url = urlsplit(item['url'])
        if url.scheme != 'https' or url.hostname not in {'phet.colorado.edu', 'gpm.nasa.gov'} or url.username or url.password:
            raise ValueError('Unapproved Studio resource URL')
    elif item.get('path') not in {'/ai-studio/simulations/ohm', '/ai-studio/simulations/pendulum', '/ai-studio/simulations/vietnam-map'}:
        raise ValueError('Unapproved Studio resource path')

ResourceId = Literal[tuple(RESOURCE_BY_ID)]


def model_resources():
    return [{'id': item['id'], 'type': item['kind'], 'topic': item['description'], 'limitations': item['limitations']} for item in RESOURCE_CATALOG]
