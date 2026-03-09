"""
Report API for MyTapo.

Provides HTTP endpoints for on-demand energy reports.
Called by n8n workflows, iPhone Shortcuts, or other automation tools.
"""

import os
import json
import logging
from datetime import datetime
from aiohttp import web
from dotenv import load_dotenv

from influx_queries import InfluxQueries
from utils import send_pushover_notification_new, get_awtrix_client
from awtrix_client import AwtrixMessage

load_dotenv()

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)


class ReportAPI:
    """HTTP API for on-demand energy reports."""

    def __init__(self):
        self.queries = InfluxQueries()
        self.pushover_user = os.getenv("PUSHOVER_USER_GROUP_WOERIS")
        self.awtrix_client = get_awtrix_client()
        self.api_token = os.getenv("REPORT_API_TOKEN", "")

    def _check_auth(self, request: web.Request) -> bool:
        """Check API token if configured."""
        if not self.api_token:
            return True
        token = request.headers.get("Authorization", "").replace("Bearer ", "")
        if not token:
            token = request.query.get("token", "")
        return token == self.api_token

    def _format_summary_text(self, data: dict, report_type: str) -> str:
        """Format human-readable summary for Pushover."""
        if report_type == "today":
            total = data.get("total_kwh", 0)
            cost = data.get("cost", 0)
            lines = [f"Today's Energy Report ({datetime.now().strftime('%H:%M')})", ""]
            lines.append(f"Total: {total:.1f} kWh | EUR {cost:.2f}")
            lines.append("")
            lines.append("Top Consumers:")
            for i, dev in enumerate(data.get("top_devices", [])[:5], 1):
                lines.append(f"{i}. {dev['device']}: {dev['kwh']:.1f} kWh ({dev['percentage']:.0f}%)")
            return "\n".join(lines)

        elif report_type == "events":
            events = data.get("events", {})
            if not events:
                return "No events detected in this period."
            parts = []
            for event_type, info in events.items():
                count = info["count"]
                duration = info.get("total_duration_seconds", 0)
                if duration > 3600:
                    parts.append(f"{count}x {event_type} ({duration/3600:.1f}h)")
                elif duration > 60:
                    parts.append(f"{count}x {event_type} ({duration/60:.0f}m)")
                else:
                    parts.append(f"{count}x {event_type}")
            return f"Events ({data.get('period', 'day')}): " + ", ".join(parts)

        elif report_type == "top-devices":
            devices = data.get("devices", [])
            lines = [f"Top Consumers ({data.get('period', 'today')}):"]
            for i, dev in enumerate(devices[:5], 1):
                lines.append(f"{i}. {dev['device']}: {dev['kwh']:.1f} kWh - EUR {dev['cost']:.2f}")
            return "\n".join(lines)

        elif report_type == "solar":
            lines = ["Solar Report:"]
            lines.append(f"Today: {data.get('today_kwh', 0):.2f} kWh (EUR {data.get('today_savings', 0):.2f})")
            lines.append(f"Week: {data.get('week_kwh', 0):.1f} kWh (EUR {data.get('week_savings', 0):.2f})")
            return "\n".join(lines)

        elif report_type == "comparison":
            current = data.get("current", {})
            trend = data.get("trend", "N/A")
            lines = [
                f"Comparison ({data.get('period', 'week')}): {trend}",
                f"Current: {current.get('total_kwh', 0):.1f} kWh | EUR {current.get('cost', 0):.2f}",
                f"Previous: {data.get('previous', {}).get('total_kwh', 0):.1f} kWh"
            ]
            return "\n".join(lines)

        return json.dumps(data, indent=2)

    def _format_awtrix_text(self, data: dict, report_type: str) -> str:
        """Format compact text for Awtrix display."""
        if report_type == "today":
            total = data.get("total_kwh", 0)
            cost = data.get("cost", 0)
            top_devices = data.get("top_devices", [])[:3]
            top_str = " | ".join(f"{d.get('device', '?')} {d.get('percentage', 0):.0f}%" for d in top_devices)
            top_part = f" | {top_str}" if top_str else ""
            return f"Today: {total:.1f}kWh EUR{cost:.2f}{top_part}"

        elif report_type == "events":
            events = data.get("events", {})
            parts = [f"{info['count']}x {et}" for et, info in events.items()]
            return " | ".join(parts[:3]) if parts else "No events"

        elif report_type == "solar":
            return f"Solar: {data.get('today_kwh', 0):.1f}kWh EUR{data.get('today_savings', 0):.2f}"

        elif report_type == "comparison":
            return f"{data.get('period', 'week')}: {data.get('trend', 'N/A')} ({data.get('current', {}).get('total_kwh', 0):.1f}kWh)"

        return ""

    async def health(self, request: web.Request) -> web.Response:
        return web.json_response({"status": "ok", "service": "report-api"})

    async def list_reports(self, request: web.Request) -> web.Response:
        reports = [
            {"endpoint": "/reports/today", "description": "Today's consumption (all devices)"},
            {"endpoint": "/reports/events?period=day|week", "description": "Event summary"},
            {"endpoint": "/reports/top-devices?period=day", "description": "Top power consumers"},
            {"endpoint": "/reports/solar", "description": "Solar generation summary"},
            {"endpoint": "/reports/comparison?period=week", "description": "Period vs previous period"},
            {"endpoint": "/reports/custom", "description": "POST - Raw data context for AI analysis"},
        ]
        return web.json_response({"reports": reports})

    async def report_today(self, request: web.Request) -> web.Response:
        if not self._check_auth(request):
            return web.json_response({"error": "unauthorized"}, status=401)

        consumption = self.queries.query_today_consumption()
        top_devices = self.queries.query_top_devices(days=1)
        total = sum(consumption.values())
        cost = total * self.queries.cost_per_kwh

        data = {
            "total_kwh": round(total, 2),
            "cost": round(cost, 2),
            "devices": consumption,
            "top_devices": top_devices[:5],
            "timestamp": datetime.utcnow().isoformat()
        }

        return web.json_response({
            "data": data,
            "summary_text": self._format_summary_text(data, "today"),
            "awtrix_text": self._format_awtrix_text(data, "today")
        })

    async def report_events(self, request: web.Request) -> web.Response:
        if not self._check_auth(request):
            return web.json_response({"error": "unauthorized"}, status=401)

        period = request.query.get("period", "day")
        days = {"day": 1, "week": 7, "month": 30}.get(period, 1)
        events = self.queries.query_events(days)

        data = {"period": period, "days": days, "events": events}

        return web.json_response({
            "data": data,
            "summary_text": self._format_summary_text(data, "events"),
            "awtrix_text": self._format_awtrix_text(data, "events")
        })

    async def report_top_devices(self, request: web.Request) -> web.Response:
        if not self._check_auth(request):
            return web.json_response({"error": "unauthorized"}, status=401)

        period = request.query.get("period", "day")
        days = {"day": 1, "week": 7, "month": 30}.get(period, 1)
        devices = self.queries.query_top_devices(days=days)

        data = {"period": period, "devices": devices}

        return web.json_response({
            "data": data,
            "summary_text": self._format_summary_text(data, "top-devices"),
            "awtrix_text": self._format_awtrix_text(data, "top-devices")
        })

    async def report_solar(self, request: web.Request) -> web.Response:
        if not self._check_auth(request):
            return web.json_response({"error": "unauthorized"}, status=401)

        data = self.queries.query_solar_summary()

        return web.json_response({
            "data": data,
            "summary_text": self._format_summary_text(data, "solar"),
            "awtrix_text": self._format_awtrix_text(data, "solar")
        })

    async def report_comparison(self, request: web.Request) -> web.Response:
        if not self._check_auth(request):
            return web.json_response({"error": "unauthorized"}, status=401)

        period = request.query.get("period", "week")
        data = self.queries.query_comparison(period)

        return web.json_response({
            "data": data,
            "summary_text": self._format_summary_text(data, "comparison"),
            "awtrix_text": self._format_awtrix_text(data, "comparison")
        })

    async def report_custom(self, request: web.Request) -> web.Response:
        """POST endpoint: returns full data context for Claude API analysis."""
        if not self._check_auth(request):
            return web.json_response({"error": "unauthorized"}, status=401)

        try:
            body = await request.json()
            question = body.get("question", "")
        except Exception:
            question = ""

        data = self.queries.query_custom_context(question)

        return web.json_response({
            "data": data,
            "summary_text": "Custom data context for AI analysis",
            "awtrix_text": ""
        })


def create_app() -> web.Application:
    """Create and configure the aiohttp application."""
    api = ReportAPI()
    app = web.Application()

    app.router.add_get("/health", api.health)
    app.router.add_get("/reports", api.list_reports)
    app.router.add_get("/reports/today", api.report_today)
    app.router.add_get("/reports/events", api.report_events)
    app.router.add_get("/reports/top-devices", api.report_top_devices)
    app.router.add_get("/reports/solar", api.report_solar)
    app.router.add_get("/reports/comparison", api.report_comparison)
    app.router.add_post("/reports/custom", api.report_custom)

    return app


if __name__ == "__main__":
    port = int(os.getenv("REPORT_API_PORT", "8099"))
    logger.info(f"Starting Report API on port {port}")
    app = create_app()
    web.run_app(app, host="0.0.0.0", port=port)
