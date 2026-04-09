"""The Navimow integration."""
import asyncio
import logging
from typing import Any
from urllib.parse import urlparse

from homeassistant.config_entries import ConfigEntry
from homeassistant.const import Platform
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import ConfigEntryAuthFailed, ConfigEntryNotReady
from homeassistant.helpers import config_entry_oauth2_flow
from homeassistant.helpers.aiohttp_client import async_get_clientsession

from .auth import NavimowOAuth2Implementation
from .const import (
    DOMAIN,
    CLIENT_ID,
    CLIENT_SECRET,
    API_BASE_URL,
    MQTT_BROKER,
    MQTT_PORT,
    MQTT_USERNAME,
    MQTT_PASSWORD,
)
from .services import async_setup_services

_LOGGER = logging.getLogger(__name__)
_LOGGER.debug("Navimow module imported (__init__.py)")

PLATFORMS: list[Platform] = [Platform.LAWN_MOWER, Platform.SENSOR]


async def async_setup(hass: HomeAssistant, config: dict[str, Any]) -> bool:
    """Set up the Navimow component."""
    hass.data.setdefault(DOMAIN, {})
    _LOGGER.debug("Navimow async_setup called, registering OAuth2 implementation")
    # Register OAuth2 implementation so config flow can find it.
    config_entry_oauth2_flow.async_register_implementation(
        hass,
        DOMAIN,
        NavimowOAuth2Implementation(
            hass,
            DOMAIN,
            CLIENT_ID,
            CLIENT_SECRET,
        ),
    )
    return True


