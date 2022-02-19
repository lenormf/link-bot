# -*- coding: utf-8 -*-
#
# link_plugin.py for link-bot
# by lenormf
#

import irc3
import requests

from urllib.parse import urlparse

from bs4 import BeautifulSoup


@irc3.plugin
class Title:
    requires = ["irc3.plugins.log"]

    USER_AGENT = "Mozilla/5.0 (Windows NT 6.1; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/62.0.3202.62 Safari/537.36"
    REQUEST_TIMEOUT = 3
    MAX_MESSAGE_LENGTH = 512

    def __init__(self, bot):
        self.bot = bot
        self.log = bot.log

        self.log.debug(self.bot.config)
        if self.bot.config["debug"]:
            # NOTE: official documented way of enabling debug on `requests`
            import logging
            from http.client import HTTPConnection

            HTTPConnection.debuglevel = 1

            logging.basicConfig()
            logging.getLogger().setLevel(logging.DEBUG)
            requests_log = logging.getLogger("urllib3")
            requests_log.setLevel(logging.DEBUG)
            requests_log.propagate = True

    def _get_url_title(self, url):
        try:
            url_parsed = urlparse(url)
            url_scheme, url_netloc = url_parsed[:2]

            self.log.debug("URL parsed: %r", url_parsed)
        except ValueError as e:
            self.log.exception(e)
            self.log.error("Unable to parse URL: %s", url)
            return None

        if not url_scheme:
            return None

        if url_scheme not in ["http", "https"]:
            self.log.debug("Unsupported scheme: %r", url_scheme)
            return None

        html = None
        try:
            headers = {
                "User-Agent": Title.USER_AGENT,
            }

            r = requests.head(url, headers=headers, allow_redirects=True,
                              timeout=Title.REQUEST_TIMEOUT)

            self.log.debug("headers: %r", r.headers)

            if "content-type" not in r.headers \
               or "text/html" not in r.headers["content-type"]:
                return None

            r = requests.get(url, headers=headers,
                             timeout=Title.REQUEST_TIMEOUT)
            html = r.text
        except requests.exceptions.RequestException as e:
            self.log.error("Unable to fetch URL: %s", e)
            return None

        self.log.debug("HTML [%r]", html)

        try:
            soup = BeautifulSoup(html, "lxml")

            def get_opengraph_property(soup, property):
                property = "og:%s" % property
                opengraph = soup.find("meta", property=property)
                if opengraph and "content" in opengraph.attrs:
                    return opengraph["content"]
                return None

            og_title = get_opengraph_property(soup, "title")
            og_description = get_opengraph_property(soup, "description")

            if not og_title:
                title = soup.find("title")
                if not title:
                    return None
                og_title = title.text

            og_title = og_title.strip()

            if og_description:
                return "%s | %s" % (og_title, og_description)
            else:
                return og_title
        except Exception as e:
            # NOTE: in theory no exceptions should be thrown here
            self.log.error("Unable to parse the HTML: %s", e)
            return None

        return None

    @irc3.event(irc3.rfc.PRIVMSG)
    async def show_title(self, mask, target, event, data):
        """Print the title of a webpage when a URL is posted on a channel"""

        if mask.nick == self.bot.nick or target not in self.bot.config["autojoins"]:
            return

        # Implementation based on https://stackoverflow.com/a/43848928
        def utf8_byte_truncate(utf8, max_bytes):
            def lead_byte(b):
                return (b & 0xC0) != 0x80

            if len(utf8) <= max_bytes:
                return len(utf8)

            i = max_bytes
            while i > 0 and not lead_byte(utf8[i]):
                i -= 1

            return i

        titles = {}
        for url in data.split(" "):
            self.log.debug("Parsing URL: %s", url)

            title_parsed = self._get_url_title(url)
            if not title_parsed:
                self.log.error("No title could be parsed")
                continue

            # NOTE: the following is a workaround for https://github.com/gawel/irc3/issues/191
            title_parsed_bytes = title_parsed.encode("utf-8")
            length_bytes = utf8_byte_truncate(title_parsed_bytes,
                                              Title.MAX_MESSAGE_LENGTH - len("PRIVMSG  :" + "\n") - len(target))
            if length_bytes != len(title_parsed_bytes):
                self.log.warning("Truncated the title to %d bytes (max: %d)",
                                 length_bytes, Title.MAX_MESSAGE_LENGTH)
                title_parsed = title_parsed_bytes[:length_bytes].decode("utf-8")

            titles[url] = title_parsed

        if len(titles) == 1:
            self.bot.privmsg(target, titles.popitem()[1])
        else:
            for url, title in titles.items():
                self.bot.privmsg(target, "%s: %s" % (url, title))
