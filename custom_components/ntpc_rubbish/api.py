"""API client for New Taipei City garbage truck data."""
from __future__ import annotations

import ssl
from typing import Any

import aiohttp

from .const import (
    NTPC_OFFICIAL_AROUND_POINTS_API,
    NTPC_OFFICIAL_ARRIVAL_API,
    NTPC_ROUTE_API,
)

# Both NTPC hosts (data.ntpc.gov.tw and crd-rubbish.epd.ntpc.gov.tw) serve
# certificates missing the Subject Key Identifier extension, which Python 3.13+
# rejects by default. Verification is relaxed only for these trusted government
# hosts.
_NTPC_SSL_CONTEXT = ssl.create_default_context()
_NTPC_SSL_CONTEXT.check_hostname = False
_NTPC_SSL_CONTEXT.verify_mode = ssl.CERT_NONE

_OFFICIAL_SITE_HEADERS = {
    "Referer": "https://crd-rubbish.epd.ntpc.gov.tw/dispPageBox/Ntpcepd/NtpMP.aspx?ddsPageID=MAP",
    "User-Agent": (
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/146.0.0.0 Safari/537.36 Edg/146.0.0.0"
    ),
}


class NtpcRubbishApiError(Exception):
    """Raised when an NTPC API call fails (network or unparseable response)."""


class NtpcRubbishApiClient:
    """Client for the NTPC Open Data API."""

    def __init__(self, session: aiohttp.ClientSession) -> None:
        self._session = session

    async def _fetch_all_pages(
        self, url: str, size: int = 1000
    ) -> list[dict[str, Any]]:
        """Fetch all pages of data from a paginated API endpoint."""
        results: list[dict[str, Any]] = []
        page = 0
        while True:
            try:
                async with self._session.get(
                    url,
                    params={"page": page, "size": size},
                    timeout=aiohttp.ClientTimeout(total=30),
                    ssl=_NTPC_SSL_CONTEXT,
                ) as resp:
                    resp.raise_for_status()
                    data: list[dict[str, Any]] = await resp.json()
                    if not data:
                        break
                    results.extend(data)
                    if len(data) < size:
                        break
                    page += 1
            except aiohttp.ClientError as err:
                raise NtpcRubbishApiError(
                    f"network error fetching {url} page {page}: {err}"
                ) from err
        return results

    async def get_all_routes(self) -> list[dict[str, Any]]:
        """Fetch all garbage truck route data."""
        return await self._fetch_all_pages(NTPC_ROUTE_API)

    async def get_route_point(
        self, lineid: str, rank: str
    ) -> dict[str, Any] | None:
        """Find a specific collection point by lineid and rank."""
        page = 0
        while True:
            try:
                async with self._session.get(
                    NTPC_ROUTE_API,
                    params={"page": page, "size": 1000},
                    timeout=aiohttp.ClientTimeout(total=30),
                    ssl=_NTPC_SSL_CONTEXT,
                ) as resp:
                    resp.raise_for_status()
                    data: list[dict[str, Any]] = await resp.json()
                    if not data:
                        return None
                    for item in data:
                        if item.get("lineid") == lineid and item.get("rank") == rank:
                            return item
                    if len(data) < 1000:
                        return None
                    page += 1
            except aiohttp.ClientError as err:
                raise NtpcRubbishApiError(
                    f"network error fetching route point lineid={lineid} rank={rank}: {err}"
                ) from err

    async def get_official_line_arrivals(self, line_ids: list[str]) -> dict[str, Any]:
        """Fetch official arrival data for one or more line IDs."""
        payload = {"LineID": ",".join(line_ids)}
        try:
            async with self._session.post(
                NTPC_OFFICIAL_ARRIVAL_API,
                data=payload,
                headers=_OFFICIAL_SITE_HEADERS,
                timeout=aiohttp.ClientTimeout(total=30),
                ssl=_NTPC_SSL_CONTEXT,
            ) as resp:
                resp.raise_for_status()
                return await resp.json()
        except aiohttp.ClientError as err:
            raise NtpcRubbishApiError(
                f"network error fetching official line arrivals: {err}"
            ) from err

    async def get_official_around_points(
        self,
        *,
        latitude: float,
        longitude: float,
        week: int,
        time_interval: int,
        radius: int = 500,
    ) -> dict[str, Any]:
        """Fetch the official live map payload around a collection point."""
        payload = {
            "lat": str(latitude),
            "lng": str(longitude),
            "radius": str(radius),
            "week": str(week),
            "time": str(time_interval),
        }
        try:
            async with self._session.post(
                NTPC_OFFICIAL_AROUND_POINTS_API,
                data=payload,
                headers=_OFFICIAL_SITE_HEADERS,
                timeout=aiohttp.ClientTimeout(total=30),
                ssl=_NTPC_SSL_CONTEXT,
            ) as resp:
                resp.raise_for_status()
                return await resp.json()
        except aiohttp.ClientError as err:
            raise NtpcRubbishApiError(
                f"network error fetching official around points: {err}"
            ) from err
