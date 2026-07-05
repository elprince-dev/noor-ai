import time
import json
from typing import List

import boto3
from langchain_core.chat_history import BaseChatMessageHistory
from langchain_core.messages import BaseMessage, messages_from_dict, message_to_dict

from src.config import config


class DynamoDBChatHistory(BaseChatMessageHistory):
    """Persistent chat history backed by DynamoDB.

    Each message is stored as a separate item with a sort key (MessageIndex)
    to maintain ordering. TTL ensures automatic cleanup of old sessions.
    """

    def __init__(self, session_id: str):
        self._session_id = session_id
        self._table = boto3.resource("dynamodb").Table(config.chat_table)

    @property
    def messages(self) -> List[BaseMessage]:
        """Retrieve all messages for this session, ordered by index."""
        response = self._table.query(
            KeyConditionExpression="SessionId = :sid",
            ExpressionAttributeValues={":sid": self._session_id},
            ScanIndexForward=True,
        )
        messages: List[BaseMessage] = []
        for item in response.get("Items", []):
            msg_data = json.loads(item["MessageData"])
            messages.extend(messages_from_dict([msg_data]))
        return messages

    def add_message(self, message: BaseMessage) -> None:
        """Append a message to the session history."""
        count_response = self._table.query(
            KeyConditionExpression="SessionId = :sid",
            ExpressionAttributeValues={":sid": self._session_id},
            Select="COUNT",
        )
        ttl = int(time.time()) + (config.session_ttl_hours * 3600)

        self._table.put_item(
            Item={
                "SessionId": self._session_id,
                "MessageIndex": count_response["Count"],
                "MessageData": json.dumps(message_to_dict(message)),
                "Timestamp": int(time.time()),
                "TTL": ttl,
            }
        )

    def clear(self) -> None:
        """Delete all messages for this session."""
        response = self._table.query(
            KeyConditionExpression="SessionId = :sid",
            ExpressionAttributeValues={":sid": self._session_id},
            ProjectionExpression="SessionId, MessageIndex",
        )
        with self._table.batch_writer() as batch:
            for item in response.get("Items", []):
                batch.delete_item(
                    Key={
                        "SessionId": item["SessionId"],
                        "MessageIndex": item["MessageIndex"],
                    }
                )


class MemoryService:
    """Factory for chat history instances."""

    @staticmethod
    def get_history(session_id: str) -> DynamoDBChatHistory:
        """Create a chat history instance for the given session."""
        return DynamoDBChatHistory(session_id=session_id)
