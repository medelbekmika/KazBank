
import os
import psycopg
from dotenv import load_dotenv

load_dotenv()
DATABASE_URL = os.environ["DATABASE_URL"]

DDL = """
CREATE TABLE IF NOT EXISTS customers (
    customer_id SERIAL PRIMARY KEY,
    full_name TEXT NOT NULL,
    city TEXT DEFAULT 'Almaty',
    email TEXT UNIQUE
);

CREATE TABLE IF NOT EXISTS accounts (
    account_id SERIAL PRIMARY KEY,
    customer_id INTEGER NOT NULL REFERENCES customers(customer_id),
    account_number TEXT NOT NULL UNIQUE,
    balance NUMERIC(15,2) NOT NULL DEFAULT 0 CHECK (balance >= 0)
);

CREATE TABLE IF NOT EXISTS transactions (
    transaction_id SERIAL PRIMARY KEY,
    account_id INTEGER NOT NULL REFERENCES accounts(account_id),
    amount NUMERIC(15,2) NOT NULL CHECK (amount > 0),
    tx_type TEXT NOT NULL CHECK (tx_type IN ('DEBIT', 'CREDIT')),
    related_account_id INTEGER REFERENCES accounts(account_id),
    created_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP
);
"""

CUSTOMERS = [
    ("Arman Bekov", "Almaty", "arman@example.com"),
    ("Zarina Seiit", "Astana", "zarina@example.com"),
    ("Daniyar Nurlan", "Shymkent", "daniyar@example.com"),
    ("Aigerim Sadyk", "Almaty", "aigerim@example.com"),
    ("Nurlan Omarov", "Karaganda", "nurlan@example.com"),
    ("Madina Kairat", "Astana", "madina@example.com"),
    ("Dias Tulegen", "Aktobe", "dias@example.com"),
    ("Aliya Serik", "Almaty", "aliya@example.com"),
    ("Timur Asan", "Taraz", "timur@example.com"),
    ("Dana Mukhtar", "Kostanay", "dana@example.com"),
]


def main():
    with psycopg.connect(DATABASE_URL) as conn:
        conn.execute(DDL)

        # Insert customers only if the table is empty.
        customer_count = conn.execute(
            "SELECT COUNT(*) FROM customers"
        ).fetchone()[0]

        if customer_count == 0:
            with conn.cursor() as cur:
                cur.executemany(
                    """
                    INSERT INTO customers (full_name, city, email)
                    VALUES (%s, %s, %s)
                    """,
                    CUSTOMERS,
                )

        # Get customer IDs for account creation.
        customer_ids = conn.execute(
            "SELECT customer_id FROM customers ORDER BY customer_id LIMIT 10"
        ).fetchall()

        account_count = conn.execute(
            "SELECT COUNT(*) FROM accounts"
        ).fetchone()[0]

        if account_count == 0:
            if not customer_ids:
                raise ValueError("No customers found. Cannot create accounts.")

            account_rows = []

            for i in range(15):
                customer_id = customer_ids[i % len(customer_ids)][0]
                account_rows.append(
                    (customer_id, f"KZ{1000000000 + i}", 100000 + i * 5000)
                )

            with conn.cursor() as cur:
                cur.executemany(
                    """
                    INSERT INTO accounts (customer_id, account_number, balance)
                    VALUES (%s, %s, %s)
                    """,
                    account_rows,
                )

    print("KazBank schema is ready; seed data inserted if tables were empty.")


if __name__ == "__main__":
    main()
