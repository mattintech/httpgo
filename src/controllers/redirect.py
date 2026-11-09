"""Redirect controller - handles go-link redirects.

    go/name            -> the link's URL
    go/name/extra/path -> the link's URL with /extra/path appended, or
                          substituted for {*} if the URL contains it
                          (e.g. https://jira.example.com/browse/{*})
    go/name+           -> details page for the link
"""

from urllib.parse import quote, urlsplit, urlunsplit

from flask import Blueprint, redirect, render_template, request

from src.models.link import Link

redirect_bp = Blueprint('redirect', __name__)

PLACEHOLDER = '{*}'


def build_target(url, rest='', query=''):
    """Combine a stored URL with any extra path and query string from the request."""
    rest = quote(rest, safe="/:@!$&'()*+,;=-._~")

    if PLACEHOLDER in url:
        url = url.replace(PLACEHOLDER, rest)
    elif rest:
        scheme, netloc, path, url_query, fragment = urlsplit(url)
        path = path.rstrip('/') + '/' + rest
        url = urlunsplit((scheme, netloc, path, url_query, fragment))

    if query:
        scheme, netloc, path, url_query, fragment = urlsplit(url)
        url_query = f'{url_query}&{query}' if url_query else query
        url = urlunsplit((scheme, netloc, path, url_query, fragment))

    return url


@redirect_bp.route('/<path:path>')
def go_redirect(path):
    name, _, rest = path.partition('/')

    if name.endswith('+') and not rest:
        link = Link.get_by_shortname(name[:-1])
        if link:
            return render_template('details.html', link=link)
        name = name[:-1]
    else:
        link = Link.get_by_shortname(name)

    if link is None:
        links = Link.get_all(order_by='shortname')
        return render_template('directory.html', links=links,
                               missing=name.lower()), 404

    Link.increment_hits(link.shortname)
    query = request.query_string.decode('utf-8', 'replace')
    # 302, not 301: links change and browsers cache 301s forever.
    return redirect(build_target(link.url, rest, query), code=302)
