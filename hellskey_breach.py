#!/usr/bin/env python3
# PYTHON_ARGCOMPLETE_OK
"""
HellsKey Breach – Elite OSINT Tool with Token‑Based Access Control
Team: Black Hat Hackers 👁‍🗨HellsKey Breach👁‍🗨
"""

import os
import sys
import json
import time
import re
import base64
import requests
import argparse
import argcomplete
import tldextract
import threading
import queue
from pathlib import Path
from yaspin import yaspin, Spinner
from rich.console import Console
from rich.table import Table
from rich.panel import Panel
from rich import box
from rich.text import Text
from datetime import datetime

# ==================== Configuration ====================
VERSION = "8.0.0"
TEAM_NAME = "Black Hat Hackers HellsKey Breach"
TEAM_SLOGAN = "We see what others don't"
SITE_URL = "http://2dpg7coa4gi4rw2pjaor4cwwcelspqlpt2yvmu6avgk6mq3jmwz6pxad.onion"
TOKEN_API_URL = f"{SITE_URL}/api/verify-token.php"
SEARCH_API_URL = f"{SITE_URL}/api/check.php"
TOR_PROXY = "socks5h://127.0.0.1:9050"

console = Console()

# ==================== Utility Functions ====================
def read_file(file_path):
    with open(file_path, 'r') as f:
        return [line.strip() for line in f if line.strip()]

def write_file(file_path, data):
    with open(file_path, 'w') as f:
        f.write(data)

def get_root_domain(domain):
    ext = tldextract.extract(domain)
    if not ext.suffix:
        return None
    return f"{ext.domain}.{ext.suffix}"

def is_valid_ip(ip_str):
    pattern = r'^(?:(?:25[0-5]|2[0-4][0-9]|[01]?[0-9][0-9]?)\.){3}(?:25[0-5]|2[0-4][0-9]|[01]?[0-9][0-9]?)$'
    return re.match(pattern, ip_str) is not None

def check_tor():
    try:
        session = requests.Session()
        session.proxies = {'http': TOR_PROXY, 'https': TOR_PROXY}
        r = session.get("https://check.torproject.org/api/ip", timeout=10)
        if r.status_code == 200 and r.json().get('IsTor'):
            return True
    except:
        pass
    return False

def obfuscate(text):
    """Return base64 encoded text for non‑subscribers."""
    if not text:
        return ''
    return base64.b64encode(text.encode()).decode()

# ==================== Tor‑Aware Requests ====================
def make_request(url, params=None, data=None, method='GET', timeout=60, retries=3):
    session = requests.Session()
    if '.onion' in url:
        session.proxies = {'http': TOR_PROXY, 'https': TOR_PROXY}
    for attempt in range(retries):
        try:
            if method.upper() == 'GET':
                resp = session.get(url, params=params, timeout=timeout)
            else:
                resp = session.post(url, data=data, timeout=timeout)
            resp.raise_for_status()
            return resp.json()
        except (requests.exceptions.Timeout,
                requests.exceptions.ConnectionError,
                requests.exceptions.ChunkedEncodingError) as e:
            if attempt == retries - 1:
                console.print(f"[red]Request failed after {retries} attempts: {e}[/red]")
                raise
            wait = 2 ** attempt
            console.print(f"[yellow]Request failed ({e}), retrying in {wait}s...[/yellow]")
            time.sleep(wait)

def validate_hellskey_token(token):
    try:
        data = make_request(TOKEN_API_URL, params={'token': token})
        return data.get('valid', False)
    except:
        return False

# ==================== Method to Types Mapping ====================
METHOD_TO_TYPES = {
    'domain': ['domain', 'subdomain'],
    'domain.all': ['domain', 'subdomain', 'url', 'email', 'password', 'username', 'phone', 'cred', 'endpoint', 'port'],
    'cred.email': ['email'],
    'cred.email.domain': ['email'],
    'cred.username': ['username'],
    'cred.password': ['password'],
    'cred.phone': ['phone'],
    'cred.country': ['cred'],
    'ip': ['domain', 'subdomain', 'url'],
    'ip.port': ['port'],
    'ip.asn': ['asn'],
    'ip.cidr': ['domain', 'subdomain', 'url'],
    'url.path': ['endpoint', 'url'],
    'url.port': ['port'],
    'app.domain': ['domain'],
    'app.id': ['app_id'],
    'app.name': ['app_name'],
    'related': ['domain'],
    'subdomain': ['subdomain'],
}