async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Set up Navimow from a config entry."""
    # 延迟导入 mower_sdk，避免在加载 config_flow 时触发依赖导入
    from mower_sdk.api import MowerAPI
    from mower_sdk.errors import MowerAPIError
    from mower_sdk.sdk import NavimowSDK
    
    from .coordinator import NavimowCoordinator
    
    hass.data.setdefault(DOMAIN, {})

    def _mask_secret(value: str | None) -> str:
        if not value:
            return "<empty>"
        if len(value) <= 4:
            return "*" * len(value)
        return f"{value[:2]}***{value[-2:]}"

    try:
        # 获取 OAuth2 实现
        implementation = await config_entry_oauth2_flow.async_get_config_entry_implementation(
            hass, entry
        )
        if not isinstance(implementation, NavimowOAuth2Implementation):
            raise ConfigEntryAuthFailed("Invalid OAuth2 implementation")

        # 创建 OAuth2Session
        oauth_session = config_entry_oauth2_flow.OAuth2Session(
            hass, entry, implementation
        )

        token: dict[str, Any] | None = None
        if hasattr(oauth_session, "async_get_valid_token"):
            try:
                token = await oauth_session.async_get_valid_token()
            except AttributeError:
                token = None
        if not token and hasattr(oauth_session, "async_ensure_token_valid"):
            await oauth_session.async_ensure_token_valid()
            token = oauth_session.token
        if not token and hasattr(oauth_session, "async_get_access_token"):
            access_token_value = await oauth_session.async_get_access_token()
            token = {"access_token": access_token_value} if access_token_value else None
        if not token:
            # Final fallback for older HA versions storing token on the entry.
            token = entry.data.get("token")
        if not token:
            raise ConfigEntryAuthFailed("No valid token available")
        access_token = token.get("access_token")
        if not access_token:
            raise ConfigEntryAuthFailed("No access token in token data")

        # 创建 MowerAPI 实例
        api = MowerAPI(
            session=async_get_clientsession(hass),
            token=access_token,
            base_url=entry.data.get("api_base_url", API_BASE_URL),
        )

        # 发现设备
        try:
            devices = await api.async_get_devices()
            _LOGGER.info("Discovered %d Navimow device(s)", len(devices))
        except MowerAPIError as err:
            _LOGGER.error("Failed to discover devices: %s", err)
            raise ConfigEntryNotReady(f"Failed to discover devices: {err}") from err
        except ConfigEntryAuthFailed:
            raise
        except Exception as err:
            _LOGGER.error("Authentication failed during device discovery: %s", err)
            raise ConfigEntryAuthFailed(f"Authentication failed: {err}") from err

        if not devices:
            _LOGGER.warning("No Navimow devices found")

        # 获取 MQTT 连接信息并创建 SDK
        try:
            mqtt_info = await api.async_get_mqtt_user_info()
        except MowerAPIError as err:
            _LOGGER.error("Failed to get MQTT info: %s", err)
            raise ConfigEntryNotReady(f"Failed to get MQTT info: {err}") from err

        mqtt_host = mqtt_info.get("mqttHost") or entry.data.get(
            "mqtt_broker", MQTT_BROKER
        )
        mqtt_url = mqtt_info.get("mqttUrl")
        mqtt_username = mqtt_info.get("userName") or entry.data.get(
            "mqtt_username", MQTT_USERNAME
        )
        mqtt_password = mqtt_info.get("pwdInfo") or entry.data.get(
            "mqtt_password", MQTT_PASSWORD
        )
        mqtt_port = 443 if mqtt_url else entry.data.get("mqtt_port", MQTT_PORT)
        ws_path = mqtt_url
        if mqtt_url:
            parsed = urlparse(mqtt_url)
            if parsed.scheme in ("ws", "wss") and parsed.hostname:
                if not mqtt_host:
                    mqtt_host = parsed.hostname
                if parsed.port:
                    mqtt_port = parsed.port
                ws_path = parsed.path or "/"
                if parsed.query:
                    ws_path = f"{ws_path}?{parsed.query}"
        auth_headers = {"Authorization": f"Bearer {access_token}"} if ws_path else None

        _LOGGER.info(
            "MQTT connection parameters: broker=%s port=%s mqtt_url=%s ws_path=%s username=%s password=%s auth_header=%s",
            mqtt_host,
            mqtt_port,
            mqtt_url,
            ws_path,
            _mask_secret(mqtt_username),
            _mask_secret(mqtt_password),
            "Bearer <masked>" if auth_headers else "<none>",
        )

        def _attach_mqtt_debug_hooks(sdk: NavimowSDK, api: MowerAPI) -> None:
            mqtt = sdk._mqtt
            original_on_message = mqtt.on_message
            def _get_client_id() -> str:
                client_id_bytes = getattr(mqtt.client, "_client_id", b"")
                if isinstance(client_id_bytes, (bytes, bytearray)):
                    return client_id_bytes.decode("utf-8", errors="replace") or "<empty>"
                return str(client_id_bytes) if client_id_bytes else "<empty>"

            async def _on_connected() -> None:
                _LOGGER.info(
                    "MQTT connected callback: broker=%s port=%s ws_path=%s tls=%s client_id=%s",
                    mqtt.broker,
                    mqtt.port,
                    mqtt.ws_path,
                    mqtt._use_tls,
                    _get_client_id(),
                )

            async def _on_ready() -> None:
                _LOGGER.info(
                    "MQTT ready callback: subscribed to downlink topics on broker=%s port=%s client_id=%s",
                    mqtt.broker,
                    mqtt.port,
                    _get_client_id(),
                )

            async def _on_disconnected() -> None:
                _LOGGER.debug(
                    "MQTT disconnected callback: broker=%s port=%s ws_path=%s tls=%s client_id=%s",
                    mqtt.broker,
                    mqtt.port,
                    mqtt.ws_path,
                    mqtt._use_tls,
                    _get_client_id(),
                )
                # 断连后重新从服务端拉取 MQTT 凭据（userName/pwdInfo 与 OAuth token 绑定，
                # token 刷新或过期后凭据会失效，直接用旧凭据重连会导致 CODE_OAUTH_INFO_ILLEGAL）
                await _async_refresh_mqtt_credentials(sdk, api)

            async def _on_message(topic: str, payload: bytes, device_id: str) -> None:
                payload_text = (payload or b"").decode("utf-8", errors="replace")
                _LOGGER.debug(
                    "MQTT message received: topic=%s bytes=%d device=%s payload=%s",
                    topic,
                    len(payload or b""),
                    device_id,
                    payload_text,
                )
                if original_on_message is not None:
                    await original_on_message(topic, payload, device_id)

            mqtt.on_connected = _on_connected
            mqtt.on_ready = _on_ready
            mqtt.on_disconnected = _on_disconnected
            mqtt.on_message = _on_message

            def _on_subscribe(_client, _userdata, mid, granted_qos, *args, **kwargs):
                _LOGGER.info(
                    "MQTT subscribed: mid=%s granted_qos=%s broker=%s port=%s client_id=%s",
                    mid,
                    granted_qos,
                    mqtt.broker,
                    mqtt.port,
                    _get_client_id(),
                )

            def _on_log(_client, _userdata, level, buf):
                _LOGGER.debug("MQTT client log: level=%s msg=%s", level, buf)

            mqtt.client.on_subscribe = _on_subscribe
            mqtt.client.on_log = _on_log

        async def _probe_mqtt_status(sdk: NavimowSDK) -> None:
            await asyncio.sleep(5)
            _LOGGER.info("MQTT status probe (5s): connected=%s", sdk.is_connected)
            await asyncio.sleep(25)
            _LOGGER.info("MQTT status probe (30s): connected=%s", sdk.is_connected)

        async def _async_refresh_mqtt_credentials(sdk: NavimowSDK, api: MowerAPI) -> None:
            """Token 过期或 MQTT 断连后，重新获取 MQTT 凭据并更新 SDK。

            服务端下发的 userName/pwdInfo 与 OAuth token 绑定，token 刷新后需同步更新，
            否则 MQTT 重连时会收到 CODE_OAUTH_INFO_ILLEGAL。

            必须先刷新 OAuth token：MQTT 断连往往正是因为 token 过期触发的，
            此时 api._token 极可能也已失效，需先换新 token 再拉取 MQTT 凭据。
            """
            new_access_token: str | None = None
            new_auth_headers: dict[str, str] | None = None
            try:
                # 先刷新 OAuth token（oauth_session 来自外层闭包）
                if hasattr(oauth_session, "async_ensure_token_valid"):
                    await oauth_session.async_ensure_token_valid()
                    fresh_token = oauth_session.token
                elif hasattr(oauth_session, "async_get_valid_token"):
                    fresh_token = await oauth_session.async_get_valid_token()
                else:
                    fresh_token = oauth_session.token

                if fresh_token and fresh_token.get("access_token"):
                    new_access_token = fresh_token["access_token"]
                    api.set_token(new_access_token)
                    new_auth_headers = {"Authorization": f"Bearer {new_access_token}"}
            except Exception as err:
                _LOGGER.warning("Failed to refresh OAuth token before MQTT credential refresh: %s", err)

            try:
                new_mqtt_info = await api.async_get_mqtt_user_info()
            except Exception as err:
                _LOGGER.warning("Failed to refresh MQTT credentials: %s", err)
                return
            new_username = new_mqtt_info.get("userName")
            new_password = new_mqtt_info.get("pwdInfo")
            if new_auth_headers or new_username or new_password:
                # update_credentials 在断连时会调用 loop_stop()/tls_set()/load_default_certs()
                # 等阻塞 SSL 操作，必须在 executor 中执行，避免阻塞 HA 事件循环。
                # auth_headers 更新与 username/password 更新合并为一次 executor 调用。
                _new_auth_headers = new_auth_headers
                _new_username = new_username
                _new_password = new_password
                def _do_credential_update() -> None:
                    sdk.update_mqtt_credentials(
                        auth_headers=_new_auth_headers,
                        username=_new_username,
                        password=_new_password,
                    )
                await hass.async_add_executor_job(_do_credential_update)
                _LOGGER.info(
                    "MQTT credentials refreshed from server: username=%s",
                    _mask_secret(new_username),
                )

        def _create_sdk(api: MowerAPI) -> NavimowSDK:
            sdk = NavimowSDK(
                broker=mqtt_host,
                port=mqtt_port,
                username=mqtt_username,
                password=mqtt_password,
                ws_path=ws_path,
                auth_headers=auth_headers,
                loop=hass.loop,
                records=devices,
                # broker 每小时断连时，优先用 MQTT 协议层 keepalive（PINGREQ/PINGRESP）保活。
                keepalive_seconds=2400,  # 40 分钟
                reconnect_min_delay=1,
                reconnect_max_delay=60,
            )
            _LOGGER.info(
                "Invoking SDK MQTT connect: broker=%s port=%s ws_path=%s",
                mqtt_host,
                mqtt_port,
                ws_path,
            )
            sdk.connect()
            return sdk

        sdk = await hass.async_add_executor_job(_create_sdk, api)
        _attach_mqtt_debug_hooks(sdk, api)
        async_setup_services(hass, api)
        hass.async_create_task(_probe_mqtt_status(sdk))

        coordinators: dict[str, NavimowCoordinator] = {}
        for device in devices:
            coordinator = NavimowCoordinator(
                hass=hass,
                sdk=sdk,
                api=api,
                device=device,
                oauth_session=oauth_session,
            )
            await coordinator.async_setup()
            await coordinator.async_config_entry_first_refresh()
            coordinators[device.id] = coordinator

        # 存储数据
        hass.data[DOMAIN][entry.entry_id] = {
            "sdk": sdk,
            "api": api,
            "devices": devices,
            "coordinators": coordinators,
            "oauth_session": oauth_session,
        }

        # 转发到平台
        await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)

        # 设置重新加载监听器
        entry.async_on_unload(entry.add_update_listener(async_reload_entry))

        return True

    except ConfigEntryAuthFailed:
        raise
    except Exception as err:
        _LOGGER.exception("Error setting up Navimow integration: %s", err)
        raise ConfigEntryNotReady(f"Error setting up integration: {err}") from err


async def async_unload_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Unload a config entry."""
    unload_ok = await hass.config_entries.async_unload_platforms(entry, PLATFORMS)

    if unload_ok:
        # 清理数据
        if entry.entry_id in hass.data.get(DOMAIN, {}):
            data = hass.data[DOMAIN][entry.entry_id]
            sdk = data.get("sdk")
            if sdk:
                try:
                    sdk.disconnect()
                except Exception as err:
                    _LOGGER.warning("Error disconnecting MQTT: %s", err)

            hass.data[DOMAIN].pop(entry.entry_id)

    return unload_ok


async def async_reload_entry(hass: HomeAssistant, entry: ConfigEntry) -> None:
    """Reload config entry."""
    await hass.config_entries.async_reload(entry.entry_id)
