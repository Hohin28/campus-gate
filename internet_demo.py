"""Campus Gate — Internet demo launcher.

Makes the app reachable from ANYWHERE (phone on its own mobile data, laptop on
any network) by opening a public HTTPS tunnel to the local server:

    laptop (uvicorn on 127.0.0.1:8000)
        -> tunnel (outbound only, no router/firewall setup)
        -> https://<public-url>   <- phone opens this from any network

Two transports, tried in order:
  1. cloudflared quick tunnel  (needs outbound port 7844 — fine on home
     Wi-Fi / phone hotspots, often BLOCKED on college networks)
  2. Pinggy over SSH port 443  (443 is plain HTTPS — open on almost every
     network; free sessions last ~60 minutes, restart to renew)

The public URL is real HTTPS, so the phone camera works with NO security
warning. The URL changes on every start; only people you give it to — and
who have a login — can use it.

Run via "Start Campus Gate (Internet Demo).bat".
"""
import os
import queue
import re
import subprocess
import sys
import threading
import time
import urllib.request

ROOT = os.path.dirname(os.path.abspath(__file__))
TOOLS = os.path.join(ROOT, "tools")
CF_EXE = os.path.join(TOOLS, "cloudflared.exe")
CF_LOG = os.path.join(TOOLS, "cloudflared.log")
TUNNEL_TXT = os.path.join(ROOT, "frontend", "tunnel.txt")
CF_URL = ("https://github.com/cloudflare/cloudflared/releases/latest/"
          "download/cloudflared-windows-amd64.exe")

RE_CF = re.compile(r"https://[a-z0-9-]+\.trycloudflare\.com")
RE_PINGGY = re.compile(r"https://[a-zA-Z0-9.-]+\.pinggy(?:-free)?\.(?:link|net)")


def ensure_cloudflared():
    if os.path.exists(CF_EXE):
        return True
    os.makedirs(TOOLS, exist_ok=True)
    print("First run: downloading cloudflared (~60 MB, one time)...")
    try:
        urllib.request.urlretrieve(CF_URL, CF_EXE + ".part")
        os.replace(CF_EXE + ".part", CF_EXE)
        print("Download complete.")
        return True
    except Exception as e:
        print(f"Could not download cloudflared ({e}); will use the SSH tunnel.")
        return False


class Piped:
    """Run a process and stream its merged output through a queue,
    so we can wait for patterns with a deadline."""

    def __init__(self, cmd, log_path=None):
        self.proc = subprocess.Popen(
            cmd, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
            text=True, encoding="utf-8", errors="replace")
        self.q = queue.Queue()
        self.log = open(log_path, "w", encoding="utf-8") if log_path else None
        threading.Thread(target=self._pump, daemon=True).start()

    def _pump(self):
        for line in self.proc.stdout:
            if self.log:
                self.log.write(line)
                self.log.flush()
            self.q.put(line)
        self.q.put(None)

    def wait_for(self, checker, timeout):
        """checker(line) -> value or None. Returns value, or None on timeout/exit."""
        deadline = time.time() + timeout
        while time.time() < deadline:
            try:
                line = self.q.get(timeout=0.5)
            except queue.Empty:
                continue
            if line is None:
                return None
            val = checker(line)
            if val is not None:
                return val
        return None

    def stop(self):
        try:
            self.proc.terminate()
        except Exception:
            pass
        if self.log:
            try:
                self.log.close()
            except Exception:
                pass


def try_cloudflared():
    if not ensure_cloudflared():
        return None
    print("Trying tunnel 1/2: Cloudflare...")
    p = Piped([CF_EXE, "tunnel", "--url", "http://127.0.0.1:8000",
               "--protocol", "http2", "--no-autoupdate"], log_path=CF_LOG)

    state = {"url": None}
    def check(line):
        if state["url"] is None:
            m = RE_CF.search(line)
            if m:
                state["url"] = m.group(0)
        # ready only once a connection is actually registered with the edge
        if "Registered tunnel connection" in line and state["url"]:
            return state["url"]
        return None

    url = p.wait_for(check, timeout=30)
    if url:
        return p, url, "Cloudflare"
    print("  Cloudflare tunnel blocked on this network (port 7844).")
    p.stop()
    return None


