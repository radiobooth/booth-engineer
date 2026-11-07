"""Check that Booth can make HTTPS connections from this Python (run by the release workflow on each Mac).

The Python inside the Mac app can't find macOS's trusted certificates by itself, so setup failed at plex.tv
on testers' Macs until Booth pointed it at them (radiobooth.cli.use_system_certificates). Any answer from
the server, even an error page, means the certificate checked out.
"""

import ssl
import sys
import urllib.error
import urllib.request

from radiobooth import cli

print("Python's own certificate paths:", ssl.get_default_verify_paths())
cli.use_system_certificates()
try:
    urllib.request.urlopen("https://plex.tv/", timeout=30).close()
except urllib.error.HTTPError as e:
    print(f"plex.tv answered HTTP {e.code}")
except urllib.error.URLError as e:
    sys.exit(f"HTTPS failed: {e.reason}")
print("HTTPS to plex.tv: ok")
