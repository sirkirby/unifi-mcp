"""UniFi Drive: storage, shared drives and file services on a UniFi NAS (UNAS).

A UNAS is its own UniFi OS console, separate from the gateway, so nothing here
goes through the Network application. Requests use the console's local login
(``/api/auth/login``) and the Drive application's proxy path
``/proxy/drive/api/...``.
"""
