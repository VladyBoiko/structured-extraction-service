"""Output schema: what the model extracts from one support ticket.

13 top-level fields, 6 enums and a `products` list of nested objects.
"""
from enum import Enum

from pydantic import BaseModel, ConfigDict, Field


class Category(str, Enum):
    """What the problem is about. What the customer wants done is `RequestedAction`."""

    order_status = "order_status"
    order_change = "order_change"
    delivery = "delivery"
    payment = "payment"
    product_defect = "product_defect"
    usage_help = "usage_help"
    product_question = "product_question"
    account = "account"
    other = "other"


class Priority(str, Enum):
    low = "low"
    medium = "medium"
    high = "high"
    urgent = "urgent"


class Sentiment(str, Enum):
    negative = "negative"
    neutral = "neutral"
    positive = "positive"


class Language(str, Enum):
    en = "en"
    uk = "uk"
    de = "de"
    mixed = "mixed"


class RequestedAction(str, Enum):
    refund = "refund"
    replacement = "replacement"
    repair = "repair"
    cancellation = "cancellation"
    information = "information"
    other = "other"
    none = "none"


class ProductCategory(str, Enum):
    smartphone = "smartphone"
    laptop = "laptop"
    tv = "tv"
    headphones = "headphones"
    tablet = "tablet"
    appliance = "appliance"
    accessory = "accessory"
    other = "other"
    unknown = "unknown"


class Product(BaseModel):
    """Nested object: one product the ticket is about."""

    model_config = ConfigDict(extra="forbid")

    name: str | None = Field(description="Product name or model as written by the customer, or null if not mentioned.")
    category: ProductCategory = Field(description="Type of product; 'unknown' if it cannot be determined.")


class TicketExtraction(BaseModel):
    model_config = ConfigDict(extra="forbid")

    category: Category = Field(
        description="What the problem is about (not what the customer wants; that is requested_action).")
    priority: Priority = Field(description="How urgent the ticket is.")
    sentiment: Sentiment = Field(description="Customer's attitude.")
    language: Language = Field(description="Language of the ticket text.")
    requested_action: RequestedAction = Field(description="What the customer wants us to do.")
    needs_human: bool = Field(description="True if a support agent must act; false if an automatic answer is enough.")
    escalation_threat: bool = Field(
        description="True if the customer threatens a complaint, legal action, a chargeback or a public review.")
    repeat_contact: bool = Field(
        description="True if the customer says they already contacted support about this issue before.")
    deadline: str | None = Field(
        description="Time limit the customer states (e.g. 'tomorrow noon', 'by Friday'), as written; null if none.")
    tracking_number: str | None = Field(
        description="Parcel tracking number if mentioned, or null. Never the order number.")
    order_id: str | None = Field(description="Order number in the form ES-12345, or null if not mentioned.")
    summary: str = Field(min_length=1, max_length=200, description="One short sentence in English.")
    products: list[Product] = Field(
        description="Every product the ticket is about, one entry per distinct product; empty if none is mentioned.")


def _resolve(node, defs):
    """Inline $ref so the schema is self-contained (every provider handles that reliably)."""
    if isinstance(node, dict):
        if "$ref" in node:
            name = node["$ref"].split("/")[-1]
            extra = {k: v for k, v in node.items() if k != "$ref"}
            return _resolve({**defs[name], **extra}, defs)
        return {k: _resolve(v, defs) for k, v in node.items() if k not in ("$defs", "title")}
    if isinstance(node, list):
        return [_resolve(v, defs) for v in node]
    return node


def json_schema() -> dict:
    """JSON Schema for structured output (sent to both the cloud and the local model)."""
    raw = TicketExtraction.model_json_schema()
    return _resolve(raw, raw.get("$defs", {}))