ALL_TYPES = ['email', 'password', 'domain', 'username', 'phone', 'subdomain', 'cred', 'endpoint', 'port', 'url', 'asn', 'app_id', 'app_name']

# ==================== Detailed Result Class ====================
class DetailedResult:
    def __init__(self, type, data, query='', subscriber=False):
        self.type = type
        self.domain = data.get('domain', '')
        self.value = data.get('value', '')
        self.file = data.get('file', '')
        self.query = query
        self.subscriber = subscriber

        # Fields to be extracted
        self.url = ''
        self.path = ''
        self.port = ''
        self.username = ''
        self.password = ''
        self.email = ''
        self.country = ''

        self._parse_value()

    def _parse_value(self):
        val = self.value.strip()
        # Try full credential line
        pattern = r'^(https?://[^:]+(?::\d+)?(?:/[^:]*)?):([^:]+):([^:]+):?(.*)$'
        match = re.match(pattern, val)
        if match:
            self.url = match.group(1)
            self.username = match.group(2)
            self.password = match.group(3)
            self.country = match.group(4) if match.group(4) else ''
            self._extract_url_parts()
            if '@' in self.username and '.' in self.username:
                self.email = self.username
                self.username = ''
            return
        pattern2 = r'^(https?://[^:]+(?::\d+)?(?:/[^:]*)?):([^:]+):([^:]+)$'
        match = re.match(pattern2, val)
        if match:
            self.url = match.group(1)
            self.username = match.group(2)
            self.password = match.group(3)
            self._extract_url_parts()
            if '@' in self.username and '.' in self.username:
                self.email = self.username
                self.username = ''
            return
        if val.startswith('http://') or val.startswith('https://'):
            self.url = val
            self._extract_url_parts()
            return
        if self.type == 'email':
            self.email = val
        elif self.type == 'username':
            self.username = val
        elif self.type == 'password':
            self.password = val
        elif self.type in ('domain', 'subdomain'):
            self.domain = val
        elif self.type == 'url':
            self.url = val
            self._extract_url_parts()
        elif self.type == 'endpoint':
            self.path = val
        elif self.type == 'port':
            self.port = val
        else:
            if '://' in val:
                self.url = val
                self._extract_url_parts()

    def _extract_url_parts(self):
        if not self.url:
            return
        url_match = re.match(r'^(https?://)?([^:/]+)(?::(\d+))?(/.*)?$', self.url)
        if url_match:
            if url_match.group(3):
                self.port = url_match.group(3)
            if url_match.group(4):
                self.path = url_match.group(4)

    def print(self):
        """Print with optional obfuscation for non‑subscribers."""
        lines = []
        # URL lines are always in clear
        if self.url:
            lines.append(f"[magenta][ URL  ]> [cyan]{self.url}[/cyan]")
        if self.path and self.path not in ('/', ''):
            lines.append(f"[magenta][ URL  ]> [red]Path[/red]          : [cyan]{self.path}[/cyan]")
        if self.port:
            lines.append(f"[magenta][ URL  ]> [red]Port[/red]          : [cyan]{self.port}[/cyan]")

        if self.email:
            display = self.email if self.subscriber else obfuscate(self.email)
            lines.append(f"[magenta][ CRED ]> [red]Email[/red]         : [green]{display}[/green]")
        if self.username:
            display = self.username if self.subscriber else obfuscate(self.username)
            lines.append(f"[magenta][ CRED ]> [red]Username[/red]      : [green]{display}[/green]")
        if self.password:
            display = self.password if self.subscriber else obfuscate(self.password)
            lines.append(f"[magenta][ CRED ]> [red]Password[/red]      : [green]{display}[/green]")
        if self.country:
            lines.append(f"[magenta][ CRED ]> [red]Country[/red]       : [cyan]{self.country}[/cyan]")

        if self.domain and not any([self.url, self.email, self.username, self.password]):
            lines.append(f"[magenta][ Domain ]> [cyan]{self.domain}[/cyan]")

        if not lines:
            display = self.value if self.subscriber else obfuscate(self.value)
            lines.append(f"[magenta][ {self.type.upper()} ]> [cyan]{display}[/cyan]")

        return '\n'.join(lines)

    def save_format(self):
        """For file output, always save clear text (but obfuscated if non‑subscriber)."""
        if self.email:
            return self.email if self.subscriber else obfuscate(self.email)
        if self.username:
            return self.username if self.subscriber else obfuscate(self.username)
        if self.password:
            return self.password if self.subscriber else obfuscate(self.password)
        if self.url:
            return self.url
        if self.domain:
            return self.domain
        return self.value if self.subscriber else obfuscate(self.value)

