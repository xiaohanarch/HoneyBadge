"""Create 11 missing NebulaGraph tags from schema (without DEFAULT values)."""

from nebula3.Config import Config as NebulaConfig
from nebula3.gclient.net import ConnectionPool


def get_connection(host: str, port: int) -> ConnectionPool:
    config = NebulaConfig()
    config.max_connection_pool_size = 10
    config.timeout = 120000
    pool = ConnectionPool()
    ok = pool.init([(host, port)], config)
    if not ok:
        raise RuntimeError(f"Failed to connect to NebulaGraph at {host}:{port}")
    return pool


# 11 missing tags - simplified without DEFAULT values
CREATE_TAG_STATEMENTS = [
    """CREATE TAG IF NOT EXISTS ARInvoice(
        invoice_number STRING NOT NULL,
        invoice_type STRING,
        invoice_date TIMESTAMP NOT NULL,
        due_date TIMESTAMP,
        status STRING,
        total_amount DOUBLE NOT NULL,
        tax_amount DOUBLE,
        currency STRING,
        exchange_rate DOUBLE,
        payment_terms STRING,
        gl_date TIMESTAMP,
        org_id INT64,
        dept_id INT64,
        data_scope STRING,
        created_at TIMESTAMP,
        updated_at TIMESTAMP,
        etl_batch_id STRING,
        source_system STRING,
        is_active BOOL
    )""",
    """CREATE TAG IF NOT EXISTS AccountingDistribution(
        distribution_id STRING NOT NULL,
        line_number INT64,
        debit_amount DOUBLE,
        credit_amount DOUBLE,
        currency STRING,
        accounting_class STRING,
        posted_flag BOOL,
        org_id INT64,
        dept_id INT64,
        data_scope STRING,
        created_at TIMESTAMP,
        updated_at TIMESTAMP,
        etl_batch_id STRING,
        source_system STRING,
        is_active BOOL
    )""",
    """CREATE TAG IF NOT EXISTS GLBalance(
        period_name STRING NOT NULL,
        currency_code STRING,
        period_net_dr DOUBLE,
        period_net_cr DOUBLE,
        begin_balance_dr DOUBLE,
        begin_balance_cr DOUBLE,
        translated_flag STRING,
        org_id INT64,
        dept_id INT64,
        data_scope STRING,
        created_at TIMESTAMP,
        updated_at TIMESTAMP,
        etl_batch_id STRING,
        source_system STRING,
        is_active BOOL
    )""",
    """CREATE TAG IF NOT EXISTS GLJournalLine(
        line_number INT64 NOT NULL,
        debit_amount DOUBLE,
        credit_amount DOUBLE,
        description STRING,
        reference STRING,
        org_id INT64,
        dept_id INT64,
        data_scope STRING,
        created_at TIMESTAMP,
        updated_at TIMESTAMP,
        etl_batch_id STRING,
        source_system STRING,
        is_active BOOL
    )""",
    """CREATE TAG IF NOT EXISTS Invoice(
        invoice_number STRING NOT NULL,
        invoice_type STRING,
        invoice_date TIMESTAMP NOT NULL,
        due_date TIMESTAMP,
        status STRING,
        total_amount DOUBLE NOT NULL,
        tax_amount DOUBLE,
        currency STRING,
        exchange_rate DOUBLE,
        payment_method STRING,
        description STRING,
        gl_date TIMESTAMP,
        pay_group STRING,
        source STRING,
        org_id INT64,
        dept_id INT64,
        data_scope STRING,
        created_at TIMESTAMP,
        updated_at TIMESTAMP,
        etl_batch_id STRING,
        source_system STRING,
        is_active BOOL
    )""",
    """CREATE TAG IF NOT EXISTS POShipment(
        shipment_number INT64 NOT NULL,
        shipment_type STRING,
        quantity DOUBLE NOT NULL,
        quantity_received DOUBLE,
        quantity_billed DOUBLE,
        quantity_cancelled DOUBLE,
        need_by_date TIMESTAMP,
        promised_date TIMESTAMP,
        ship_to_location STRING,
        receiving_routing STRING,
        match_option STRING,
        price_override DOUBLE,
        amount DOUBLE,
        status STRING,
        accrue_on_receipt_flag STRING,
        inspection_required_flag STRING,
        org_id INT64,
        dept_id INT64,
        data_scope STRING,
        created_at TIMESTAMP,
        updated_at TIMESTAMP,
        etl_batch_id STRING,
        source_system STRING,
        is_active BOOL
    )""",
    """CREATE TAG IF NOT EXISTS PaymentSchedule(
        schedule_id STRING NOT NULL,
        installment_number INT64,
        due_date TIMESTAMP NOT NULL,
        gross_amount DOUBLE NOT NULL,
        amount_remaining DOUBLE,
        payment_status STRING,
        discount_date TIMESTAMP,
        discount_amount_available DOUBLE,
        second_discount_date TIMESTAMP,
        second_discount_amount DOUBLE,
        third_discount_date TIMESTAMP,
        third_discount_amount DOUBLE,
        org_id INT64,
        dept_id INT64,
        data_scope STRING,
        created_at TIMESTAMP,
        updated_at TIMESTAMP,
        etl_batch_id STRING,
        source_system STRING,
        is_active BOOL
    )""",
    """CREATE TAG IF NOT EXISTS PurchaseOrderLine(
        line_number INT64 NOT NULL,
        line_type STRING,
        quantity DOUBLE NOT NULL,
        unit_price DOUBLE NOT NULL,
        amount DOUBLE NOT NULL,
        uom STRING,
        need_by_date TIMESTAMP,
        promised_date TIMESTAMP,
        received_quantity DOUBLE,
        invoiced_quantity DOUBLE,
        status STRING,
        tax_code STRING,
        tax_rate DOUBLE,
        org_id INT64,
        dept_id INT64,
        data_scope STRING,
        created_at TIMESTAMP,
        updated_at TIMESTAMP,
        etl_batch_id STRING,
        source_system STRING,
        is_active BOOL
    )""",
    """CREATE TAG IF NOT EXISTS ReceiptLine(
        line_number INT64 NOT NULL,
        received_quantity DOUBLE NOT NULL,
        accepted_quantity DOUBLE,
        rejected_quantity DOUBLE,
        uom STRING,
        inspection_status STRING,
        lot_number STRING,
        sublocation STRING,
        org_id INT64,
        dept_id INT64,
        data_scope STRING,
        created_at TIMESTAMP,
        updated_at TIMESTAMP,
        etl_batch_id STRING,
        source_system STRING,
        is_active BOOL
    )""",
    """CREATE TAG IF NOT EXISTS SalesOrderLine(
        line_number INT64 NOT NULL,
        quantity DOUBLE NOT NULL,
        unit_price DOUBLE NOT NULL,
        amount DOUBLE NOT NULL,
        uom STRING,
        shipped_quantity DOUBLE,
        invoiced_quantity DOUBLE,
        status STRING,
        tax_code STRING,
        tax_rate DOUBLE,
        scheduled_ship_date TIMESTAMP,
        org_id INT64,
        dept_id INT64,
        data_scope STRING,
        created_at TIMESTAMP,
        updated_at TIMESTAMP,
        etl_batch_id STRING,
        source_system STRING,
        is_active BOOL
    )""",
    """CREATE TAG IF NOT EXISTS XLAJournalLine(
        ae_line_num INT64 NOT NULL,
        accounting_class STRING,
        entered_dr DOUBLE,
        entered_cr DOUBLE,
        accounted_dr DOUBLE,
        accounted_cr DOUBLE,
        currency_code STRING,
        currency_conversion_rate DOUBLE,
        description STRING,
        org_id INT64,
        dept_id INT64,
        data_scope STRING,
        created_at TIMESTAMP,
        updated_at TIMESTAMP,
        etl_batch_id STRING,
        source_system STRING,
        is_active BOOL
    )""",
]


def main():
    pool = get_connection("localhost", 9669)
    session = pool.get_session("root", "nebula")
    session.execute("USE honeybadge")

    for stmt in CREATE_TAG_STATEMENTS:
        tag_name = stmt.split("IF NOT EXISTS")[1].split("(")[0].strip()
        result = session.execute(stmt)
        if result.is_succeeded():
            print(f"Created {tag_name}: OK")
        else:
            print(f"ERROR creating {tag_name}: {result.error_msg()}")

    # Verify
    r = session.execute("SHOW TAGS")
    print(f"\nTotal tags in DB: {r.row_size()}")

    session.release()
    pool.close()
    print("\nDone!")


if __name__ == "__main__":
    main()
