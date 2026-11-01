from pydantic import BaseModel, Field


class Address(BaseModel):
    street: str
    city: str
    zip: str
    country: str = Field(min_length=2, max_length=2)


class Card(BaseModel):
    number: str
    cvv: str
    exp_month: int
    exp_year: int


class OrderRequest(BaseModel):
    user_id: str
    email: str = Field(pattern=r"^[^@\s]+@[^@\s]+$")
    address: Address
    card: Card


class OrderLine(BaseModel):
    product_id: str
    name: str
    quantity: int
    unit_price_cents: int


class Order(BaseModel):
    order_id: str
    user_id: str
    email: str
    address: Address
    lines: list[OrderLine]
    subtotal_cents: int
    shipping_cents: int
    total_cents: int
    transaction_id: str