# ==================== Core API Client ====================
class HellsKeyAPICore:
    def __init__(self, token=None, debug=True):
        self.token = token
        self.subscriber = bool(token and validate_hellskey_token(token))
        self.debug = debug
        self.cache = {}

    def search(self, query, method, limit=10000, timeout=60,
               use_spinner=False, callback=None, search_text='', err_text=''):
        cache_key = (query, method, limit)
        if cache_key in self.cache:
            return self.cache[cache_key]

        types = METHOD_TO_TYPES.get(method, ALL_TYPES)
        if not types:
            types = ALL_TYPES

        params = {'q': query, 'limit': limit}
        if self.token:
            params['token'] = self.token
        for t in types:
            params.setdefault('types[]', []).append(t)

        if use_spinner:
            with yaspin(Spinner(["🐟", "🐠", "🐡", "🐬", "🐋", "🐳", "🦈", "🐙", "🐚", "🪼", "🪸"], 200), text=search_text or f"Querying {query}...") as sp:
                try:
                    response = make_request(SEARCH_API_URL, params=params, timeout=timeout)
                except Exception as e:
                    sp.text = f"Request error: {e}"
                    sp.fail("💥")
                    return [], 0
        else:
            try:
                response = make_request(SEARCH_API_URL, params=params, timeout=timeout)
            except Exception as e:
                console.print(f"[red]Request error: {e}[/red]")
                return [], 0

        if not response.get('success'):
            err_msg = response.get('error', 'Unknown error')
            if use_spinner:
                with yaspin(Spinner(["👁‍🗨", "👁", "🗨", "🔍"], 200), text=err_text or f"Error: {err_msg}") as sp:
                    sp.fail("💥")
            else:
                console.print(f"[red]API Error: {err_msg}[/red]")
            return [], 0

        results_data = response.get('results')
        pages = response.get('pages', 1)
        results = []

        if isinstance(results_data, dict):
            for result_type, items in results_data.items():
                for item in items:
                    result = DetailedResult(type=result_type, data=item, query=query, subscriber=self.subscriber)
                    if callback:
                        callback(result)
                    results.append(result)
        elif isinstance(results_data, list):
            for item in results_data:
                result = DetailedResult(type='unknown', data=item, query=query, subscriber=self.subscriber)
                if callback:
                    callback(result)
                results.append(result)

        if not results and use_spinner:
            with yaspin(Spinner(["👁‍🗨", "👁", "🗨", "🔍"], 200), text=err_text or f"No results for {query}") as sp:
                sp.fail("💥")

        self.cache[cache_key] = (results, pages)
        return results, pages

# ==================== View-Type Filter ====================
def filter_by_view_type(results, view_type):
    if not view_type:
        return results
    type_map = {
        'subdomain': ['subdomain'],
        'related': ['domain'],
        'domain': ['domain'],
        'email': ['email'],
        'username': ['username'],
        'password': ['password'],
        'ip': ['ip'],
    }
    allowed_types = type_map.get(view_type, [view_type])
    filtered = []
    for r in results:
        if r.type in allowed_types:
            filtered.append(r)
        elif view_type == 'ip' and is_valid_ip(r.value):
            filtered.append(r)
    return filtered

# ==================== Multi‑threaded Worker ====================
def worker(q, core, method, limit, timeout, results_list, pages_list):
    while True:
        query = q.get()
        if query is None:
            break
        res, pages = core.search(query, method, limit, timeout, use_spinner=False)
        results_list.extend(res)
        pages_list.append((query, pages))
        q.task_done()

