# KazBank — Python + PostgreSQL REST API

**Course:** CSCI2204 Database Management Systems  
**Project:** Python + PostgreSQL Integration Practice  
**Application:** KazBank Mini-Project

## 1. Project description

KazBank is a REST API built with Python, Flask, and PostgreSQL. It supports customer management, account lookup, money transfers, and transaction history.

The application uses Psycopg 3 and a shared PostgreSQL connection pool.

## 2. Requirements

- Python 3.10 or newer
- PostgreSQL 15 or newer
- A PostgreSQL database named `kazbank`

## 3. Installation and setup

### Step 1. Create the database

Create the database if it does not already exist:

```bash
createdb kazbank
```

Alternatively, use PostgreSQL:

```bash
psql -d postgres
```

Then execute:

```sql
CREATE DATABASE kazbank;
```

If the database already exists, do not create it again.

### Step 2. Create and activate a virtual environment

macOS/Linux:

```bash
python3 -m venv .venv
source .venv/bin/activate
```

Windows:

```bash
python -m venv .venv
.venv\Scripts\activate
```

### Step 3. Install dependencies

```bash
pip install -r requirements.txt
```

### Step 4. Configure environment variables

Copy the example configuration:

```bash
cp .env.example .env
```

Edit `.env` and configure your PostgreSQL connection:

```env
DATABASE_URL=postgresql://USERNAME:PASSWORD@localhost:5432/kazbank
FLASK_HOST=127.0.0.1
FLASK_PORT=5000
```

Replace `USERNAME` and `PASSWORD` with your PostgreSQL credentials.

Do not commit `.env` to the repository.

### Step 5. Create tables and insert seed data

```bash
python schema_seed.py
```

The script creates the database tables and inserts initial sample data.

### Step 6. Start the Flask application

```bash
python run.py
```

The API will be available at:

`http://127.0.0.1:5000`

Keep this terminal running while testing the API.

## 4. API endpoints

| Method | Endpoint | Description |
|---|---|---|
| GET | `/customers` | List all customers |
| POST | `/customers` | Create a customer |
| GET | `/accounts?customer_id=1` | List accounts belonging to a customer |
| POST | `/transfer` | Transfer money between accounts |
| GET | `/transactions?account_id=1` | View account transaction history |
| GET | `/health` | Check application and connection pool health |

An optional city filter is also supported:

`GET /customers?city=Almaty`

## 5. Sample API requests

### List customers

```bash
curl http://127.0.0.1:5000/customers
```

### Create a customer

```bash
curl -X POST http://127.0.0.1:5000/customers \
-H "Content-Type: application/json" \
-d '{"full_name":"Test User","city":"Almaty","email":"test@example.com"}'
```

Expected status: `201 Created`.

### List customer accounts

```bash
curl "http://127.0.0.1:5000/accounts?customer_id=1"
```

### Transfer money

Example: transfer 1,000 from account 1 to account 11.

```bash
curl -X POST http://127.0.0.1:5000/transfer \
-H "Content-Type: application/json" \
-d '{"from_account_id":1,"to_account_id":11,"amount":"1000.00"}'
```

Expected response:

```json
{
  "status": "success",
  "from_account_id": 1,
  "to_account_id": 11,
  "amount": "1000.00"
}
```

### View transaction history

```bash
curl "http://127.0.0.1:5000/transactions?account_id=1"
```

### Check application health

```bash
curl http://127.0.0.1:5000/health
```

Expected status: `200 OK`. The response includes connection pool statistics.

## 6. Error handling and security tests

### Duplicate email

An existing email should return HTTP `409 Conflict`.

```bash
curl -i -X POST http://127.0.0.1:5000/customers \
-H "Content-Type: application/json" \
-d '{"full_name":"Duplicate Test","city":"Almaty","email":"arman@example.com"}'
```

### Missing required field

A missing `full_name` should return HTTP `400 Bad Request`.

```bash
curl -i -X POST http://127.0.0.1:5000/customers \
-H "Content-Type: application/json" \
-d '{"city":"Almaty"}'
```

### Insufficient funds

A transfer exceeding the source account balance should return HTTP `400 Bad Request`.

```bash
curl -i -X POST http://127.0.0.1:5000/transfer \
-H "Content-Type: application/json" \
-d '{"from_account_id":1,"to_account_id":11,"amount":"999999999.00"}'
```

The account balances must remain unchanged.

### SQL injection test

```bash
curl -G "http://127.0.0.1:5000/customers" \
--data-urlencode "city=' OR '1'='1"
```

The input is treated as a regular parameter value, not executable SQL.

All user-supplied SQL values are passed through Psycopg parameterized queries using `%s` placeholders. SQL queries are not constructed by concatenating user input.

## 7. Database transactions and connection pooling

- A single shared `ConnectionPool` is created when the Flask application starts (`min_size=2`, `max_size=8`, `timeout=5s`) and closed on shutdown.
- Write operations commit explicitly on success and roll back on any exception.
- `POST /transfer` runs in one `SERIALIZABLE` transaction (`SET TRANSACTION ISOLATION LEVEL SERIALIZABLE` as the first statement). The level applies to that transaction only, so it does not leak into other requests that reuse the pooled connection.
- Serialization failures (`SQLSTATE 40001`, also at `COMMIT`) restart the whole transaction, up to three attempts with a short back-off; after that the API returns `409`.
- Both account rows are locked with `SELECT ... FOR UPDATE ORDER BY account_id` (ascending order) to prevent deadlocks.
- The debit step is wrapped in a `SAVEPOINT`: if the `CHECK (balance >= 0)` constraint fires, only that step is rolled back to the savepoint and reported as `400 Insufficient funds`.
- A transfer updates both balances and writes the DEBIT and CREDIT rows in `transactions` in the same transaction: either everything is saved or nothing.

## 8. HTTP status codes

| Situation | Status |
|---|---|
| Success (GET / transfer) | 200 |
| Customer created | 201 |
| Invalid or missing input, insufficient funds, constraint violation | 400 |
| Account not found / unknown route | 404 |
| Duplicate email (`UniqueViolation`) or unresolved serialization conflict | 409 |
| Database unavailable (`OperationalError`, pool timeout) | 503 |

All responses, including 404/405/500, are JSON.

## 9. Rubric mapping

| Requirement | Where |
|---|---|
| R1 — Schema and seed from Python | `schema_seed.py` |
| R2 — Five endpoints | `app/routes.py` |
| R3 — Shared connection pool | `app/__init__.py` |
| R4 — Atomic transfer | `transfer()` in `app/routes.py` |
| R5 — SERIALIZABLE + retry | `run_serializable_with_retry()` |
| R6 — Specific psycopg3 errors | error handlers in `app/__init__.py` |
| R7 — Parameterised SQL | every query uses `%s` placeholders |
| R8 — `/health` with pool stats | `health()` in `app/routes.py` |
