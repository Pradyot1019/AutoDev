"""Four dependency-free reference services, laid out the way the Developer agent emits them.

source/<slug>/app/*.py + app/config.json, tests/<slug>/test_*.py  (24 tests in total).
"""

SERVICES = {}

# ---------------------------------------------------------------- expense tracker
SERVICES["expense-tracker"] = {
    "files": {
        "app/__init__.py": "",
        "app/config.json": '{\n  "currency": "INR",\n  "monthly_limit": 50000,\n  "categories": ["food", "rent", "travel"]\n}\n',
        "app/ledger.py": '''"""Expense ledger."""
import json
from datetime import date
from pathlib import Path

CONFIG = Path(__file__).with_name("config.json")


def load_config():
    with open(CONFIG, encoding="utf-8") as handle:
        return json.load(handle)


def add_expense(items, name, amount, category="general"):
    if amount <= 0:
        raise ValueError("amount must be positive")
    if not name:
        raise ValueError("name required")
    entry = {"name": name, "amount": round(amount, 2), "category": category}
    items.append(entry)
    return entry


def total(items):
    result = 0
    for item in items:
        result = result + item["amount"]
    return result


def by_category(items):
    grouped = {}
    for item in items:
        grouped[item["category"]] = grouped.get(item["category"], 0) + item["amount"]
    return grouped


def over_budget(items, limit):
    return total(items) > limit


def average(items):
    if not items:
        return 0
    return total(items) / len(items)


def month_key(day):
    return f"{day.year}-{day.month:02d}"


def monthly_total(items, month):
    selected = [i for i in items if i.get("month") == month]
    return total(selected)


def today_key():
    return month_key(date.today())
''',
    },
    "tests": {
        "test_ledger.py": '''import pytest
from app.ledger import (add_expense, total, by_category, over_budget, average,
                        month_key, monthly_total, load_config)
from datetime import date


def test_add_and_total():
    items = []
    add_expense(items, "tea", 10)
    add_expense(items, "lunch", 90.5)
    assert total(items) == 100.5


def test_rejects_bad_input():
    items = []
    with pytest.raises(ValueError):
        add_expense(items, "x", 0)
    with pytest.raises(ValueError):
        add_expense(items, "", 5)


def test_by_category_and_average():
    items = []
    add_expense(items, "a", 10, "food")
    add_expense(items, "b", 30, "food")
    add_expense(items, "c", 20, "rent")
    assert by_category(items) == {"food": 40, "rent": 20}
    assert average(items) == 20
    assert average([]) == 0


def test_over_budget():
    items = []
    add_expense(items, "a", 500)
    assert over_budget(items, 100)
    assert not over_budget(items, 1000)


def test_month_helpers():
    assert month_key(date(2026, 3, 9)) == "2026-03"
    items = [{"amount": 5, "month": "2026-03"}, {"amount": 7, "month": "2026-04"}]
    assert monthly_total(items, "2026-03") == 5


def test_config_loads():
    assert load_config()["currency"] == "INR"
''',
    },
}

# ---------------------------------------------------------------- inventory
SERVICES["inventory"] = {
    "files": {
        "app/__init__.py": "",
        "app/config.json": '{\n  "low_stock_threshold": 5,\n  "warehouse": "BLR-1"\n}\n',
        "app/stock.py": '''"""Inventory stock rules."""
import json
from pathlib import Path

CONFIG = Path(__file__).with_name("config.json")


def threshold():
    return json.loads(CONFIG.read_text(encoding="utf-8"))["low_stock_threshold"]


def add_stock(stock, sku, qty):
    if qty <= 0:
        raise ValueError("quantity must be positive")
    stock[sku] = stock.get(sku, 0) + qty
    return stock[sku]


def remove_stock(stock, sku, qty):
    if sku not in stock:
        raise KeyError(sku)
    if qty > stock[sku]:
        raise ValueError("insufficient stock")
    stock[sku] = stock[sku] - qty
    return stock[sku]


def low_stock(stock, limit):
    return sorted(sku for sku, qty in stock.items() if qty < limit)


def reorder_quantity(target, current):
    if current >= target:
        return 0
    return target - current


def total_value(prices, stock):
    value = 0
    for sku, qty in stock.items():
        value = value + prices[sku] * qty
    return value


def apply_discount(price, percent):
    if percent < 0 or percent > 100:
        raise ValueError("percent out of range")
    return round(price * (1 - percent / 100), 2)
''',
    },
    "tests": {
        "test_stock.py": '''import pytest
from app.stock import (add_stock, remove_stock, low_stock, reorder_quantity,
                       total_value, apply_discount, threshold)


def test_add_and_remove():
    stock = {}
    add_stock(stock, "A", 10)
    assert remove_stock(stock, "A", 4) == 6
    assert stock["A"] == 6


def test_remove_errors():
    stock = {"A": 2}
    with pytest.raises(ValueError):
        remove_stock(stock, "A", 9)
    with pytest.raises(KeyError):
        remove_stock(stock, "Z", 1)
    with pytest.raises(ValueError):
        add_stock(stock, "A", 0)


def test_low_stock():
    assert low_stock({"A": 1, "B": 50, "C": 3}, 5) == ["A", "C"]


def test_reorder_quantity():
    assert reorder_quantity(20, 5) == 15
    assert reorder_quantity(10, 30) == 0


def test_value_and_discount():
    assert total_value({"A": 10, "B": 2}, {"A": 3, "B": 4}) == 38
    assert apply_discount(200, 25) == 150
    with pytest.raises(ValueError):
        apply_discount(100, 120)


def test_threshold_config():
    assert threshold() == 5
''',
    },
}