# ==================== Team Banner ====================
def show_team_banner():
    console.print("╔════════════════════════════════════════════════════════════╗", style="red")
    console.print("║    ██╗  ██╗███████╗██╗     ██╗     ███████╗██╗  ██╗███████╗██╗   ██╗    ║", style="white")
    console.print("║    ██║  ██║██╔════╝██║     ██║     ██╔════╝██║ ██╔╝██╔════╝╚██╗ ██╔╝    ║", style="white")
    console.print("║    ███████║█████╗  ██║     ██║     █████╗  █████╔╝ █████╗   ╚████╔╝     ║", style="white")
    console.print("║    ██╔══██║██╔══╝  ██║     ██║     ██╔══╝  ██╔═██╗ ██╔══╝    ╚██╔╝      ║", style="white")
    console.print("║    ██║  ██║███████╗███████╗███████╗███████╗██║  ██╗███████╗   ██║       ║", style="white")
    console.print("║    ╚═╝  ╚═╝╚══════╝╚══════╝╚══════╝╚══════╝╚═╝  ╚═╝╚══════╝   ╚═╝       ║", style="white")
    console.print("╠════════════════════════════════════════════════════════════╣", style="red")
    console.print(f"║  {TEAM_NAME} – {TEAM_SLOGAN}{' '*(60 - len(TEAM_NAME+TEAM_SLOGAN)-6)}║", style="cyan")
    console.print(f"║  Version {VERSION} | Dark Web OSINT Suite | {datetime.now().strftime('%Y-%m-%d')}{' '*(15)}║", style="green")
    console.print("╚════════════════════════════════════════════════════════════╝", style="red")

    # Separator line
    console.print("═" * 60, style="cyan")

    # Contact information
    console.print("📲 Telegram Admin:", style="yellow", end=" ")
    console.print("https://t.me/HellsKey", style="green")
    console.print("📲 Telegram Channel:", style="yellow", end=" ")
    console.print("https://t.me/+mh91Ns55-6kwNDgx", style="green")
    console.print("🌐 Dark Web Site:", style="yellow", end=" ")
    console.print("http://2dpg7coa4gi4rw2pjaor4cwwcelspqlpt2yvmu6avgk6mq3jmwz6pxad.onion", style="cyan")
    console.print("🐙 GitHub:", style="yellow", end=" ")
    console.print("https://github.com/HellsKey", style="magenta")

    # Hashtags
    console.print("\n#UPL_DataSpill #BlackHat #ExclusiveLeaks #DataBreach #VIP #LeakedFiles #DarkWeb", style="white")

# ==================== Token Info ====================
def show_token_info(token):
    if not token:
        console.print("[yellow]No token configured. Run --init to save one.[/yellow]")
        return
    valid = validate_hellskey_token(token)
    if valid:
        console.print("[green]✓ Token is VALID[/green]")
        console.print("[cyan]Subscriber status: [bold]ACTIVE[/bold][/cyan]")
    else:
        console.print("[red]✗ Token is INVALID[/red]")
        console.print("[yellow]Please obtain a valid token.[/yellow]")

