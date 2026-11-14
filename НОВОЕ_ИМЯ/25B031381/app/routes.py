from decimal import Decimal, InvalidOperation
import time

from psycopg import errors
from psycopg.rows import dict_row
from flask import current_app, jsonify, request

class InsufficientFunds(Exception):
    pass


class AccountNotFound(Exception):
    pass

def get_pool():
    return current_app.extensions["db_pool"]


def json_error(message, status):
    return jsonify({"error": message}), status


def parse_account_id(data, field):
    """Strict positive integer: rejects missing, bool, float, '1.5', 'abc'."""
    if field not in data:
        raise ValueError(f"{field} is required")

    value = data[field]

    if isinstance(value, bool):
        raise ValueError(f"{field} must be an integer")
    if isinstance(value, int):
        result = value
    elif isinstance(value, str) and value.strip().isdigit():
        result = int(value.strip())
    else:
        raise ValueError(f"{field} must be an integer")

    if result <= 0:
        raise ValueError(f"{field} must be a positive integer")
    return result


def parse_positive_amount(data, field="amount"):
    if field not in data:
        raise ValueError(f"{field} is required")

    value = data[field]
    if isinstance(value, bool) or not isinstance(value, (int, float, str)):
        raise ValueError(f"{field} must be a valid number")

    try:
        amount = Decimal(str(value).strip())
    except (InvalidOperation, ValueError):
        raise ValueError(f"{field} must be a valid number")

    if not amount.is_finite() or amount <= 0:
        raise ValueError(f"{field} must be greater than zero")

    if amount.as_tuple().exponent < -2:
        raise ValueError(f"{field} may have at most 2 decimal places")

    if amount >= Decimal("1e13"):  # NUMERIC(15,2) holds at most 13 integer digits
        raise ValueError(f"{field} is too large")

    return amount


def optional_text(data, field):
    """Return stripped str, or None if absent/null/blank. Non-str -> ValueError."""
    value = data.get(field)
    if value is None:
        return None
    if not isinstance(value, str):
        raise ValueError(f"{field} must be a string")
    value = value.strip()
    return value or None


def run_serializable_with_retry(operation, max_retries=3):
    """Run `operation(conn)` in one SERIALIZABLE transaction.

    The whole transaction is retried on SQLSTATE 40001 (SerializationFailure).
    The isolation level is set with SET TRANSACTION, so it applies to this
    transaction only and never leaks into the pooled connection.
    """
    for attempt in range(max_retries):
        try:
            with get_pool().connection() as conn:
                try:
                    # Must be the first statement of the transaction.
                    conn.execute("SET TRANSACTION ISOLATION LEVEL SERIALIZABLE")
                    result = operation(conn)
                    conn.commit()  # 40001 can also be raised here
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

        if not isinstance(data, dict):
            return json_error("JSON object body is required", 400)

        full_name = data.get("full_name")
        if not isinstance(full_name, str) or not full_name.strip():
            return json_error("full_name is required and must be a non-empty string", 400)

        try:
            city = optional_text(data, "city") or "Almaty"
            email = optional_text(data, "email")
        except ValueError as exc:
            return json_error(str(exc), 400)

        with get_pool().connection() as conn:
            try:
                with conn.cursor(row_factory=dict_row) as cur:
                    row = cur.execute(
                        """INSERT INTO customers
                           (full_name, city, email)
                           VALUES (%s, %s, %s)
                           RETURNING customer_id, full_name, city, email""",
                        (full_name.strip(), city, email),
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
            return json_error("JSON object body is required", 400)

        try:
            from_account = parse_account_id(data, "from_account_id")
            to_account = parse_account_id(data, "to_account_id")
            amount = parse_positive_amount(data)
        except ValueError as exc:
            return json_error(str(exc), 400)

        if from_account == to_account:
            return json_error("Source and destination accounts must be different", 400)

        def transaction(conn):
            # Lock both rows in ascending account_id order (deadlock prevention).
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
                raise AccountNotFound("One or both accounts do not exist")

            balances = {row["account_id"]: row["balance"] for row in locked}

            if balances[from_account] < amount:
                raise InsufficientFunds("Insufficient funds")

            # SAVEPOINT around the debit step: if the CHECK (balance >= 0)
            # constraint fires, only this step is rolled back to the savepoint
            # and reported as "insufficient funds".
            conn.execute("SAVEPOINT debit_step")
            try:
                conn.execute(
                    """UPDATE accounts
                       SET balance = balance - %s
                       WHERE account_id = %s""",
                    (amount, from_account),
                )
            except errors.CheckViolation:
                conn.execute("ROLLBACK TO SAVEPOINT debit_step")
                raise InsufficientFunds("Insufficient funds")
            conn.execute("RELEASE SAVEPOINT debit_step")

            conn.execute(
                """UPDATE accounts
                   SET balance = balance + %s
                   WHERE account_id = %s""",
                (amount, to_account),
            )

            # Both log rows belong to the same atomic transfer: any failure
            # here rolls back the whole transaction (balances included).
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

            return {
                "status": "success",
                "from_account_id": from_account,
                "to_account_id": to_account,
                "amount": str(amount),
            }

        try:
            result = run_serializable_with_retry(transaction)
            return jsonify(result), 200

        except AccountNotFound as exc:
            return json_error(str(exc), 404)

        except InsufficientFunds as exc:
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
