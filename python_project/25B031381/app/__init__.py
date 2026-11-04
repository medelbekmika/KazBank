import atexit
import os

import psycopg
from dotenv import load_dotenv
from flask import Flask, jsonify
from psycopg import errors
from psycopg_pool import ConnectionPool, PoolTimeout
from werkzeug.exceptions import HTTPException


def create_app():
    load_dotenv()
    app = Flask(__name__)

    database_url = os.environ.get("DATABASE_URL")
    if not database_url:
        raise RuntimeError("DATABASE_URL is not set. Copy .env.example to .env and configure it.")

    # Create exactly one shared pool when the application starts.
    pool = ConnectionPool(
        conninfo=database_url,
        min_size=2,
        max_size=8,
        timeout=5.0,
        open=True,
    )
    app.extensions["db_pool"] = pool
    atexit.register(pool.close)  # close connections cleanly on shutdown

    from app.routes import register_routes
    register_routes(app)

    # ---- Database errors -------------------------------------------------
    @app.errorhandler(errors.UniqueViolation)
    def handle_unique_violation(exc):
        return jsonify({"error": "Conflict", "detail": "A value that must be unique already exists."}), 409

    @app.errorhandler(errors.NotNullViolation)
    def handle_not_null_violation(exc):
        column = getattr(exc.diag, "column_name", None)
        detail = f"Missing required field: {column}" if column else "A required database field is missing."
        return jsonify({"error": "Bad Request", "detail": detail}), 400

    @app.errorhandler(errors.ForeignKeyViolation)
    @app.errorhandler(errors.CheckViolation)
    def handle_constraint_violation(exc):
        return jsonify({"error": "Bad Request", "detail": "Request violates a database constraint."}), 400

    @app.errorhandler(psycopg.OperationalError)
    @app.errorhandler(PoolTimeout)
    def handle_operational_error(exc):
        app.logger.exception("Database unavailable")
        return jsonify({"error": "Service Unavailable", "detail": "Database unavailable."}), 503

    # ---- Everything else is JSON too (404, 405, 500, ...) ------------------
    @app.errorhandler(HTTPException)
    def handle_http_exception(exc):
        return jsonify({"error": exc.name, "detail": exc.description}), exc.code

    @app.errorhandler(Exception)
    def handle_unexpected(exc):
        app.logger.exception("Unhandled error")
        return jsonify({"error": "Internal Server Error", "detail": "Unexpected server error."}), 500

    return app