# ==================== Help Menu ====================
def show_help():
    console.print("\n[bold cyan]HELLSKEY BREACH – Elite OSINT Framework[/bold cyan]")
    console.print("[dim]A comprehensive tool for gathering intelligence from dark web sources.[/dim]\n")

    console.print("[bold yellow]USAGE:[/bold yellow]")
    console.print("  hellskey_breach.py [QUERY] [OPTIONS]\n")

    categories = [
        ("🔍 BASIC SEARCHES", [
            ("hellskey_breach.py example.com", "Basic search (exact domain)"),
            ("hellskey_breach.py example.com --method domain.all", "Search domain + subdomains"),
            ("hellskey_breach.py example.com --view-type subdomain", "Show only subdomains"),
            ("hellskey_breach.py example.com --view-type related", "Show related companies"),
        ]),
        ("🔐 CREDENTIAL SEARCHES", [
            ("hellskey_breach.py someone@example.com --method cred.email", "Search by email"),
            ("hellskey_breach.py someone --method cred.username", "Search by username"),
            ("hellskey_breach.py example@123 --method cred.password", "Search by password"),
            ("hellskey_breach.py US --method cred.country", "Search credentials by country"),
            ("hellskey_breach.py example.com --method cred.email.domain", "Search creds by domain emails"),
        ]),
        ("📱 APPLICATION SEARCHES", [
            ("hellskey_breach.py com.discord --method app.id", "Search by app ID"),
            ("hellskey_breach.py discord.com --method app.domain", "Search by app domain"),
            ("hellskey_breach.py Discord --method app.name", "Search by app name"),
        ]),
        ("🌐 NETWORK SEARCHES", [
            ("hellskey_breach.py 1.1.1.1 --method ip", "IP lookup"),
            ("hellskey_breach.py xx.xx.xx.0/24 --method ip", "CIDR search"),
            ("hellskey_breach.py AS123 --method ip.asn", "Search by IP ASN"),
            ("hellskey_breach.py /wp-login.php --method url.path", "Search URL path"),
        ]),
        ("⚙️  BATCH & OUTPUT", [
            ("hellskey_breach.py targets.txt -o results.txt", "Batch search from file"),
            ("hellskey_breach.py targets.txt --threads 5", "Batch search with 5 threads"),
            ("hellskey_breach.py example.com --scan", "Full domain scan"),
            ("hellskey_breach.py example.com --scan -o report.json --output-type json", "Save scan as JSON"),
        ]),
        ("🔑 TOKEN MANAGEMENT", [
            ("hellskey_breach.py --init YOUR_TOKEN", "Save your token (full access)"),
            ("hellskey_breach.py --info", "Check token status"),
        ]),
    ]

    for title, commands in categories:
        table = Table(title=f"[bold magenta]{title}[/bold magenta]", box=box.ROUNDED, header_style="bold cyan")
        table.add_column("Command", style="green")
        table.add_column("Purpose", style="white")
        for cmd, purpose in commands:
            table.add_row(cmd, purpose)
        console.print(table)
        console.print()

    console.print("[bold yellow]NOTES:[/bold yellow]")
    console.print("• [cyan]--view-type[/cyan] filters results after retrieval (e.g., subdomain, related, ip, email).")
    console.print("• [cyan]--method[/cyan] determines which data types the API returns.")
    console.print("• Without a valid token, sensitive data (emails, usernames, passwords) are base64‑encoded.")
    console.print("• Tor must be running for .onion access. Use [cyan]--no-tor-check[/cyan] to bypass.")

