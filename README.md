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

Do not commit `.env` to GitLab.

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

- A single shared `ConnectionPool` is created when the Flask application starts.
- Pool configuration: `min_size=2`, `max_size=8`.
- Write operations explicitly commit successful transactions and roll back after exceptions.
- Money transfers use PostgreSQL `SERIALIZABLE` isolation.
- Serialization failures (`SQLSTATE 40001`) trigger retries, up to three attempts.
- Both account rows are locked in ascending account ID order.
- A transfer updates both balances and creates debit and credit transaction records in one database transaction.
- A savepoint protects the transaction-log insertion step. If logging fails, the outer transaction rolls back the balance changes.

## 8. Rubric checklist

| Requirement | Implementation / verification |
|---|---|
| R1 — Schema and seed script | Implemented and executed successfully |
| R2 — Required API endpoints | Implemented and tested |
| R3 — Shared connection pool | Implemented; `/health` confirms min=2 and max=8 |
| R4 — Atomic transfer | Successful transfer and insufficient-funds case tested |
| R5 — SERIALIZABLE and retry | Implemented; concurrency retry not independently stress-tested |
| R6 — Database error handling | Handlers implemented; duplicate email tested; all database error classes not independently tested |
| R7 — Parameterized SQL | Implemented; SQL injection input tested |
| R8 — Health endpoint | Tested; returned HTTP 200 and pool statistics |

## 9. GitLab submission

Before submission:

- Include the project source files.
- Include `README.md`, `requirements.txt`, and `.env.example`.
- Do not include `.env` or `.venv/`.
- Submit the project in the required directory: `python_project/<your_id>/`.

## 10. Schema compatibility note

The assignment refers to the KazBank schema from Week 4. The exact Week 4 schema should be compared with the tables and columns in `schema_seed.py` before final submission. If the instructor provided a specific DDL, use that schema and adjust the application queries if necessary.