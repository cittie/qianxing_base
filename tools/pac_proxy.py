#!/usr/bin/env python3
"""Resolve which proxy the local PAC file wants for a given host.

Why this exists
---------------
The PAC (AutoConfigURL) is evaluated by WinINET, i.e. by browsers and by .NET apps.
git/libcurl does NOT understand PAC, so a git command has to be told the proxy
explicitly -- and the only correct way to know it is to evaluate the PAC.

The local PAC (gfwlist2pac, "precise mode") has been seen served as space-separated
decimal byte values rather than raw JS; this script detects and decodes that form.

Usage
-----
    python pac_proxy.py github.com                 # what proxy does the PAC pick?
    python pac_proxy.py github.com gitlab.com
    python pac_proxy.py --pac-url http://127.0.0.1:10811/pac?t=123 github.com
    python pac_proxy.py --git-config github.com    # print a git config command
    python pac_proxy.py --json github.com

Exit codes: 0 resolved, 2 could not fetch/evaluate the PAC.
"""

from __future__ import annotations

import argparse
import json
import re
import sys
import urllib.request

REG_PATH = r"Software\Microsoft\Windows\CurrentVersion\Internet Settings"


def pac_url_from_registry() -> str | None:
    """Read AutoConfigURL from the current user's WinINET settings."""
    try:
        import winreg  # Windows only
    except ImportError:
        return None
    try:
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, REG_PATH) as key:
            value, _ = winreg.QueryValueEx(key, "AutoConfigURL")
            return value or None
    except OSError:
        return None


def fetch(url: str, timeout: float = 20.0) -> str:
    """Fetch the PAC. Note: deliberately no proxy -- the PAC server is local."""
    opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
    with opener.open(url, timeout=timeout) as resp:
        raw = resp.read()
    return decode_maybe_decimal(raw)


def decode_maybe_decimal(raw: bytes) -> str:
    """Some PAC servers return the JS as space-separated decimal byte values."""
    text = raw.decode("utf-8", "replace")
    stripped = text.strip()
    if stripped and re.fullmatch(r"[\d\s]+", stripped):
        tokens = stripped.split()
        try:
            return bytes(int(t) for t in tokens).decode("utf-8", "replace")
        except (ValueError, OverflowError):
            pass
    return text


class Pac:
    def __init__(self, js: str) -> None:
        self.js = js
        self.proxy = self._scalar("proxy")
        self.direct = self._scalar("direct") or "DIRECT"
        self.rules = self._rules()

    def _scalar(self, name: str) -> str | None:
        m = re.search(r'var\s+' + name + r'\s*=\s*"([^"]*)"', self.js)
        return m.group(1) if m else None

    def _rules(self) -> list[str]:
        m = re.search(r"var\s+rules\s*=\s*\[(.*?)\];", self.js, re.S)
        if not m:
            return []
        return re.findall(r'"((?:[^"\\]|\\.)*)"', m.group(1))

    def resolve(self, url_or_host: str) -> str:
        """Evaluate the rules the way gfwlist2pac's FindProxyForURL does, approximately."""
        host = url_or_host
        if "://" in host:
            host = host.split("://", 1)[1]
        host = host.split("/", 1)[0].split(":", 1)[0].lower()
        url = url_or_host if "://" in url_or_host else "http://" + host + "/"

        for rule in self.rules:
            if self._matches(rule, host, url):
                return self.proxy or "DIRECT"
        return self.direct

    @staticmethod
    def _matches(rule: str, host: str, url: str) -> bool:
        if not rule:
            return False
        # /regex/ form
        if len(rule) > 2 and rule.startswith("/") and rule.endswith("/"):
            try:
                return re.search(rule[1:-1], url, re.I) is not None
            except re.error:
                return False
        # "||example.com" -> the domain and any subdomain
        if rule.startswith("||"):
            domain = rule[2:].lstrip(".").lower()
            return host == domain or host.endswith("." + domain)
        # "|http://..." -> url prefix
        if rule.startswith("|"):
            return url.lower().startswith(rule[1:].lower())
        # ".example.com" -> matches at the end of the host
        if rule.startswith("."):
            return host.endswith(rule.lower())
        # plain substring
        return rule.lower() in url.lower()


def git_command(host: str, proxy: str) -> str:
    """git has no PAC support, so pin the resolved proxy for that host only."""
    if proxy.upper().startswith("DIRECT"):
        return f"git config --global --unset http.https://{host}.proxy   # PAC says DIRECT"
    scheme, _, addr = proxy.partition(" ")
    addr = addr.strip()
    if scheme.upper().startswith("SOCKS5"):
        # socks5h: let the proxy resolve DNS (required here; plain socks5 fails)
        url = f"socks5h://{addr}"
    elif scheme.upper() == "PROXY":
        url = f"http://{addr}"
    elif scheme.upper() == "HTTPS":
        url = f"https://{addr}"
    else:
        url = proxy
    return f"git config --global http.https://{host}.proxy {url}"


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("hosts", nargs="*", help="hosts or URLs to resolve")
    ap.add_argument("--pac-url", default=None, help="override the AutoConfigURL")
    ap.add_argument("--json", action="store_true", help="machine-readable output")
    ap.add_argument("--git-config", action="store_true", help="print a git config command")
    args = ap.parse_args()

    url = args.pac_url or pac_url_from_registry()
    if not url:
        print("no PAC URL given and none found in the registry", file=sys.stderr)
        return 2

    try:
        js = fetch(url)
    except Exception as exc:  # noqa: BLE001 - report and exit
        print(f"could not fetch PAC from {url}: {exc}", file=sys.stderr)
        return 2

    pac = Pac(js)
    if not pac.rules:
        print(f"PAC at {url} has no rules array (is it really a PAC?)", file=sys.stderr)
        return 2

    hosts = args.hosts or ["github.com"]
    results = {h: pac.resolve(h) for h in hosts}

    if args.json:
        print(json.dumps({"pac": url, "default": pac.direct, "resolved": results}, indent=2))
    else:
        print(f"PAC          : {url}")
        print(f"default      : {pac.direct}")
        print(f"rules        : {len(pac.rules)}")
        for host, proxy in results.items():
            print(f"{host:<28} -> {proxy}")
        if args.git_config:
            print()
            for host, proxy in results.items():
                print(git_command(host, proxy))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