# ==================== Main CLI ====================
def main():
    if len(sys.argv) == 1 or '--help' in sys.argv or '-h' in sys.argv:
        show_team_banner()
        show_help()
        sys.exit(0)

    parser = argparse.ArgumentParser(description='HellsKey Breach - Elite OSINT Tool', add_help=False)
    parser.add_argument('query', nargs='?', help='Search query or file path')
    parser.add_argument('--init', help='Initialize with your HellsKey token')
    parser.add_argument('--info', action='store_true', help='Show token status and team info')
    parser.add_argument('-m', '--method', default='domain', help='Search method')
    parser.add_argument('--view-type', help='Filter output by type')
    parser.add_argument('--scan', action='store_true', help='Perform full domain scan')
    parser.add_argument('-o', '--output', help='Output file')
    parser.add_argument('-ot', '--output-type', choices=['text', 'json', 'csv'], default='text', help='Output format')
    parser.add_argument('-t', '--timeout', type=int, default=60, help='Request timeout')
    parser.add_argument('-l', '--limit', type=int, default=10000, help='Result limit')
    parser.add_argument('--threads', type=int, default=1, help='Number of threads for batch processing')
    parser.add_argument('-nc', '--no-color', action='store_true', help='Disable colors')
    parser.add_argument('--no-tor-check', action='store_true', help='Skip Tor connectivity check')
    parser.add_argument('-v', '--version', action='store_true', help='Show version')
    argcomplete.autocomplete(parser)
    args = parser.parse_args()

    if args.version:
        console.print(VERSION)
        sys.exit(0)

    if not args.no_color:
        show_team_banner()

    if not args.no_tor_check and not check_tor():
        console.print("[red]Tor is not reachable. Please start Tor or use --no-tor-check to bypass.[/red]")
        sys.exit(1)

    config_file = Path.home() / '.hellskey_breach_config.json'
    if args.init:
        token = args.init
        console.print("[yellow]Validating token...[/yellow]")
        if validate_hellskey_token(token):
            with open(config_file, 'w') as f:
                json.dump({'token': token}, f)
            console.print("[green]Token saved successfully. You now have full access.[/green]")
        else:
            console.print("[red]Invalid token. You will see obfuscated results only.[/red]")
        sys.exit(0)

    if args.info:
        token = None
        if config_file.exists():
            with open(config_file) as f:
                config = json.load(f)
                token = config.get('token')
        show_token_info(token)
        sys.exit(0)

    token = None
    if config_file.exists():
        with open(config_file) as f:
            config = json.load(f)
        token = config.get('token')

    core = HellsKeyAPICore(token=token, debug=True)

    if not core.subscriber:
        console.print("[yellow]You are using the free tier. Results are obfuscated. Subscribe for full access.[/yellow]")

    if args.scan:
        if not args.query:
            console.print("[red]Please provide a domain for scan.[/red]")
            sys.exit(1)
        domain = get_root_domain(args.query)
        if not domain:
            console.print("[red]Invalid domain.[/red]")
            sys.exit(1)
        run_scan(domain, args, core)
        sys.exit(0)

    if not args.query:
        console.print("[red]Please provide a query or use --scan.[/red]")
        sys.exit(1)

    queries = []
    if os.path.isfile(args.query):
        queries = read_file(args.query)
    else:
        queries = [args.query]

    all_results = []
    pages_info = []

    if args.threads > 1 and len(queries) > 1:
        q = queue.Queue()
        for qry in queries:
            q.put(qry)
        for _ in range(args.threads):
            q.put(None)
        threads = []
        for _ in range(args.threads):
            t = threading.Thread(target=worker, args=(q, core, args.method, args.limit, args.timeout, all_results, pages_info))
            t.start()
            threads.append(t)
        for t in threads:
            t.join()
    else:
        for qry in queries:
            results, pages = core.search(
                query=qry,
                method=args.method,
                limit=args.limit,
                timeout=args.timeout,
                use_spinner=True,
                callback=lambda r: console.print(r.print() + '\n') if not args.view_type else None,
                search_text=f"[green]Querying {qry}...[/green]",
                err_text=f"[red]No results for {qry}[/red]"
            )
            if pages > 1:
                console.print(f"Pages count: {pages}")
            all_results.extend(results)

    if args.view_type:
        all_results = filter_by_view_type(all_results, args.view_type)

    if args.threads > 1 or not args.view_type:
        for res in all_results:
            console.print(res.print())
            console.print()

    for qry, pages in pages_info:
        if pages > 1:
            console.print(f"Pages count for {qry}: {pages}")

    if args.output and all_results:
        save_output(all_results, args.output, args.output_type)
        console.print(f"[green]Results saved to {args.output}[/green]")

