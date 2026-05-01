"""Constants for the New Taipei City Garbage Truck integration."""
from __future__ import annotations

DOMAIN = "ntpc_rubbish"

NTPC_ROUTE_API = "https://data.ntpc.gov.tw/api/datasets/edc3ad26-8ae7-4916-a00b-bc6048d19bf8/json"
NTPC_OFFICIAL_ARRIVAL_API = "https://crd-rubbish.epd.ntpc.gov.tw/WebAPI/GetArrival"
NTPC_OFFICIAL_AROUND_POINTS_API = "https://crd-rubbish.epd.ntpc.gov.tw/WebAPI/GetAroundPoints"

CONF_ROUTES = "routes"          # all routes at the selected physical collection point
CONF_ENABLED_ROUTE_KEYS = "enabled_route_keys"
CONF_POINT_NAME = "point_name"
CONF_DISTRICT = "district"
CONF_SCHEDULED_TIME = "scheduled_time"  # comma-separated times for display
CONF_LATITUDE = "latitude"
CONF_LONGITUDE = "longitude"
CONF_UPDATE_INTERVAL = "update_interval"
SERVICE_UPDATE = "update"

DEFAULT_SCAN_INTERVAL = 30   # seconds
ROUTE_CACHE_TTL = 86400  # 24 hours

# Maps Python weekday() (0=Monday) to API field day suffix
DAY_FIELDS = {
    0: "monday",
    1: "tuesday",
    2: "wednesday",
    3: "thursday",
    4: "friday",
    5: "saturday",
    6: "sunday",
}
