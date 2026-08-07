"""Feedback persistence in the DynamoDB feedback table (Req 11.3, 11.5, 12.2).

`FeedbackRepository` keeps persistence swappable — property tests use an
in-memory fake. `DynamoFeedbackRepository` is the single feedback-table
gateway for both the write side (Feedback API) and the read side (triage).

The boto3 Table resource is created lazily on first use so importing this
module (and constructing the repository) needs no AWS credentials.
"""
from typing import Any, Mapping, Protocol, cast

import boto3
from boto3.dynamodb.conditions import Key

from src.feedback.models import FeedbackRecord, Rating


class FeedbackRepository(Protocol):
    """Persists and lists feedback records keyed by Request_ID."""

    def put(self, record: FeedbackRecord) -> None: ...

    def list_down_rated(self) -> list[FeedbackRecord]: ...


class DynamoFeedbackRepository:
    """Feedback store backed by the DynamoDB feedback table.

    Items are `{RequestId, Rating, FeedbackAt, Comment?}` — `RequestId` is
    the partition key, and (`Rating`, `FeedbackAt`) form the `RatingIndex`
    GSI used by triage. PutItem is an unconditional overwrite so a repeat
    rating for the same Request_ID is last-write-wins (Req 11.5).
    """

    def __init__(self, table_name: str) -> None:
        self._table_name = table_name
        self._table = None  # lazy: no AWS touch until first put/query

    def _get_table(self):
        if self._table is None:
            self._table = boto3.resource("dynamodb").Table(self._table_name)
        return self._table

    def put(self, record: FeedbackRecord) -> None:
        """PutItem keyed by RequestId — unconditional overwrite (Req 11.3, 11.5)."""
        item: dict[str, Any] = {
            "RequestId": record.request_id,
            "Rating": record.rating,
            "FeedbackAt": record.feedback_at,
        }
        if record.comment is not None:
            item["Comment"] = record.comment
        self._get_table().put_item(Item=item)

    def list_down_rated(self) -> list[FeedbackRecord]:
        """Query RatingIndex for down ratings, newest-first (Req 12.2).

        `FeedbackAt` is the index sort key, so ScanIndexForward=False yields
        descending timestamp order. Paginates through the full result set.
        """
        table = self._get_table()
        records: list[FeedbackRecord] = []
        kwargs: dict[str, Any] = {
            "IndexName": "RatingIndex",
            "KeyConditionExpression": Key("Rating").eq("down"),
            "ScanIndexForward": False,
        }
        while True:
            response = table.query(**kwargs)
            records.extend(_record_from_item(item) for item in response.get("Items", []))
            last_key = response.get("LastEvaluatedKey")
            if not last_key:
                return records
            kwargs["ExclusiveStartKey"] = last_key


def _record_from_item(item: Mapping[str, Any]) -> FeedbackRecord:
    return FeedbackRecord(
        request_id=str(item["RequestId"]),
        rating=cast(Rating, str(item["Rating"])),
        feedback_at=str(item["FeedbackAt"]),
        comment=None if item.get("Comment") is None else str(item["Comment"]),
    )