# ---------------------------------------------------------------- authentication
SERVICES["authentication"] = {
    "files": {
        "app/__init__.py": "",
        "app/config.json": '{\n  "max_attempts": 5,\n  "session_ttl_seconds": 3600\n}\n',
        "app/auth.py": '''"""Credential and session rules."""
import hashlib
import json
from pathlib import Path

CONFIG = Path(__file__).with_name("config.json")


def settings():
    return json.loads(CONFIG.read_text(encoding="utf-8"))


def hash_password(password, salt):
    return hashlib.sha256((salt + password).encode("utf-8")).hexdigest()


def verify_password(password, salt, digest):
    return hash_password(password, salt) == digest


def password_strength(password):
    score = 0
    if len(password) >= 8:
        score = score + 1
    if any(c.isdigit() for c in password):
        score = score + 1
    if any(c.isupper() for c in password):
        score = score + 1
    if any(not c.isalnum() for c in password):
        score = score + 1
    return score


def is_locked(attempts, max_attempts):
    return attempts >= max_attempts


def session_expired(created, now, ttl):
    return now - created > ttl


def remaining_attempts(attempts, max_attempts):
    return max(max_attempts - attempts, 0)
''',
    },
    "tests": {
        "test_auth.py": '''from app.auth import (hash_password, verify_password, password_strength, is_locked,
                      session_expired, remaining_attempts, settings)


def test_hash_roundtrip():
    digest = hash_password("secret", "salt")
    assert verify_password("secret", "salt", digest)
    assert not verify_password("wrong", "salt", digest)


def test_salt_changes_digest():
    assert hash_password("x", "a") != hash_password("x", "b")


def test_strength_scale():
    assert password_strength("abc") == 0
    assert password_strength("Abcdefg1!") == 4


def test_lockout():
    assert is_locked(7, 5)
    assert not is_locked(1, 5)
    assert remaining_attempts(2, 5) == 3


def test_session_expiry():
    assert session_expired(0, 5000, 3600)
    assert not session_expired(0, 100, 3600)


def test_settings():
    assert settings()["max_attempts"] == 5
''',
    },
}

# ---------------------------------------------------------------- notification worker
SERVICES["notification-worker"] = {
    "files": {
        "app/__init__.py": "",
        "app/config.json": '{\n  "max_attempts": 4,\n  "base_delay_seconds": 2,\n  "batch_size": 10\n}\n',
        "app/worker.py": '''"""Notification queue rules."""
import json
from pathlib import Path

CONFIG = Path(__file__).with_name("config.json")


def settings():
    return json.loads(CONFIG.read_text(encoding="utf-8"))


def enqueue(queue, message, priority=5):
    if priority < 1:
        raise ValueError("priority must be >= 1")
    queue.append((priority, message))
    return len(queue)


def next_message(queue):
    if not queue:
        return None
    best = min(range(len(queue)), key=lambda i: queue[i][0])
    return queue.pop(best)[1]


def retry_delay(attempt, base):
    return base * (2 ** attempt)


def should_retry(attempt, max_attempts):
    return attempt < max_attempts


def render(template, **values):
    return template.format(**values)


def batches(messages, size):
    return [messages[i:i + size] for i in range(0, len(messages), size)]
''',
    },
    "tests": {
        "test_worker.py": '''import pytest
from app.worker import (enqueue, next_message, retry_delay, should_retry, render,
                        batches, settings)


def test_priority_order():
    queue = []
    enqueue(queue, "low", 9)
    enqueue(queue, "high", 1)
    assert next_message(queue) == "high"
    assert next_message(queue) == "low"
    assert next_message(queue) is None


def test_enqueue_validation():
    with pytest.raises(ValueError):
        enqueue([], "x", 0)


def test_backoff():
    assert retry_delay(0, 2) == 2
    assert retry_delay(3, 2) == 16


def test_should_retry():
    assert should_retry(1, 4)
    assert not should_retry(9, 4)


def test_render_and_batches():
    assert render("Hi {name}", name="Prem") == "Hi Prem"
    assert batches([1, 2, 3, 4, 5], 2) == [[1, 2], [3, 4], [5]]


def test_settings():
    assert settings()["batch_size"] == 10
''',
    },
}