def try_pinggy():
    print("Trying tunnel 2/2: Pinggy over port 443 (works on strict networks)...")
    cmd = ["ssh", "-T", "-p", "443",
           "-o", "StrictHostKeyChecking=no",
           "-o", "ServerAliveInterval=30",
           "-o", "ConnectTimeout=12",
           "-o", "ExitOnForwardFailure=yes",
           "-R", "0:127.0.0.1:8000", "a.pinggy.io"]
    p = Piped(cmd)

    def check(line):
        m = RE_PINGGY.search(line)
        return m.group(0) if m else None

    url = p.wait_for(check, timeout=40)
    if url:
        return p, url, "Pinggy (free session ~60 min; restart to renew)"
    print("  Pinggy did not respond either.")
    p.stop()
    return None


def clear_tunnel_file():
    """Remove any URL left behind by a previous (crashed) run."""
    try:
        if os.path.exists(TUNNEL_TXT):
            os.remove(TUNNEL_TXT)
    except OSError:
        pass


def start_heartbeat(url):
    """Re-touch tunnel.txt every 20s. The server only advertises the public
    URL while this heartbeat is fresh, so a dead tunnel is never handed to
    the phone (that used to leave a stale QR pointing nowhere)."""
    def beat():
        while True:
            try:
                with open(TUNNEL_TXT, "w") as f:
                    f.write(url)
            except OSError:
                pass
            time.sleep(20)
    threading.Thread(target=beat, daemon=True).start()


def banner(url, transport):
    with open(TUNNEL_TXT, "w") as f:
        f.write(url)
    start_heartbeat(url)
    print("")
    print("=" * 64)
    print("  PUBLIC URL - works from ANY network / mobile data:")
    print("")
    print("    " + url)
    print("")
    print("  On the phone: open that URL and log in (guard1/guard123).")
    print("  QR page:        " + url + "/connect")
    print("  Face station:   " + url + "/face")
    print("  Warden laptop:  " + url + "  (or http://localhost:8000)")
    print("")
    print("  Tunnel: " + transport)
    print("  Real HTTPS -> camera works, NO security warning.")
    print("  Keep this window OPEN. Close it to stop everything.")
    print("=" * 64)
    print("")


def main():
    clear_tunnel_file()   # never advertise a URL from a previous run
    print("Starting Campus Gate server (local)...")
    uv = subprocess.Popen(
        [sys.executable, "-m", "uvicorn", "main:app", "--app-dir", "backend",
         "--host", "127.0.0.1", "--port", "8000", "--log-level", "warning"],
        cwd=ROOT)

    tun = try_cloudflared() or try_pinggy()
    try:
        if not tun:
            print("")
            print("No internet tunnel could be opened (is the laptop online?).")
            print("Fallback: use the phone's HOTSPOT + 'Start Campus Gate")
            print("(Phone Demo).bat' — that works with no internet tunnel.")
            try:
                input("Press Enter to stop...")
            except EOFError:
                pass
            return
        p, url, transport = tun
        banner(url, transport)
        # keep pumping tunnel output until it dies or the user closes the window
        while True:
            try:
                line = p.q.get(timeout=1)
            except queue.Empty:
                continue
            if line is None:
                print("Tunnel closed. Restart this launcher to get a new URL.")
                break
    except KeyboardInterrupt:
        pass
    finally:
        try:
            if os.path.exists(TUNNEL_TXT):
                os.remove(TUNNEL_TXT)
        except OSError:
            pass
        if tun:
            tun[0].stop()
        try:
            uv.terminate()
        except Exception:
            pass
        print("Stopped.")


if __name__ == "__main__":
    main()
