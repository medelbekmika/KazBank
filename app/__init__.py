from flask import Flask, jsonify
from dotenv import load_dotenv
from psycopg_pool import ConnectionPool
from psycopg import errors
import os
import psycopg

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

    from app.routes import register_routes
    register_routes(app)

    @app.errorhandler(errors.UniqueViolation)
    def handle_unique_violation(exc):
        return jsonify({"error": "Conflict", "detail": "A value that must be unique already exists."}), 409

    @app.errorhandler(errors.NotNullViolation)
    def handle_not_null_violation(exc):
        return jsonify({"error": "Bad Request", "detail": "A required database field is missing."}), 400

    @app.errorhandler(psycopg.OperationalError)
    def handle_operational_error(exc):
        app.logger.exception("Database operational error")
        return jsonify({"error": "Service Unavailable", "detail": "Database unavailable."}), 503

    @app.errorhandler(404)
    def handle_not_found(exc):
        return jsonify({"error": "Not Found", "detail": "The requested resource does not exist."}), 404

    @app.errorhandler(400)
    def handle_bad_request(exc):
        return jsonify({"error": "Bad Request", "detail": "Invalid request."}), 400

    return app