def run_scan(domain, args, core):
    output_dir = Path(domain)
    output_dir.mkdir(exist_ok=True)

    console.print(f"[yellow]Starting full scan for {domain}[/yellow]")

    all_client_results = []
    all_employee_results = []
    subdomains_set = set()
    ips_set = set()

    # 1. Related companies
    console.print(f"\n[magenta]⚓  Find {domain} related companies...[/magenta]")
    related, pages = core.search(
        query=domain,
        method='domain',
        limit=args.limit,
        timeout=args.timeout,
        use_spinner=True,
        callback=None,
        search_text="",
        err_text=""
    )
    console.print(f"Pages count: {pages if pages else 'unknown'}")
    if not related:
        console.print(f"[red]💥  Not found related ![/red]")
    console.print(f"[magenta]{'-'*30}[/magenta]")

    # 2. Subdomains
    console.print(f"\n[magenta]⚓  Find {domain} subdomains...[/magenta]")
    subs_raw, pages = core.search(
        query=domain,
        method='domain',
        limit=args.limit,
        timeout=args.timeout,
        use_spinner=True,
        callback=None,
        search_text="",
        err_text=""
    )
    console.print(f"Pages count: {pages}")
    unique_subs = {}
    for s in subs_raw:
        if s.domain and s.domain not in unique_subs:
            unique_subs[s.domain] = s
    if unique_subs:
        for s_domain, s_obj in unique_subs.items():
            console.print(s_obj.print())
            subdomains_set.add(s_domain)
    else:
        console.print(f"[red]💥  Not found subdomains ![/red]")
    console.print(f"[magenta]{'-'*30}[/magenta]")

    # 3. Apps
    console.print(f"\n[magenta]⚓  Find {domain} apps...[/magenta]")
    apps, pages = core.search(
        query=domain,
        method='app.domain',
        limit=args.limit,
        timeout=args.timeout,
        use_spinner=True,
        callback=lambda r: console.print(r.print() + '\n'),
        search_text="",
        err_text=""
    )
    console.print(f"Pages count: {pages}")
    if not apps:
        console.print(f"[red]💥  Not found apps ![/red]")
    console.print(f"[magenta]{'-'*30}[/magenta]")

    # 4. IPs
    console.print(f"\n[magenta]⚓  Find {domain} IPs...[/magenta]")
    ips_main, pages = core.search(
        query=domain,
        method='ip',
        limit=args.limit,
        timeout=args.timeout,
        use_spinner=True,
        callback=None,
        search_text="",
        err_text=""
    )
    console.print(f"Pages count: {pages}")
    for r in ips_main:
        if is_valid_ip(r.value):
            console.print(f"[magenta][ IP ]> [cyan]{r.value}[/cyan]")
            ips_set.add(r.value)
    if not any(is_valid_ip(r.value) for r in ips_main):
        console.print(f"[red]💥  Not found ips ![/red]")
    console.print()

    for sub in subdomains_set:
        if sub == domain:
            continue
        console.print(f"[magenta]⚓  Find {sub} IPs...[/magenta]")
        sub_ips, pages = core.search(
            query=sub,
            method='ip',
            limit=args.limit,
            timeout=args.timeout,
            use_spinner=True,
            callback=None,
            search_text="",
            err_text=""
        )
        console.print(f"Pages count: {pages}")
        for r in sub_ips:
            if is_valid_ip(r.value):
                console.print(f"[magenta][ IP ]> [cyan]{r.value}[/cyan]")
                ips_set.add(r.value)
        if not any(is_valid_ip(r.value) for r in sub_ips):
            console.print(f"[red]💥  Not found ips ![/red]")
        console.print()

    console.print(f"[magenta]{'-'*30}[/magenta]")

    # 5. Client creds
    console.print(f"\n[magenta]⚓  Find {domain} client creds...[/magenta]")
    client_results, pages = core.search(
        query=domain,
        method='domain.all',
        limit=args.limit,
        timeout=args.timeout,
        use_spinner=True,
        callback=None,
        search_text="",
        err_text=""
    )
    console.print(f"Pages count: {pages}")
    if client_results:
        for res in client_results:
            console.print(res.print())
            console.print()
        all_client_results.extend(client_results)
        classify_and_save(client_results, output_dir, prefix='client')
    else:
        console.print(f"[red]💥  Not found clients ![/red]")

    # 6. Employee creds
    console.print(f"\n[magenta]⚓  Find {domain} employees creds...[/magenta]")
    employee_results, pages = core.search(
        query=domain,
        method='cred.email.domain',
        limit=args.limit,
        timeout=args.timeout,
        use_spinner=True,
        callback=None,
        search_text="",
        err_text=""
    )
    console.print(f"Pages count: {pages}")
    if employee_results:
        for res in employee_results:
            console.print(res.print())
            console.print()
        all_employee_results.extend(employee_results)
        classify_and_save(employee_results, output_dir, prefix='employe')
    else:
        console.print(f"[red]💥  Not found Employees![/red]")

    # 7. Save scan.json
    scan_data = {
        'subdomains': list(subdomains_set),
        'ips': list(ips_set),
        'client': {
            'emails': list(set(r.email for r in all_client_results if r.email)),
            'usernames': list(set(r.username for r in all_client_results if r.username)),
            'passwords': list(set(r.password for r in all_client_results if r.password)),
            'urls': list(set(r.url for r in all_client_results if r.url)),
            'paths': list(set(r.path for r in all_client_results if r.path)),
            'ports': list(set(r.port for r in all_client_results if r.port)),
        } if all_client_results else {},
        'employee': {
            'emails': list(set(r.email for r in all_employee_results if r.email)),
            'usernames': list(set(r.username for r in all_employee_results if r.username)),
            'passwords': list(set(r.password for r in all_employee_results if r.password)),
            'urls': list(set(r.url for r in all_employee_results if r.url)),
            'paths': list(set(r.path for r in all_employee_results if r.path)),
            'ports': list(set(r.port for r in all_employee_results if r.port)),
        } if all_employee_results else {}
    }
    with open(output_dir / 'scan.json', 'w') as f:
        json.dump(scan_data, f, indent=2)
    console.print(f"[green]scan.json saved[/green]")

    console.print(f"[magenta]>[yellow] Saved output: [/yellow]")
    for file in output_dir.iterdir():
        if file.is_file():
            console.print(f"\t[magenta]-[/magenta] [blue]{file}[/blue]")
    console.print()

