"""Constants for Navimow integration."""
from __future__ import annotations
from typing import Final

DOMAIN: Final = "navimow"

# OAuth2 Configuration
# 授权页面 URL（用户登录页面）
# 添加 channel=homeassistant 以便 HA 跳转回登录页时携带渠道信息
OAUTH2_AUTHORIZE: Final = (
    "https://navimow-h5-fra.willand.com/smartHome/login?channel=homeassistant"
)

# Token 交换端点
OAUTH2_TOKEN: Final = "https://navimow-fra.ninebot.com/openapi/oauth/getAccessToken"

# Token 刷新端点
OAUTH2_REFRESH: Final | None = None

# OAuth2 Client 配置
CLIENT_ID: Final = "homeassistant"
CLIENT_SECRET: Final = "57056e15-722e-42be-bbaa-b0cbfb208a52"

# API 配置
API_BASE_URL: Final = "https://navimow-fra.ninebot.com"

# MQTT 配置
# TODO: 需要提供实际的 MQTT broker 地址和端口
MQTT_BROKER: Final = "mqtt.navimow.com"
MQTT_PORT: Final = 1883
MQTT_USERNAME: Final | None = None
MQTT_PASSWORD: Final | None = None

# 更新间隔（秒）
UPDATE_INTERVAL: Final = 30

# MQTT 超时时间（秒），超过该时间未收到状态消息则走 HTTP 兜底。
# Reduced to detect silent MQTT outages (no state pushes from server) sooner.
MQTT_STALE_SECONDS: Final = 90

# MQTT Keepalive (seconds). PINGREQ interval for faster half-open TCP detection.
MQTT_KEEPALIVE_SECONDS: Final = 120

# HTTP 兜底最小拉取间隔（秒）。
# 当 MQTT 实时状态缺失时，按分钟级回退到 HTTP，避免状态长时间卡住。
HTTP_FALLBACK_MIN_INTERVAL: Final = 60

# MowerStatus 到 LawnMowerActivity 的映射
MOWER_STATUS_TO_ACTIVITY = {
    "idle": "docked",
    "mowing": "mowing",
    "paused": "paused",
    "docked": "docked",
    "charging": "docked",
    "returning": "returning",
    "error": "error",
    "unknown": "error",
}
