"""Check that Booth can make HTTPS connections on a Mac (run by the release workflow on each Mac runner).

The app's Python looks for trusted certificates where it was built (on the runners, a python.org Python's
own cert.pem). Testers' Macs don't have that file, so setup failed at plex.tv until Booth pointed Python at
the list macOS keeps (radiobooth.cli.use_system_certificates). The runner does have the file, so this checks
the macOS list on its own, the way testers' Macs use it. Any answer from the server, even an error page,
means the certificate checked out.
"""

import ssl
import sys
import urllib.error
import urllib.request

from radiobooth import cli

print("Python's own certificate paths:", ssl.get_default_verify_paths())
macos_only = ssl.create_default_context(cafile=cli.MAC_CERTIFICATES)
try:
    urllib.request.urlopen("https://plex.tv/", timeout=30, context=macos_only).close()
except urllib.error.HTTPError as e:
    print(f"plex.tv answered HTTP {e.code}")
except urllib.error.URLError as e:
    sys.exit(f"HTTPS with {cli.MAC_CERTIFICATES} failed: {e.reason}")
print(f"HTTPS to plex.tv with {cli.MAC_CERTIFICATES}: ok")