def classify_and_save(results, output_dir, prefix):
    emails = set()
    usernames = set()
    passwords = set()
    urls = set()
    paths = set()
    ports = set()

    for r in results:
        if r.email:
            emails.add(r.email if r.subscriber else obfuscate(r.email))
        if r.username:
            usernames.add(r.username if r.subscriber else obfuscate(r.username))
        if r.password:
            passwords.add(r.password if r.subscriber else obfuscate(r.password))
        if r.url:
            urls.add(r.url)
        if r.path:
            paths.add(r.path)
        if r.port:
            ports.add(r.port)

    if emails:
        write_file(output_dir / f'{prefix}-emails.txt', '\n'.join(sorted(emails)))
        console.print(f"[green]Saved {len(emails)} emails to {prefix}-emails.txt[/green]")
    if usernames:
        write_file(output_dir / f'{prefix}-usernames.txt', '\n'.join(sorted(usernames)))
        console.print(f"[green]Saved {len(usernames)} usernames to {prefix}-usernames.txt[/green]")
    if passwords:
        write_file(output_dir / f'{prefix}-passwords.txt', '\n'.join(sorted(passwords)))
        console.print(f"[green]Saved {len(passwords)} passwords to {prefix}-passwords.txt[/green]")
    if urls:
        write_file(output_dir / f'{prefix}-urls.txt', '\n'.join(sorted(urls)))
        console.print(f"[green]Saved {len(urls)} URLs to {prefix}-urls.txt[/green]")
    if paths:
        write_file(output_dir / f'{prefix}-paths.txt', '\n'.join(sorted(paths)))
        console.print(f"[green]Saved {len(paths)} paths to {prefix}-paths.txt[/green]")
    if ports:
        write_file(output_dir / f'{prefix}-ports.txt', '\n'.join(sorted(ports)))
        console.print(f"[green]Saved {len(ports)} ports to {prefix}-ports.txt[/green]")

def save_output(results, filename, fmt):
    if fmt == 'text':
        data = '\n'.join([r.save_format() for r in results])
        write_file(filename, data)
    elif fmt == 'json':
        data = [{'type': r.type, 'domain': r.domain, 'value': r.save_format(), 'file': r.file,
                 'url': r.url, 'path': r.path, 'port': r.port,
                 'email': r.email if r.subscriber else obfuscate(r.email),
                 'username': r.username if r.subscriber else obfuscate(r.username),
                 'password': r.password if r.subscriber else obfuscate(r.password),
                 'country': r.country} for r in results]
        with open(filename, 'w') as f:
            json.dump(data, f, indent=2)
    else:  # csv
        lines = ['type,domain,value,file,url,path,port,email,username,password,country']
        for r in results:
            val = r.save_format()
            email = r.email if r.subscriber else obfuscate(r.email) if r.email else ''
            uname = r.username if r.subscriber else obfuscate(r.username) if r.username else ''
            pwd = r.password if r.subscriber else obfuscate(r.password) if r.password else ''
            lines.append(f"{r.type},{r.domain},{val},{r.file},{r.url},{r.path},{r.port},{email},{uname},{pwd},{r.country}")
        write_file(filename, '\n'.join(lines))

if __name__ == "__main__":
    main()
