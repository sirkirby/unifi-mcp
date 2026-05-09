import asyncio
import logging
from typing import Any, Dict, List, Optional

import aiohttp
from aiounifi.models.api import ApiRequest
from aiounifi.models.site import Site  # Import Site model

from unifi_core.network.managers.connection_manager import ConnectionManager

logger = logging.getLogger("unifi-network-mcp")

CACHE_PREFIX_SYSINFO = "system_info"
CACHE_PREFIX_SETTINGS = "settings"
CACHE_PREFIX_SITES = "sites"
CACHE_PREFIX_ADMINS = "admin_users"


class SystemManager:
    """Manages system, site, and user operations on the Unifi Controller."""

    def __init__(self, connection_manager: ConnectionManager):
        """Initialize the System Manager.

        Args:
            connection_manager: The shared ConnectionManager instance.
        """
        self._connection = connection_manager

    async def get_system_info(self) -> Dict[str, Any]:
        """Get system information including version, uptime, etc."""
        cache_key = f"{CACHE_PREFIX_SYSINFO}_{self._connection.site}"
        cached_data = self._connection.get_cached(cache_key, timeout=15)
        if cached_data is not None:
            return cached_data

        try:
            api_request = ApiRequest(method="get", path="/stat/sysinfo")
            response = await self._connection.request(api_request)
            if isinstance(response, list) and len(response) > 0:
                info = response[0] if isinstance(response[0], dict) else {}
            elif isinstance(response, dict):
                info = response
            else:
                info = {}
            self._connection._update_cache(cache_key, info, timeout=15)
            return info
        except Exception as e:
            logger.error("Error getting system info: %s", e)
            raise

    async def get_controller_status(self) -> Dict[str, Any]:
        """Get status information about the controller."""
        try:
            api_request = ApiRequest(method="get", path="/stat/status")
            response = await self._connection.request(api_request)
            if isinstance(response, list) and len(response) > 0:
                return response[0] if isinstance(response[0], dict) else {}
            elif isinstance(response, dict):
                return response
            return {}
        except Exception as e:
            logger.error("Error getting controller status: %s", e)
            raise

    async def create_backup(self) -> Optional[Dict[str, Any]]:
        """Create a backup of the controller configuration.

        Returns:
            Dict with backup metadata including download URL, or None on failure.
        """
        try:
            api_request = ApiRequest(method="post", path="/cmd/backup", data={"cmd": "backup"})
            response = await self._connection.request(api_request)
            if isinstance(response, list) and response:
                logger.info("Backup creation requested successfully.")
                return response[0]
            if isinstance(response, dict) and response.get("url"):
                logger.info("Backup creation requested successfully.")
                return response
            logger.error("Unexpected backup response: %s", response)
            return None
        except Exception as e:
            logger.error("Error creating backup: %s", e, exc_info=True)
            raise

    async def restore_backup(self, backup_data: bytes) -> bool:
        """Restore a controller configuration from backup.

        Args:
            backup_data: Backup data as bytes

        Returns:
            bool: True if successful, False otherwise
        """
        if not await self._connection.ensure_connected() or not self._connection.controller:
            raise ConnectionError("Not connected to controller")
        try:
            form = aiohttp.FormData()
            form.add_field(
                "file",
                backup_data,
                filename="backup.unf",
                content_type="application/octet-stream",
            )

            restore_url = f"{self._connection.url_base}/api/s/{self._connection.site}/cmd/restore"
            logger.info("Attempting to restore backup via POST to %s", restore_url)

            async with self._connection.controller.session.post(restore_url, data=form) as response:
                if response.status == 200:
                    logger.info("Backup restoration initiated successfully.")
                    self._connection._invalidate_cache()
                    self._connection._initialized = False
                    return True
                else:
                    response_text = await response.text()
                    logger.error("Error restoring backup: HTTP %s, Response: %s", response.status, response_text)
                    return False
        except Exception as e:
            logger.error("Exception during backup restore: %s", e)
            raise

    async def list_backups(self) -> List[Dict[str, Any]]:
        """List available backups on the controller.

        Returns:
            List of backup dicts with filename, datetime, size, etc.
        """
        try:
            api_request = ApiRequest(method="post", path="/cmd/backup", data={"cmd": "list-backups"})
            response = await self._connection.request(api_request)
            if isinstance(response, list):
                return response
            if isinstance(response, dict):
                return response.get("data", [])
            return []
        except Exception as e:
            logger.error("Error listing backups: %s", e, exc_info=True)
            raise

    async def delete_backup(self, filename: str) -> bool:
        """Delete a backup file from the controller.

        Args:
            filename: Backup filename (from list_backups).

        Returns:
            True on success, False on failure.
        """
        try:
            api_request = ApiRequest(
                method="post",
                path="/cmd/backup",
                data={"cmd": "delete-backup", "filename": filename},
            )
            await self._connection.request(api_request)
            logger.info("Backup '%s' deleted successfully.", filename)
            return True
        except Exception as e:
            logger.error("Error deleting backup '%s': %s", filename, e, exc_info=True)
            raise

    async def get_autobackup_settings(self) -> Dict[str, Any]:
        """Get auto-backup settings from the controller.

        Returns:
            Dict with autobackup_enabled, cron schedule, retention, cloud settings.
        """
        try:
            settings_list = await self.get_settings("super_mgmt")
            if not settings_list:
                return {}
            settings = settings_list[0]
            return {
                "autobackup_enabled": settings.get("autobackup_enabled", False),
                "autobackup_cron_expr": settings.get("autobackup_cron_expr"),
                "autobackup_days": settings.get("autobackup_days"),
                "autobackup_max_files": settings.get("autobackup_max_files"),
                "autobackup_timezone": settings.get("autobackup_timezone"),
                "autobackup_cloud_enabled": settings.get("autobackup_cloud_enabled", False),
            }
        except Exception as e:
            logger.error("Error getting auto-backup settings: %s", e, exc_info=True)
            raise

    async def update_autobackup_settings(self, settings: Dict[str, Any]) -> bool:
        """Update auto-backup settings on the controller.

        Args:
            settings: Dict of auto-backup fields to update.

        Returns:
            True on success, False on failure.
        """
        try:
            # update_settings handles cache invalidation with correct site-qualified key
            return await self.update_settings("super_mgmt", settings)
        except Exception as e:
            logger.error("Error updating auto-backup settings: %s", e, exc_info=True)
            raise

    async def check_firmware_updates(self) -> Dict[str, Any]:
        """Check for firmware updates for devices."""
        try:
            api_request = ApiRequest(
                method="get",
                path=f"/api/s/{self._connection.site}/stat/fwupdate/latest-version",
            )
            response = await self._connection.request(api_request)
            if isinstance(response, list) and len(response) > 0:
                return response[0] if isinstance(response[0], dict) else {}
            elif isinstance(response, dict):
                return response
            return {}
        except Exception as e:
            logger.error("Error checking firmware updates: %s", e)
            raise

    async def upgrade_controller(self) -> bool:
        """Upgrade the controller to the latest version (requires confirmation)."""
        logger.warning("Initiating controller upgrade. This is a potentially disruptive operation.")
        try:
            api_request = ApiRequest(method="post", path="/cmd/system", data={"cmd": "upgrade"})
            response = await self._connection.request(api_request)

            success = isinstance(response, dict) and response.get("meta", {}).get("rc") == "ok"
            if success:
                logger.info("Controller upgrade initiated successfully.")
                self._connection._initialized = False
            else:
                logger.error("Error initiating controller upgrade: %s", response)

            return success
        except Exception as e:
            logger.error("Error upgrading controller: %s", e)
            raise

    async def reboot_controller(self) -> bool:
        """Reboot the controller (requires confirmation)."""
        logger.warning("Initiating controller reboot. This is a potentially disruptive operation.")
        try:
            api_request = ApiRequest(method="post", path="/cmd/system", data={"cmd": "reboot"})
            response = await self._connection.request(api_request)

            success = isinstance(response, dict) and response.get("meta", {}).get("rc") == "ok"
            if success:
                logger.info("Controller reboot initiated successfully.")
                self._connection._initialized = False
            else:
                logger.error("Error initiating controller reboot: %s", response)

            return success
        except Exception as e:
            logger.error("Error rebooting controller: %s", e)
            raise

    async def get_settings(self, section: str) -> List[Dict[str, Any]]:  # API returns list
        """Get system settings for a specific section.

        Args:
            section: Settings section (e.g., "super", "guest_access", "mgmt")

        Returns:
            List containing the settings dictionary (usually just one element)
        """
        cache_key = f"{CACHE_PREFIX_SETTINGS}_{section}_{self._connection.site}"
        cached_data = self._connection.get_cached(cache_key)
        if cached_data is not None:
            return cached_data

        try:
            api_request = ApiRequest(method="get", path=f"/get/setting/{section}")
            response = await self._connection.request(api_request)
            settings_list = response if isinstance(response, list) else []
            self._connection._update_cache(cache_key, settings_list)
            return settings_list
        except Exception as e:
            logger.error("Error getting %s settings: %s", section, e)
            raise

    async def update_settings(self, section: str, settings_data: Dict[str, Any]) -> bool:
        """Update system settings for a specific section.

        Args:
            section: Settings section (e.g., "super", "guest_access", "mgmt")
            settings_data: Dictionary with updated settings (should include _id if modifying existing)

        Returns:
            bool: True if successful, False otherwise
        """
        try:
            current_settings_list = await self.get_settings(section)
            if not current_settings_list or not isinstance(current_settings_list[0], dict):
                logger.warning(
                    "Could not get current settings for section '%s' to update, proceeding without _id check.", section
                )
                settings_id = None
            else:
                settings_id = current_settings_list[0].get("_id")

            if "_id" not in settings_data and settings_id:
                settings_data["_id"] = settings_id
            elif "_id" not in settings_data:
                logger.warning(
                    "Attempting to update settings section '%s' without an _id. This might not work as expected.",
                    section,
                )

            if "key" not in settings_data:
                settings_data["key"] = section

            endpoint = f"/set/setting/{section}"

            api_request = ApiRequest(method="put", path=endpoint, data=settings_data)
            response = await self._connection.request(api_request)

            self._connection._invalidate_cache(f"{CACHE_PREFIX_SETTINGS}_{section}_{self._connection.site}")

            success = isinstance(response, dict) and response.get("meta", {}).get("rc") == "ok"
            if not success and isinstance(response, list) and len(response) > 0:
                success = True

            if success:
                logger.info("%s settings updated successfully", section)
            else:
                logger.error("Error updating %s settings: %s", section, response)

            return success
        except Exception as e:
            logger.error("Error updating %s settings: %s", section, e)
            raise

    async def get_network_health(self) -> List[Dict[str, Any]]:
        """Return a summary of the controller network health.

        The official UniFi Network controller exposes a convenient endpoint that aggregates
        overall health information (WAN connectivity, number of devices, users, etc.) at
        `/stat/health`.  Unlike other ``/stat/*`` endpoints that wrap a single dict in a list,
        this endpoint returns a **multi-element list** — one dict per subsystem (wan, lan,
        wlan, vpn, etc.).

        This helper wraps that call and caches the result for a short period because the data
        is fairly volatile but still expensive to compute for the controller.
        """

        cache_key = f"health_{self._connection.site}"
        cached_data: Optional[List[Dict[str, Any]]] = self._connection.get_cached(cache_key, timeout=10)
        if cached_data is not None:
            return cached_data

        try:
            api_request = ApiRequest(
                method="get",
                path="/stat/health",
            )
            response = await self._connection.request(api_request)

            if isinstance(response, list):
                health = response
            elif isinstance(response, dict):
                health = [response]
            else:
                health = []

            self._connection._update_cache(cache_key, health, timeout=10)
            return health
        except Exception as e:
            logger.error("Error getting network health: %s", e)
            raise

    async def get_site_settings(self) -> Dict[str, Any]:
        """Retrieve all site-level configuration sections in a single response.

        UniFi exposes site-level settings as a flat collection of section
        objects (one per subsystem: ``super_identity``, ``country``, ``mgmt``,
        ``locale``, ``ntp``, ``connectivity``, ``guest_access``, ``snmp``,
        and ~35 others). The controller does **not** expose a single
        aggregated "site" section — fetching ``/get/setting/site`` returns
        ``api.err.Invalid``.

        This method fetches the unfiltered ``/get/setting`` endpoint and
        returns a dict keyed by each section's ``key`` discriminator so
        callers can index directly (e.g. ``result["super_identity"]["name"]``).
        ``raw`` retains the original list for callers that need ordering or
        sections without a ``key`` field.
        """
        try:
            settings_list = await self.get_settings("")
            keyed: Dict[str, Any] = {}
            for entry in settings_list:
                if isinstance(entry, dict):
                    section_key = entry.get("key")
                    if section_key:
                        keyed[section_key] = entry
            return {"raw": settings_list, "sections": keyed}
        except Exception as e:
            logger.error("Error getting site settings: %s", e)
            raise

    async def get_sites(self) -> List[Site]:  # Changed return type
        """Get a list of all sites in the controller."""
        cache_key = CACHE_PREFIX_SITES
        cached_data: Optional[List[Site]] = self._connection.get_cached(cache_key)
        if cached_data is not None:
            return cached_data

        try:
            api_request = ApiRequest(method="get", path="/api/self/sites")
            response = await self._connection.request(api_request)
            sites_data = response if isinstance(response, list) else []
            sites: List[Site] = [Site(raw_site) for raw_site in sites_data]
            self._connection._update_cache(cache_key, sites)
            return sites
        except Exception as e:
            logger.error("Error getting sites: %s", e)
            raise

    async def get_site_details(self, site_identifier: str) -> Optional[Site]:  # Changed return type
        """Get detailed information for a specific site by ID, name, or description.

        Args:
            site_identifier: ID (_id), name, or description (desc) of the site.

        Returns:
            Site object if found, None otherwise.
        """
        sites = await self.get_sites()
        site: Optional[Site] = next(
            (
                s
                for s in sites
                if s.site_id == site_identifier  # Use site_id property
                or s.name == site_identifier
                or s.description == site_identifier
            ),
            None,
        )

        if not site:
            logger.warning("Site '%s' not found.", site_identifier)
        return site

    async def get_current_site(self) -> Optional[Site]:  # Changed return type
        """Get information about the currently configured site for the connection."""
        return await self.get_site_details(self._connection.site)

    async def create_site(self, name: str, description: Optional[str] = None) -> Optional[Site]:  # Changed return type
        """Create a new site.

        Args:
            name: Name for the new site (will be formatted: lowercase, underscores).
            description: Optional description for the site.

        Returns:
            The created site data if successful, None otherwise.
        """
        try:
            formatted_name = name.lower().replace(" ", "_").replace("-", "_")
            site_desc = description or name

            sites = await self.get_sites()
            if any(s.name == formatted_name for s in sites):
                logger.error("Site with internal name '%s' already exists", formatted_name)
                return None
            if any(s.description == site_desc for s in sites):
                logger.warning(
                    "Site with description '%s' already exists, but proceeding with unique internal name.", site_desc
                )

            payload = {"cmd": "add-site", "name": formatted_name, "desc": site_desc}

            api_request = ApiRequest(method="post", path="/cmd/sitemgr", data=payload)
            response = await self._connection.request(api_request)

            self._connection._invalidate_cache(CACHE_PREFIX_SITES)

            if isinstance(response, dict) and response.get("meta", {}).get("rc") == "ok":
                logger.info("Site '%s' (internal: '%s') created successfully.", site_desc, formatted_name)
                await asyncio.sleep(1.5)
                new_site_details: Optional[Site] = await self.get_site_details(formatted_name)
                if not new_site_details:
                    logger.warning("Could not fetch details of newly created site immediately.")
                return new_site_details
            else:
                logger.error("Error creating site: %s", response)
                return None
        except Exception as e:
            logger.error("Error creating site '%s': %s", name, e)
            raise

    async def update_site(self, site_id: str, description: str) -> bool:
        """Update a site's description.
        Note: Changing the internal 'name' of a site is usually not supported or advised.

        Args:
            site_id: _id of the site to update.
            description: New description for the site.

        Returns:
            bool: True if successful, False otherwise.
        """
        try:
            site = await self.get_site_details(site_id)
            if not site:
                logger.warning("Site '%s' not found.", site_id)
                return False
            site_internal_id = site.site_id
            if not site_internal_id:
                logger.error("Site found for '%s' but has no _id property.", site_id)
                return False

            payload = {
                "cmd": "update-site",
                "site": site_internal_id,
                "desc": description,
            }

            api_request = ApiRequest(method="post", path="/cmd/sitemgr", data=payload)
            response = await self._connection.request(api_request)

            self._connection._invalidate_cache(CACHE_PREFIX_SITES)

            success = isinstance(response, dict) and response.get("meta", {}).get("rc") == "ok"
            if success:
                logger.info("Site %s description updated successfully.", site_id)
            else:
                logger.error("Error updating site %s: %s", site_id, response)

            return success
        except Exception as e:
            logger.error("Error updating site %s: %s", site_id, e)
            raise

    async def delete_site(self, site_id: str) -> bool:
        """Delete a site.

        Args:
            site_id: _id of the site to delete.

        Returns:
            bool: True if successful, False otherwise.
        """
        try:
            site = await self.get_site_details(site_id)
            if not site:
                return False
            site_internal_id = site.site_id
            if not site_internal_id:
                logger.error("Site found for '%s' but has no _id property.", site_id)
                return False

            # Don't allow deleting the default site
            if site.name == "default":
                logger.error("Cannot delete the default site.")
                return False

            payload = {
                "cmd": "delete-site",
                "site": site_internal_id,  # API requires _id
            }

            api_request = ApiRequest(method="post", path="/cmd/sitemgr", data=payload)
            response = await self._connection.request(api_request)

            self._connection._invalidate_cache(CACHE_PREFIX_SITES)

            success = isinstance(response, dict) and response.get("meta", {}).get("rc") == "ok"
            if success:
                logger.info("Site %s deleted successfully.", site_id)
                # If deleting the current site, switch back to default?
                if self._connection.site == site.name:
                    logger.warning(
                        "Deleted the current site '%s'. Consider switching to another site (e.g., default).",
                        self._connection.site,
                    )
                    # Optionally switch automatically: await self.switch_site("default")
            else:
                logger.error("Error deleting site %s: %s", site_id, response)

            return success
        except Exception as e:
            logger.error("Error deleting site %s: %s", site_id, e)
            raise

    async def switch_site(self, site_identifier: str) -> bool:
        """Switch the active site for the connection manager.

        Args:
            site_identifier: ID (_id), name, or description of the site to switch to.

        Returns:
            bool: True if site switch was successful, False otherwise.
        """
        try:
            site = await self.get_site_details(site_identifier)
            if not site:
                return False

            site_name = site.name
            if not site_name:
                logger.error("Site identified by '%s' has no internal name, cannot switch.", site_identifier)
                return False

            await self._connection.set_site(site_name)
            return True
        except Exception as e:
            logger.error("Error switching to site '%s': %s", site_identifier, e)
            raise

    async def get_admin_users(self) -> List[Dict[str, Any]]:
        """Get a list of admin users for the controller."""
        cache_key = CACHE_PREFIX_ADMINS
        cached_data = self._connection.get_cached(cache_key)
        if cached_data is not None:
            return cached_data

        try:
            api_request = ApiRequest(method="get", path="/api/stat/admin")
            response = await self._connection.request(api_request)
            admins = response if isinstance(response, list) else []
            self._connection._update_cache(cache_key, admins)
            return admins
        except Exception as e:
            logger.error("Error getting admin users: %s", e)
            raise

    async def get_admin_user_details(self, user_identifier: str) -> Optional[Dict[str, Any]]:
        """Get detailed information for a specific admin user by ID or name.

        Args:
            user_identifier: ID (_id) or name of the admin user.

        Returns:
            Admin user dictionary if found, None otherwise.
        """
        admin_users = await self.get_admin_users()
        user = next(
            (u for u in admin_users if u.get("_id") == user_identifier or u.get("name") == user_identifier),
            None,
        )
        if not user:
            logger.warning("Admin user '%s' not found.", user_identifier)
        return user

    async def create_admin_user(
        self,
        name: str,
        password: str,
        email: Optional[str] = None,
        is_super: bool = False,
        site_access: Optional[List[str]] = None,
    ) -> Optional[Dict[str, Any]]:
        """Create a new admin user.

        Args:
            name: Username for the new admin.
            password: Password for the new admin.
            email: Optional email for the admin.
            is_super: Whether the user is a super admin.
            site_access: List of site _ids the user has access to (if not super admin).

        Returns:
            The created admin user data if successful, None otherwise.
        """
        try:
            admin_users = await self.get_admin_users()
            if any(u.get("name") == name for u in admin_users):
                logger.error("Admin user with name '%s' already exists", name)
                return None

            payload = {
                "cmd": "create-admin",
                "name": name,
                "x_password": password,
                "email": email or "",
                "is_super": is_super,
            }

            if not is_super and site_access is not None:
                payload["site_access"] = site_access
            elif not is_super:
                logger.warning(
                    "Creating non-super admin '%s' without site_access. They may have no site access initially.", name
                )

            api_request = ApiRequest(method="post", path="/cmd/sitemgr", data=payload)
            response = await self._connection.request(api_request)

            self._connection._invalidate_cache(CACHE_PREFIX_ADMINS)

            if isinstance(response, dict) and response.get("meta", {}).get("rc") == "ok":
                logger.info("Admin user '%s' created successfully.", name)
                self._connection._invalidate_cache(CACHE_PREFIX_ADMINS)
                created_user_data = None
                if "data" in response and isinstance(response["data"], list) and len(response["data"]) > 0:
                    created_user_data = response["data"][0]
                if created_user_data:
                    return created_user_data  # Return the dict

                logger.warning("Admin user creation reported success, but could not extract details.")
                return {"success": True}  # Return simple success dict
            else:
                logger.error("Error creating admin user '%s': %s", name, response)
                return None
        except Exception as e:
            logger.error("Error creating admin user '%s': %s", name, e)
            raise

    async def update_admin_user(
        self,
        user_id: str,
        name: Optional[str] = None,
        password: Optional[str] = None,
        email: Optional[str] = None,
        is_super: Optional[bool] = None,
        site_access: Optional[List[str]] = None,
    ) -> bool:
        """Update an admin user.

        Args:
            user_id: _id of the admin user to update.
            name: New username.
            password: New password.
            email: New email.
            is_super: New super admin status.
            site_access: New list of site _ids the user has access to.

        Returns:
            bool: True if successful, False otherwise.
        """
        try:
            user = await self.get_admin_user_details(user_id)
            if not user:
                return False
            admin_internal_id = user.get("_id")
            if not admin_internal_id:
                logger.error("Admin user found for '%s' but has no _id.", user_id)
                return False

            payload = {"cmd": "update-admin", "admin_id": admin_internal_id}
            if name is not None:
                if name != user.get("name"):
                    admins = await self.get_admin_users()
                    if any(u.get("name") == name and u.get("_id") != admin_internal_id for u in admins):
                        logger.error("Cannot rename admin: Username '%s' already exists.", name)
                        return False
                payload["name"] = name
            if password is not None:
                payload["x_password"] = password
            if email is not None:
                payload["email"] = email
            if is_super is not None:
                payload["is_super"] = is_super
            if site_access is not None:
                current_is_super = user.get("is_super", False) if is_super is None else is_super
                if not current_is_super:
                    payload["site_access"] = site_access
                else:
                    logger.info("Ignoring site_access update for super admin.")

            if len(payload) <= 2:  # Only cmd and admin_id
                logger.warning("No fields provided to update for admin user %s", user_id)
                return False

            api_request = ApiRequest(method="post", path="/cmd/sitemgr", data=payload)
            response = await self._connection.request(api_request)

            self._connection._invalidate_cache(CACHE_PREFIX_ADMINS)

            success = isinstance(response, dict) and response.get("meta", {}).get("rc") == "ok"
            if success:
                logger.info("Admin user %s updated successfully.", user_id)
                self._connection._invalidate_cache(CACHE_PREFIX_ADMINS)
                return True
            else:
                logger.error("Error updating admin user %s: %s", user_id, response)
                return False
        except Exception as e:
            logger.error("Error updating admin user %s: %s", user_id, e)
            raise

    async def delete_admin_user(self, user_id: str) -> bool:
        """Delete an admin user.

        Args:
            user_id: _id of the admin user to delete.

        Returns:
            bool: True if successful, False otherwise.
        """
        try:
            user = await self.get_admin_user_details(user_id)
            if not user:
                return False
            admin_internal_id = user.get("_id")
            if not admin_internal_id:
                logger.error("Admin user found for '%s' but has no _id.", user_id)
                return False

            if user.get("name") == self._connection.username:
                logger.error("Cannot delete the currently configured admin user for this connection.")
                return False

            api_request = ApiRequest(method="delete", path=f"/api/stat/admin/{user_id}")
            response = await self._connection.request(api_request)

            success = isinstance(response, dict) and response.get("meta", {}).get("rc") == "ok"
            if success:
                logger.info("Admin user %s deleted successfully.", user_id)
                self._connection._invalidate_cache(CACHE_PREFIX_ADMINS)
                return True
            else:
                logger.error("Error deleting admin user %s: %s", user_id, response)
                return False
        except Exception as e:
            logger.error("Error deleting admin user %s: %s", user_id, e)
            raise

    async def invite_admin_user(
        self,
        email: str,
        is_super: bool = False,
        site_access: Optional[List[str]] = None,
    ) -> bool:
        """Send an invite to a new admin user.

        Args:
            email: Email address to send the invite to.
            is_super: Whether the invited user should be a super admin.
            site_access: List of site _ids the user will have access to.

        Returns:
            bool: True if successful, False otherwise.
        """
        try:
            payload = {
                "cmd": "invite-admin",
                "email": email,
                "for_super": is_super,
            }
            if site_access:
                logger.warning("Site access payload structure for invite is assumed, verify API requirements.")

            api_request = ApiRequest(method="post", path="/cmd/sitemgr", data=payload)
            response = await self._connection.request(api_request)

            success = isinstance(response, dict) and response.get("meta", {}).get("rc") == "ok"
            if success:
                logger.info("Admin invitation sent successfully to %s.", email)
                return True
            else:
                logger.error("Error sending admin invitation to %s: %s", email, response)
                return False
        except Exception as e:
            logger.error("Error inviting admin user %s: %s", email, e)
            raise

    async def get_current_admin_user(self) -> Optional[Dict[str, Any]]:  # Keep as Dict
        """Get information about the currently logged in admin user (based on connection username)."""
        return await self.get_admin_user_details(self._connection.username)
