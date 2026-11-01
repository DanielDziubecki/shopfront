"""Simulated shoppers: browse, look at products, fill carts and check out."""

import random
import uuid

from locust import FastHttpUser, between, task

PRODUCTS = [
    "TENT-2P", "TENT-4P", "BAG-0C", "PAD-AIR", "STOVE-CAN", "POT-MOKA",
    "LAMP-HEAD", "PACK-45", "PACK-20", "POLE-CARB", "FILTER-SQZ", "JACKET-RAIN",
]  # fmt: skip
CATEGORIES = ["camping", "hiking", "kitchen", "sleep", "clothing"]

# Test card numbers (Luhn-valid, never real).
CARDS = [
    "4111115260181593", "4111110830166133", "4111111860913907", "4111119960308241",
    "5555556281948215", "6011119935181901", "4012889378657971", "5200825432319488",
    "4000007574911860", "2223002527601895",
]  # fmt: skip

ADDRESSES = [
    {"street": "1600 Amphitheatre Pkwy", "city": "Mountain View", "zip": "94043", "country": "US"},
    {"street": "221B Baker Street", "city": "London", "zip": "NW1 6XE", "country": "GB"},
    {"street": "Unter den Linden 77", "city": "Berlin", "zip": "10117", "country": "DE"},
    {"street": "ul. Marszalkowska 1", "city": "Warszawa", "zip": "00-624", "country": "PL"},
    {"street": "100 Queen St W", "city": "Toronto", "zip": "M5H 2N2", "country": "CA"},
]


class Shopper(FastHttpUser):
    wait_time = between(1, 4)

    def on_start(self) -> None:
        self.session_id = f"s-{uuid.uuid4().hex[:12]}"
        self.headers = {"x-session-id": self.session_id}

    @task(2)
    def home(self) -> None:
        self.client.get("/")

    @task(1)
    def browse_category(self) -> None:
        self.client.get(f"/api/products?category={random.choice(CATEGORIES)}")

    @task(6)
    def view_product(self) -> None:
        product = random.choice(PRODUCTS)
        self.client.get(f"/api/products/{product}", headers=self.headers, name="/api/products/[id]")

    @task(3)
    def add_to_cart(self) -> None:
        product = random.choice(PRODUCTS)
        self.client.get(f"/api/products/{product}", headers=self.headers, name="/api/products/[id]")
        self.client.post(
            "/api/cart",
            json={"product_id": product, "quantity": random.randint(1, 3)},
            headers=self.headers,
        )

    @task(1)
    def view_cart(self) -> None:
        self.client.get("/api/cart", headers=self.headers)

    @task(1)
    def checkout(self) -> None:
        self.add_to_cart()
        self.client.post(
            "/api/checkout",
            json={
                "email": f"{self.session_id}@example.com",
                "address": random.choice(ADDRESSES),
                "card": {
                    "number": random.choice(CARDS),
                    "cvv": "123",
                    "exp_month": random.randint(1, 12),
                    "exp_year": 2030,
                },
            },
            headers=self.headers,
        )
