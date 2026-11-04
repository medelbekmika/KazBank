from decimal import Decimal, InvalidOperation
import time

import psycopg
from psycopg import IsolationLevel, errors
from psycopg.rows import dict_row
from flask import current_app, jsonify, request


def get_pool():
    return current_app.extensions["db_pool"]


def json_error(message, status):
    return jsonify({"error": message}), status


def parse_positive_amount(value):
    try:
        amount = Decimal(str(value))
    except (InvalidOperation, TypeError, ValueError):
        raise ValueError("amount must be a valid number")

    if not amount.is_finite() or amount <= 0:
        raise ValueError("amount must be greater than zero")

    if amount.as_tuple().exponent < -2:
        raise ValueError("amount may have at most 2 decimal places")

    return amount


def run_serializable_with_retry(operation, max_retries=3):
    """Retry the complete transaction after PostgreSQL SQLSTATE 40001."""
    for attempt in range(max_retries):
        try:
            with get_pool().connection() as conn:
                conn.isolation_level = IsolationLevel.SERIALIZABLE

                try:
                    result = operation(conn)
                    conn.commit()
                    return result
                except Exception:
                    conn.rollback()
                    raise

        except errors.SerializationFailure:
            if attempt == max_retries - 1:
                raise
            time.sleep(0.05 * (attempt + 1))

    raise RuntimeError("Maximum serialization retries exceeded")


def register_routes(app):

    @app.get("/customers")
    def list_customers():
        city = request.args.get("city")

        with get_pool().connection() as conn:
            with conn.cursor(row_factory=dict_row) as cur:
                if city:
                    rows = cur.execute(
                        """SELECT customer_id, full_name, city, email
                           FROM customers
                           WHERE city = %s
                           ORDER BY customer_id""",
                        (city,),
                    ).fetchall()
                else:
                    rows = cur.execute(
                        """SELECT customer_id, full_name, city, email
                           FROM customers
                           ORDER BY customer_id"""
                    ).fetchall()

        return jsonify(rows), 200

    @app.post("/customers")
    def create_customer():
        data = request.get_json(silent=True)

        if not isinstance(data, dict) or not data.get("full_name"):
            return json_error("full_name is required", 400)

        with get_pool().connection() as conn:
            try:
                with conn.cursor(row_factory=dict_row) as cur:
                    row = cur.execute(
                        """INSERT INTO customers
                           (full_name, city, email)
                           VALUES (%s, %s, %s)
                           RETURNING customer_id, full_name, city, email""",
                        (
                            data["full_name"],
                            data.get("city", "Almaty"),
                            data.get("email"),
                        ),
                    ).fetchone()

                conn.commit()

            except Exception:
                conn.rollback()
                raise

        return jsonify(row), 201

    @app.get("/accounts")
    def list_accounts():
        customer_id = request.args.get("customer_id", type=int)

        if customer_id is None:
            return json_error(
                "customer_id query parameter is required and must be an integer",
                400,
            )

        with get_pool().connection() as conn:
            with conn.cursor(row_factory=dict_row) as cur:
                rows = cur.execute(
                    """SELECT account_id, customer_id, account_number, balance
                       FROM accounts
                       WHERE customer_id = %s
                       ORDER BY account_id""",
                    (customer_id,),
                ).fetchall()

        return jsonify(rows), 200

    @app.post("/transfer")
    def transfer():
        data = request.get_json(silent=True)

        if not isinstance(data, dict):
            return json_error("JSON body is required", 400)

        try:
            from_account = int(data["from_account_id"])
            to_account = int(data["to_account_id"])
            amount = parse_positive_amount(data["amount"])

        except (KeyError, TypeError, ValueError) as exc:
            return json_error(str(exc) or "Invalid transfer input", 400)

        if from_account == to_account:
            return json_error(
                "Source and destination accounts must be different",
                400,
            )

        def transaction(conn):
            # Lock both rows in a consistent order to reduce deadlock risk.
            account_ids = sorted([from_account, to_account])

            with conn.cursor(row_factory=dict_row) as cur:
                locked = cur.execute(
                    """SELECT account_id, balance
                       FROM accounts
                       WHERE account_id = ANY(%s)
                       ORDER BY account_id
                       FOR UPDATE""",
                    (account_ids,),
                ).fetchall()

            if len(locked) != 2:
                raise LookupError("One or both accounts do not exist")

            balances = {
                row["account_id"]: row["balance"]
                for row in locked
            }

            if balances[from_account] < amount:
                raise ArithmeticError("Insufficient funds")

            conn.execute(
                """UPDATE accounts
                   SET balance = balance - %s
                   WHERE account_id = %s""",
                (amount, from_account),
            )

            conn.execute(
                """UPDATE accounts
                   SET balance = balance + %s
                   WHERE account_id = %s""",
                (amount, to_account),
            )

            # Both transaction records belong to the same atomic transfer.
            conn.execute("SAVEPOINT transfer_log")

            try:
                conn.execute(
                    """INSERT INTO transactions
                       (account_id, amount, tx_type, related_account_id)
                       VALUES (%s, %s, 'DEBIT', %s)""",
                    (from_account, amount, to_account),
                )

                conn.execute(
                    """INSERT INTO transactions
                       (account_id, amount, tx_type, related_account_id)
                       VALUES (%s, %s, 'CREDIT', %s)""",
                    (to_account, amount, from_account),
                )

                conn.execute("RELEASE SAVEPOINT transfer_log")

            except Exception:
                conn.execute("ROLLBACK TO SAVEPOINT transfer_log")
                conn.execute("RELEASE SAVEPOINT transfer_log")
                raise

            return {
                "status": "success",
                "from_account_id": from_account,
                "to_account_id": to_account,
                "amount": str(amount),
            }

        try:
            result = run_serializable_with_retry(transaction)
            return jsonify(result), 200

        except LookupError as exc:
            return json_error(str(exc), 404)

        except ArithmeticError as exc:
            return json_error(str(exc), 400)

        except errors.SerializationFailure:
            return json_error(
                "Transaction could not be completed due to concurrent updates; retry the request.",
                409,
            )

    @app.get("/transactions")
    def list_transactions():
        account_id = request.args.get("account_id", type=int)

        if account_id is None:
            return json_error(
                "account_id query parameter is required and must be an integer",
                400,
            )

        with get_pool().connection() as conn:
            with conn.cursor(row_factory=dict_row) as cur:
                rows = cur.execute(
                    """SELECT transaction_id, account_id, amount, tx_type,
                              related_account_id, created_at
                       FROM transactions
                       WHERE account_id = %s
                       ORDER BY transaction_id DESC""",
                    (account_id,),
                ).fetchall()

        return jsonify(rows), 200

    @app.get("/health")
    def health():
        pool = get_pool()

        try:
            pool.check()
            return jsonify({
                "status": "ok",
                "pool": pool.get_stats(),
            }), 200

        except Exception:
            current_app.logger.exception("Health check failed")
            return jsonify({
                "status": "error",
                "pool": pool.get_stats(),
            }), 503