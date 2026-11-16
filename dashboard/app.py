
import os
from datetime import datetime, timezone

from flask import (
    Flask,
    jsonify,
    make_response,
    render_template,
    request
)

from dashboard.services.market_service import MarketService
from dashboard.services.history_service import HistoryService
from dashboard.services.analytics_service import AnalyticsService
from dashboard.services.risk_service import RiskService
from dashboard.services.data_service import DataService
from dashboard.services.etl_bootstrap import ETLBootstrapManager


app = Flask(__name__)

PRODUCTION = (
    os.environ.get(
        "CRYPTOSCOPE_PRODUCTION", "false"
    ).lower() == "true"
)

app.config["JSON_SORT_KEYS"] = False

market_service = MarketService()
history_service = HistoryService()
analytics_service = AnalyticsService(history_service)
risk_service = RiskService(history_service)
data_service = DataService()

# The dashboard stays responsive while a missing database is rebuilt.
etl_bootstrap = ETLBootstrapManager()
AUTO_ETL = os.environ.get("CRYPTOSCOPE_AUTO_ETL", "true").lower() == "true"


@app.before_request
def require_historical_data():
    # Live tickers and HTML pages can work while historical candles download.
    if request.endpoint not in {
        "api_history", "api_correlation", "api_risk",
        "api_data", "api_data_export"
    }:
        return None

    result = etl_bootstrap.ensure_started() if AUTO_ETL else {
        "status": "disabled", "missing_symbols": []
    }
    if result["status"] == "ready" or not AUTO_ETL:
        return None

    description = (
        "Historical data is being initialized; retry shortly"
        if result["status"] in ("running", "waiting")
        else "Historical ETL initialization failed; check server logs"
    )
    response = jsonify({
        "error": description,
        "etl_status": result["status"],
        "missing_symbols": result.get("missing_symbols", []),
    })
    response.status_code = 503
    response.headers["Retry-After"] = "10"
    response.headers["Cache-Control"] = "no-store"
    return response


# ---------------------------------
# Dashboard pages
# ---------------------------------

@app.get("/")
def overview():
    return render_template(
        "overview.html",
        active_page="overview"
    )


@app.get("/explorer")
def explorer():
    return render_template(
        "explorer.html",
        active_page="explorer",
        title="Coin Explorer"
    )


@app.get("/compare")
def compare():
    return render_template(
        "compare.html",
        active_page="compare",
        title="Compare Assets"
    )


@app.get("/analytics")
def analytics():
    return render_template(
        "analytics.html",
        active_page="analytics",
        title="Advanced Analytics"
    )


@app.get("/data")
def data_explorer():
    return render_template(
        "data.html",
        active_page="data",
        title="Data Explorer"
    )


# ---------------------------------
# Market API
# ---------------------------------

@app.get("/api/markets")
def api_markets():
    try:
        return jsonify(
            market_service.get_markets()
        )

    except RuntimeError:
        app.logger.exception("Market API failed")

        return jsonify({
            "error": "Market data unavailable",
            "markets": []
        }), 503


# ---------------------------------
# Historical data API
# ---------------------------------

@app.get("/api/history")
def api_history():
    symbol = request.args.get(
        "symbol", "BTCUSDT"
    ).upper()

    interval = request.args.get(
        "interval", "1h"
    )

    try:
        limit = int(
            request.args.get("limit", 168)
        )

        result = history_service.get_candles(
            symbol=symbol,
            interval=interval,
            limit=limit
        )

        return jsonify(result)

    except (ValueError, TypeError) as error:
        return jsonify({
            "error": str(error)
        }), 400

    except RuntimeError:
        app.logger.exception(
            "Historical data unavailable"
        )

        return jsonify({
            "error": "Historical data unavailable"
        }), 503


# ---------------------------------
# Correlation API
# ---------------------------------

@app.get("/api/analytics/correlation")
def api_correlation():
    try:
        days = int(
            request.args.get("days", 30)
        )

        return jsonify(
            analytics_service.get_correlation(
                days=days
            )
        )

    except (ValueError, TypeError) as error:
        return jsonify({
            "error": str(error)
        }), 400

    except Exception:
        app.logger.exception(
            "Correlation analysis failed"
        )

        return jsonify({
            "error": "Correlation analysis unavailable"
        }), 503


# ---------------------------------
# Risk analysis API
# ---------------------------------

@app.get("/api/analytics/risk")
def api_risk():
    symbol = request.args.get(
        "symbol", "BTCUSDT"
    ).upper()

    try:
        days = int(
            request.args.get("days", 365)
        )

        result = risk_service.get_analysis(
            symbol=symbol,
            days=days
        )

        return jsonify(result)

    except (ValueError, TypeError) as error:
        return jsonify({
            "error": str(error)
        }), 400

    except Exception:
        app.logger.exception(
            "Risk analysis failed"
        )

        return jsonify({
            "error": "Risk analysis unavailable"
        }), 503


# ---------------------------------
# Data Explorer API
# ---------------------------------

@app.get("/api/data")
def api_data():
    symbol = request.args.get(
        "symbol", ""
    ).upper() or None

    try:
        page = int(
            request.args.get("page", 1)
        )

        page_size = int(
            request.args.get("page_size", 25)
        )

        result = data_service.get_records(
            symbol=symbol,
            start=request.args.get("start") or None,
            end=request.args.get("end") or None,
            page=page,
            page_size=page_size
        )

        return jsonify(result)

    except (ValueError, TypeError) as error:
        return jsonify({
            "error": str(error)
        }), 400

    except Exception:
        app.logger.exception(
            "Data Explorer failed"
        )

        return jsonify({
            "error": "Data Explorer unavailable"
        }), 503


# ---------------------------------
# CSV export API
# ---------------------------------

@app.get("/api/data/export")
def api_data_export():
    symbol = request.args.get(
        "symbol", ""
    ).upper() or None

    try:
        content = data_service.export_csv(
            symbol=symbol,
            start=request.args.get("start") or None,
            end=request.args.get("end") or None
        )

        date = datetime.now(
            timezone.utc
        ).strftime("%Y%m%d")

        response = make_response(content)

        response.headers["Content-Type"] = (
            "text/csv; charset=utf-8"
        )

        response.headers["Content-Disposition"] = (
            f'attachment; filename="cryptoscope_{date}.csv"'
        )

        response.headers["Cache-Control"] = "no-store"

        return response

    except (ValueError, TypeError) as error:
        return jsonify({
            "error": str(error)
        }), 400

    except Exception:
        app.logger.exception(
            "CSV export failed"
        )

        return jsonify({
            "error": "CSV export unavailable"
        }), 503


# ---------------------------------
# Health check
# ---------------------------------

@app.get("/health")
def health():
    return jsonify({
        "status": "ok",
        "service": "cryptoscope-dashboard"
    })


@app.get("/api/etl/status")
def api_etl_status():
    result = etl_bootstrap.ensure_started() if AUTO_ETL else {
        "status": "disabled", "missing_symbols": []
    }
    return jsonify(result)


# Flask's WSGI module is imported (not executed as __main__) in production.
# Starting here makes initial ETL automatic both locally and on WSGI imports.
if AUTO_ETL:
    etl_bootstrap.ensure_started()


if __name__ == "__main__":
    app.run(
        host="127.0.0.1",
        port=5000,
        debug=not PRODUCTION,
        use_reloader=False  # Avoid starting a duplicate background ETL worker.
    )
